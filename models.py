"""Normalized listing model shared across all sources (Sreality, Bezrealitky, iDNES)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Listing:
    source: str                      # "sreality" | "bezrealitky" | "idnes"
    listing_id: str                  # globally unique, source-prefixed (dedup key)
    title: str
    price_czk: Optional[int]         # sale price as listed
    disposition: str                 # "3+kk" / "3+1"
    area_m2: Optional[int]
    city: str
    district: str
    url: str
    image_url: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    charges_czk: Optional[int] = None       # extra fees if exposed (legacy field)
    distance_km: Optional[float] = None     # from search center, filled by pipeline
    has_balcony: Optional[bool] = None      # None = unknown (not in list payload)
    has_parking: Optional[bool] = None
