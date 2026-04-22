"""Gated integration test for the BestBuy Developer API fetcher.

Runs only when both ``SCRAPERSLIB_LIVE_TESTS=1`` and ``BESTBUY_API_KEY``
are set; otherwise skipped. Hitting the real API verifies that the
synthetic fixture shape used by ``test_bestbuy_api.py`` matches the
actual Developer API contract.

The test URL may 404 once BestBuy retires the model; refresh by
picking a currently-listed SKU from ``bestbuy.com/site/...-laptops``
and updating ``LIVE_URL`` below.
"""

from __future__ import annotations

import os

import pytest

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier1.bestbuy_api import fetch_bestbuy_api_product

LIVE = bool(os.environ.get("SCRAPERSLIB_LIVE_TESTS"))
HAS_KEY = bool(os.environ.get("BESTBUY_API_KEY"))

# Placeholder 7-digit SKU. Pick a currently-listed gaming-laptop SKU
# from bestbuy.com and paste it here to run the test against a live
# product. BESTBUY_TEST_SKU env var overrides the default.
DEFAULT_TEST_SKU = os.environ.get("BESTBUY_TEST_SKU", "6571369")
LIVE_URL = (
    f"https://www.bestbuy.com/site/placeholder/{DEFAULT_TEST_SKU}.p"
    f"?skuId={DEFAULT_TEST_SKU}"
)


@pytest.mark.skipif(
    not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1"
)
@pytest.mark.skipif(
    not HAS_KEY, reason="BESTBUY_API_KEY not set; Developer API requires a key"
)
def test_fetch_bestbuy_product_live():
    anchor = Anchor(
        anchor_id="bestbuy_test_product",
        anchor_type="product",
        name=f"BestBuy SKU {DEFAULT_TEST_SKU}",
        attribution_regex=AttributionRegex(primary=[DEFAULT_TEST_SKU]),
        source_urls={"bestbuy_api": LIVE_URL},
    )

    snapshots = fetch_bestbuy_api_product(LIVE_URL, anchors=[anchor])

    assert len(snapshots) == 1
    s = snapshots[0]
    assert s.source == "bestbuy_api"
    assert s.source_id == DEFAULT_TEST_SKU
    assert s.url == LIVE_URL
    assert s.title
    assert s.raw["spec_source"] == "developer_api_details"
    assert s.raw["sku"] == DEFAULT_TEST_SKU

    # Every currently-listed product should carry at least one price
    # field and a handful of ``details`` rows; the API is stable enough
    # that blank responses mean the SKU is retired.
    assert s.price is not None or s.list_price is not None, (
        "no price on the live response — SKU likely retired; update "
        "DEFAULT_TEST_SKU in this file"
    )
    assert len(s.specs) >= 5, (
        f"only {len(s.specs)} spec rows; API contract may have changed"
    )
