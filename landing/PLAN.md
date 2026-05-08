# Landing page

Single-page portfolio explainer for `scrapers-lib`. Lives at `landing/index.html`. Opens via `file://`. Self-contained — no build step, no external assets, no framework, no web fonts.

Built and declared at rest **2026-05-07**.

> **Document history.** This file was originally a forward-looking spec for the page. The build iterated several rounds; the final aesthetic diverged significantly from the original direction. This file now describes what was *actually* built. A short note on what was dropped from the original spec is preserved at the bottom under [Historical: what the original spec called for](#historical-what-the-original-spec-called-for).

## Current state

- **Path:** `landing/index.html` — single self-contained HTML file
- **CSS:** inline `<style>` block; no external stylesheet
- **JS:** ~30 lines inline, vanilla, only for the contact-form modal (open/close, submit AJAX, validation)
- **Dependencies at runtime:** none (zero web fonts, zero CDN assets, zero framework)
- **External service:** none — the contact form opens a `mailto:` link in the visitor's mail client
- **Hosting:** opens via `file://`; GitHub Pages or similar is an optional next step but not committed

## Aesthetic

**Direction landed:** executive memo / engineering report. No fluff. Real data is the visual hero.

- System serif stack (Iowan Old Style → Charter → Source Serif → Georgia → Cambria) for body and display
- System monospace (SF Mono → Cascadia → Consolas → Menlo) for code and module names
- Cool slate-tinted "scrapers-lib" zone (`#ecedf0`) and warm cream "ways to use it" zone (`#f4f0e0`) — subtle, not loud
- Single muted slate-blue accent (`#1f3a5e`); near-black ink (`#181816`) on near-white parchment (`#fafaf7`)
- Square corners only — `border-radius` is `0` everywhere
- Hairline rules between rows; heavier rules between sections
- Sticky thin top nav (52px) with section anchors and smooth scroll
- Per-section "↑ Top" buttons, subtle hairline-bordered
- Mobile-responsive — desktop-first, reads at 1400px max-width, reflows cleanly to 400px

## Page structure — 6 sections

1. **Masthead** — project name (`scrapers-lib`, monospaced), one-line hook with **2 weeks** underlined, byline (`By Swarnim Bagre`) and version (`May 2026 · v1.3.1`) right-aligned.

2. **Overview** — two paragraphs of plain-English description on the left + two stat accordions on the right. Each accordion is a `<details>` element with a smooth height transition (CSS `grid-template-rows: 0fr → 1fr` trick). The `+` toggle rotates 135° to `×` when expanded:
   - `14 source modules` → reveals full per-tier module list
   - `6 manufacturer brands` → reveals brand list

3. **Architecture** — single outer frame with two flex zones (subtle color tinting differentiates them) and a thin bridge between:
   - **Left zone (cool slate tint):** `scrapers-lib`
     - Three tier cards stacked (Tier I / II / III) — each shows the module names in monospace
     - A column of three `→` flow arrows
     - Core card on the right — lists `schemas / scheduler / normalizers / attribution / dispatch` with one-line descriptions
   - **Bridge:** a single `→`, no border lines
   - **Right zone (warm cream tint):** `ways to use it`
     - Three use-case cards stacked, written for a cold visitor (no project codenames):
       - Product sentiment tracking
       - Competitor spec aggregation
       - Trend & chatter monitoring
   - Outer flex layout (`flex: 3 1 540px` for lib zone, `flex: 0 0 64px` for bridge, `flex: 1 1 280px` for use zone) chosen after a grid-based attempt mis-sized the columns.

4. **Challenges Faced** — `<table>` with grouped rows by status, `rowspan="2"` on the SOLVED group's status cell. Visible status order: **By design → Solved (×2) → Working around → Blocked**. Color darkness hierarchy:
   - **By design** — darkest (`#181816`); engineer's intentional choice carries the most weight
   - **Solved** — slightly less dark (`#2c2a25`)
   - **Working around** — medium (`#4a4844`)
   - **Blocked** — lightest, italicized, hollow square indicator (`#898680`); out of the engineer's control
   Each row has: status pill, challenge headline (h3), how-handled cell, what-would-unlock-a-proper-fix cell. Mobile collapses each row into a stacked block with column labels injected via CSS `attr(data-label)`.

5. **Output Shape** — two real JSON specimens, vertically stacked, using verbatim Pydantic v2 field signatures pulled from `scrapers_lib/core/schemas.py`:
   - `ProductSnapshot` — 21 fields, sample is a Dell XPS 15 9530 listing
   - `RawMention` — 14 fields, sample is a Reddit r/laptops post about that XPS 15
   Realistic sample values throughout (no `"string"` placeholders); subtle accent-tinted syntax highlighting in inline `<span>` classes.

6. **Contact** — three-column footer (Built / Method / Source):
   - **Built** — `2 weeks · 21 Apr → 7 May 2026`, then `using dev system and Claude Code`
   - **Method** — single sentence: human-led architectural calls, product framing, and design direction; Claude served as collaborative ideator and executor for coding and writing
   - **Source** — `Available on request` + clickable envelope icon → opens a native `<dialog>` modal with a 3-field form (name, email, reason — reason has 50-char minimum). Submit assembles a `mailto:` URL with the fields prefilled and opens the visitor's mail client; the form is replaced with a confirmation panel that shows the recipient address as a visible fallback.

## Numbers displayed — all verifiable from current repo state

- **14** source modules — Tier 1: 5 (`rss`, `article`, `reddit`, `youtube`, `bestbuy_api`); Tier 2: 7 (`acer`, `asus_rog`, `asus_www`, `dell`, `hp`, `lenovo`, `msi`); Tier 3: 2 (`amazon`, `bestbuy`)
- **6** manufacturer brands — Acer, ASUS, Dell, HP, Lenovo, MSI
- **2 weeks / 16 days** — built 21 April → 7 May 2026
- **v1.3.1** — current library version (declared resting cut)
- **v1.0 frozen 2026-04-22** — public API stability boundary

## Contact form delivery

The form does not POST anywhere. On submit, JS reads the three field values, assembles a `mailto:` URL with `subject` and `body` parameters URL-encoded, and sets `window.location.href` to open the visitor's default mail client with the request prefilled.

The recipient email is assembled at runtime from string parts in JS (raw address is not present literally in static HTML, to deter naive scraping). After triggering the mail client, the form is replaced with a confirmation panel that displays the recipient address visibly as a fallback in case the visitor's browser has no `mailto:` handler configured.

**Why mailto: over a third-party form service:** an earlier iteration used FormSubmit.co's AJAX endpoint, but the activation email never arrived at the recipient's `@dell.com` inbox (corporate filters appear to block FormSubmit). `mailto:` removes the third-party dependency entirely and is reliable for any visitor with a mail client. The known UX cost — visitors using webmail without a configured handler see nothing happen — is acceptable for a low-traffic portfolio page; the fallback line in the confirmation panel covers that case.

## Anti-AI-slop checklist (still binding for any future revision)

The original anti-slop list survived every pivot and remains the binding reference for any future change to this page:

- No centered hero with massive gradient text + a "Get Started" CTA
- No three-column "features" grid with stock icons (lightbulb / rocket / chart)
- No "Trusted by" rows, fake testimonials, vanity metrics
- No sign-up form, newsletter, or "Star on GitHub" CTA styled as a primary action
- No generic Tailwind aesthetics: `rounded-2xl`, `gradient-to-r`, blur backdrops, glass-morphism
- No animated particles, parallax scrolling, fade-in-on-scroll, scroll-triggered animations
- No multi-page navigation (this is a single page)
- No stock photography, hero illustrations, abstract decorative SVG
- No "Built with [Python / Pydantic / Playwright]" tech-badge row
- No lorem ipsum, "compelling" SaaS-style copy, marketing verbs (Discover / Unlock / Empower / Streamline)
- No multiple CTA buttons; there is nothing to sign up for
- No generic dark-purple-blue gradient backgrounds

## Hard technical limits (still binding)

- Single `index.html`. Inline `<style>`. No external stylesheet.
- No CSS framework (no Tailwind, Bootstrap, Bulma, etc.)
- No web fonts. System stacks only.
- JavaScript is allowed only for the contact-form modal (open/close, AJAX submit, basic validation). Roughly 30 lines, vanilla, inline `<script>`.
- No analytics, no tracking pixels, no third-party embeds, no external API endpoints.
- Mobile-responsive — desktop-first, reads at 1400px down to 400px.

## Workflow if revisiting

If a future revision is needed:

1. Re-read this file in full.
2. Re-read the [anti-AI-slop checklist](#anti-ai-slop-checklist-still-binding) and confirm any change does not introduce a banned pattern.
3. Verify any displayed number against repo state before changing copy.
4. Verify Pydantic field signatures in `scrapers_lib/core/schemas.py` haven't changed before editing the JSON specimens.
5. Test: open `landing/index.html` in a browser and check at 1400px desktop, 940px breakpoint, 720px breakpoint, 400px mobile.

---

## Historical: what the original spec called for

The original spec proposed a **longform-editorial** aesthetic anchored to:

- **Bartosz Ciechanowski** (`ciechanow.ski`) — explanatory longform, text-first
- **Tufte CSS** (`edwardtufte.github.io/tufte-css`) — serif typography, sidenotes
- **Maciej Cegłowski** (`idlewords.com`) — mid-2010s personal-essay flavor
- **Stripe documentation pages** — typography discipline, asymmetric grid
- A touch of **brutalist editorial** — strong type contrast, asymmetric grid

The user reviewed the proposed direction and rejected it as scroll-death-prone for a portfolio context. Subsequent iterations:

- **Iteration 1 → dashboard / infographic density** — modular Pudding.cool / Cloudflare-recap aesthetic with big-numeral hero. Built. Reviewed. Felt too marketing-toned.
- **Iteration 2 → executive memo** — current direction. No fluff. Structured, scannable, real data does the work. This is what shipped.

References that **survived** all pivots: Stripe documentation pages (typography discipline + asymmetric grid).

References that were **dropped**: Ciechanowski, Tufte CSS, Cegłowski / idlewords, Pudding.cool, Cloudflare-recap, big-numeral display.

The full text of the original spec is available in git history if needed: `git log -p -- landing/PLAN.md`.
