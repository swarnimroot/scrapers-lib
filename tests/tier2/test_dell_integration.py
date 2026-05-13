"""Gated integration test for the Dell fetcher.

Runs only when ``SCRAPERSLIB_LIVE_TESTS=1`` is set; otherwise skipped so
the default ``pytest`` run does not hit the network. Fetches one real
Dell product page, verifies that the full pipeline produces one
:class:`ProductSnapshot` per tile with rich API-derived specs.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier2.dell import fetch_dell_product

LIVE = bool(os.environ.get("SCRAPERSLIB_LIVE_TESTS"))

# This URL may 404 once Dell retires the product; refresh by running the
# recon script and updating the fixtures if that happens.
AURORA_URL = (
    "https://www.dell.com/en-us/shop/dell-laptops/alienware-16x-aurora-gaming-laptop/"
    "spd/alienware-aurora-ac16251-gaming-laptop"
)


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_aurora_live(tmp_path: Path):
    anchor = Anchor(
        anchor_id="dell_alienware_aurora_16x",
        anchor_type="product",
        name="Alienware Aurora 16X",
        attribution_regex=AttributionRegex(primary=["Aurora 16X"]),
        source_urls={"dell": AURORA_URL},
    )

    snapshots = fetch_dell_product(
        AURORA_URL,
        anchors=[anchor],
        profiles_dir=tmp_path / "profiles",
    )

    # Dell pages in this shape have 3 pre-built tiles; allow for future
    # structure changes, but insist on at least one.
    assert len(snapshots) >= 1
    for s in snapshots:
        assert s.source == "dell"
        assert s.anchor_id == anchor.anchor_id
        assert s.source_id
        assert s.url == AURORA_URL
        assert s.title
        assert s.specs, f"tile {s.source_id} has no specs"
        # The techspecs API returns ~20 categories; accept bullet-fallback
        # (6 categories) if a single tile's API call happens to fail.
        assert len(s.specs) >= 6
        # Default flow does not enrich with configurator options.
        assert s.options is None


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_aurora_live_include_options(tmp_path: Path):
    """`include_options=True` should also pull the cty/pdp option menu."""
    anchor = Anchor(
        anchor_id="dell_alienware_aurora_16x",
        anchor_type="product",
        name="Alienware Aurora 16X",
        attribution_regex=AttributionRegex(primary=["Aurora 16X"]),
        source_urls={"dell": AURORA_URL},
    )

    snapshots = fetch_dell_product(
        AURORA_URL,
        anchors=[anchor],
        profiles_dir=tmp_path / "profiles",
        include_options=True,
    )

    assert len(snapshots) >= 1
    for s in snapshots:
        assert s.options is not None, f"tile {s.source_id}: options not enriched"
        # Aurora 16 / 16X both surface the same Processor / Graphics axes.
        assert "Processor" in s.options
        assert "Graphics" in s.options
        # Every option carries a non-empty label + recognized status.
        for module, opts in s.options.items():
            assert opts, f"module {module!r} has no options"
            for o in opts:
                assert o.label and o.option_id and o.status
