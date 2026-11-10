"""Reglur um heimili, aðild og boð.

Views athuga hvort notandinn má gera hlutinn (eigandi eða meðlimur); hér er gætt að því að
heimili standi aldrei eftir án eiganda og að boð gildi aðeins einu sinni.

Hver notandi er einstaklingur á listanum (`Membership.person`) og sér ekki hvað aðrir ætla að
gefa honum (apps/gifts/services/privacy.py). Einstaklingurinn heitir það sem hinir kalla hann
(„Dísa“); nafnið sem notandinn skráir sjálfur („Ásdís“) er `user.name` og birtist honum.
"""

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from .models import Household, Invite, Membership

logger = logging.getLogger(__name__)

_IS_TRANSLIT = str.maketrans(
    {"þ": "th", "Þ": "Th", "ð": "d", "Ð": "D", "æ": "ae", "Æ": "Ae", "ö": "o", "Ö": "O"}
)


class HouseholdError(Exception):
    """Aðgerð sem brýtur reglu; skilaboðin eru birt notandanum."""


class InvalidName(HouseholdError):
    """Nafnið sem notandinn skrifaði gengur ekki (tómt eða annar notandi er það á listanum)."""


def unique_slug(name: str) -> str:
    """„Heimilið á Þórsgötu“ → „heimilid-a-thorsgotu“, með -2, -3 … ef slóðin er tekin."""
    base = slugify(name.translate(_IS_TRANSLIT))[:40].strip("-") or "heimili"
    slug, n = base, 1
    while Household.objects.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


def _save_user_name(user, name: str) -> None:
    name = name.strip()[:150]
    if name and name != user.name:
        user.name = name
        user.save(update_fields=["name"])


def _link(membership: Membership, person) -> None:
    """Tengir aðild einstaklingi og sér til þess að hann eigi línu (jólagjöf) á árinu."""
    from apps.gifts.services.gifts import ensure_christmas_gift

    membership.person = person
    membership.save(update_fields=["person"])
    if person.give_christmas:
        ensure_christmas_gift(person)


def _person_named(household: Household, name: str):
    """Einstaklingur með þessu nafni í Fjölskyldu (búinn til ef þarf), sem enginn notandi er."""
    from apps.gifts.models import Group
    from apps.gifts.services.people import find_or_create

    name = name.strip()[:100]
    if not name:
        raise InvalidName(_("Skrifaðu nafnið þitt."))
    person = find_or_create(household, name, Group.FJOLSKYLDA)
    if Membership.objects.filter(person=person).exists():
        raise InvalidName(
            _("Einhver annar í heimilinu er þegar „%(name)s“ á listanum. Skrifaðu nafnið aðeins öðruvísi.")
            % {"name": person.name}
        )
    return person


@transaction.atomic
def create_household(user, name: str, your_name: str = "") -> Household:
    """Nýtt heimili; sá sem stofnar það verður eigandi og einstaklingur í Fjölskyldu."""
    your_name = your_name.strip() or user.name
    _save_user_name(user, your_name)
    household = Household.objects.create(name=name.strip(), slug=unique_slug(name))
    membership = Membership.objects.create(user=user, household=household, role=Membership.Role.OWNER)
    if your_name:
        _link(membership, _person_named(household, your_name))
    return household


def rename_household(household: Household, name: str) -> None:
    # Slóðin breytist ekki, svo bókamerki og opnir flipar haldi áfram að virka
    household.name = name.strip()
    household.save(update_fields=["name"])


def _check_person(household: Household, person, membership: Membership | None = None) -> None:
    if person is None:
        return
    if person.household_id != household.pk:
        raise HouseholdError(_("Þessi einstaklingur er ekki í heimilinu."))
    taken = Membership.objects.filter(person=person)
    if membership is not None:
        taken = taken.exclude(pk=membership.pk)
    if taken.exists():
        raise HouseholdError(_("Annar notandi er þegar tengdur „%(name)s“.") % {"name": person.name})


def create_invite(household: Household, by, person=None, email: str = "") -> Invite:
    """Boð í heimilið, sent í pósti á `email` (ef gefið). Hlekkinn má líka afrita úr lista virkra boða.

    Með `person` tengist sá sem þiggur boðið þeim einstaklingi á listanum. Einstaklingur hefur
    aðeins eitt virkt boð: nýtt boð kemur í stað þess eldra.
    """
    email = email.strip()
    if email:
        try:
            validate_email(email)
        except ValidationError as exc:
            raise HouseholdError(_("Netfangið er ekki gilt.")) from exc
    with transaction.atomic():
        _check_person(household, person)
        if person is not None:
            household.invites.usable().filter(person=person).delete()
        invite = Invite.objects.create(household=household, created_by=by, person=person, email=email)
    # Fari pósturinn ekki er boðið samt til og hlekkinn má afrita (`invite.mailed` segir til)
    invite.mailed = send_invite(invite) if email else False
    return invite


def invite_url(invite: Invite) -> str:
    return settings.SITE_URL + reverse("households:invite_accept", args=[invite.token])


def send_invite(invite: Invite) -> bool:
    """Sendir boðið í pósti. Skilar False ef það tókst ekki (villan er skráð, t.d. í Sentry)."""
    ctx = {"invite": invite, "url": invite_url(invite), "days": Invite.VALID_DAYS}
    subject = render_to_string("households/email/invite_subject.txt", ctx).strip()
    body = render_to_string("households/email/invite.txt", ctx)
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [invite.email])
    except Exception:
        logger.exception("Boð fór ekki í pósti á %s", invite.email)
        return False
    return True


def invite_for(person) -> Invite | None:
    """Virkt boð einstaklings (einstaklingsglugginn)."""
    return Invite.objects.usable().filter(person=person).order_by("-created_at").first()


@transaction.atomic
def set_person(membership: Membership, person, *, by) -> None:
    """Hvaða einstaklingur á listanum notandinn er (None = enginn).

    Enginn breytir eigin tengingu eftir að hún er komin, annars gæti hann aftengt sig og séð hvað
    aðrir ætla að gefa honum. Ótengdur notandi velur sjálfur einu sinni (`claim_person`).
    """
    if membership.user_id == by.pk and membership.person_id is not None:
        raise HouseholdError(_("Þú getur ekki breytt því hver þú ert á listanum. Biddu annan eiganda."))
    _check_person(membership.household, person, membership)
    if person is None:
        membership.person = None
        membership.save(update_fields=["person"])
    else:
        _link(membership, person)
        _keep_what_was_seen(person)


def _keep_what_was_seen(person) -> None:
    """Meðlimur sem tengist núna hefur séð hugmyndirnar á línunni sinni: þær verða hans eigin
    (sjást áfram, en ekki staða þeirra). Á aðeins við þetta ár og næstu, ekki liðin ár.

    Nýr notandi úr boði hefur ekkert séð, svo þetta er ekki gert í `accept_invite`.
    """
    from apps.gifts.models import Idea

    Idea.objects.filter(
        gift__person=person, gift__deleted_at__isnull=True, gift__season__year__gte=timezone.localdate().year
    ).update(wish=True)


@transaction.atomic
def claim_person(membership: Membership, *, person=None, name: str = "") -> None:
    """„Hver ert þú á listanum?“: ótengdur notandi velur einstakling eða skrifar nýtt nafn."""
    if membership.person_id is not None:
        raise HouseholdError(_("Þú ert þegar á listanum."))
    if person is None:
        person = _person_named(membership.household, name)
    set_person(membership, person, by=membership.user)


def revoke_invite(invite: Invite) -> None:
    invite.delete()


@transaction.atomic
def accept_invite(token: str, user, name: str = "") -> Membership:
    """Boð þegið. `name` er nafnið sem notandinn skrifar sjálfur; það birtist honum.

    Boð til einstaklings tengir notandann honum og nafnið á listanum helst („Dísa“). Almennt boð
    setur notandann á listann í Fjölskyldu undir nafninu sem hann skrifar.
    """
    invite = Invite.objects.select_for_update().filter(token=token).first()
    if invite is None:
        raise HouseholdError(_("Þetta boð er ekki til eða hefur verið afturkallað."))
    existing = Membership.objects.filter(household=invite.household, user=user).first()
    if existing:
        # Boðið er ekki notað upp ef viðkomandi er þegar með, svo hægt sé að senda það öðrum
        return existing
    if invite.accepted_at:
        raise HouseholdError(_("Þetta boð hefur þegar verið notað. Biddu um nýjan hlekk."))
    if invite.expires_at <= timezone.now():
        raise HouseholdError(_("Þetta boð er útrunnið. Biddu um nýjan hlekk."))
    name = name.strip() or user.name
    if not name:
        raise InvalidName(_("Skrifaðu nafnið þitt."))
    # Einstaklingurinn gæti hafa verið tengdur öðrum eftir að boðið var búið til
    person = invite.person
    if person is None or Membership.objects.filter(person=person).exists():
        person = _person_named(invite.household, name)
    _save_user_name(user, name)
    invite.accepted_by = user
    invite.accepted_at = timezone.now()
    invite.save(update_fields=["accepted_by", "accepted_at"])
    membership = Membership.objects.create(household=invite.household, user=user, role=Membership.Role.MEMBER)
    _link(membership, person)
    return membership


def _owner_count(household: Household) -> int:
    return household.memberships.filter(role=Membership.Role.OWNER).count()


@transaction.atomic
def set_role(membership: Membership, role: str) -> None:
    if role not in Membership.Role.values:
        raise HouseholdError(_("Óþekkt hlutverk."))
    if (
        membership.role == Membership.Role.OWNER
        and role != Membership.Role.OWNER
        and _owner_count(membership.household) == 1
    ):
        raise HouseholdError(_("Heimilið verður að hafa að minnsta kosti einn eiganda."))
    membership.role = role
    membership.save(update_fields=["role"])


@transaction.atomic
def remove_member(membership: Membership, by) -> None:
    if membership.user_id == by.pk:
        raise HouseholdError(_("Notaðu „Yfirgefa heimili“ til að fara úr heimilinu."))
    if membership.role == Membership.Role.OWNER and _owner_count(membership.household) == 1:
        raise HouseholdError(_("Heimilið verður að hafa að minnsta kosti einn eiganda."))
    membership.delete()


@transaction.atomic
def leave(membership: Membership) -> None:
    household = membership.household
    if household.memberships.count() == 1:
        raise HouseholdError(_("Þú ert eini meðlimur heimilisins. Eyddu heimilinu í staðinn."))
    if membership.role == Membership.Role.OWNER and _owner_count(household) == 1:
        raise HouseholdError(_("Gerðu einhvern annan að eiganda áður en þú ferð."))
    membership.delete()


def delete_household(household: Household) -> None:
    # Gift.person er PROTECT, svo gjafir fara á undan fólkinu
    from apps.gifts.models import Gift

    with transaction.atomic():
        Gift.objects.filter(season__household=household).delete()
        household.delete()
