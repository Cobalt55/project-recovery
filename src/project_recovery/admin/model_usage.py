"""Model Usage window policy and view formatting."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from project_recovery.costs import PRICING_EFFECTIVE_DATE

USAGE_WINDOWS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "all": None,
}


def window_start(window: str, now: datetime | None = None) -> datetime | None:
    """Resolve a supported usage window or reject it explicitly."""
    if window not in USAGE_WINDOWS:
        raise ValueError("unsupported usage window")
    duration = USAGE_WINDOWS[window]
    return None if duration is None else (now or datetime.now(UTC)) - duration


def usage_view(summary: dict[str, object]) -> dict[str, object]:
    """Normalize aggregate decimals and expose the pricing effective date."""
    overview_value = summary.get("overview")
    overview = dict(overview_value) if isinstance(overview_value, Mapping) else {}
    models_value = summary.get("models")
    models = (
        [dict(row) for row in models_value if isinstance(row, Mapping)]
        if isinstance(models_value, list)
        else []
    )
    for row in [overview, *models]:
        cost = row.get("estimated_cost")
        row["estimated_cost"] = f"{Decimal(cost or 0):.6f}"
        latency = row.get("average_latency_ms")
        if latency is not None:
            row["average_latency_ms"] = int(Decimal(latency))
    return {
        "overview": overview,
        "models": models,
        "pricing_effective_date": PRICING_EFFECTIVE_DATE,
    }


__all__ = ["USAGE_WINDOWS", "usage_view", "window_start"]
