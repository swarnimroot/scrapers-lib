"""Unit tests for scrapers_lib.tier2.asus_www.

Tests run against committed www.asus.com /techspec/ HTML fixtures captured
during Wave 2e step 4 reconnaissance. No network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scrapers_lib.core.registry import list_fetchers
from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier2 import asus, asus_www
from scrapers_lib.tier2.asus_www import (
    _config_summary,
    _extract_nuxt_iife,
    _extract_specs,
    _source_id_from_url,
    _split_content_rows,
    _title_from_state,
    parse_asus_www_product_page,
)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


FIX = Path(__file__).parent / "fixtures" / "asus_www"

ZENBOOK_URL = (
    "https://www.asus.com/us/laptops/for-home/zenbook/asus-zenbook-14-ux3405/techspec/"
)
VIVOBOOK_URL = (
    "https://www.asus.com/us/laptops/for-home/vivobook/vivobook-16-laptop-f1605/techspec/"
)
TUF_URL = (
    "https://www.asus.com/us/laptops/for-gaming/tuf-gaming/asus-tuf-gaming-a16-2025/techspec/"
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
# parse_asus_www_product_page — Zenbook 14 UX3405 (full feature surface)
# ---------------------------------------------------------------------------


class TestParseZenbookFull:
    @pytest.fixture
    def snapshot(self):
        html = _load("zenbook_14_ux3405.html")
        snaps = parse_asus_www_product_page(
            html,
            ZENBOOK_URL,
            anchors=[_anchor("asus_zenbook_14_ux3405", ZENBOOK_URL)],
        )
        assert len(snaps) == 1
        return snaps[0]

    def test_source_is_asus(self, snapshot):
        # Same SOURCE as ROG sibling; one anchor matches either surface.
        assert snapshot.source == "asus"

    def test_source_id_is_model_slug(self, snapshot):
        assert snapshot.source_id == "asus-zenbook-14-ux3405"

    def test_variant_key_is_none(self, snapshot):
        assert snapshot.variant_key is None

    def test_brand_normalized_to_asus(self, snapshot):
        # Match ROG sibling: parent brand for cross-vendor grouping.
        assert snapshot.brand == "ASUS"

    def test_anchor_id(self, snapshot):
        assert snapshot.anchor_id == "asus_zenbook_14_ux3405"

    def test_no_prices(self, snapshot):
        # www.asus.com /techspec/ is marketing, not shop — no prices.
        assert snapshot.price is None
        assert snapshot.list_price is None
        assert snapshot.in_stock is None

    def test_raw_provenance(self, snapshot):
        assert snapshot.raw["spec_source"] == "www_asus_pd_techspec_m2"
        assert snapshot.raw["product_slug"] == "asus-zenbook-14-ux3405"

    def test_spec_count_matches_recon(self, snapshot):
        # Recon census: 28 categories on Zenbook.
        assert len(snapshot.specs) == 28

    def test_hp_gap_axes_all_present(self, snapshot):
        # The whole point of Wave 2e step 4 is closing HP's coverage gap on
        # the manufacturer side — these axes must always be there.
        for expected in ("Dimensions (W x D x H)", "Weight", "I/O Ports", "Audio"):
            assert expected in snapshot.specs

    def test_standard_axes_present(self, snapshot):
        for expected in (
            "Processor",
            "Graphics",
            "Display",
            "Memory",
            "Storage",
            "Battery",
            "Power Supply",
            "Camera",
            "Network and Communication",
            "Operating System",
            "Security",
        ):
            assert expected in snapshot.specs

    def test_multi_sku_variants_preserved(self, snapshot):
        # Processor has multiple distinct CPU SKU options.
        proc = snapshot.specs["Processor"]
        assert "\n" in proc
        alts = proc.split("\n")
        assert len(alts) >= 3

    def test_dedup_collapses_repeated_values(self, snapshot):
        # Some specs (e.g. Battery) are identical across every SKU; dedup
        # collapses 6+ identical Content rows down.
        assert "\n" not in snapshot.specs["Battery"]

    def test_dimensions_in_both_units(self, snapshot):
        dims = snapshot.specs["Dimensions (W x D x H)"]
        assert "cm" in dims
        assert '"' in dims  # inch marks

    def test_config_summary_uses_first_row(self, snapshot):
        # The first row of each hint-matched spec drives the summary.
        cs = snapshot.config_summary
        assert cs is not None
        # Components separated by " / ".
        assert " / " in cs

    def test_specs_have_no_residual_br_tags(self, snapshot):
        # br variants should all be split, not landed in values.
        for v in snapshot.specs.values():
            assert "<br" not in v.lower()
            assert "</br" not in v.lower()


# ---------------------------------------------------------------------------
# Vivobook 16 F1605 — `</br>` separator generality
# ---------------------------------------------------------------------------


class TestParseVivobookFull:
    """Vivobook fixture uses ``</br>`` (sic) as a row separator instead of
    the ``<br>`` Zenbook + TUF use. The br-split regex must handle both.
    """

    @pytest.fixture
    def snapshot(self):
        html = _load("vivobook_16_f1605.html")
        snaps = parse_asus_www_product_page(
            html,
            VIVOBOOK_URL,
            anchors=[_anchor("asus_vivobook_16_f1605", VIVOBOOK_URL)],
        )
        return snaps[0]

    def test_source_id(self, snapshot):
        assert snapshot.source_id == "vivobook-16-laptop-f1605"

    def test_spec_count(self, snapshot):
        assert len(snapshot.specs) == 28

    def test_invalid_br_separator_split(self, snapshot):
        # Display has multi-SKU variants joined by `</br>` (sic) on Vivobook.
        # If the split regex were `<br>`-only, Display would emerge as a
        # single un-split blob; with the variant-tolerant regex it splits.
        display = snapshot.specs["Display"]
        assert "\n" in display

    def test_hp_gap_axes_all_present(self, snapshot):
        for expected in ("Dimensions (W x D x H)", "Weight", "I/O Ports", "Audio"):
            assert expected in snapshot.specs


# ---------------------------------------------------------------------------
# TUF Gaming A16 2025 — gaming-laptop schema (smaller spec set)
# ---------------------------------------------------------------------------


class TestParseTufGamingFull:
    """TUF Gaming pages have a slightly different schema than consumer
    Zenbook/Vivobook: 22 categories vs 28 (drops Color, Built-in Apps,
    MyASUS Features, Disclaimer; adds AURA SYNC).
    """

    @pytest.fixture
    def snapshot(self):
        html = _load("tuf_gaming_a16_2025.html")
        snaps = parse_asus_www_product_page(
            html,
            TUF_URL,
            anchors=[_anchor("asus_tuf_gaming_a16_2025", TUF_URL)],
        )
        return snaps[0]

    def test_source_id(self, snapshot):
        assert snapshot.source_id == "asus-tuf-gaming-a16-2025"

    def test_spec_count(self, snapshot):
        assert len(snapshot.specs) == 22

    def test_gaming_specific_category(self, snapshot):
        # AURA SYNC is gaming-specific and should be picked up if present.
        # Category-name capitalization drift: TUF uses "Keyboard and Touchpad"
        # while Zenbook/Vivobook use "Keyboard & Touchpad" — the parser
        # emits whatever Title is in state, no normalization.
        assert "Keyboard and Touchpad" in snapshot.specs

    def test_hp_gap_axes_all_present(self, snapshot):
        for expected in ("Dimensions (W x D x H)", "Weight", "I/O Ports", "Audio"):
            assert expected in snapshot.specs


# ---------------------------------------------------------------------------
# _extract_nuxt_iife — anchor + paren-balance
# ---------------------------------------------------------------------------


class TestExtractNuxtIIFE:
    def test_extracts_complete_statement_from_zenbook(self):
        html = _load("zenbook_14_ux3405.html")
        stmt = _extract_nuxt_iife(html)
        assert stmt.startswith("var __NUXT__ = (function(")
        assert stmt.endswith(");")

    def test_extracted_statement_balances_parens(self):
        html = _load("zenbook_14_ux3405.html")
        stmt = _extract_nuxt_iife(html)
        # Trim "var __NUXT__ = " prefix and ";" suffix to get the IIFE
        # expression itself; opening-and-closing paren counts must match.
        expr = stmt[len("var __NUXT__ = ") : -1]
        depth = 0
        in_str: str | None = None
        i = 0
        while i < len(expr):
            c = expr[i]
            if in_str is not None:
                if c == "\\":
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
                i += 1
                continue
            if c in ('"', "'"):
                in_str = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        assert depth == 0

    def test_anchor_missing_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="anchor not found"):
            _extract_nuxt_iife("<html><body>no nuxt here</body></html>")


# ---------------------------------------------------------------------------
# _split_content_rows — separator variants + tag stripping + dedupe
# ---------------------------------------------------------------------------


class TestSplitContentRows:
    def test_lowercase_br(self):
        assert _split_content_rows("a<br>b<br>c") == ["a", "b", "c"]

    def test_self_closing_br(self):
        assert _split_content_rows("a<br/>b<br />c") == ["a", "b", "c"]

    def test_uppercase_br(self):
        assert _split_content_rows("a<BR>b<BR>c") == ["a", "b", "c"]

    def test_invalid_close_br_sic(self):
        # Vivobook fixture's separator. Must split or its multi-SKU rows
        # collapse into a single un-split blob.
        assert _split_content_rows("a</br>b</br>c") == ["a", "b", "c"]

    def test_dedupe_preserves_first_occurrence(self):
        assert _split_content_rows("alpha<br>beta<br>alpha<br>gamma") == [
            "alpha",
            "beta",
            "gamma",
        ]

    def test_strips_inline_tags(self):
        # <sup>, <sub>, <span> appear inline within Content cells.
        assert _split_content_rows("Intel<sup>®</sup> Core™") == ["Intel® Core™"]

    def test_html_entities_decoded(self):
        assert _split_content_rows("a&amp;b<br>c&nbsp;d") == ["a&b", "c d"]

    def test_empty_rows_dropped(self):
        # Trailing/leading br produces empty parts — those are skipped.
        assert _split_content_rows("<br>x<br><br>y<br>") == ["x", "y"]

    def test_collapses_whitespace(self):
        assert _split_content_rows("foo   bar<br>baz") == ["foo bar", "baz"]


# ---------------------------------------------------------------------------
# _source_id_from_url — region prefix + /techspec/ trailing + rejection
# ---------------------------------------------------------------------------


class TestSourceIdFromUrl:
    def test_us_zenbook(self):
        assert (
            _source_id_from_url(
                "https://www.asus.com/us/laptops/for-home/zenbook/"
                "asus-zenbook-14-ux3405/techspec/"
            )
            == "asus-zenbook-14-ux3405"
        )

    def test_for_gaming_path(self):
        assert (
            _source_id_from_url(
                "https://www.asus.com/us/laptops/for-gaming/tuf-gaming/"
                "asus-tuf-gaming-a16-2025/techspec/"
            )
            == "asus-tuf-gaming-a16-2025"
        )

    def test_no_region_prefix(self):
        assert (
            _source_id_from_url(
                "https://www.asus.com/laptops/for-home/vivobook/"
                "vivobook-16-laptop-f1605/techspec"
            )
            == "vivobook-16-laptop-f1605"
        )

    def test_compound_locale_region(self):
        # Locale prefix can be hyphenated (me-en, sa-en, ...).
        assert (
            _source_id_from_url(
                "https://www.asus.com/me-en/laptops/for-home/zenbook/"
                "asus-zenbook-14-ux3405/techspec/"
            )
            == "asus-zenbook-14-ux3405"
        )

    def test_rejects_non_asus_host(self):
        with pytest.raises(ValueError, match="not an asus.com domain"):
            _source_id_from_url(
                "https://www.example.com/us/laptops/for-home/zenbook/"
                "asus-zenbook-14-ux3405/techspec/"
            )

    def test_rejects_missing_techspec_segment(self):
        with pytest.raises(ValueError, match="does not match"):
            _source_id_from_url(
                "https://www.asus.com/us/laptops/for-home/zenbook/"
                "asus-zenbook-14-ux3405/"
            )

    def test_rejects_rog_path_shape(self):
        # ROG paths lack the for-{home,gaming} segment + techspec suffix.
        with pytest.raises(ValueError, match="does not match"):
            _source_id_from_url(
                "https://www.asus.com/laptops/rog-strix/rog-strix-g16-2025/spec/"
            )


# ---------------------------------------------------------------------------
# Pure helpers that don't need a fixture
# ---------------------------------------------------------------------------


class TestExtractSpecsHandlesShape:
    def test_missing_state_returns_empty(self):
        assert _extract_specs({}) == {}

    def test_missing_pd_techspec_m2_returns_empty(self):
        assert _extract_specs({"state": {"PDPage": {}}}) == {}

    def test_extracts_simple_entry(self):
        state = {
            "state": {
                "PDPage": {
                    "PDTechSpecM2": {
                        "SpecList": [
                            {"Title": "Memory", "Content": "16GB<br>32GB"},
                        ]
                    }
                }
            }
        }
        assert _extract_specs(state) == {"Memory": "16GB\n32GB"}

    def test_skips_entry_without_title(self):
        state = {
            "state": {
                "PDPage": {
                    "PDTechSpecM2": {
                        "SpecList": [
                            {"Title": "", "Content": "x"},
                            {"Title": "Storage", "Content": "1TB"},
                        ]
                    }
                }
            }
        }
        assert _extract_specs(state) == {"Storage": "1TB"}

    def test_first_occurrence_wins_on_duplicate_title(self):
        state = {
            "state": {
                "PDPage": {
                    "PDTechSpecM2": {
                        "SpecList": [
                            {"Title": "Memory", "Content": "16GB"},
                            {"Title": "Memory", "Content": "32GB"},
                        ]
                    }
                }
            }
        }
        assert _extract_specs(state) == {"Memory": "16GB"}


class TestTitleFromState:
    def test_pulls_name(self):
        state = {
            "state": {
                "PDPage": {"PDFirstScreen": {"Name": "Zenbook 14 (UX3405)"}}
            }
        }
        assert _title_from_state(state) == "Zenbook 14 (UX3405)"

    def test_falls_back_to_product_name(self):
        state = {
            "state": {
                "PDPage": {"PDFirstScreen": {"ProductName": "Vivobook 16"}}
            }
        }
        assert _title_from_state(state) == "Vivobook 16"

    def test_returns_none_when_missing(self):
        assert _title_from_state({}) is None

    def test_returns_none_for_blank_name(self):
        state = {"state": {"PDPage": {"PDFirstScreen": {"Name": "   "}}}}
        assert _title_from_state(state) is None


class TestConfigSummary:
    def test_uses_first_row_per_hint(self):
        specs = {
            "Graphics": "Intel Arc\nNVIDIA RTX 4060",
            "Memory": "32GB\n16GB",
            "Storage": "1TB",
            "Display": "14-inch OLED",
            "Other": "ignored",
        }
        cs = _config_summary(specs)
        assert cs == "Intel Arc / 32GB / 1TB / 14-inch OLED"

    def test_empty_specs_returns_none(self):
        assert _config_summary({}) is None

    def test_skips_missing_hints(self):
        # If only Storage matches, the summary still emits it.
        cs = _config_summary({"Storage": "1TB"})
        assert cs == "1TB"


# ---------------------------------------------------------------------------
# Attribution + missing-spec error contracts
# ---------------------------------------------------------------------------


class TestAttributionContract:
    def test_no_matching_anchor_raises_value_error(self):
        html = _load("zenbook_14_ux3405.html")
        # Anchor's source_url doesn't equal the URL we're parsing.
        bad = _anchor("asus_zenbook_14_ux3405", "https://www.asus.com/wrong/")
        with pytest.raises(ValueError, match="no Anchor has source_urls"):
            parse_asus_www_product_page(html, ZENBOOK_URL, anchors=[bad])

    def test_no_anchors_raises_value_error(self):
        html = _load("zenbook_14_ux3405.html")
        with pytest.raises(ValueError):
            parse_asus_www_product_page(html, ZENBOOK_URL, anchors=[])


# ---------------------------------------------------------------------------
# asus.fetch_asus_product host dispatcher
# ---------------------------------------------------------------------------


class TestAsusHostDispatch:
    def test_registry_has_single_asus_entry(self):
        # asus_www must NOT register separately — it shares SOURCE with ROG
        # via host dispatch in asus.fetch_asus_product.
        names = list(list_fetchers())
        assert names.count("asus") == 1

    def test_module_constants_share_source(self):
        assert asus.SOURCE == asus_www.SOURCE == "asus"

    def test_dispatch_routes_www_host(self, monkeypatch):
        # The dispatcher should call asus_www.fetch_asus_www_product for
        # www.asus.com URLs and never reach asus._fetch_spec_page.
        called: dict[str, object] = {}

        def fake_www(url, anchors=None, *, timeout=30.0, **_):
            called["url"] = url
            called["anchors"] = anchors
            called["timeout"] = timeout
            return ["sentinel"]

        def fake_rog(*a, **kw):
            raise AssertionError("rog path should not run for www host")

        monkeypatch.setattr(
            "scrapers_lib.tier2.asus_www.fetch_asus_www_product", fake_www
        )
        monkeypatch.setattr(asus, "_fetch_spec_page", fake_rog)

        out = asus.fetch_asus_product(ZENBOOK_URL, anchors=[], timeout=42.0)
        assert out == ["sentinel"]
        assert called["url"] == ZENBOOK_URL
        assert called["timeout"] == 42.0

    def test_dispatch_does_not_route_rog_host(self, monkeypatch):
        # rog.asus.com URLs must NOT delegate to asus_www.
        def fake_www(*a, **kw):
            raise AssertionError("www path should not run for rog host")

        sentinel = object()

        def fake_rog(url, *, timeout):
            return "<html>rog body</html>"

        monkeypatch.setattr(
            "scrapers_lib.tier2.asus_www.fetch_asus_www_product", fake_www
        )
        monkeypatch.setattr(asus, "_fetch_spec_page", fake_rog)

        def fake_parse(html, url, *, anchors=None):
            return [sentinel]

        monkeypatch.setattr(asus, "parse_asus_product_page", fake_parse)

        out = asus.fetch_asus_product(
            "https://rog.asus.com/laptops/rog-strix/rog-strix-g16-2025/spec/",
            anchors=[],
        )
        assert out == [sentinel]
