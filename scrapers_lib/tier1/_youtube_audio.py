"""Local-STT audio fallback for ``tier1.youtube`` — Tier 1 (optional).

When YouTube's caption endpoint is bot-gated (``PoTokenRequired`` /
``IpBlocked`` / ``RequestBlocked``) or the uploader has disabled
captions outright, ``fetch_youtube_transcript`` can route here instead
of giving up. The path is:

1. ``yt-dlp`` downloads audio-only (``bestaudio[ext=m4a]``, typically
   3-10 MB for a 10-minute video) to a process-local tempdir that is
   wiped on context exit.
2. ``faster-whisper`` (CTranslate2 build of OpenAI Whisper) transcribes
   the file locally on CPU; ``small.en`` is the default model
   (~150 MB weights, ~30 s wall time per 10-minute clip on a modern
   consumer CPU). Weights are cached lazily by the HuggingFace hub on
   first call.
3. Per-segment timestamps from faster-whisper are returned as
   ``{text, start, duration}`` dicts — the exact shape
   :func:`scrapers_lib.tier1.youtube.parse_youtube_transcript` already
   consumes, so chunking, anchor matching, and ``?t=Ns`` deep-link
   construction all keep working unchanged downstream.

Heavy dependencies are imported lazily and gated behind the
``[youtube-audio]`` extras package. Consumers that never call the
audio path pay nothing at import time and don't need to install
``yt-dlp`` / ``faster-whisper`` at all.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from scrapers_lib.core.scheduler import BlockedError

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "audio fallback requires the optional [youtube-audio] extra. "
    'Install with: pip install "scrapers-lib[youtube-audio]"'
)

# Markers in yt-dlp's DownloadError message that mean "video itself is
# gone / inaccessible" rather than "we got bot-gated". These map to
# `return []` (legitimate content-absence), not BlockedError.
_UNAVAILABLE_MARKERS = (
    "video unavailable",
    "private video",
    "this video is private",
    "video has been removed",
    "removed by the user",
    "removed by the uploader",
    "account associated with this video has been terminated",
    "video is no longer available",
    "this live event will begin",
    "premieres in",
    "members-only content",
    "sign in to confirm your age",
)

# Module-level cache: WhisperModel instances are expensive to construct
# (weight load + CTranslate2 JIT). Keyed by model name so callers can
# choose `small.en` / `base.en` / etc. on a per-call basis without
# re-paying the load cost.
_MODEL_CACHE: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fetch_audio_snippets(
    video_id: str,
    *,
    model_name: str = "small.en",
) -> list[dict[str, Any]]:
    """Download a video's audio and transcribe it locally.

    Returns a list of ``{text, start, duration}`` snippet dicts shaped
    exactly like ``youtube-transcript-api``'s ``to_raw_data()`` output,
    so the caller can hand them straight to
    :func:`parse_youtube_transcript` for chunking and attribution.

    Returns ``[]`` when the video itself is unavailable (private,
    deleted, region-locked, age-gated, members-only, upcoming
    livestream). Raises :class:`BlockedError` when yt-dlp's transport
    itself is being refused.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory(prefix="scrapers_lib_yt_") as tmpdir:
        audio_path = _download_audio(url, Path(tmpdir))
        if audio_path is None:
            return []
        # Materialize the generator while the audio file still exists.
        segments = list(_transcribe(audio_path, model_name=model_name))

    snippets: list[dict[str, Any]] = []
    for seg in segments:
        text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        start = float(getattr(seg, "start", 0.0) or 0.0)
        end = float(getattr(seg, "end", start) or start)
        snippets.append(
            {
                "text": text,
                "start": start,
                "duration": max(0.0, end - start),
            }
        )
    return snippets


# ---------------------------------------------------------------------------
# yt-dlp wrapper
# ---------------------------------------------------------------------------


def _download_audio(url: str, tmpdir: Path) -> Path | None:
    """Fetch ``url``'s best audio-only stream into ``tmpdir``.

    Returns the path to the downloaded file, or ``None`` when yt-dlp
    reports the video itself is unavailable (private / deleted /
    age-gated / region-locked / members-only / upcoming livestream).

    Raises :class:`BlockedError` for everything else (network refused,
    rate-limit, IP-block, PoToken on the audio stream).
    """
    yt_dlp = _get_yt_dlp()
    opts = {
        # Smallest reasonable audio: m4a (AAC) is the common YouTube
        # audio-only format, ~3-10 MB for a 10-minute clip. Fall through
        # to webm/opus or "any audio" if m4a isn't offered.
        "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
        "outtmpl": str(tmpdir / "audio.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        # We don't need any post-processing; faster-whisper / PyAV can
        # decode m4a, webm, opus directly without a system ffmpeg.
        "postprocessors": [],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e).lower()
        if any(marker in msg for marker in _UNAVAILABLE_MARKERS):
            logger.info(
                "youtube-audio: %s reported as unavailable by yt-dlp (%s); "
                "returning empty",
                url,
                e,
            )
            return None
        raise BlockedError(
            f"youtube-audio: yt-dlp refused {url}: {e}"
        ) from e
    except Exception as e:
        # Anything else (network, disk, unexpected) — treat as transport
        # failure so the Scheduler can back off on the domain.
        raise BlockedError(
            f"youtube-audio: yt-dlp unexpected failure on {url}: {e}"
        ) from e

    path = Path(filename)
    if not path.exists():
        # yt-dlp occasionally renames after post-processing. Pick up
        # whatever single audio file ended up in the tempdir.
        candidates = [
            p for p in tmpdir.iterdir() if p.is_file() and p.stat().st_size > 0
        ]
        if not candidates:
            logger.info(
                "youtube-audio: yt-dlp produced no file for %s; returning empty",
                url,
            )
            return None
        path = candidates[0]
    return path


# ---------------------------------------------------------------------------
# faster-whisper wrapper
# ---------------------------------------------------------------------------


def _transcribe(audio_path: Path, *, model_name: str):
    """Run faster-whisper on ``audio_path``; return its segments generator.

    The caller is responsible for materializing the generator before
    the audio file goes out of scope (faster-whisper streams segments
    lazily, reading the file as it goes).
    """
    model = _load_model(model_name)
    segments, _info = model.transcribe(
        str(audio_path),
        # beam_size=1 is meaningfully faster on CPU and the WER delta
        # vs beam=5 is negligible for the small.en model. If callers
        # want higher accuracy, they pick a bigger model, not bigger
        # beam.
        beam_size=1,
        # Suppress hallucination loops on long silences / music.
        condition_on_previous_text=False,
    )
    return segments


def _load_model(model_name: str):
    """Return a cached ``WhisperModel`` for ``model_name``.

    Configured for CPU + int8 quantization, which is the fastest
    CPU-only configuration faster-whisper supports and what we
    explicitly target (no-GPU consumer laptop).
    """
    if model_name not in _MODEL_CACHE:
        WhisperModel = _get_faster_whisper()
        logger.info("youtube-audio: loading faster-whisper model %s", model_name)
        _MODEL_CACHE[model_name] = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",
        )
    return _MODEL_CACHE[model_name]


# ---------------------------------------------------------------------------
# Lazy-import gates — raise a clear install hint when the extras are absent.
# ---------------------------------------------------------------------------


def _get_yt_dlp():
    try:
        import yt_dlp  # noqa: I001
        import yt_dlp.utils  # noqa: F401  (re-exports DownloadError)
    except ImportError as e:
        raise ImportError(_INSTALL_HINT) from e
    return yt_dlp


def _get_faster_whisper():
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise ImportError(_INSTALL_HINT) from e
    return WhisperModel
