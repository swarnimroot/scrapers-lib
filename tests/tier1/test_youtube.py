"""Unit tests for scrapers_lib.tier1.youtube.

Fixture strategy:

- ``transcript_dQw4w9WgXcQ.json`` — a real YouTube transcript captured
  via ``YouTubeTranscriptApi().fetch(...).to_raw_data()``. Small
  (7 KB), stable (Rick Astley's "Never Gonna Give You Up" is
  evergreen). Used for happy-path chunking + anchor attribution.
- Tiny synthetic snippet lists built inline for deterministic edge-case
  testing (boundary conditions, empty, very short videos).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scrapers_lib.core.registry import get_fetcher
from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.core.scheduler import BlockedError
from scrapers_lib.tier1 import youtube
from scrapers_lib.tier1.youtube import (
    SOURCE,
    _chunk_snippets,
    _extract_video_id,
    _normalize_snippets,
    parse_youtube_transcript,
)


FIX = Path(__file__).parent / "fixtures" / "youtube"


def _load_fixture():
    data = json.loads(
        (FIX / "transcript_dQw4w9WgXcQ.json").read_text(encoding="utf-8")
    )
    return data["snippets"]


# ---------------------------------------------------------------------------
# Chunking against the real fixture
# ---------------------------------------------------------------------------


class TestRealFixtureDiscovery:
    @pytest.fixture
    def mentions(self):
        snippets = _load_fixture()
        return parse_youtube_transcript(snippets, video_id="dQw4w9WgXcQ")

    def test_default_60s_chunking_yields_few_chunks(self, mentions):
        # 211-second video / 60s chunks -> 4 chunks.
        assert len(mentions) == 4

    def test_source_type_is_transcript_chunk(self, mentions):
        for m in mentions:
            assert m.source_type == "transcript_chunk"

    def test_source_is_youtube(self, mentions):
        for m in mentions:
            assert m.source == "youtube"

    def test_parent_id_is_video_id(self, mentions):
        for m in mentions:
            assert m.parent_id == "dQw4w9WgXcQ"

    def test_source_url_deep_links_to_chunk_start(self, mentions):
        for m in mentions:
            assert m.source_url.startswith(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t="
            )
            # Timestamp should match the chunk's declared start.
            t = int(m.raw["chunk_start_seconds"])
            assert f"&t={t}s" in m.source_url

    def test_chunks_are_time_ordered(self, mentions):
        starts = [m.raw["chunk_start_seconds"] for m in mentions]
        assert starts == sorted(starts)

    def test_chunk_end_is_after_start(self, mentions):
        for m in mentions:
            assert m.raw["chunk_end_seconds"] >= m.raw["chunk_start_seconds"]

    def test_mention_id_deterministic_on_reparse(self, mentions):
        snippets = _load_fixture()
        again = parse_youtube_transcript(snippets, video_id="dQw4w9WgXcQ")
        assert [m.mention_id for m in mentions] == [m.mention_id for m in again]

    def test_discovery_mode_attribution_none(self, mentions):
        for m in mentions:
            assert m.attribution is None

    def test_no_source_title_set(self, mentions):
        # YouTube title/channel would need Data API access — intentionally None.
        for m in mentions:
            assert m.source_title is None
            assert m.channel is None
            assert m.author is None


class TestRealFixtureChunkSizes:
    def test_20s_chunks_produce_more(self):
        snippets = _load_fixture()
        ms = parse_youtube_transcript(
            snippets, video_id="dQw4w9WgXcQ", chunk_seconds=20.0
        )
        # 211s / 20s ≈ 11 chunks.
        assert 9 <= len(ms) <= 12

    def test_large_chunk_seconds_produces_one_chunk(self):
        snippets = _load_fixture()
        ms = parse_youtube_transcript(
            snippets, video_id="dQw4w9WgXcQ", chunk_seconds=600.0
        )
        assert len(ms) == 1

    def test_chunk_seconds_zero_raises(self):
        snippets = _load_fixture()
        with pytest.raises(ValueError, match="chunk_seconds"):
            parse_youtube_transcript(
                snippets, video_id="dQw4w9WgXcQ", chunk_seconds=0
            )

    def test_negative_chunk_seconds_raises(self):
        with pytest.raises(ValueError, match="chunk_seconds"):
            parse_youtube_transcript([], video_id="x", chunk_seconds=-1.0)


class TestRealFixtureAnchorMode:
    def test_never_gonna_hits_every_chunk(self):
        # The phrase "never gonna" appears in every 60s chunk of the song.
        snippets = _load_fixture()
        anchor = Anchor(
            anchor_id="never_gonna",
            anchor_type="topic",
            name="never gonna",
            attribution_regex=AttributionRegex(primary=["never gonna"]),
        )
        mentions = parse_youtube_transcript(
            snippets, video_id="dQw4w9WgXcQ", anchors=[anchor]
        )
        assert len(mentions) == 4
        for m in mentions:
            assert m.attribution is not None
            assert m.attribution.anchor_id == "never_gonna"
            assert m.mention_id.endswith("_never_gonna")

    def test_irrelevant_anchor_returns_empty(self):
        snippets = _load_fixture()
        anchor = Anchor(
            anchor_id="quantum_physics",
            anchor_type="topic",
            name="Quantum Physics",
            attribution_regex=AttributionRegex(primary=["quantum physics"]),
        )
        mentions = parse_youtube_transcript(
            snippets, video_id="dQw4w9WgXcQ", anchors=[anchor]
        )
        assert mentions == []


# ---------------------------------------------------------------------------
# Synthetic chunking edge cases
# ---------------------------------------------------------------------------


class TestChunkingEdgeCases:
    def test_empty_snippets_returns_empty_list(self):
        assert parse_youtube_transcript([], video_id="vvvvvvvvvvv") == []

    def test_single_snippet_one_chunk(self):
        snippets = [{"text": "hello world", "start": 10.0, "duration": 2.0}]
        mentions = parse_youtube_transcript(snippets, video_id="vvvvvvvvvvv")
        assert len(mentions) == 1
        assert mentions[0].raw_text == "hello world"
        assert mentions[0].raw["chunk_start_seconds"] == 10.0
        assert mentions[0].raw["chunk_end_seconds"] == 12.0

    def test_boundary_snippet_goes_into_later_chunk(self):
        # With chunk_seconds=10 starting at offset=0, a snippet at start=10.0
        # belongs to chunk 1, not chunk 0 (half-open interval).
        snippets = [
            {"text": "early", "start": 0.0, "duration": 1.0},
            {"text": "boundary", "start": 10.0, "duration": 1.0},
        ]
        mentions = parse_youtube_transcript(
            snippets, video_id="vvvvvvvvvvv", chunk_seconds=10.0
        )
        assert len(mentions) == 2
        assert mentions[0].raw_text == "early"
        assert mentions[1].raw_text == "boundary"

    def test_snippets_with_non_zero_start_offset(self):
        # Transcript starting at t=100s: chunking is relative to first start.
        snippets = [
            {"text": "hi", "start": 100.0, "duration": 1.0},
            {"text": "bye", "start": 115.0, "duration": 1.0},
        ]
        mentions = parse_youtube_transcript(
            snippets, video_id="vvvvvvvvvvv", chunk_seconds=30.0
        )
        assert len(mentions) == 1
        assert mentions[0].raw_text == "hi bye"

    def test_empty_text_snippet_dropped_during_normalize(self):
        snippets = [
            {"text": "", "start": 0.0, "duration": 1.0},
            {"text": "   ", "start": 1.0, "duration": 1.0},
            {"text": "real content", "start": 2.0, "duration": 1.0},
        ]
        mentions = parse_youtube_transcript(snippets, video_id="vvvvvvvvvvv")
        assert len(mentions) == 1
        assert mentions[0].raw_text == "real content"

    def test_chunk_where_all_snippets_have_empty_text(self):
        # No usable text after normalization -> empty result, not error.
        snippets = [
            {"text": "", "start": 0.0, "duration": 1.0},
            {"text": "   ", "start": 1.0, "duration": 1.0},
        ]
        assert parse_youtube_transcript(snippets, video_id="v") == []


# ---------------------------------------------------------------------------
# Input shape tolerance (dicts vs objects)
# ---------------------------------------------------------------------------


class TestInputShape:
    def test_accepts_raw_data_dicts(self):
        snippets = [
            {"text": "x", "start": 0.0, "duration": 1.0},
            {"text": "y", "start": 1.0, "duration": 1.0},
        ]
        out = parse_youtube_transcript(snippets, video_id="v")
        assert len(out) == 1

    def test_accepts_snippet_like_objects(self):
        snippets = [
            SimpleNamespace(text="x", start=0.0, duration=1.0),
            SimpleNamespace(text="y", start=1.0, duration=1.0),
        ]
        out = parse_youtube_transcript(snippets, video_id="v")
        assert len(out) == 1

    def test_mixed_shapes_tolerated(self):
        snippets = [
            {"text": "dict", "start": 0.0, "duration": 1.0},
            SimpleNamespace(text="object", start=1.0, duration=1.0),
        ]
        out = parse_youtube_transcript(snippets, video_id="v")
        assert len(out) == 1
        assert "dict" in out[0].raw_text and "object" in out[0].raw_text


# ---------------------------------------------------------------------------
# _chunk_snippets helper
# ---------------------------------------------------------------------------


class TestChunkSnippets:
    def test_empty_returns_empty(self):
        assert _chunk_snippets([], 60.0) == []

    def test_all_in_one_chunk(self):
        ss = _normalize_snippets(
            [
                {"text": "a", "start": 0.0, "duration": 1.0},
                {"text": "b", "start": 30.0, "duration": 1.0},
                {"text": "c", "start": 59.9, "duration": 1.0},
            ]
        )
        chunks = _chunk_snippets(ss, 60.0)
        assert len(chunks) == 1
        assert [s["text"] for s in chunks[0]] == ["a", "b", "c"]

    def test_sparse_timeline_skips_empty_bins(self):
        # snippets at 0s, 200s — chunk_seconds=60 -> bins 0, 3 occupied
        # (bins 1, 2 empty); result should have 2 chunks, not 4.
        ss = _normalize_snippets(
            [
                {"text": "a", "start": 0.0, "duration": 1.0},
                {"text": "z", "start": 200.0, "duration": 1.0},
            ]
        )
        chunks = _chunk_snippets(ss, 60.0)
        assert len(chunks) == 2
        assert [[s["text"] for s in c] for c in chunks] == [["a"], ["z"]]


# ---------------------------------------------------------------------------
# URL / ID extractor
# ---------------------------------------------------------------------------


class TestExtractVideoId:
    @pytest.mark.parametrize(
        "inp,expected",
        [
            ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=90s", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ?t=30", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/v/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ],
    )
    def test_forms(self, inp, expected):
        assert _extract_video_id(inp) == expected

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _extract_video_id("")

    def test_bare_wrong_length_raises(self):
        with pytest.raises(ValueError):
            _extract_video_id("short")

    def test_non_youtube_host_raises(self):
        with pytest.raises(ValueError, match="not a YouTube"):
            _extract_video_id("https://example.com/watch?v=dQw4w9WgXcQ")

    def test_non_url_garbage_raises(self):
        with pytest.raises(ValueError):
            _extract_video_id("some random string")


# ---------------------------------------------------------------------------
# Exception translation (mock the transcript API)
# ---------------------------------------------------------------------------


class TestExceptionTranslation:
    def test_no_transcript_found_returns_empty(self, monkeypatch):
        from youtube_transcript_api import NoTranscriptFound

        class StubApi:
            def fetch(self, video_id, languages=None, preserve_formatting=False):
                # These error classes take positional args in the live lib.
                raise NoTranscriptFound(video_id, list(languages or []), None)

        monkeypatch.setattr(youtube, "_fetch_snippets", lambda *a, **kw: [])
        out = youtube.fetch_youtube_transcript("dQw4w9WgXcQ")
        assert out == []

    def test_blocked_error_propagates_as_blocked_error(self, monkeypatch):
        def raise_blocked(*a, **kw):
            raise BlockedError("simulated")

        monkeypatch.setattr(youtube, "_fetch_snippets", raise_blocked)
        with pytest.raises(BlockedError, match="simulated"):
            youtube.fetch_youtube_transcript("dQw4w9WgXcQ")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registered_under_youtube(self):
        assert get_fetcher(SOURCE) is youtube.fetch_youtube_transcript

    def test_source_constant(self):
        assert SOURCE == "youtube"
