import pytest
from django.urls import reverse
from django.utils import timezone

from apps.gifts import listing
from apps.gifts.models import Gift, Idea, IdeaGiver, Person, Season
from apps.gifts.services import gifts as gift_services
from apps.gifts.services import people, stores
from apps.gifts.services.billing import season_billing
from apps.households.models import Membership
from tests.factories import (
    GiftFactory,
    IdeaFactory,
    MembershipFactory,
    PersonFactory,
    SeasonFactory,
    StoreFactory,
    giver,
)

pytestmark = pytest.mark.django_db

THIS_YEAR = timezone.localdate().year
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def member():
    return MembershipFactory(role=Membership.Role.OWNER)


@pytest.fixture
def home(member):
    return member.household


@pytest.fixture
def season(home):
    return SeasonFactory(household=home, year=THIS_YEAR, budget=100000)


@pytest.fixture
def client(client, member):
    client.force_login(member.user)
    return client


def _gift(season, name="Hugi", group="born", **kwargs):
    person = PersonFactory(household=season.household, name=name, group=group)
    return GiftFactory(season=season, person=person, **kwargs)


def url(name, *args):
    return reverse(f"gifts:{name}", args=args)


# ---------- Síða og síur ----------


def test_household_root_redirects_to_this_year_and_creates_it(client, home):
    response = client.get(url("list", home.slug))
    assert response.url == url("season", home.slug, THIS_YEAR)
    assert Season.objects.filter(household=home, year=THIS_YEAR).exists()


def test_list_page_renders_groups_rows_and_summary(client, home, season):
    gift = _gift(season, plan=15000)
    IdeaFactory(gift=gift, text="legó")
    response = client.get(url("season", home.slug, THIS_YEAR))
    assert response.status_code == 200
    html = response.text
    assert f'id="gift-{gift.pk}"' in html
    assert "legó" in html and "15.000 kr." in html
    assert "Börn" in html
    assert 'id="summary"' in html


def test_htmx_filter_request_returns_only_sections(client, home, season):
    _gift(season, "Hugi", bought=True)
    _gift(season, "Una", group="born")
    response = client.get(
        url("season", home.slug, THIS_YEAR) + "?syna=eftir", HTTP_HX_TARGET="sections", **HX
    )
    assert 'id="summary"' not in response.text
    assert "Una" in response.text and "Hugi" not in response.text
    assert 'id="filter-tabs" hx-swap-oob="true"' in response.text


def test_search_matches_giver_names_and_stores(season):
    gift = _gift(season, "Hugi")
    idea = IdeaFactory(gift=gift, text="púsl", store=StoreFactory(household=season.household, name="Elkó"))
    giver(idea, PersonFactory(household=season.household, name="Amma Jóa"))
    _gift(season, "Una")
    for q in ("amma", "elko", "PÚSL"):
        gl = listing.build_list(season, listing.ListState(q=q))
        names = [r.person.name for s in gl.sections for r in s.rows]
        assert names == ["Hugi"], q


def test_store_filter_and_undecided(season):
    gift = _gift(season, "Hugi")
    IdeaFactory(gift=gift, store=StoreFactory(household=season.household, name="Epal"))
    _gift(season, "Una")
    by_store = listing.build_list(season, listing.ListState(store="epal"))
    undecided = listing.build_list(season, listing.ListState(store=listing.NO_STORE))
    assert [r.person.name for s in by_store.sections for r in s.rows] == ["Hugi"]
    assert [r.person.name for s in undecided.sections for r in s.rows] == ["Una"]
    unknown = listing.build_list(season, listing.ListState(store="ekki-til"))
    assert unknown.state.store == listing.ALL_STORES


def test_sorting_by_name_uses_icelandic_order(season):
    for name in ("Örn", "Ásdís", "Bragi", "Anna"):
        _gift(season, name, group="vinir")
    gl = listing.build_list(season, listing.ListState(sort="nafn"))
    assert [r.person.name for r in gl.section("vinir").rows] == ["Anna", "Ásdís", "Bragi", "Örn"]


def test_empty_annad_group_is_hidden_unless_it_has_gifts(season):
    groups = [s.group for s in listing.build_list(season, listing.ListState()).sections]
    assert "annad" not in groups and "born" in groups


def test_history_line_shows_previous_years(season):
    gift = _gift(season, "Hugi")
    old = SeasonFactory(household=season.household, year=THIS_YEAR - 1)
    IdeaFactory(gift=GiftFactory(season=old, person=gift.person), text="Andrés áskrift", picked=True)
    row = listing.build_row(gift)
    assert row.history == [(THIS_YEAR - 1, "Andrés áskrift")]


# ---------- Breytingar í línu ----------


def test_bought_with_known_price_saves_and_returns_row_with_oob(client, home, season):
    gift = _gift(season)
    IdeaFactory(gift=gift, picked=True, price=5000)
    response = client.post(url("bought", home.slug, gift.pk), {"bought": "on"}, **HX)
    gift.refresh_from_db()
    assert gift.bought
    assert f'id="gift-{gift.pk}"' in response.text
    assert 'id="summary" hx-swap-oob="true"' in response.text
    assert 'id="group-born-head" hx-swap-oob="true"' in response.text


def test_bought_without_price_asks_and_does_not_save(client, home, season):
    gift = _gift(season)
    response = client.post(url("bought", home.slug, gift.pk), {"bought": "on"}, **HX)
    gift.refresh_from_db()
    assert not gift.bought
    assert response["HX-Retarget"] == "#modal-body"
    assert "Hvað kostaði gjöfin?" in response.text
    row = response.text.split(f'id="gift-{gift.pk}"')[1]
    assert row.startswith(' hx-swap-oob="true"')
    checkbox = row.split('<input type="checkbox"')[1].split(">")[0]
    assert "checked" not in checkbox


def test_price_dialog_adds_amount_or_skips(client, home, season):
    gift = _gift(season)
    client.post(url("price", home.slug, gift.pk), {"amount": "2500+990"}, **HX)
    gift.refresh_from_db()
    assert (gift.bought, gift.manual_price, gift.actual_price) == (True, 3490, 3490)

    other = _gift(season, "Una")
    response = client.post(url("price", home.slug, other.pk), {"skip": "1"}, **HX)
    other.refresh_from_db()
    assert other.bought and other.manual_price is None
    assert "closeModal" in response["HX-Trigger-After-Settle"]


def test_price_dialog_rejects_garbage(client, home, season):
    gift = _gift(season)
    response = client.post(url("price", home.slug, gift.pk), {"amount": "mikið"}, **HX)
    assert response.status_code == 422
    assert "Skrifaðu upphæð" in response.text


def test_unchecking_bought_clears_manual_price(client, home, season):
    gift = _gift(season, bought=True, manual_price=4000)
    client.post(url("bought", home.slug, gift.pk), {}, **HX)
    gift.refresh_from_db()
    assert not gift.bought and gift.manual_price is None


def test_plan_supports_plus_to_add(client, home, season):
    gift = _gift(season, plan=15000)
    client.post(url("plan", home.slug, gift.pk), {"plan": "+2.000"}, **HX)
    gift.refresh_from_db()
    assert gift.plan == 17000
    client.post(url("plan", home.slug, gift.pk), {"plan": ""}, **HX)
    gift.refresh_from_db()
    assert gift.plan is None


def test_add_and_remove_ideas_inline(client, home, season):
    gift = _gift(season)
    client.post(url("idea_add", home.slug, gift.pk), {"text": "sokkar, spil"}, **HX)
    assert list(gift.ideas.values_list("text", flat=True)) == ["sokkar", "spil"]
    client.post(url("idea_remove", home.slug, gift.ideas.first().pk), **HX)
    assert list(gift.ideas.values_list("text", flat=True)) == ["spil"]


def test_row_disappears_when_it_no_longer_matches_filter(client, home, season):
    gift = _gift(season)
    IdeaFactory(gift=gift, picked=True, price=1000)
    response = client.post(url("bought", home.slug, gift.pk), {"bought": "on", "syna": "eftir"}, **HX)
    assert f'id="gift-{gift.pk}" ' not in response.text.split('id="group-born-head"')[0]


def test_delete_shows_undo_toast_and_restore_brings_it_back(client, home, season):
    gift = _gift(season)
    response = client.post(url("delete", home.slug, gift.pk), **HX)
    gift.refresh_from_db()
    assert gift.deleted_at is not None
    assert url("restore", home.slug, gift.pk) in response.text
    client.post(url("restore", home.slug, gift.pk), **HX)
    gift.refresh_from_db()
    assert gift.deleted_at is None


def test_budget_accepts_formatted_amounts(client, home, season):
    response = client.post(url("budget", home.slug, THIS_YEAR), {"budget": "160.000 kr."}, **HX)
    season.refresh_from_db()
    assert season.budget == 160000
    assert "160.000 kr." in response.text


# ---------- Gluggar ----------


def test_new_gift_dialog_creates_person_gift_ideas_and_store(client, home, season):
    response = client.get(url("gift_new", home.slug, THIS_YEAR), **HX)
    assert "Bæta við nýrri gjöf eða hugmynd" in response.text
    response = client.post(
        url("gift_new", home.slug, THIS_YEAR),
        {
            "name": "Mahsa",
            "group": "vinir",
            "plan": "3.000",
            "ideas": "vasi, kerti",
            "store": "",
            "link": "https://www.epal.is/vasi",
        },
        **HX,
    )
    assert response["HX-Retarget"] == "#sections"
    gift = Gift.objects.get(person__name="Mahsa")
    sections = response.text.split('id="summary"')[0]
    assert f'id="gift-{gift.pk}">' in sections  # línan er inni í listanum, ekki OOB
    assert (gift.plan, gift.person.group) == (3000, "vinir")
    assert [i.text for i in gift.ideas.all()] == ["vasi", "kerti"]
    assert [s.name for s in gift.stores.all()] == ["Epal"]


def test_new_gift_for_someone_already_on_list_is_rejected(client, home, season):
    _gift(season, "Hugi")
    response = client.post(
        url("gift_new", home.slug, THIS_YEAR),
        {"name": "hugi", "group": "born", "ideas": ""},
        **HX,
    )
    assert response.status_code == 422
    assert "þegar á listanum" in response.text


def test_edit_gift_keeps_picked_ideas_and_renames_person(client, home, season):
    gift = _gift(season, "Hugi")
    kept = IdeaFactory(gift=gift, text="legó", picked=True, price=5000)
    IdeaFactory(gift=gift, text="bók")
    client.post(
        url("gift_edit", home.slug, gift.pk),
        {"name": "Hugi Snær", "group": "born", "ideas": "Legó, spil", "plan": ""},
        **HX,
    )
    gift.refresh_from_db()
    kept.refresh_from_db()
    assert gift.person.name == "Hugi Snær"
    assert [(i.text, i.picked) for i in gift.ideas.all()] == [("Legó", True), ("spil", False)]
    assert kept.price == 5000


def test_renaming_person_with_other_years_makes_new_recipient(season):
    gift = _gift(season, "Ásdís")
    old = SeasonFactory(household=season.household, year=THIS_YEAR - 1)
    GiftFactory(season=old, person=gift.person)
    original = gift.person
    new = people.resolve_recipient(gift, "Ásdís frá börnum")
    assert new.pk != original.pk
    assert Person.objects.get(pk=original.pk).name == "Ásdís"  # fyrri ár óbreytt
    gift.refresh_from_db()
    assert gift.person == new


def test_renaming_person_used_only_here_renames(season):
    gift = _gift(season, "Helgi")
    person = people.resolve_recipient(gift, "Helgi Hafþór")
    assert person.pk == gift.person_id and person.name == "Helgi Hafþór"


def test_renaming_to_existing_person_moves_gift_and_drops_orphan(season):
    gift = _gift(season, "Ömmu")
    amma = PersonFactory(household=season.household, name="Amma")
    orphan = gift.person
    assert people.resolve_recipient(gift, "amma") == amma
    assert not Person.objects.filter(pk=orphan.pk).exists()


def test_idea_dialog_saves_givers_and_splits_billing_equally(client, home, season):
    gift = _gift(season, "Hugi")
    idea = IdeaFactory(gift=gift, text="púsl")
    response = client.get(url("idea", home.slug, idea.pk), **HX)
    assert "Frá hverjum?" in response.text
    client.post(
        url("idea", home.slug, idea.pk),
        {
            "text": "púsl",
            "givers": ["Amma Jóa", "Afi", "okkur"],
            "for_other": "on",
            "price": "6.000",
            "picked": "on",
            "store": "Spilavinir",
            "locations": "Kringlan, Smáralind",
        },
        **HX,
    )
    idea.refresh_from_db()
    links = {link.person.name: link.share for link in idea.giver_links.all()}
    assert links == {"Amma Jóa": None, "Afi": None}  # „okkur“ er ekki gefandi
    assert idea.for_other and idea.picked and idea.price == 6000
    gift.refresh_from_db()
    assert gift.bought and gift.actual_price is None  # allt rukkað, ekkert á okkur
    payers = {p.person.name: p.unpaid for p in season_billing(season)}
    assert payers == {"Amma Jóa": 3000, "Afi": 3000}  # alltaf jöfn skipting
    assert sorted(loc.name for loc in idea.store.locations.all()) == ["Kringlan", "Smáralind"]
    # Nýir gefendur verða ekki viðtakendur
    assert not Person.objects.recipients().filter(name="Amma Jóa").exists()


def test_idea_without_givers_cannot_be_for_other(client, home, season):
    idea = IdeaFactory(gift=_gift(season), text="bók")
    client.post(url("idea", home.slug, idea.pk), {"text": "bók", "for_other": "on", "paid": "on"}, **HX)
    idea.refresh_from_db()
    assert not idea.for_other


def test_people_search_offers_to_create_unknown_name(client, home, season):
    PersonFactory(household=home, name="Amma Jóa")
    response = client.get(url("people_search", home.slug) + "?q=amm", **HX)
    assert 'data-name="Amma Jóa"' in response.text and "Búa til" in response.text
    response = client.get(url("people_search", home.slug) + "?q=amma jóa", **HX)
    assert "Búa til" not in response.text
    assert "Búa til" not in client.get(url("people_search", home.slug) + "?q=okkur", **HX).text


def test_new_season_copies_christmas_recipients(client, home, season):
    _gift(season, "Hugi", plan=15000)
    _gift(season, "Kennarar", group="vinna")
    Person.objects.filter(name="Kennarar").update(give_christmas=False)
    response = client.post(url("new_season", home.slug), {"year": THIS_YEAR + 1, "copy": "on"}, **HX)
    assert response["HX-Redirect"] == url("season", home.slug, THIS_YEAR + 1)
    new = Season.objects.get(household=home, year=THIS_YEAR + 1)
    assert [(g.person.name, g.plan) for g in new.gifts.all()] == [("Hugi", 15000)]
    assert new.budget == 100000


# ---------- Læst ár ----------


def test_past_year_is_locked_until_unlocked(client, home):
    past = SeasonFactory(household=home, year=THIS_YEAR - 1)
    gift = _gift(past)
    page = client.get(url("season", home.slug, past.year))
    assert "listinn er læstur" in page.text
    assert client.post(url("plan", home.slug, gift.pk), {"plan": "1"}, **HX).status_code == 403
    assert client.get(url("gift_edit", home.slug, gift.pk), **HX).status_code == 403

    client.post(url("unlock", home.slug, past.year), **HX)
    past.refresh_from_db()
    assert past.unlocked_until > timezone.now()
    assert client.post(url("plan", home.slug, gift.pk), {"plan": "1"}, **HX).status_code == 200


def test_cannot_reach_gifts_of_other_households(client, home, season):
    stranger_gift = GiftFactory()
    stranger_idea = IdeaFactory(gift=stranger_gift)
    for name, pk in (
        ("bought", stranger_gift.pk),
        ("plan", stranger_gift.pk),
        ("idea_remove", stranger_idea.pk),
    ):
        assert client.post(url(name, home.slug, pk), {"bought": "on"}, **HX).status_code == 404
    assert client.get(url("idea", home.slug, stranger_idea.pk), **HX).status_code == 404
    assert Idea.objects.filter(pk=stranger_idea.pk).exists()


# ---------- Framsetning ----------


def test_pace_and_hero_texts():
    summary = type("S", (), {"todo": 4, "days_left": 2})()
    assert listing.pace_text(summary) == "~2 gjafir á dag"
    summary = type("S", (), {"todo": 2, "days_left": 7})()
    assert listing.pace_text(summary) == "~1 gjöf á 3,5 daga"
    season = Season(year=2026)
    assert listing.hero_texts(season, 1)[1] == "Jólin koma á morgun!"
    assert listing.hero_texts(season, -5)[1] == "Jólin 2026"


def test_tree_fill():
    assert listing.Tree(0).fill_y == 245
    assert listing.Tree(1).fill_y == 35 and listing.Tree(1).lit
    assert listing.Tree(0.5).line


def test_save_idea_marks_all_givers_paid(season):
    idea = IdeaFactory(gift=_gift(season))
    data = gift_services.IdeaData(
        text="x", givers=["A", "B"], for_other=True, paid=True,
        note="", store="", locations="", price=1001, link="", picked=True,
    )  # fmt: skip
    gift_services.save_idea(idea, data)
    assert list(IdeaGiver.objects.filter(idea=idea).values_list("paid", flat=True)) == [True, True]


# ---------- Ný lína og einstaklingsgluggi ----------


def test_new_row_form_is_rendered_for_group(client, home, season):
    response = client.get(url("new_row", home.slug, THIS_YEAR) + "?flokkur=born", **HX)
    assert 'class="row gift new-row"' in response.text
    assert 'name="group" value="born"' in response.text


def test_new_row_creates_person_and_gift_and_returns_row(client, home, season):
    response = client.post(
        url("new_row", home.slug, THIS_YEAR),
        {"name": "Óskar Birnir", "group": "born", "plan": "15.000"},
        **HX,
    )
    gift = Gift.objects.get(person__name="Óskar Birnir", season=season)
    assert (gift.plan, gift.person.group, gift.person.give_christmas) == (15000, "born", True)
    assert f'id="gift-{gift.pk}"' in response.text
    assert 'id="group-born-head" hx-swap-oob="true"' in response.text


def test_new_row_rejects_name_already_on_list(client, home, season):
    _gift(season, "Hugi")
    response = client.post(url("new_row", home.slug, THIS_YEAR), {"name": "hugi", "group": "born"}, **HX)
    assert response.status_code == 422
    assert "þegar á listanum" in response.text and "new-row" in response.text


def test_person_dialog_saves_birthday_and_gift_flags(client, home, season):
    gift = _gift(season, "Hugi")
    old = SeasonFactory(household=home, year=THIS_YEAR - 1)
    IdeaFactory(
        gift=GiftFactory(season=old, person=gift.person, bought=True), text="Andrés áskrift", picked=True
    )
    older = SeasonFactory(household=home, year=THIS_YEAR - 2)
    IdeaFactory(gift=GiftFactory(season=older, person=gift.person), text="aldrei keypt")
    page = client.get(url("person", home.slug, gift.person_id) + f"?ar={THIS_YEAR}", **HX)
    assert "Andrés áskrift" in page.text and f'name="ar" value="{THIS_YEAR}"' in page.text
    assert "aldrei keypt" not in page.text  # fyrri gjafir: aðeins keyptar
    response = client.post(
        url("person", home.slug, gift.person_id),
        {"name": "Hugi", "group": "born", "birthday": "2016-05-04", "give_birthday": "on", "ar": THIS_YEAR},
        **HX,
    )
    person = Person.objects.get(pk=gift.person_id)
    assert str(person.birthday) == "2016-05-04"
    assert person.give_birthday and not person.give_christmas
    assert response["HX-Retarget"] == "#sections"


def test_person_dialog_asks_before_merging(client, home, season):
    gift = _gift(season, "Ömmu")
    amma = PersonFactory(household=home, name="Amma", group="fjolskylda")
    data = {"name": "Amma", "group": "fjolskylda", "give_christmas": "on", "ar": THIS_YEAR}
    response = client.post(url("person", home.slug, gift.person_id), data, **HX)
    assert response.status_code == 422 and "er þegar til" in response.text
    assert Person.objects.filter(pk=gift.person_id).exists()
    client.post(url("person", home.slug, gift.person_id), {**data, "merge": "on"}, **HX)
    gift.refresh_from_db()
    assert gift.person == amma
    assert not Person.objects.filter(name="Ömmu").exists()


def test_person_dialog_is_scoped_to_household(client, home):
    stranger = PersonFactory()
    assert client.get(url("person", home.slug, stranger.pk), **HX).status_code == 404


def test_adding_same_idea_twice_is_ignored(client, home, season):
    gift = _gift(season)
    client.post(url("idea_add", home.slug, gift.pk), {"text": "spil"}, **HX)
    client.post(url("idea_add", home.slug, gift.pk), {"text": "Spil, bók, bók"}, **HX)
    assert list(gift.ideas.values_list("text", flat=True)) == ["spil", "bók"]


# ---------- Búðargluggi ----------


def test_store_dialog_renames_and_sets_locations(client, home, season):
    gift = _gift(season)
    store = StoreFactory(household=home, name="elko")
    IdeaFactory(gift=gift, store=store)
    page = client.get(url("store", home.slug, store.pk) + f"?ar={THIS_YEAR}", **HX)
    assert 'value="elko"' in page.text
    response = client.post(
        url("store", home.slug, store.pk),
        {"name": "Elko", "new_locations": "Kringlan, Smáralind", "ar": THIS_YEAR},
        **HX,
    )
    store.refresh_from_db()
    assert store.name == "Elko"
    assert sorted(loc.name for loc in store.locations.all()) == ["Kringlan", "Smáralind"]
    assert response["HX-Retarget"] == "#sections"
    # Hakað af: Smáralind fer
    client.post(
        url("store", home.slug, store.pk), {"name": "Elko", "locations": ["Kringlan"], "ar": THIS_YEAR}, **HX
    )
    assert [loc.name for loc in store.locations.all()] == ["Kringlan"]


def test_store_dialog_asks_before_merging(client, home, season):
    gift = _gift(season)
    old = StoreFactory(household=home, name="Hagkaup Skeifan")
    target = StoreFactory(household=home, name="Hagkaup")
    idea = IdeaFactory(gift=gift, store=old)
    data = {"name": "hagkaup", "locations": ["Skeifan"], "ar": THIS_YEAR}
    response = client.post(url("store", home.slug, old.pk), data, **HX)
    assert response.status_code == 422 and "er þegar til" in response.text
    client.post(url("store", home.slug, old.pk), {**data, "merge": "on"}, **HX)
    idea.refresh_from_db()
    assert idea.store == target
    assert [loc.name for loc in target.locations.all()] == ["Skeifan"]


def test_store_dialog_is_scoped_to_household(client, home):
    assert client.get(url("store", home.slug, StoreFactory().pk), **HX).status_code == 404


def test_store_dialog_offers_default_locations_first(client, home, season):
    store = StoreFactory(household=home, name="Elko")
    IdeaFactory(gift=_gift(season), store=store)
    stores.set_locations(store, "Netverslun, kringlan")
    page = client.get(url("store", home.slug, store.pk), **HX).text
    order = [
        n for n in ("Kringlan", "Smáralind", "Skeifan", "Glerártorg", "Laugavegur", "Netverslun") if n in page
    ]
    assert order == ["Kringlan", "Smáralind", "Skeifan", "Glerártorg", "Laugavegur", "Netverslun"]
    assert sorted(page.index(n) for n in order) == [page.index(n) for n in order]
    assert page.count('value="Kringlan" checked') == 1  # „kringlan“ telst sami staður
    assert 'value="Smáralind" checked' not in page
