"""Gated integration test for the HP shop PDP fetcher.

Runs only when ``SCRAPERSLIB_LIVE_TESTS=1`` is set; otherwise skipped so
the default ``pytest`` run does not hit the network. Fetches one real HP
Omen shop PDP and verifies the full pipeline produces per-tile snapshots
with rich spec content.
"""

from __future__ import annotations

import os

import pytest

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier2.hp import fetch_hp_product

LIVE = bool(os.environ.get("SCRAPERSLIB_LIVE_TESTS"))

# This URL may 404 or restructure once HP retires the model; refresh the
# fixtures by re-running scripts/hp/ probes if that happens.
OMEN_MAX_URL = (
    "https://www.hp.com/us-en/shop/pdp/omen-max-gaming-laptop-16t-ah000-16-a4nq6av-1"
)


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_omen_max_live():
    anchor = Anchor(
        anchor_id="hp_omen_max_16t_ah000",
        anchor_type="product",
        name="HP OMEN MAX Gaming Laptop 16t-ah000",
        attribution_regex=AttributionRegex(primary=["OMEN Max"]),
        source_urls={"hp": OMEN_MAX_URL},
    )

    snapshots = fetch_hp_product(OMEN_MAX_URL, anchors=[anchor])

    # HP's Omen Max typically ships with 3 Recommended Configurations, but
    # allow more or fewer if HP changes merchandising.
    assert len(snapshots) >= 1
    for s in snapshots:
        assert s.source == "hp"
        assert s.anchor_id == anchor.anchor_id
        assert s.source_id
        assert s.variant_key == s.source_id
        assert s.url == OMEN_MAX_URL
        assert s.title
        assert s.brand == "HP"
        assert s.specs, f"tile {s.source_id} has no specs"
        # HP's pdpCTOConfiguration exposes ~12 config-picker categories.
        # Tolerate 9+ as a reasonable floor for future structural changes.
        assert len(s.specs) >= 9
        # At least one Processor-adjacent category must be present — names
        # vary ("Processor and graphics" / "Processor, graphics & memory").
        assert any("processor" in k.lower() for k in s.specs)
