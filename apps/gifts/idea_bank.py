"""Gjafahugmyndabanki: almennar hugmyndir þegar hugmyndaflugið þrýtur (afmælissíðan)."""

from django.utils.translation import gettext_lazy as _

# (táknmynd, texti, u.þ.b. verð)
IDEAS = [
    ("local_cafe", _("Kaffiáskrift (3 mánuðir)"), 7500),
    ("museum", _("Árskort í listasafn"), 6900),
    ("spa", _("Sund- og saunapassi"), 5000),
    ("menu_book", _("Góð bók og kerti"), 6000),
    ("restaurant", _("Gjafabréf út að borða"), 10000),
    ("theater_comedy", _("Leikhúsmiðar"), 9000),
    ("extension", _("Púsl eða spil"), 4500),
    ("local_florist", _("Blóm og konfekt"), 5500),
]
