"""Pydantic v2 schemas for scrapers-lib.

Three core types every fetcher emits:

- :class:`Anchor` — a thing the consumer is tracking (product, game, company, topic).
  Consumer-defined; the library never creates one.
- :class:`ProductSnapshot` — a point-in-time observation of a product listing on a
  specific source (price, stock, specs, variant).
- :class:`RawMention` — a piece of verbatim text from a community, news, or
  transcript source, attributed to an Anchor.

See ``docs/ARCHITECTURE.md`` §3 for the field-by-field reference.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AnchorType = Literal["product", "game", "company", "topic", "custom"]
MentionSourceType = Literal["post", "comment", "article", "video", "transcript_chunk"]
AttributionMethod = Literal["regex", "url_map", "manual"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AttributionRegex(BaseModel):
    """Token lists that drive regex-based attribution.

    Tokens are literal by default (auto-escaped for regex). Prefix a token with
    ``re:`` to treat the rest as raw regex. Matching is case-insensitive.
    See :mod:`scrapers_lib.core.attribution` for the gate semantics.
    """

    model_config = ConfigDict(extra="forbid")

    primary: list[str] = Field(..., min_length=1)
    corroboration: list[str] = Field(default_factory=list)
    exclusion: list[str] = Field(default_factory=list)


class Anchor(BaseModel):
    """A thing the consumer is tracking. Consumer-defined; the library never creates one.

    Anchors drive attribution: for a piece of text or a product page to be relevant,
    the library must be able to link it to one of the consumer's Anchors via
    :attr:`attribution_regex` or :attr:`source_urls`.
    """

    model_config = ConfigDict(extra="forbid")

    anchor_id: str = Field(..., min_length=1)
    anchor_type: AnchorType
    name: str = Field(..., min_length=1)
    aliases: list[str] = Field(default_factory=list)
    attribution_regex: AttributionRegex
    source_urls: dict[str, str] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class Attribution(BaseModel):
    """Result of attributing a piece of text or a product page to an Anchor."""

    model_config = ConfigDict(extra="forbid")

    anchor_id: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
    method: AttributionMethod
    matched_tokens: list[str] = Field(default_factory=list)


class ComponentOption(BaseModel):
    """A single selectable option within a configurator module.

    Currently surfaced only by the Dell fetcher (Wave 2h, v1.5.0) when
    invoked with ``include_options=True``. ``status`` carries the source
    site's vocabulary verbatim — Dell uses ``"selected"`` (the current
    default), ``"available"`` (offered and orderable), and
    ``"unavailable"`` (offered on the page but not currently shippable
    — typically out of stock or constrained by another selection).
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    option_id: str = Field(..., min_length=1)


class ProductSnapshot(BaseModel):
    """A point-in-time observation of a product listing on a specific source.

    Consumers accumulate snapshots over time and diff them to derive price or
    availability history. The library itself is stateless.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    source: str = Field(..., min_length=1)
    source_id: str = Field(..., min_length=1)
    variant_key: str | None = None
    anchor_id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    brand: str | None = None
    model: str | None = None
    category: str | None = None
    config_summary: str | None = None
    price: Decimal | None = None
    list_price: Decimal | None = None
    currency: str = "USD"
    in_stock: bool | None = None
    availability_text: str | None = None
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    review_count: int | None = Field(default=None, ge=0)
    image_url: str | None = None
    specs: dict[str, str] = Field(default_factory=dict)
    options: dict[str, list[ComponentOption]] | None = None
    raw: dict[str, Any] | None = None
    fetched_at: datetime = Field(default_factory=_utc_now)

    @field_validator("price", "list_price")
    @classmethod
    def _nonneg_price(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError("price/list_price must be non-negative")
        return v


class RawMention(BaseModel):
    """A piece of verbatim text from a source, optionally attributed to an Anchor.

    ``attribution`` is ``None`` when the fetcher was invoked in discovery mode
    (``anchors=None``) — the downstream consumer applies its own filters. When
    ``anchors=[...]`` is passed, the fetcher emits one ``RawMention`` per
    matched anchor and ``attribution`` is populated.
    """

    model_config = ConfigDict(extra="forbid")

    mention_id: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    source_type: MentionSourceType
    source_url: str = Field(..., min_length=1)
    source_title: str | None = None
    author: str | None = None
    author_id: str | None = None
    channel: str | None = None
    parent_id: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=_utc_now)
    raw_text: str = Field(..., min_length=1)
    attribution: Attribution | None = None
    raw: dict[str, Any] | None = None

    @field_validator("raw_text")
    @classmethod
    def _raw_text_nonempty_after_strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("raw_text must be non-empty after stripping whitespace")
        return v
