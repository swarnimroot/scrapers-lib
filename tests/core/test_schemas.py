"""Unit tests for scrapers_lib.core.schemas."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from scrapers_lib.core.schemas import (
    Anchor,
    Attribution,
    AttributionRegex,
    ProductSnapshot,
    RawMention,
)


class TestAttributionRegex:
    def test_minimal_valid(self):
        rx = AttributionRegex(primary=["foo"])
        assert rx.primary == ["foo"]
        assert rx.corroboration == []
        assert rx.exclusion == []

    def test_full_valid(self):
        rx = AttributionRegex(
            primary=["foo"], corroboration=["bar"], exclusion=["baz"]
        )
        assert rx.corroboration == ["bar"]
        assert rx.exclusion == ["baz"]

    def test_empty_primary_rejected(self):
        with pytest.raises(ValidationError):
            AttributionRegex(primary=[])

    def test_missing_primary_rejected(self):
        with pytest.raises(ValidationError):
            AttributionRegex()  # type: ignore[call-arg]


class TestAnchor:
    def test_minimal_valid(self):
        a = Anchor(
            anchor_id="test",
            anchor_type="topic",
            name="Test",
            attribution_regex=AttributionRegex(primary=["test"]),
        )
        assert a.anchor_id == "test"
        assert a.aliases == []
        assert a.source_urls == {}
        assert a.attributes == {}
        assert a.notes is None

    def test_full_valid(self):
        a = Anchor(
            anchor_id="example_product",
            anchor_type="product",
            name="Example Product",
            aliases=["ExProd", "EP"],
            attribution_regex=AttributionRegex(
                primary=["Example Product"],
                corroboration=["ExProd"],
                exclusion=["Not Example"],
            ),
            source_urls={"dell": "https://www.dell.com/example-product"},
            attributes={"brand": "Example", "cpu": "Ultra 9"},
            notes="initial setup",
        )
        assert a.source_urls["dell"].endswith("example-product")
        assert a.attributes["cpu"] == "Ultra 9"

    def test_attribution_regex_accepts_dict(self):
        a = Anchor(
            anchor_id="x",
            anchor_type="topic",
            name="X",
            attribution_regex={"primary": ["x"]},  # type: ignore[arg-type]
        )
        assert a.attribution_regex.primary == ["x"]

    def test_empty_anchor_id_rejected(self):
        with pytest.raises(ValidationError):
            Anchor(
                anchor_id="",
                anchor_type="topic",
                name="X",
                attribution_regex=AttributionRegex(primary=["x"]),
            )

    def test_invalid_anchor_type_rejected(self):
        with pytest.raises(ValidationError):
            Anchor(
                anchor_id="x",
                anchor_type="not_a_type",  # type: ignore[arg-type]
                name="X",
                attribution_regex=AttributionRegex(primary=["x"]),
            )

    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            Anchor(
                anchor_id="x",
                anchor_type="topic",
                name="X",
                attribution_regex=AttributionRegex(primary=["x"]),
                unknown_field="nope",  # type: ignore[call-arg]
            )


class TestAttribution:
    def test_minimal_valid(self):
        a = Attribution(anchor_id="x", confidence=1.0, method="regex")
        assert a.matched_tokens == []

    def test_confidence_above_one_rejected(self):
        with pytest.raises(ValidationError):
            Attribution(anchor_id="x", confidence=1.5, method="regex")

    def test_confidence_negative_rejected(self):
        with pytest.raises(ValidationError):
            Attribution(anchor_id="x", confidence=-0.1, method="regex")

    def test_invalid_method_rejected(self):
        with pytest.raises(ValidationError):
            Attribution(anchor_id="x", confidence=1.0, method="invalid")  # type: ignore[arg-type]


class TestProductSnapshot:
    def _make(self, **overrides):
        defaults = dict(
            source="test",
            source_id="SKU123",
            anchor_id="test_anchor",
            url="https://example.com/p/123",
            title="Test Product",
        )
        defaults.update(overrides)
        return ProductSnapshot(**defaults)

    def test_minimal_valid(self):
        p = self._make()
        assert p.currency == "USD"
        assert p.specs == {}
        assert p.fetched_at.tzinfo is not None

    def test_price_decimal(self):
        p = self._make(price=Decimal("1299.99"))
        assert p.price == Decimal("1299.99")

    def test_price_from_string(self):
        p = self._make(price="1299.99")
        assert p.price == Decimal("1299.99")

    def test_negative_price_rejected(self):
        with pytest.raises(ValidationError):
            self._make(price=Decimal("-1.00"))

    def test_rating_valid(self):
        p = self._make(rating=4.5)
        assert p.rating == 4.5

    def test_rating_above_five_rejected(self):
        with pytest.raises(ValidationError):
            self._make(rating=5.1)

    def test_rating_negative_rejected(self):
        with pytest.raises(ValidationError):
            self._make(rating=-0.1)

    def test_negative_review_count_rejected(self):
        with pytest.raises(ValidationError):
            self._make(review_count=-1)

    def test_model_field_does_not_collide(self):
        """`model` as a field name must not conflict with Pydantic internals."""
        p = self._make(model="XPS 15")
        assert p.model == "XPS 15"


class TestRawMention:
    def _make(self, **overrides):
        defaults = dict(
            mention_id="test_123",
            source="test",
            source_type="post",
            source_url="https://example.com/p/1",
            raw_text="Some verbatim text.",
            attribution=Attribution(anchor_id="x", confidence=1.0, method="regex"),
        )
        defaults.update(overrides)
        return RawMention(**defaults)

    def test_minimal_valid(self):
        m = self._make()
        assert m.fetched_at.tzinfo is not None
        assert m.raw_text == "Some verbatim text."

    def test_empty_raw_text_rejected(self):
        with pytest.raises(ValidationError):
            self._make(raw_text="")

    def test_whitespace_only_raw_text_rejected(self):
        with pytest.raises(ValidationError):
            self._make(raw_text="   \n\t  ")

    def test_invalid_source_type_rejected(self):
        with pytest.raises(ValidationError):
            self._make(source_type="not_a_type")  # type: ignore[arg-type]

    def test_attribution_accepts_dict(self):
        m = self._make(
            attribution={"anchor_id": "x", "confidence": 1.0, "method": "regex"}  # type: ignore[arg-type]
        )
        assert m.attribution.anchor_id == "x"
