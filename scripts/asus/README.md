# scripts/asus/

ASUS ROG reconnaissance scripts. Single-purpose here — the pattern emerged
quickly after a negative result on `shop.asus.com` and a direct hit on the
`rog.asus.com/laptops/<line>/<model>/spec/` marketing/spec surface.

1. **Fixture-refresh tooling.** Re-run when ASUS redesigns the ROG spec
   pages and the committed fixtures need updating.
2. **A worked example of Tier 2 reconnaissance when the e-commerce
   surface is professionally gated and the marketing surface is open.**
   See [`docs/ADDING_A_SOURCE.md`](../../docs/ADDING_A_SOURCE.md) for the
   methodology; ASUS is the case study for the "shop is DataDome-gated
   → pivot to the manufacturer's spec-reference surface" decision.

## The script

| Script | What it does | Network |
|---|---|---|
| `probe_asus_rog.py` | First hits `shop.asus.com` to reconfirm the DataDome negative result (`captcha-delivery.com` script + 403). Then fetches both committed ROG fixtures (Strix G16 2025 + Zephyrus G16 2026) and prints the `<h2>` spec-section header outline for each — quick verification that the pattern the `tier2/asus.py` fetcher depends on still holds. | yes |

## Running

From the repo root:

```bash
.venv/Scripts/python.exe scripts/asus/probe_asus_rog.py
```

The script assumes the package is installed editable (`pip install -e .`)
so `from scrapers_lib...` resolves.

## Output locations

Fixtures land in `tests/tier2/fixtures/asus/`:

- `rog_strix_g16_2025_spec.html` — primary gaming fixture (Intel variant,
  RTX 50-series).
- `rog_zephyrus_g16_2026_spec.html` — generality fixture (different ROG
  subline, different year).

Fixtures deliberately chosen from different product lines to exercise
per-line category variation — for example, Strix exposes an "AURA SYNC"
category that Zephyrus does not. The parser must walk `<h2>`s by position,
never hard-code category names.

## Why there's no `tier2/base` lift

Four Tier 2 sources in (Dell, Lenovo, HP, ASUS), still zero shared helpers:

- **Dell** — HTML fragments from an Akamai-protected API endpoint via
  `page.context.request.get()`.
- **Lenovo** — nested JSON API responses, no anti-bot.
- **HP** — JSON-encoded HTML comment in a hidden div, no anti-bot for
  httpx but browsers are rejected.
- **ASUS** — SSR'd `<h2>`-headed DOM sections, no anti-bot on the
  marketing surface (but DataDome on the shop surface).

Four bespoke stories. Per `docs/ADDING_A_SOURCE.md` §2, a repeating shape
across **two or more** sites must be observed before anything lifts into
`tier2/base.py`. None so far.

## The DataDome fork

`shop.asus.com` uses DataDome — a professional anti-bot service returning
a ~768-byte 403 with a captcha-delivery.com JS challenge script. This is
the same surface-protection tier Amazon uses. Under the project's
"free tiers only" constraint (no paid proxies / bypass services), this
surface is off-limits.

The ROG marketing spec page carries no prices but otherwise delivers a
richer spec sheet than `shop.asus.com` would — the manufacturer
authoritative spec is on `rog.asus.com`, the shop surface just repackages
it with prices bolted on. For Demo 2's max-spec comparison use case, no
prices is acceptable (Lenovo PSREF has the same limitation and was
accepted precedent).
