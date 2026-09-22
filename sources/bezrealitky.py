"""Bezrealitky.cz source adapter.

Like Sreality, the site is a Next.js app; search results are dehydrated into
`__NEXT_DATA__` under props.pageProps.apolloCache as `Advert:<id>` objects
(Apollo's normalized cache). We read them straight from there — no GraphQL POST.

We fetch the Karlovarský-kraj sale listing, paginate, then filter client-side
by disposition / price / GPS radius (radius applied later in the pipeline).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Optional

from config import BEZREALITKY_KRAJ, DISPOSITIONS, MAX_PRICE_CZK, PROPERTY_TYPES
from models import Listing

# Bezrealitky URL uses singular category slugs (no chaty category on this portal).
_PROP_SLUGS = {
    "byty": "byt",
    "domy": "dum",
}
LIST_ROOT = "https://www.bezrealitky.cz/vypis/nabidka-prodej"
DETAIL = "https://www.bezrealitky.cz/nemovitosti-byty-domy"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
PER_PAGE = 15

_NEXT_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


class SourceError(RuntimeError):
    """Raised when Bezrealitky is unreachable or its payload shape changed."""


def _disposition(enum: Optional[str]) -> str:
    """DISP_3_KK -> '3+kk', DISP_3_1 -> '3+1'."""
    if not isinstance(enum, str) or not enum.startswith("DISP_"):
        return ""
    body = enum[5:]
    if "_" not in body:
        return body
    rooms, kind = body.split("_", 1)
    return f"{rooms}+{'kk' if kind.upper() == 'KK' else kind}"


def _get_next_data(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "cs-CZ,cs;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise SourceError(f"Bezrealitky HTTP {e.code} for {url}") from e
    except Exception as e:
        raise SourceError(f"Bezrealitky fetch failed for {url}: {e}") from e
    m = _NEXT_RE.search(html)
    if not m:
        raise SourceError(
            f"Bezrealitky: __NEXT_DATA__ not found at {url} (layout changed?)")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise SourceError(f"Bezrealitky: bad __NEXT_DATA__ JSON at {url}: {e}") from e


def _first_keyed(advert: dict, prefix: str):
    """Apollo keys carry arg hashes, e.g. address({"locale":"CS"}). Match by prefix."""
    for k, v in advert.items():
        if k.startswith(prefix):
            return v
    return None


def _image_url(cache: dict, advert: dict) -> Optional[str]:
    main = advert.get("mainImage")
    if not (isinstance(main, dict) and main.get("__ref")):
        return None
    img = cache.get(main["__ref"]) or {}
    thumb = None
    for k, v in img.items():
        if k.startswith("url(") and isinstance(v, str):
            if "record_thumb" in v.lower():
                return v
            thumb = thumb or v
    return thumb


def _to_listing(cache: dict, a: dict) -> Optional[Listing]:
    if not isinstance(a, dict) or "id" not in a:
        return None
    disp = _disposition(a.get("disposition"))
    price = a.get("price")
    gps = a.get("gps") or {}
    lat, lng = gps.get("lat"), gps.get("lng")
    surface = a.get("surface")
    address = _first_keyed(a, "address(") or ""
    alt = _first_keyed(a, "imageAltText(")
    uri = a.get("uri")

    return Listing(
        source="bezrealitky",
        listing_id=f"bezrealitky:{a['id']}",
        title=(alt or f"Prodej bytu {disp}").strip(),
        price_czk=int(price) if isinstance(price, (int, float)) else None,
        disposition=disp,
        area_m2=int(surface) if isinstance(surface, (int, float)) and surface else None,
        city=address,
        district="",
        url=f"{DETAIL}/{uri}" if uri else DETAIL,
        image_url=_image_url(cache, a),
        latitude=float(lat) if isinstance(lat, (int, float)) else None,
        longitude=float(lng) if isinstance(lng, (int, float)) else None,
    )


def _total_count(cache: dict) -> int:
    """Read totalCount from the main listAdverts query (ignore the discounted one)."""
    for v in cache.values():
        if not isinstance(v, dict):
            continue
        for key, val in v.items():
            if (key.startswith("listAdverts(")
                    and '"discountedOnly":true' not in key
                    and isinstance(val, dict) and "totalCount" in val):
                return val.get("totalCount") or 0
    return 0


def fetch_listings(verbose: bool = False) -> list[Listing]:
    """Fetch regional sale listings, filter to target disposition + budget.

    GPS radius is applied later by the pipeline. Fails gracefully per-page.
    """
    out: list[Listing] = []
    seen: set[str] = set()

    for prop in PROPERTY_TYPES:
        slug = _PROP_SLUGS.get(prop)
        if not slug:
            continue
        base = f"{LIST_ROOT}/{slug}/{BEZREALITKY_KRAJ}"
        page, total = 1, None

        while True:
            url = base + (f"?page={page}" if page > 1 else "")
            try:
                data = _get_next_data(url)
            except SourceError as e:
                if verbose:
                    print(f"  ! {e}")
                break

            cache = data.get("props", {}).get("pageProps", {}).get("apolloCache", {}) or {}
            if total is None:
                total = _total_count(cache)
            adverts = [v for k, v in cache.items() if k.startswith("Advert:")]
            if not adverts:
                break

            for a in adverts:
                try:
                    lst = _to_listing(cache, a)
                except Exception as e:
                    if verbose:
                        print(f"  ! skipping malformed advert: {e}")
                    continue
                if not lst or lst.listing_id in seen:
                    continue
                if DISPOSITIONS and lst.disposition not in DISPOSITIONS:
                    continue
                if (MAX_PRICE_CZK is not None and lst.price_czk is not None
                        and lst.price_czk > MAX_PRICE_CZK):
                    continue
                seen.add(lst.listing_id)
                out.append(lst)

            if not total or page * PER_PAGE >= total:
                break
            page += 1

    return out
