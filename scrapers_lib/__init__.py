"""scrapers-lib — multi-source scraping library with normalized schemas and a persistent scheduler."""

from scrapers_lib._version import __version__
from scrapers_lib.core.scheduler import BlockedError, Scheduler
from scrapers_lib.core.schemas import (
    Anchor,
    Attribution,
    AttributionRegex,
    ProductSnapshot,
    RawMention,
)

__all__ = [
    "__version__",
    "Anchor",
    "Attribution",
    "AttributionRegex",
    "BlockedError",
    "ProductSnapshot",
    "RawMention",
    "Scheduler",
]
