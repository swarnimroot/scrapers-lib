"""Unit tests for scrapers_lib.tier1.reddit (unauthenticated JSON endpoints).

Three fixtures:

- ``subreddit_games_new.json`` — real 25-post r/Games listing captured
  via the unauthenticated JSON endpoint. Exercises post shape, author
  extraction, dual-mode attribution on real Microsoft / Halo posts.
- ``post_comments.json`` — real [post, comments] bundle for one r/Games
  post. Small (1 comment, no nesting), exercises the post+comments
  order invariant.
- ``nested_comments.json`` — hand-crafted with nested replies (depth
  0 / 1 / 2), a ``kind="more"`` stub (unfollowed; counted), a deleted
  comment (skipped), and anchor-matchable body text. Exercises the
  tree-walk, deletion skipping, and more-stub counting.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scrapers_lib.core.registry import get_fetcher
from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier1 import reddit
from scrapers_lib.tier1.reddit import (
    SOURCE,
    SOURCE_COMMENTS,
    _count_more_stubs,
    _extract_post_location,
    _extract_subreddit_name,
    parse_reddit_comments,
    parse_reddit_listing,
)


FIX = Path(__file__).parent / "fixtures" / "reddit"


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _microsoft() -> Anchor:
    return Anchor(
        anchor_id="microsoft",
        anchor_type="company",
        name="Microsoft",
        attribution_regex=AttributionRegex(primary=["Microsoft"]),
    )


def _halo() -> Anchor:
    return Anchor(
        anchor_id="halo",
        anchor_type="game",
        name="Halo",
        attribution_regex=AttributionRegex(primary=["Halo"]),
    )


def _sony() -> Anchor:
    return Anchor(
        anchor_id="sony",
        anchor_type="company",
        name="Sony",
        attribution_regex=AttributionRegex(primary=["Sony"]),
    )


def _alan_wake_2() -> Anchor:
    return Anchor(
        anchor_id="alan_wake_2",
        anchor_type="game",
        name="Alan Wake 2",
        attribution_regex=AttributionRegex(primary=["Alan Wake 2", "AW2"]),
    )


# ---------------------------------------------------------------------------
# Listing parser — r/Games live fixture
# ---------------------------------------------------------------------------


class TestParseListingDiscovery:
    @pytest.fixture
    def mentions(self):
        return parse_reddit_listing(_load("subreddit_games_new.json"), subreddit="Games")

    def test_mention_count_matches_fixture_children(self, mentions):
        # Fixture has 25 posts; all have titles so none should be skipped.
        assert len(mentions) == 25

    def test_all_are_posts(self, mentions):
        for m in mentions:
            assert m.source_type == "post"

    def test_all_have_source_reddit(self, mentions):
        for m in mentions:
            assert m.source == "reddit"

    def test_all_have_attribution_none_in_discovery(self, mentions):
        for m in mentions:
            assert m.attribution is None

    def test_channel_formatted_with_r_prefix(self, mentions):
        for m in mentions:
            assert m.channel == "r/Games"

    def test_mention_ids_use_reddit_post_id_helper(self, mentions):
        for m in mentions:
            assert m.mention_id.startswith("reddit_post_")

    def test_mention_ids_unique(self, mentions):
        ids = [m.mention_id for m in mentions]
        assert len(ids) == len(set(ids))

    def test_source_url_absolute(self, mentions):
        for m in mentions:
            assert m.source_url.startswith("https://www.reddit.com")

    def test_first_post_fields_populated(self, mentions):
        first = mentions[0]
        assert first.source_title
        assert first.author == "TODG3"
        assert first.published_at is not None
        assert first.published_at.tzinfo == timezone.utc

    def test_raw_stores_reddit_score(self, mentions):
        # Real fixture, exact score is whatever was live — just check present.
        for m in mentions:
            assert "score" in m.raw
            assert "num_comments" in m.raw


class TestParseListingAnchorMode:
    @pytest.fixture
    def mentions(self):
        # Combine Microsoft + Halo anchors; the "Halo exec / Microsoft legend"
        # post should match both and fan out to two mentions.
        return parse_reddit_listing(
            _load("subreddit_games_new.json"),
            subreddit="Games",
            anchors=[_microsoft(), _halo()],
        )

    def test_multi_anchor_fans_out(self, mentions):
        # At least one post should match both anchors -> >= 2 mentions total.
        assert len(mentions) >= 2
        ids = {m.attribution.anchor_id for m in mentions}
        assert "microsoft" in ids
        assert "halo" in ids

    def test_anchor_mode_mention_id_suffixes_anchor(self, mentions):
        for m in mentions:
            assert m.mention_id.endswith(f"_{m.attribution.anchor_id}")

    def test_non_matching_posts_dropped(self, mentions):
        # 25 posts in fixture, most won't match Microsoft/Halo — result
        # should be far fewer than 25.
        assert len(mentions) < 25


# ---------------------------------------------------------------------------
# Comments parser — real fixture
# ---------------------------------------------------------------------------


class TestParseRealComments:
    @pytest.fixture
    def mentions(self):
        return parse_reddit_comments(_load("post_comments.json"), subreddit="Games")

    def test_post_emitted_first(self, mentions):
        assert mentions[0].source_type == "post"

    def test_comment_parent_id_is_post_fullname(self, mentions):
        # Fixture has 1 comment with parent_id=link_id=t3_1ssqc6y.
        comments = [m for m in mentions if m.source_type == "comment"]
        assert comments
        assert all(c.parent_id == "t3_1ssqc6y" for c in comments)

    def test_post_plus_comment_mentions(self, mentions):
        # 1 post + at least 1 comment = at least 2 mentions.
        types = [m.source_type for m in mentions]
        assert types[0] == "post"
        assert "comment" in types


# ---------------------------------------------------------------------------
# Comments parser — nested + deleted + more-stubs fixture
# ---------------------------------------------------------------------------


class TestParseNestedComments:
    @pytest.fixture
    def mentions(self):
        return parse_reddit_comments(_load("nested_comments.json"), subreddit="TestSub")

    def test_pre_order_traversal(self, mentions):
        # Expect: post, c001, c002 (reply to c001), c003 (reply to c002),
        # c011 (second top-level). c010 deleted -> skipped. c004-c007 are
        # more-stubs -> not emitted.
        ids = [m.raw.get("post_id") or m.raw.get("comment_id") for m in mentions]
        assert ids == ["pxxxxx", "c001", "c002", "c003", "c011"]

    def test_deleted_comment_skipped(self, mentions):
        for m in mentions:
            assert m.raw.get("comment_id") != "c010"

    def test_more_stub_count_on_post_raw(self, mentions):
        # fixture declares a "more" stub with children=[c004..c007] => count 4
        post_mention = mentions[0]
        assert post_mention.raw["more_count"] == 4

    def test_depth_preserved_on_nested_comments(self, mentions):
        depths = {
            m.raw["comment_id"]: m.raw["depth"]
            for m in mentions
            if m.source_type == "comment"
        }
        assert depths == {"c001": 0, "c002": 1, "c003": 2, "c011": 0}

    def test_parent_id_chain(self, mentions):
        # RawMention.parent_id is always the link_id (post fullname) for
        # every comment — they all hang off the same post.
        for m in mentions:
            if m.source_type == "comment":
                assert m.parent_id == "t3_pxxxxx"
        # raw.parent_id preserves the comment's OWN parent (post or parent comment).
        raw_parents = {
            m.raw["comment_id"]: m.raw["parent_id"]
            for m in mentions
            if m.source_type == "comment"
        }
        assert raw_parents == {
            "c001": "t3_pxxxxx",
            "c002": "t1_c001",
            "c003": "t1_c002",
            "c011": "t3_pxxxxx",
        }

    def test_author_none_when_deleted(self):
        # Include the deleted comment in a direct test to verify author handling.
        body = _load("nested_comments.json")
        # c010 had author="[deleted]" and body="[removed]" -> whole comment skipped.
        mentions = parse_reddit_comments(body, subreddit="TestSub")
        assert not any(m.author == "[deleted]" for m in mentions)


class TestNestedAnchorMode:
    def test_multi_comment_matches_fan_out_correctly(self):
        mentions = parse_reddit_comments(
            _load("nested_comments.json"),
            subreddit="TestSub",
            anchors=[_alan_wake_2(), _microsoft(), _sony()],
        )
        # Post body: "Alan Wake 2 explicitly" -> matches AW2 anchor
        # c001: mentions Microsoft -> microsoft anchor
        # c002: mentions Microsoft AND Sony -> both anchors
        # c003: no anchor hits -> dropped
        # c011: no anchor hits -> dropped
        anchor_hits = [(m.source_type, m.attribution.anchor_id) for m in mentions]
        assert ("post", "alan_wake_2") in anchor_hits
        assert ("comment", "microsoft") in anchor_hits
        assert ("comment", "sony") in anchor_hits
        # c002 has both -> verify fan-out
        c002_hits = {
            m.attribution.anchor_id
            for m in mentions
            if m.raw.get("comment_id") == "c002"
        }
        assert c002_hits == {"microsoft", "sony"}


# ---------------------------------------------------------------------------
# URL / shorthand parsers
# ---------------------------------------------------------------------------


class TestExtractSubredditName:
    @pytest.mark.parametrize(
        "inp,expected",
        [
            ("Games", "Games"),
            ("r/Games", "Games"),
            ("R/Games", "Games"),
            ("r/Games/", "Games"),
            ("https://www.reddit.com/r/Games", "Games"),
            ("https://www.reddit.com/r/Games/", "Games"),
            ("https://reddit.com/r/Games/new", "Games"),
            ("https://old.reddit.com/r/Games/", "Games"),
        ],
    )
    def test_forms(self, inp, expected):
        assert _extract_subreddit_name(inp) == expected

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _extract_subreddit_name("")

    def test_non_reddit_host_raises(self):
        with pytest.raises(ValueError, match="not a Reddit"):
            _extract_subreddit_name("https://example.com/r/Games")


class TestExtractPostLocation:
    @pytest.mark.parametrize(
        "inp,sub,pid",
        [
            ("t3_abc123", None, "abc123"),
            ("abc123", None, "abc123"),
            (
                "https://www.reddit.com/r/Games/comments/abc123/title_slug/",
                "Games",
                "abc123",
            ),
            ("https://reddit.com/r/Games/comments/abc123/", "Games", "abc123"),
            ("https://www.reddit.com/comments/abc123", None, "abc123"),
        ],
    )
    def test_forms(self, inp, sub, pid):
        assert _extract_post_location(inp) == (sub, pid)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _extract_post_location("")

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            _extract_post_location("not-a-reference with spaces")


# ---------------------------------------------------------------------------
# sort / time_filter validation
# ---------------------------------------------------------------------------


class TestSortValidation:
    def test_bad_sort_raises(self):
        with pytest.raises(ValueError, match="sort="):
            reddit.fetch_reddit_listing("Games", sort="best")

    def test_bad_time_filter_only_when_sort_is_top(self):
        with pytest.raises(ValueError, match="time_filter="):
            reddit.fetch_reddit_listing("Games", sort="top", time_filter="decade")

    def test_time_filter_ignored_when_sort_is_not_top(self):
        # Should not raise just because time_filter is weird when sort="new".
        # We can't actually call this without hitting the network; prove it
        # by invoking the validation logic path-through (patch _fetch_json).
        import types

        called = {}

        def fake_fetch(url, *, params, timeout, user_agent):
            called["params"] = params
            return {"kind": "Listing", "data": {"children": []}}

        orig = reddit._fetch_json
        reddit._fetch_json = fake_fetch
        try:
            out = reddit.fetch_reddit_listing(
                "Games", sort="new", time_filter="decade", limit=5
            )
            assert out == []
            # Confirm the invalid time_filter was not propagated.
            assert "t" not in called["params"]
        finally:
            reddit._fetch_json = orig


# ---------------------------------------------------------------------------
# more-stub counter helper
# ---------------------------------------------------------------------------


class TestCountMoreStubs:
    def test_counts_nested_more_children(self):
        body = _load("nested_comments.json")
        assert _count_more_stubs(body[1]) == 4

    def test_no_more_returns_zero(self):
        body = _load("post_comments.json")
        # Real fixture has no "more" stubs.
        assert _count_more_stubs(body[1]) == 0

    def test_non_dict_input_is_zero(self):
        assert _count_more_stubs("") == 0
        assert _count_more_stubs(None) == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_listing_with_empty_children(self):
        out = parse_reddit_listing(
            {"data": {"children": []}}, subreddit="Empty"
        )
        assert out == []

    def test_listing_with_non_t3_child_skipped(self):
        out = parse_reddit_listing(
            {
                "data": {
                    "children": [
                        {
                            "kind": "more",
                            "data": {"id": "xxx"},
                        }
                    ]
                }
            },
            subreddit="Weird",
        )
        assert out == []

    def test_comments_with_shape_that_is_not_list(self):
        # Malformed/unexpected — parser should log + return [] not crash.
        out = parse_reddit_comments({"oops": "not a list"}, subreddit="x")
        assert out == []

    def test_comments_with_list_shorter_than_two(self):
        out = parse_reddit_comments([{"data": {"children": []}}], subreddit="x")
        assert out == []


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_listing_registered(self):
        assert get_fetcher(SOURCE) is reddit.fetch_reddit_listing

    def test_comments_registered(self):
        assert get_fetcher(SOURCE_COMMENTS) is reddit.fetch_reddit_comments

    def test_source_constants(self):
        assert SOURCE == "reddit"
        assert SOURCE_COMMENTS == "reddit_comments"
