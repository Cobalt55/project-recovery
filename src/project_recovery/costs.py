"""Versioned OpenAI token-cost estimates for the approved model policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Final

PRICING_EFFECTIVE_DATE: Final = "2026-08-11"
PRICING_SOURCE_ROOT: Final = "https://developers.openai.com/api/docs/models/"
TOKENS_PER_MILLION: Final = Decimal("1000000")
MONEY_QUANTUM: Final = Decimal("0.000001")


@dataclass(frozen=True)
class TokenPrices:
    """USD prices per one million text tokens."""

    input: Decimal
    cached_input: Decimal
    output: Decimal
    source_url: str


MODEL_PRICES: Final[Mapping[str, TokenPrices]] = MappingProxyType(
    {
        "gpt-5.6-luna": TokenPrices(
            input=Decimal("0.20"),
            cached_input=Decimal("0.02"),
            output=Decimal("1.20"),
            source_url=f"{PRICING_SOURCE_ROOT}gpt-5.6-luna",
        ),
        "gpt-5.6-terra": TokenPrices(
            input=Decimal("2.00"),
            cached_input=Decimal("0.20"),
            output=Decimal("12.00"),
            source_url=f"{PRICING_SOURCE_ROOT}gpt-5.6-terra",
        ),
        "gpt-5.6-sol": TokenPrices(
            input=Decimal("5.00"),
            cached_input=Decimal("0.50"),
            output=Decimal("30.00"),
            source_url=f"{PRICING_SOURCE_ROOT}gpt-5.6-sol",
        ),
    }
)


def calculate_cost(
    model: str,
    input_tokens: int | None,
    cached_tokens: int | None,
    output_tokens: int | None,
) -> Decimal | None:
    """Return a six-decimal USD estimate, or ``None`` when it is unpriceable.

    The Agents SDK reports cached input as a subset of total input. Unknown
    models and inconsistent counters remain explicitly unpriced.
    """

    prices = MODEL_PRICES.get(model)
    if prices is None or input_tokens is None or output_tokens is None:
        return None
    cached = cached_tokens or 0
    if input_tokens < 0 or cached < 0 or output_tokens < 0 or cached > input_tokens:
        return None
    uncached = input_tokens - cached
    estimate = (
        Decimal(uncached) * prices.input
        + Decimal(cached) * prices.cached_input
        + Decimal(output_tokens) * prices.output
    ) / TOKENS_PER_MILLION
    return estimate.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


__all__ = [
    "MODEL_PRICES",
    "PRICING_EFFECTIVE_DATE",
    "TokenPrices",
    "calculate_cost",
]
