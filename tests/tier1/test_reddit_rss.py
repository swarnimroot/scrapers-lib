"""Unit tests for scrapers_lib.tier1.reddit's ``.rss`` (Atom) path.

Reddit 403-blocks the JSON API for our IP; the live fetchers parse the public
``.rss`` Atom feeds instead (:func:`parse_reddit_rss_listing` /
:func:`parse_reddit_rss_comments`). These tests feed small inline Atom
documents (the shape Reddit actually emits) through the pure parsers and assert
the structured :class:`RawMention` output: post/comment typing, the canonical
``reddit_post_id`` / ``reddit_comment_id`` mention-id scheme (so rows dedup
against any JSON-fetched corpus), ``parent_id`` threading for downstream
comment-inheritance, ``/u/`` author stripping, HTML-body stripping, and
deleted/empty skipping.
"""

from __future__ import annotations

from datetime import datetime, timezone

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier1.reddit import (
    _rss_author,
    _strip_html_to_text,
    parse_reddit_rss_comments,
    parse_reddit_rss_listing,
)


def _alienware() -> Anchor:
    return Anchor(
        anchor_id="alienware",
        anchor_type="company",
        name="Alienware",
        attribution_regex=AttributionRegex(primary=["Alienware"]),
    )


_LISTING_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>t3_aaa111</id>
    <link href="https://www.reddit.com/r/GamingLaptops/comments/aaa111/slug/"/>
    <title>Alienware 16 thermals after a month</title>
    <author><name>/u/reviewer</name></author>
    <published>2026-05-01T12:00:00+00:00</published>
    <content type="html">&lt;div class="md"&gt;&lt;p&gt;My Alienware runs hot under load but stays quiet.&lt;/p&gt;&lt;/div&gt;</content>
  </entry>
  <entry>
    <id>t3_bbb222</id>
    <link href="https://www.reddit.com/r/GamingLaptops/comments/bbb222/slug/"/>
    <title>Need a cheap office laptop</title>
    <author><name>/u/shopper</name></author>
    <published>2026-05-02T08:30:00+00:00</published>
    <content type="html">&lt;div class="md"&gt;&lt;p&gt;Something for spreadsheets only.&lt;/p&gt;&lt;/div&gt;</content>
  </entry>
</feed>
"""

_COMMENTS_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>t3_aaa111</id>
    <link href="https://www.reddit.com/r/GamingLaptops/comments/aaa111/slug/"/>
    <title>Alienware 16 thermals after a month</title>
    <author><name>/u/reviewer</name></author>
    <published>2026-05-01T12:00:00+00:00</published>
    <content type="html">&lt;div class="md"&gt;&lt;p&gt;My Alienware runs hot under load.&lt;/p&gt;&lt;/div&gt;</content>
  </entry>
  <entry>
    <id>t1_ccc333</id>
    <link href="https://www.reddit.com/r/GamingLaptops/comments/aaa111/slug/ccc333/"/>
    <author><name>/u/helper</name></author>
    <published>2026-05-01T13:00:00+00:00</published>
    <content type="html">&lt;div class="md"&gt;&lt;p&gt;The Alienware fan curve is aggressive.&lt;/p&gt;&lt;/div&gt;</content>
  </entry>
  <entry>
    <id>t1_ddd444</id>
    <link href="https://www.reddit.com/r/GamingLaptops/comments/aaa111/slug/ddd444/"/>
    <author><name>/u/empty</name></author>
    <published>2026-05-01T14:00:00+00:00</published>
    <content type="html">&lt;div class="md"&gt;&lt;p&gt;[removed]&lt;/p&gt;&lt;/div&gt;</content>
  </entry>
</feed>
"""


# ---------------------------------------------------------------------------
# Listing parser
# ---------------------------------------------------------------------------


def test_listing_discovery_mode_emits_one_post_per_entry() -> None:
    mentions = parse_reddit_rss_listing(
        _LISTING_ATOM, subreddit="GamingLaptops", anchors=None
    )
    assert len(mentions) == 2
    first = mentions[0]
    assert first.source_type == "post"
    assert first.mention_id == "reddit_post_aaa111"
    assert first.channel == "r/GamingLaptops"
    assert first.author == "reviewer"  # /u/ stripped
    assert first.published_at == datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    # title + body composed, HTML stripped.
    assert "thermals" in first.raw_text
    assert "runs hot under load" in first.raw_text
    assert "<p>" not in first.raw_text


def test_listing_anchored_mode_only_emits_matches() -> None:
    mentions = parse_reddit_rss_listing(
        _LISTING_ATOM, subreddit="GamingLaptops", anchors=[_alienware()]
    )
    # Only the Alienware post matches; the office-laptop post is dropped.
    assert len(mentions) == 1
    m = mentions[0]
    assert m.mention_id == "reddit_post_aaa111_alienware"
    assert m.attribution is not None
    assert m.attribution.anchor_id == "alienware"


# ---------------------------------------------------------------------------
# Comments parser
# ---------------------------------------------------------------------------


def test_comments_emits_post_plus_comments_and_skips_removed() -> None:
    mentions = parse_reddit_rss_comments(
        _COMMENTS_ATOM,
        subreddit="GamingLaptops",
        post_fullname="t3_aaa111",
        anchors=None,
    )
    posts = [m for m in mentions if m.source_type == "post"]
    comments = [m for m in mentions if m.source_type == "comment"]
    assert len(posts) == 1
    # ddd444 is [removed] → skipped; only ccc333 survives.
    assert len(comments) == 1
    c = comments[0]
    assert c.mention_id == "reddit_comment_ccc333"
    assert c.parent_id == "t3_aaa111"  # threading for comment-inheritance
    assert c.channel == "r/GamingLaptops"
    assert c.author == "helper"
    assert "fan curve is aggressive" in c.raw_text


def test_comments_emit_all_comments_bypasses_anchor_match() -> None:
    # With anchors set + emit_all_comments, the comment emits unattributed so
    # the caller can inherit attribution from the parent post downstream.
    mentions = parse_reddit_rss_comments(
        _COMMENTS_ATOM,
        subreddit="GamingLaptops",
        post_fullname="t3_aaa111",
        anchors=[_alienware()],
        emit_all_comments=True,
    )
    comments = [m for m in mentions if m.source_type == "comment"]
    assert len(comments) == 1
    assert comments[0].attribution is None
    assert comments[0].mention_id == "reddit_comment_ccc333"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_strip_html_to_text_collapses_and_unescapes() -> None:
    raw = '<!-- SC_OFF --><div class="md"><p>Runs&nbsp;hot &amp; loud</p></div>'
    assert _strip_html_to_text(raw) == "Runs hot & loud"
    assert _strip_html_to_text("") == ""


def test_rss_author_strips_prefix_and_handles_deleted() -> None:
    assert _rss_author({"author": "/u/someone"}) == "someone"
    assert _rss_author({"author": "u/someone"}) == "someone"
    assert _rss_author({"author": "[deleted]"}) is None
    assert _rss_author({}) is None
