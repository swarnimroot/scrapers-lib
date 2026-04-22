"""Unit tests for scrapers_lib.core.attribution."""

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.core.attribution import (
    attribute_regex,
    attribute_url,
    paragraph_id,
    reddit_comment_id,
    reddit_post_id,
    rss_article_id,
    youtube_chunk_id,
)


def _anchor(
    anchor_id: str,
    primary: list[str],
    corroboration: list[str] | None = None,
    exclusion: list[str] | None = None,
    source_urls: dict[str, str] | None = None,
) -> Anchor:
    return Anchor(
        anchor_id=anchor_id,
        anchor_type="topic",
        name=anchor_id.replace("_", " ").title(),
        attribution_regex=AttributionRegex(
            primary=primary,
            corroboration=corroboration or [],
            exclusion=exclusion or [],
        ),
        source_urls=source_urls or {},
    )


class TestRegexGate:
    def test_primary_only_match(self):
        a = _anchor("foo", primary=["foo"])
        r = attribute_regex("this text mentions foo directly", [a])
        assert r is not None
        assert r.anchor_id == "foo"
        assert r.method == "regex"
        assert r.confidence == 1.0
        assert "foo" in r.matched_tokens

    def test_primary_no_match(self):
        a = _anchor("foo", primary=["foo"])
        assert attribute_regex("text about something else entirely", [a]) is None

    def test_case_insensitive(self):
        a = _anchor("foo", primary=["Foo"])
        assert attribute_regex("FOO appears here", [a]) is not None

    def test_primary_and_corroboration_both_required(self):
        a = _anchor("foo", primary=["foo"], corroboration=["bar"])
        assert attribute_regex("foo and bar", [a]) is not None
        assert attribute_regex("foo alone", [a]) is None
        assert attribute_regex("only bar here", [a]) is None

    def test_exclusion_drops_otherwise_matched(self):
        a = _anchor("foo", primary=["foo"], exclusion=["not_foo"])
        assert attribute_regex("just foo here", [a]) is not None
        assert attribute_regex("this is not_foo but also foo", [a]) is None

    def test_ambiguous_match_returns_none(self):
        a1 = _anchor("one", primary=["cat"])
        a2 = _anchor("two", primary=["cat"])
        assert attribute_regex("I like cat", [a1, a2]) is None

    def test_empty_text_returns_none(self):
        a = _anchor("foo", primary=["foo"])
        assert attribute_regex("", [a]) is None

    def test_empty_anchors_returns_none(self):
        assert attribute_regex("any text", []) is None

    def test_raw_regex_token(self):
        a = _anchor("foo", primary=["re:foo\\d+"])
        assert attribute_regex("foo42 here", [a]) is not None
        assert attribute_regex("foo but no digits", [a]) is None

    def test_literal_special_chars_auto_escaped(self):
        a = _anchor("cpp", primary=["C++"])
        # Would break without auto-escaping of +
        assert attribute_regex("I use C++ daily", [a]) is not None

    def test_corroboration_matched_tokens_included(self):
        a = _anchor("foo", primary=["foo"], corroboration=["bar"])
        r = attribute_regex("foo and bar", [a])
        assert r is not None
        assert "foo" in r.matched_tokens
        assert "bar" in r.matched_tokens

    def test_only_one_of_two_anchors_matches(self):
        a1 = _anchor("foo", primary=["foo"])
        a2 = _anchor("bar", primary=["bar"])
        r = attribute_regex("this mentions foo only", [a1, a2])
        assert r is not None
        assert r.anchor_id == "foo"


class TestUrlGate:
    def test_exact_url_match(self):
        a = _anchor(
            "foo", primary=["foo"], source_urls={"dell": "https://dell.com/foo"}
        )
        r = attribute_url("https://dell.com/foo", "dell", [a])
        assert r is not None
        assert r.anchor_id == "foo"
        assert r.method == "url_map"
        assert r.confidence == 1.0

    def test_url_mismatch(self):
        a = _anchor(
            "foo", primary=["foo"], source_urls={"dell": "https://dell.com/foo"}
        )
        assert attribute_url("https://dell.com/bar", "dell", [a]) is None

    def test_wrong_source_key(self):
        a = _anchor(
            "foo", primary=["foo"], source_urls={"dell": "https://dell.com/foo"}
        )
        assert attribute_url("https://dell.com/foo", "hp", [a]) is None

    def test_trailing_slash_does_not_match(self):
        """Exact match — consumer is responsible for canonical URLs."""
        a = _anchor(
            "foo", primary=["foo"], source_urls={"dell": "https://dell.com/foo"}
        )
        assert attribute_url("https://dell.com/foo/", "dell", [a]) is None

    def test_ambiguous_url_returns_none(self):
        a1 = _anchor("one", primary=["x"], source_urls={"dell": "https://d.com/s"})
        a2 = _anchor("two", primary=["y"], source_urls={"dell": "https://d.com/s"})
        assert attribute_url("https://d.com/s", "dell", [a1, a2]) is None

    def test_empty_url_returns_none(self):
        a = _anchor("foo", primary=["foo"], source_urls={"dell": "https://d.com/f"})
        assert attribute_url("", "dell", [a]) is None

    def test_empty_anchors_returns_none(self):
        assert attribute_url("https://d.com/f", "dell", []) is None


class TestMentionIds:
    def test_reddit_post(self):
        assert reddit_post_id("abc123") == "reddit_post_abc123"

    def test_reddit_comment(self):
        assert reddit_comment_id("xyz789") == "reddit_comment_xyz789"

    def test_rss_article_id_deterministic(self):
        assert rss_article_id("ign", "https://ign.com/a/1") == rss_article_id(
            "ign", "https://ign.com/a/1"
        )

    def test_rss_article_id_prefix(self):
        i = rss_article_id("ign", "https://ign.com/a/1")
        assert i.startswith("rss_ign_")

    def test_rss_article_id_slugifies_source(self):
        assert rss_article_id("The Verge", "abc").startswith("rss_the_verge_")

    def test_rss_article_id_differs_by_guid(self):
        a = rss_article_id("ign", "guid_a")
        b = rss_article_id("ign", "guid_b")
        assert a != b

    def test_paragraph_id(self):
        assert paragraph_id("dell", "xps_15", 3) == "dell_xps_15_p3"

    def test_youtube_chunk_id(self):
        assert youtube_chunk_id("video123", 5) == "youtube_video123_chunk_5"
