"""Textareglur sem allt kerfið deilir.

Samsvara `norm` og `storeKey` í gamla appinu (gjafalistinn/index.html).
"""

import unicodedata

# Íslensk stafrófsröð; aðrir stafir raðast á eftir
_IS_ALPHABET = "aábcdðeéfghiíjklmnoópqrstuúvwxyýzþæö"
_IS_ORDER = {c: i for i, c in enumerate(_IS_ALPHABET)}


def normalize(value: str | None) -> str:
    """„ Ömmu Jóu “ → „ömmu jóu“. Notað til að bera saman nöfn fólks."""
    return (value or "").strip().casefold()


def fold_key(value: str | None) -> str:
    """Elkó/Elko/ELKO → „elko“. Notað til að bera saman búðir og staðsetningar."""
    decomposed = unicodedata.normalize("NFD", normalize(value))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def is_sort_key(value: str | None) -> tuple:
    """Röðunarlykill eftir íslenskri stafrófsröð (Á á eftir A, Þ Æ Ö síðast)."""
    return tuple(
        (_IS_ORDER.get(c, -1 if c == " " else len(_IS_ALPHABET) + ord(c)), c) for c in normalize(value)
    )


def capfirst_is(value: str) -> str:
    return value[:1].upper() + value[1:]


def split_list(value: str | None) -> list[str]:
    """„Kringlan, Smáralind,“ → ["Kringlan", "Smáralind"], án tvítekninga (fold_key)."""
    seen: dict[str, str] = {}
    for part in (value or "").split(","):
        part = part.strip()
        if part and fold_key(part) not in seen:
            seen[fold_key(part)] = part
    return list(seen.values())
