"""Gated integration test for the YouTube transcript fetcher.

Runs only when ``SCRAPERSLIB_LIVE_TESTS=1`` is set. Hits
``youtube-transcript-api`` live for one stable, evergreen video
(Rick Astley — "Never Gonna Give You Up") chosen because:

1. It has always had captions (original + auto-translations).
2. It has been online since 2009 with no takedown risk.
3. Its content is predictable enough to test anchor matching.

YouTube has been tightening transcript-API access (``PoTokenRequired``
error class exists for a reason). If this test starts raising
``BlockedError``, the ``project_demo3_gaming_radar`` memory should
note it and we may need to revisit fetch strategy.
"""

from __future__ import annotations

import os

import pytest

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier1.youtube import fetch_youtube_transcript

LIVE = bool(os.environ.get("SCRAPERSLIB_LIVE_TESTS"))

VIDEO_ID = "dQw4w9WgXcQ"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_transcript_discovery_live():
    mentions = fetch_youtube_transcript(VIDEO_URL)
    # 211s video / 60s default chunking -> ~4 chunks.
    assert 2 <= len(mentions) <= 6, (
        f"unexpected chunk count {len(mentions)} — YT video shape may have changed"
    )
    for m in mentions:
        assert m.source == "youtube"
        assert m.source_type == "transcript_chunk"
        assert m.parent_id == VIDEO_ID
        assert m.attribution is None
        assert m.raw_text.strip()
        assert m.source_url.startswith(
            f"https://www.youtube.com/watch?v={VIDEO_ID}&t="
        )


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_transcript_anchor_mode_live():
    anchor = Anchor(
        anchor_id="never_gonna",
        anchor_type="topic",
        name="never gonna",
        attribution_regex=AttributionRegex(primary=["never gonna"]),
    )
    mentions = fetch_youtube_transcript(VIDEO_URL, anchors=[anchor])
    assert len(mentions) >= 1, "song title phrase should match at least one chunk"
    for m in mentions:
        assert m.attribution is not None
        assert m.attribution.anchor_id == "never_gonna"
        assert m.mention_id.endswith("_never_gonna")
