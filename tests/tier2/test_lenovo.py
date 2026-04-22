"""Unit tests for scrapers_lib.tier2.lenovo.

Tests run against committed LoadSpecData JSON fixtures captured during
Wave 2b reconnaissance. No network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scrapers_lib.core.registry import list_fetchers
from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier2 import lenovo
from scrapers_lib.tier2.lenovo import (
    _extract_product_key,
    _flatten_spec_data,
    _serialize_feature,
    _serialize_fvgitem,
    parse_lenovo_product_page,
)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


FIX = Path(__file__).parent / "fixtures" / "lenovo"

LEGION_URL = "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16AFR10H?tab=spec"
LOQ_URL = "https://psref.lenovo.com/l/Product/LOQ/LOQ_15IRX10?tab=spec"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _anchor(anchor_id: str, url: str) -> Anchor:
    return Anchor(
        anchor_id=anchor_id,
        anchor_type="product",
        name=anchor_id.replace("_", " ").title(),
        attribution_regex=AttributionRegex(primary=[anchor_id]),
        source_urls={"lenovo": url},
    )


# ---------------------------------------------------------------------------
# parse_lenovo_product_page — Legion Pro 7 (AMD, gaming)
# ---------------------------------------------------------------------------


class TestParseLegionProFull:
    @pytest.fixture
    def snapshot(self):
        body = _load("loadspecdata_legion_pro_7_16afr10h.json")
        snaps = parse_lenovo_product_page(
            body,
            LEGION_URL,
            anchors=[_anchor("legion_pro_7_16afr10h", LEGION_URL)],
        )
        assert len(snaps) == 1
        return snaps[0]

    def test_source_is_lenovo(self, snapshot):
        assert snapshot.source == "lenovo"

    def test_source_id_is_product_key(self, snapshot):
        assert snapshot.source_id == "Legion_Pro_7_16AFR10H"

    def test_variant_key_is_none(self, snapshot):
        # Per-model granularity; option alternatives live inside specs, not as siblings.
        assert snapshot.variant_key is None

    def test_anchor_id_from_attribution(self, snapshot):
        assert snapshot.anchor_id == "legion_pro_7_16afr10h"

    def test_title_from_product_name(self, snapshot):
        assert snapshot.title == "Legion Pro 7 16AFR10H"

    def test_brand_is_lenovo(self, snapshot):
        assert snapshot.brand == "Lenovo"

    def test_category_from_classification(self, snapshot):
        assert snapshot.category == "Laptops"

    def test_raw_carries_provenance(self, snapshot):
        assert snapshot.raw["spec_source"] == "loadspecdata"
        assert snapshot.raw["product_key"] == "Legion_Pro_7_16AFR10H"
        assert snapshot.raw["classification"] == "Laptops"
        # ProductID is Lenovo's internal numeric identifier; preserve for debugging.
        assert snapshot.raw["product_id"]

    def test_specs_count_reasonable(self, snapshot):
        # LoadSpecData exposes ~50 feature keys per modern laptop.
        assert len(snapshot.specs) >= 40

    def test_url_and_pricing_fields(self, snapshot):
        # PSREF is a spec reference, not a shop — no price/stock/rating data.
        assert snapshot.url == LEGION_URL
        assert snapshot.price is None
        assert snapshot.list_price is None
        assert snapshot.in_stock is None
        assert snapshot.rating is None
        assert snapshot.review_count is None

    def test_rich_spec_content(self, snapshot):
        # Values verified from the LoadSpecData payload.
        specs = snapshot.specs

        # Multi-SKU Processor: two alternatives, one per line.
        proc = specs["Performance > Processor > Processor"]
        assert "AMD Ryzen" in proc
        assert "9955HX" in proc
        assert "9955HX3D" in proc  # second alternative
        assert "\n" in proc  # alternatives joined with newline
        assert proc.count("\n") == 1  # exactly two alternatives

        # Structured per-attribute format within one alternative
        assert "Cores: 16" in proc
        assert "Max Frequency: 5.4GHz" in proc

        # Processor Family — single DefaultDescription, unwrapped to bare value
        fam = specs["Performance > Processor > Processor Family"]
        assert fam == "AMD Ryzen™ 9 9000 Series Processor"

        # Other key categories must be present
        assert "Performance > Memory > Max Memory" in specs
        assert "Performance > Storage > Storage Type" in specs
        assert "Performance > Graphics > Graphics" in specs
        assert "Performance > Battery > Battery" in specs

    def test_html_entities_decoded(self, snapshot):
        # &trade; / &reg; / &amp; must all be unescaped into their characters.
        joined = "\n".join(snapshot.specs.values())
        assert "&trade;" not in joined
        assert "&reg;" not in joined
        assert "&amp;" not in joined
        # Positive check: the trademark symbol did arrive decoded somewhere.
        assert "™" in joined


# ---------------------------------------------------------------------------
# parse_lenovo_product_page — LOQ 15IRX10 (Intel, entry-level)
# ---------------------------------------------------------------------------


class TestParseLoqFull:
    """Generality: pattern must work beyond Legion/AMD. LOQ is a different
    product line (separate URL segment ``/Product/LOQ/``) with Intel chips."""

    @pytest.fixture
    def snapshot(self):
        body = _load("loadspecdata_loq_15irx10.json")
        snaps = parse_lenovo_product_page(
            body,
            LOQ_URL,
            anchors=[_anchor("loq_15irx10", LOQ_URL)],
        )
        assert len(snaps) == 1
        return snaps[0]

    def test_source_id(self, snapshot):
        assert snapshot.source_id == "LOQ_15IRX10"

    def test_title(self, snapshot):
        assert snapshot.title == "LOQ 15IRX10"

    def test_brand(self, snapshot):
        assert snapshot.brand == "Lenovo"

    def test_category(self, snapshot):
        assert snapshot.category == "Laptops"

    def test_processor_family_is_intel(self, snapshot):
        fam = snapshot.specs["Performance > Processor > Processor Family"]
        assert "Intel" in fam
        assert "Gen" in fam or "Generation" in fam

    def test_spec_keys_reasonable(self, snapshot):
        assert len(snapshot.specs) >= 40

    def test_same_top_level_categories_as_legion(self, snapshot):
        # The L1 set that appears in spec keys should match across products.
        l1_names = {k.split(" > ")[0] for k in snapshot.specs}
        assert "Performance" in l1_names
        assert "Design" in l1_names
        assert "Connectivity" in l1_names
        assert "Certifications" in l1_names


# ---------------------------------------------------------------------------
# URL → ProductKey
# ---------------------------------------------------------------------------


class TestExtractProductKey:
    def test_slash_l_form(self):
        assert _extract_product_key(LEGION_URL) == "Legion_Pro_7_16AFR10H"

    def test_legacy_form_no_slash_l(self):
        assert (
            _extract_product_key(
                "https://psref.lenovo.com/Product/Legion/Legion_Pro_7_16AFR10H?tab=spec"
            )
            == "Legion_Pro_7_16AFR10H"
        )

    def test_no_query_string(self):
        assert (
            _extract_product_key(
                "https://psref.lenovo.com/l/Product/LOQ/LOQ_15IRX10"
            )
            == "LOQ_15IRX10"
        )

    def test_trailing_slash_tolerated(self):
        assert (
            _extract_product_key(
                "https://psref.lenovo.com/l/Product/LOQ/LOQ_15IRX10/"
            )
            == "LOQ_15IRX10"
        )

    def test_url_fragment_ignored(self):
        assert (
            _extract_product_key(
                "https://psref.lenovo.com/l/Product/LOQ/LOQ_15IRX10#spec"
            )
            == "LOQ_15IRX10"
        )

    def test_wrong_host_raises(self):
        with pytest.raises(ValueError, match="psref.lenovo.com"):
            _extract_product_key(
                "https://www.lenovo.com/us/en/laptops/legion/legion-pro-7"
            )

    def test_wrong_path_shape_raises(self):
        with pytest.raises(ValueError, match="does not match"):
            _extract_product_key("https://psref.lenovo.com/some/other/path")

    def test_missing_line_segment_raises(self):
        with pytest.raises(ValueError, match="does not match"):
            _extract_product_key("https://psref.lenovo.com/Product/JustOne")


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


class TestAttribution:
    def test_no_anchors_raises(self):
        body = _load("loadspecdata_legion_pro_7_16afr10h.json")
        with pytest.raises(ValueError, match="no Anchor"):
            parse_lenovo_product_page(body, LEGION_URL)

    def test_anchor_url_mismatch_raises(self):
        body = _load("loadspecdata_legion_pro_7_16afr10h.json")
        wrong = _anchor(
            "wrong",
            "https://psref.lenovo.com/l/Product/ThinkPad/ThinkPad_X1_Something",
        )
        with pytest.raises(ValueError, match="no Anchor"):
            parse_lenovo_product_page(body, LEGION_URL, anchors=[wrong])

    def test_matching_anchor_used(self):
        body = _load("loadspecdata_legion_pro_7_16afr10h.json")
        a = _anchor("chosen_one", LEGION_URL)
        snaps = parse_lenovo_product_page(body, LEGION_URL, anchors=[a])
        assert snaps[0].anchor_id == "chosen_one"


# ---------------------------------------------------------------------------
# Payload error modes
# ---------------------------------------------------------------------------


class TestPayloadErrors:
    def test_malformed_json_raises(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_lenovo_product_page(
                "{not valid json",
                LEGION_URL,
                anchors=[_anchor("legion", LEGION_URL)],
            )

    def test_nonsuccess_code_raises(self):
        import json as _json
        payload = _json.dumps({"code": 0, "data": {}})
        with pytest.raises(ValueError, match="code="):
            parse_lenovo_product_page(
                payload,
                LEGION_URL,
                anchors=[_anchor("legion", LEGION_URL)],
            )

    def test_empty_general_spec_data_raises(self):
        import json as _json
        payload = _json.dumps(
            {"code": 1, "data": {"Classification": "Laptops", "GeneralSpecData": []}}
        )
        with pytest.raises(ValueError, match="GeneralSpecData empty"):
            parse_lenovo_product_page(
                payload,
                LEGION_URL,
                anchors=[_anchor("legion", LEGION_URL)],
            )

    def test_empty_spec_data_emits_snapshot_with_no_specs(self, caplog):
        import json as _json
        payload = _json.dumps(
            {
                "code": 1,
                "data": {
                    "Classification": "Laptops",
                    "GeneralSpecData": [
                        {
                            "ProductID": "9999",
                            "ProductName": "Hypothetical Product",
                            "GeneralSpecJson": _json.dumps(
                                {"data": {"SpecData": []}}
                            ),
                        }
                    ],
                },
            }
        )
        with caplog.at_level("WARNING"):
            snaps = parse_lenovo_product_page(
                payload,
                LEGION_URL,
                anchors=[_anchor("legion", LEGION_URL)],
            )
        assert len(snaps) == 1
        assert snaps[0].specs == {}
        assert snaps[0].title == "Hypothetical Product"
        assert any("SpecData empty" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestSerializeFvgItem:
    def test_default_description_unwrapped(self):
        items = [{"Att": "DefaultDescription", "AttV": "Just the prose"}]
        assert _serialize_fvgitem(items) == "Just the prose"

    def test_attribute_value_pairs(self):
        items = [
            {"Att": "Cores", "AttV": "16"},
            {"Att": "Threads", "AttV": "32"},
        ]
        assert _serialize_fvgitem(items) == "Cores: 16; Threads: 32"

    def test_html_entities_decoded(self):
        items = [{"Att": "Name", "AttV": "Ryzen&trade; 9 &amp; 7"}]
        assert _serialize_fvgitem(items) == "Name: Ryzen™ 9 & 7"

    def test_empty_items_returns_empty_string(self):
        assert _serialize_fvgitem([]) == ""

    def test_items_without_attv_dropped(self):
        items = [
            {"Att": "Cores", "AttV": "16"},
            {"Att": "Threads", "AttV": ""},
            {"Att": "Cache", "AttV": None},
        ]
        assert _serialize_fvgitem(items) == "Cores: 16"


class TestSerializeFeature:
    def test_multi_alternative_joined_with_newline(self):
        feature = {
            "FName": "Processor",
            "FVs": [
                {
                    "FVGs": [
                        {
                            "FVGItem": [
                                {"Att": "Name", "AttV": "CPU A"},
                                {"Att": "Cores", "AttV": "8"},
                            ]
                        }
                    ]
                },
                {
                    "FVGs": [
                        {
                            "FVGItem": [
                                {"Att": "Name", "AttV": "CPU B"},
                                {"Att": "Cores", "AttV": "16"},
                            ]
                        }
                    ]
                },
            ],
        }
        result = _serialize_feature(feature)
        assert "Name: CPU A; Cores: 8" in result
        assert "Name: CPU B; Cores: 16" in result
        assert result.count("\n") == 1

    def test_empty_fvs_returns_empty(self):
        assert _serialize_feature({"FName": "X", "FVs": []}) == ""

    def test_missing_fvs_returns_empty(self):
        assert _serialize_feature({"FName": "X"}) == ""


class TestFlattenSpecData:
    def test_builds_three_level_keys(self):
        spec_data = [
            {
                "L1": "Performance",
                "L2": [
                    {
                        "L2": "Processor",
                        "Features": [
                            {
                                "FName": "Processor Family",
                                "FVs": [
                                    {
                                        "FVGs": [
                                            {
                                                "FVGItem": [
                                                    {
                                                        "Att": "DefaultDescription",
                                                        "AttV": "Some family",
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        out = _flatten_spec_data(spec_data)
        assert out == {"Performance > Processor > Processor Family": "Some family"}

    def test_skips_blocks_with_missing_names(self):
        # L1 without a name should be skipped entirely.
        spec_data = [
            {
                "L1": "",
                "L2": [
                    {
                        "L2": "Processor",
                        "Features": [
                            {
                                "FName": "Processor",
                                "FVs": [
                                    {
                                        "FVGs": [
                                            {"FVGItem": [{"Att": "X", "AttV": "Y"}]}
                                        ]
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        assert _flatten_spec_data(spec_data) == {}

    def test_features_with_no_value_skipped(self):
        spec_data = [
            {
                "L1": "Performance",
                "L2": [
                    {
                        "L2": "Processor",
                        "Features": [
                            {"FName": "Empty Feature", "FVs": []},
                        ],
                    }
                ],
            }
        ]
        assert _flatten_spec_data(spec_data) == {}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistered:
    def test_lenovo_in_registry(self):
        assert "lenovo" in list_fetchers()

    def test_registered_callable_is_fetch_lenovo_product(self):
        from scrapers_lib.core.registry import get_fetcher
        assert get_fetcher("lenovo") is lenovo.fetch_lenovo_product
