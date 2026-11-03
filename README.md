# Jólahjól

Gjafalisti fyrir heimili: gjafir og hugmyndir, búðir, rukkun og óskalistar sem hægt er að deila.
Django 6 + HTMX + Alpine. Arftaki `gjafalistinn/index.html`, sem er forskriftin að hegðuninni.

## Þróun

Skipanirnar eru í `justfile` (`just` sýnir þær allar):

```bash
just setup              # pakkar, pre-commit, Postgres í Docker og migrations
just createsuperuser
just dev                # Postgres + runserver
just check              # það sama og CI: lint, migrations í takt og próf
just test -k billing    # aukarök fara til pytest
```

Docker Desktop þarf að vera í gangi fyrir gagnagrunninn (127.0.0.1:5433).

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
| `accounts` | notandi auðkenndur með netfangi |
| `households` | heimili og aðild; `Household.objects.for_member(user)` stýrir aðgangi |
| `gifts` | líkön og `services/`: raunverð, rukkun, búðir, fólk, ár, eftir búðum |
| `wishlists` | opnir óskalistahlekkir |
| `legacy` | `import_legacy` |

Reglurnar eru í `apps/gifts/services/` og eru prófaðar óháð viðmóti.
