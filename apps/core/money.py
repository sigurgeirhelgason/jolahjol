"""Upphæðir í krónum. Krónur hafa engin aukastaf og eru geymdar sem heiltölur."""

import re

_TERM = re.compile(r"[+-]?\d+")


def evaluate_amount(value: str | int | None, base: int | None = None) -> int | None:
    """Einföld samlagning í upphæðareitum.

    "5000+2.300" → 7300, "4.990 kr." → 4990, og "+2000" bætir við `base`.
    Samsvarar `evalAmount` í gamla appinu.
    """
    if value is None:
        return None
    text = re.sub(r"\s|kr\.?", "", str(value), flags=re.IGNORECASE)
    text = text.replace(".", "").replace("−", "-")
    terms = _TERM.findall(text)
    if not terms:
        return None
    total = sum(int(t) for t in terms)
    if text[:1] in "+-" and base is not None:
        return base + total
    return total


def format_kr(value: int | None) -> str:
    """15000 → „15.000 kr.“ (íslenskt snið óháð locale-stillingum)."""
    n = round(value or 0)
    digits = f"{abs(n):,}".replace(",", ".")
    return f"{'−' if n < 0 else ''}{digits} kr."


def signed_kr(value: int) -> str:
    """Með formerki: „+2.000 kr.“, „−500 kr.“."""
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return sign + format_kr(abs(value))
