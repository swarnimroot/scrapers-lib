# scrapers-lib — Product Requirements Document

**Status:** stable &nbsp;·&nbsp; **Last updated:** 2026-05-07 &nbsp;·&nbsp; **Library version:** 1.3.1

---

## 1. What scrapers-lib is

scrapers-lib is a reusable Python library that turns heterogeneous web data — community posts, product pages, news articles, review sites, video transcripts — into **normalized, schema-validated data** that any downstream Python project can consume and analyze.

It is infrastructure, not an application. It does not know or care what a consumer is tracking. It knows how to fetch from a growing set of sources and how to shape the result into three consistent types.

## 2. The problem it solves

A single Python project that needs data from five sources typically ends up with five one-off scrapers, five ad-hoc rate-limit strategies, five different output shapes, and one maintenance headache the first time a site redesigns. Every subsequent project repeats the mistake.

scrapers-lib centralizes the boring, fragile, hard-to-get-right parts — fetching, retrying, stealth, rate limiting, caching, normalization, attribution, scheduling — so that projects can focus on **what they want to know**, not **how to get the data**.

## 3. Users

Any Python project that needs multi-source web data with normalized output and reasonable reliability. This includes, but is not limited to:

- Product / competitive intelligence projects tracking specific SKUs across manufacturers and retailers.
- Sentiment and trend projects tracking mentions of specific topics, companies, or titles across news and community sources.
- Research projects building corpora of community commentary on specific subjects.

The library is designed so none of these use cases leak into its code. New consumers compose new behaviors from existing primitives.

## 4. Success criteria

**v1.0.0 shipped on 2026-04-22 with the following guarantees, all met:**

- Three schemas (Anchor, ProductSnapshot, RawMention) stable and documented; backward-compatible changes only within the 1.x line.
- Working fetchers across all three tiers: six Tier 1 (rss, article, reddit, reddit_comments, youtube, bestbuy_api), six Tier 2 (dell, hp, lenovo, asus, acer, msi), three Tier 3 (amazon, amazon_reviews, bestbuy_reviews). API-based, feed-based, and scraping-based sources all represented. (Tier 2 expanded post-v1.0 in Waves 2e + 2f, and the shared `warmed_curl_session()` helper graduated in Wave 2g, all without changing existing signatures.)
- A queue-based Scheduler that can run unattended for days on a single laptop without losing state.
- Reasonable success rates per source, documented honestly in ARCHITECTURE.md §11 (coverage, fields populated, and known limitations called out per source — no marketing claims about reliability).
- Consumers pin a library version and depend on its public API behavior within the 1.x line.

v0.x was the pre-release path (buildable and usable, but public APIs could change between minor versions); that phase closed at v1.0.0.

## 5. Non-goals

scrapers-lib **does not**:

- Store long-term data. Consumers persist results wherever they want (SQLite, DuckDB, JSON, Postgres — library doesn't care).
- Make LLM calls. LLM-based classification, synthesis, or summarization lives entirely in consumer projects.
- Own a UI. Dashboards, reports, and visualizations are consumer concerns.
- Normalize spec vocabulary across sources. "Memory" vs "RAM" vs "System Memory" stays as the source exposes it; alignment is a consumer or future-helper concern.
- Decide what to fetch. Consumers define Anchors, Sources, and schedules; the library executes.
- Depend on paid scraping infrastructure. Free tiers only: residential IP, stealth Playwright (where required), `curl_cffi` browser impersonation with warmed sessions for Akamai-gated hosts, and patient pacing.

## 6. Constraints

- **Free tiers only.** No paid proxies, scraping services, or premium API access.
- **Residential IP.** All scraping runs from a single home laptop; no proxy rotation.
- **Python 3.12.**
- **Local-only development.** Git is local; no remote by default. Library is not published to PyPI — consumers install via `pip install -e` from a local checkout.
- **Windows-first.** Primary development and deployment platform is Windows; Linux/macOS should work but aren't actively tested.
- **Patient scraping posture.** Real-time data is not a goal. The Scheduler runs 24x7 at slow pacing; data arriving hours or a day later is acceptable. This buys reliability by trading latency.

## 7. Scope and boundaries

**In scope:** fetchers for each supported source, normalization into the three schemas, attribution primitives (regex and URL-map gates), caching, rate limiting, retry/backoff, robots.txt awareness, stealth Playwright and `curl_cffi` browser impersonation (with warmed sessions) for bot-gated hosts, a persistent Scheduler with per-domain budgets, integration tests as site-drift canaries, versioning discipline.

**Out of scope:** everything listed under §5 (non-goals), plus any source that requires paid access to work reliably. If a source is too fragile or too ToS-hostile to serve well on free tiers, the library says so and skips it rather than pretending.

## 8. Versioning and API stability

- Semantic versioning (`0.x.y` → `1.0.0` → `1.x.y`).
- **As of v1.0.0:** schemas and public fetcher signatures are frozen. Backward-incompatible changes require a major bump. The freeze has held through v1.3.1 — Waves 2d, 2e, 2f, and 2g added kwargs, new fetchers, and one internal-helper refactor (BestBuy reviews pagination, HP `async_techspecs`, ASUS `www` host, Acer, MSI, `warmed_curl_session()` graduation) without breaking any existing signature.
- Documented deprecation path: any removed public API goes through a deprecation warning in one minor version before removal.
- Historical: before v1.0.0 public APIs could change between minor versions; consumers pinned exact versions during the 0.x line.
