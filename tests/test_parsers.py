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


class TestSrealityDispositions(unittest.TestCase):
    def test_multiple_dispositions_in_one_param(self):
        # A repeated `velikost=` makes Sreality return only the first size.
        with mock.patch.object(sreality, "DISPOSITIONS", ["2+kk", "3+kk"]):
            url = sreality._search_url("byty", "pisek", 1)
        self.assertEqual(url.count("velikost="), 1)
        self.assertIn("velikost=2%2Bkk,3%2Bkk", url)

    def test_no_dispositions_no_param(self):
        with mock.patch.object(sreality, "DISPOSITIONS", []):
            self.assertNotIn("velikost", sreality._search_url("byty", "pisek", 1))


class TestSrealityLandAndRent(unittest.TestCase):
    LAND = {
        "id": 77, "name": "Prodej stavebního pozemku 860\xa0m²",
        "categorySubCb": {"name": "Bydlení", "value": 19},
        "priceCzk": 2000, "priceSummaryCzk": 1_720_000,
        "priceUnitCb": {"name": "za m²", "value": 3},
        "locality": {"city": "Kostelec", "citySeoName": "kostelec",
                     "cityPartSeoName": "kostelec"},
    }

    def test_land_price_is_total_not_per_m2(self):
        l = sreality._parse_item(self.LAND, "pozemek")
        self.assertEqual(l.price_czk, 1_720_000)
        self.assertEqual(l.area_m2, 860)
        self.assertEqual(l.disposition, "Bydlení")
        self.assertIn("/pozemek/bydleni/kostelec-kostelec/77", l.url)

    def test_price_for_whole_property_is_kept(self):
        item = dict(self.LAND, priceCzk=4_110_832, priceSummaryCzk=4_110_832,
                    priceUnitCb={"name": "za nemovitost", "value": 1})
        self.assertEqual(sreality._parse_item(item, "pozemek").price_czk, 4_110_832)

    def test_pozemky_search_url(self):
        self.assertIn("/pozemky/pisek", sreality._search_url("pozemky", "pisek", 1))

    def test_dispositions_do_not_narrow_land_search(self):
        with mock.patch.object(sreality, "DISPOSITIONS", ["2+kk"]):
            self.assertNotIn("velikost", sreality._search_url("pozemky", "pisek", 1))
            self.assertNotIn("velikost", sreality._search_url("domy", "pisek", 1))

    def test_rent_url_and_detail(self):
        search = "https://www.sreality.cz/hledani/pronajem"
        detail = "https://www.sreality.cz/detail/pronajem"
        with mock.patch.object(sreality, "SEARCH_ROOT", search), \
                mock.patch.object(sreality, "DETAIL_ROOT", detail):
            self.assertTrue(sreality._search_url("byty", "pisek", 1)
                            .startswith(search + "/byty/pisek"))
            item = {"id": 5, "name": "Pronájem bytu 2+kk 92\xa0m²",
                    "categorySubCb": {"name": "2+kk"}, "priceCzk": 17000,
                    "priceUnitCb": {"name": "za měsíc", "value": 2},
                    "locality": {"citySeoName": "pisek",
                                 "cityPartSeoName": "vnitrni-mesto"}}
            l = sreality._parse_item(item, "byt")
        self.assertEqual(l.price_czk, 17000)
        self.assertIn("/detail/pronajem/byt/2+kk/pisek-vnitrni-mesto/5", l.url)


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

    def test_area_with_thousands_separator(self):
        card = (
            'class="c-products__item"><a '
            'href="https://reality.idnes.cz/detail/prodej/pozemek/krenovice/6a85aa/">'
            '<span class="c-products__title">prodej pole 13 645 m² '
            'Křenovice, okres Písek 682 250 Kč (50 Kč/m² )</span></a>'
        )
        l = next(idnes._parse_cards(card))
        self.assertEqual(l.area_m2, 13_645)
        self.assertEqual(l.price_czk, 682_250)
        self.assertEqual(l.disposition, "pole")
        self.assertIn("Křenovice", l.city)

    def test_land_kind_from_genitive_title(self):
        card = (
            'class="c-products__item"><a '
            'href="https://reality.idnes.cz/detail/prodej/pozemek/x/6a85bb/">'
            '<span class="c-products__title">prodej stavebního pozemku 4 440 m² '
            'Albrechtice, okres Písek 4 990 000 Kč</span></a>'
        )
        l = next(idnes._parse_cards(card))
        self.assertEqual((l.disposition, l.area_m2), ("stavební", 4440))

    def test_rent_card_area_not_glued_to_disposition(self):
        # "3+1 57 m²" must be 57, not "1 57" -> 157
        card = (
            'class="c-products__item"><a '
            'href="https://reality.idnes.cz/detail/pronajem/byt/pisek-x/6a85cc/">'
            '<span class="c-products__title">pronájem bytu 3+1 57 m² '
            'Velké náměstí, Písek - Vnitřní Město 14 500 Kč/měsíc</span></a>'
        )
        l = next(idnes._parse_cards(card))
        self.assertEqual((l.disposition, l.area_m2, l.price_czk), ("3+1", 57, 14_500))
        self.assertIn("/pronajem/", l.url)

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


class TestBezrealitkyLandAndRent(unittest.TestCase):
    def test_land_area_comes_from_plot_size(self):
        advert = {"id": "9", "estateType": "POZEMEK", "disposition": "UNDEFINED",
                  "price": 5_050_000, "surface": 0, "surfaceLand": 2888,
                  "gps": {"lat": 49.3, "lng": 14.1}, "uri": "9-prodej-pozemku"}
        l = bezrealitky._to_listing({}, advert)
        self.assertEqual((l.area_m2, l.price_czk, l.disposition), (2888, 5_050_000, ""))

    def test_rent_keeps_charges(self):
        advert = {"id": "8", "disposition": "DISP_2_1", "price": 13_000,
                  "charges": 5_500, "surface": 46, "uri": "8-pronajem"}
        with mock.patch.object(bezrealitky, "OFFER_TYPE", "pronajem"):
            l = bezrealitky._to_listing({}, advert)
        self.assertEqual((l.price_czk, l.charges_czk), (13_000, 5_500))

    def test_sale_ignores_charges(self):
        advert = {"id": "7", "disposition": "DISP_2_1", "price": 3_000_000,
                  "charges": 900, "surface": 46, "uri": "7-prodej"}
        self.assertIsNone(bezrealitky._to_listing({}, advert).charges_czk)


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
