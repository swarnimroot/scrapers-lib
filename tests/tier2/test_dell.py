"""Unit tests for scrapers_lib.tier2.dell.

Tests run against committed HTML fixtures captured during Wave 2a
reconnaissance. No network.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from scrapers_lib.core.registry import list_fetchers
from scrapers_lib.core.schemas import Anchor, AttributionRegex, ComponentOption
from scrapers_lib.tier2 import dell
from scrapers_lib.tier2.dell import (
    _config_summary,
    _construct_cto_url,
    _extract_techspecs_endpoints,
    _extract_tiles,
    _jsonld_shared,
    _parse_techspecs_html,
    _parse_tile_bullets,
    parse_dell_configurator_options,
    parse_dell_product_page,
)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


FIX = Path(__file__).parent / "fixtures" / "dell"

AURORA_URL = (
    "https://www.dell.com/en-us/shop/dell-laptops/alienware-16x-aurora-gaming-laptop/"
    "spd/alienware-aurora-ac16251-gaming-laptop"
)
XPS_URL = (
    "https://www.dell.com/en-us/shop/dell-laptops/dell-xps-16-laptop/"
    "spd/xps-da16260-laptop"
)

AURORA_OCS = (
    "useac16251hbtshqfq",
    "useac16251hbtshqmy",
    "useac16251wmlkcto03",
)
XPS_OCS = (
    "useda16260hbtshyzd",
    "useda16260hbtshyzf",
    "useda16260wcto04_q1",
)


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _techspecs(ocs: tuple[str, ...]) -> dict[str, str]:
    return {oc: _load(f"techspecs_{oc}.txt") for oc in ocs}


def _anchor(anchor_id: str, url: str) -> Anchor:
    return Anchor(
        anchor_id=anchor_id,
        anchor_type="product",
        name=anchor_id.replace("_", " ").title(),
        attribution_regex=AttributionRegex(primary=[anchor_id]),
        source_urls={"dell": url},
    )


# ---------------------------------------------------------------------------
# parse_dell_product_page — Aurora, full techspecs coverage
# ---------------------------------------------------------------------------


class TestParseAuroraFull:
    @pytest.fixture
    def snapshots(self):
        html = _load("alienware_aurora_16x.html")
        return parse_dell_product_page(
            html,
            AURORA_URL,
            anchors=[_anchor("dell_alienware_aurora_16x", AURORA_URL)],
            techspecs_html_by_oc=_techspecs(AURORA_OCS),
        )

    def test_emits_three_snapshots(self, snapshots):
        assert len(snapshots) == 3

    def test_source_ids_match_known_ocs(self, snapshots):
        assert {s.source_id for s in snapshots} == set(AURORA_OCS)

    def test_variant_key_equals_source_id(self, snapshots):
        for s in snapshots:
            assert s.variant_key == s.source_id

    def test_all_snapshots_carry_anchor(self, snapshots):
        assert all(s.anchor_id == "dell_alienware_aurora_16x" for s in snapshots)

    def test_all_snapshots_are_dell(self, snapshots):
        assert all(s.source == "dell" for s in snapshots)

    def test_prices_match_captured_values(self, snapshots):
        by_oc = {s.source_id: s for s in snapshots}
        # Captured at fixture creation; if Dell re-prices, refresh the fixture.
        assert by_oc["useac16251hbtshqfq"].price == Decimal("1949.99")
        assert by_oc["useac16251hbtshqmy"].price == Decimal("2499.99")
        assert by_oc["useac16251wmlkcto03"].price == Decimal("2699.99")

    def test_list_prices_match_captured_values(self, snapshots):
        by_oc = {s.source_id: s for s in snapshots}
        assert by_oc["useac16251hbtshqfq"].list_price == Decimal("2499.99")
        assert by_oc["useac16251hbtshqmy"].list_price == Decimal("3299.99")
        assert by_oc["useac16251wmlkcto03"].list_price == Decimal("2919.99")

    def test_currency_default_usd(self, snapshots):
        assert all(s.currency == "USD" for s in snapshots)

    def test_brand_from_jsonld(self, snapshots):
        # JSON-LD lists brand as "Dell"; Alienware is the sub-brand/product name.
        assert all(s.brand == "Dell" for s in snapshots)

    def test_title_from_jsonld(self, snapshots):
        assert all("Alienware" in s.title for s in snapshots)

    def test_image_url_present(self, snapshots):
        assert all(s.image_url and s.image_url.startswith("http") for s in snapshots)

    def test_specs_came_from_api_not_bullets(self, snapshots):
        # API response carries 20+ categories; tile bullets carry 6.
        for s in snapshots:
            assert len(s.specs) >= 15, (
                f"tile {s.source_id} has only {len(s.specs)} specs — "
                f"API response may not have been applied"
            )
            assert s.raw == {"spec_source": "techspecs_api"}

    def test_rich_spec_content(self, snapshots):
        # The 5060 tile. Exact strings pulled from the Dell techspecs response.
        by_oc = {s.source_id: s for s in snapshots}
        specs = by_oc["useac16251hbtshqfq"].specs
        assert "Intel" in specs["Processor"]
        assert "Ultra 9" in specs["Processor"]
        assert "RTX" in specs["Graphics Card"] and "5060" in specs["Graphics Card"]
        assert "32GB" in specs["Memory"]
        assert "DDR5" in specs["Memory"]
        assert "2 TB" in specs["Storage"]
        assert "WQXGA" in specs["Display"]
        # Multi-line port spec preserved as newline-separated
        assert "Thunderbolt" in specs["Ports"]
        assert "\n" in specs["Ports"]
        assert "HDMI" in specs["Ports"]
        assert "Height (rear)" in specs["Dimensions & Weight"]
        assert "Wi-Fi 7" in specs["Wireless"]

    def test_config_summary_from_bullets(self, snapshots):
        by_oc = {s.source_id: s for s in snapshots}
        summary = by_oc["useac16251hbtshqfq"].config_summary
        assert summary is not None
        # Format "GPU / RAM / Storage / Display"
        assert "RTX" in summary and "5060" in summary
        assert "32 GB" in summary
        assert "2 TB" in summary


# ---------------------------------------------------------------------------
# parse_dell_product_page — XPS (different product line) full coverage
# ---------------------------------------------------------------------------


class TestParseXpsFull:
    """Proves the Dell pattern generalizes beyond Alienware gaming laptops."""

    @pytest.fixture
    def snapshots(self):
        html = _load("xps_16_9640.html")
        return parse_dell_product_page(
            html,
            XPS_URL,
            anchors=[_anchor("dell_xps_16", XPS_URL)],
            techspecs_html_by_oc=_techspecs(XPS_OCS),
        )

    def test_emits_three_snapshots(self, snapshots):
        assert len(snapshots) == 3

    def test_source_ids_match_known_ocs(self, snapshots):
        assert {s.source_id for s in snapshots} == set(XPS_OCS)

    def test_every_tile_has_api_specs(self, snapshots):
        for s in snapshots:
            assert len(s.specs) >= 15
            assert s.raw["spec_source"] == "techspecs_api"

    def test_prices_are_decimals(self, snapshots):
        for s in snapshots:
            assert s.price is None or isinstance(s.price, Decimal)
            assert s.list_price is None or isinstance(s.list_price, Decimal)

    def test_brand_present(self, snapshots):
        assert all(s.brand for s in snapshots)


# ---------------------------------------------------------------------------
# Fallback behavior when techspecs API response is unavailable
# ---------------------------------------------------------------------------


class TestFallbackToTileBullets:
    def test_missing_techspecs_uses_tile_bullets(self):
        html = _load("alienware_aurora_16x.html")
        snapshots = parse_dell_product_page(
            html,
            AURORA_URL,
            anchors=[_anchor("x", AURORA_URL)],
            techspecs_html_by_oc={},  # nothing from API
        )
        assert len(snapshots) == 3
        for s in snapshots:
            assert s.raw["spec_source"] == "tile_bullets"
            # Tile bullets contain exactly these six labels.
            assert "Processor" in s.specs
            assert "Graphics Card" in s.specs
            assert "Memory" in s.specs
            assert "Storage" in s.specs

    def test_partial_techspecs_mixes_sources(self):
        html = _load("alienware_aurora_16x.html")
        # Only the first tile gets API specs; the other two fall back.
        partial = {AURORA_OCS[0]: _load(f"techspecs_{AURORA_OCS[0]}.txt")}
        snapshots = parse_dell_product_page(
            html, AURORA_URL,
            anchors=[_anchor("x", AURORA_URL)],
            techspecs_html_by_oc=partial,
        )
        by_oc = {s.source_id: s for s in snapshots}
        assert by_oc[AURORA_OCS[0]].raw["spec_source"] == "techspecs_api"
        assert by_oc[AURORA_OCS[1]].raw["spec_source"] == "tile_bullets"
        assert by_oc[AURORA_OCS[2]].raw["spec_source"] == "tile_bullets"


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


class TestAttribution:
    def test_no_anchors_raises(self):
        html = _load("alienware_aurora_16x.html")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_dell_product_page(html, AURORA_URL)

    def test_anchor_url_mismatch_raises(self):
        html = _load("alienware_aurora_16x.html")
        wrong = _anchor("wrong", "https://www.dell.com/en-us/shop/some-other")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_dell_product_page(html, AURORA_URL, anchors=[wrong])

    def test_matching_anchor_used(self):
        html = _load("alienware_aurora_16x.html")
        a = _anchor("chosen_one", AURORA_URL)
        snapshots = parse_dell_product_page(
            html, AURORA_URL,
            anchors=[a],
            techspecs_html_by_oc=_techspecs(AURORA_OCS),
        )
        assert all(s.anchor_id == "chosen_one" for s in snapshots)


# ---------------------------------------------------------------------------
# Internal parser helpers
# ---------------------------------------------------------------------------


class TestExtractTechspecsEndpoints:
    def test_finds_all_three_aurora_endpoints(self):
        html = _load("alienware_aurora_16x.html")
        eps = _extract_techspecs_endpoints(html)
        assert set(eps.keys()) == set(AURORA_OCS)
        for oc, path in eps.items():
            assert path.startswith("/csbapi/unifiedpd/techspecs/")
            assert path.endswith(f"/{oc}")

    def test_finds_all_three_xps_endpoints(self):
        html = _load("xps_16_9640.html")
        eps = _extract_techspecs_endpoints(html)
        assert set(eps.keys()) == set(XPS_OCS)

    def test_empty_html_returns_empty_dict(self):
        assert _extract_techspecs_endpoints("<html></html>") == {}


class TestParseTechspecsHtml:
    def test_aurora_tile_has_expected_labels(self):
        html = _load("techspecs_useac16251hbtshqfq.txt")
        specs = _parse_techspecs_html(html)
        for label in ("Processor", "Graphics Card", "Memory", "Storage",
                      "Display", "Ports", "Dimensions & Weight", "Wireless",
                      "Keyboard"):
            assert label in specs, f"missing label {label!r}"

    def test_processor_value_rich(self):
        html = _load("techspecs_useac16251hbtshqfq.txt")
        specs = _parse_techspecs_html(html)
        # Full detail: includes cache/cores/speed parenthetical.
        v = specs["Processor"]
        assert "275HX" in v
        assert "36MB" in v or "cache" in v.lower()

    def test_ports_preserves_line_breaks(self):
        html = _load("techspecs_useac16251hbtshqfq.txt")
        specs = _parse_techspecs_html(html)
        assert "\n" in specs["Ports"]
        # nbsp & extra whitespace collapsed but line breaks kept.
        assert not any(line.strip() == "" for line in specs["Ports"].split("\n"))

    def test_asterisk_footnote_stripped_from_label(self):
        # The Memory label has a <span>*</span> footnote marker.
        html = _load("techspecs_useac16251hbtshqfq.txt")
        specs = _parse_techspecs_html(html)
        assert "Memory" in specs
        # Ensure we don't have labels like "Memory *"
        for k in specs:
            assert "*" not in k

    def test_operating_system_uses_value_not_preamble(self):
        # The OS spec has a "(Dell recommends Windows 11 Pro...)" preamble
        # before the actual value. We must pick the <p> value, not the preamble.
        html = _load("techspecs_useac16251hbtshqfq.txt")
        specs = _parse_techspecs_html(html)
        assert specs["Operating System"] == "Windows 11 Home"


class TestExtractTiles:
    def test_aurora_three_tiles(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(_load("alienware_aurora_16x.html"), "html.parser")
        tiles = _extract_tiles(soup)
        assert len(tiles) == 3
        assert {t["oc"] for t in tiles} == set(AURORA_OCS)

    def test_aurora_tile_prices_parsed(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(_load("alienware_aurora_16x.html"), "html.parser")
        tiles = _extract_tiles(soup)
        by_oc = {t["oc"]: t for t in tiles}
        assert by_oc["useac16251hbtshqfq"]["price"] == Decimal("1949.99")
        assert by_oc["useac16251hbtshqfq"]["list_price"] == Decimal("2499.99")

    def test_aurora_tile_bullets_parsed(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(_load("alienware_aurora_16x.html"), "html.parser")
        tiles = _extract_tiles(soup)
        t = next(t for t in tiles if t["oc"] == "useac16251hbtshqfq")
        assert "Processor" in t["bullet_specs"]
        assert "Intel" in t["bullet_specs"]["Processor"]
        assert "Tech Specs" not in t["bullet_specs"]


class TestJsonldShared:
    def test_brand_as_nested_dict(self):
        shared = _jsonld_shared({"brand": {"@type": "Brand", "name": "Dell"}})
        assert shared["brand"] == "Dell"

    def test_brand_as_string(self):
        shared = _jsonld_shared({"brand": "Alienware"})
        assert shared["brand"] == "Alienware"

    def test_rating_coerced_to_float(self):
        shared = _jsonld_shared(
            {"aggregateRating": {"ratingValue": "4.5", "reviewCount": "27"}}
        )
        assert shared["rating"] == 4.5
        assert shared["review_count"] == 27

    def test_image_as_string(self):
        shared = _jsonld_shared({"image": "https://example.com/a.jpg"})
        assert shared["image"] == "https://example.com/a.jpg"

    def test_image_as_list(self):
        shared = _jsonld_shared({"image": ["https://example.com/a.jpg", "b.jpg"]})
        assert shared["image"] == "https://example.com/a.jpg"

    def test_empty_input(self):
        assert _jsonld_shared({}) == {"name": None}


class TestConfigSummary:
    def test_full_summary(self):
        s = _config_summary({
            "Processor": "CPU X",
            "Graphics Card": "RTX 5060",
            "Memory": "32 GB",
            "Storage": "2 TB",
            "Display": "16 inch",
            "Operating System": "Windows",
        })
        assert s == "RTX 5060 / 32 GB / 2 TB / 16 inch"

    def test_partial_summary(self):
        assert _config_summary({"Memory": "8 GB"}) == "8 GB"

    def test_empty_returns_none(self):
        assert _config_summary({}) is None


class TestParseTileBullets:
    def test_tech_specs_button_skipped(self):
        # The Dell tile bullets are div+div inside each li; the trailing
        # "Tech Specs" button bullet has no value and must be dropped.
        from bs4 import BeautifulSoup
        html = (
            "<div>"
            "<ul>"
            "  <li><div>Processor</div><div>Intel i7</div></li>"
            "  <li><div>Memory</div><div>16 GB</div></li>"
            "  <li>Tech Specs</li>"
            "</ul>"
            "</div>"
        )
        soup = BeautifulSoup(html, "html.parser")
        specs = _parse_tile_bullets(soup.div)
        assert specs == {"Processor": "Intel i7", "Memory": "16 GB"}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistered:
    def test_dell_in_registry(self):
        # Loading the module side-registers; the import at the top of this
        # file guarantees it.
        assert "dell" in list_fetchers()

    def test_registered_callable_is_fetch_dell_product(self):
        from scrapers_lib.core.registry import get_fetcher
        assert get_fetcher("dell") is dell.fetch_dell_product


# ---------------------------------------------------------------------------
# _construct_cto_url
# ---------------------------------------------------------------------------


class TestConstructCtoUrl:
    def test_shop_landing_url_yields_cty_pdp(self):
        url = (
            "https://www.dell.com/en-us/shop/dell-laptops/"
            "alienware-16-aurora-gaming-laptop/spd/"
            "alienware-aurora-ac16250-gaming-laptop"
        )
        assert _construct_cto_url(url, "useac16250hbtshtgb") == (
            "https://www.dell.com/en-us/shop/cty/pdp/spd/"
            "alienware-aurora-ac16250-gaming-laptop/useac16250hbtshtgb"
        )

    def test_preserves_locale_prefix(self):
        url = (
            "https://www.dell.com/en-uk/shop/dell-laptops/some-product/"
            "spd/some-spd-slug"
        )
        assert _construct_cto_url(url, "ukabc123") == (
            "https://www.dell.com/en-uk/shop/cty/pdp/spd/some-spd-slug/ukabc123"
        )

    def test_empty_oc_returns_none(self):
        url = (
            "https://www.dell.com/en-us/shop/dell-laptops/x/spd/some-slug"
        )
        assert _construct_cto_url(url, "") is None

    def test_unrecognized_shape_returns_none(self):
        assert _construct_cto_url("https://www.dell.com/category-page", "useoc") is None
        assert _construct_cto_url("https://www.dell.com/en-us/shop/no-spd-segment", "useoc") is None


# ---------------------------------------------------------------------------
# parse_dell_configurator_options — fixture-driven
# ---------------------------------------------------------------------------


CTO_FIXTURE = "cto_useac16250hbtshtgb_after_scroll.html"
CTO_OC = "useac16250hbtshtgb"


class TestParseConfiguratorOptions:
    @pytest.fixture
    def options(self):
        return parse_dell_configurator_options(_load(CTO_FIXTURE))

    def test_returns_dict_keyed_by_module_name(self, options):
        assert isinstance(options, dict)
        for k, v in options.items():
            assert isinstance(k, str)
            assert isinstance(v, list)

    def test_ten_hardware_modules_present(self, options):
        # Per recon: Processor, OS, OS Language Pack, Graphics, Memory,
        # Storage, Display, Keyboard, Primary Battery, AC Adapter.
        assert len(options) == 10
        for expected in (
            "Processor",
            "Operating System",
            "Operating System Language Pack",
            "Graphics",
            "Memory",
            "Storage",
            "Display",
            "Keyboard",
            "Primary Battery",
            "AC Adapter",
        ):
            assert expected in options, f"missing module: {expected}"

    def test_module_order_matches_dom(self, options):
        # Dell renders Processor first and AC Adapter last on the Aurora 16
        # configurator. Insertion order should reflect that.
        keys = list(options.keys())
        assert keys[0] == "Processor"
        assert keys[-1] == "AC Adapter"

    def test_every_option_is_component_option(self, options):
        for opts in options.values():
            for o in opts:
                assert isinstance(o, ComponentOption)
                assert o.label
                assert o.option_id
                assert o.status

    def test_status_vocabulary_is_dell_specific(self, options):
        seen = {o.status for opts in options.values() for o in opts}
        assert seen.issubset({"selected", "available", "unavailable"})

    def test_each_module_has_exactly_one_selected(self, options):
        # Every module must surface a current default; Dell can't render a
        # configurator with nothing chosen.
        for module, opts in options.items():
            selected = [o for o in opts if o.status == "selected"]
            assert len(selected) == 1, (
                f"module {module!r} has {len(selected)} selected options"
            )

    def test_processor_options_match_recon(self, options):
        labels = [o.label for o in options["Processor"]]
        assert any("Core" in label and "240H" in label for label in labels)
        assert any("Core" in label and "270H" in label for label in labels)

    def test_graphics_carries_four_options(self, options):
        gpu = options["Graphics"]
        assert len(gpu) == 4
        # 5050 is the captured default
        selected = [o for o in gpu if o.status == "selected"]
        assert "5050" in selected[0].label

    def test_storage_size_options(self, options):
        labels = " | ".join(o.label for o in options["Storage"])
        assert "512 GB" in labels
        assert "1 TB" in labels

    def test_option_id_carries_module_id_prefix(self, options):
        # Dell's option_id is composite "<moduleId>-<sku>"; e.g. Processor's
        # module id is 146. The prefix is stable across both options.
        for o in options["Processor"]:
            assert o.option_id.startswith("146-"), o.option_id
        for o in options["Graphics"]:
            assert o.option_id.startswith("6-"), o.option_id

    def test_no_software_modules_surfaced(self, options):
        # Software / accessories live in a different DOM and must not
        # leak into the hardware options dict.
        for forbidden in ("Microsoft 365", "Microsoft Office", "Anti-Virus", "PDF Solutions"):
            assert forbidden not in options


class TestParseConfiguratorOptionsEdgeCases:
    def test_empty_html_returns_empty_dict(self):
        assert parse_dell_configurator_options("") == {}

    def test_unrelated_html_returns_empty_dict(self):
        html = "<html><body><div>nothing to see here</div></body></html>"
        assert parse_dell_configurator_options(html) == {}

    def test_module_with_no_options_is_omitted(self):
        # An accordion-box that has a title but zero options — skip it.
        html = (
            '<div class="accordion-box single-column-accordion">'
            '  <h2 class="module-title">Empty Module</h2>'
            '  <div class="options"></div>'
            "</div>"
        )
        assert parse_dell_configurator_options(html) == {}

    def test_option_missing_required_attrs_is_skipped(self):
        html = (
            '<div class="accordion-box single-column-accordion">'
            '  <h2 class="module-title">Processor</h2>'
            '  <div class="options">'
            '    <div class="option detailed-option">No attrs at all</div>'
            '    <div class="option detailed-option" data-option-id="146-A" data-status="selected">Real CPU</div>'
            "  </div>"
            "</div>"
        )
        result = parse_dell_configurator_options(html)
        assert list(result.keys()) == ["Processor"]
        assert len(result["Processor"]) == 1
        assert result["Processor"][0].option_id == "146-A"

    def test_duplicate_option_ids_deduped(self):
        html = (
            '<div class="accordion-box single-column-accordion">'
            '  <h2 class="module-title">Processor</h2>'
            '  <div class="options">'
            '    <div class="option detailed-option" data-option-id="146-A" data-status="selected">CPU A</div>'
            '    <div class="option detailed-option" data-option-id="146-A" data-status="selected">CPU A duplicate</div>'
            '    <div class="option detailed-option" data-option-id="146-B" data-status="available">CPU B</div>'
            "  </div>"
            "</div>"
        )
        result = parse_dell_configurator_options(html)
        assert len(result["Processor"]) == 2
        ids = [o.option_id for o in result["Processor"]]
        assert ids == ["146-A", "146-B"]


# ---------------------------------------------------------------------------
# parse_dell_product_page: configurator_options threading
# ---------------------------------------------------------------------------


class TestProductPageWithConfiguratorOptions:
    def _build_options(self) -> dict[str, list[ComponentOption]]:
        return {
            "Processor": [
                ComponentOption(label="CPU A", status="selected", option_id="146-A"),
                ComponentOption(label="CPU B", status="available", option_id="146-B"),
            ],
            "Graphics": [
                ComponentOption(label="GPU X", status="selected", option_id="6-X"),
            ],
        }

    def test_options_attached_to_every_snapshot(self):
        html = _load("alienware_aurora_16x.html")
        opts = self._build_options()
        snapshots = parse_dell_product_page(
            html,
            AURORA_URL,
            anchors=[_anchor("dell_alienware_aurora_16x", AURORA_URL)],
            techspecs_html_by_oc=_techspecs(AURORA_OCS),
            configurator_options=opts,
        )
        assert len(snapshots) == 3
        # Pydantic v2 validates+copies nested models on construction, so we
        # compare by value (not identity). Logically the same menu rides
        # along on every tile.
        for s in snapshots:
            assert s.options == opts
            assert "Processor" in s.options
            assert s.options["Processor"][0].option_id == "146-A"

    def test_options_default_to_none(self):
        # Backward-compat: omitting the kwarg keeps the field None.
        html = _load("alienware_aurora_16x.html")
        snapshots = parse_dell_product_page(
            html,
            AURORA_URL,
            anchors=[_anchor("dell_alienware_aurora_16x", AURORA_URL)],
            techspecs_html_by_oc=_techspecs(AURORA_OCS),
        )
        assert all(s.options is None for s in snapshots)
