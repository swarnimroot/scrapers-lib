"""Unit tests for scrapers_lib.tier3.amazon.

Tests run against committed Amazon PDP HTML fixtures captured during
Wave 2c reconnaissance — one Alienware 16 Area-51 (B0F8P6MRQT) and one
ASUS ROG Strix G16 (B0DW1FVPK8), chosen deliberately from different
brands to exercise Amazon's two bylineInfo rendering variants. No
network.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from scrapers_lib.core.registry import get_fetcher
from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.core.scheduler import BlockedError
from scrapers_lib.tier3 import amazon
from scrapers_lib.tier3.amazon import (
    SOURCE,
    SOURCE_REVIEWS,
    _derive_in_stock,
    _extract_asin,
    _looks_blocked,
    _parse_dollars,
    parse_amazon_product_page,
    parse_amazon_reviews,
)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


FIX = Path(__file__).parent / "fixtures" / "amazon"

ALIENWARE_ASIN = "B0F8P6MRQT"
ALIENWARE_URL = f"https://www.amazon.com/dp/{ALIENWARE_ASIN}"

ASUS_ASIN = "B0DW1FVPK8"
ASUS_URL = f"https://www.amazon.com/dp/{ASUS_ASIN}"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _anchor(anchor_id: str, url: str) -> Anchor:
    return Anchor(
        anchor_id=anchor_id,
        anchor_type="product",
        name=anchor_id.replace("_", " ").title(),
        attribution_regex=AttributionRegex(primary=[anchor_id]),
        source_urls={"amazon": url},
    )


# ---------------------------------------------------------------------------
# parse_amazon_product_page — Alienware (standard bylineInfo PDP)
# ---------------------------------------------------------------------------


class TestParseAlienwareProduct:
    @pytest.fixture
    def snapshot(self):
        html = _load(f"pdp_{ALIENWARE_ASIN}.html")
        snaps = parse_amazon_product_page(
            html,
            ALIENWARE_URL,
            anchors=[_anchor("alienware_area_51", ALIENWARE_URL)],
        )
        assert len(snaps) == 1
        return snaps[0]

    def test_source(self, snapshot):
        assert snapshot.source == "amazon"

    def test_source_id_is_asin(self, snapshot):
        assert snapshot.source_id == ALIENWARE_ASIN

    def test_variant_key_is_asin(self, snapshot):
        # Amazon PDP is per-ASIN; we treat variant_key = source_id to stay
        # schema-consistent with per-tile sources.
        assert snapshot.variant_key == ALIENWARE_ASIN

    def test_anchor_id_from_attribution(self, snapshot):
        assert snapshot.anchor_id == "alienware_area_51"

    def test_title_populated(self, snapshot):
        assert "Alienware" in snapshot.title
        assert "Area-51" in snapshot.title

    def test_brand_from_bylineInfo(self, snapshot):
        assert snapshot.brand == "Alienware"

    def test_price_parsed(self, snapshot):
        assert snapshot.price == Decimal("2609.00")
        assert snapshot.currency == "USD"

    def test_rating_parsed(self, snapshot):
        assert snapshot.rating == 4.5

    def test_review_count_parsed(self, snapshot):
        assert snapshot.review_count == 28

    def test_image_url_populated(self, snapshot):
        assert snapshot.image_url is not None
        assert snapshot.image_url.startswith("https://")

    def test_availability_text(self, snapshot):
        assert snapshot.availability_text is not None
        assert "stock" in snapshot.availability_text.lower()

    def test_in_stock_true_on_only_n_left(self, snapshot):
        assert snapshot.in_stock is True

    def test_specs_are_keyvalue_rows(self, snapshot):
        # PDP has 5+ prodDetTable sections; expect at least 40 pairs after merge.
        assert len(snapshot.specs) >= 40, f"only {len(snapshot.specs)} specs"

    def test_specs_include_well_known_keys(self, snapshot):
        for key in ("Graphics Coprocessor", "RAM Memory Installed", "Item Weight"):
            assert key in snapshot.specs, f"missing {key!r}"

    def test_feature_bullets_in_raw(self, snapshot):
        bullets = snapshot.raw["feature_bullets"]
        assert isinstance(bullets, list) and len(bullets) >= 3

    def test_raw_records_spec_source(self, snapshot):
        assert snapshot.raw["spec_source"] == "prodDetTable"
        assert snapshot.raw["asin"] == ALIENWARE_ASIN


# ---------------------------------------------------------------------------
# parse_amazon_product_page — ASUS (premium PDP, empty bylineInfo)
# ---------------------------------------------------------------------------


class TestParseAsusProduct:
    @pytest.fixture
    def snapshot(self):
        html = _load(f"pdp_{ASUS_ASIN}.html")
        snaps = parse_amazon_product_page(
            html,
            ASUS_URL,
            anchors=[_anchor("asus_rog_strix_g16", ASUS_URL)],
        )
        return snaps[0]

    def test_source_id_is_asin(self, snapshot):
        assert snapshot.source_id == ASUS_ASIN

    def test_brand_from_visitStoreDesktopUrl_fallback(self, snapshot):
        # Premium PDPs hide #bylineInfo; brand comes from the store link
        # or the brand-logo image.
        assert snapshot.brand == "ASUS"

    def test_price_parsed(self, snapshot):
        assert snapshot.price == Decimal("2899.99")

    def test_rating_parsed(self, snapshot):
        assert snapshot.rating == 4.0

    def test_review_count_parsed(self, snapshot):
        assert snapshot.review_count == 84

    def test_specs_populated(self, snapshot):
        assert len(snapshot.specs) >= 40

    def test_title_contains_asus(self, snapshot):
        assert "ASUS" in snapshot.title.upper()


# ---------------------------------------------------------------------------
# parse_amazon_reviews
# ---------------------------------------------------------------------------


class TestParseAlienwareReviews:
    @pytest.fixture
    def mentions(self):
        html = _load(f"pdp_{ALIENWARE_ASIN}.html")
        return parse_amazon_reviews(
            html,
            ALIENWARE_URL,
            anchors=[_anchor("alienware_area_51", ALIENWARE_URL)],
        )

    def test_at_least_one_review(self, mentions):
        assert len(mentions) >= 1

    def test_all_have_non_empty_body(self, mentions):
        for m in mentions:
            assert m.raw_text.strip()

    def test_source_is_amazon(self, mentions):
        assert mentions[0].source == "amazon"

    def test_source_type_is_post(self, mentions):
        assert mentions[0].source_type == "post"

    def test_parent_id_is_asin(self, mentions):
        assert mentions[0].parent_id == ALIENWARE_ASIN

    def test_mention_id_is_deterministic(self, mentions):
        # Format: amazon_<asin>_<reviewId>
        for m in mentions:
            assert m.mention_id.startswith(f"amazon_{ALIENWARE_ASIN}_")

    def test_source_url_points_at_customer_review(self, mentions):
        assert "/gp/customer-reviews/" in mentions[0].source_url

    def test_attribution_is_url_map(self, mentions):
        assert mentions[0].attribution.method == "url_map"
        assert mentions[0].attribution.anchor_id == "alienware_area_51"

    def test_first_review_has_parsed_date(self, mentions):
        assert mentions[0].published_at is not None

    def test_first_review_has_star_rating(self, mentions):
        assert mentions[0].raw["star_rating"] is not None
        assert 0.0 <= mentions[0].raw["star_rating"] <= 5.0

    def test_first_review_has_author(self, mentions):
        assert mentions[0].author

    def test_first_review_has_title(self, mentions):
        assert mentions[0].source_title

    def test_at_least_one_verified_purchase(self, mentions):
        assert any(m.raw["verified_purchase"] for m in mentions)


class TestParseAsusReviews:
    def test_reviews_parse_on_premium_pdp(self):
        html = _load(f"pdp_{ASUS_ASIN}.html")
        mentions = parse_amazon_reviews(
            html, ASUS_URL, anchors=[_anchor("asus_rog_strix_g16", ASUS_URL)]
        )
        assert len(mentions) >= 1
        for m in mentions:
            assert m.raw_text.strip()
            assert m.parent_id == ASUS_ASIN


# ---------------------------------------------------------------------------
# Attribution gate
# ---------------------------------------------------------------------------


class TestAttributionGate:
    def test_no_anchor_raises_value_error(self):
        html = _load(f"pdp_{ALIENWARE_ASIN}.html")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_amazon_product_page(html, ALIENWARE_URL, anchors=[])

    def test_wrong_url_anchor_raises_value_error(self):
        html = _load(f"pdp_{ALIENWARE_ASIN}.html")
        wrong = _anchor("other", "https://www.amazon.com/dp/B000000000")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_amazon_product_page(html, ALIENWARE_URL, anchors=[wrong])

    def test_reviews_parser_requires_anchor_too(self):
        html = _load(f"pdp_{ALIENWARE_ASIN}.html")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_amazon_reviews(html, ALIENWARE_URL, anchors=[])


# ---------------------------------------------------------------------------
# _extract_asin
# ---------------------------------------------------------------------------


class TestExtractAsin:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.amazon.com/dp/B0F8P6MRQT", "B0F8P6MRQT"),
            ("https://www.amazon.com/dp/B0F8P6MRQT/", "B0F8P6MRQT"),
            ("https://www.amazon.com/dp/B0F8P6MRQT?ref=foo", "B0F8P6MRQT"),
            (
                "https://www.amazon.com/Alienware-Gaming-Laptop/dp/B0F8P6MRQT/ref=sr_1_1",
                "B0F8P6MRQT",
            ),
            ("https://www.amazon.com/gp/product/B0F8P6MRQT", "B0F8P6MRQT"),
            ("https://www.amazon.com/gp/product/B0F8P6MRQT/", "B0F8P6MRQT"),
            ("https://www.amazon.co.uk/dp/B0F8P6MRQT", "B0F8P6MRQT"),
        ],
    )
    def test_parses_expected(self, url, expected):
        assert _extract_asin(url) == expected

    def test_non_amazon_host_raises(self):
        with pytest.raises(ValueError, match="not an amazon domain"):
            _extract_asin("https://www.example.com/dp/B0F8P6MRQT")

    def test_unrecognized_path_raises(self):
        with pytest.raises(ValueError, match="does not match"):
            _extract_asin("https://www.amazon.com/reviews/something")


# ---------------------------------------------------------------------------
# Block detection — positives and negatives
# ---------------------------------------------------------------------------


class TestLooksBlocked:
    def test_real_pdp_is_not_blocked(self):
        html = _load(f"pdp_{ALIENWARE_ASIN}.html")
        assert _looks_blocked(html) is False

    def test_real_asus_pdp_is_not_blocked(self):
        html = _load(f"pdp_{ASUS_ASIN}.html")
        assert _looks_blocked(html) is False

    @pytest.mark.parametrize(
        "snippet",
        [
            "<html><head><title>Robot Check</title></head><body>...</body></html>",
            "<p>To discuss automated access to Amazon data please contact ...</p>",
            "<title>Sorry! Something went wrong</title>",
            '<form action="/errors/validateCaptcha">...</form>',
            "<p>Type the characters you see in this image:</p>",
        ],
    )
    def test_known_block_shapes_are_flagged(self, snippet):
        assert _looks_blocked(snippet) is True


# ---------------------------------------------------------------------------
# _parse_dollars
# ---------------------------------------------------------------------------


class TestParseDollars:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("$2,609.00", Decimal("2609.00")),
            ("$ 2,609.00", Decimal("2609.00")),
            ("2609.00", Decimal("2609.00")),
            ("1,234.5", Decimal("1234.5")),
            ("$19", Decimal("19")),
        ],
    )
    def test_common_shapes(self, text, expected):
        assert _parse_dollars(text) == expected

    def test_empty_string_returns_none(self):
        assert _parse_dollars("") is None

    def test_no_digits_returns_none(self):
        assert _parse_dollars("free shipping") is None


# ---------------------------------------------------------------------------
# _derive_in_stock
# ---------------------------------------------------------------------------


class TestDeriveInStock:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("In Stock", True),
            ("In stock", True),
            ("Only 3 left in stock - order soon.", True),
            ("Only 1 left in stock.", True),
            ("Currently unavailable.", False),
            ("Temporarily out of stock.", False),
            ("Out of Stock", False),
            ("", None),
            (None, None),
            ("See availability at checkout", None),
        ],
    )
    def test_known_shapes(self, text, expected):
        assert _derive_in_stock(text) is expected


# ---------------------------------------------------------------------------
# BlockedError propagation
# ---------------------------------------------------------------------------


class TestBlockedError:
    def test_product_parse_raises_on_block_page(self):
        # Minimal Amazon "Robot Check" page.
        html = "<html><head><title>Robot Check</title></head><body></body></html>"
        with pytest.raises(BlockedError):
            parse_amazon_product_page(
                html,
                ALIENWARE_URL,
                anchors=[_anchor("alienware_area_51", ALIENWARE_URL)],
            )

    def test_reviews_parse_raises_on_block_page(self):
        html = "<html><head><title>Robot Check</title></head><body></body></html>"
        with pytest.raises(BlockedError):
            parse_amazon_reviews(
                html,
                ALIENWARE_URL,
                anchors=[_anchor("alienware_area_51", ALIENWARE_URL)],
            )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_product_fetcher_registered(self):
        assert get_fetcher(SOURCE) is amazon.fetch_amazon_product

    def test_reviews_fetcher_registered(self):
        assert get_fetcher(SOURCE_REVIEWS) is amazon.fetch_amazon_reviews

    def test_source_constants(self):
        assert SOURCE == "amazon"
        assert SOURCE_REVIEWS == "amazon_reviews"
