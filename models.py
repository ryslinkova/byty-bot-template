"""Normalized listing model shared across all sources (Sreality, Bezrealitky, iDNES)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Listing:
    source: str                      # "sreality" | "bezrealitky" | "idnes"
    listing_id: str                  # globally unique, source-prefixed (dedup key)
    title: str
    price_czk: Optional[int]         # sale price, or monthly rent, as listed
    disposition: str                 # "3+kk" / "3+1"; for land the kind ("pole")
    area_m2: Optional[int]          # usable area; for land the plot area
    city: str
    district: str
    url: str
    image_url: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    charges_czk: Optional[int] = None       # monthly fees on top of rent, if exposed
    distance_km: Optional[float] = None     # from search center, filled by pipeline
    has_balcony: Optional[bool] = None      # None = unknown (not in list payload)
    has_parking: Optional[bool] = None
    offer: str = "prodej"                   # "prodej" | "pronajem"
    property_type: str = "byty"             # "byty" | "domy" | "chaty" | "pozemky"
