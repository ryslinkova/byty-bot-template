"""Tests for geo, dedup and cross-source collapse. Offline, no network."""

import tempfile
import unittest
from pathlib import Path

import dedup
from config import MIN_AREA_M2
from geo import haversine_km
from unittest import mock

import email_report
import main
from main import check_config, collapse_cross_source, meets_min_area
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


def _land(source="sreality", lid="l", price=900_000, kind="Pole", area=12_000):
    l = _mk(source=source, lid=lid, price=price, disp=kind, area=area)
    l.property_type = "pozemky"
    return l


class TestLand(unittest.TestCase):
    def test_land_uses_its_own_min_area(self):
        small_plot, big_plot = _land(lid="a", area=500), _land(lid="b")
        flat = _mk(lid="f", area=50)
        with mock.patch.object(main, "MIN_LAND_AREA_M2", 1000):
            out = meets_min_area([small_plot, big_plot, flat])
        self.assertEqual({l.listing_id for l in out}, {"sreality:b", "sreality:f"})

    def test_land_ignores_flat_area_minimum(self):
        # a 30 m² plot must not be dropped by the 40 m² flat limit
        with mock.patch.object(main, "MIN_LAND_AREA_M2", None):
            self.assertEqual(len(meets_min_area([_land(area=30)])), 1)

    def test_same_plot_on_two_portals_collapses_despite_different_kind(self):
        out = collapse_cross_source([
            _land(source="sreality", lid="s", kind="Bydlení", area=4440, price=4_990_000),
            _land(source="idnes", lid="i", kind="stavební", area=4440, price=4_990_000),
        ])
        self.assertEqual(len(out), 1)

    def test_plot_and_flat_with_equal_numbers_are_not_the_same(self):
        flat = _mk(source="sreality", lid="f", price=900_000, area=60, disp="")
        plot = _land(source="idnes", lid="p", price=900_000, area=60, kind="")
        self.assertEqual(len(collapse_cross_source([flat, plot])), 2)


class TestConfigCheck(unittest.TestCase):
    def test_bad_offer_type(self):
        with mock.patch.object(main, "OFFER_TYPE", "koupe"):
            with self.assertRaises(SystemExit):
                check_config()

    def test_unknown_property_type(self):
        with mock.patch.object(main, "PROPERTY_TYPES", ["byty", "hrady"]):
            with self.assertRaises(SystemExit):
                check_config()

    def test_default_config_is_valid(self):
        check_config()


class TestEmailFormatting(unittest.TestCase):
    def test_land_line(self):
        l = _land(kind="Pole", area=93_428, price=4_110_832)
        card = email_report._listing_card(l)
        self.assertIn("Pozemek – pole", card)
        self.assertIn("93\u00a0428\u00a0m²", card)
        self.assertIn("4\u00a0110\u00a0832 Kč", card)

    def test_rent_shows_month_and_charges(self):
        l = _mk(price=13_000)
        l.offer, l.charges_czk = "pronajem", 5_500
        line = email_report._price_line(l)
        self.assertIn("13\u00a0000 Kč/měsíc", line)
        self.assertIn("5\u00a0500 Kč poplatky", line)

    def test_sale_price_has_no_month(self):
        self.assertNotIn("měsíc", email_report._price_line(_mk()))


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
