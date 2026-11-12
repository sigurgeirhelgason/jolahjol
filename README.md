# Jólahjól

Gjafalisti fyrir heimili: gjafir og hugmyndir, búðir, rukkun og óskalistar sem hægt er að deila.
Django 6 + HTMX + Alpine. Arftaki `gjafalistinn/index.html`, sem er forskriftin að hegðuninni.

## Þróun

Skipanirnar eru í `justfile` (`just` sýnir þær allar):

```bash
just setup              # pakkar, pre-commit, Postgres í Docker, migrations og Chromium fyrir e2e
just dev                # Postgres + runserver
just check              # það sama og CI: lint, migrations í takt, próf og e2e
just test -k billing    # aukarök fara til pytest
just e2e --headed       # Playwright-próf í vafra (sýnilegum)
```

Docker Desktop þarf að vera í gangi fyrir gagnagrunninn (127.0.0.1:5433).

**Innskráning í þróun:** stofnaðu aðgang á `/accounts/signup/` (netfangið er ekki staðfest).
Póstur („Týnt lykilorð“) prentast í terminal þar sem `just dev` keyrir. Admin er á `/admin/` með
`just createsuperuser`.

## Gögn úr gamla appinu

Í gamla appinu: **Sækja afrit (JSON)**. Síðan:

```bash
just import-legacy jolahjol-2026-11-03.json            # heimilið „okkar“
just import-legacy-replace jolahjol-2026-11-03.json    # skipta út áður innfluttum gögnum
```

Til að gera notanda að eiganda: `just manage import_legacy … --owner netfang@example.com`.

## Uppbygging

| App | Hlutverk |
|---|---|
| `core` | texta- og upphæðarföll (`normalize`, `fold_key`, `evaluate_amount`, `kr`-filter) |
| `accounts` | notandi auðkenndur með netfangi; netfang + lykilorð, nýskráning með heimili í einu skrefi, „Týnt lykilorð“ (allauth), `prune_users` |
| `households` | heimili, aðild, boð; `HouseholdMixin` sækir heimilið úr `/h/<slug>/` og skilar 404 annars |
| `gifts` | líkön og `services/` (reglur), `listing.py` (framsetning listans), views og gluggar |
| `wishlists` | opnir óskalistahlekkir |
| `legacy` | `import_legacy` |

Reglurnar eru í `apps/gifts/services/` og eru prófaðar óháð viðmóti.

**Síður jólaárs** (`/h/<heimili>/<ár>/…`): gjafalisti, `budir/` (eftir búð eða staðsetningu),
`folk/` og `rukkun/`. Þær deila `gifts/base_season.html` (hetjuhluti, ársval, yfirlit). Gluggar vita
frá hvaða síðu þeir voru opnaðir (`<body data-page>` → `X-Page`); á öðrum síðum en listanum er
síðan sótt aftur eftir vistun.

**Óskalistar** (`apps/wishlists`): einstaklingsglugginn býr til hlekk `/o/<tóki>/`. Opna síðan
sýnir aðeins hugmyndir viðkomandi á árinu; „Ég kaupi þetta“ gerir nafnið að gefanda. Sama tæki
getur hætt við (undirritað cookie). Takmörkun á beiðnum notar cache í gagnagrunni
(`just migrate` keyrir `createcachetable`).

**Afmæli** (`/h/<heimili>/afmaeli/`): afmæli næstu 12 mánuði hjá þeim sem eru merktir „Gef
afmælisgjafir“. Afmælisgjöf er venjuleg `Gift` með `occasion=afmaeli` á afmælisárinu (jólasíðurnar
sía á `.christmas()`). Gjöfin verður ekki til fyrr en eitthvað er skráð á hana.
Áminningar í pósti: `just reminders` (`send_birthday_reminders`, keyrt daglega í prod; `SITE_URL`
fyrir hlekkinn í póstinum).

**Framendi:** sniðmát í `templates/`, `gifts/list.html` með `partialdef` fyrir htmx-svör. Allt JS
er í `static/js/app.js` (Alpine CSP-útgáfa: engar inline-segðir). htmx, Alpine og leturgerðir eru
hýst sjálf og CSP er ströng. Nýjar táknmyndir: bæta við `scripts/fetch_icons.py` og keyra `just icons`.

## Prod

Hetzner (sami þjónn og Maintenance Tracker) á bak við Cloudflare Tunnel; `just deploy` gefur út.
Uppsetning og daglegar skipanir: [docs/PRODUCTION.md](docs/PRODUCTION.md).
