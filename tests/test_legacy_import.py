"""Innflutningur raunverulegs afrits úr gamla appinu.

`fixtures/legacy_v2.json` var búið til úr gjafalistinn/index.html (Excel-gögnin og raunhæf
notkun ofan á þau) og `legacy_v2_totals.json` eru tölurnar sem gamla appið reiknaði.
"""

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.gifts.models import Gift, IdeaGiver, Person, Season, Store
from apps.gifts.services import billing, summary
from apps.households.models import Household, Membership

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.django_db


@pytest.fixture
def imported():
    out = StringIO()
    call_command(
        "import_legacy",
        FIXTURES / "legacy_v2.json",
        household="okkar",
        create="Heimilið okkar",
        owner="sigurgeir@example.com",
        stdout=out,
    )
    return Household.objects.get(slug="okkar"), out.getvalue()


def test_totals_match_old_app(imported):
    household, _ = imported
    expected = json.loads((FIXTURES / "legacy_v2_totals.json").read_text(encoding="utf-8"))
    for year, old in expected.items():
        s = summary.season_summary(Season.objects.get(household=household, year=int(year)))
        assert (s.budget, s.total_plan, s.spent, s.owed) == (
            old["budget"],
            old["plan"],
            old["spent"],
            old["owed"],
        ), year
        # 2026 hafði tvær gjafir til Braga sem sameinast í eina
        merged = 1 if year == "2026" else 0
        assert (s.count, s.done) == (old["count"] - merged, old["done"] - merged), year


def test_owner_and_report(imported):
    household, out = imported
    assert Membership.objects.get(household=household).role == Membership.Role.OWNER
    assert "Tvær gjafir sameinaðar: Bragi (2026)" in out
    assert "– Afa Braga" in out and "– Ömmu Jóu" in out


def test_givers_are_people_and_hidden_as_recipients(imported):
    household, _ = imported
    amma = Person.objects.get(household=household, key="ömmu jóu")
    assert amma not in Person.objects.recipients()
    # „ömmu jóu“ og „Ömmu Jóu“ eru sami gefandi; „okkur“ verður enginn gefandi
    assert IdeaGiver.objects.filter(person=amma).count() == 2
    assert not Person.objects.filter(household=household, key="okkur").exists()
    [payer_amma, payer_afi] = sorted(
        billing.season_billing(Season.objects.get(household=household, year=2026)),
        key=lambda p: p.person.name != "Ömmu Jóu",
    )
    assert payer_amma.unpaid == 3500 and len(payer_amma.lines) == 2
    assert payer_afi.unpaid == 0 and payer_afi.total == 4000


def test_stores_are_canonical_and_keep_locations(imported):
    household, _ = imported
    names = set(Store.objects.filter(household=household).values_list("name", flat=True))
    assert "Elko" in names and "Elkó" not in names  # STORE_NAMES vinnur
    assert "Vínbúðin" in names and "Netverslun" in names  # samheiti
    assert not names & {"jóla Keanu", "mini Le Creuset", "úr, bók"}  # ekki búðir
    elko = Store.objects.get(household=household, key="elko")
    assert sorted(loc.name for loc in elko.locations.all()) == ["Netverslun", "Smáralind"]


def test_people_details(imported):
    household, _ = imported
    hugi = Person.objects.get(household=household, name="Hugi")
    assert hugi.group == "born" and str(hugi.birthday) == "2016-05-17"
    assert Person.objects.get(household=household, name="Mahsa").give_christmas is False
    # Gamla Excel-búðin „jóla Keanu“ varð keypt hugmynd
    sigurgeir_2025 = Gift.objects.get(person__name="Sigurgeir", season__year=2025)
    assert sigurgeir_2025.ideas.filter(text="jóla Keanu", picked=True).exists()


def test_refuses_to_import_twice_without_replace(imported):
    with pytest.raises(CommandError):
        call_command("import_legacy", FIXTURES / "legacy_v2.json", household="okkar", stdout=StringIO())
    call_command(
        "import_legacy", FIXTURES / "legacy_v2.json", household="okkar", replace=True, stdout=StringIO()
    )
    assert Gift.objects.alive().filter(season__year=2026).count() == 24


def test_rejects_unknown_format(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"version": 1, "years": {}}', encoding="utf-8")
    with pytest.raises(CommandError):
        call_command("import_legacy", bad, household="x", create="X", stdout=StringIO())
