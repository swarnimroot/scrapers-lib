"""Gated integration test for the ASUS ROG fetcher.

Runs only when ``SCRAPERSLIB_LIVE_TESTS=1`` is set; otherwise skipped so
the default ``pytest`` run does not hit the network. Fetches one real
ROG spec page and verifies the full pipeline produces a rich snapshot.
"""

from __future__ import annotations

import os

import pytest

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier2.asus import fetch_asus_product

LIVE = bool(os.environ.get("SCRAPERSLIB_LIVE_TESTS"))

STRIX_URL = "https://rog.asus.com/laptops/rog-strix/rog-strix-g16-2025/spec/"


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_rog_strix_g16_live():
    anchor = Anchor(
        anchor_id="asus_rog_strix_g16_2025",
        anchor_type="product",
        name="ASUS ROG Strix G16 (2025)",
        attribution_regex=AttributionRegex(primary=["ROG Strix G16"]),
        source_urls={"asus": STRIX_URL},
    )

    snapshots = fetch_asus_product(STRIX_URL, anchors=[anchor])

    assert len(snapshots) == 1
    s = snapshots[0]
    assert s.source == "asus"
    assert s.anchor_id == anchor.anchor_id
    assert s.source_id == "rog-strix-g16-2025"
    assert s.url == STRIX_URL
    assert s.title
    assert s.brand == "ASUS"
    assert s.specs, "spec dict unexpectedly empty"

    # ROG spec pages are rich — 20+ categories typical. Tolerate 15+ as a
    # safe floor for future structural changes.
    assert len(s.specs) >= 15

    # The Demo-2 max-spec axes must be covered.
    for expected in ("Processor", "Graphics", "Memory", "Storage", "Display"):
        assert expected in s.specs, f"missing expected category {expected!r}"
