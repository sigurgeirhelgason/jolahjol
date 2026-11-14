HIDDEN_COOKIE = "faldir"


def hidden_people(request):
    """Fólk sem er falið á þessu tæki (augað við nafnið, sjá static/js/app.js).

    Gjafir og verð þeirra verða óskýr, t.d. þegar makinn horfir á skjáinn með manni. Valið er
    geymt í vafrakökunni `faldir` (auðkenni einstaklinga, aðskilin með punkti) en ekki í
    gagnagrunninum: það á við um skjáinn, ekki notandann. Þjónninn les hana svo síða og
    htmx-línur teiknist strax faldar, án þess að efnið sjáist í augnablik.
    """
    raw = request.COOKIES.get(HIDDEN_COOKIE, "")
    return {"hidden_people": frozenset(int(p) for p in raw.split(".") if p.isdigit())}
