"""Lenovo PSREF reconnaissance — probe 3: PDF datasheet coverage.

Probe 2 (``probe_psref_xhr.py``) discovered that PSREF's ``ShowSpecPage``
endpoint returns page chrome with an empty iframe and a link to a PDF
datasheet at ``/syspool/Sys/PDF/<Line>/<Model>/<Model>_Spec.pdf``. This
probe fetches that PDF and extracts its text so we can answer one
concrete question: does the PDF carry the **full** spec sheet (every
category — processor, memory, display, ports, wireless, battery,
dimensions, weight, keyboard, camera, audio, chassis, etc.) or just a
subset?

Status of the ``pdfplumber`` dependency: installed into ``.venv/`` for
this one probe. **Not** yet added to ``pyproject.toml`` — the decision
to adopt a PDF-parsing dep is pending and depends on whether this probe
shows full coverage.

Output (under ``tests/tier2/fixtures/lenovo/``):

- ``legion_pro_7_16afr10h_spec.pdf`` — raw PDF bytes.
- ``legion_pro_7_16afr10h_spec.txt`` — extracted plain text.

Stdout reports: HTTP metadata, page count, extracted-text size,
first N non-blank lines (preview), spec-category keyword occurrences,
and a list of heading-like lines (short, no colon) to give a sense
of how the data is structured.

Run from the repo root::

    .venv/Scripts/python.exe scripts/lenovo/probe_psref_pdf.py

See ``docs/ADDING_A_SOURCE.md`` §4.1 (PDF datasheet row) — PDF is flagged
as last-resort; this probe is what decides whether Lenovo should escalate
to that row.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx
import pdfplumber

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier2" / "fixtures" / "lenovo"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

# Template derived from ShowSpecPage.json page chrome. Backslashes in the
# PSREF-rendered href are a Windows-path artefact; a real browser URL-encodes
# them or normalizes to forward slashes. We try forward slashes first.
PDF_URL_TEMPLATE = (
    "https://psref.lenovo.com/syspool/Sys/PDF/{line}/{model}/{model}_Spec.pdf"
)
LINE = "Legion"
MODEL = "Legion_Pro_7_16AFR10H"
LABEL = "legion_pro_7_16afr10h"

SPEC_CATEGORIES = [
    "Processor", "CPU", "Graphics", "GPU", "Chipset", "Memory", "RAM",
    "Storage", "SSD", "HDD", "Display", "Camera", "Webcam", "Audio",
    "Microphone", "Speakers", "Keyboard", "Touchpad", "Fingerprint",
    "Battery", "AC Adapter", "Power", "Wireless", "Bluetooth", "WLAN",
    "Ethernet", "Ports", "Slots", "Card Reader", "Dimensions", "Weight",
    "Chassis", "Color", "Case Material", "OS", "Operating System",
    "Certifications", "Security", "Pen", "TPM", "Software",
]


def fetch_pdf(url: str) -> httpx.Response:
    print(f"[GET] {url}")
    resp = httpx.get(
        url,
        headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=60.0,
    )
    print(f"status: {resp.status_code}")
    print(f"final URL: {resp.url}")
    print(f"content-type: {resp.headers.get('content-type', '(unset)')}")
    print(f"length: {len(resp.content):,} bytes")
    return resp


def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    url = PDF_URL_TEMPLATE.format(line=LINE, model=MODEL)
    try:
        resp = fetch_pdf(url)
    except httpx.HTTPError as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 2

    if resp.status_code != 200:
        print("Non-200 — aborting.")
        (FIX / f"{LABEL}_spec_status{resp.status_code}.bin").write_bytes(resp.content[:4000])
        return 1

    if not resp.content.startswith(b"%PDF"):
        print("Body is not a PDF (no '%PDF' magic). Saving head for post-mortem.")
        (FIX / f"{LABEL}_spec.notpdf").write_bytes(resp.content[:4000])
        return 1

    pdf_path = FIX / f"{LABEL}_spec.pdf"
    pdf_path.write_bytes(resp.content)
    print(f"saved PDF: {pdf_path.relative_to(REPO)}")

    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        print(f"\npdf pages: {page_count}")
        for page in pdf.pages:
            txt = page.extract_text() or ""
            parts.append(txt)

    full_text = "\n\n".join(parts)
    txt_path = FIX / f"{LABEL}_spec.txt"
    txt_path.write_text(full_text, encoding="utf-8")
    print(f"extracted text: {txt_path.relative_to(REPO)} ({len(full_text):,} chars)")

    lines = [ln.rstrip() for ln in full_text.splitlines() if ln.strip()]
    print(f"\nnon-blank lines: {len(lines)}")

    print("\n--- first 40 non-blank lines ---")
    for ln in lines[:40]:
        print(f"  {ln}")

    print("\n--- spec-category keyword occurrences (word-boundary, case-insensitive) ---")
    hits: dict[str, int] = {}
    for cat in SPEC_CATEGORIES:
        pat = re.compile(r"\b" + re.escape(cat) + r"\b", re.I)
        n = len(pat.findall(full_text))
        if n > 0:
            hits[cat] = n
    for cat in sorted(hits, key=lambda k: (-hits[k], k)):
        print(f"  {cat:25s}  {hits[cat]}")
    missed = [c for c in SPEC_CATEGORIES if c not in hits]
    if missed:
        print(f"  (0 occurrences: {', '.join(missed)})")

    heading_like = [
        ln for ln in lines
        if 3 <= len(ln) <= 45
        and ":" not in ln
        and re.search(r"^[A-Za-z]", ln)
    ]
    print(f"\n--- heading-like lines (short, no colon): {len(heading_like)} total, showing 40 ---")
    for ln in heading_like[:40]:
        print(f"  {ln}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
