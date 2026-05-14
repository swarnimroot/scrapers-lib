"""Unit tests for the audio-fallback path on tier1.youtube.

Two layers covered here:

1. **Wiring** — verify ``fetch_youtube_transcript`` routes correctly
   based on the ``audio_fallback`` flag and the outcome of the caption
   fetch (success / empty / BlockedError).
2. **The ``_youtube_audio`` module** — internal helpers with both
   ``yt_dlp`` and ``faster_whisper`` mocked out (the real extras are
   optional, so tests must run without them installed).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scrapers_lib.core.scheduler import BlockedError
from scrapers_lib.tier1 import _youtube_audio, youtube


# ---------------------------------------------------------------------------
# Wiring: fetch_youtube_transcript ↔ audio-fallback decision tree
# ---------------------------------------------------------------------------


def _stub_audio_snippets():
    return [
        {"text": "hello world", "start": 0.0, "duration": 2.0},
        {"text": "from audio", "start": 2.0, "duration": 2.0},
    ]


class TestAudioFallbackDecisionTree:
    def test_blocked_with_fallback_off_reraises(self, monkeypatch):
        def boom(*a, **kw):
            raise BlockedError("captions gated")

        monkeypatch.setattr(youtube, "_fetch_snippets", boom)
        with pytest.raises(BlockedError, match="captions gated"):
            youtube.fetch_youtube_transcript("dQw4w9WgXcQ")

    def test_blocked_with_fallback_on_routes_to_audio(self, monkeypatch):
        def boom(*a, **kw):
            raise BlockedError("captions gated")

        captured: dict = {}

        def fake_audio(video_id, *, model_name):
            captured["video_id"] = video_id
            captured["model_name"] = model_name
            return _stub_audio_snippets()

        monkeypatch.setattr(youtube, "_fetch_snippets", boom)
        monkeypatch.setattr(youtube, "_audio_fallback_snippets", fake_audio)
        out = youtube.fetch_youtube_transcript(
            "dQw4w9WgXcQ", audio_fallback=True
        )

        assert captured == {"video_id": "dQw4w9WgXcQ", "model_name": "small.en"}
        assert len(out) == 1
        assert "hello world" in out[0].raw_text
        assert "from audio" in out[0].raw_text

    def test_empty_with_fallback_off_returns_empty(self, monkeypatch):
        monkeypatch.setattr(youtube, "_fetch_snippets", lambda *a, **kw: [])
        out = youtube.fetch_youtube_transcript("dQw4w9WgXcQ")
        assert out == []

    def test_empty_with_fallback_on_routes_to_audio(self, monkeypatch):
        monkeypatch.setattr(youtube, "_fetch_snippets", lambda *a, **kw: [])

        called: dict = {}

        def fake_audio(video_id, *, model_name):
            called["hit"] = True
            return _stub_audio_snippets()

        monkeypatch.setattr(youtube, "_audio_fallback_snippets", fake_audio)
        out = youtube.fetch_youtube_transcript(
            "dQw4w9WgXcQ", audio_fallback=True
        )

        assert called.get("hit") is True
        assert len(out) == 1

    def test_real_snippets_skip_audio_even_with_fallback_on(self, monkeypatch):
        real = [{"text": "from captions", "start": 0.0, "duration": 1.0}]
        monkeypatch.setattr(youtube, "_fetch_snippets", lambda *a, **kw: real)

        def must_not_run(*a, **kw):
            raise AssertionError("audio fallback should not run on caption hit")

        monkeypatch.setattr(youtube, "_audio_fallback_snippets", must_not_run)
        out = youtube.fetch_youtube_transcript(
            "dQw4w9WgXcQ", audio_fallback=True
        )
        assert len(out) == 1
        assert out[0].raw_text == "from captions"

    def test_audio_model_kwarg_forwarded(self, monkeypatch):
        def boom(*a, **kw):
            raise BlockedError("gated")

        captured: dict = {}

        def fake_audio(video_id, *, model_name):
            captured["model"] = model_name
            return []

        monkeypatch.setattr(youtube, "_fetch_snippets", boom)
        monkeypatch.setattr(youtube, "_audio_fallback_snippets", fake_audio)
        youtube.fetch_youtube_transcript(
            "dQw4w9WgXcQ", audio_fallback=True, audio_model="base.en"
        )
        assert captured["model"] == "base.en"

    def test_audio_path_blocked_surfaces_as_blocked(self, monkeypatch):
        def boom(*a, **kw):
            raise BlockedError("captions gated")

        def audio_also_blocked(video_id, *, model_name):
            raise BlockedError("audio gated too")

        monkeypatch.setattr(youtube, "_fetch_snippets", boom)
        monkeypatch.setattr(
            youtube, "_audio_fallback_snippets", audio_also_blocked
        )
        with pytest.raises(BlockedError, match="audio gated too"):
            youtube.fetch_youtube_transcript(
                "dQw4w9WgXcQ", audio_fallback=True
            )

    def test_audio_returns_empty_yields_empty(self, monkeypatch):
        monkeypatch.setattr(youtube, "_fetch_snippets", lambda *a, **kw: [])
        monkeypatch.setattr(
            youtube,
            "_audio_fallback_snippets",
            lambda v, *, model_name: [],
        )
        out = youtube.fetch_youtube_transcript(
            "dQw4w9WgXcQ", audio_fallback=True
        )
        assert out == []

    def test_audio_snippets_produce_correct_deep_link(self, monkeypatch):
        def boom(*a, **kw):
            raise BlockedError("gated")

        audio = [
            {"text": "late in the video", "start": 100.5, "duration": 2.0},
            {"text": "still talking", "start": 102.5, "duration": 2.0},
        ]
        monkeypatch.setattr(youtube, "_fetch_snippets", boom)
        monkeypatch.setattr(
            youtube,
            "_audio_fallback_snippets",
            lambda v, *, model_name: audio,
        )
        out = youtube.fetch_youtube_transcript(
            "dQw4w9WgXcQ", audio_fallback=True
        )
        assert len(out) == 1
        # First snippet's start (100.5) → int(100.5) = 100 → ?t=100s.
        assert "&t=100s" in out[0].source_url


# ---------------------------------------------------------------------------
# _youtube_audio: fakes for yt_dlp + faster_whisper
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_model_cache():
    """Wipe the module-level WhisperModel cache between tests."""
    _youtube_audio._MODEL_CACHE.clear()
    yield
    _youtube_audio._MODEL_CACHE.clear()


class _FakeSegment:
    def __init__(self, text, start, end):
        self.text = text
        self.start = start
        self.end = end


class _FakeWhisperModel:
    """Stand-in for faster_whisper.WhisperModel."""

    def __init__(self, *args, **kwargs):
        self.init_args = (args, kwargs)

    def transcribe(self, audio_path, **opts):
        segments = [
            _FakeSegment("hello ", 0.0, 1.2),
            _FakeSegment("world", 1.2, 2.5),
            _FakeSegment("   ", 2.5, 2.8),  # whitespace-only → dropped
            _FakeSegment("from local STT", 2.8, 5.0),
        ]
        info = SimpleNamespace(language="en")
        return iter(segments), info


def _make_fake_ytdlp_module(behavior: str = "ok", message: str = ""):
    """Build a fake `yt_dlp` module whose `YoutubeDL.extract_info` behaves
    as requested. ``behavior`` ∈ {"ok", "unavailable", "blocked", "boom"}.
    """

    class _Utils:
        class DownloadError(Exception):
            pass

    class _FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            if behavior == "ok":
                # Materialize a fake audio file so _download_audio's
                # post-download existence check succeeds.
                target = self.opts["outtmpl"].replace("%(ext)s", "m4a")
                Path(target).write_bytes(b"\x00" * 16)
                return {"id": "abc", "ext": "m4a"}
            if behavior == "unavailable":
                raise _Utils.DownloadError(
                    message or "ERROR: [youtube] xyz: Video unavailable"
                )
            if behavior == "blocked":
                raise _Utils.DownloadError(
                    message or "ERROR: HTTP 429 Too Many Requests"
                )
            if behavior == "boom":
                raise RuntimeError(message or "disk full")
            raise AssertionError(f"unknown behavior {behavior!r}")

        def prepare_filename(self, info):
            return self.opts["outtmpl"].replace("%(ext)s", info.get("ext", "m4a"))

    module = SimpleNamespace(YoutubeDL=_FakeYDL, utils=_Utils)
    return module


class TestFetchAudioSnippets:
    def test_happy_path_returns_normalized_dicts(self, monkeypatch):
        monkeypatch.setattr(
            _youtube_audio, "_get_yt_dlp",
            lambda: _make_fake_ytdlp_module("ok"),
        )
        monkeypatch.setattr(
            _youtube_audio, "_get_faster_whisper", lambda: _FakeWhisperModel
        )

        out = _youtube_audio.fetch_audio_snippets("dQw4w9WgXcQ")

        assert len(out) == 3  # whitespace-only segment dropped
        # Text is stripped; start/duration carry through faithfully.
        assert out[0] == {"text": "hello", "start": 0.0, "duration": 1.2}
        assert out[1] == {"text": "world", "start": 1.2, "duration": pytest.approx(1.3)}
        assert out[2]["text"] == "from local STT"
        assert out[2]["start"] == 2.8
        assert out[2]["duration"] == pytest.approx(2.2)

    def test_model_cache_reused_across_calls(self, monkeypatch):
        monkeypatch.setattr(
            _youtube_audio, "_get_yt_dlp",
            lambda: _make_fake_ytdlp_module("ok"),
        )
        construction_count = {"n": 0}

        class _Counted(_FakeWhisperModel):
            def __init__(self, *a, **kw):
                construction_count["n"] += 1
                super().__init__(*a, **kw)

        monkeypatch.setattr(
            _youtube_audio, "_get_faster_whisper", lambda: _Counted
        )

        _youtube_audio.fetch_audio_snippets("dQw4w9WgXcQ")
        _youtube_audio.fetch_audio_snippets("dQw4w9WgXcQ")
        _youtube_audio.fetch_audio_snippets(
            "dQw4w9WgXcQ", model_name="small.en"
        )

        # Same model name three times → one construction.
        assert construction_count["n"] == 1

    def test_model_cache_keys_by_model_name(self, monkeypatch):
        monkeypatch.setattr(
            _youtube_audio, "_get_yt_dlp",
            lambda: _make_fake_ytdlp_module("ok"),
        )
        construction_count = {"n": 0}

        class _Counted(_FakeWhisperModel):
            def __init__(self, *a, **kw):
                construction_count["n"] += 1
                super().__init__(*a, **kw)

        monkeypatch.setattr(
            _youtube_audio, "_get_faster_whisper", lambda: _Counted
        )
        _youtube_audio.fetch_audio_snippets("dQw4w9WgXcQ", model_name="small.en")
        _youtube_audio.fetch_audio_snippets("dQw4w9WgXcQ", model_name="base.en")
        assert construction_count["n"] == 2

    def test_unavailable_video_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            _youtube_audio,
            "_get_yt_dlp",
            lambda: _make_fake_ytdlp_module("unavailable"),
        )
        monkeypatch.setattr(
            _youtube_audio, "_get_faster_whisper", lambda: _FakeWhisperModel
        )
        out = _youtube_audio.fetch_audio_snippets("dQw4w9WgXcQ")
        assert out == []

    @pytest.mark.parametrize(
        "msg",
        [
            "ERROR: Private video",
            "ERROR: This video has been removed by the user",
            "ERROR: Sign in to confirm your age",
            "ERROR: This live event will begin in 2 hours",
            "ERROR: Members-only content",
        ],
    )
    def test_unavailable_marker_variants_return_empty(self, monkeypatch, msg):
        monkeypatch.setattr(
            _youtube_audio,
            "_get_yt_dlp",
            lambda: _make_fake_ytdlp_module("unavailable", message=msg),
        )
        monkeypatch.setattr(
            _youtube_audio, "_get_faster_whisper", lambda: _FakeWhisperModel
        )
        assert _youtube_audio.fetch_audio_snippets("dQw4w9WgXcQ") == []

    def test_download_error_without_unavailable_marker_raises_blocked(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            _youtube_audio,
            "_get_yt_dlp",
            lambda: _make_fake_ytdlp_module("blocked"),
        )
        monkeypatch.setattr(
            _youtube_audio, "_get_faster_whisper", lambda: _FakeWhisperModel
        )
        with pytest.raises(BlockedError, match="yt-dlp refused"):
            _youtube_audio.fetch_audio_snippets("dQw4w9WgXcQ")

    def test_unexpected_exception_raises_blocked(self, monkeypatch):
        monkeypatch.setattr(
            _youtube_audio,
            "_get_yt_dlp",
            lambda: _make_fake_ytdlp_module("boom"),
        )
        monkeypatch.setattr(
            _youtube_audio, "_get_faster_whisper", lambda: _FakeWhisperModel
        )
        with pytest.raises(BlockedError, match="unexpected failure"):
            _youtube_audio.fetch_audio_snippets("dQw4w9WgXcQ")


# ---------------------------------------------------------------------------
# Lazy-import gates surface clear install hints when extras are absent.
# ---------------------------------------------------------------------------


class TestInstallHints:
    def test_missing_yt_dlp_raises_with_extras_hint(self, monkeypatch):
        # Setting sys.modules[name] = None forces `import name` to fail.
        monkeypatch.setitem(sys.modules, "yt_dlp", None)
        with pytest.raises(ImportError, match=r"\[youtube-audio\]"):
            _youtube_audio._get_yt_dlp()

    def test_missing_faster_whisper_raises_with_extras_hint(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "faster_whisper", None)
        with pytest.raises(ImportError, match=r"\[youtube-audio\]"):
            _youtube_audio._get_faster_whisper()
