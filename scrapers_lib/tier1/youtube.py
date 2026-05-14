"""YouTube transcript fetcher (``youtube-transcript-api``) — Tier 1.

Pulls auto-generated or human-authored captions from a public YouTube
video, groups the fine-grained per-word snippets into coherent
time-windowed chunks (default 60 s ≈ ~150 words of speech), and emits
one :class:`RawMention` per chunk.

Partial-success is first-class: videos without captions
(``NoTranscriptFound``, ``TranscriptsDisabled``), unavailable videos
(``VideoUnavailable``), and videos in languages we didn't request all
return an **empty list** rather than raising. Genuine bot-gate hits
(``RequestBlocked``, ``IpBlocked``, ``PoTokenRequired``) raise
:class:`BlockedError` so the Scheduler can back off at the domain level.

Audio fallback (opt-in via ``audio_fallback=True``): YouTube's caption
endpoint became POT-gated through 2025-2026; in practice roughly half
of caption requests from residential IPs are now refused. Passing
``audio_fallback=True`` routes bot-gated and caption-absent videos to
:mod:`._youtube_audio`, which downloads audio with ``yt-dlp`` and
transcribes locally with ``faster-whisper`` on CPU. The audio path
requires the ``[youtube-audio]`` extras package and is otherwise off
by default — consumers that don't enable it pay nothing.

Dual-mode (discovery / anchor-driven) matches :mod:`tier1.rss`,
:mod:`tier1.article`, and :mod:`tier1.reddit`.

Metadata gap (intentional): the YouTube Data API is required for rich
metadata (channel name, title, published date, category) and would
need credentials we don't have. The transcript API returns only the
caption track. Consequently the emitted :class:`RawMention` carries:

- ``source_url`` — deep-linked to the chunk's start timestamp
  (``?t=<start>s``) so consumers can jump back to the exact moment.
- ``parent_id`` — the video ID (so chunks cluster by video downstream).
- No ``source_title`` / ``author`` / ``channel``.  Consumers that need
  those should enrich via a separate metadata call.

``youtube_transcript_api`` is imported lazily so ``import scrapers_lib``
stays cheap for consumers that never touch Wave 3.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from scrapers_lib.core.attribution import (
    attribute_regex_all,
    youtube_chunk_id,
)
from scrapers_lib.core.registry import register
from scrapers_lib.core.schemas import Anchor, Attribution, RawMention
from scrapers_lib.core.scheduler import BlockedError

logger = logging.getLogger(__name__)

SOURCE = "youtube"

# YouTube video IDs are 11 characters: letters (both cases), digits,
# underscore, hyphen. This is tight enough to reject paths of other
# lengths (playlists, channels).
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Hostnames we will accept a URL from.
_YT_HOSTS = (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register(SOURCE)
def fetch_youtube_transcript(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    languages: tuple[str, ...] = ("en",),
    chunk_seconds: float = 60.0,
    preserve_formatting: bool = False,
    audio_fallback: bool = False,
    audio_model: str = "small.en",
    **_: Any,
) -> list[RawMention]:
    """Fetch a video's captions; emit :class:`RawMention` per chunked segment.

    ``url`` accepts any YouTube watch / embed / youtu.be / shorts URL,
    or a bare 11-char video ID.

    ``languages`` is a priority-ordered list of language codes
    (``("en",)`` default). If the video has no caption track in any of
    the requested languages, the fetcher returns ``[]``.

    ``chunk_seconds`` controls how tightly the raw transcript snippets
    are grouped. The default 60 s is a reasonable floor for gaming-
    review content (~150 English words of speech per chunk, enough for
    sentiment / anchor matching). Reduce for finer temporal granularity;
    increase for coarser, paragraph-level chunks.

    ``audio_fallback`` (default ``False``) turns on a local speech-to-
    text safety net. When ``True``, two conditions route to the audio
    path: (a) the caption endpoint raises :class:`BlockedError`
    (PoToken / IpBlocked / RequestBlocked); (b) the caption endpoint
    returns ``[]`` (uploader disabled captions, no caption track in
    the requested languages, etc.). yt-dlp downloads audio-only,
    faster-whisper transcribes locally on CPU, and the resulting
    timestamped segments flow through the same chunking + deep-link
    logic as native captions. Requires ``pip install
    "scrapers-lib[youtube-audio]"``. See :mod:`._youtube_audio`.

    ``audio_model`` selects the faster-whisper model when the audio
    path runs. Default ``"small.en"`` (~150 MB weights, ~30 s wall time
    per 10-minute clip on a modern consumer CPU, solid WER for product
    / gaming review vocabulary). Other useful choices: ``"base.en"``
    (faster, slightly worse), ``"medium.en"`` (slower, better WER).

    Raises :class:`BlockedError` when YouTube is clearly refusing the
    request (rate-limit, IP block, PoToken required) *and*
    ``audio_fallback`` is off or itself blocked. Returns ``[]`` for
    videos that legitimately lack captions when ``audio_fallback`` is
    off, or that are also unavailable to the audio path (private,
    deleted, age-gated, region-locked).
    """
    video_id = _extract_video_id(url)
    try:
        snippets = _fetch_snippets(
            video_id,
            languages=languages,
            preserve_formatting=preserve_formatting,
        )
    except BlockedError:
        if not audio_fallback:
            raise
        logger.info(
            "youtube: captions bot-gated for %s; routing to audio fallback",
            video_id,
        )
        snippets = _audio_fallback_snippets(video_id, model_name=audio_model)
    else:
        if not snippets and audio_fallback:
            logger.info(
                "youtube: no captions for %s; routing to audio fallback",
                video_id,
            )
            snippets = _audio_fallback_snippets(video_id, model_name=audio_model)

    return parse_youtube_transcript(
        snippets,
        video_id=video_id,
        anchors=anchors,
        chunk_seconds=chunk_seconds,
    )


def _audio_fallback_snippets(
    video_id: str,
    *,
    model_name: str,
) -> list[dict[str, Any]]:
    """Thin wrapper around :mod:`._youtube_audio` with lazy import.

    Kept as a module-level function (not inlined) so tests can
    ``monkeypatch.setattr(youtube, "_audio_fallback_snippets", ...)``
    to exercise the fallthrough wiring without needing the
    ``[youtube-audio]`` extras installed.
    """
    from ._youtube_audio import fetch_audio_snippets

    return fetch_audio_snippets(video_id, model_name=model_name)


def parse_youtube_transcript(
    snippets: list[dict[str, Any]] | list[Any],
    *,
    video_id: str,
    anchors: list[Anchor] | None = None,
    chunk_seconds: float = 60.0,
) -> list[RawMention]:
    """Pure parse: caption snippets → chunked :class:`RawMention` objects.

    Accepts either the raw-data shape (``list[dict]`` with ``text``,
    ``start``, ``duration`` keys — what ``FetchedTranscript.to_raw_data()``
    returns) or a list of objects with those same attributes (what
    ``FetchedTranscript.snippets`` returns directly). This lets tests
    inject either form.

    Returns an empty list when ``snippets`` is empty.
    """
    if chunk_seconds <= 0:
        raise ValueError("chunk_seconds must be positive")

    normalized = _normalize_snippets(snippets)
    if not normalized:
        logger.info("youtube: no snippets for video %s", video_id)
        return []

    chunks = _chunk_snippets(normalized, chunk_seconds)
    mentions: list[RawMention] = []

    for idx, chunk in enumerate(chunks):
        text = " ".join(s["text"] for s in chunk if s.get("text")).strip()
        if not text:
            continue
        chunk_start = chunk[0]["start"]
        last = chunk[-1]
        chunk_end = float(last["start"]) + float(last.get("duration", 0.0))

        base = _chunk_base(
            video_id=video_id,
            text=text,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
        )

        base_id = youtube_chunk_id(video_id, idx)

        if anchors is None:
            mentions.append(
                RawMention(mention_id=base_id, attribution=None, **base)
            )
            continue

        for match in attribute_regex_all(text, anchors):
            mentions.append(
                RawMention(
                    mention_id=f"{base_id}_{match.anchor_id}",
                    attribution=match,
                    **base,
                )
            )

    return mentions


# ---------------------------------------------------------------------------
# I/O (lazy import)
# ---------------------------------------------------------------------------


def _fetch_snippets(
    video_id: str,
    *,
    languages: tuple[str, ...],
    preserve_formatting: bool,
) -> list[dict[str, Any]]:
    """Call youtube-transcript-api for ``video_id``; return raw-data list.

    Translates library-side exceptions into our conventions:

    - Content-absence errors (``NoTranscriptFound``, ``TranscriptsDisabled``,
      ``VideoUnavailable``, ``VideoUnplayable``, ``AgeRestricted``,
      ``NotTranslatable``, ``TranslationLanguageNotAvailable``,
      ``InvalidVideoId``) → return empty list.
    - Bot-gate errors (``RequestBlocked``, ``IpBlocked``, ``PoTokenRequired``)
      → raise :class:`BlockedError`.
    - Everything else bubbles up (Scheduler handles retry).
    """
    from youtube_transcript_api import (  # noqa: I001  (lazy)
        AgeRestricted,
        InvalidVideoId,
        IpBlocked,
        NoTranscriptFound,
        NotTranslatable,
        PoTokenRequired,
        RequestBlocked,
        TranscriptsDisabled,
        TranslationLanguageNotAvailable,
        VideoUnavailable,
        VideoUnplayable,
        YouTubeTranscriptApi,
    )

    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(
            video_id,
            languages=languages,
            preserve_formatting=preserve_formatting,
        )
    except (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
        VideoUnplayable,
        AgeRestricted,
        InvalidVideoId,
        NotTranslatable,
        TranslationLanguageNotAvailable,
    ) as e:
        logger.info(
            "youtube: no transcript for %s (%s); returning empty",
            video_id,
            type(e).__name__,
        )
        return []
    except (RequestBlocked, IpBlocked, PoTokenRequired) as e:
        raise BlockedError(
            f"youtube: bot-gate on {video_id} ({type(e).__name__})"
        ) from e

    return fetched.to_raw_data()


# ---------------------------------------------------------------------------
# URL / ID extraction (pure)
# ---------------------------------------------------------------------------


def _extract_video_id(url_or_id: str) -> str:
    """Normalize any YouTube reference to the 11-char video ID.

    Accepts:

    - ``https://www.youtube.com/watch?v=<ID>``
    - ``https://youtu.be/<ID>``
    - ``https://www.youtube.com/embed/<ID>``
    - ``https://www.youtube.com/shorts/<ID>``
    - ``https://www.youtube.com/v/<ID>`` (legacy)
    - bare ``<ID>`` (11 chars, ``[A-Za-z0-9_-]``)
    """
    s = (url_or_id or "").strip()
    if not s:
        raise ValueError("youtube: empty URL or video ID")

    # Bare ID.
    if _VIDEO_ID_RE.match(s):
        return s

    if "://" not in s:
        raise ValueError(
            f"youtube: {url_or_id!r} is not a valid URL or 11-char video ID"
        )

    parsed = urlparse(s)
    host = (parsed.hostname or "").lower()
    if host not in _YT_HOSTS:
        raise ValueError(
            f"youtube: URL host {host!r} is not a YouTube domain"
        )

    # youtu.be/<ID>
    if host.endswith("youtu.be"):
        first = parsed.path.strip("/").split("/", 1)[0]
        if _VIDEO_ID_RE.match(first):
            return first
        raise ValueError(f"youtube: youtu.be path {parsed.path!r} has no video ID")

    # youtube.com?v=<ID>
    qs = parse_qs(parsed.query)
    if "v" in qs and qs["v"]:
        candidate = qs["v"][0]
        if _VIDEO_ID_RE.match(candidate):
            return candidate

    # youtube.com/embed/<ID>, /shorts/<ID>, /v/<ID>
    path_parts = parsed.path.strip("/").split("/")
    if len(path_parts) >= 2 and path_parts[0] in {"embed", "shorts", "v"}:
        if _VIDEO_ID_RE.match(path_parts[1]):
            return path_parts[1]

    raise ValueError(
        f"youtube: URL {url_or_id!r} does not carry a recognizable video ID"
    )


# ---------------------------------------------------------------------------
# Chunking helpers (pure)
# ---------------------------------------------------------------------------


def _normalize_snippets(
    snippets: list[dict[str, Any]] | list[Any],
) -> list[dict[str, Any]]:
    """Accept either raw-data dicts or ``FetchedTranscriptSnippet`` objects.

    Returns a list of ``{text, start, duration}`` dicts. Lets callers
    (including tests) pass either shape.
    """
    out: list[dict[str, Any]] = []
    for s in snippets:
        if isinstance(s, dict):
            text = s.get("text") or ""
            start = float(s.get("start") or 0.0)
            duration = float(s.get("duration") or 0.0)
        else:
            text = getattr(s, "text", "") or ""
            start = float(getattr(s, "start", 0.0) or 0.0)
            duration = float(getattr(s, "duration", 0.0) or 0.0)
        text = str(text).strip()
        if not text:
            continue
        out.append({"text": text, "start": start, "duration": duration})
    return out


def _chunk_snippets(
    snippets: list[dict[str, Any]],
    chunk_seconds: float,
) -> list[list[dict[str, Any]]]:
    """Group snippets into bins of ``chunk_seconds`` starting at the first snippet's start.

    A snippet belongs to bin ``k`` when its ``start`` falls in
    ``[k*chunk_seconds, (k+1)*chunk_seconds)`` after subtracting the
    transcript's first start offset (so the first chunk always
    begins at index 0). Bins with no snippets are dropped.
    """
    if not snippets:
        return []
    offset = snippets[0]["start"]
    bins: dict[int, list[dict[str, Any]]] = {}
    for s in snippets:
        k = int((s["start"] - offset) // chunk_seconds)
        bins.setdefault(k, []).append(s)
    return [bins[k] for k in sorted(bins)]


def _chunk_base(
    *,
    video_id: str,
    text: str,
    chunk_start: float,
    chunk_end: float,
) -> dict[str, Any]:
    """Per-chunk fields shared by discovery and anchor modes."""
    start_int = int(chunk_start)
    return {
        "source": SOURCE,
        "source_type": "transcript_chunk",
        # Deep-link into the video at the chunk's start second — YouTube
        # renders `?t=<n>s` as a jump-to-timestamp anchor.
        "source_url": f"https://www.youtube.com/watch?v={video_id}&t={start_int}s",
        "source_title": None,
        "author": None,
        "channel": None,
        "parent_id": video_id,
        "published_at": None,
        "raw_text": text,
        "raw": {
            "video_id": video_id,
            "chunk_start_seconds": float(chunk_start),
            "chunk_end_seconds": float(chunk_end),
        },
    }
