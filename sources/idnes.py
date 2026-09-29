"""iDNES Reality source adapter (best-effort).

reality.idnes.cz is server-rendered but bot-protected: a request without a full
browser header set gets a "Robot" challenge page. With proper headers it serves
normal HTML, which we parse with regex.

Unlike Sreality/Bezrealitky, iDNES listings carry NO coordinates, so we can't do
a precise radius. We fetch the relevant okres pages and keep only listings whose
town is in TOWNS_NEAR (config) — a static allowlist approximating the target area.
Disposition, area, locality and price are parsed from the card title.
"""

from __future__ import annotations

import http.client
import re
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Iterator

from config import DISPOSITIONS, IDNES_OKRESY, MAX_PRICE_CZK, PROPERTY_TYPES, TOWNS_NEAR
from models import Listing

SEARCH_ROOT = "https://reality.idnes.cz/s/prodej"
MAX_PAGES = 20  # safety cap per okres; paging usually ends much sooner

# iDNES path segment per config property category (cottages live under a
# combined "chaty-chalupy" listing; /chaty alone is a 404).
_PROP_PATHS = {"byty": "byty", "domy": "domy", "chaty": "chaty-chalupy"}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
    "Referer": "https://reality.idnes.cz/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

_HREF_RE = re.compile(
    r'href="(https://reality\.idnes\.cz/detail/prodej/(?:byt|dum|chata)/[^"]+)"')
_DISP_RE = re.compile(r"(\d\+(?:kk|\d))", re.I)
_AREA_RE = re.compile(r"(\d+)\s*m²")
_PRICE_RE = re.compile(r"([\d\s ]+)\s*Kč")
# Locality sits between the LAST "m²" and the price (houses list two areas:
# "domu 120 m² s pozemkem 900 m² Obec, okres X").
_LOC_RE = re.compile(r"m²\s*((?:(?!m²).)+?)\s+[\d ][\d\s ]*Kč")
_OKRES_RE = re.compile(r",?\s*okres\s.*$", re.I)
_ID_RE = re.compile(
    r"/detail/prodej/(?:byt|dum|chata)/[^/]+/([0-9a-fA-F]+)")


class SourceError(RuntimeError):
    """Raised when a single iDNES page fails to load."""


class BotChallenge(SourceError):
    """iDNES served the robot-challenge page — further pages will fail too."""


class NoSuchPage(SourceError):
    """Paged past the last result page; iDNES answers those with a 404."""


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


_NEAR = {_norm(t) for t in TOWNS_NEAR}


def _is_near(locality: str) -> bool:
    """True if any allowlisted town appears as a whole token in the locality.

    The trailing ", okres X" is dropped first — otherwise "Milevsko, okres Písek"
    would match "Písek" and the whole district would slip through.
    """
    padded = f" {_norm(_OKRES_RE.sub('', locality))} "
    return any(f" {town} " in padded for town in _NEAR)


# A truncated response still carries whole listing cards, so anything above this
# is parsed instead of thrown away. (A page of results is ~130 kB.)
_MIN_USABLE_BYTES = 20_000


def _fetch(url: str, attempt: int = 1) -> str:
    # iDNES resets the connection on rapid sequential requests; retry once politely.
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", "replace")
    except http.client.IncompleteRead as e:
        # iDNES regularly cuts a response short mid-stream. The part that did
        # arrive is valid HTML with listings in it — use it rather than lose
        # the whole page.
        if len(e.partial) >= _MIN_USABLE_BYTES:
            html = e.partial.decode("utf-8", "replace")
        elif attempt < 2:
            time.sleep(1.5)
            return _fetch(url, attempt + 1)
        else:
            raise SourceError(
                f"iDNES sent only {len(e.partial)} B for {url}") from e
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NoSuchPage(f"iDNES has no page {url}") from e
        raise SourceError(f"iDNES HTTP {e.code} for {url}") from e
    except Exception as e:
        if attempt < 2:
            time.sleep(1.5)
            return _fetch(url, attempt + 1)
        raise SourceError(f"iDNES fetch failed for {url}: {e}") from e
    if re.search(r"<title>\s*Robot", html):
        raise BotChallenge(f"iDNES served bot-challenge page for {url}")
    return html


def _parse_cards(html: str) -> Iterator[Listing]:
    for block in html.split('class="c-products__item"')[1:]:
        ti = block.find("c-products__title")
        if ti == -1:
            continue
        # Skip past the rest of the opening tag, otherwise the class name itself
        # ends up in the title once the tags are stripped.
        tag_end = block.find(">", ti)
        start = tag_end + 1 if tag_end != -1 else ti
        seg = re.sub(r"<[^>]+>", " ", block[start:start + 500])
        seg = re.sub(r"[\s ]+", " ", seg).strip()

        href_m = _HREF_RE.search(block)
        disp_m = _DISP_RE.search(seg)
        if not href_m:
            continue
        url = href_m.group(1)
        id_m = _ID_RE.search(url)
        if not id_m:
            continue

        disp = disp_m.group(1).lower() if disp_m else ""
        area_m = _AREA_RE.search(seg)
        price_m = _PRICE_RE.search(seg)
        loc_m = _LOC_RE.search(seg)
        price = None
        if price_m:
            digits = re.sub(r"\D", "", price_m.group(1))
            price = int(digits) if digits else None
        area = int(area_m.group(1)) if area_m else None
        locality = loc_m.group(1).strip() if loc_m else ""

        yield Listing(
            source="idnes",
            listing_id=f"idnes:{id_m.group(1)}",
            title=seg[:120] if seg else "Nemovitost k prodeji",
            price_czk=price,
            disposition=disp,
            area_m2=area,
            city=locality,
            district="",
            url=url,
            image_url=None,
            latitude=None,
            longitude=None,
        )


def fetch_listings(verbose: bool = False) -> list[Listing]:
    """Fetch iDNES okres pages, keep target disposition + price + near towns."""
    out: list[Listing] = []
    seen: set[str] = set()

    for prop in PROPERTY_TYPES:
        search_slug = _PROP_PATHS.get(prop)
        if search_slug is None:
            if verbose:
                print(f"  ! iDNES: neznámý typ {prop!r}, přeskakuji")
            continue
        for okres in IDNES_OKRESY:
            # Paging is 0-indexed and the first page carries no ?page (the
            # newest listings live there). Past the last page iDNES serves the
            # last page again instead of a 404, so we stop on a page that
            # brings no id we haven't already seen in this okres.
            ids_in_okres: set[str] = set()
            for page in range(MAX_PAGES):
                if out or page > 0:
                    time.sleep(0.7)  # be polite; avoids connection resets
                url = f"{SEARCH_ROOT}/{search_slug}/{okres}/"
                if page:
                    url += f"?page={page}"
                try:
                    html = _fetch(url)
                except NoSuchPage:
                    break  # ran out of result pages, nothing is missing
                except BotChallenge as e:
                    if verbose:
                        print(f"  ! {e}")
                    break  # the whole okres is blocked, no point paging on
                except SourceError as e:
                    # A single flaky page must not cost us the rest of the okres.
                    if verbose:
                        print(f"  ! {e} — pokračuji další stranou")
                    continue

                cards = list(_parse_cards(html))
                page_ids = {c.listing_id for c in cards}
                if not page_ids - ids_in_okres:
                    break
                ids_in_okres |= page_ids

                for lst in cards:
                    if lst.listing_id in seen:
                        continue
                    if DISPOSITIONS and lst.disposition not in DISPOSITIONS:
                        continue
                    if (MAX_PRICE_CZK is not None and lst.price_czk is not None
                            and lst.price_czk > MAX_PRICE_CZK):
                        continue
                    if not _is_near(lst.city):
                        continue
                    seen.add(lst.listing_id)
                    out.append(lst)

                if page == MAX_PAGES - 1 and verbose:
                    print(f"  i iDNES {search_slug}/{okres}: dosažen strop {MAX_PAGES} stran "
                          f"(další výsledky mohou být vynechány)")

    return out
