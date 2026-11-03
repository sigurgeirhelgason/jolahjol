import pytest

from apps.core.money import evaluate_amount, format_kr, signed_kr
from apps.core.text import fold_key, is_sort_key, normalize, split_list


@pytest.mark.parametrize(
    ("value", "base", "expected"),
    [
        ("5000+2.300", None, 7300),
        ("4.990 kr.", None, 4990),
        ("2500+990", None, 3490),
        ("+2000", 5000, 7000),
        ("−500", 5000, 4500),
        ("+2000", None, 2000),
        ("15000", 5000, 15000),
        ("", None, None),
        ("—", None, None),
        (None, None, None),
    ],
)
def test_evaluate_amount(value, base, expected):
    assert evaluate_amount(value, base) == expected


def test_format_kr():
    assert format_kr(15000) == "15.000 kr."
    assert format_kr(1234567) == "1.234.567 kr."
    assert format_kr(0) == "0 kr."
    assert format_kr(None) == "0 kr."
    assert format_kr(-500) == "−500 kr."
    assert signed_kr(2000) == "+2.000 kr."
    assert signed_kr(-12800) == "−12.800 kr."


def test_keys():
    assert normalize("  Ömmu Jóu ") == "ömmu jóu"
    assert fold_key("Elkó") == fold_key("ELKO") == fold_key("elko")
    assert split_list("Kringlan, smáralind, kringlan,") == ["Kringlan", "smáralind"]


def test_icelandic_sort_order():
    names = ["Þór", "Óskar", "Ari", "Ásdís", "Örn", "Oddur", "Æsa", "Bragi", "Una Eydís", "Una"]
    assert sorted(names, key=is_sort_key) == [
        "Ari", "Ásdís", "Bragi", "Oddur", "Óskar", "Una", "Una Eydís", "Þór", "Æsa", "Örn",
    ]  # fmt: skip
