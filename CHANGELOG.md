# Changelog

All notable changes to scrapers-lib are documented here. Follows [Keep a Changelog](https://keepachangelog.com/) conventions.

## [Unreleased]

### Added
- Initial scaffold: folder structure, `pyproject.toml`, `.env.example`, `.gitignore`, `LICENSE`, `CHANGELOG.md`, empty module stubs.
- Draft documentation: PRD, Architecture, Tasks, README.
- `scrapers_lib.core.schemas`: Pydantic v2 models — `Anchor`, `AttributionRegex`, `Attribution`, `ProductSnapshot`, `RawMention`.
- `scrapers_lib.core.attribution`: regex gate, URL-map gate, deterministic mention-ID helpers (Reddit post/comment, RSS article, paragraph, YouTube chunk).
- Top-level re-exports of the core schemas at `scrapers_lib`.
- 55 unit tests covering schema validation and attribution behavior (`tests/core/`).

## Versioning

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §14 for the versioning policy. Pre-1.0 releases may change public APIs between minor versions.
