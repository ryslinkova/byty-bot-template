"""Sreality.cz source adapter.

Sreality's old public JSON API (/api/cs/v2/estates) is decommissioned (nginx 404).
The current site is a Next.js app that server-renders search results into a
`__NEXT_DATA__` JSON blob (React Query dehydrated state). We fetch the public
search page — the same URL a browser hits — and read the `estatesSearch` results
out of that blob. No API key, no headless browser; plain HTTP + a regex.

URL grammar (verified live):
  base:        https://www.sreality.cz/hledani/{prodej|pronajem}/{byty|domy|chaty|pozemky}
  locality:    /{okres-slug}        e.g. /cheb  (in the path, one per request)
  disposition: ?velikost=3%2Bkk,3%2B1  (optional, byty only; ONE comma-separated param)
  max price:   &cena-do=5000000     (optional)
  pagination:  &strana=N
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.error
import urllib.request
from typing import Optional

from config import DISPOSITIONS, MAX_PRICE_CZK, OFFER_TYPE, OKRESY, PROPERTY_TYPES
from models import Listing

# Sreality search/detail path segments per property category.
# Cottages are searched under /chaty but their detail pages live under /dum.
_PROP_PATHS = {
    "byty": ("byty", "byt"),
    "domy": ("domy", "dum"),
    "chaty": ("chaty", "dum"),
    "pozemky": ("pozemky", "pozemek"),
}
SEARCH_ROOT = f"https://www.sreality.cz/hledani/{OFFER_TYPE}"
DETAIL_ROOT = f"https://www.sreality.cz/detail/{OFFER_TYPE}"

# priceUnitCb value for "za m²": Sreality lists land at a per-m² price in
# `priceCzk`; the whole price is then only in `priceSummaryCzk`.
_UNIT_PER_M2 = 3
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
PER_PAGE = 22

# CDN returns 401 without resize/format params; og:image uses this suffix.
_SDN_IMAGE_FL = "?fl=res,1200,1200,1|shr,,20|jpg,80"

_NEXT_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_AREA_RE = re.compile(r"(\d+)\s*m")  # pulls "50" out of "Prodej bytu 3+kk 50 m²"


class SourceError(RuntimeError):
    """Raised when Sreality is unreachable or its payload shape changed."""


def _velikost_qs() -> str:
    if not DISPOSITIONS:
        return ""
    # Sreality takes several sizes comma-separated in ONE parameter; a repeated
    # `velikost=` is silently reduced to the first value.
    return "velikost=" + ",".join(d.replace("+", "%2B") for d in DISPOSITIONS)


def _search_url(prop: str, okres: str, page: int) -> str:
    search_slug, _ = _PROP_PATHS[prop]
    url = f"{SEARCH_ROOT}/{search_slug}/{okres}"
    qs: list[str] = []
    if prop == "byty" and _velikost_qs():
        qs.append(_velikost_qs())
    if MAX_PRICE_CZK is not None:
        qs.append(f"cena-do={MAX_PRICE_CZK}")
    if page > 1:
        qs.append(f"strana={page}")
    if qs:
        url += "?" + "&".join(qs)
    return url


def _get_next_data(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "cs-CZ,cs;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise SourceError(f"Sreality HTTP {e.code} for {url}") from e
    except Exception as e:  # network / timeout / DNS
        raise SourceError(f"Sreality fetch failed for {url}: {e}") from e

    m = _NEXT_RE.search(html)
    if not m:
        raise SourceError(
            f"Sreality: __NEXT_DATA__ not found at {url} (page layout changed?)")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise SourceError(f"Sreality: bad __NEXT_DATA__ JSON at {url}: {e}") from e


def _extract_search(next_data: dict):
    """Return (results, pagination) from the dehydrated `estatesSearch` query."""
    pp = next_data.get("props", {}).get("pageProps", {})
    for q in pp.get("dehydratedState", {}).get("queries", []):
        key = q.get("queryKey")
        if isinstance(key, list) and key and key[0] == "estatesSearch":
            data = q.get("state", {}).get("data", {}) or {}
            return data.get("results", []) or [], data.get("pagination", {}) or {}
    return [], {}


def _disp_slug(disp: str) -> str:
    """Disposition as it appears in a detail URL.

    Flats come through as "3+kk" and pass unchanged; houses and cottages come as
    words ("Rodinny", "Zemedelska usedlost") that the URL wants lowercased,
    without diacritics and dash-separated — otherwise the link 404s.
    """
    ascii_only = (unicodedata.normalize("NFKD", disp)
                  .encode("ascii", "ignore").decode())
    return "-".join(ascii_only.lower().split())


def _detail_url(item: dict, disp_slug: str, detail_slug: str) -> str:
    loc = item.get("locality") or {}
    city = loc.get("citySeoName") or loc.get("municipalitySeoName") or "x"
    part = loc.get("cityPartSeoName") or city
    return f"{DETAIL_ROOT}/{detail_slug}/{disp_slug}/{city}-{part}/{item['id']}"


def _image_url(raw: str) -> str:
    url = ("https:" + raw) if raw.startswith("//") else raw
    if "sdn.cz" in url and "fl=" not in url:
        url += _SDN_IMAGE_FL
    return url


def _parse_item(item: dict, detail_slug: str) -> Optional[Listing]:
    """Map one Sreality result dict to a Listing. Returns None if unusable."""
    if not isinstance(item, dict) or "id" not in item:
        return None

    loc = item.get("locality") or {}
    sub = item.get("categorySubCb") or {}
    disp = sub.get("name") if isinstance(sub, dict) else None

    unit = item.get("priceUnitCb")
    per_m2 = isinstance(unit, dict) and unit.get("value") == _UNIT_PER_M2
    price = None if per_m2 else item.get("priceCzk")
    if not isinstance(price, (int, float)):
        price = item.get("priceSummaryCzk")

    name = (item.get("name") or "").replace("\xa0", " ").strip()
    area = None
    mm = _AREA_RE.search(name)
    if mm:
        area = int(mm.group(1))

    lat, lon = loc.get("latitude"), loc.get("longitude")

    img = None
    images = item.get("images") or []
    if images and isinstance(images[0], dict) and images[0].get("url"):
        img = _image_url(images[0]["url"])

    return Listing(
        source="sreality",
        listing_id=f"sreality:{item['id']}",
        title=name or "Nemovitost",
        price_czk=int(price) if isinstance(price, (int, float)) else None,
        disposition=disp or "",
        area_m2=area,
        city=loc.get("city") or loc.get("municipality") or "",
        district=loc.get("district") or "",
        url=_detail_url(item, _disp_slug(disp or ""), detail_slug),
        image_url=img,
        latitude=float(lat) if isinstance(lat, (int, float)) else None,
        longitude=float(lon) if isinstance(lon, (int, float)) else None,
    )


def fetch_listings(verbose: bool = False) -> list[Listing]:
    """Fetch all matching listings across configured okresy. Deduped by id.

    Fails gracefully: if one okres errors out, the others still return.
    """
    out: list[Listing] = []
    seen: set[str] = set()

    for prop in PROPERTY_TYPES:
        if prop not in _PROP_PATHS:
            if verbose:
                print(f"  ! Sreality: neznámý typ {prop!r}, přeskakuji")
            continue
        _, detail_slug = _PROP_PATHS[prop]
        for okres in OKRESY:
            page = 1
            while True:
                url = _search_url(prop, okres, page)
                try:
                    results, pagination = _extract_search(_get_next_data(url))
                except SourceError as e:
                    if verbose:
                        print(f"  ! {e}")
                    break  # skip this okres, keep the rest

                for it in results:
                    try:
                        lst = _parse_item(it, detail_slug)
                    except Exception as e:  # one bad item must not kill the batch
                        if verbose:
                            print(f"  ! skipping malformed item: {e}")
                        lst = None
                    if lst and lst.listing_id not in seen:
                        lst.offer, lst.property_type = OFFER_TYPE, prop
                        if (prop == "byty" and DISPOSITIONS
                                and lst.disposition not in DISPOSITIONS):
                            continue
                        if (MAX_PRICE_CZK is not None and lst.price_czk is not None
                                and lst.price_czk > MAX_PRICE_CZK):
                            continue
                        seen.add(lst.listing_id)
                        out.append(lst)

                total = pagination.get("total") or 0
                if not results or page * PER_PAGE >= total:
                    break
                page += 1

    return out
