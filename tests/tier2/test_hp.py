"""Unit tests for scrapers_lib.tier2.hp.

Tests run against committed HP shop PDP HTML fixtures captured during
Wave 2b reconnaissance. No network.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from scrapers_lib.core.registry import list_fetchers
from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier2 import hp
from scrapers_lib.tier2.hp import (
    _config_summary,
    _extract_state_json,
    _flatten_technical_specs,
    _jsonld_shared,
    _pick_title,
    _validate_pdp_url,
    parse_hp_product_page,
)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


FIX = Path(__file__).parent / "fixtures" / "hp"

OMEN_MAX_URL = (
    "https://www.hp.com/us-en/shop/pdp/omen-max-gaming-laptop-16t-ah000-16-a4nq6av-1"
)
PAVILION_URL = (
    "https://www.hp.com/us-en/shop/pdp/hp-pavilion-laptop-16z-ag000-16-94g92av-1"
)

OMEN_MAX_TILE_IDS = (
    "3074457345621832827",  # Casual Gamer
    "3074457345621841323",  # Campaign Hero
    "3074457345621841324",  # eSports Pro
)
PAVILION_TILE_IDS = (
    "3074457345621913319",
    "3074457345622227318",
    "3074457345622218819",
)


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _anchor(anchor_id: str, url: str) -> Anchor:
    return Anchor(
        anchor_id=anchor_id,
        anchor_type="product",
        name=anchor_id.replace("_", " ").title(),
        attribution_regex=AttributionRegex(primary=[anchor_id]),
        source_urls={"hp": url},
    )


# ---------------------------------------------------------------------------
# parse_hp_product_page — OMEN Max (gaming, Intel)
# ---------------------------------------------------------------------------


class TestParseOmenMaxFull:
    @pytest.fixture
    def snapshots(self):
        html = _load("omen_max_a4nq6av_1.html")
        return parse_hp_product_page(
            html,
            OMEN_MAX_URL,
            anchors=[_anchor("hp_omen_max_16", OMEN_MAX_URL)],
        )

    def test_emits_three_snapshots(self, snapshots):
        assert len(snapshots) == 3

    def test_source_ids_match_known_tiles(self, snapshots):
        assert {s.source_id for s in snapshots} == set(OMEN_MAX_TILE_IDS)

    def test_variant_key_equals_source_id(self, snapshots):
        for s in snapshots:
            assert s.variant_key == s.source_id

    def test_all_snapshots_are_hp(self, snapshots):
        assert all(s.source == "hp" for s in snapshots)

    def test_all_snapshots_carry_anchor(self, snapshots):
        assert all(s.anchor_id == "hp_omen_max_16" for s in snapshots)

    def test_all_brand_is_hp(self, snapshots):
        assert all(s.brand == "HP" for s in snapshots)

    def test_title_from_tile_not_jsonld(self, snapshots):
        # HP PDPs sometimes carry template-reused JSON-LD naming a different
        # product. All tiles must use the tile's own name.
        for s in snapshots:
            assert "OMEN MAX" in s.title or "Omen MAX" in s.title

    def test_image_url_populated(self, snapshots):
        for s in snapshots:
            assert s.image_url and s.image_url.startswith("http")

    def test_prices_differ_per_tile(self, snapshots):
        prices = [s.price for s in snapshots]
        # Three distinct configs → three distinct sale prices.
        assert len(set(prices)) == 3
        # All sale prices strictly less than list prices (HP shop shows the
        # sale-active case on this fixture; if HP lifts the sale, this
        # assertion will legitimately flip — refresh the fixture).
        for s in snapshots:
            assert s.price is not None and s.list_price is not None
            assert s.price < s.list_price

    def test_prices_are_decimal(self, snapshots):
        for s in snapshots:
            assert isinstance(s.price, Decimal)
            assert isinstance(s.list_price, Decimal)

    def test_rating_from_jsonld(self, snapshots):
        for s in snapshots:
            assert s.rating is not None
            assert 0 <= s.rating <= 5
            assert isinstance(s.review_count, int)
            assert s.review_count > 0

    def test_raw_carries_provenance(self, snapshots):
        for s in snapshots:
            assert s.raw["spec_source"] == "pdpCTOConfiguration"
            assert s.raw["config_catentry_id"] == s.source_id
            assert s.raw["config_name"]  # e.g. "Casual Gamer"

    def test_specs_count(self, snapshots):
        for s in snapshots:
            # 12 config-picker categories on Omen Max.
            assert len(s.specs) == 12

    def test_spec_keys_union(self, snapshots):
        expected = {
            "Operating system",
            "Processor and graphics",
            "Memory",
            "Storage",
            "Display",
            "Color",
            "Personalization",
            "Keyboard",
            "Wireless technology",
            "Primary battery",
            "Office software",
            "McAfee AI Powered Security Software",
        }
        for s in snapshots:
            assert set(s.specs.keys()) == expected

    def test_rich_processor_graphics_content(self, snapshots):
        # Tile 0 (Casual Gamer): current is 255HX + 5070 Ti
        casual = next(s for s in snapshots if s.source_id == OMEN_MAX_TILE_IDS[0])
        pg = casual.specs["Processor and graphics"]
        assert "Intel" in pg
        assert "Core" in pg
        assert "255HX" in pg
        assert "RTX" in pg
        assert "5070 Ti" in pg
        # Alternatives on subsequent lines
        assert "\n" in pg
        assert "5080" in pg or "5090" in pg

    def test_memory_alternatives_preserved(self, snapshots):
        casual = next(s for s in snapshots if s.source_id == OMEN_MAX_TILE_IDS[0])
        mem = casual.specs["Memory"]
        assert "DDR5" in mem
        assert "16 GB" in mem
        # Alt options should reach 64 GB.
        assert "64 GB" in mem

    def test_current_value_on_first_line(self, snapshots):
        # The first newline-separated segment of each spec must be the
        # "Current Configuration" — consumers rely on this ordering.
        casual = next(s for s in snapshots if s.source_id == OMEN_MAX_TILE_IDS[0])
        mem_first = casual.specs["Memory"].split("\n", 1)[0]
        assert "16 GB" in mem_first  # Casual Gamer defaults to 16 GB

        esports = next(s for s in snapshots if s.source_id == OMEN_MAX_TILE_IDS[2])
        mem_first = esports.specs["Memory"].split("\n", 1)[0]
        assert "32 GB" in mem_first  # eSports Pro defaults to 32 GB

    def test_html_entities_decoded(self, snapshots):
        joined = "\n".join(
            v for s in snapshots for v in s.specs.values()
        )
        # Raw entities must not leak through.
        assert "&trade;" not in joined
        assert "&reg;" not in joined
        assert "&amp;" not in joined
        # Evidence of decoding: trademark symbol is present (in Intel/NVIDIA names).
        assert "™" in joined or "®" in joined

    def test_config_summary_shape(self, snapshots):
        for s in snapshots:
            assert s.config_summary is not None
            # GPU / RAM / Storage / Display separated by " / "
            parts = s.config_summary.split(" / ")
            assert len(parts) == 4
            # GPU segment must mention NVIDIA (Omen is discrete-GPU)
            assert "NVIDIA" in parts[0] or "Intel" in parts[0]


# ---------------------------------------------------------------------------
# parse_hp_product_page — Pavilion 16z (consumer, AMD, generality check)
# ---------------------------------------------------------------------------


class TestParsePavilionFull:
    """Proves the HP pattern generalizes beyond Omen gaming.

    Pavilion differs structurally from Omen in category naming (it merges
    Processor+Graphics+Memory into one combined category). The parser must
    walk categories by position, never hard-code names.
    """

    @pytest.fixture
    def snapshots(self):
        html = _load("pavilion_16z_94g92av_1.html")
        return parse_hp_product_page(
            html,
            PAVILION_URL,
            anchors=[_anchor("hp_pavilion_16z", PAVILION_URL)],
        )

    def test_emits_three_snapshots(self, snapshots):
        assert len(snapshots) == 3

    def test_source_ids_match_known_tiles(self, snapshots):
        assert {s.source_id for s in snapshots} == set(PAVILION_TILE_IDS)

    def test_specs_count_eleven(self, snapshots):
        # Pavilion's merged "Processor, graphics & memory" cuts us from 12 to 11.
        for s in snapshots:
            assert len(s.specs) == 11

    def test_merged_processor_graphics_memory_category(self, snapshots):
        # The merged-category naming HP actually uses.
        s = snapshots[0]
        assert "Processor, graphics & memory" in s.specs
        assert "Processor and graphics" not in s.specs
        assert "Memory" not in s.specs

    def test_brand_still_hp(self, snapshots):
        # Even when JSON-LD on this page lists a different product name,
        # brand defaults to HP.
        for s in snapshots:
            assert s.brand == "HP"


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


class TestValidatePdpUrl:
    def test_valid_shop_pdp_url_passes(self):
        _validate_pdp_url(OMEN_MAX_URL)
        _validate_pdp_url(PAVILION_URL)

    def test_trailing_query_string_ok(self):
        _validate_pdp_url(OMEN_MAX_URL + "?jumpid=in_r11632")

    def test_non_hp_host_raises(self):
        with pytest.raises(ValueError, match="not hp.com"):
            _validate_pdp_url(
                "https://www.dell.com/us-en/shop/dell-laptops/alienware-16"
            )

    def test_support_page_rejected(self):
        # HP support documents have a different structure and are NOT parsed here.
        with pytest.raises(ValueError, match="not /us-en/shop/pdp"):
            _validate_pdp_url(
                "https://support.hp.com/us-en/document/ish_12049662-12049760-16"
            )

    def test_marketing_landing_page_rejected(self):
        with pytest.raises(ValueError, match="not /us-en/shop/pdp"):
            _validate_pdp_url(
                "https://www.hp.com/us-en/gaming-pc/laptops/2025-omen-16-intel.html"
            )


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


class TestAttribution:
    def test_no_anchors_raises(self):
        html = _load("omen_max_a4nq6av_1.html")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_hp_product_page(html, OMEN_MAX_URL)

    def test_anchor_url_mismatch_raises(self):
        html = _load("omen_max_a4nq6av_1.html")
        wrong = _anchor("wrong", PAVILION_URL)  # right format, wrong product
        with pytest.raises(ValueError, match="no Anchor"):
            parse_hp_product_page(html, OMEN_MAX_URL, anchors=[wrong])

    def test_matching_anchor_used(self):
        html = _load("omen_max_a4nq6av_1.html")
        a = _anchor("chosen_one", OMEN_MAX_URL)
        snaps = parse_hp_product_page(html, OMEN_MAX_URL, anchors=[a])
        assert all(s.anchor_id == "chosen_one" for s in snaps)


# ---------------------------------------------------------------------------
# State JSON extraction
# ---------------------------------------------------------------------------


class TestExtractStateJson:
    def test_extracts_from_real_fixture(self):
        html = _load("omen_max_a4nq6av_1.html")
        data = _extract_state_json(html)
        assert isinstance(data, dict)
        assert "slugInfo" in data
        assert "pdpCTOConfiguration" in data["slugInfo"]["components"]

    def test_missing_block_raises(self):
        with pytest.raises(RuntimeError, match="no <div id='data'"):
            _extract_state_json("<html><body>no state here</body></html>")

    def test_malformed_json_in_block_raises(self):
        malformed = (
            '<html><body><div id="data" style="display:none">'
            "<!-- {this is not JSON } -->"
            "</div></body></html>"
        )
        with pytest.raises(RuntimeError, match="state JSON failed to parse"):
            _extract_state_json(malformed)


class TestParsePageStructuralFailures:
    def test_missing_pdpCTOConfiguration_raises(self):
        # A page whose state JSON is valid but lacks the configurations path.
        html = (
            '<html><body><div id="data" style="display:none">'
            '<!-- {"slugInfo": {"components": {}}} -->'
            "</div></body></html>"
        )
        with pytest.raises(RuntimeError, match="no pdpCTOConfiguration"):
            parse_hp_product_page(
                html,
                OMEN_MAX_URL,
                anchors=[_anchor("hp_omen_max_16", OMEN_MAX_URL)],
            )


# ---------------------------------------------------------------------------
# _flatten_technical_specs (pure)
# ---------------------------------------------------------------------------


class TestFlattenTechnicalSpecs:
    def test_current_then_alternates_joined_with_newline(self):
        specs_list = [
            {
                "name": "Memory",
                "value": [
                    {
                        "value": "16 GB DDR5",
                        "subheading": "Included in Current Configuration",
                    },
                    {
                        "value": "32 GB DDR5<br />64 GB DDR5",
                        "subheading": "Alternate Options",
                    },
                ],
            }
        ]
        out = _flatten_technical_specs(specs_list)
        assert out == {"Memory": "16 GB DDR5\n32 GB DDR5\n64 GB DDR5"}

    def test_br_variants_split(self):
        specs_list = [
            {
                "name": "OS",
                "value": [
                    {
                        "value": "A<br>B<br />C<br/>D",
                        "subheading": "Alternate Options",
                    }
                ],
            }
        ]
        out = _flatten_technical_specs(specs_list)
        assert out["OS"] == "A\nB\nC\nD"

    def test_html_entities_decoded(self):
        specs_list = [
            {
                "name": "CPU",
                "value": [
                    {
                        "value": "Ryzen&trade; 7 &amp; &reg;",
                        "subheading": "Included in Current Configuration",
                    }
                ],
            }
        ]
        out = _flatten_technical_specs(specs_list)
        assert out["CPU"] == "Ryzen™ 7 & ®"

    def test_missing_name_dropped(self):
        specs_list = [
            {
                "name": "",
                "value": [{"value": "x", "subheading": "Included in Current Configuration"}],
            },
            {
                "value": [{"value": "y", "subheading": "Included in Current Configuration"}],
            },
        ]
        assert _flatten_technical_specs(specs_list) == {}

    def test_empty_value_list_drops_category(self):
        specs_list = [{"name": "Empty", "value": []}]
        assert _flatten_technical_specs(specs_list) == {}

    def test_unknown_subheading_treated_as_alternate(self):
        specs_list = [
            {
                "name": "X",
                "value": [
                    {
                        "value": "current-like",
                        "subheading": "Included in Current Configuration",
                    },
                    {"value": "mystery", "subheading": "Some New HP Heading"},
                ],
            }
        ]
        out = _flatten_technical_specs(specs_list)
        # current first, mystery (unknown) appended as alt
        assert out["X"] == "current-like\nmystery"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


class TestPickTitle:
    def test_prefers_tile_name(self):
        t = {"name": "OMEN MAX Gaming Laptop 16t-ah000, 16\""}
        shared = {"name": "Some stale JSON-LD name"}
        assert _pick_title(t, shared, OMEN_MAX_URL).startswith("OMEN MAX")

    def test_falls_back_to_shared_jsonld(self):
        t: dict = {"name": ""}
        shared = {"name": "JSON-LD name"}
        assert _pick_title(t, shared, OMEN_MAX_URL) == "JSON-LD name"

    def test_falls_back_to_url_slug(self):
        t: dict = {}
        shared: dict = {}
        title = _pick_title(t, shared, OMEN_MAX_URL)
        assert "omen" in title.lower()


class TestJsonldShared:
    def test_brand_from_nested_dict(self):
        assert _jsonld_shared({"brand": {"name": "HP"}}).get("brand") == "HP"

    def test_brand_as_string(self):
        assert _jsonld_shared({"brand": "HP"}).get("brand") == "HP"

    def test_rating_coerced(self):
        s = _jsonld_shared(
            {"aggregateRating": {"ratingValue": "4.5", "reviewCount": "42"}}
        )
        assert s["rating"] == 4.5
        assert s["review_count"] == 42

    def test_image_first_of_list(self):
        s = _jsonld_shared({"image": ["https://a.png", "https://b.png"]})
        assert s["image"] == "https://a.png"


class TestConfigSummary:
    def test_picks_gpu_ram_storage_display_on_omen(self):
        specs = {
            "Operating system": "Windows 11 Home",
            "Processor and graphics": "Intel Core Ultra 7 + RTX 5070 Ti\nalt",
            "Memory": "16 GB DDR5\nalt",
            "Storage": "512 GB SSD\nalt",
            "Display": "16\" 2K\nalt",
            "Color": "Black",
        }
        summary = _config_summary(specs)
        assert summary is not None
        parts = summary.split(" / ")
        assert len(parts) == 4
        assert "Intel" in parts[0] or "RTX" in parts[0]
        assert "16 GB" in parts[1]
        assert "SSD" in parts[2]
        assert "2K" in parts[3] or "16" in parts[3]

    def test_picks_merged_category_on_pavilion(self):
        specs = {
            "Operating system": "Windows 11",
            "Processor, graphics & memory": "Ryzen 5 + Radeon + 16 GB",
            "Storage": "512 GB",
            "Display": "16\" 1080p",
        }
        summary = _config_summary(specs)
        # "processor" substring hits the merged category; then memory is
        # skipped (already matched under processor); storage + display fill
        # the rest.
        assert summary is not None
        assert "Ryzen" in summary
        assert "512" in summary
        assert "1080p" in summary

    def test_empty_specs_returns_none(self):
        assert _config_summary({}) is None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistered:
    def test_hp_in_registry(self):
        assert "hp" in list_fetchers()

    def test_registered_callable_is_fetch_hp_product(self):
        from scrapers_lib.core.registry import get_fetcher

        assert get_fetcher("hp") is hp.fetch_hp_product
