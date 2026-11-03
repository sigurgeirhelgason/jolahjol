"""Reglur um heimili, aðild og boð.

Views athuga hvort notandinn má gera hlutinn (eigandi eða meðlimur); hér er gætt að því að
heimili standi aldrei eftir án eiganda og að boð gildi aðeins einu sinni.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from .models import Household, Invite, Membership

_IS_TRANSLIT = str.maketrans(
    {"þ": "th", "Þ": "Th", "ð": "d", "Ð": "D", "æ": "ae", "Æ": "Ae", "ö": "o", "Ö": "O"}
)


class HouseholdError(Exception):
    """Aðgerð sem brýtur reglu; skilaboðin eru birt notandanum."""


def unique_slug(name: str) -> str:
    """„Heimilið á Þórsgötu“ → „heimilid-a-thorsgotu“, með -2, -3 … ef slóðin er tekin."""
    base = slugify(name.translate(_IS_TRANSLIT))[:40].strip("-") or "heimili"
    slug, n = base, 1
    while Household.objects.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


@transaction.atomic
def create_household(user, name: str) -> Household:
    household = Household.objects.create(name=name.strip(), slug=unique_slug(name))
    Membership.objects.create(user=user, household=household, role=Membership.Role.OWNER)
    return household


def rename_household(household: Household, name: str) -> None:
    # Slóðin breytist ekki, svo bókamerki og opnir flipar haldi áfram að virka
    household.name = name.strip()
    household.save(update_fields=["name"])


def create_invite(household: Household, by) -> Invite:
    return Invite.objects.create(household=household, created_by=by)


def revoke_invite(invite: Invite) -> None:
    invite.delete()


@transaction.atomic
def accept_invite(token: str, user) -> Membership:
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
    invite.accepted_by = user
    invite.accepted_at = timezone.now()
    invite.save(update_fields=["accepted_by", "accepted_at"])
    return Membership.objects.create(household=invite.household, user=user, role=Membership.Role.MEMBER)


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
