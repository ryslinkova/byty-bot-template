"""Daily orchestration.

Flow:  fetch all sources  ->  refine to radius  ->  keep only NEW  ->  email
Marks listings as seen ONLY after a successful send (or preview), so a delivery
failure doesn't drop them from tomorrow's run.

Usage:
  python3 main.py --dry-run   # build email to preview_email.html, do not send
  python3 main.py             # send via Gmail SMTP (needs env credentials)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env into os.environ (local dev only; CI uses GitHub Secrets)."""
    env_path = Path(__file__).with_name(".env")
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key:
            os.environ.setdefault(key, value)


_load_dotenv()

import dedup
import email_report
from config import CENTER_LAT, CENTER_LON, MIN_AREA_M2, RADIUS_KM
from geo import haversine_km
from models import Listing
from sources.bezrealitky import fetch_listings as fetch_bezrealitky
from sources.idnes import fetch_listings as fetch_idnes
from sources.sreality import fetch_listings as fetch_sreality

# Each source is isolated: one failing must not sink the others.
SOURCES = [
    ("sreality", fetch_sreality),
    ("bezrealitky", fetch_bezrealitky),
    ("idnes", fetch_idnes),
]


def collect() -> list[Listing]:
    all_listings: list[Listing] = []
    for name, fetch in SOURCES:
        try:
            found = fetch(verbose=True)
            print(f"  {name}: {len(found)} inzerátů")
            all_listings.extend(found)
        except Exception as e:  # never let one source kill the run
            print(f"  ! {name} selhalo, pokračuji bez něj: {e}")
    return all_listings


def within_radius(listings: list[Listing]) -> list[Listing]:
    kept = []
    for l in listings:
        if l.latitude is not None and l.longitude is not None:
            l.distance_km = round(
                haversine_km(CENTER_LAT, CENTER_LON, l.latitude, l.longitude), 1)
        if l.distance_km is None or l.distance_km <= RADIUS_KM:
            kept.append(l)
    return kept


def meets_min_area(listings: list[Listing]) -> list[Listing]:
    if MIN_AREA_M2 is None:
        return listings
    return [
        l for l in listings
        if l.area_m2 is None or l.area_m2 >= MIN_AREA_M2
    ]


# Same flat is often posted on multiple portals. Collapse exact matches on
# (disposition, area, price), keeping the no-commission source first.
SOURCE_PRIORITY = {"bezrealitky": 0, "sreality": 1, "idnes": 2}


def collapse_cross_source(listings: list[Listing]) -> list[Listing]:
    kept: list[Listing] = []
    # key -> sources already kept for it. Collapsing happens only ACROSS
    # portals: two listings on the same portal that happen to share
    # disposition/area/price are two different properties, not a cross-post.
    sources_per_key: dict[tuple, set[str]] = {}
    for l in sorted(listings, key=lambda x: SOURCE_PRIORITY.get(x.source, 9)):
        # only collapse when we have enough to be confident it's the same flat
        if l.area_m2 and l.price_czk:
            key = (l.disposition, l.area_m2, l.price_czk)
        else:
            key = (l.listing_id,)
        sources = sources_per_key.setdefault(key, set())
        if sources and l.source not in sources:
            continue
        sources.add(l.source)
        kept.append(l)
    return kept


def main(dry_run: bool = False) -> None:
    now = datetime.now()
    fetched = collect()
    near = within_radius(fetched)
    sized = meets_min_area(near)
    unique = collapse_cross_source(sized)
    new = dedup.filter_new(unique)
    area_note = f", min. {MIN_AREA_M2} m2" if MIN_AREA_M2 else ""
    print(f"\nCelkem: {len(fetched)} staženo · {len(near)} v okruhu {RADIUS_KM:.0f} km"
          f"{area_note} · {len(sized)} po filtru plochy · {len(unique)} unikátních · {len(new)} nových")

    if not new:
        print("Nic nového — e-mail se neposílá.")
        return

    subject = email_report.build_subject(new, now)
    html = email_report.build_html(new, now)

    if dry_run:
        path = email_report.write_preview(html)
        print(f"\nDRY-RUN: e-mail uložen do {path} (NEodesláno).")
        print(f"Předmět by byl: {subject}")
        return

    email_report.send_email(subject, html)
    added = dedup.mark_seen(new)
    print(f"\nE-mail odeslán ({subject}). Zapsáno {added} nových do dedup DB.")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
