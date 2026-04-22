"""Unit tests for scrapers_lib.tier1.bestbuy_api.

Tests run against synthetic JSON fixtures that mirror BestBuy's
documented Developer API response schema (one on-sale in-stock
product, one at-regular-price sold-out product). The gated live
integration test at ``test_bestbuy_api_integration.py`` verifies the
synthetic shape against the real API when ``BESTBUY_API_KEY`` is
available. No network in this file.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers_lib.core.registry import get_fetcher
from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier1 import bestbuy_api
from scrapers_lib.tier1.bestbuy_api import (
    API_KEY_ENV,
    SOURCE,
    _decimal_or_none,
    _derive_in_stock,
    _extract_sku,
    _float_or_none,
    _int_or_none,
    _leaf_category,
    _parse_details,
    parse_bestbuy_product_response,
)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


FIX = Path(__file__).parent / "fixtures" / "bestbuy_api"

ALIENWARE_SKU = "6587430"
ALIENWARE_URL = (
    f"https://www.bestbuy.com/site/alienware-16-area-51-gaming-laptop/"
    f"{ALIENWARE_SKU}.p?skuId={ALIENWARE_SKU}"
)

ASUS_SKU = "6587999"
ASUS_URL = (
    f"https://www.bestbuy.com/site/asus-rog-strix-g16-2025-gaming-laptop/"
    f"{ASUS_SKU}.p?skuId={ASUS_SKU}"
)


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _anchor(anchor_id: str, url: str) -> Anchor:
    return Anchor(
        anchor_id=anchor_id,
        anchor_type="product",
        name=anchor_id.replace("_", " ").title(),
        attribution_regex=AttributionRegex(primary=[anchor_id]),
        source_urls={"bestbuy_api": url},
    )


# ---------------------------------------------------------------------------
# On-sale in-stock product (Alienware)
# ---------------------------------------------------------------------------


class TestParseAlienwareOnSale:
    @pytest.fixture
    def snapshot(self):
        body = _load(f"product_{ALIENWARE_SKU}.json")
        snaps = parse_bestbuy_product_response(
            body, ALIENWARE_URL, anchors=[_anchor("alienware_area_51", ALIENWARE_URL)]
        )
        assert len(snaps) == 1
        return snaps[0]

    def test_source(self, snapshot):
        assert snapshot.source == "bestbuy_api"

    def test_source_id_is_sku_string(self, snapshot):
        assert snapshot.source_id == ALIENWARE_SKU
        assert isinstance(snapshot.source_id, str)

    def test_variant_key_is_none(self, snapshot):
        # One snapshot per SKU — no multi-variant fan-out from the API.
        assert snapshot.variant_key is None

    def test_title_from_name(self, snapshot):
        assert snapshot.title.startswith("Alienware")

    def test_brand_from_manufacturer(self, snapshot):
        assert snapshot.brand == "Alienware"

    def test_model_from_modelNumber(self, snapshot):
        assert snapshot.model == "AW16250-16-LQT-5070TI"

    def test_sale_price_is_price(self, snapshot):
        # On-sale: salePrice → price, regularPrice → list_price.
        assert snapshot.price == Decimal("2799.99")
        assert snapshot.list_price == Decimal("3199.99")

    def test_currency_defaults_to_usd(self, snapshot):
        assert snapshot.currency == "USD"

    def test_rating_parsed(self, snapshot):
        assert snapshot.rating == 4.6

    def test_review_count_parsed(self, snapshot):
        assert snapshot.review_count == 47

    def test_category_is_leaf_of_path(self, snapshot):
        assert snapshot.category == "Gaming Laptops"

    def test_in_stock_true_for_orderable_available(self, snapshot):
        assert snapshot.in_stock is True

    def test_image_url_prefers_largeFrontImage(self, snapshot):
        assert snapshot.image_url is not None
        assert "800x800" in snapshot.image_url

    def test_config_summary_from_first_features(self, snapshot):
        assert snapshot.config_summary is not None
        assert " / " in snapshot.config_summary

    def test_specs_populated(self, snapshot):
        assert len(snapshot.specs) >= 20

    def test_specs_well_known_keys_present(self, snapshot):
        for k in ("Processor", "Graphics", "System Memory (RAM)"):
            assert k in snapshot.specs

    def test_raw_records_spec_source_and_on_sale(self, snapshot):
        assert snapshot.raw["spec_source"] == "developer_api_details"
        assert snapshot.raw["on_sale"] is True
        assert snapshot.raw["sku"] == ALIENWARE_SKU


# ---------------------------------------------------------------------------
# Regular-price sold-out product (ASUS)
# ---------------------------------------------------------------------------


class TestParseAsusSoldOut:
    @pytest.fixture
    def snapshot(self):
        body = _load(f"product_{ASUS_SKU}.json")
        return parse_bestbuy_product_response(
            body, ASUS_URL, anchors=[_anchor("asus_rog_strix_g16", ASUS_URL)]
        )[0]

    def test_not_on_sale_price_is_regularPrice(self, snapshot):
        # salePrice is null; regularPrice is promoted to price, list_price stays None.
        assert snapshot.price == Decimal("2899.99")
        assert snapshot.list_price is None

    def test_in_stock_false_for_orderable_soldout(self, snapshot):
        assert snapshot.in_stock is False

    def test_availability_text_from_onlineAvailabilityText(self, snapshot):
        assert snapshot.availability_text == "Sold Out Online"

    def test_image_falls_back_to_image_when_largeFrontImage_null(self, snapshot):
        # largeFrontImage is null in this fixture.
        assert snapshot.image_url is not None
        assert "largeFrontImage" not in snapshot.image_url  # sanity

    def test_raw_on_sale_false(self, snapshot):
        assert snapshot.raw["on_sale"] is False


# ---------------------------------------------------------------------------
# Attribution gate
# ---------------------------------------------------------------------------


class TestAttributionGate:
    def test_no_anchor_raises_value_error(self):
        body = _load(f"product_{ALIENWARE_SKU}.json")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_bestbuy_product_response(body, ALIENWARE_URL, anchors=[])

    def test_wrong_url_raises_value_error(self):
        body = _load(f"product_{ALIENWARE_SKU}.json")
        wrong = _anchor("other", "https://www.bestbuy.com/site/foo/0000000.p")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_bestbuy_product_response(body, ALIENWARE_URL, anchors=[wrong])


# ---------------------------------------------------------------------------
# JSON shape failures
# ---------------------------------------------------------------------------


class TestMalformedPayloads:
    def test_non_json_body_raises(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_bestbuy_product_response(
                "not json at all",
                ALIENWARE_URL,
                anchors=[_anchor("alienware_area_51", ALIENWARE_URL)],
            )

    def test_missing_sku_raises(self):
        body = json.dumps({"name": "missing sku"})
        with pytest.raises(ValueError, match="missing sku"):
            parse_bestbuy_product_response(
                body,
                ALIENWARE_URL,
                anchors=[_anchor("alienware_area_51", ALIENWARE_URL)],
            )

    def test_missing_name_raises(self):
        body = json.dumps({"sku": 1234567})
        with pytest.raises(ValueError, match="missing sku or name"):
            parse_bestbuy_product_response(
                body,
                ALIENWARE_URL,
                anchors=[_anchor("alienware_area_51", ALIENWARE_URL)],
            )


# ---------------------------------------------------------------------------
# SKU extraction
# ---------------------------------------------------------------------------


class TestExtractSku:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.bestbuy.com/site/foo/6587430.p", "6587430"),
            ("https://www.bestbuy.com/site/foo/6587430.p/", "6587430"),
            ("https://www.bestbuy.com/site/foo/6587430.p?skuId=6587430", "6587430"),
            ("https://www.bestbuy.com/site/foo/bar?skuId=6587430", "6587430"),
            ("https://www.bestbuy.com/site/foo/bar?skuId=6587430&other=x", "6587430"),
        ],
    )
    def test_parses_expected(self, url, expected):
        assert _extract_sku(url) == expected

    def test_non_bestbuy_host_raises(self):
        with pytest.raises(ValueError, match="not bestbuy.com"):
            _extract_sku("https://www.amazon.com/site/foo/6587430.p")

    def test_no_sku_in_url_raises(self):
        with pytest.raises(ValueError, match="does not carry a SKU"):
            _extract_sku("https://www.bestbuy.com/site/foo/bar")


# ---------------------------------------------------------------------------
# Credential handling (no network)
# ---------------------------------------------------------------------------


class TestCredentialHandling:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv(API_KEY_ENV, raising=False)
        with pytest.raises(RuntimeError, match=API_KEY_ENV):
            bestbuy_api.fetch_bestbuy_api_product(
                ALIENWARE_URL,
                anchors=[_anchor("alienware_area_51", ALIENWARE_URL)],
            )

    def test_explicit_api_key_skips_env_lookup(self, monkeypatch):
        # monkeypatch env missing; pass api_key explicitly — still needs to
        # reach a network call to fail, so we stub httpx to raise before
        # the network hits.
        monkeypatch.delenv(API_KEY_ENV, raising=False)
        monkeypatch.setattr(
            bestbuy_api, "_fetch_product", lambda *a, **kw: (_ for _ in ()).throw(
                RuntimeError("stub-fetch-called")
            )
        )
        with pytest.raises(RuntimeError, match="stub-fetch-called"):
            bestbuy_api.fetch_bestbuy_api_product(
                ALIENWARE_URL,
                anchors=[_anchor("alienware_area_51", ALIENWARE_URL)],
                api_key="explicit-key-123",
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestParseDetails:
    def test_flat_list_to_dict(self):
        out = _parse_details(
            [
                {"name": "Processor", "value": "Intel"},
                {"name": "RAM", "value": "32GB"},
            ]
        )
        assert out == {"Processor": "Intel", "RAM": "32GB"}

    def test_empty_values_skipped(self):
        out = _parse_details([{"name": "X", "value": ""}, {"name": "", "value": "y"}])
        assert out == {}

    def test_first_occurrence_wins_on_duplicate_key(self):
        out = _parse_details(
            [
                {"name": "X", "value": "first"},
                {"name": "X", "value": "second"},
            ]
        )
        assert out == {"X": "first"}

    def test_non_dict_items_skipped(self):
        out = _parse_details(
            [{"name": "X", "value": "y"}, "not a dict", None, {"name": "A", "value": "B"}]
        )
        assert out == {"X": "y", "A": "B"}


class TestLeafCategory:
    def test_returns_last_name(self):
        path = [
            {"id": "1", "name": "A"},
            {"id": "2", "name": "B"},
            {"id": "3", "name": "C"},
        ]
        assert _leaf_category(path) == "C"

    def test_skips_entries_without_name(self):
        path = [{"id": "1", "name": "A"}, {"id": "2"}]
        assert _leaf_category(path) == "A"

    def test_empty_list_returns_none(self):
        assert _leaf_category([]) is None


class TestDeriveInStock:
    def test_orderable_available(self):
        assert _derive_in_stock({"orderable": "Available"}) is True

    def test_orderable_soldout(self):
        assert _derive_in_stock({"orderable": "SoldOut"}) is False

    def test_online_available_bool(self):
        assert _derive_in_stock({"onlineAvailability": True}) is True

    def test_all_missing_returns_none(self):
        assert _derive_in_stock({}) is None


class TestNumericCoercion:
    def test_decimal_from_str(self):
        assert _decimal_or_none("12.50") == Decimal("12.50")

    def test_decimal_from_int(self):
        assert _decimal_or_none(42) == Decimal("42")

    def test_decimal_from_none(self):
        assert _decimal_or_none(None) is None

    def test_float_from_str(self):
        assert _float_or_none("4.5") == 4.5

    def test_int_from_str(self):
        assert _int_or_none("47") == 47

    def test_int_from_none(self):
        assert _int_or_none(None) is None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registered_under_bestbuy_api(self):
        assert get_fetcher(SOURCE) is bestbuy_api.fetch_bestbuy_api_product

    def test_source_constant(self):
        assert SOURCE == "bestbuy_api"
