"""Unit tests for scrapers_lib.tier2.asus.

Tests run against committed ROG spec-page HTML fixtures captured during
Wave 2b reconnaissance. No network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from scrapers_lib.core.registry import list_fetchers
from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier2 import asus
from scrapers_lib.tier2.asus import (
    _clean_variant_text,
    _collect_variant_rows,
    _config_summary,
    _find_spec_title_h2s,
    _flatten_spec_sections,
    _jsonld_shared,
    _source_id_from_url,
    parse_asus_product_page,
)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


FIX = Path(__file__).parent / "fixtures" / "asus"

STRIX_URL = "https://rog.asus.com/laptops/rog-strix/rog-strix-g16-2025/spec/"
ZEPHYRUS_URL = (
    "https://rog.asus.com/laptops/rog-zephyrus/rog-zephyrus-g16-2026/spec/"
)


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _anchor(anchor_id: str, url: str) -> Anchor:
    return Anchor(
        anchor_id=anchor_id,
        anchor_type="product",
        name=anchor_id.replace("_", " ").title(),
        attribution_regex=AttributionRegex(primary=[anchor_id]),
        source_urls={"asus": url},
    )


# ---------------------------------------------------------------------------
# parse_asus_product_page — ROG Strix G16 2025
# ---------------------------------------------------------------------------


class TestParseStrixG16Full:
    @pytest.fixture
    def snapshot(self):
        html = _load("rog_strix_g16_2025_spec.html")
        snaps = parse_asus_product_page(
            html,
            STRIX_URL,
            anchors=[_anchor("asus_rog_strix_g16_2025", STRIX_URL)],
        )
        assert len(snaps) == 1
        return snaps[0]

    def test_source_is_asus(self, snapshot):
        assert snapshot.source == "asus"

    def test_source_id_from_url_slug(self, snapshot):
        assert snapshot.source_id == "rog-strix-g16-2025"

    def test_variant_key_is_none(self, snapshot):
        # Per-model granularity; option alternatives live inside specs.
        assert snapshot.variant_key is None

    def test_brand_is_asus_not_sub_brand(self, snapshot):
        # JSON-LD on ROG pages declares brand "ROG"; we normalize to parent
        # brand "ASUS" so consumers grouping by brand don't get a split
        # across ASUS/ROG/TUF sub-brands.
        assert snapshot.brand == "ASUS"
        # Sub-brand preserved in raw for anyone who wants it.
        assert snapshot.raw["jsonld_brand"] == "ROG"

    def test_anchor_id(self, snapshot):
        assert snapshot.anchor_id == "asus_rog_strix_g16_2025"

    def test_title_from_jsonld(self, snapshot):
        assert "ROG Strix G16" in snapshot.title
        assert "2025" in snapshot.title

    def test_image_url(self, snapshot):
        assert snapshot.image_url and snapshot.image_url.startswith("http")

    def test_no_prices(self, snapshot):
        # rog.asus.com is marketing, not shop — no prices, ever.
        assert snapshot.price is None
        assert snapshot.list_price is None
        assert snapshot.in_stock is None
        assert snapshot.rating is None

    def test_raw_provenance(self, snapshot):
        assert snapshot.raw["spec_source"] == "rog_spec_page"
        assert snapshot.raw["product_slug"] == "rog-strix-g16-2025"

    def test_spec_categories_present(self, snapshot):
        # ROG publishes a rich spec sheet — expect all the categories HP
        # couldn't deliver plus the standard five.
        for expected in [
            "Operating System",
            "Processor",
            "Graphics",
            "Display",
            "Memory",
            "Storage",
            "I/O Ports",
            "Weight",
            "Dimensions (W x D x H)",
            "Power Supply",
            "Security",
            "Network and Communication",
            "Battery",
            "Camera",
            "Audio",
            "Keyboard and Touchpad",
        ]:
            assert expected in snapshot.specs, f"missing spec category {expected!r}"

    def test_spec_count_reasonable(self, snapshot):
        # Strix G16 has 20+ categories.
        assert len(snapshot.specs) >= 20

    def test_variant_dedup(self, snapshot):
        # Weight is identical across every SKU variant; ASUS emits 22 rows
        # but dedup collapses to 1.
        assert snapshot.specs["Weight"].count("\n") == 0
        assert "Kg" in snapshot.specs["Weight"]
        assert "lbs" in snapshot.specs["Weight"]

    def test_multi_sku_variants_preserved(self, snapshot):
        # Processor has multiple distinct CPU options across variants.
        proc = snapshot.specs["Processor"]
        assert "\n" in proc
        alternatives = proc.split("\n")
        assert len(alternatives) >= 3
        # Different processor families must be represented.
        joined = proc
        assert "Ultra 7" in joined
        assert "Ultra 9" in joined

    def test_ports_detail(self, snapshot):
        # HP's fetcher couldn't deliver this — ASUS ships it plainly.
        ports = snapshot.specs["I/O Ports"]
        assert "HDMI" in ports
        assert "Thunderbolt" in ports
        assert "USB" in ports

    def test_dimensions_in_both_units(self, snapshot):
        dims = snapshot.specs["Dimensions (W x D x H)"]
        assert "cm" in dims
        assert '"' in dims  # inch marks

    def test_symbol_whitespace_tight(self, snapshot):
        # BS4 pulls <sup>®</sup> out of its word; verify we re-tighten.
        joined = "\n".join(snapshot.specs.values())
        # A leading-space before ® must not remain.
        assert " ®" not in joined
        # Positive: the symbols did arrive.
        assert "®" in joined
        assert "™" in joined


# ---------------------------------------------------------------------------
# parse_asus_product_page — ROG Zephyrus G16 2026 (generality)
# ---------------------------------------------------------------------------


class TestParseZephyrusG16Full:
    """Generality: different ROG subline (Zephyrus vs Strix) + different year.

    The parser must not hard-code Strix-specific category names — if ASUS
    drops or adds a category on different product lines (Zephyrus omits
    "AURA SYNC" which Strix has), we still emit whatever is there.
    """

    @pytest.fixture
    def snapshot(self):
        html = _load("rog_zephyrus_g16_2026_spec.html")
        snaps = parse_asus_product_page(
            html,
            ZEPHYRUS_URL,
            anchors=[_anchor("asus_rog_zephyrus_g16_2026", ZEPHYRUS_URL)],
        )
        assert len(snaps) == 1
        return snaps[0]

    def test_source_id(self, snapshot):
        assert snapshot.source_id == "rog-zephyrus-g16-2026"

    def test_brand_is_asus(self, snapshot):
        assert snapshot.brand == "ASUS"

    def test_title(self, snapshot):
        assert "Zephyrus" in snapshot.title

    def test_common_categories(self, snapshot):
        # The always-present axes for any ROG laptop.
        for expected in ["Processor", "Graphics", "Memory", "Storage", "Display"]:
            assert expected in snapshot.specs

    def test_spec_count_reasonable(self, snapshot):
        assert len(snapshot.specs) >= 18


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------


class TestSourceIdFromUrl:
    def test_spec_form(self):
        assert (
            _source_id_from_url(
                "https://rog.asus.com/laptops/rog-strix/rog-strix-g16-2025/spec/"
            )
            == "rog-strix-g16-2025"
        )

    def test_product_root_form(self):
        assert (
            _source_id_from_url(
                "https://rog.asus.com/laptops/rog-strix/rog-strix-g16-2025/"
            )
            == "rog-strix-g16-2025"
        )

    def test_no_trailing_slash(self):
        assert (
            _source_id_from_url(
                "https://rog.asus.com/laptops/rog-zephyrus/rog-zephyrus-g16-2026"
            )
            == "rog-zephyrus-g16-2026"
        )

    def test_asus_domain_also_ok(self):
        # The fetcher host check accepts any asus.com subdomain; hostname
        # validation still bans non-asus hosts.
        _source_id_from_url(
            "https://asus.com/laptops/rog-strix/rog-strix-g16-2025/"
        )

    def test_non_asus_host_raises(self):
        with pytest.raises(ValueError, match="not an asus.com domain"):
            _source_id_from_url(
                "https://rog.msi.com/laptops/raider/titan-16/spec/"
            )

    def test_wrong_path_shape_raises(self):
        with pytest.raises(ValueError, match="does not match"):
            _source_id_from_url("https://rog.asus.com/motherboards/x870-e")

    def test_marketing_landing_rejected(self):
        # /laptops/<series> (no second segment) is a series index, not a
        # product page; reject it.
        with pytest.raises(ValueError, match="does not match"):
            _source_id_from_url(
                "https://rog.asus.com/laptops/rog-strix-series/"
            )


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


class TestAttribution:
    def test_no_anchors_raises(self):
        html = _load("rog_strix_g16_2025_spec.html")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_asus_product_page(html, STRIX_URL)

    def test_anchor_url_mismatch_raises(self):
        html = _load("rog_strix_g16_2025_spec.html")
        wrong = _anchor("wrong", ZEPHYRUS_URL)  # real URL, wrong product
        with pytest.raises(ValueError, match="no Anchor"):
            parse_asus_product_page(html, STRIX_URL, anchors=[wrong])

    def test_matching_anchor_used(self):
        html = _load("rog_strix_g16_2025_spec.html")
        a = _anchor("chosen_one", STRIX_URL)
        snaps = parse_asus_product_page(html, STRIX_URL, anchors=[a])
        assert snaps[0].anchor_id == "chosen_one"


# ---------------------------------------------------------------------------
# Structural error
# ---------------------------------------------------------------------------


class TestStructuralError:
    def test_missing_h2_spec_blocks_raises(self):
        # Page HTML with valid URL but no recognized h2 blocks.
        html = "<html><body><h2>Some unrelated heading</h2></body></html>"
        with pytest.raises(RuntimeError, match="no <h2"):
            parse_asus_product_page(
                html,
                STRIX_URL,
                anchors=[_anchor("asus_rog_strix_g16_2025", STRIX_URL)],
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestFindSpecTitleH2s:
    def test_matches_by_class_prefix(self):
        soup = BeautifulSoup(
            '<h2 class="ProductSpec__productSpecItemTitle__aB1">Processor</h2>'
            '<h2 class="ProductSpec__productSpecItemTitle__xY9">Memory</h2>'
            '<h2 class="SomeUnrelated__title__q">Unrelated</h2>',
            "html.parser",
        )
        titles = _find_spec_title_h2s(soup)
        assert [h.get_text(strip=True) for h in titles] == ["Processor", "Memory"]

    def test_no_matches(self):
        soup = BeautifulSoup("<h2>Not a spec heading</h2>", "html.parser")
        assert _find_spec_title_h2s(soup) == []


class TestCollectVariantRows:
    def test_preserves_first_occurrence_order(self):
        soup = BeautifulSoup(
            '<div>'
            '  <div class="ProductSpec__rowItem__A">A</div>'
            '  <div class="ProductSpec__rowItem__B">B</div>'
            '  <div class="ProductSpec__rowItem__C">A</div>'  # dup of first
            '  <div class="ProductSpec__rowItem__D">C</div>'
            '</div>',
            "html.parser",
        )
        val_div = soup.div
        assert _collect_variant_rows(val_div) == ["A", "B", "C"]

    def test_fallback_when_no_class_match(self):
        # If ASUS ever changes the hash prefix, we still fall back to
        # any direct <div> children so we don't silently emit nothing.
        soup = BeautifulSoup(
            '<div><div>alpha</div><div>beta</div><div>alpha</div></div>',
            "html.parser",
        )
        val_div = soup.div
        assert _collect_variant_rows(val_div) == ["alpha", "beta"]

    def test_empty_div(self):
        soup = BeautifulSoup("<div></div>", "html.parser")
        assert _collect_variant_rows(soup.div) == []


class TestCleanVariantText:
    def test_tightens_registered_and_trademark_whitespace(self):
        soup = BeautifulSoup(
            "<div>Intel <sup>®</sup> Core<sup>™</sup> Ultra 9</div>",
            "html.parser",
        )
        assert _clean_variant_text(soup.div) == "Intel® Core™ Ultra 9"

    def test_decodes_html_entities(self):
        soup = BeautifulSoup(
            "<div>A &amp; B &trade;</div>", "html.parser"
        )
        # Entities decoded; the whitespace-tightening rule also collapses
        # the space before ™ (same rule that fixes "Intel ® Core" → "Intel®").
        assert _clean_variant_text(soup.div) == "A & B™"

    def test_collapses_whitespace(self):
        soup = BeautifulSoup(
            "<div>  lots   of    whitespace   </div>", "html.parser"
        )
        assert _clean_variant_text(soup.div) == "lots of whitespace"


class TestFlattenSpecSections:
    def test_builds_category_to_variants_map(self):
        soup = BeautifulSoup(
            '<div>'
            '  <h2 class="ProductSpec__productSpecItemTitle__x">Processor</h2>'
            '  <div>'
            '    <div class="ProductSpec__rowItem__a">CPU A</div>'
            '    <div class="ProductSpec__rowItem__b">CPU B</div>'
            '  </div>'
            '</div>',
            "html.parser",
        )
        out = _flatten_spec_sections(soup)
        assert out == {"Processor": "CPU A\nCPU B"}


class TestJsonldShared:
    def test_brand_from_nested_dict(self):
        assert _jsonld_shared({"brand": {"name": "ROG"}}).get("brand") == "ROG"

    def test_brand_as_string(self):
        assert _jsonld_shared({"brand": "ROG"}).get("brand") == "ROG"

    def test_offers_single_dict(self):
        s = _jsonld_shared(
            {"offers": {"price": "1999.00", "priceCurrency": "USD"}}
        )
        from decimal import Decimal
        assert s["price_low"] == Decimal("1999.00")
        assert s["price_high"] == Decimal("1999.00")
        assert s["currency"] == "USD"

    def test_offers_list_spans_range(self):
        s = _jsonld_shared(
            {"offers": [
                {"price": "1500.00", "priceCurrency": "USD"},
                {"price": "2500.00", "priceCurrency": "USD"},
            ]}
        )
        from decimal import Decimal
        assert s["price_low"] == Decimal("1500.00")
        assert s["price_high"] == Decimal("2500.00")

    def test_image_first_of_list(self):
        s = _jsonld_shared({"image": ["https://a.png", "https://b.png"]})
        assert s["image"] == "https://a.png"


class TestConfigSummary:
    def test_picks_gpu_ram_storage_display(self):
        specs = {
            "Processor": "Core Ultra 9",
            "Graphics": "RTX 5090\nRTX 5080",
            "Memory": "32GB DDR5\n64GB DDR5",
            "Storage": "1TB SSD\n2TB SSD",
            "Display": "16\" 240Hz OLED",
            "Camera": "1080p",
        }
        summary = _config_summary(specs)
        assert summary is not None
        parts = summary.split(" / ")
        assert len(parts) == 4
        assert "RTX" in parts[0]
        assert "DDR5" in parts[1]
        assert "SSD" in parts[2]

    def test_empty_specs_returns_none(self):
        assert _config_summary({}) is None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistered:
    def test_asus_in_registry(self):
        assert "asus" in list_fetchers()

    def test_registered_callable_is_fetch_asus_product(self):
        from scrapers_lib.core.registry import get_fetcher

        assert get_fetcher("asus") is asus.fetch_asus_product
