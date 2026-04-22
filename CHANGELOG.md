# Changelog

All notable changes to scrapers-lib are documented here. Follows [Keep a Changelog](https://keepachangelog.com/) conventions.

## [Unreleased]

## [0.1.0] — 2026-04-21

### Added
- Initial scaffold: folder structure, `pyproject.toml`, `.env.example`, `.gitignore`, `LICENSE`, `CHANGELOG.md`, empty module stubs.
- Draft documentation: PRD, Architecture, Tasks, README.
- `scrapers_lib.core.schemas`: Pydantic v2 models — `Anchor`, `AttributionRegex`, `Attribution`, `ProductSnapshot`, `RawMention`.
- `scrapers_lib.core.attribution`: regex gate, URL-map gate, deterministic mention-ID helpers (Reddit post/comment, RSS article, paragraph, YouTube chunk).
- `scrapers_lib.core.logging_config`: opt-in `configure_logging()` helper with per-module level overrides.
- `scrapers_lib.core.registry`: internal fetcher registry with function and decorator (`@register`) forms.
- `scrapers_lib.core.rate_limiter`: per-domain token-bucket `RateLimiter` with pure-logic `Bucket` sub-class.
- `scrapers_lib.core.cache`: `Cache` — diskcache-backed wrapper with per-source TTL defaults from ARCHITECTURE §7.
- `scrapers_lib.core.robots`: `RobotsChecker` — robots.txt-aware URL checker with per-origin caching; injectable `fetch_fn` for testing.
- `scrapers_lib.core.http_client`: `HttpClient` — httpx wrapper with retry/backoff on 429/503/network errors, UA rotation, `Retry-After` respect.
- `scrapers_lib.core.playwright_base`: `BrowserProfile` and `stealth_context` (lazy Playwright import) for per-domain persistent Chromium profiles.
- `scrapers_lib.core.scheduler`: `Scheduler` — SQLite-backed persistent job queue with worker loop, per-job retry, per-domain adaptive backoff, `BlockedError` for explicit 429/403 signals, optional RateLimiter + RobotsChecker integration, callback result delivery, `stats()`, `stop()`.
- Top-level re-exports at `scrapers_lib`: `Anchor`, `Attribution`, `AttributionRegex`, `BlockedError`, `ProductSnapshot`, `RawMention`, `Scheduler`.
- 165 unit tests across `tests/core/` — schemas (28), attribution (27), logging (7), registry (11), rate limiter (15), cache (17), robots (11), http_client (13), playwright_base (15), scheduler (22).

## Versioning

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §14 for the versioning policy. Pre-1.0 releases may change public APIs between minor versions.
