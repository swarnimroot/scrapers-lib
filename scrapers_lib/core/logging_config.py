"""Opt-in logging configuration helper for consumers of scrapers-lib.

The library never auto-configures logging. Library modules call
``logging.getLogger(__name__)`` and emit at appropriate levels; consumers
decide whether and how to surface those records.

This helper is provided as a convenience for consumers who want a sensible
default setup: call :func:`configure_logging` once at startup and go.
"""

from __future__ import annotations

import logging
import sys
from typing import IO


_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"
_SENTINEL_ATTR = "_scrapers_lib_configured"


def configure_logging(
    level: str | int = "INFO",
    *,
    stream: IO | None = None,
    per_module: dict[str, str | int] | None = None,
) -> None:
    """Install a StreamHandler on the root logger at ``level``.

    Idempotent: calling more than once does not add duplicate handlers
    (uses a sentinel attribute on the root logger).

    ``per_module`` lets consumers tune specific logger levels, e.g.
    ``{"scrapers_lib.tier3": "DEBUG"}`` to verbose-log Tier 3 scrapers
    while keeping the rest at INFO.
    """
    root = logging.getLogger()

    if not getattr(root, _SENTINEL_ATTR, False):
        handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
        handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT))
        root.addHandler(handler)
        setattr(root, _SENTINEL_ATTR, True)

    root.setLevel(level)

    if per_module:
        for name, mod_level in per_module.items():
            logging.getLogger(name).setLevel(mod_level)


def _reset_for_tests() -> None:
    """Test-only: remove our handler and sentinel so configure_logging can be retested."""
    root = logging.getLogger()
    if getattr(root, _SENTINEL_ATTR, False):
        for h in list(root.handlers):
            root.removeHandler(h)
        delattr(root, _SENTINEL_ATTR)
