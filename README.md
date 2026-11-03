# Jólahjól

Gjafalisti fyrir heimili: gjafir og hugmyndir, búðir, rukkun og óskalistar sem hægt er að deila.
Django 6 + HTMX + Alpine. Arftaki `gjafalistinn/index.html`, sem er forskriftin að hegðuninni.

## Þróun

```bash
docker compose up -d            # Postgres á 127.0.0.1:5433
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Próf og lint:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Gögn úr gamla appinu

Í gamla appinu: **Sækja afrit (JSON)**. Síðan:

```bash
uv run python manage.py import_legacy jolahjol-2026-11-03.json \
    --household okkar --create "Heimilið okkar" --owner netfang@example.com
```

`--replace` skiptir út gögnum heimilis sem hefur þegar verið flutt inn.

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
