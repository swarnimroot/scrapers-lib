"""Unit tests for scrapers_lib.tier1.article.

Tests run against three fixtures:
- ``ign_mario_galaxy.html`` — real IGN article, 194 KB, Next.js shell
  with clean JSON-LD + article body. Used for happy-path + dual-mode
  verification on a real-world layout.
- ``polygon_ecco_dolphin.html`` — real Polygon article, 230 KB, Vox
  Media CMS. §5.7 generality check — different layout, same
  trafilatura ``Document`` shape.
- ``empty_paywall.html`` — synthetic minimal fixture for the
  partial-failure path (trafilatura returns ``None`` / body below
  ``min_length``, fetcher returns empty list rather than raising).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from scrapers_lib.core.registry import get_fetcher
from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier1 import article
from scrapers_lib.tier1.article import (
    SOURCE,
    _derive_slug,
    _homepage_for,
    _parse_date,
    parse_article,
)


FIX = Path(__file__).parent / "fixtures" / "article"

IGN_URL = (
    "https://www.ign.com/articles/"
    "mario-galaxy-movie-backstory-now-video-game-canon-miyamoto-suggests"
)
POLYGON_URL = "https://www.polygon.com/ecco-the-dolphin-collection-new-game/"
PAYWALL_URL = "https://paywall.example/article"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _nintendo() -> Anchor:
    return Anchor(
        anchor_id="nintendo",
        anchor_type="company",
        name="Nintendo",
        attribution_regex=AttributionRegex(primary=["Nintendo"]),
    )


def _sega() -> Anchor:
    return Anchor(
        anchor_id="sega",
        anchor_type="company",
        name="Sega",
        attribution_regex=AttributionRegex(primary=["Sega"]),
    )


# ---------------------------------------------------------------------------
# Discovery mode — IGN fixture
# ---------------------------------------------------------------------------


class TestParseIgnArticleDiscovery:
    @pytest.fixture
    def mention(self):
        html = _load("ign_mario_galaxy.html")
        mentions = parse_article(html, IGN_URL, source_slug="ign")
        assert len(mentions) == 1
        return mentions[0]

    def test_source_from_slug(self, mention):
        assert mention.source == "ign"

    def test_source_type_is_article(self, mention):
        assert mention.source_type == "article"

    def test_attribution_is_none_in_discovery(self, mention):
        assert mention.attribution is None

    def test_mention_id_format(self, mention):
        assert mention.mention_id.startswith("article_ign_")

    def test_mention_id_deterministic_on_refetch(self):
        html = _load("ign_mario_galaxy.html")
        one = parse_article(html, IGN_URL, source_slug="ign")[0]
        two = parse_article(html, IGN_URL, source_slug="ign")[0]
        assert one.mention_id == two.mention_id

    def test_title_populated(self, mention):
        assert mention.source_title is not None
        assert "Mario Galaxy" in mention.source_title

    def test_author_populated(self, mention):
        assert mention.author == "Tom Phillips"

    def test_published_at_parsed_to_utc(self, mention):
        assert mention.published_at == datetime(
            2026, 4, 22, 0, 0, 0, tzinfo=timezone.utc
        )

    def test_channel_prefers_sitename(self, mention):
        # trafilatura extracts sitename="IGN" (nicer than hostname="ign.com").
        assert mention.channel == "IGN"

    def test_body_length_reasonable(self, mention):
        # The Mario Galaxy article body was ~2665 chars at capture time;
        # tolerate some drift if the fixture is refreshed.
        assert len(mention.raw_text) >= 1000

    def test_source_url_echoes_input(self, mention):
        assert mention.source_url == IGN_URL

    def test_raw_stores_extraction_metadata(self, mention):
        assert mention.raw["extractor"] == "trafilatura"
        assert mention.raw["hostname"] == "ign.com"
        assert mention.raw["sitename"] == "IGN"
        assert mention.raw["image"]  # featured-image URL


# ---------------------------------------------------------------------------
# Generality check — Polygon fixture (different CMS)
# ---------------------------------------------------------------------------


class TestParsePolygonArticleDiscovery:
    @pytest.fixture
    def mention(self):
        html = _load("polygon_ecco_dolphin.html")
        return parse_article(html, POLYGON_URL, source_slug="polygon")[0]

    def test_source_from_slug(self, mention):
        assert mention.source == "polygon"

    def test_channel_from_sitename(self, mention):
        # Polygon's sitename is "Polygon.com" (with the .com suffix — not
        # ideal but what trafilatura returns; we echo it verbatim).
        assert mention.channel == "Polygon.com"

    def test_author_populated(self, mention):
        assert mention.author == "Michael McWhertor"

    def test_body_contains_ecco(self, mention):
        assert "Ecco" in mention.raw_text

    def test_published_at_parsed(self, mention):
        assert mention.published_at is not None
        assert mention.published_at.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# Anchor-driven mode — cross-article anchor isolation
# ---------------------------------------------------------------------------


class TestAnchorMode:
    def test_ign_article_matches_nintendo_not_sega(self):
        # Mario Galaxy / Miyamoto article: should hit Nintendo, miss Sega.
        html = _load("ign_mario_galaxy.html")
        mentions = parse_article(
            html, IGN_URL, anchors=[_nintendo(), _sega()], source_slug="ign"
        )
        assert len(mentions) == 1
        assert mentions[0].attribution.anchor_id == "nintendo"

    def test_polygon_article_matches_sega_not_nintendo(self):
        # Ecco the Dolphin / Sega article: should hit Sega, miss Nintendo.
        html = _load("polygon_ecco_dolphin.html")
        mentions = parse_article(
            html,
            POLYGON_URL,
            anchors=[_nintendo(), _sega()],
            source_slug="polygon",
        )
        assert len(mentions) == 1
        assert mentions[0].attribution.anchor_id == "sega"

    def test_no_anchor_match_returns_empty(self):
        html = _load("ign_mario_galaxy.html")
        irrelevant = Anchor(
            anchor_id="cooking",
            anchor_type="topic",
            name="Cooking",
            attribution_regex=AttributionRegex(primary=["kitchen gadgets"]),
        )
        mentions = parse_article(
            html, IGN_URL, anchors=[irrelevant], source_slug="ign"
        )
        assert mentions == []

    def test_multi_anchor_fan_out_via_synthetic_text(self):
        # Build a synthetic HTML guaranteed to hit both Nintendo and Sega
        # so we verify the one-article -> N-mention fan-out end-to-end.
        body_para = (
            "Nintendo and Sega, once bitter rivals in the 16-bit console era, "
            "both appeared at a recent gaming conference. Representatives from "
            "Nintendo discussed upcoming Switch titles while Sega teased a new "
            "Sonic game. Nintendo legend Shigeru Miyamoto attended. Sega's "
            "Haruki Satomi also spoke. The joint panel covered the history of "
            "gaming, from the Sega Genesis to the Nintendo Entertainment System, "
            "touching on the competitive landscape and the industry's current "
            "direction. Both companies continue to release major titles each year."
        )
        html = (
            "<!DOCTYPE html><html><head>"
            "<title>Nintendo and Sega Reunion</title></head>"
            "<body><article><h1>Nintendo and Sega Reunion</h1>"
            f"<p>{body_para}</p></article></body></html>"
        )
        url = "https://synthetic.example/nintendo-sega-reunion"
        mentions = parse_article(
            html, url, anchors=[_nintendo(), _sega()], source_slug="synthetic"
        )
        assert len(mentions) == 2
        ids = {m.attribution.anchor_id for m in mentions}
        assert ids == {"nintendo", "sega"}

    def test_anchor_mode_mention_id_suffixes_anchor(self):
        html = _load("ign_mario_galaxy.html")
        mentions = parse_article(
            html, IGN_URL, anchors=[_nintendo()], source_slug="ign"
        )
        assert mentions[0].mention_id.endswith("_nintendo")


# ---------------------------------------------------------------------------
# Partial-failure path — empty / paywall / short body
# ---------------------------------------------------------------------------


class TestPartialFailure:
    def test_paywall_fixture_returns_empty_list(self):
        html = _load("empty_paywall.html")
        mentions = parse_article(html, PAYWALL_URL, source_slug="paywall")
        assert mentions == []

    def test_min_length_gates_short_body(self):
        # Use a real article body but crank min_length up past its size.
        html = _load("ign_mario_galaxy.html")
        mentions = parse_article(
            html, IGN_URL, source_slug="ign", min_length=1_000_000
        )
        assert mentions == []

    def test_anchor_mode_no_match_returns_empty(self):
        html = _load("empty_paywall.html")
        mentions = parse_article(
            html,
            PAYWALL_URL,
            anchors=[_nintendo()],
            source_slug="paywall",
        )
        assert mentions == []


# ---------------------------------------------------------------------------
# source_slug derivation
# ---------------------------------------------------------------------------


class TestDeriveSlug:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.ign.com/articles/foo", "ign"),
            ("https://ign.com/articles/foo", "ign"),
            ("https://www.polygon.com/", "polygon"),
            ("https://www.rockpapershotgun.com/feed/bar", "rockpapershotgun"),
            ("https://venturebeat.com/games/foo", "venturebeat"),
        ],
    )
    def test_hostname_based_slug(self, url, expected):
        assert _derive_slug(url) == expected

    def test_empty_url_falls_back_to_source(self):
        assert _derive_slug("") == SOURCE

    def test_explicit_slug_used_over_derivation(self):
        html = _load("ign_mario_galaxy.html")
        mention = parse_article(html, IGN_URL, source_slug="custom_slug")[0]
        assert mention.source == "custom_slug"

    def test_derived_slug_when_not_passed(self):
        html = _load("ign_mario_galaxy.html")
        mention = parse_article(html, IGN_URL)[0]
        assert mention.source == "ign"


# ---------------------------------------------------------------------------
# Date parser
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_iso_date_string(self):
        assert _parse_date("2026-04-22") == datetime(
            2026, 4, 22, 0, 0, 0, tzinfo=timezone.utc
        )

    def test_empty_returns_none(self):
        assert _parse_date("") is None
        assert _parse_date(None) is None

    def test_malformed_returns_none(self):
        assert _parse_date("22 April 2026") is None
        assert _parse_date("not a date") is None


# ---------------------------------------------------------------------------
# Homepage derivation (for warm-up GET)
# ---------------------------------------------------------------------------


class TestHomepageFor:
    def test_strips_path(self):
        assert (
            _homepage_for("https://www.notebookcheck.net/Foo.123.0.html")
            == "https://www.notebookcheck.net/"
        )

    def test_strips_query_and_fragment(self):
        assert (
            _homepage_for("https://example.com/article?x=y#frag")
            == "https://example.com/"
        )

    def test_preserves_scheme(self):
        assert _homepage_for("http://example.com/article") == "http://example.com/"

    def test_fallback_on_invalid_url(self):
        # No scheme or netloc → echo input rather than synthesizing a bogus host.
        assert _homepage_for("not-a-url") == "not-a-url"


# ---------------------------------------------------------------------------
# _fetch_html — warmed curl_cffi session + httpx.HTTPStatusError adapter
# ---------------------------------------------------------------------------


def _build_fake_curl_cffi_module(
    *,
    target_status: int = 200,
    target_text: str = "<html><body><p>x</p></body></html>",
):
    """Fake curl_cffi module for ``_fetch_html`` tests.

    First ``Session.get`` is the warm-up — always 200, empty body. The
    second ``Session.get`` is the target article fetch — returns the
    configured ``(target_status, target_text)``.

    Returns ``(fake_module, calls_recorder)``.
    """
    calls = MagicMock()

    class _FakeResp:
        def __init__(self, text: str, status: int) -> None:
            self.text = text
            self.status_code = status

    class _FakeSession:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self._call_count = 0

        def __enter__(self) -> "_FakeSession":
            return self

        def __exit__(self, *exc: Any) -> None:
            return None

        def get(self, url: str, **kwargs: Any) -> _FakeResp:
            calls(url=url, session_kwargs=self.kwargs, **kwargs)
            self._call_count += 1
            if self._call_count == 1:
                return _FakeResp("", 200)
            return _FakeResp(target_text, target_status)

    fake_requests = SimpleNamespace(Session=_FakeSession)
    fake_module = SimpleNamespace(
        requests=fake_requests,
        CurlHttpVersion=SimpleNamespace(V1_1="V1_1_SENTINEL"),
    )
    return fake_module, calls


def _patch_curl_cffi(fake_module: Any):
    return patch.dict(
        "sys.modules",
        {
            "curl_cffi": fake_module,
            "curl_cffi.requests": fake_module.requests,
        },
    )


class TestFetchHtmlOverWarmedSession:
    """``_fetch_html`` uses ``warmed_curl_session()`` (Chrome impersonation
    + HTTP/1.1 + per-host warm-up) and wraps non-2xx responses as
    ``httpx.HTTPStatusError`` to preserve the documented exception
    contract.
    """

    def test_warm_up_targets_scheme_plus_host(self):
        fake_module, calls = _build_fake_curl_cffi_module()
        with _patch_curl_cffi(fake_module), patch(
            "scrapers_lib.core.curl_session.time.sleep"
        ):
            article._fetch_html(
                "https://www.notebookcheck.net/Some-Article.123.0.html",
                timeout=30.0,
            )
        urls = [c.kwargs["url"] for c in calls.call_args_list]
        assert urls == [
            "https://www.notebookcheck.net/",
            "https://www.notebookcheck.net/Some-Article.123.0.html",
        ]

    def test_target_request_sends_default_headers(self):
        fake_module, calls = _build_fake_curl_cffi_module()
        with _patch_curl_cffi(fake_module), patch(
            "scrapers_lib.core.curl_session.time.sleep"
        ):
            article._fetch_html(
                "https://example.com/article", timeout=30.0
            )
        target_call = calls.call_args_list[1]
        headers = target_call.kwargs["headers"]
        assert "User-Agent" in headers
        assert headers["Accept-Language"] == "en-US,en;q=0.9"
        assert headers["Accept"].startswith("text/html")

    def test_html_body_returned_on_success(self):
        fake_module, _calls = _build_fake_curl_cffi_module(
            target_text="<html><body><p>actual body</p></body></html>"
        )
        with _patch_curl_cffi(fake_module), patch(
            "scrapers_lib.core.curl_session.time.sleep"
        ):
            html = article._fetch_html(
                "https://example.com/article", timeout=30.0
            )
        assert html == "<html><body><p>actual body</p></body></html>"

    def test_403_raises_httpx_status_error(self):
        fake_module, _calls = _build_fake_curl_cffi_module(
            target_status=403, target_text=""
        )
        with _patch_curl_cffi(fake_module), patch(
            "scrapers_lib.core.curl_session.time.sleep"
        ):
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                article._fetch_html(
                    "https://example.com/blocked", timeout=30.0
                )
        assert exc_info.value.response.status_code == 403

    def test_500_raises_httpx_status_error(self):
        fake_module, _calls = _build_fake_curl_cffi_module(
            target_status=500, target_text=""
        )
        with _patch_curl_cffi(fake_module), patch(
            "scrapers_lib.core.curl_session.time.sleep"
        ):
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                article._fetch_html(
                    "https://example.com/", timeout=30.0
                )
        assert exc_info.value.response.status_code == 500


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registered_under_article(self):
        assert get_fetcher(SOURCE) is article.fetch_article

    def test_source_constant(self):
        assert SOURCE == "article"
