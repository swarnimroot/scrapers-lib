"""Unit tests for scrapers_lib.tier3.bestbuy.

Tests run against committed BestBuy PDP HTML fixtures captured during
Wave 2c reconnaissance — two unrelated Alienware SKUs (6628371 Area-51
18" + 6630638 16X Aurora 16") fetched via curl_cffi + Chrome
impersonation + HTTP/1.1 (the combination that gets past Akamai's
HTTP/2 RST-stream gate). No network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scrapers_lib.core.registry import get_fetcher
from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.core.scheduler import BlockedError
from scrapers_lib.tier3 import bestbuy
from scrapers_lib.tier3.bestbuy import (
    SOURCE,
    SOURCE_REVIEWS,
    _extract_sku,
    _iter_reviews,
    _looks_blocked,
    parse_bestbuy_pdp_reviews,
)


FIX = Path(__file__).parent / "fixtures" / "bestbuy"

AREA51_SKU = "6628371"
AREA51_URL = f"https://www.bestbuy.com/site/alienware/{AREA51_SKU}.p?skuId={AREA51_SKU}"

AURORA_SKU = "6630638"
AURORA_URL = f"https://www.bestbuy.com/site/alienware/{AURORA_SKU}.p?skuId={AURORA_SKU}"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _anchor(anchor_id: str, url: str) -> Anchor:
    return Anchor(
        anchor_id=anchor_id,
        anchor_type="product",
        name=anchor_id.replace("_", " ").title(),
        attribution_regex=AttributionRegex(primary=[anchor_id]),
        source_urls={"bestbuy": url},
    )


# ---------------------------------------------------------------------------
# Reviews on Area-51 18" (SKU 6628371)
# ---------------------------------------------------------------------------


class TestParseArea51Reviews:
    @pytest.fixture
    def mentions(self):
        html = _load(f"pdp_{AREA51_SKU}.html")
        return parse_bestbuy_pdp_reviews(
            html, AREA51_URL, anchors=[_anchor("alienware_area_51_18", AREA51_URL)]
        )

    def test_at_least_three_reviews(self, mentions):
        # BestBuy inlines ~5 reviews on the PDP; tolerate slight churn.
        assert len(mentions) >= 3

    def test_all_have_non_empty_body(self, mentions):
        for m in mentions:
            assert m.raw_text.strip()

    def test_source_is_bestbuy(self, mentions):
        assert mentions[0].source == "bestbuy"

    def test_source_type_is_post(self, mentions):
        assert mentions[0].source_type == "post"

    def test_parent_id_is_sku(self, mentions):
        assert mentions[0].parent_id == AREA51_SKU

    def test_mention_id_is_deterministic_prefix(self, mentions):
        for m in mentions:
            assert m.mention_id.startswith(f"bestbuy_{AREA51_SKU}_")

    def test_mention_id_is_unique_across_reviews(self, mentions):
        ids = [m.mention_id for m in mentions]
        assert len(ids) == len(set(ids))

    def test_source_url_points_at_reviews_page(self, mentions):
        assert mentions[0].source_url == (
            f"https://www.bestbuy.com/site/reviews/name/{AREA51_SKU}"
        )

    def test_attribution_is_url_map(self, mentions):
        assert mentions[0].attribution.method == "url_map"
        assert mentions[0].attribution.anchor_id == "alienware_area_51_18"

    def test_each_review_has_author(self, mentions):
        for m in mentions:
            assert m.author

    def test_each_review_has_title(self, mentions):
        for m in mentions:
            assert m.source_title

    def test_each_review_has_star_rating_in_range(self, mentions):
        for m in mentions:
            r = m.raw["star_rating"]
            assert r is None or (0.0 <= r <= 5.0)

    def test_published_at_is_none(self, mentions):
        # JSON-LD on BestBuy PDPs does not carry datePublished; document
        # this limitation as a test so it stays honest if the API changes.
        assert mentions[0].published_at is None


# ---------------------------------------------------------------------------
# Generality check: Aurora 16X (different SKU, still Alienware)
# ---------------------------------------------------------------------------


class TestParseAuroraReviews:
    def test_reviews_parse_on_second_sku(self):
        html = _load(f"pdp_{AURORA_SKU}.html")
        mentions = parse_bestbuy_pdp_reviews(
            html, AURORA_URL, anchors=[_anchor("alienware_aurora_16x", AURORA_URL)]
        )
        assert len(mentions) >= 3
        for m in mentions:
            assert m.raw_text.strip()
            assert m.parent_id == AURORA_SKU
            assert m.source == "bestbuy"


# ---------------------------------------------------------------------------
# Attribution gate
# ---------------------------------------------------------------------------


class TestAttributionGate:
    def test_no_anchor_raises_value_error(self):
        html = _load(f"pdp_{AREA51_SKU}.html")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_bestbuy_pdp_reviews(html, AREA51_URL, anchors=[])

    def test_wrong_url_raises_value_error(self):
        html = _load(f"pdp_{AREA51_SKU}.html")
        wrong = _anchor("other", "https://www.bestbuy.com/site/bar/0000000.p")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_bestbuy_pdp_reviews(html, AREA51_URL, anchors=[wrong])


# ---------------------------------------------------------------------------
# JSON-LD shape tolerance
# ---------------------------------------------------------------------------


class TestIterReviews:
    def test_list_returns_dicts_only(self):
        product = {
            "review": [
                {"@type": "Review", "reviewBody": "A"},
                "not a dict",
                {"@type": "Review", "reviewBody": "B"},
            ]
        }
        result = _iter_reviews(product)
        assert len(result) == 2

    def test_single_dict_wrapped_to_list(self):
        product = {"review": {"@type": "Review", "reviewBody": "solo"}}
        assert len(_iter_reviews(product)) == 1

    def test_missing_review_key_returns_empty(self):
        assert _iter_reviews({}) == []

    def test_null_review_returns_empty(self):
        assert _iter_reviews({"review": None}) == []


class TestEmptyBodySkipping:
    def test_review_with_empty_body_skipped(self):
        # Build a synthetic HTML with one good review + one empty-body.
        html = (
            '<html><body><script type="application/ld+json">'
            '{"@type":"Product","sku":"1234567","review":['
            '{"@type":"Review","name":"Good","reviewBody":"This is a review.",'
            '"reviewRating":{"ratingValue":5},"author":{"name":"Alice"}},'
            '{"@type":"Review","name":"Empty","reviewBody":"",'
            '"reviewRating":{"ratingValue":1},"author":{"name":"Bob"}}'
            "]}"
            "</script></body></html>"
        )
        url = "https://www.bestbuy.com/site/x/1234567.p?skuId=1234567"
        mentions = parse_bestbuy_pdp_reviews(
            html, url, anchors=[_anchor("x", url)]
        )
        assert len(mentions) == 1
        assert mentions[0].author == "Alice"

    def test_author_as_string_not_dict(self):
        html = (
            '<html><body><script type="application/ld+json">'
            '{"@type":"Product","sku":"1234567","review":'
            '{"@type":"Review","name":"T","reviewBody":"Body text",'
            '"reviewRating":{"ratingValue":4},"author":"PlainName"}'
            "}</script></body></html>"
        )
        url = "https://www.bestbuy.com/site/x/1234567.p?skuId=1234567"
        mentions = parse_bestbuy_pdp_reviews(
            html, url, anchors=[_anchor("x", url)]
        )
        assert len(mentions) == 1
        assert mentions[0].author == "PlainName"


# ---------------------------------------------------------------------------
# SKU extraction
# ---------------------------------------------------------------------------


class TestExtractSku:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.bestbuy.com/site/foo/6628371.p", "6628371"),
            ("https://www.bestbuy.com/site/foo/6628371.p/", "6628371"),
            ("https://www.bestbuy.com/site/foo/6628371.p?skuId=6628371", "6628371"),
            ("https://www.bestbuy.com/site/foo/bar?skuId=6628371", "6628371"),
        ],
    )
    def test_parses_expected(self, url, expected):
        assert _extract_sku(url) == expected

    def test_non_bestbuy_host_raises(self):
        with pytest.raises(ValueError, match="not bestbuy.com"):
            _extract_sku("https://www.amazon.com/site/foo/6628371.p")

    def test_no_sku_raises(self):
        with pytest.raises(ValueError, match="does not carry a SKU"):
            _extract_sku("https://www.bestbuy.com/site/foo/bar")


# ---------------------------------------------------------------------------
# Block detection — positives and negatives
# ---------------------------------------------------------------------------


class TestLooksBlocked:
    def test_real_pdp_not_blocked(self):
        html = _load(f"pdp_{AREA51_SKU}.html")
        assert _looks_blocked(html) is False

    def test_second_pdp_not_blocked(self):
        html = _load(f"pdp_{AURORA_SKU}.html")
        assert _looks_blocked(html) is False

    @pytest.mark.parametrize(
        "snippet",
        [
            "<p>Pardon Our Interruption</p>",
            "<title>Access Denied — edgesuite</title>",
            "<html>reference to errors.edgesuite.net here</html>",
        ],
    )
    def test_known_block_shapes_flagged(self, snippet):
        assert _looks_blocked(snippet) is True


# ---------------------------------------------------------------------------
# BlockedError propagation
# ---------------------------------------------------------------------------


class TestBlockedError:
    def test_parse_raises_on_block_page(self):
        html = "<html><body>Pardon Our Interruption</body></html>"
        with pytest.raises(BlockedError):
            parse_bestbuy_pdp_reviews(
                html,
                AREA51_URL,
                anchors=[_anchor("alienware_area_51_18", AREA51_URL)],
            )


# ---------------------------------------------------------------------------
# No JSON-LD at all
# ---------------------------------------------------------------------------


class TestNoJsonLd:
    def test_empty_review_list_when_no_product_jsonld(self):
        html = "<html><body><p>no structured data here</p></body></html>"
        mentions = parse_bestbuy_pdp_reviews(
            html,
            AREA51_URL,
            anchors=[_anchor("alienware_area_51_18", AREA51_URL)],
        )
        assert mentions == []


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registered_under_bestbuy_reviews(self):
        assert get_fetcher(SOURCE_REVIEWS) is bestbuy.fetch_bestbuy_reviews

    def test_source_constants(self):
        assert SOURCE == "bestbuy"
        assert SOURCE_REVIEWS == "bestbuy_reviews"
