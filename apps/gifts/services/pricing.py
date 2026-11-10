"""Raunverð og skipting upphæða á gefendur.

Raunverð er það sem *við* greiðum: summa keyptra hugmynda með verði, nema þess hluta
sem gefendur greiða þegar hugmynd er keypt fyrir annan. Samsvarar `syncPrice` og
`byGiver` í gamla appinu.
"""

from dataclasses import dataclass

from ..models import Gift, Idea, Person


@dataclass(frozen=True)
class Shares:
    givers: list[tuple[Person, int]]  # hlutur hvers gefanda sem er rukkaður
    ours: int  # það sem við greiðum sjálf


def split_shares(idea: Idea) -> Shares:
    """Skiptir verði hugmyndar á gefendur.

    - Ekki keypt fyrir annan, eða engir gefendur: við greiðum allt.
    - Engin `share` tilgreind: jöfn skipting, afgangur af námundun á fyrsta gefanda.
    - `share` tilgreind: hver greiðir sinn hlut og afgangurinn er okkar.
    """
    price = idea.price or 0
    links = list(idea.giver_links.all())
    if not idea.for_other or not links:
        return Shares([], price)
    if any(link.share is not None for link in links):
        parts = [(link.person, link.share or 0) for link in links]
        return Shares(parts, max(0, price - sum(n for _, n in parts)))
    base, rest = divmod(price, len(links))
    parts = [(link.person, base + (rest if i == 0 else 0)) for i, link in enumerate(links)]
    return Shares(parts, 0)


def actual_price(gift: Gift) -> int | None:
    """Raunverð gjafar, eða None ef það er óþekkt eða allt er rukkað annan.

    Ef keyptar hugmyndir eru með verð ræður summa okkar hlutar í þeim, hvort sem gjöfin er
    merkt „Tilbúið“ eða ekki (peningurinn er farinn); annars upphæðin sem var slegin inn þegar
    gjöfin var merkt tilbúin.
    """
    priced = [i for i in gift.ideas.all() if i.picked and i.price]
    if not priced:
        return gift.manual_price if gift.bought else None
    shares = [split_shares(i) for i in priced]
    ours = sum(s.ours for s in shares)
    has_own = any(not s.givers for s in shares) or ours > 0
    return ours if has_own else None


def giver_breakdown(gift: Gift) -> list[tuple[Person | None, int]] | None:
    """Sundurliðun raunverðs eftir gefendum (None = frá okkur).

    Aðeins þegar einhver keypt hugmynd hefur gefendur; annars None svo viðmótið
    sýni bara heildartöluna. Gjöf frá mörgum (ekki rukkuð) skiptist jafnt til sýnis.
    """
    priced = [i for i in gift.ideas.all() if i.picked and i.price]
    if not any(i.giver_links.all() for i in priced):
        return None
    sums: dict[int | None, list] = {}
    for idea in priced:
        if idea.for_other:
            continue  # rukkaður hluti er utan raunverðs
        links = list(idea.giver_links.all())
        if not links:
            sums.setdefault(None, [None, 0])[1] += idea.price
            continue
        base, rest = divmod(idea.price, len(links))
        for i, link in enumerate(links):
            sums.setdefault(link.person_id, [link.person, 0])[1] += base + (rest if i == 0 else 0)
    total = actual_price(gift) or 0
    rest = total - sum(n for _, n in sums.values())
    if rest > 0:
        sums.setdefault(None, [None, 0])[1] += rest
    return [(who, n) for who, n in sums.values() if n] or None
