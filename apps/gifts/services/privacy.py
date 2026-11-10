"""Þú sérð ekki hvað aðrir ætla að gefa þér.

Hver notandi er tengdur einstaklingi á listanum (`Membership.person`). Gjafir handa honum eru
leyndar fyrir honum, öll ár og öll tilefni: hann sér aðeins óskirnar sem hann skráði sjálfur
(`Idea.wish`), ekki hugmyndir annarra, hvað er keypt, verð, áætlun, búðir né gefendur. Gjöfin
telst heldur ekki með í samtölum hjá honum, svo ekki sé hægt að reikna hana út.

Allt sem sýnir gjafir fer í gegnum `Viewer`: listinn, Verslanir, Rukkun, Fólk, afmælin, saga
einstaklings og opni óskalistinn. Views sem breyta gjöf neita (404) ef hún er leynd.

Einstaklingurinn heitir það sem hinir kalla hann („Dísa“); sjálfur sér notandinn nafnið sem
hann skráði („Ásdís“), sjá `Viewer.display_name`.
"""

from dataclasses import dataclass

from ..models import Gift, Person


@dataclass(frozen=True)
class Viewer:
    """Sá sem skoðar: einstaklingurinn sem notandinn er á listanum (ef einhver) og nafn hans."""

    person_id: int | None = None
    name: str = ""

    @classmethod
    def of(cls, membership) -> "Viewer":
        if membership is None or membership.person_id is None:
            return cls()
        return cls(membership.person_id, membership.user.name)

    def is_me(self, person: Person) -> bool:
        return self.person_id is not None and person.pk == self.person_id

    def is_recipient(self, gift: Gift) -> bool:
        return self.person_id is not None and gift.person_id == self.person_id

    def is_secret(self, gift: Gift) -> bool:
        """Gjöf handa þeim sem skoðar: staðan er leynd fyrir honum."""
        return self.is_recipient(gift)

    def visible(self, gifts) -> list[Gift]:
        return [g for g in gifts if not self.is_secret(g)]

    def secret(self, gifts) -> list[Gift]:
        return [g for g in gifts if self.is_secret(g)]

    def display_name(self, person: Person) -> str:
        """Eigið nafn notandans á hans eigin einstaklingi, annars nafnið á listanum."""
        if self.is_me(person) and self.name:
            return self.name
        return person.name


EVERYONE = Viewer()


def is_linked(person: Person) -> bool:
    """Er einstaklingurinn notandi í heimilinu (þá gæti hann opnað sinn eigin óskalista)?"""
    return person.memberships.exists()
