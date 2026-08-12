"""Personal settings validation used by the rendered account page."""

from project_recovery.config import ALLOWED_MODELS, ALLOWED_REASONING_EFFORTS

THEMES = ("system", "light", "dark")


def validated_settings(model: str, reasoning_effort: str, theme: str) -> dict[str, str] | None:
    """Accept only the approved model, effort, and local presentation choices."""
    if model not in ALLOWED_MODELS or reasoning_effort not in ALLOWED_REASONING_EFFORTS:
        return None
    if theme not in THEMES:
        return None
    return {"model": model, "reasoning_effort": reasoning_effort, "theme": theme}
