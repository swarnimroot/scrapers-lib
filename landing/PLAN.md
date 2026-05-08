# Landing page plan

A single-page artifact that explains `scrapers-lib` in plain language for a
non-technical reader (portfolio context). One self-contained HTML file at
`landing/index.html` — no build step, no JS framework, opens in any browser,
optionally hostable on GitHub Pages later.

## What this page IS

A portfolio / explainer one-pager. The reader leaves understanding *what was
built*, *how it works at a high level*, *what the output looks like*, and
*who built it*.

## What this page IS NOT (anti-AI-slop checklist)

If the generated design includes any of these, it has failed and must be
rejected before commit:

- Centered hero with massive gradient text + a "Get Started" CTA
- Three-column "features" grid with stock icons (lightbulb / rocket / chart)
- "Trusted by" rows, fake testimonials, vanity metrics
- Sign-up form, newsletter, "Star on GitHub" CTAs styled as primary actions
- Generic Tailwind aesthetics: rounded-2xl, gradient-to-r, blur backdrops, glass-morphism
- Animated particles, parallax scrolling, fade-in-on-scroll, scroll-triggered animations
- Multi-page navigation (this is one page; no nav bar with menu items going nowhere)
- Stock photography, hero illustrations, abstract geometric SVG decorations
- "Built with [Python / Pydantic / Playwright]" tech-badge row
- Lorem ipsum, "compelling" SaaS-style copy, action verbs ("Discover" / "Unlock" / "Empower" / "Streamline")
- Multiple call-to-action buttons; there is nothing to sign up for
- Generic dark-purple-blue gradient backgrounds

## Design direction (positive)

**Aesthetic traits to embody:**

- **Editorial / single long-form article**, not a SaaS landing page. Reads like
  an engineer's confident one-page report, not a startup pitch.
- **Left-aligned and content-first** — never centered hero.
- **Real data, not placeholders** — actual JSON snippets from the library's
  schemas, the actual list of 14 sources, actual numbers (1082 unit tests, 6
  manufacturers, etc.). Nothing inflated, nothing invented.
- **Functional density** — text and data dominate. Whitespace serves rhythm,
  not "breathing room" marketing pretense.
- **Disciplined typographic hierarchy** — at most one proportional typeface
  for prose and one monospace for data/code. No decorative fonts.
- **Minimal color** — near-black on off-white (or inverted). At most one muted
  accent for code blocks or pull-quotes. No gradients. No shadows. No rounded
  corners on everything.
- **No imagery** — typography and code blocks carry the page. If a diagram is
  needed, hand-roll it as text/ASCII or a simple inline SVG, not a stock
  illustration.
- **Honest scale** — every number on the page should be verifiable from the
  repo's actual state.
- **Mobile-responsive** but desktop-first. Reads well at 1200px+; reflows
  cleanly at 400px.

**Reference inspirations** (anchor frontend-design generation against these):

- `ciechanow.ski` (Bartosz Ciechanowski) — explanatory longform, text-first,
  minimal chrome, content-density without decoration.
- Tufte CSS (`edwardtufte.github.io/tufte-css`) — serif typography, sidenotes,
  generous margins for the content type, deliberate hierarchy.
- Stripe documentation pages — typography discipline, asymmetric grid,
  comfortable code-block treatment.
- Older personal engineering blogs that read like one-page reports — Maciej
  Cegłowski's `idlewords.com`, mid-2010s single-page essays.
- A touch of **brutalist editorial** — strong type contrast, asymmetric grid,
  no rounded corners, content-up-front.

**What this rules out:** anything that looks like a 2024-era YC-startup
landing page; anything Vercel/Linear-template-flavored; anything that signals
"AI-generated marketing site."

## Page structure (single scroll, in order)

1. **Title + one-sentence hook + author/year line.**
   Example tone: "scrapers-lib — a Python library that gathers product
   information and customer chatter from across the web." Below it, a small
   line: "By Swarnim · 2025–2026."

2. **What it is** — one short paragraph. Plain English. No marketing.

3. **The three-tier model** — short prose introducing the tiers, followed by
   a small table or grid:
   - **Tier 1:** Places that *want* to be read (RSS feeds, public APIs,
     Reddit's JSON endpoints, YouTube transcripts). Easiest. Examples: RSS,
     Reddit, YouTube, BestBuy Developer API.
   - **Tier 2:** Manufacturer product pages — companies talking about their
     own products. Medium effort; some sites have basic gates worked around
     politely. Examples: Dell, HP, Lenovo, ASUS (ROG + www), Acer, MSI.
   - **Tier 3:** Retailer pages where scrapers aren't welcome — strangers
     talking about products on retailer property. Hardest; most careful tools.
     Examples: Amazon, BestBuy reviews.

4. **What the output looks like** — two real-shape JSON blocks, side-by-side
   or stacked depending on layout. Plain prose explaining each:
   - **Product Snapshot** — a structured fact card from a manufacturer page
     (Dell laptop with specs).
   - **Raw Mention** — a captured comment / review / article excerpt with
     timestamp + source URL + attribution.
   Pull realistic shapes from `scrapers_lib/core/schemas.py` (read it during
   the build to ensure shapes match the real Pydantic models).

5. **By the numbers** — small data block. Honest, no inflation:
   - 6 manufacturers covered (Tier 2)
   - 14 source modules across 3 tiers
   - 1082 unit tests, 0 failing
   - Public API frozen at v1.0 since 2026-04-22
   - Built across ~9 months
   - Latest tag: v1.3.1 (2026-05-07)

6. **Architecture sketch** — one small inline diagram (text/ASCII or simple
   inline SVG, NOT a stock illustration). Shows: tiers → core (schemas,
   scheduler, attribution) → consumer projects. Small, glanceable.

7. **Built by** — Swarnim (designed and directed). Built collaboratively with
   Claude (Anthropic's coding agent). 2-3 sentences. Honest origin story —
   non-technical owner directing AI to write all the code, with explicit
   architectural calls and reviews. No false-modesty, no over-claiming.

8. **Source link** — one line. Stub if private; URL if public.

## Technical scope (hard limits)

- Single `index.html` in `landing/`. Optionally one `style.css` if the inline
  block grows past ~200 lines, but inline is preferred.
- No external CSS framework (no Tailwind, no Bootstrap, no Bulma).
- No JavaScript unless absolutely required for one specific interaction
  (probably none needed).
- At most one Google Font (or system font stack with monospace fallback).
- Self-contained — opens via `file://` in any browser.
- No analytics, no tracking pixels, no third-party embeds.

## Workflow for the build session

1. Resume command auto-loads `MEMORY.md` and re-reads `docs/TASKS.md`
   Current state.
2. Claude reads this `landing/PLAN.md` and `scrapers_lib/core/schemas.py` for
   real output shapes.
3. Claude walks the user through the design direction (references + anti-slop
   list + section order) and confirms before generating.
4. Claude invokes the `frontend-design` skill with this PLAN.md as the brief.
5. User reviews generated output against the anti-slop checklist; iterate on
   any drift.
6. Commit only after explicit greenlight.
