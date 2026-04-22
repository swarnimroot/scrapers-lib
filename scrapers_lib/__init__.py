"""scrapers-lib — multi-source scraping library with normalized schemas and a persistent scheduler."""

from scrapers_lib.core.schemas import (
    Anchor,
    Attribution,
    AttributionRegex,
    ProductSnapshot,
    RawMention,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Anchor",
    "Attribution",
    "AttributionRegex",
    "ProductSnapshot",
    "RawMention",
]
