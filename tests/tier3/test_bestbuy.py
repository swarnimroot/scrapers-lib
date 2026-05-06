"""Unit tests for scrapers_lib.tier3.bestbuy.

Tests run against committed BestBuy HTML fixtures. Wave 2c captured two
PDP fixtures (6628371 Area-51 18" + 6630638 16X Aurora 16") for the
default path; Wave 2d added three reviews-page fixtures from the same
SKU (reviews_6628371_page1..3.html) for the paginated path. All fixtures
were fetched via curl_cffi + Chrome impersonation + HTTP/1.1 (the
combination that gets past Akamai's HTTP/2 RST-stream gate). No network.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from scrapers_lib.core.registry import get_fetcher
from scrapers_lib.core.schemas import Anchor, Attribution, AttributionRegex
from scrapers_lib.core.scheduler import BlockedError
from scrapers_lib.tier3 import bestbuy
from scrapers_lib.tier3.bestbuy import (
    SOURCE,
    SOURCE_REVIEWS,
    _extract_helpful_count,
    _extract_ownership_duration,
    _extract_sku,
    _extract_verified_purchase,
    _get_soup,
    _has_next_reviews_page,
    _iter_reviews,
    _looks_blocked,
    _parse_bestbuy_date,
    _parse_review_item,
    fetch_bestbuy_reviews,
    parse_bestbuy_pdp_reviews,
    parse_bestbuy_reviews_page,
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

    @pytest.mark.parametrize(
        "url,expected",
        [
            (
                "https://www.bestbuy.com/product/foo-bar/J3K4L6J65W/sku/6630640",
                "6630640",
            ),
            (
                "https://www.bestbuy.com/product/foo-bar/J3K4L6J65W/sku/6630640/",
                "6630640",
            ),
            (
                "https://www.bestbuy.com/product/foo/J3K4L6J65W/sku/6630640?ref=top",
                "6630640",
            ),
        ],
    )
    def test_modern_path_form_parses(self, url, expected):
        assert _extract_sku(url) == expected

    def test_html_fallback_extracts_skuId_from_meta_unescaped(self):
        html = '<script>{"skuId":"6628371","bsin":"JJGGLHJLTS"}</script>'
        url = "https://www.bestbuy.com/product/foo/JJGGLHJLTS"
        assert _extract_sku(url, html=html) == "6628371"

    def test_html_fallback_extracts_skuId_from_meta_escaped(self):
        # The actual analytics-metadata meta tag stores the JSON in an
        # HTML attribute, so quotes are escaped as ``&quot;``.
        html = (
            '<meta name="analytics-metadata" '
            'content="{&quot;skuId&quot;:&quot;6628371&quot;}"/>'
        )
        url = "https://www.bestbuy.com/product/foo/JJGGLHJLTS"
        assert _extract_sku(url, html=html) == "6628371"

    def test_url_sku_takes_precedence_over_html(self):
        html = '{"skuId":"9999999"}'
        url = "https://www.bestbuy.com/site/foo/6628371.p"
        assert _extract_sku(url, html=html) == "6628371"

    def test_no_sku_in_url_or_html_raises(self):
        url = "https://www.bestbuy.com/product/foo/JJGGLHJLTS"
        html = "<html>no analytics metadata here</html>"
        with pytest.raises(ValueError, match="does not carry a SKU"):
            _extract_sku(url, html=html)

    def test_html_fallback_uses_real_pdp_fixture(self):
        # The fixture HTML contains the ``"skuId":"6628371"`` analytics
        # metadata tag; URL has only a synthetic model id, no SKU.
        html = _load(f"pdp_{AREA51_SKU}.html")
        url = "https://www.bestbuy.com/product/foo/J3K4L6QTGK"
        assert _extract_sku(url, html=html) == AREA51_SKU


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


# ---------------------------------------------------------------------------
# Wave 2d — reviews-page pagination
# ---------------------------------------------------------------------------


def _area51_attribution() -> Attribution:
    return Attribution(
        anchor_id="alienware_area_51_18",
        confidence=1.0,
        method="url_map",
        matched_tokens=[],
    )


class TestParseReviewsPageArea51:
    """parse_bestbuy_reviews_page against the real page-1 fixture (SKU 6628371)."""

    @pytest.fixture
    def mentions(self):
        html = _load(f"reviews_{AREA51_SKU}_page1.html")
        return parse_bestbuy_reviews_page(
            html,
            product_url=AREA51_URL,
            sku=AREA51_SKU,
            attribution=_area51_attribution(),
        )

    def test_page1_returns_20_reviews(self, mentions):
        # BestBuy paginates at 20/page; exact count is stable for a
        # frozen fixture. If the fixture is ever re-captured and the
        # per-page count changes upstream, this is the early warning.
        assert len(mentions) == 20

    def test_all_have_non_empty_body(self, mentions):
        for m in mentions:
            assert m.raw_text.strip()

    def test_all_have_published_at_as_utc_datetime(self, mentions):
        # Wave 2d's headline capability: every review has a real timestamp.
        for m in mentions:
            assert isinstance(m.published_at, datetime)
            assert m.published_at.tzinfo is timezone.utc

    def test_all_have_author(self, mentions):
        for m in mentions:
            assert m.author

    def test_all_have_title(self, mentions):
        for m in mentions:
            assert m.source_title

    def test_all_have_star_rating_in_range(self, mentions):
        for m in mentions:
            r = m.raw["star_rating"]
            assert r is not None and 0.0 <= r <= 5.0

    def test_all_have_helpful_count_integer_or_none(self, mentions):
        for m in mentions:
            hc = m.raw["helpful_count"]
            assert hc is None or isinstance(hc, int)

    def test_verified_purchase_flag_is_bool(self, mentions):
        # Extractor should always emit a boolean, never None or missing.
        for m in mentions:
            assert isinstance(m.raw["verified_purchase"], bool)

    def test_some_reviews_are_verified_purchase(self, mentions):
        # Fixture observation (SKU 6628371 page 1 captured 2026-04-22):
        # 6 of 20 reviews carry the Verified Purchase badge. Assert at
        # least one — confirms the extractor finds the badge when it's
        # present, without depending on an assumed verified/unverified mix.
        verified_count = sum(1 for m in mentions if m.raw["verified_purchase"])
        assert verified_count >= 1

    def test_source_is_bestbuy(self, mentions):
        assert mentions[0].source == "bestbuy"

    def test_source_type_is_post(self, mentions):
        assert mentions[0].source_type == "post"

    def test_parent_id_is_sku(self, mentions):
        assert mentions[0].parent_id == AREA51_SKU

    def test_mention_ids_unique(self, mentions):
        ids = [m.mention_id for m in mentions]
        assert len(ids) == len(set(ids))

    def test_attribution_reused_from_caller(self, mentions):
        # Every mention gets the same Attribution object passed in (not
        # re-resolved per-review) — lighter on the CPU and keeps all
        # reviews on one page pointing at the same anchor.
        anchor_ids = {m.attribution.anchor_id for m in mentions}
        assert anchor_ids == {"alienware_area_51_18"}


class TestPublishedAtParsing:
    """Cross-page: dates land inside a plausible window."""

    def test_dates_span_recent_years(self):
        html = _load(f"reviews_{AREA51_SKU}_page1.html")
        mentions = parse_bestbuy_reviews_page(
            html,
            product_url=AREA51_URL,
            sku=AREA51_SKU,
            attribution=_area51_attribution(),
        )
        years = {m.published_at.year for m in mentions}
        # Wave 2d recon observed 2025-2026 dates on this fixture. Widen
        # tolerance for any future re-capture of the same SKU.
        assert all(2020 <= y <= 2030 for y in years)


class TestNoDuplicatesAcrossPages:
    """page 1 and page 2 must return disjoint mention_id sets."""

    def test_page1_and_page2_have_no_duplicate_ids(self):
        p1_html = _load(f"reviews_{AREA51_SKU}_page1.html")
        p2_html = _load(f"reviews_{AREA51_SKU}_page2.html")
        attribution = _area51_attribution()
        p1 = parse_bestbuy_reviews_page(
            p1_html, product_url=AREA51_URL, sku=AREA51_SKU, attribution=attribution
        )
        p2 = parse_bestbuy_reviews_page(
            p2_html, product_url=AREA51_URL, sku=AREA51_SKU, attribution=attribution
        )
        ids1 = {m.mention_id for m in p1}
        ids2 = {m.mention_id for m in p2}
        assert ids1 and ids2
        assert ids1.isdisjoint(ids2)


class TestHasNextReviewsPage:
    def test_page1_real_fixture_has_next(self):
        html = _load(f"reviews_{AREA51_SKU}_page1.html")
        assert _has_next_reviews_page(html) is True

    def test_synthetic_page_without_next_link(self):
        html = "<html><head></head><body>No rel=next here.</body></html>"
        assert _has_next_reviews_page(html) is False

    def test_case_insensitive_rel_attr(self):
        html = '<link REL="NEXT" href="...">'
        assert _has_next_reviews_page(html) is True


class TestParseBestbuyDate:
    @pytest.mark.parametrize(
        "title_attr,expected",
        [
            ("Jan 1, 2026 9:24 AM", datetime(2026, 1, 1, 9, 24, tzinfo=timezone.utc)),
            ("Apr 16, 2025 12:00 PM", datetime(2025, 4, 16, 12, 0, tzinfo=timezone.utc)),
            ("Dec 31, 2024 11:59 PM", datetime(2024, 12, 31, 23, 59, tzinfo=timezone.utc)),
        ],
    )
    def test_parses_expected_format(self, title_attr, expected):
        assert _parse_bestbuy_date(title_attr) == expected

    def test_none_passthrough(self):
        assert _parse_bestbuy_date(None) is None

    def test_empty_string_passthrough(self):
        assert _parse_bestbuy_date("") is None

    def test_unparseable_returns_none(self):
        assert _parse_bestbuy_date("2026-01-01T09:24:00Z") is None

    def test_whitespace_tolerated(self):
        assert _parse_bestbuy_date(" Jan 1, 2026 9:24 AM ") == datetime(
            2026, 1, 1, 9, 24, tzinfo=timezone.utc
        )


class TestExtractHelpfulCount:
    @pytest.mark.parametrize(
        "aria_label,expected",
        [
            ("Rate this review as helpful. 0 people found this review to be helpful.", 0),
            ("Rate this review as helpful. 1 person found this review to be helpful.", 1),
            ("Rate this review as helpful. 42 people found this review to be helpful.", 42),
        ],
    )
    def test_parses_aria_label(self, aria_label, expected):
        html = f'<li><button class="helpfulness-button" aria-label="{aria_label}"></button></li>'
        li = _get_soup(html).find("li")
        assert _extract_helpful_count(li) == expected

    def test_missing_button_returns_none(self):
        li = _get_soup("<li><p>no button</p></li>").find("li")
        assert _extract_helpful_count(li) is None

    def test_unparseable_aria_label_returns_none(self):
        html = '<li><button class="helpfulness-button" aria-label="Some other text."></button></li>'
        li = _get_soup(html).find("li")
        assert _extract_helpful_count(li) is None


class TestExtractVerifiedPurchase:
    def test_detects_verified_badge(self):
        html = '<li><button data-track="Verified Purchase Badge">VP</button></li>'
        li = _get_soup(html).find("li")
        assert _extract_verified_purchase(li) is True

    def test_absent_badge(self):
        html = '<li><button data-track="Review">R</button></li>'
        li = _get_soup(html).find("li")
        assert _extract_verified_purchase(li) is False


class TestExtractOwnershipDuration:
    @pytest.mark.parametrize(
        "fragment,expected",
        [
            ("Posted 3 months ago. Owned for 2 weeks when reviewed.", "2 weeks"),
            ("Owned for 6 months when reviewed.", "6 months"),
            ("Owned for less than 1 week when reviewed.", "less than 1 week"),
        ],
    )
    def test_extracts_duration(self, fragment, expected):
        li = _get_soup(f"<li>{fragment}</li>").find("li")
        assert _extract_ownership_duration(li) == expected

    def test_absent_phrase_returns_none(self):
        li = _get_soup("<li>no ownership text here</li>").find("li")
        assert _extract_ownership_duration(li) is None


class TestParseReviewItemTolerance:
    """_parse_review_item handles malformed / partial review <li> cleanly."""

    def test_missing_jsonld_script_returns_none(self):
        html = '<li class="review-item"><p>no json-ld here</p></li>'
        li = _get_soup(html).find("li")
        assert (
            _parse_review_item(
                li,
                sku=AREA51_SKU,
                product_url=AREA51_URL,
                attribution=_area51_attribution(),
            )
            is None
        )

    def test_jsonld_wrong_type_returns_none(self):
        html = (
            '<li class="review-item">'
            '<script type="application/ld+json">{"@type":"Product"}</script>'
            "</li>"
        )
        li = _get_soup(html).find("li")
        assert (
            _parse_review_item(
                li,
                sku=AREA51_SKU,
                product_url=AREA51_URL,
                attribution=_area51_attribution(),
            )
            is None
        )

    def test_malformed_json_returns_none(self):
        html = (
            '<li class="review-item">'
            '<script type="application/ld+json">{not valid json}</script>'
            "</li>"
        )
        li = _get_soup(html).find("li")
        assert (
            _parse_review_item(
                li,
                sku=AREA51_SKU,
                product_url=AREA51_URL,
                attribution=_area51_attribution(),
            )
            is None
        )

    def test_empty_body_returns_none(self):
        html = (
            '<li class="review-item">'
            '<script type="application/ld+json">'
            '{"@type":"Review","name":"Title","author":{"name":"A"},"reviewBody":""}'
            "</script></li>"
        )
        li = _get_soup(html).find("li")
        assert (
            _parse_review_item(
                li,
                sku=AREA51_SKU,
                product_url=AREA51_URL,
                attribution=_area51_attribution(),
            )
            is None
        )

    def test_missing_time_element_gives_none_published_at(self):
        html = (
            '<li class="review-item">'
            '<script type="application/ld+json">'
            '{"@type":"Review","name":"T","author":{"name":"A"},'
            '"reviewBody":"Body","reviewRating":{"ratingValue":5}}'
            "</script></li>"
        )
        li = _get_soup(html).find("li")
        m = _parse_review_item(
            li,
            sku=AREA51_SKU,
            product_url=AREA51_URL,
            attribution=_area51_attribution(),
        )
        assert m is not None
        assert m.published_at is None


class TestPaginatedBlockDetection:
    def test_block_page_raises(self):
        html = "<html><body>Pardon Our Interruption</body></html>"
        with pytest.raises(BlockedError):
            parse_bestbuy_reviews_page(
                html,
                product_url=AREA51_URL,
                sku=AREA51_SKU,
                attribution=_area51_attribution(),
            )


class TestPaginateOrchestration:
    """fetch_bestbuy_reviews(paginate=True) with mocked I/O."""

    def test_attribution_required(self):
        with pytest.raises(ValueError, match="no Anchor"):
            fetch_bestbuy_reviews(AREA51_URL, anchors=[], paginate=True)

    def test_walks_until_no_rel_next(self):
        p1_html = _load(f"reviews_{AREA51_SKU}_page1.html")
        p2_html = _load(f"reviews_{AREA51_SKU}_page2.html")
        # Strip rel=next from p2 to simulate end-of-data.
        p2_truncated = p2_html.replace('rel="next"', 'rel="other"')

        pages = [(p1_html, 1), (p2_truncated, 2), ("<html></html>", 3)]

        def fake_iter(sku, **kwargs):
            for h, p in pages:
                yield h, p

        with patch.object(bestbuy, "_iter_reviews_pages", side_effect=fake_iter):
            mentions = fetch_bestbuy_reviews(
                AREA51_URL,
                anchors=[_anchor("alienware_area_51_18", AREA51_URL)],
                paginate=True,
            )
        # p1 has 20 reviews + p2 has 20 reviews; p3 never visited because
        # p2 had no rel=next.
        assert len(mentions) == 40

    def test_walks_until_empty_page(self):
        p1_html = _load(f"reviews_{AREA51_SKU}_page1.html")
        empty_html = "<html><body>no review-item here</body></html>"

        pages = [(p1_html, 1), (empty_html, 2), ("should never see this", 3)]

        def fake_iter(sku, **kwargs):
            for h, p in pages:
                yield h, p

        with patch.object(bestbuy, "_iter_reviews_pages", side_effect=fake_iter):
            mentions = fetch_bestbuy_reviews(
                AREA51_URL,
                anchors=[_anchor("alienware_area_51_18", AREA51_URL)],
                paginate=True,
            )
        # Only p1's 20 reviews — empty p2 terminated the walk before p3.
        assert len(mentions) == 20

    def test_default_paginate_false_hits_pdp_path(self):
        # Make sure paginate=False keeps the existing PDP behavior by
        # verifying _iter_reviews_pages is NEVER called.
        pdp_html = _load(f"pdp_{AREA51_SKU}.html")
        with patch.object(bestbuy, "_fetch_pdp", return_value=pdp_html) as fp, \
             patch.object(bestbuy, "_iter_reviews_pages") as fi:
            mentions = fetch_bestbuy_reviews(
                AREA51_URL,
                anchors=[_anchor("alienware_area_51_18", AREA51_URL)],
            )
        assert fp.called
        assert not fi.called
        assert mentions  # PDP path still produces reviews
