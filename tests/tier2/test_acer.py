"""Unit tests for scrapers_lib.tier2.acer.

Tests run against committed Acer PDP HTML fixtures captured during Wave
2f reconnaissance. No network. Three brand-line fixtures:

- Predator Helios Neo 16S AI (gaming flagship, Predator brand)
- Acer Nitro V 16S AI AMD (mid-gaming, Nitro brand)
- Aspire 7 Intel (mainstream consumer)
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier2.acer import (
    _config_summary,
    _find_techspec_tables,
    _flatten_spec_tables,
    _jsonld_shared,
    _sku_from_url,
    _table_categories,
    parse_acer_product_page,
)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


FIX = Path(__file__).parent / "fixtures" / "acer"

HELIOS_URL = (
    "https://www.acer.com/us-en/predator/laptops/helios/"
    "helios-neo-16s-ai/pdp/NH.U0KAA.001"
)
NITRO_URL = (
    "https://www.acer.com/us-en/laptops/nitro/"
    "nitro-v-16s-ai-amd/pdp/NH.U10AA.001"
)
ASPIRE_URL = (
    "https://www.acer.com/us-en/laptops/aspire/"
    "aspire-7-intel/pdp/NH.Q81AA.001"
)


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _anchor(anchor_id: str, url: str) -> Anchor:
    return Anchor(
        anchor_id=anchor_id,
        anchor_type="product",
        name=anchor_id.replace("_", " ").title(),
        attribution_regex=AttributionRegex(primary=[anchor_id]),
        source_urls={"acer": url},
    )


# ---------------------------------------------------------------------------
# parse_acer_product_page — Predator Helios (gaming flagship, mandatory)
# ---------------------------------------------------------------------------


class TestParseHeliosFull:
    @pytest.fixture
    def snapshot(self):
        html = _load("helios-neo-16s-ai.html")
        snaps = parse_acer_product_page(
            html,
            HELIOS_URL,
            anchors=[_anchor("acer_predator_helios_neo_16s_ai", HELIOS_URL)],
        )
        assert len(snaps) == 1
        return snaps[0]

    def test_source_is_acer(self, snapshot):
        assert snapshot.source == "acer"

    def test_source_id_is_sku(self, snapshot):
        assert snapshot.source_id == "NH.U0KAA.001"

    def test_variant_key_is_none(self, snapshot):
        # Per-SKU granularity; the SKU itself is the variant.
        assert snapshot.variant_key is None

    def test_brand_normalized_to_acer(self, snapshot):
        # JSON-LD reports "predator" sub-brand; we normalize to parent.
        assert snapshot.brand == "Acer"
        assert snapshot.raw["jsonld_brand"] == "predator"

    def test_anchor_id(self, snapshot):
        assert snapshot.anchor_id == "acer_predator_helios_neo_16s_ai"

    def test_title_from_jsonld(self, snapshot):
        assert "Predator Helios" in snapshot.title

    def test_image_url(self, snapshot):
        assert snapshot.image_url and snapshot.image_url.startswith("http")
        assert "predator-helios" in snapshot.image_url

    def test_price_from_offer(self, snapshot):
        assert snapshot.price == Decimal("1799.99")
        assert snapshot.currency == "USD"

    def test_out_of_stock(self, snapshot):
        # JSON-LD offer says OutOfStock.
        assert snapshot.in_stock is False
        assert snapshot.availability_text and "OutOfStock" in snapshot.availability_text

    def test_raw_provenance(self, snapshot):
        assert snapshot.raw["spec_source"] == "ssr_table"
        assert snapshot.raw["sku"] == "NH.U0KAA.001"

    def test_thirteen_categories_captured(self, snapshot):
        # Recon established Acer ships exactly 13 spec tables per PDP.
        soup = BeautifulSoup(_load("helios-neo-16s-ai.html"), "html.parser")
        cats = _table_categories(soup)
        assert len(cats) == 13
        assert cats[0] == "Operating System"
        assert "Processor" in cats
        assert "Display & Graphics" in cats
        assert "Memory" in cats
        assert "Storage" in cats
        assert "Interfaces/Ports" in cats
        assert "Battery Information" in cats

    def test_core_spec_fields_present(self, snapshot):
        # CPU / GPU / RAM / storage / display labels exactly as Acer
        # publishes them. The downstream cleaner handles cross-vendor
        # normalization; the fetcher preserves the verbatim labels.
        for expected in [
            "Operating System",
            "Processor Manufacturer",
            "Processor Type",
            "Processor Model",
            "Graphics Controller Manufacturer",
            "Graphics Controller Model",
            "Standard Memory",
            "System Memory Technology",
            "Total Solid State Drive Capacity",
            "Solid State Drive Interface",
            "Wireless LAN Standard",
            "Battery Energy",
            "Maximum Power Supply Wattage",
            "Weight (Approximate)",
        ]:
            assert expected in snapshot.specs, (
                f"missing spec label {expected!r}"
            )

    def test_processor_values_verbatim(self, snapshot):
        assert snapshot.specs["Processor Manufacturer"] == "Intel®"
        assert snapshot.specs["Processor Type"] == "Core™ Ultra 9"
        assert snapshot.specs["Processor Model"] == "275HX"

    def test_graphics_values_verbatim(self, snapshot):
        assert (
            snapshot.specs["Graphics Controller Manufacturer"] == "NVIDIA®"
        )
        assert (
            snapshot.specs["Graphics Controller Model"]
            == "GeForce RTX™ 5070 Ti"
        )

    def test_spec_count_matches_table_rows(self, snapshot):
        # Every <th>/<td> row across 13 tables collapsed into the dict.
        # Helios has 60 such rows in recon; we expect them all (no
        # collisions observed).
        assert len(snapshot.specs) >= 55

    def test_config_summary_has_all_axes(self, snapshot):
        assert snapshot.config_summary is not None
        # GPU / RAM / Storage / Display all present, separated by " / ".
        parts = snapshot.config_summary.split(" / ")
        assert len(parts) >= 3


# ---------------------------------------------------------------------------
# parse_acer_product_page — Nitro (mid-gaming, generality)
# ---------------------------------------------------------------------------


class TestParseNitroFull:
    """Generality: different brand-line + URL form (no /predator/ segment)."""

    @pytest.fixture
    def snapshot(self):
        html = _load("nitro-v-16s-ai.html")
        snaps = parse_acer_product_page(
            html,
            NITRO_URL,
            anchors=[_anchor("acer_nitro_v_16s_ai", NITRO_URL)],
        )
        assert len(snaps) == 1
        return snaps[0]

    def test_source_id_is_sku(self, snapshot):
        assert snapshot.source_id == "NH.U10AA.001"

    def test_brand_is_acer(self, snapshot):
        # Nitro's JSON-LD brand IS "acer"; normalization is idempotent.
        assert snapshot.brand == "Acer"
        assert snapshot.raw["jsonld_brand"] == "acer"

    def test_title(self, snapshot):
        assert "Nitro" in snapshot.title

    def test_thirteen_categories_captured(self, snapshot):
        soup = BeautifulSoup(_load("nitro-v-16s-ai.html"), "html.parser")
        assert len(_table_categories(soup)) == 13

    def test_core_categories_present(self, snapshot):
        # Nitro's Graphics table breaks out the GPU as Manufacturer +
        # Boost Clock + Maximum Graphics Power but omits a single
        # consolidated "Graphics Controller Model" row — proves the
        # parser doesn't hard-code the Helios label set.
        for label in [
            "Processor Manufacturer",
            "Graphics Controller Manufacturer",
            "Standard Memory",
            "Total Solid State Drive Capacity",
        ]:
            assert label in snapshot.specs


# ---------------------------------------------------------------------------
# parse_acer_product_page — Aspire (mainstream, generality)
# ---------------------------------------------------------------------------


class TestParseAspireFull:
    """Generality: mainstream consumer line. Confirms parser doesn't
    overfit to gaming-only categories like "Graphics Memory Capacity"."""

    @pytest.fixture
    def snapshot(self):
        html = _load("aspire-7-intel.html")
        snaps = parse_acer_product_page(
            html,
            ASPIRE_URL,
            anchors=[_anchor("acer_aspire_7_intel", ASPIRE_URL)],
        )
        assert len(snaps) == 1
        return snaps[0]

    def test_source_id_is_sku(self, snapshot):
        assert snapshot.source_id == "NH.Q81AA.001"

    def test_brand_is_acer(self, snapshot):
        assert snapshot.brand == "Acer"

    def test_title(self, snapshot):
        assert "Aspire" in snapshot.title

    def test_zero_price_treated_as_missing(self, snapshot):
        # Aspire fixture's offer carries price="0" (placeholder for
        # unpriced / discontinued listing); the fetcher coerces this
        # to None rather than emit a fake $0 product.
        assert snapshot.price is None

    def test_thirteen_categories_captured(self, snapshot):
        soup = BeautifulSoup(_load("aspire-7-intel.html"), "html.parser")
        assert len(_table_categories(soup)) == 13

    def test_core_categories_present(self, snapshot):
        # Aspire ships with "Maximum Supported System Memory" but no
        # "Standard Memory" row, and emits "Total Solid State Drive
        # Capacity" + "Screen Size" + "Processor Manufacturer".
        # All labels here are recon-confirmed common to all three
        # fixtures.
        for label in [
            "Operating System",
            "Processor Manufacturer",
            "Maximum Supported System Memory",
            "Total Solid State Drive Capacity",
            "Screen Size",
        ]:
            assert label in snapshot.specs


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------


class TestSkuFromUrl:
    def test_predator_form_with_brand_segment(self):
        assert _sku_from_url(HELIOS_URL) == "NH.U0KAA.001"

    def test_nitro_form_no_brand_segment(self):
        assert _sku_from_url(NITRO_URL) == "NH.U10AA.001"

    def test_aspire_form(self):
        assert _sku_from_url(ASPIRE_URL) == "NH.Q81AA.001"

    def test_trailing_slash_accepted(self):
        assert (
            _sku_from_url(NITRO_URL + "/")
            == "NH.U10AA.001"
        )

    def test_alternate_region_prefix(self):
        # Acer regional sites use the same path shape with a different
        # locale segment (ae-en, ph-en, ee-en, etc.).
        assert (
            _sku_from_url(
                "https://www.acer.com/ae-en/laptops/aspire/"
                "aspire-7-intel/pdp/NH.QMFEM.004"
            )
            == "NH.QMFEM.004"
        )

    def test_missing_pdp_segment_raises(self):
        with pytest.raises(ValueError, match="does not end in"):
            _sku_from_url(
                "https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-ai-amd/"
            )

    def test_malformed_sku_raises(self):
        # A path with /pdp/ but the segment that follows isn't
        # NH.<seg>.<seg> — caught by the regex before SKU validation.
        with pytest.raises(ValueError, match="does not end in"):
            _sku_from_url(
                "https://www.acer.com/us-en/laptops/aspire/aspire-7/pdp/foo"
            )

    def test_non_acer_host_raises(self):
        with pytest.raises(ValueError, match="not an acer.com domain"):
            _sku_from_url(
                "https://store.dell.com/us-en/laptops/foo/pdp/NH.U0KAA.001"
            )

    def test_acer_subdomain_accepted(self):
        # Any acer.com subdomain is accepted; only the host TLD matters.
        assert (
            _sku_from_url(
                "https://store.acer.com/us-en/laptops/aspire/"
                "aspire-7/pdp/NH.Q81AA.001"
            )
            == "NH.Q81AA.001"
        )


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


class TestAttribution:
    def test_no_anchors_raises(self):
        html = _load("helios-neo-16s-ai.html")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_acer_product_page(html, HELIOS_URL)

    def test_anchor_url_mismatch_raises(self):
        html = _load("helios-neo-16s-ai.html")
        # Real-looking anchor pointing at a different SKU's URL.
        wrong = _anchor("wrong", NITRO_URL)
        with pytest.raises(ValueError, match="no Anchor"):
            parse_acer_product_page(html, HELIOS_URL, anchors=[wrong])

    def test_matching_anchor_used(self):
        html = _load("helios-neo-16s-ai.html")
        a = _anchor("chosen_one", HELIOS_URL)
        snaps = parse_acer_product_page(html, HELIOS_URL, anchors=[a])
        assert snaps[0].anchor_id == "chosen_one"


# ---------------------------------------------------------------------------
# Structural error paths
# ---------------------------------------------------------------------------


class TestStructuralError:
    def test_missing_spec_tables_raises(self):
        # Page with valid attribution but no agw-table_techSpec blocks.
        html = (
            "<html><body><table class='agw-table'>"
            "<caption>Layout</caption><tr><th>foo</th><td>bar</td></tr>"
            "</table></body></html>"
        )
        with pytest.raises(RuntimeError, match="agw-table_techSpec"):
            parse_acer_product_page(
                html,
                HELIOS_URL,
                anchors=[_anchor("acer_predator_helios_neo_16s_ai", HELIOS_URL)],
            )

    def test_jsonld_absent_does_not_error(self):
        # Strip JSON-LD from the fixture; the fetcher must still emit
        # a snapshot (degraded title, no image, no price), not raise.
        html = _load("helios-neo-16s-ai.html")
        import re as _re

        stripped = _re.sub(
            r"<script[^>]*application/ld\+json[^>]*>.*?</script>",
            "",
            html,
            flags=_re.DOTALL | _re.IGNORECASE,
        )
        snaps = parse_acer_product_page(
            stripped,
            HELIOS_URL,
            anchors=[_anchor("acer_predator_helios_neo_16s_ai", HELIOS_URL)],
        )
        assert len(snaps) == 1
        # Title falls back to the SKU when no JSON-LD name is available.
        assert snaps[0].title == "NH.U0KAA.001"
        # Brand still normalized to Acer; no JSON-LD brand to preserve.
        assert snaps[0].brand == "Acer"
        assert snaps[0].raw["jsonld_brand"] is None
        assert snaps[0].image_url is None
        # Specs still extracted from the surviving spec tables.
        assert "Processor Manufacturer" in snaps[0].specs


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestFindTechspecTables:
    def test_matches_only_techspec_class(self):
        soup = BeautifulSoup(
            "<table class='agw-table agw-table_techSpec'>"
            "<caption>A</caption>"
            "<tr><th>l</th><td>v</td></tr>"
            "</table>"
            "<table class='agw-table other'>"
            "<caption>B</caption>"
            "<tr><th>l</th><td>v</td></tr>"
            "</table>",
            "html.parser",
        )
        tables = _find_techspec_tables(soup)
        assert len(tables) == 1
        assert tables[0].find("caption").get_text(strip=True) == "A"

    def test_returns_empty_when_no_tables(self):
        soup = BeautifulSoup("<div>no tables here</div>", "html.parser")
        assert _find_techspec_tables(soup) == []


class TestFlattenSpecTables:
    def test_extracts_label_value_pairs(self):
        soup = BeautifulSoup(
            "<table class='agw-table agw-table_techSpec'>"
            "<caption>Processor</caption>"
            "<tr><th>Manufacturer</th><td>Intel</td></tr>"
            "<tr><th>Model</th><td>i7-1300H</td></tr>"
            "</table>",
            "html.parser",
        )
        out = _flatten_spec_tables(soup)
        assert out == {"Manufacturer": "Intel", "Model": "i7-1300H"}

    def test_skips_rows_with_missing_th_or_td(self):
        soup = BeautifulSoup(
            "<table class='agw-table agw-table_techSpec'>"
            "<caption>X</caption>"
            "<tr><th>only-th</th></tr>"
            "<tr><td>only-td</td></tr>"
            "<tr><th>good</th><td>val</td></tr>"
            "</table>",
            "html.parser",
        )
        out = _flatten_spec_tables(soup)
        assert out == {"good": "val"}

    def test_first_occurrence_wins_on_duplicate_label(self):
        soup = BeautifulSoup(
            "<table class='agw-table agw-table_techSpec'>"
            "<caption>A</caption>"
            "<tr><th>Manufacturer</th><td>FirstWin</td></tr>"
            "</table>"
            "<table class='agw-table agw-table_techSpec'>"
            "<caption>B</caption>"
            "<tr><th>Manufacturer</th><td>SecondLose</td></tr>"
            "</table>",
            "html.parser",
        )
        out = _flatten_spec_tables(soup)
        assert out == {"Manufacturer": "FirstWin"}

    def test_empty_label_or_value_skipped(self):
        soup = BeautifulSoup(
            "<table class='agw-table agw-table_techSpec'>"
            "<caption>X</caption>"
            "<tr><th>   </th><td>val</td></tr>"
            "<tr><th>label</th><td>   </td></tr>"
            "<tr><th>good</th><td>val</td></tr>"
            "</table>",
            "html.parser",
        )
        out = _flatten_spec_tables(soup)
        assert out == {"good": "val"}


class TestJsonldShared:
    def test_brand_from_nested_dict(self):
        assert (
            _jsonld_shared({"brand": {"name": "predator"}}).get("brand")
            == "predator"
        )

    def test_brand_as_string(self):
        assert _jsonld_shared({"brand": "acer"}).get("brand") == "acer"

    def test_image_first_of_list(self):
        s = _jsonld_shared({"image": ["https://a.png", "https://b.png"]})
        assert s["image"] == "https://a.png"

    def test_offer_in_stock(self):
        s = _jsonld_shared(
            {
                "offers": {
                    "price": "1500.00",
                    "priceCurrency": "USD",
                    "availability": "InStock",
                }
            }
        )
        assert s["price"] == Decimal("1500.00")
        assert s["currency"] == "USD"
        assert s["in_stock"] is True

    def test_offer_out_of_stock(self):
        s = _jsonld_shared(
            {"offers": {"availability": "https://schema.org/OutOfStock"}}
        )
        assert s["in_stock"] is False

    def test_offer_zero_price_dropped(self):
        # Acer publishes "0" as a placeholder for unpriced listings.
        s = _jsonld_shared(
            {"offers": {"price": "0", "priceCurrency": "USD"}}
        )
        assert "price" not in s

    def test_no_offers_yields_no_price_or_stock(self):
        s = _jsonld_shared({"name": "x"})
        assert "price" not in s
        assert "in_stock" not in s


class TestConfigSummary:
    def test_picks_known_axes(self):
        specs = {
            "Graphics Controller Model": "GeForce RTX 5070 Ti",
            "Standard Memory": "32 GB",
            "Total Solid State Drive Capacity": "1 TB",
            "Screen Size": "16\"",
            "Processor Type": "Core Ultra 9",
        }
        summary = _config_summary(specs)
        assert summary is not None
        parts = summary.split(" / ")
        assert "GeForce RTX 5070 Ti" in parts
        assert "32 GB" in parts
        assert "1 TB" in parts

    def test_empty_specs_returns_none(self):
        assert _config_summary({}) is None

    def test_partial_axes_ok(self):
        # Missing axes are simply skipped, not None'd out.
        summary = _config_summary({"Standard Memory": "16 GB"})
        assert summary == "16 GB"
