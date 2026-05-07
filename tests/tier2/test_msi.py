"""Unit tests for scrapers_lib.tier2.msi.

Tests run against committed MSI laptop HTML fixtures captured during
Wave 2f reconnaissance via a warmed curl_cffi + Chrome + HTTP/1.1
session. No network — Akamai bypass logic is exercised through mocks.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from scrapers_lib.core.registry import list_fetchers
from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier2 import msi
from scrapers_lib.tier2.msi import (
    _clean_cell_text,
    _config_summary,
    _extract_itemlist,
    _extract_spec_rows,
    _extract_variant_code,
    _extract_variant_headers,
    _find_itemlist_in,
    _find_spec_table,
    _flatten_itemlist,
    _jsonld_shared,
    _main_url_for_slug,
    _parse_url,
    _spec_url_for_slug,
    fetch_msi_product,
    parse_msi_main_page,
    parse_msi_specification_page,
)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


FIX = Path(__file__).parent / "fixtures" / "msi"

STEALTH_URL = "https://us.msi.com/Laptop/Stealth-16-AI-Plus-B3WX"
STEALTH_SPEC_URL = "https://us.msi.com/Laptop/Stealth-16-AI-Plus-B3WX/Specification"
RAIDER_MAIN_URL = "https://us.msi.com/Laptop/Raider-16-Max-HX-B2WX"
RAIDER_SPEC_URL = "https://us.msi.com/Laptop/Raider-16-Max-HX-B2WX/Specification"
CROSSHAIR_SPEC_URL = "https://us.msi.com/Laptop/Crosshair-16-HX-E14WX/Specification"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _anchor(anchor_id: str, url: str) -> Anchor:
    return Anchor(
        anchor_id=anchor_id,
        anchor_type="product",
        name=anchor_id.replace("_", " ").title(),
        attribution_regex=AttributionRegex(primary=[anchor_id]),
        source_urls={"msi": url},
    )


# ---------------------------------------------------------------------------
# parse_msi_main_page — Stealth (AI/Stealth, JSON-LD ItemList path)
# ---------------------------------------------------------------------------


class TestParseStealthMain:
    @pytest.fixture
    def snapshot(self):
        html = _load("stealth_16_ai_plus_b3wx_main.html")
        snaps = parse_msi_main_page(
            html,
            STEALTH_URL,
            anchors=[_anchor("msi_stealth_16_ai_plus", STEALTH_URL)],
        )
        assert len(snaps) == 1
        return snaps[0]

    def test_source_is_msi(self, snapshot):
        assert snapshot.source == "msi"

    def test_source_id_from_url_slug(self, snapshot):
        assert snapshot.source_id == "Stealth-16-AI-Plus-B3WX"

    def test_variant_key_is_none(self, snapshot):
        # Highlight ItemList is product-wide — no per-SKU split.
        assert snapshot.variant_key is None

    def test_brand_is_msi(self, snapshot):
        assert snapshot.brand == "MSI"

    def test_anchor_id(self, snapshot):
        assert snapshot.anchor_id == "msi_stealth_16_ai_plus"

    def test_title_from_jsonld(self, snapshot):
        # MSI's Product JSON-LD names the family ("Stealth 16 AI+ B3W").
        assert "Stealth 16 AI+" in snapshot.title

    def test_image_url_populated(self, snapshot):
        # Image may come from the Product JSON-LD OR be empty if MSI omits.
        # Stealth main page provides one.
        assert snapshot.image_url is None or snapshot.image_url.startswith("http")

    def test_no_prices(self, snapshot):
        # Main-page surface emits no price data.
        assert snapshot.price is None
        assert snapshot.list_price is None
        assert snapshot.in_stock is None

    def test_raw_provenance(self, snapshot):
        assert snapshot.raw["spec_source"] == "jsonld_itemlist"
        assert snapshot.raw["product_slug"] == "Stealth-16-AI-Plus-B3WX"
        assert snapshot.raw["itemlist_count"] == len(snapshot.specs)

    def test_specs_count_eleven(self, snapshot):
        assert len(snapshot.specs) == 11

    def test_specs_include_processor_graphics_display(self, snapshot):
        for k in ("Processor", "Graphics Card", "Display", "Operating System"):
            assert k in snapshot.specs, f"missing {k!r}"

    def test_processor_value_richness(self, snapshot):
        v = snapshot.specs["Processor"]
        assert "Intel" in v
        assert "Core" in v
        assert "Ultra 9" in v

    def test_graphics_value_richness(self, snapshot):
        v = snapshot.specs["Graphics Card"]
        assert "NVIDIA" in v
        assert "RTX" in v
        assert "5080" in v

    def test_html_entities_decoded_in_specs(self, snapshot):
        joined = "\n".join(snapshot.specs.values())
        assert "&trade;" not in joined
        assert "&reg;" not in joined
        assert "&amp;" not in joined

    def test_config_summary_shape(self, snapshot):
        summary = snapshot.config_summary
        assert summary is not None
        # GPU / RAM-or-Display / Storage / Display — ItemList lacks RAM
        # and Storage as dedicated keys, so the summary is shorter.
        assert "RTX" in summary or "GeForce" in summary


# ---------------------------------------------------------------------------
# parse_msi_main_page — Raider gaming (no ItemList → empty list)
# ---------------------------------------------------------------------------


class TestParseRaiderMainNoItemList:
    def test_returns_empty_list(self):
        html = _load("raider_16_max_hx_b2wx_main.html")
        snaps = parse_msi_main_page(
            html,
            RAIDER_MAIN_URL,
            anchors=[_anchor("msi_raider", RAIDER_MAIN_URL)],
        )
        # Gaming pages ship Product JSON-LD but no ItemList — caller is
        # expected to fall through to the /Specification table.
        assert snaps == []

    def test_attribution_still_validated(self):
        html = _load("raider_16_max_hx_b2wx_main.html")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_msi_main_page(html, RAIDER_MAIN_URL)


# ---------------------------------------------------------------------------
# parse_msi_specification_page — Raider (3 SKUs, gaming)
# ---------------------------------------------------------------------------


class TestParseRaiderSpec:
    @pytest.fixture
    def snapshots(self):
        html = _load("raider_16_max_hx_b2wx_specification.html")
        return parse_msi_specification_page(
            html,
            RAIDER_SPEC_URL,
            anchors=[_anchor("msi_raider_16_max_hx", RAIDER_SPEC_URL)],
        )

    def test_emits_three_snapshots(self, snapshots):
        assert len(snapshots) == 3

    def test_variant_keys(self, snapshots):
        keys = [s.variant_key for s in snapshots]
        assert keys == ["B2WH-004US", "B2WI-003US", "B2WJ-002US"]

    def test_source_ids_are_full_headers(self, snapshots):
        ids = [s.source_id for s in snapshots]
        assert all(i.startswith("Raider 16 Max HX ") for i in ids)
        assert ids[0].endswith("B2WH-004US")

    def test_all_anchor_id_propagated(self, snapshots):
        for s in snapshots:
            assert s.anchor_id == "msi_raider_16_max_hx"

    def test_all_brand_msi(self, snapshots):
        for s in snapshots:
            assert s.brand == "MSI"

    def test_all_url_unchanged(self, snapshots):
        for s in snapshots:
            assert s.url == RAIDER_SPEC_URL

    def test_per_sku_spec_count(self, snapshots):
        # Recon observed ~28 spec rows on Raider /Specification.
        for s in snapshots:
            assert len(s.specs) == 28

    def test_spec_keys_include_known_categories(self, snapshots):
        expected = {
            "CPU",
            "Operating Systems",
            "Display",
            "Chipset",
            "Discrete Graphics",
            "Video Memory",
            "Memory",
            "Storage",
            "Keyboard",
            "WebCam",
            "Audio",
            "USB Ports",
            "Wi-Fi/ Bluetooth",
            "Battery",
            "Dimension (WXDXH)",
            "Weight (W/ Battery)",
            "Warranty",
        }
        for s in snapshots:
            assert expected.issubset(set(s.specs.keys()))

    def test_per_sku_gpu_differs(self, snapshots):
        # Three SKUs ship different GPUs (5070 Ti / 5080 / 5090).
        gpus = [s.specs["Discrete Graphics"] for s in snapshots]
        assert len(set(gpus)) == 3
        assert "5070 Ti" in gpus[0]
        assert "5080" in gpus[1]
        assert "5090" in gpus[2]

    def test_per_sku_video_memory_differs(self, snapshots):
        vrams = [s.specs["Video Memory"] for s in snapshots]
        assert "12GB" in vrams[0]
        assert "16GB" in vrams[1]
        assert "24GB" in vrams[2]

    def test_raw_provenance_matches(self, snapshots):
        for i, s in enumerate(snapshots):
            assert s.raw["spec_source"] == "specification_table"
            assert s.raw["product_slug"] == "Raider-16-Max-HX-B2WX"
            assert s.raw["variant_index"] == i
            assert s.raw["variant_count"] == 3
            assert s.raw["variant_header"] == s.source_id

    def test_no_prices_on_specification_surface(self, snapshots):
        # Specification page is a static spec sheet — no price/availability.
        for s in snapshots:
            assert s.price is None
            assert s.list_price is None
            assert s.in_stock is None

    def test_html_entities_decoded(self, snapshots):
        joined = "\n".join(v for s in snapshots for v in s.specs.values())
        assert "&reg;" not in joined
        assert "&trade;" not in joined
        assert "&amp;" not in joined


# ---------------------------------------------------------------------------
# parse_msi_specification_page — Crosshair (2 SKUs, generality check)
# ---------------------------------------------------------------------------


class TestParseCrosshairSpec:
    @pytest.fixture
    def snapshots(self):
        html = _load("crosshair_16_hx_e14wx_specification.html")
        return parse_msi_specification_page(
            html,
            CROSSHAIR_SPEC_URL,
            anchors=[_anchor("msi_crosshair_16_hx", CROSSHAIR_SPEC_URL)],
        )

    def test_emits_two_snapshots(self, snapshots):
        assert len(snapshots) == 2

    def test_variant_keys(self, snapshots):
        keys = [s.variant_key for s in snapshots]
        assert keys == ["E14WFK-036US", "E14WGK-038US"]

    def test_per_sku_gpu_differs(self, snapshots):
        gpus = [s.specs["Discrete Graphics"] for s in snapshots]
        assert "5060" in gpus[0]
        assert "5070" in gpus[1]

    def test_variant_count_in_raw(self, snapshots):
        for s in snapshots:
            assert s.raw["variant_count"] == 2


# ---------------------------------------------------------------------------
# parse_msi_specification_page — Stealth (AI/Stealth on /Specification)
#
# This fixture backs the Specification-first default. AI/Stealth lines
# also expose /Specification with the same comprehensive ~27-field
# per-SKU table the gaming lines use; the ItemList highlight on the
# main page is now the fallback, not the default.
# ---------------------------------------------------------------------------


class TestParseStealthSpec:
    @pytest.fixture
    def snapshots(self):
        html = _load("stealth_16_ai_plus_b3wx_specification.html")
        return parse_msi_specification_page(
            html,
            STEALTH_SPEC_URL,
            anchors=[_anchor("msi_stealth_16_ai_plus", STEALTH_SPEC_URL)],
        )

    def test_emits_at_least_one_snapshot(self, snapshots):
        assert len(snapshots) >= 1

    def test_each_snapshot_has_at_least_25_fields(self, snapshots):
        # The new Specification-first default's main payoff: comprehensive
        # spec coverage for AI/Stealth SKUs (~27 fields), versus the ~11
        # the old ItemList default returned.
        for s in snapshots:
            assert len(s.specs) >= 25, (
                f"snapshot {s.variant_key} has {len(s.specs)} fields; "
                f"expected >= 25"
            )

    def test_variant_key_extracted(self, snapshots):
        # Stealth SKU codes share the B3W*-NNNUS shape.
        for s in snapshots:
            assert s.variant_key is not None
            assert s.variant_key.endswith("US")

    def test_spec_keys_include_known_categories(self, snapshots):
        expected = {
            "CPU",
            "Display",
            "Discrete Graphics",
            "Memory",
            "Storage",
            "Battery",
        }
        for s in snapshots:
            assert expected.issubset(set(s.specs.keys()))

    def test_raw_provenance_is_specification_table(self, snapshots):
        for s in snapshots:
            assert s.raw["spec_source"] == "specification_table"
            assert s.raw["product_slug"] == "Stealth-16-AI-Plus-B3WX"


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------


class TestParseUrl:
    def test_main_url(self):
        slug, surface = _parse_url(STEALTH_URL)
        assert slug == "Stealth-16-AI-Plus-B3WX"
        assert surface is None

    def test_specification_url(self):
        slug, surface = _parse_url(RAIDER_SPEC_URL)
        assert slug == "Raider-16-Max-HX-B2WX"
        assert surface == "Specification"

    def test_trailing_slash_ok(self):
        slug, surface = _parse_url(STEALTH_URL + "/")
        assert slug == "Stealth-16-AI-Plus-B3WX"
        assert surface is None

    def test_non_msi_host_raises(self):
        with pytest.raises(ValueError, match="not an msi.com domain"):
            _parse_url("https://www.dell.com/Laptop/some-slug")

    def test_bad_path_raises(self):
        with pytest.raises(ValueError, match="not /Laptop/"):
            _parse_url("https://us.msi.com/Desktop/some-slug")

    def test_main_url_for_slug(self):
        # /Specification → main
        assert _main_url_for_slug(RAIDER_SPEC_URL, "Raider-16-Max-HX-B2WX") == (
            "https://us.msi.com/Laptop/Raider-16-Max-HX-B2WX"
        )

    def test_spec_url_for_slug(self):
        assert _spec_url_for_slug(STEALTH_URL, "Stealth-16-AI-Plus-B3WX") == (
            "https://us.msi.com/Laptop/Stealth-16-AI-Plus-B3WX/Specification"
        )

    def test_non_us_host_logs_but_passes(self, caplog):
        # Regional URLs should not raise; they just produce a soft INFO.
        import logging

        with caplog.at_level(logging.INFO, logger="scrapers_lib.tier2.msi"):
            slug, surface = _parse_url(
                "https://de.msi.com/Laptop/Raider-16-Max-HX-B2WX"
            )
        assert slug == "Raider-16-Max-HX-B2WX"
        assert surface is None


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


class TestAttribution:
    def test_no_anchors_raises_on_main(self):
        html = _load("stealth_16_ai_plus_b3wx_main.html")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_msi_main_page(html, STEALTH_URL)

    def test_no_anchors_raises_on_spec(self):
        html = _load("raider_16_max_hx_b2wx_specification.html")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_msi_specification_page(html, RAIDER_SPEC_URL)

    def test_anchor_url_mismatch_raises(self):
        html = _load("raider_16_max_hx_b2wx_specification.html")
        wrong = _anchor("wrong", CROSSHAIR_SPEC_URL)
        with pytest.raises(ValueError, match="no Anchor"):
            parse_msi_specification_page(html, RAIDER_SPEC_URL, anchors=[wrong])

    def test_matching_anchor_used_on_spec(self):
        html = _load("raider_16_max_hx_b2wx_specification.html")
        a = _anchor("chosen_one", RAIDER_SPEC_URL)
        snaps = parse_msi_specification_page(html, RAIDER_SPEC_URL, anchors=[a])
        for s in snaps:
            assert s.anchor_id == "chosen_one"


# ---------------------------------------------------------------------------
# JSON-LD ItemList helpers
# ---------------------------------------------------------------------------


class TestExtractItemList:
    def test_extracts_from_stealth_fixture(self):
        html = _load("stealth_16_ai_plus_b3wx_main.html")
        item_list = _extract_itemlist(html)
        assert item_list is not None
        assert item_list.get("@type") == "ItemList"
        assert isinstance(item_list.get("itemListElement"), list)
        assert len(item_list["itemListElement"]) == 11

    def test_returns_none_on_gaming_fixture(self):
        html = _load("raider_16_max_hx_b2wx_main.html")
        assert _extract_itemlist(html) is None

    def test_returns_none_when_no_jsonld(self):
        assert _extract_itemlist("<html><body></body></html>") is None

    def test_skips_malformed_blocks(self):
        # A malformed first block should not stop a good second block.
        html = (
            '<html><head>'
            '<script type="application/ld+json">{not json}</script>'
            '<script type="application/ld+json">'
            '{"@type":"ItemList","itemListElement":[{"@type":"ListItem","position":1,"name":"X","description":"Y"}]}'
            '</script>'
            '</head></html>'
        )
        item_list = _extract_itemlist(html)
        assert item_list is not None
        assert item_list["@type"] == "ItemList"


class TestFindItemListIn:
    def test_finds_top_level(self):
        d = {"@type": "ItemList", "itemListElement": []}
        assert _find_itemlist_in(d) is d

    def test_finds_in_array(self):
        a = [{"@type": "Product"}, {"@type": "ItemList", "itemListElement": []}]
        assert _find_itemlist_in(a) is a[1]

    def test_finds_in_graph(self):
        d = {"@graph": [{"@type": "ItemList", "itemListElement": []}]}
        assert _find_itemlist_in(d) is d["@graph"][0]

    def test_returns_none_when_absent(self):
        assert _find_itemlist_in({"@type": "Product"}) is None
        assert _find_itemlist_in([]) is None
        assert _find_itemlist_in("string") is None


class TestFlattenItemList:
    def test_basic(self):
        item_list = {
            "itemListElement": [
                {"name": "Processor", "description": "Intel Core Ultra 9"},
                {"name": "Memory", "description": "32 GB DDR5"},
            ]
        }
        assert _flatten_itemlist(item_list) == {
            "Processor": "Intel Core Ultra 9",
            "Memory": "32 GB DDR5",
        }

    def test_preserves_first_occurrence_order(self):
        item_list = {
            "itemListElement": [
                {"name": "B", "description": "1"},
                {"name": "A", "description": "2"},
                {"name": "B", "description": "3"},  # dupe — drop
            ]
        }
        out = _flatten_itemlist(item_list)
        assert list(out.keys()) == ["B", "A"]
        assert out["B"] == "1"

    def test_html_entities_decoded(self):
        item_list = {
            "itemListElement": [
                {"name": "CPU", "description": "Intel&reg; Core&trade; &amp; AI"},
            ]
        }
        out = _flatten_itemlist(item_list)
        assert out["CPU"] == "Intel® Core™ & AI"

    def test_drops_missing_fields(self):
        item_list = {
            "itemListElement": [
                {"name": "", "description": "x"},
                {"name": "y", "description": ""},
                {"name": "OK", "description": "good"},
            ]
        }
        assert _flatten_itemlist(item_list) == {"OK": "good"}

    def test_non_list_returns_empty(self):
        assert _flatten_itemlist({"itemListElement": "oops"}) == {}

    def test_missing_key_returns_empty(self):
        assert _flatten_itemlist({}) == {}


# ---------------------------------------------------------------------------
# Spec-table extraction helpers
# ---------------------------------------------------------------------------


class TestFindSpecTable:
    def test_finds_class_match(self):
        html = (
            '<html><body>'
            '<table class="other"><tr><td>x</td></tr></table>'
            '<table class="table table-configurations">'
            '<tr><td>SKU</td></tr></table>'
            '</body></html>'
        )
        soup = BeautifulSoup(html, "html.parser")
        t = _find_spec_table(soup)
        assert t is not None
        assert "table-configurations" in t.get("class")

    def test_falls_back_to_first_table(self):
        # Defensive: if MSI drops the class, we still pick the first table.
        html = (
            "<html><body><table><tr><td>x</td></tr></table></body></html>"
        )
        soup = BeautifulSoup(html, "html.parser")
        assert _find_spec_table(soup) is not None

    def test_returns_none_when_no_table(self):
        soup = BeautifulSoup("<html><body></body></html>", "html.parser")
        assert _find_spec_table(soup) is None


class TestExtractVariantHeaders:
    def test_three_skus(self):
        html = _load("raider_16_max_hx_b2wx_specification.html")
        soup = BeautifulSoup(html, "html.parser")
        table = _find_spec_table(soup)
        headers = _extract_variant_headers(table)
        assert headers == [
            "Raider 16 Max HX B2WH-004US",
            "Raider 16 Max HX B2WI-003US",
            "Raider 16 Max HX B2WJ-002US",
        ]

    def test_two_skus(self):
        html = _load("crosshair_16_hx_e14wx_specification.html")
        soup = BeautifulSoup(html, "html.parser")
        table = _find_spec_table(soup)
        headers = _extract_variant_headers(table)
        assert len(headers) == 2

    def test_one_sku_synthetic(self):
        html = (
            '<table><thead><tr>'
            '<td>Show the Differences</td><td>Solo SKU XYZ-001US</td>'
            '</tr></thead><tbody></tbody></table>'
        )
        soup = BeautifulSoup(html, "html.parser")
        headers = _extract_variant_headers(soup.find("table"))
        assert headers == ["Solo SKU XYZ-001US"]

    def test_no_thead_returns_empty(self):
        html = "<table><tbody><tr><td>x</td></tr></tbody></table>"
        soup = BeautifulSoup(html, "html.parser")
        assert _extract_variant_headers(soup.find("table")) == []

    def test_empty_thead_returns_empty(self):
        html = "<table><thead></thead></table>"
        soup = BeautifulSoup(html, "html.parser")
        assert _extract_variant_headers(soup.find("table")) == []

    def test_strips_trailing_empty_cells(self):
        html = (
            '<table><thead><tr>'
            '<td>Show</td><td>SKU-A</td><td>SKU-B</td><td></td>'
            '</tr></thead></table>'
        )
        soup = BeautifulSoup(html, "html.parser")
        assert _extract_variant_headers(soup.find("table")) == ["SKU-A", "SKU-B"]


class TestExtractSpecRows:
    def test_three_skus_yields_padded_rows(self):
        html = _load("raider_16_max_hx_b2wx_specification.html")
        soup = BeautifulSoup(html, "html.parser")
        table = _find_spec_table(soup)
        rows = _extract_spec_rows(table, n_variants=3)
        assert len(rows) == 28
        for key, values in rows:
            assert key
            assert len(values) == 3

    def test_skips_promotional_rows_without_th(self):
        # Synthetic: tbody row whose first cell is <td>, not <th>.
        html = (
            "<table><tbody>"
            "<tr><td>Promo row</td><td>x</td></tr>"
            "<tr><th>CPU</th><td>Intel</td></tr>"
            "</tbody></table>"
        )
        soup = BeautifulSoup(html, "html.parser")
        rows = _extract_spec_rows(soup.find("table"), n_variants=1)
        assert rows == [("CPU", ["Intel"])]

    def test_pads_short_rows(self):
        html = (
            "<table><tbody>"
            "<tr><th>CPU</th><td>Intel</td></tr>"
            "</tbody></table>"
        )
        soup = BeautifulSoup(html, "html.parser")
        rows = _extract_spec_rows(soup.find("table"), n_variants=3)
        assert rows == [("CPU", ["Intel", "", ""])]

    def test_empty_tbody_returns_empty(self):
        html = "<table><tbody></tbody></table>"
        soup = BeautifulSoup(html, "html.parser")
        assert _extract_spec_rows(soup.find("table"), n_variants=2) == []

    def test_no_tbody_returns_empty(self):
        html = "<table></table>"
        soup = BeautifulSoup(html, "html.parser")
        assert _extract_spec_rows(soup.find("table"), n_variants=2) == []

    def test_drops_empty_key_rows(self):
        html = (
            "<table><tbody>"
            "<tr><th></th><td>orphan</td></tr>"
            "</tbody></table>"
        )
        soup = BeautifulSoup(html, "html.parser")
        assert _extract_spec_rows(soup.find("table"), n_variants=1) == []


class TestCleanCellText:
    def test_decodes_entities(self):
        soup = BeautifulSoup("<td>Intel&reg; Core&trade;</td>", "html.parser")
        assert _clean_cell_text(soup.find("td")) == "Intel® Core™"

    def test_collapses_whitespace(self):
        soup = BeautifulSoup(
            "<td>line1<br/>   line2\n\t\tline3</td>", "html.parser"
        )
        # <br/> renders as separator → spaces collapse around it.
        out = _clean_cell_text(soup.find("td"))
        assert "line1" in out and "line2" in out and "line3" in out
        assert "  " not in out  # no double-spaces


# ---------------------------------------------------------------------------
# Variant-code extraction
# ---------------------------------------------------------------------------


class TestExtractVariantCode:
    @pytest.mark.parametrize(
        "header,expected",
        [
            ("Raider 16 Max HX B2WH-004US", "B2WH-004US"),
            ("Raider 16 Max HX B2WI-003US", "B2WI-003US"),
            ("Raider 16 Max HX B2WJ-002US", "B2WJ-002US"),
            ("Crosshair 16 HX E14WFK-036US", "E14WFK-036US"),
            ("Crosshair 16 HX E14WGK-038US", "E14WGK-038US"),
            ("Stealth 16 AI+ B3WI-039US Copilot+ PC", "B3WI-039US"),
        ],
    )
    def test_known_msi_skus(self, header, expected):
        assert _extract_variant_code(header) == expected

    def test_no_match_returns_none(self):
        assert _extract_variant_code("Some Marketing Headline") is None

    def test_empty_returns_none(self):
        assert _extract_variant_code("") is None


# ---------------------------------------------------------------------------
# Edge-case parsing failures
# ---------------------------------------------------------------------------


class TestParseSpecPageStructuralFailures:
    def test_missing_table_raises(self):
        html = "<html><body><p>No table here</p></body></html>"
        with pytest.raises(RuntimeError, match="no recognizable spec <table>"):
            parse_msi_specification_page(
                html,
                RAIDER_SPEC_URL,
                anchors=[_anchor("msi_raider", RAIDER_SPEC_URL)],
            )

    def test_table_without_headers_raises(self):
        html = (
            "<html><body><table>"
            "<tbody><tr><th>CPU</th><td>x</td></tr></tbody>"
            "</table></body></html>"
        )
        with pytest.raises(RuntimeError, match="no SKU column headers"):
            parse_msi_specification_page(
                html,
                RAIDER_SPEC_URL,
                anchors=[_anchor("msi_raider", RAIDER_SPEC_URL)],
            )

    def test_table_without_tbody_rows_raises(self):
        html = (
            "<html><body><table>"
            "<thead><tr><td>Show</td><td>SKU</td></tr></thead>"
            "<tbody></tbody>"
            "</table></body></html>"
        )
        with pytest.raises(RuntimeError, match="no <tbody> spec rows"):
            parse_msi_specification_page(
                html,
                RAIDER_SPEC_URL,
                anchors=[_anchor("msi_raider", RAIDER_SPEC_URL)],
            )


# ---------------------------------------------------------------------------
# JSON-LD helpers
# ---------------------------------------------------------------------------


class TestJsonldShared:
    def test_brand_from_nested_dict(self):
        assert _jsonld_shared({"brand": {"name": "MSI"}}).get("brand") == "MSI"

    def test_brand_as_string(self):
        assert _jsonld_shared({"brand": "MSI"}).get("brand") == "MSI"

    def test_image_string(self):
        s = _jsonld_shared({"image": "https://x.png"})
        assert s["image"] == "https://x.png"

    def test_image_first_of_list(self):
        s = _jsonld_shared({"image": ["https://a.png", "https://b.png"]})
        assert s["image"] == "https://a.png"

    def test_empty_image_string_dropped(self):
        # MSI sometimes ships an empty image string; we should not surface it.
        out = _jsonld_shared({"image": ""})
        assert "image" not in out

    def test_missing_fields(self):
        assert _jsonld_shared({}) == {"name": None}


# ---------------------------------------------------------------------------
# Config summary
# ---------------------------------------------------------------------------


class TestConfigSummary:
    def test_picks_table_axes(self):
        specs = {
            "CPU": "Intel Core Ultra 9",
            "Discrete Graphics": "NVIDIA RTX 5090",
            "Memory": "32 GB DDR5",
            "Storage": "1TB NVMe SSD",
            "Display": '16" QHD+ 240Hz',
        }
        from scrapers_lib.tier2.msi import _CONFIG_SUMMARY_HINTS_TABLE

        s = _config_summary(specs, _CONFIG_SUMMARY_HINTS_TABLE)
        assert s is not None
        parts = s.split(" / ")
        assert "RTX" in parts[0]
        assert "32 GB" in parts[1]
        assert "1TB" in parts[2]
        assert "240Hz" in parts[3]

    def test_picks_itemlist_axes(self):
        specs = {
            "Processor": "Intel Core Ultra 9",
            "Graphics Card": "RTX 5080",
            "Display": "OLED 240Hz",
        }
        from scrapers_lib.tier2.msi import _CONFIG_SUMMARY_HINTS_ITEMLIST

        s = _config_summary(specs, _CONFIG_SUMMARY_HINTS_ITEMLIST)
        assert s is not None
        # Graphics matched, Display matched; Memory/Storage absent.
        assert "RTX 5080" in s
        assert "OLED" in s

    def test_returns_none_on_empty(self):
        assert _config_summary({}, ("Memory",)) is None


# ---------------------------------------------------------------------------
# Akamai bypass — fetch_msi_product session/header/protocol assertions
# ---------------------------------------------------------------------------


def _fake_curl_cffi_module(html_by_url: dict[str, str]) -> tuple[Any, MagicMock]:
    """Build a stand-in for ``curl_cffi`` that records calls.

    Returns ``(module, calls_recorder)`` where the module mimics the
    ``CurlHttpVersion`` enum and ``requests.Session`` context manager
    surface that :func:`scrapers_lib.tier2.msi._fetch_msi_html`
    consumes. ``calls_recorder`` is a ``MagicMock`` whose ``call_args_list``
    captures every ``Session.get`` invocation.
    """
    calls = MagicMock()

    class _FakeResp:
        def __init__(self, text: str, status: int = 200) -> None:
            self.text = text
            self.status_code = status

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class _FakeSession:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def __enter__(self) -> "_FakeSession":
            return self

        def __exit__(self, *exc: Any) -> None:
            return None

        def get(self, url: str, **kwargs: Any) -> _FakeResp:
            calls(url=url, session_kwargs=self.kwargs, **kwargs)
            text = html_by_url.get(url)
            if text is None:
                return _FakeResp("", status=404)
            return _FakeResp(text)

    fake_requests = SimpleNamespace(Session=_FakeSession)
    # Sentinel value the real CurlHttpVersion.V1_1 stand-in.
    fake_curl_http_version = SimpleNamespace(V1_1="V1_1_SENTINEL")
    fake_module = SimpleNamespace(
        requests=fake_requests, CurlHttpVersion=fake_curl_http_version
    )
    return fake_module, calls


class TestFetchMsiProductBypass:
    """Verify the warm-session + Chrome impersonate + HTTP/1.1 contract.

    These tests don't hit the network; they patch ``curl_cffi`` with a
    fake module recording every ``Session.get`` call, then assert the
    fetcher made the right calls in the right order with the right
    kwargs. They cover the three surface routes:

    1. Bare URL → /Specification first (comprehensive surface). Main
       page only fetched as a fallback when /Specification fails.
    2. Bare URL with /Specification missing → falls back to main-page
       ItemList highlight summary.
    3. ``/Specification`` URL → /Specification only (no fallback).
    """

    def _patch(self, html_by_url: dict[str, str]):
        fake_module, calls = _fake_curl_cffi_module(html_by_url)
        return (
            patch.dict(
                "sys.modules",
                {
                    "curl_cffi": fake_module,
                    "curl_cffi.requests": fake_module.requests,
                },
            ),
            calls,
        )

    def test_bare_stealth_url_hits_specification_first(self):
        # Stealth has BOTH surfaces. Default must prefer /Specification
        # for the comprehensive 27-field per-SKU snapshot — not the
        # ItemList highlight summary.
        stealth_spec = _load("stealth_16_ai_plus_b3wx_specification.html")
        patcher, calls = self._patch(
            {
                "https://us.msi.com/": "<html></html>",
                f"{STEALTH_URL}/Specification": stealth_spec,
            }
        )
        with patcher:
            snaps = fetch_msi_product(
                STEALTH_URL,
                anchors=[_anchor("msi_stealth", STEALTH_URL)],
            )
        assert len(snaps) == 1
        assert snaps[0].raw["spec_source"] == "specification_table"
        assert len(snaps[0].specs) >= 25

        urls_called = [c.kwargs["url"] for c in calls.call_args_list]
        # Warm first, then /Specification. Main page NOT fetched.
        assert urls_called == [
            "https://us.msi.com/",
            f"{STEALTH_URL}/Specification",
        ]

    def test_raider_bare_url_uses_specification_directly(self):
        # Gaming line: /Specification is reachable so we go straight there
        # — the main-page detour is gone under the new default.
        raider_spec = _load("raider_16_max_hx_b2wx_specification.html")
        patcher, calls = self._patch(
            {
                "https://us.msi.com/": "<html></html>",
                RAIDER_SPEC_URL: raider_spec,
            }
        )
        with patcher:
            snaps = fetch_msi_product(
                RAIDER_MAIN_URL,
                anchors=[_anchor("msi_raider", RAIDER_MAIN_URL)],
            )
        assert len(snaps) == 3
        for s in snaps:
            assert s.raw["spec_source"] == "specification_table"

        urls_called = [c.kwargs["url"] for c in calls.call_args_list]
        # Warm → /Specification only. No main-page fetch.
        assert urls_called == [
            "https://us.msi.com/",
            RAIDER_SPEC_URL,
        ]

    def test_specification_unreachable_falls_back_to_main_itemlist(self):
        # Stealth /Specification 404 (not in patch map) → fetcher must
        # gracefully degrade to the main-page ItemList highlight summary.
        stealth_main = _load("stealth_16_ai_plus_b3wx_main.html")
        patcher, calls = self._patch(
            {
                "https://us.msi.com/": "<html></html>",
                STEALTH_URL: stealth_main,
                # Note: STEALTH_URL/Specification deliberately absent → 404
            }
        )
        with patcher:
            snaps = fetch_msi_product(
                STEALTH_URL,
                anchors=[_anchor("msi_stealth", STEALTH_URL)],
            )
        # Fallback engaged: ItemList path emits one highlight snapshot.
        assert len(snaps) == 1
        assert snaps[0].raw["spec_source"] == "jsonld_itemlist"

        urls_called = [c.kwargs["url"] for c in calls.call_args_list]
        # Warm → /Specification (404) → warm → main page.
        # Each call opens its own warmed session per existing design.
        assert urls_called == [
            "https://us.msi.com/",
            f"{STEALTH_URL}/Specification",
            "https://us.msi.com/",
            STEALTH_URL,
        ]

    def test_specification_url_skips_main(self):
        raider_spec = _load("raider_16_max_hx_b2wx_specification.html")
        patcher, calls = self._patch(
            {
                "https://us.msi.com/": "<html></html>",
                RAIDER_SPEC_URL: raider_spec,
            }
        )
        with patcher:
            snaps = fetch_msi_product(
                RAIDER_SPEC_URL,
                anchors=[_anchor("msi_raider", RAIDER_SPEC_URL)],
            )
        assert len(snaps) == 3
        urls_called = [c.kwargs["url"] for c in calls.call_args_list]
        assert urls_called == ["https://us.msi.com/", RAIDER_SPEC_URL]

    def test_session_uses_chrome_impersonation_and_http11(self):
        stealth_spec = _load("stealth_16_ai_plus_b3wx_specification.html")
        patcher, calls = self._patch(
            {
                "https://us.msi.com/": "<html></html>",
                f"{STEALTH_URL}/Specification": stealth_spec,
            }
        )
        with patcher:
            fetch_msi_product(
                STEALTH_URL,
                anchors=[_anchor("msi_stealth", STEALTH_URL)],
            )
        # Every recorded session was constructed with chrome impersonation
        # AND http_version=V1_1 (the sentinel from our fake CurlHttpVersion).
        for c in calls.call_args_list:
            sk = c.kwargs["session_kwargs"]
            assert sk["impersonate"] == "chrome"
            assert sk["http_version"] == "V1_1_SENTINEL"

    def test_warm_runs_before_target(self):
        stealth_spec = _load("stealth_16_ai_plus_b3wx_specification.html")
        patcher, calls = self._patch(
            {
                "https://us.msi.com/": "<html></html>",
                f"{STEALTH_URL}/Specification": stealth_spec,
            }
        )
        with patcher:
            fetch_msi_product(
                STEALTH_URL,
                anchors=[_anchor("msi_stealth", STEALTH_URL)],
            )
        urls = [c.kwargs["url"] for c in calls.call_args_list]
        assert urls.index("https://us.msi.com/") < urls.index(
            f"{STEALTH_URL}/Specification"
        )

    def test_warm_skipped_when_warm_false(self):
        stealth_spec = _load("stealth_16_ai_plus_b3wx_specification.html")
        patcher, calls = self._patch(
            {
                "https://us.msi.com/": "<html></html>",
                f"{STEALTH_URL}/Specification": stealth_spec,
            }
        )
        with patcher:
            fetch_msi_product(
                STEALTH_URL,
                anchors=[_anchor("msi_stealth", STEALTH_URL)],
                warm=False,
            )
        urls = [c.kwargs["url"] for c in calls.call_args_list]
        assert urls == [f"{STEALTH_URL}/Specification"]

    def test_target_request_carries_referer_and_accept(self):
        stealth_spec = _load("stealth_16_ai_plus_b3wx_specification.html")
        spec_url = f"{STEALTH_URL}/Specification"
        patcher, calls = self._patch(
            {
                "https://us.msi.com/": "<html></html>",
                spec_url: stealth_spec,
            }
        )
        with patcher:
            fetch_msi_product(
                STEALTH_URL,
                anchors=[_anchor("msi_stealth", STEALTH_URL)],
            )
        # Find the call to /Specification and inspect its headers kwarg.
        target_call = next(
            c for c in calls.call_args_list if c.kwargs["url"] == spec_url
        )
        headers = target_call.kwargs.get("headers") or {}
        assert headers.get("Referer") == "https://us.msi.com/"
        assert "text/html" in headers.get("Accept", "")
        assert "en" in headers.get("Accept-Language", "")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistered:
    def test_msi_in_registry(self):
        assert "msi" in list_fetchers()

    def test_registered_callable_is_fetch_msi_product(self):
        from scrapers_lib.core.registry import get_fetcher

        assert get_fetcher("msi") is msi.fetch_msi_product
