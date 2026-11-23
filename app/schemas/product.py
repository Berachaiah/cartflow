"""
Product request/response schemas (doc 12 §26).

Validation lives here rather than in the route, and it is deliberately strict
about the two things a seller can get wrong in a way that only shows up later:

  - `category` must be one of the configured categories. A free-text category
    would be a product the Shop's chips can never filter to.
  - `was_price` must be ABOVE `price`. A "discount" that isn't one is a lie in
    the badge, and `discount_percent` would quietly render 0% next to a
    strike-through price.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.catalog import CATEGORIES

_SELLABLE_CATEGORIES = {c["name"] for c in CATEGORIES if c["name"] != "All"}


class ProductCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: str
    price: int = Field(ge=0, le=100_000_000, description="Whole naira.")
    was_price: int | None = Field(default=None, ge=0, le=100_000_000)
    stock: int = Field(default=0, ge=0, le=1_000_000)
    tags: list[str] = Field(default_factory=list)
    delivery_areas: list[str] = Field(default_factory=list)
    pickup_address: str | None = Field(default=None, max_length=500)
    image_url: str | None = Field(default=None, max_length=500)
    image_alt: str | None = Field(default=None, max_length=300)
    # `archived` is a state the seller reaches through DELETE, not by posting it.
    status: Literal["active", "draft"] = "active"

    @field_validator("name", "category", "pickup_address", "image_alt")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in _SELLABLE_CATEGORIES:
            raise ValueError(f"Pick one of: {', '.join(sorted(_SELLABLE_CATEGORIES))}.")
        return value

    @field_validator("tags", "delivery_areas")
    @classmethod
    def _clean_list(cls, value: list[str]) -> list[str]:
        """Trim, drop blanks, de-duplicate case-insensitively, cap the count.

        Tags are rendered as chips and searched client-side; a leading space or a
        duplicate is a chip nobody can match.
        """
        seen, out = set(), []
        for item in value:
            cleaned = (item or "").strip()[:30]
            key = cleaned.lower()
            if cleaned and key not in seen:
                seen.add(key)
                out.append(cleaned)
        return out[:12]

    @model_validator(mode="after")
    def _discount_is_real(self) -> "ProductCreateRequest":
        if self.was_price is not None and self.was_price <= self.price:
            raise ValueError("The 'was' price has to be higher than the price.")
        return self


class ProductUpdateRequest(BaseModel):
    """Every field optional: the Hub submits only what changed.

    `exclude_unset` at the call site is what distinguishes "leave stock alone"
    from "set stock to 0", and those are very different instructions to a shop.
    """

    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = None
    price: int | None = Field(default=None, ge=0, le=100_000_000)
    was_price: int | None = Field(default=None, ge=0, le=100_000_000)
    stock: int | None = Field(default=None, ge=0, le=1_000_000)
    tags: list[str] | None = None
    delivery_areas: list[str] | None = None
    pickup_address: str | None = Field(default=None, max_length=500)
    image_url: str | None = Field(default=None, max_length=500)
    image_alt: str | None = Field(default=None, max_length=300)
    status: Literal["active", "draft", "archived"] | None = None

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str | None) -> str | None:
        if value is not None and value not in _SELLABLE_CATEGORIES:
            raise ValueError(f"Pick one of: {', '.join(sorted(_SELLABLE_CATEGORIES))}.")
        return value

    @field_validator("tags", "delivery_areas")
    @classmethod
    def _clean_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        seen, out = set(), []
        for item in value:
            cleaned = (item or "").strip()[:30]
            key = cleaned.lower()
            if cleaned and key not in seen:
                seen.add(key)
                out.append(cleaned)
        return out[:12]


class ProductResponse(BaseModel):
    message: str
    product: dict


class ProductListResponse(BaseModel):
    message: str = "OK"
    products: list[dict]
    count: int
