"""Tests for geo, dedup and cross-source collapse. Offline, no network."""

import tempfile
import unittest
from pathlib import Path

import dedup
from config import MIN_AREA_M2
from geo import haversine_km
from main import collapse_cross_source, meets_min_area
from models import Listing


def _mk(source="sreality", lid="x", price=3_500_000, disp="3+kk", area=60):
    return Listing(source=source, listing_id=f"{source}:{lid}", title="t",
                   price_czk=price, disposition=disp, area_m2=area, city="Cheb",
                   district="", url="http://x", image_url=None,
                   latitude=None, longitude=None)


class TestGeo(unittest.TestCase):
    def test_same_point_is_zero(self):
        self.assertEqual(round(haversine_km(49.0, 14.0, 49.0, 14.0), 6), 0.0)

    def test_known_distance_cheb_to_as(self):
        # Cheb -> Aš is ~17 km
        d = haversine_km(50.0736, 12.3705, 50.2239, 12.1950)
        self.assertTrue(19 <= d <= 22, f"expected ~21 km, got {d:.1f}")


class TestDedup(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "t.db"

    def test_first_run_all_new_then_none(self):
        batch = [_mk(lid="1"), _mk(lid="2")]
        self.assertEqual(len(dedup.filter_new(batch, self.db)), 2)
        dedup.mark_seen(batch, self.db)
        self.assertEqual(len(dedup.filter_new(batch, self.db)), 0)

    def test_new_item_detected(self):
        batch = [_mk(lid="1")]
        dedup.mark_seen(batch, self.db)
        self.assertEqual(len(dedup.filter_new(batch + [_mk(lid="2")], self.db)), 1)

    def test_mark_seen_idempotent(self):
        batch = [_mk(lid="1")]
        dedup.mark_seen(batch, self.db)
        self.assertEqual(dedup.mark_seen(batch, self.db), 0)


class TestMinArea(unittest.TestCase):
    def test_filters_small_known_area(self):
        small = _mk(lid="s", area=35)
        big = _mk(lid="b", area=50)
        out = meets_min_area([small, big])
        self.assertEqual([l.listing_id for l in out], ["sreality:b"])
        self.assertEqual(MIN_AREA_M2, 40)

    def test_keeps_unknown_area(self):
        unknown = _mk(lid="u", area=None)
        self.assertEqual(meets_min_area([unknown]), [unknown])


class TestCrossSourceCollapse(unittest.TestCase):
    def test_same_flat_keeps_bezrealitky(self):
        listings = [
            _mk(source="sreality", lid="s", price=3_499_000, area=84),
            _mk(source="idnes", lid="i", price=3_499_000, area=84),
            _mk(source="bezrealitky", lid="b", price=3_499_000, area=84),
        ]
        out = collapse_cross_source(listings)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].source, "bezrealitky")

    def test_different_flats_kept(self):
        out = collapse_cross_source([
            _mk(lid="1", price=3_000_000, area=60),
            _mk(lid="2", price=3_100_000, area=70),
        ])
        self.assertEqual(len(out), 2)

    def test_same_portal_twice_is_two_properties(self):
        # Two Sreality listings can share disposition/area/price and still be
        # two different houses — a portal does not cross-post to itself.
        out = collapse_cross_source([
            _mk(source="sreality", lid="s1", price=4_990_000, area=67),
            _mk(source="sreality", lid="s2", price=4_990_000, area=67),
        ])
        self.assertEqual({l.listing_id for l in out}, {"sreality:s1", "sreality:s2"})

    def test_same_portal_twice_still_collapses_the_other_portal(self):
        out = collapse_cross_source([
            _mk(source="sreality", lid="s1", price=4_990_000, area=67),
            _mk(source="sreality", lid="s2", price=4_990_000, area=67),
            _mk(source="idnes", lid="i1", price=4_990_000, area=67),
        ])
        self.assertEqual(len(out), 2)
        self.assertEqual({l.source for l in out}, {"sreality"})

    def test_missing_area_not_collapsed(self):
        # without area we can't be sure it's the same flat -> keep both
        a = _mk(source="sreality", lid="1", price=3_000_000, area=None)
        b = _mk(source="idnes", lid="2", price=3_000_000, area=None)
        self.assertEqual(len(collapse_cross_source([a, b])), 2)


if __name__ == "__main__":
    unittest.main()
