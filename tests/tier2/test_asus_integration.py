"""Gated integration tests for the ASUS fetcher.

Runs only when ``SCRAPERSLIB_LIVE_TESTS=1`` is set; otherwise skipped so
the default ``pytest`` run does not hit the network.

Two tests exercise the host dispatcher's two branches end-to-end:

- :func:`test_fetch_rog_strix_g16_live` — ``rog.asus.com`` path (Wave 2b
  in-module parser).
- :func:`test_fetch_zenbook_www_live` — ``www.asus.com`` path
  (Wave 2e step 4 dispatcher → :mod:`scrapers_lib.tier2.asus_www`).
"""

from __future__ import annotations

import os

import pytest

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier2.asus import fetch_asus_product

LIVE = bool(os.environ.get("SCRAPERSLIB_LIVE_TESTS"))

STRIX_URL = "https://rog.asus.com/laptops/rog-strix/rog-strix-g16-2025/spec/"
ZENBOOK_WWW_URL = (
    "https://www.asus.com/us/laptops/for-home/zenbook/asus-zenbook-14-ux3405/techspec/"
)


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


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_zenbook_www_live():
    """End-to-end www.asus.com path: dispatcher → asus_www → Nuxt eval."""
    anchor = Anchor(
        anchor_id="asus_zenbook_14_ux3405",
        anchor_type="product",
        name="ASUS Zenbook 14 (UX3405)",
        attribution_regex=AttributionRegex(primary=["Zenbook 14"]),
        source_urls={"asus": ZENBOOK_WWW_URL},
    )

    snapshots = fetch_asus_product(ZENBOOK_WWW_URL, anchors=[anchor])

    assert len(snapshots) == 1
    s = snapshots[0]
    assert s.source == "asus"
    assert s.anchor_id == anchor.anchor_id
    assert s.source_id == "asus-zenbook-14-ux3405"
    assert s.url == ZENBOOK_WWW_URL
    assert s.brand == "ASUS"
    assert s.specs, "spec dict unexpectedly empty"

    # JS-state extraction yields the full multi-SKU union — 25+ categories
    # is a safe floor for Zenbook (recon census shows 28).
    assert len(s.specs) >= 25

    # Demo-2 max-spec axes (the HP-gap axes specifically).
    for expected in (
        "Processor",
        "Graphics",
        "Memory",
        "Storage",
        "Display",
        "I/O Ports",
        "Weight",
        "Dimensions (W x D x H)",
        "Audio",
    ):
        assert expected in s.specs, f"missing expected category {expected!r}"

    # JS-state surface is the canonical provenance for this branch.
    assert s.raw["spec_source"] == "www_asus_pd_techspec_m2"
