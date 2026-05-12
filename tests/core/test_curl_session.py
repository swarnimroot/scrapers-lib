"""Unit tests for scrapers_lib.core.curl_session.

Helper graduated from ``tier2/base`` to ``core/`` in v1.4.0 because the
Tier 1 article fetcher now uses it too. Test scope is unchanged: verify
the warmed_curl_session() context-manager contract via a fake curl_cffi
module patched into sys.modules.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from scrapers_lib.core.curl_session import warmed_curl_session


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
            "scrapers_lib.core.curl_session.time.sleep"
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
            "scrapers_lib.core.curl_session.time.sleep"
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
            "scrapers_lib.core.curl_session.time.sleep"
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
            "scrapers_lib.core.curl_session.time.sleep"
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
            "scrapers_lib.core.curl_session.time.sleep"
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
            "scrapers_lib.core.curl_session.time.sleep"
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
            "scrapers_lib.core.curl_session.time.sleep"
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
            "scrapers_lib.core.curl_session.time.sleep"
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
            "scrapers_lib.core.curl_session.time.sleep"
        ) as sleep_mock:
            with warmed_curl_session("https://example.com/"):
                pass
        sleep_mock.assert_called_once_with(1.0)


class TestTier2BaseReExport:
    """Backwards-compat shim — pre-v1.4.0 imports must keep working."""

    def test_tier2_base_reexports_same_function(self):
        from scrapers_lib.tier2.base import (
            warmed_curl_session as shim_warmed_curl_session,
        )

        assert shim_warmed_curl_session is warmed_curl_session
