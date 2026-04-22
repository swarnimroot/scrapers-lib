"""Gated integration test for the Lenovo PSREF fetcher.

Runs only when ``SCRAPERSLIB_LIVE_TESTS=1`` is set; otherwise skipped so the
default ``pytest`` run does not hit the network. Fetches one real PSREF
product via the public ``LoadSpecData`` endpoint and verifies the full
pipeline produces one :class:`ProductSnapshot` with rich structured specs.
"""

from __future__ import annotations

import os

import pytest

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier2.lenovo import fetch_lenovo_product

LIVE = bool(os.environ.get("SCRAPERSLIB_LIVE_TESTS"))

# This URL may 404 once Lenovo retires the model; refresh fixtures by
# re-running scripts/lenovo/ probes if that happens.
LEGION_URL = "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16AFR10H?tab=spec"


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_legion_pro_7_live():
    anchor = Anchor(
        anchor_id="lenovo_legion_pro_7_16afr10h",
        anchor_type="product",
        name="Lenovo Legion Pro 7 16AFR10H",
        attribution_regex=AttributionRegex(primary=["Legion Pro 7"]),
        source_urls={"lenovo": LEGION_URL},
    )

    snapshots = fetch_lenovo_product(LEGION_URL, anchors=[anchor])

    assert len(snapshots) == 1
    s = snapshots[0]
    assert s.source == "lenovo"
    assert s.anchor_id == anchor.anchor_id
    assert s.source_id == "Legion_Pro_7_16AFR10H"
    assert s.url == LEGION_URL
    assert s.title
    assert s.brand == "Lenovo"
    assert s.category == "Laptops"
    assert s.raw["spec_source"] == "loadspecdata"

    # PSREF's LoadSpecData for a modern laptop exposes several dozen feature
    # keys. Allow headroom for category churn but insist on real coverage.
    assert len(s.specs) >= 30, f"only {len(s.specs)} specs returned"

    # Sanity: a handful of well-known categories must be populated.
    joined_keys = "\n".join(s.specs.keys())
    assert "Performance > Processor" in joined_keys
    assert "Performance > Memory" in joined_keys
    assert "Performance > Storage" in joined_keys
    assert "Performance > Graphics" in joined_keys
