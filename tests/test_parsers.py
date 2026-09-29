"""Tests for the three source parsers. Offline — fixtures mimic real payloads."""

import unittest
from unittest import mock

from sources import bezrealitky, idnes, sreality


class TestSreality(unittest.TestCase):
    ITEM = {
        "id": 123,
        "name": "Prodej bytu 3+kk 50 m²",
        "categorySubCb": {"name": "3+kk", "value": 6},
        "priceCzk": 3_490_000,
        "locality": {"city": "Cheb", "district": "Cheb",
                     "citySeoName": "cheb", "cityPartSeoName": "cheb",
                     "latitude": 50.07, "longitude": 12.37},
        "images": [{"url": "//d18.sdn.cz/x.jpeg"}],
    }

    def test_happy_path(self):
        l = sreality._parse_item(self.ITEM, "byt")
        self.assertEqual(l.listing_id, "sreality:123")
        self.assertEqual(l.price_czk, 3_490_000)
        self.assertEqual(l.area_m2, 50)
        self.assertEqual(l.disposition, "3+kk")
        self.assertEqual(l.city, "Cheb")
        self.assertEqual(l.latitude, 50.07)
        self.assertIn("/detail/prodej/byt/3+kk/cheb-cheb/123", l.url)
        self.assertIn("fl=res", l.image_url)
        self.assertTrue(l.image_url.startswith("https://"))

    def test_house_url_is_slugified(self):
        # Word dispositions ("Rodinný") 404 on Sreality unless lowercased,
        # stripped of diacritics and dash-joined.
        item = dict(self.ITEM, categorySubCb={"name": "Zemědělská usedlost"})
        l = sreality._parse_item(item, "dum")
        self.assertIn("/detail/prodej/dum/zemedelska-usedlost/cheb-cheb/123", l.url)
        self.assertEqual(l.disposition, "Zemědělská usedlost")

    def test_cottage_detail_path_is_dum(self):
        # /chaty is a search path only; cottage detail pages live under /dum.
        self.assertEqual(sreality._PROP_PATHS["chaty"], ("chaty", "dum"))

    def test_missing_id_returns_none(self):
        self.assertIsNone(sreality._parse_item({"name": "x"}, "byt"))

    def test_missing_price_tolerated(self):
        item = dict(self.ITEM)
        del item["priceCzk"]
        self.assertIsNone(sreality._parse_item(item, "byt").price_czk)


class TestBezrealitky(unittest.TestCase):
    def test_disposition_mapping(self):
        self.assertEqual(bezrealitky._disposition("DISP_3_KK"), "3+kk")
        self.assertEqual(bezrealitky._disposition("DISP_3_1"), "3+1")
        self.assertEqual(bezrealitky._disposition(None), "")

    def test_to_listing(self):
        cache = {"Image:9": {"url(\"x\")": "https://img/record_thumb/p.jpg"}}
        advert = {
            "id": "555", "uri": "555-nabidka", "disposition": "DISP_3_1",
            "price": 3_200_000, "surface": 80,
            "gps": {"lat": 50.07, "lng": 12.37},
            "address({\"locale\":\"CS\"})": "Hlavní, Cheb",
            "mainImage": {"__ref": "Image:9"},
        }
        l = bezrealitky._to_listing(cache, advert)
        self.assertEqual(l.listing_id, "bezrealitky:555")
        self.assertEqual(l.disposition, "3+1")
        self.assertEqual(l.price_czk, 3_200_000)
        self.assertEqual(l.area_m2, 80)
        self.assertIn("555-nabidka", l.url)
        self.assertEqual(l.latitude, 50.07)


class TestIdnes(unittest.TestCase):
    CARD = (
        'prefix class="c-products__item"><a '
        'href="https://reality.idnes.cz/detail/prodej/byt/cheb-centrum/69a6cc/">'
        '<span class="c-products__title"> prodej bytu 3+kk 66 m² '
        'Centrum, Cheb 3 490 000 Kč</span></a>'
    )

    def test_parse_card(self):
        listings = list(idnes._parse_cards(self.CARD))
        self.assertEqual(len(listings), 1)
        l = listings[0]
        self.assertEqual(l.listing_id, "idnes:69a6cc")
        self.assertEqual(l.disposition, "3+kk")
        self.assertEqual(l.area_m2, 66)
        self.assertEqual(l.price_czk, 3_490_000)
        self.assertIn("Cheb", l.city)

    def test_is_near_matches_allowlisted_town(self):
        self.assertTrue(idnes._is_near("Centrum, Písek"))
        self.assertTrue(idnes._is_near("Písek - Smrkovice"))

    def test_is_near_rejects_far_town(self):
        self.assertFalse(idnes._is_near("Lišejníková, Brno - Žebětín"))

    def test_is_near_ignores_okres_suffix(self):
        self.assertFalse(idnes._is_near("5. května, Milevsko, okres Písek"))
        self.assertTrue(idnes._is_near("Kollárova, Písek - Budějovické Předměstí"))

    def test_parse_house_card_locality_after_plot_area(self):
        card = (
            'class="c-products__item"><a '
            'href="https://reality.idnes.cz/detail/prodej/dum/protivin/abc123/">'
            '<span class="c-products__title">prodej rodinného domu 120 m² '
            's pozemkem 1 120 m² Zelenohorská, Protivín, okres Písek '
            '4 990 000 Kč</span></a>'
        )
        l = next(idnes._parse_cards(card))
        self.assertEqual(l.city, "Zelenohorská, Protivín, okres Písek")
        self.assertEqual(l.area_m2, 120)


def _idnes_card(listing_id: str) -> str:
    return (
        'class="c-products__item"><a '
        f'href="https://reality.idnes.cz/detail/prodej/byt/pisek/{listing_id}/">'
        '<span class="c-products__title">prodej bytu 2+kk 50 m² '
        'Centrum, Písek 3 490 000 Kč</span></a>'
    )


class TestIdnesPaging(unittest.TestCase):
    """iDNES paging is 0-indexed (first page has no ?page) and past the last
    page it serves the last page again instead of a 404."""

    ROOT = f"{idnes.SEARCH_ROOT}/byty/okres-pisek/"
    PORTAL = {
        ROOT: _idnes_card("aa01") + _idnes_card("aa02"),
        ROOT + "?page=1": _idnes_card("bb01"),
        ROOT + "?page=2": _idnes_card("bb01"),  # repeat of the last page
    }

    def _run(self):
        fetched: list[str] = []

        def fake_fetch(url):
            fetched.append(url)
            if url not in self.PORTAL:
                raise idnes.NoSuchPage(url)
            return self.PORTAL[url]

        with mock.patch.object(idnes, "_fetch", side_effect=fake_fetch), \
                mock.patch.object(idnes, "PROPERTY_TYPES", ["byty"]), \
                mock.patch.object(idnes, "IDNES_OKRESY", ["okres-pisek"]), \
                mock.patch.object(idnes.time, "sleep"):
            listings = idnes.fetch_listings()
        return {l.listing_id for l in listings}, fetched

    def test_fetch_listings_includes_first_page(self):
        ids, _ = self._run()
        self.assertEqual(ids, {"idnes:aa01", "idnes:aa02", "idnes:bb01"})

    def test_fetch_listings_stops_when_page_repeats(self):
        _, fetched = self._run()
        self.assertEqual(fetched, [self.ROOT, self.ROOT + "?page=1", self.ROOT + "?page=2"])


if __name__ == "__main__":
    unittest.main()
