"""Unit tests for scrapers_lib.tier1.rss.

Tests run against three synthetic fixtures:
- ``rss20_sample.xml`` — canonical RSS 2.0 shape, 4 entries, diverse
  anchor-matching potential (Alan Wake 2 with corroboration, Microsoft
  Activision for multi-anchor fan-out, cooking article for no-match).
- ``atom_sample.xml`` — canonical Atom shape, 2 entries.
- ``minimal_rss20.xml`` — edge cases (missing author / published /
  guid / link).

Synthetic because real feed content changes hourly; fixtures need to
be stable for deterministic tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scrapers_lib.core.registry import get_fetcher
from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier1 import rss
from scrapers_lib.tier1.rss import (
    SOURCE,
    _compose_entry_text,
    _derive_slug,
    parse_rss_feed,
)


FIX = Path(__file__).parent / "fixtures" / "rss"
FEED_URL = "https://example-news.test/feed"


def _load(name: str) -> bytes:
    return (FIX / name).read_bytes()


def _aw2_anchor() -> Anchor:
    return Anchor(
        anchor_id="alan_wake_2",
        anchor_type="game",
        name="Alan Wake 2",
        attribution_regex=AttributionRegex(
            primary=["Alan Wake 2", "AW2"],
            corroboration=["Remedy", "Sam Lake"],
        ),
    )


def _microsoft_anchor() -> Anchor:
    return Anchor(
        anchor_id="microsoft",
        anchor_type="company",
        name="Microsoft",
        attribution_regex=AttributionRegex(
            primary=["Microsoft"],
            exclusion=["Microsoft Word", "Microsoft Office"],
        ),
    )


def _activision_anchor() -> Anchor:
    return Anchor(
        anchor_id="activision",
        anchor_type="company",
        name="Activision",
        attribution_regex=AttributionRegex(primary=["Activision"]),
    )


# ---------------------------------------------------------------------------
# Discovery mode — anchors=None
# ---------------------------------------------------------------------------


class TestDiscoveryModeRss20:
    @pytest.fixture
    def mentions(self):
        body = _load("rss20_sample.xml")
        return parse_rss_feed(body, FEED_URL, source_slug="testnews")

    def test_one_mention_per_entry(self, mentions):
        assert len(mentions) == 4

    def test_all_have_attribution_none_in_discovery_mode(self, mentions):
        for m in mentions:
            assert m.attribution is None

    def test_source_is_the_slug(self, mentions):
        for m in mentions:
            assert m.source == "testnews"

    def test_source_type_is_article(self, mentions):
        for m in mentions:
            assert m.source_type == "article"

    def test_channel_is_feed_title(self, mentions):
        for m in mentions:
            assert m.channel == "Test Gaming News"

    def test_first_entry_fields_populated(self, mentions):
        first = mentions[0]
        assert first.source_title == "Alan Wake 2 expansion launch date revealed"
        assert first.source_url == (
            "https://example-news.test/articles/alan-wake-2-expansion"
        )
        assert first.author == "Jane Reporter"
        assert first.published_at == datetime(
            2026, 4, 22, 9, 15, 0, tzinfo=timezone.utc
        )
        assert "Alan Wake 2" in first.raw_text
        # HTML tags should have been stripped out.
        assert "<b>" not in first.raw_text
        assert "</b>" not in first.raw_text

    def test_mention_id_is_deterministic_per_slug_and_guid(self, mentions):
        # Re-parsing the same body must give the same IDs.
        body = _load("rss20_sample.xml")
        again = parse_rss_feed(body, FEED_URL, source_slug="testnews")
        assert [m.mention_id for m in mentions] == [m.mention_id for m in again]

    def test_mention_ids_are_unique(self, mentions):
        ids = [m.mention_id for m in mentions]
        assert len(ids) == len(set(ids))

    def test_cooking_entry_is_retained_in_discovery_mode(self, mentions):
        # Discovery mode does no filtering — the non-gaming "cooking" article
        # is emitted too. This is the contract consumers rely on.
        titles = [m.source_title for m in mentions]
        assert "Best cooking gadgets of 2026" in titles

    def test_raw_preserves_entry_guid(self, mentions):
        assert mentions[0].raw["entry_guid"] == "test-aw2-expansion-001"


# ---------------------------------------------------------------------------
# Anchor-driven mode
# ---------------------------------------------------------------------------


class TestAnchorModeRss20:
    @pytest.fixture
    def mentions(self):
        body = _load("rss20_sample.xml")
        return parse_rss_feed(
            body,
            FEED_URL,
            anchors=[_aw2_anchor(), _microsoft_anchor(), _activision_anchor()],
            source_slug="testnews",
        )

    def test_cooking_entry_dropped_no_match(self, mentions):
        titles = [m.source_title for m in mentions]
        assert "Best cooking gadgets of 2026" not in titles

    def test_multi_anchor_entry_fans_out(self, mentions):
        # Microsoft + Activision acquisition entry should produce 2 mentions.
        ms_acti = [
            m
            for m in mentions
            if "Microsoft closes" in (m.source_title or "")
        ]
        assert len(ms_acti) == 2
        anchor_ids = {m.attribution.anchor_id for m in ms_acti}
        assert anchor_ids == {"microsoft", "activision"}

    def test_multi_anchor_mentions_have_distinct_ids(self, mentions):
        ids = [m.mention_id for m in mentions]
        assert len(ids) == len(set(ids))

    def test_mention_id_suffixes_anchor_id_in_anchor_mode(self, mentions):
        for m in mentions:
            assert m.mention_id.endswith(f"_{m.attribution.anchor_id}")

    def test_all_have_regex_attribution(self, mentions):
        for m in mentions:
            assert m.attribution is not None
            assert m.attribution.method == "regex"

    def test_alan_wake_2_corroboration_required(self, mentions):
        # AW2 anchor has corroboration=["Remedy", "Sam Lake"]; the entry must
        # match primary AND at least one corroboration. Both fixture entries
        # that mention AW2 also mention Remedy — they should hit.
        aw2 = [m for m in mentions if m.attribution.anchor_id == "alan_wake_2"]
        assert len(aw2) == 2

    def test_matched_tokens_populated(self, mentions):
        # Every mention should list at least one matched token.
        for m in mentions:
            assert m.attribution.matched_tokens

    def test_drop_articles_matching_zero_anchors(self, mentions):
        # Cooking gadgets matches none of our 3 anchors -> dropped.
        # Total mentions: 1 (AW2 expansion) + 2 (MS+Acti) + 1 (AW2 preview) = 4.
        assert len(mentions) == 4


class TestCorroborationGate:
    def test_primary_without_corroboration_dropped(self):
        # Craft a fixture whose entry has AW2 but no Remedy/Sam Lake.
        body = (
            b'<?xml version="1.0"?><rss version="2.0"><channel>'
            b"<title>t</title><link>https://x.test/</link><description>d</description>"
            b"<item><title>AW2 patch notes revealed</title>"
            b"<link>https://x.test/1</link>"
            b"<description>Details on the latest AW2 patch, version 1.2.3.</description>"
            b"<guid>x-1</guid></item>"
            b"</channel></rss>"
        )
        out = parse_rss_feed(
            body, "https://x.test/feed", anchors=[_aw2_anchor()], source_slug="x"
        )
        assert out == []

    def test_primary_with_corroboration_matches(self):
        body = (
            b'<?xml version="1.0"?><rss version="2.0"><channel>'
            b"<title>t</title><link>https://x.test/</link><description>d</description>"
            b"<item><title>AW2 details from Remedy</title>"
            b"<link>https://x.test/2</link>"
            b"<description>Remedy Entertainment shared AW2 patch information.</description>"
            b"<guid>x-2</guid></item>"
            b"</channel></rss>"
        )
        out = parse_rss_feed(
            body, "https://x.test/feed", anchors=[_aw2_anchor()], source_slug="x"
        )
        assert len(out) == 1
        assert out[0].attribution.anchor_id == "alan_wake_2"


class TestExclusionGate:
    def test_exclusion_token_drops_anchor(self):
        # Microsoft anchor has exclusion=["Microsoft Word"]; an article about
        # Microsoft Word should NOT match the microsoft anchor.
        body = (
            b'<?xml version="1.0"?><rss version="2.0"><channel>'
            b"<title>t</title><link>https://x.test/</link><description>d</description>"
            b"<item><title>Microsoft Word gets new feature</title>"
            b"<link>https://x.test/w1</link>"
            b"<description>Microsoft Word now has ...</description>"
            b"<guid>w-1</guid></item>"
            b"</channel></rss>"
        )
        out = parse_rss_feed(
            body,
            "https://x.test/feed",
            anchors=[_microsoft_anchor()],
            source_slug="x",
        )
        assert out == []


# ---------------------------------------------------------------------------
# Atom shape
# ---------------------------------------------------------------------------


class TestAtom:
    @pytest.fixture
    def mentions(self):
        body = _load("atom_sample.xml")
        return parse_rss_feed(body, "https://atom-test.example/feed", source_slug="atom_test")

    def test_atom_entries_parsed(self, mentions):
        assert len(mentions) == 2

    def test_atom_channel_title(self, mentions):
        assert mentions[0].channel == "Test Atom Gaming"

    def test_atom_content_used_in_raw_text(self, mentions):
        # The first Atom entry has both summary and content — the fetcher
        # composes both into raw_text (content's longer prose should be in).
        first = mentions[0]
        assert "Helsinki" in first.raw_text

    def test_atom_published_parsed(self, mentions):
        # First entry has <published>2026-04-22T09:15:00Z</published>.
        assert mentions[0].published_at == datetime(
            2026, 4, 22, 9, 15, 0, tzinfo=timezone.utc
        )


# ---------------------------------------------------------------------------
# Minimal / edge-case fixture
# ---------------------------------------------------------------------------


class TestMinimalFeed:
    @pytest.fixture
    def mentions(self):
        body = _load("minimal_rss20.xml")
        return parse_rss_feed(body, "https://minimal.test/feed", source_slug="minimal")

    def test_entry_with_only_title_still_emitted(self, mentions):
        titles = [m.source_title for m in mentions]
        assert "Entry with only a title" in titles

    def test_author_is_none_when_absent(self, mentions):
        for m in mentions:
            if m.source_title == "Entry with only a title":
                assert m.author is None

    def test_published_is_none_when_absent(self, mentions):
        for m in mentions:
            assert m.published_at is None

    def test_entry_without_guid_or_link_uses_title_fallback(self, mentions):
        # Second entry has only a title — falls back to title-based guid.
        second = [
            m
            for m in mentions
            if m.source_title == "Entry without guid or link but with title"
        ]
        assert len(second) == 1


# ---------------------------------------------------------------------------
# source_slug / URL-derived slug
# ---------------------------------------------------------------------------


class TestSourceSlug:
    def test_explicit_slug_used(self):
        body = _load("rss20_sample.xml")
        out = parse_rss_feed(body, FEED_URL, source_slug="custom_name")
        for m in out:
            assert m.source == "custom_name"

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://feeds.ign.com/ign/games-all", "ign"),
            ("https://www.polygon.com/feed/", "polygon"),
            ("https://kotaku.com/rss", "kotaku"),
            ("https://www.rockpapershotgun.com/feed", "rockpapershotgun"),
        ],
    )
    def test_slug_derivation(self, url, expected):
        assert _derive_slug(url) == expected

    def test_slug_fallback_on_unparseable(self):
        assert _derive_slug("not a url at all") == "rss"

    def test_slug_derived_when_not_passed(self):
        body = _load("rss20_sample.xml")
        out = parse_rss_feed(body, "https://polygon.com/feed")
        assert out
        assert out[0].source == "polygon"


# ---------------------------------------------------------------------------
# compose_entry_text helper
# ---------------------------------------------------------------------------


class TestComposeEntryText:
    def test_strips_html_tags(self):
        entry = {
            "title": "Hello",
            "summary": "This is <b>bold</b> and <i>italic</i>.",
        }
        text = _compose_entry_text(entry)
        assert "<b>" not in text
        assert "bold" in text

    def test_empty_entry_returns_empty_string(self):
        assert _compose_entry_text({}) == ""

    def test_atom_content_included_when_present(self):
        entry = {
            "title": "T",
            "summary": "summary here",
            "content": [{"type": "html", "value": "<p>body text</p>"}],
        }
        text = _compose_entry_text(entry)
        assert "summary here" in text
        assert "body text" in text


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registered_under_rss(self):
        assert get_fetcher(SOURCE) is rss.fetch_rss_feed

    def test_source_constant(self):
        assert SOURCE == "rss"
