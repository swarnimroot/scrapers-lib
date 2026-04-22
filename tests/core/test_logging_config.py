"""Unit tests for scrapers_lib.core.logging_config."""

import io
import logging

import pytest

from scrapers_lib.core.logging_config import configure_logging, _reset_for_tests


@pytest.fixture(autouse=True)
def _reset():
    _reset_for_tests()
    yield
    _reset_for_tests()


class TestConfigureLogging:
    def test_default_level_info(self):
        configure_logging()
        assert logging.getLogger().level == logging.INFO

    def test_level_string(self):
        configure_logging(level="DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_level_int(self):
        configure_logging(level=logging.WARNING)
        assert logging.getLogger().level == logging.WARNING

    def test_idempotent_no_duplicate_handlers(self):
        buf = io.StringIO()
        configure_logging(stream=buf)
        configure_logging(stream=buf)
        configure_logging(stream=buf)
        # Use exact type check — pytest installs LogCaptureHandler (a StreamHandler subclass)
        # that we must not count as one of ours.
        root = logging.getLogger()
        our_handlers = [h for h in root.handlers if type(h) is logging.StreamHandler]
        assert len(our_handlers) == 1

    def test_custom_stream_receives_output(self):
        buf = io.StringIO()
        configure_logging(level="DEBUG", stream=buf)
        logging.getLogger("scrapers_lib.test").info("hello world")
        out = buf.getvalue()
        assert "hello world" in out
        assert "scrapers_lib.test" in out
        assert "INFO" in out

    def test_per_module_overrides(self):
        configure_logging(
            level="INFO",
            per_module={"scrapers_lib.tier3": "DEBUG", "scrapers_lib.tier1": "WARNING"},
        )
        assert logging.getLogger("scrapers_lib.tier3").level == logging.DEBUG
        assert logging.getLogger("scrapers_lib.tier1").level == logging.WARNING

    def test_level_updates_on_second_call(self):
        configure_logging(level="INFO")
        configure_logging(level="ERROR")
        assert logging.getLogger().level == logging.ERROR
