"""Unit tests for scrapers_lib.tier2.base."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scrapers_lib.tier2.base import (
    _find_balanced_brace_end,
    normalize_spec_value,
    parse_inline_json,
    parse_product_jsonld,
    parse_spec_table,
    warmed_curl_session,
)


# ---------------------------------------------------------------------------
# parse_product_jsonld
# ---------------------------------------------------------------------------


class TestParseProductJsonld:
    def test_single_object(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "Product",
         "name": "XPS 15", "sku": "xps-15-9540"}
        </script>
        </head></html>
        """
        products = parse_product_jsonld(html)
        assert len(products) == 1
        assert products[0]["name"] == "XPS 15"
        assert products[0]["sku"] == "xps-15-9540"

    def test_array_of_products(self):
        html = """
        <script type="application/ld+json">
        [{"@type": "Product", "name": "A"}, {"@type": "Product", "name": "B"}]
        </script>
        """
        products = parse_product_jsonld(html)
        assert [p["name"] for p in products] == ["A", "B"]

    def test_graph_wrapper(self):
        html = """
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@graph": [
          {"@type": "WebPage", "name": "ignore"},
          {"@type": "Product", "name": "Keep"}
        ]}
        </script>
        """
        products = parse_product_jsonld(html)
        assert len(products) == 1
        assert products[0]["name"] == "Keep"

    def test_filters_non_product_types(self):
        html = """
        <script type="application/ld+json">{"@type": "Organization", "name": "Dell"}</script>
        <script type="application/ld+json">{"@type": "BreadcrumbList"}</script>
        <script type="application/ld+json">{"@type": "Product", "name": "Alienware"}</script>
        """
        products = parse_product_jsonld(html)
        assert [p["name"] for p in products] == ["Alienware"]

    def test_type_as_list(self):
        html = """
        <script type="application/ld+json">
        {"@type": ["Product", "IndividualProduct"], "name": "P"}
        </script>
        """
        products = parse_product_jsonld(html)
        assert len(products) == 1
        assert products[0]["name"] == "P"

    def test_malformed_block_skipped_others_kept(self):
        html = """
        <script type="application/ld+json">{"not": valid JSON</script>
        <script type="application/ld+json">{"@type": "Product", "name": "OK"}</script>
        """
        products = parse_product_jsonld(html)
        assert [p["name"] for p in products] == ["OK"]

    def test_no_scripts(self):
        assert parse_product_jsonld("<html><body>hi</body></html>") == []

    def test_empty_script_skipped(self):
        html = """
        <script type="application/ld+json"></script>
        <script type="application/ld+json">   </script>
        """
        assert parse_product_jsonld(html) == []

    def test_nested_product_in_graph_in_array(self):
        # Some sites stack shapes; make sure recursion handles it.
        html = """
        <script type="application/ld+json">
        [{"@graph": [{"@type": "Product", "name": "Deep"}]}]
        </script>
        """
        products = parse_product_jsonld(html)
        assert [p["name"] for p in products] == ["Deep"]


# ---------------------------------------------------------------------------
# parse_inline_json
# ---------------------------------------------------------------------------


class TestParseInlineJsonScriptId:
    def test_nextdata_script(self):
        html = """
        <html><body>
        <script id="__NEXT_DATA__" type="application/json">
        {"props": {"pageProps": {"sku": "xyz"}}}
        </script>
        </body></html>
        """
        data = parse_inline_json(html, script_id="__NEXT_DATA__")
        assert data is not None
        assert data["props"]["pageProps"]["sku"] == "xyz"

    def test_script_missing(self):
        assert parse_inline_json("<html></html>", script_id="__NEXT_DATA__") is None

    def test_script_malformed_returns_none(self):
        html = """<script id="__NEXT_DATA__" type="application/json">{not valid json</script>"""
        assert parse_inline_json(html, script_id="__NEXT_DATA__") is None

    def test_script_content_is_array_returns_none(self):
        # parse_inline_json contract is to return dict | None.
        html = """<script id="X" type="application/json">[1, 2, 3]</script>"""
        assert parse_inline_json(html, script_id="X") is None


class TestParseInlineJsonWindowVar:
    def test_window_assignment(self):
        html = """<script>window.__INITIAL_STATE__ = {"configs": [{"id": 1}]};</script>"""
        data = parse_inline_json(html, window_var="__INITIAL_STATE__")
        assert data == {"configs": [{"id": 1}]}

    def test_var_declaration(self):
        html = """<script>var DELL_STATE = {"a": 1};</script>"""
        data = parse_inline_json(html, window_var="DELL_STATE")
        assert data == {"a": 1}

    def test_const_declaration(self):
        html = """<script>const X = {"k": "v"};</script>"""
        assert parse_inline_json(html, window_var="X") == {"k": "v"}

    def test_nested_braces_in_strings(self):
        html = (
            """<script>window.X = {"note": "this has { and } inside", "n": 7};</script>"""
        )
        data = parse_inline_json(html, window_var="X")
        assert data == {"note": "this has { and } inside", "n": 7}

    def test_escaped_quote_in_string(self):
        html = r"""<script>window.X = {"msg": "she said \"hi\""};</script>"""
        data = parse_inline_json(html, window_var="X")
        assert data == {"msg": 'she said "hi"'}

    def test_window_var_missing(self):
        html = "<script>window.Y = {};</script>"
        assert parse_inline_json(html, window_var="X") is None

    def test_name_must_match_exactly(self):
        # Similar name should not match.
        html = "<script>window.FOOBAR = {\"k\": 1};</script>"
        assert parse_inline_json(html, window_var="FOO") is None

    def test_malformed_payload_returns_none(self):
        # Opening brace found but the body isn't valid JSON (e.g. JS object literal).
        html = "<script>window.X = {k: 1};</script>"
        assert parse_inline_json(html, window_var="X") is None


class TestParseInlineJsonDiscriminator:
    def test_requires_exactly_one(self):
        with pytest.raises(ValueError):
            parse_inline_json("<html></html>")
        with pytest.raises(ValueError):
            parse_inline_json("<html></html>", script_id="x", window_var="Y")


# ---------------------------------------------------------------------------
# _find_balanced_brace_end (internal but worth testing directly)
# ---------------------------------------------------------------------------


class TestFindBalancedBraceEnd:
    def test_simple(self):
        assert _find_balanced_brace_end("{}", 0) == 1

    def test_nested(self):
        s = '{"a": {"b": 1}}'
        assert _find_balanced_brace_end(s, 0) == len(s) - 1

    def test_braces_in_strings_ignored(self):
        s = '{"a": "has } brace"}'
        assert _find_balanced_brace_end(s, 0) == len(s) - 1

    def test_escape_sequences(self):
        s = '{"a": "esc \\" still in str } x"}'
        assert _find_balanced_brace_end(s, 0) == len(s) - 1

    def test_unbalanced_returns_none(self):
        assert _find_balanced_brace_end("{{}", 0) is None

    def test_wrong_start_returns_none(self):
        assert _find_balanced_brace_end("foo{}", 0) is None


# ---------------------------------------------------------------------------
# parse_spec_table
# ---------------------------------------------------------------------------


class TestParseSpecTable:
    def test_tr_with_th(self):
        html = """
        <table><tbody>
          <tr><th>CPU</th><td>Intel Core i7</td></tr>
          <tr><th>Memory</th><td>32 GB</td></tr>
        </tbody></table>
        """
        assert parse_spec_table(html) == {"CPU": "Intel Core i7", "Memory": "32 GB"}

    def test_tr_all_td(self):
        html = """
        <table>
          <tr><td>Storage</td><td>1 TB SSD</td></tr>
        </table>
        """
        assert parse_spec_table(html) == {"Storage": "1 TB SSD"}

    def test_dl_pairs(self):
        html = """
        <dl>
          <dt>Display</dt><dd>16" OLED</dd>
          <dt>Battery</dt><dd>90 Wh</dd>
        </dl>
        """
        assert parse_spec_table(html) == {"Display": '16" OLED', "Battery": "90 Wh"}

    def test_container_selector_scopes(self):
        html = """
        <div class="outside">
          <table><tr><th>Noise</th><td>ignored</td></tr></table>
        </div>
        <div class="specs">
          <table><tr><th>GPU</th><td>RTX 5070</td></tr></table>
        </div>
        """
        assert parse_spec_table(html, container_selector="div.specs") == {"GPU": "RTX 5070"}

    def test_missing_container_returns_empty(self):
        html = "<table><tr><th>K</th><td>V</td></tr></table>"
        assert parse_spec_table(html, container_selector="div.none") == {}

    def test_skips_empty_rows(self):
        html = """
        <table>
          <tr><th></th><td>no key</td></tr>
          <tr><th>K</th><td></td></tr>
          <tr><th>OK</th><td>value</td></tr>
        </table>
        """
        assert parse_spec_table(html) == {"OK": "value"}

    def test_first_occurrence_wins_on_duplicate(self):
        html = """
        <table>
          <tr><th>CPU</th><td>first</td></tr>
          <tr><th>CPU</th><td>second</td></tr>
        </table>
        """
        assert parse_spec_table(html) == {"CPU": "first"}

    def test_accepts_soup_object(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(
            "<table><tr><th>A</th><td>B</td></tr></table>", "html.parser"
        )
        assert parse_spec_table(soup) == {"A": "B"}

    def test_normalizes_values(self):
        # The value contains a literal nbsp (U+00A0) plus newlines and
        # surrounding whitespace; parse_spec_table funnels into
        # normalize_spec_value.
        html = (
            "<table><tr><th>RAM</th><td>  32 GB\n  DDR5  </td></tr></table>"
        )
        assert parse_spec_table(html) == {"RAM": "32 GB DDR5"}

    def test_no_tables_returns_empty(self):
        assert parse_spec_table("<div>nothing here</div>") == {}

    def test_row_with_single_cell_skipped(self):
        html = "<table><tr><th>lone</th></tr><tr><th>K</th><td>V</td></tr></table>"
        assert parse_spec_table(html) == {"K": "V"}

    def test_dl_without_dd_skipped(self):
        html = "<dl><dt>orphan</dt></dl>"
        assert parse_spec_table(html) == {}


# ---------------------------------------------------------------------------
# normalize_spec_value
# ---------------------------------------------------------------------------


class TestNormalizeSpecValue:
    def test_collapses_whitespace(self):
        assert normalize_spec_value("  hello   world  ") == "hello world"

    def test_converts_nbsp(self):
        assert normalize_spec_value("32 GB") == "32 GB"

    def test_tabs_and_newlines(self):
        assert normalize_spec_value("a\tb\n\nc") == "a b c"

    def test_preserves_commas_and_parens(self):
        assert (
            normalize_spec_value("  Intel Core i7, 14-core (up to 5.0 GHz)  ")
            == "Intel Core i7, 14-core (up to 5.0 GHz)"
        )

    def test_empty(self):
        assert normalize_spec_value("") == ""
        assert normalize_spec_value("   ") == ""

    def test_only_nbsp_collapses_to_empty(self):
        assert normalize_spec_value("  ") == ""


# ---------------------------------------------------------------------------
# warmed_curl_session
# ---------------------------------------------------------------------------


def _fake_curl_cffi_module():
    """Build a fake ``curl_cffi`` module recording every Session.get call.

    Returns ``(module, calls_recorder, sessions_list)``. ``calls_recorder``
    is a ``MagicMock`` whose ``call_args_list`` captures every
    ``Session.get`` call. ``sessions_list`` records each constructed
    ``_FakeSession`` instance and tracks ``__enter__`` / ``__exit__``
    for the context-manager exit assertion.
    """
    calls = MagicMock()
    sessions: list[Any] = []

    class _FakeResp:
        def __init__(self, text: str = "", status: int = 200) -> None:
            self.text = text
            self.status_code = status

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class _FakeSession:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.entered = False
            self.exited = False
            sessions.append(self)

        def __enter__(self) -> "_FakeSession":
            self.entered = True
            return self

        def __exit__(self, *exc: Any) -> None:
            self.exited = True
            return None

        def get(self, url: str, **kwargs: Any) -> _FakeResp:
            calls(url=url, session_kwargs=self.kwargs, **kwargs)
            return _FakeResp("", status=200)

    fake_requests = SimpleNamespace(Session=_FakeSession)
    fake_curl_http_version = SimpleNamespace(V1_1="V1_1_SENTINEL")
    fake_module = SimpleNamespace(
        requests=fake_requests, CurlHttpVersion=fake_curl_http_version
    )
    return fake_module, calls, sessions


class TestWarmedCurlSession:
    """Verify the warmed_curl_session() context-manager contract."""

    def _patch_curl_cffi(self, fake_module: Any):
        return patch.dict(
            "sys.modules",
            {
                "curl_cffi": fake_module,
                "curl_cffi.requests": fake_module.requests,
            },
        )

    def test_warm_true_calls_homepage_and_sleeps(self):
        fake_module, calls, _ = _fake_curl_cffi_module()
        with self._patch_curl_cffi(fake_module), patch(
            "scrapers_lib.tier2.base.time.sleep"
        ) as sleep_mock:
            with warmed_curl_session(
                "https://example.com/", warm=True, warm_delay=2.5
            ) as s:
                assert s is not None
        urls = [c.kwargs["url"] for c in calls.call_args_list]
        assert urls == ["https://example.com/"]
        sleep_mock.assert_called_once_with(2.5)

    def test_warm_false_skips_homepage_and_sleep(self):
        fake_module, calls, _ = _fake_curl_cffi_module()
        with self._patch_curl_cffi(fake_module), patch(
            "scrapers_lib.tier2.base.time.sleep"
        ) as sleep_mock:
            with warmed_curl_session(
                "https://example.com/", warm=False
            ) as s:
                assert s is not None
        assert calls.call_args_list == []
        sleep_mock.assert_not_called()

    def test_warm_failure_is_swallowed(self):
        """Homepage GET raising must not break the helper - yield anyway."""
        calls = MagicMock()
        sessions: list[Any] = []

        class _RaisingSession:
            def __init__(self, **kwargs: Any) -> None:
                self.kwargs = kwargs
                sessions.append(self)

            def __enter__(self) -> "_RaisingSession":
                return self

            def __exit__(self, *exc: Any) -> None:
                return None

            def get(self, url: str, **kwargs: Any) -> Any:
                calls(url=url)
                raise RuntimeError("simulated network failure")

        fake_requests = SimpleNamespace(Session=_RaisingSession)
        fake_curl_http_version = SimpleNamespace(V1_1="V1_1_SENTINEL")
        fake_module = SimpleNamespace(
            requests=fake_requests, CurlHttpVersion=fake_curl_http_version
        )

        with self._patch_curl_cffi(fake_module), patch(
            "scrapers_lib.tier2.base.time.sleep"
        ):
            # Must NOT raise - warm-up failure is best-effort.
            with warmed_curl_session(
                "https://example.com/", warm=True
            ) as s:
                assert s is not None
        assert calls.call_args_list and calls.call_args_list[0].kwargs[
            "url"
        ] == "https://example.com/"

    def test_warm_headers_passed_to_homepage_get(self):
        fake_module, calls, _ = _fake_curl_cffi_module()
        custom_headers = {"X-Custom-Probe": "1", "User-Agent": "test"}
        with self._patch_curl_cffi(fake_module), patch(
            "scrapers_lib.tier2.base.time.sleep"
        ):
            with warmed_curl_session(
                "https://example.com/",
                warm=True,
                warm_headers=custom_headers,
            ):
                pass
        assert len(calls.call_args_list) == 1
        warm_call = calls.call_args_list[0]
        assert warm_call.kwargs["url"] == "https://example.com/"
        assert warm_call.kwargs.get("headers") == custom_headers

    def test_warm_headers_omitted_when_not_supplied(self):
        fake_module, calls, _ = _fake_curl_cffi_module()
        with self._patch_curl_cffi(fake_module), patch(
            "scrapers_lib.tier2.base.time.sleep"
        ):
            with warmed_curl_session(
                "https://example.com/", warm=True
            ):
                pass
        assert len(calls.call_args_list) == 1
        warm_call = calls.call_args_list[0]
        assert "headers" not in warm_call.kwargs

    def test_session_uses_chrome_impersonate_and_http11(self):
        fake_module, calls, sessions = _fake_curl_cffi_module()
        with self._patch_curl_cffi(fake_module), patch(
            "scrapers_lib.tier2.base.time.sleep"
        ):
            with warmed_curl_session(
                "https://example.com/", warm=True
            ):
                pass
        assert len(sessions) == 1
        assert sessions[0].kwargs["impersonate"] == "chrome"
        assert sessions[0].kwargs["http_version"] == "V1_1_SENTINEL"

    def test_custom_impersonate_propagates(self):
        fake_module, _calls, sessions = _fake_curl_cffi_module()
        with self._patch_curl_cffi(fake_module), patch(
            "scrapers_lib.tier2.base.time.sleep"
        ):
            with warmed_curl_session(
                "https://example.com/",
                impersonate="chrome120",
                warm=False,
            ):
                pass
        assert len(sessions) == 1
        assert sessions[0].kwargs["impersonate"] == "chrome120"

    def test_context_manager_exits_session(self):
        fake_module, _calls, sessions = _fake_curl_cffi_module()
        with self._patch_curl_cffi(fake_module), patch(
            "scrapers_lib.tier2.base.time.sleep"
        ):
            with warmed_curl_session(
                "https://example.com/", warm=False
            ):
                pass
        assert len(sessions) == 1
        assert sessions[0].entered is True
        assert sessions[0].exited is True

    def test_default_warm_delay_is_one_second(self):
        fake_module, _calls, _ = _fake_curl_cffi_module()
        with self._patch_curl_cffi(fake_module), patch(
            "scrapers_lib.tier2.base.time.sleep"
        ) as sleep_mock:
            with warmed_curl_session("https://example.com/"):
                pass
        sleep_mock.assert_called_once_with(1.0)
