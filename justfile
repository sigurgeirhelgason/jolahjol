# Justfile fyrir Jólahjól
# Settu upp just: https://github.com/casey/just#installation

set windows-shell := ["cmd", "/c"]

# Íslenskir stafir birtast rétt í terminal
export PYTHONIOENCODING := "utf-8"

# uv er sett upp með pip, svo það er keyrt í gegnum python
uv := "python -m uv"
manage := uv + " run python manage.py"

# Sjálfgefið: sýna allar skipanir
default:
    @just --list

# ---------- Uppsetning ----------

# Fyrsta uppsetning: pakkar, pre-commit, gagnagrunnur og migrations
setup: install dev-db migrate
    {{uv}} run pre-commit install

install:
    {{uv}} sync

# ---------- Þróun ----------

# Ræsa Postgres í Docker (127.0.0.1:5433)
dev-db:
    docker compose up -d db

# Gagnagrunnur og Django-þjónn saman
dev: dev-db
    {{manage}} runserver

runserver:
    {{manage}} runserver

dev-stop:
    docker compose stop db

# ---------- Django ----------

migrate:
    {{manage}} migrate

makemigrations *args:
    {{manage}} makemigrations {{args}}

shell:
    {{manage}} shell

createsuperuser:
    {{manage}} createsuperuser

collectstatic:
    {{manage}} collectstatic --noinput

# Keyra hvaða manage.py skipun sem er, t.d. just manage showmigrations
manage *args:
    {{manage}} {{args}}

# Flytja inn JSON-afrit úr gamla appinu, t.d. just import-legacy afrit.json
import-legacy file household="okkar" name="Heimilið okkar":
    {{manage}} import_legacy "{{file}}" --household {{household}} --create "{{name}}"

# Skipta út áður innfluttum gögnum heimilis
import-legacy-replace file household="okkar":
    {{manage}} import_legacy "{{file}}" --household {{household}} --replace

# Uppfæra þýðingaskrár (íslenska og enska)
messages:
    {{manage}} makemessages -l is -l en --ignore=.venv
    {{manage}} compilemessages --ignore=.venv

# ---------- Próf og gæði ----------

# Öll próf; aukarök fara til pytest, t.d. just test -k billing
test *args:
    {{uv}} run pytest {{args}}

# Próf með nýjum test-gagnagrunni (eftir breytingar á migrations)
test-fresh:
    {{uv}} run pytest --create-db

lint:
    {{uv}} run ruff check .
    {{uv}} run ruff format --check .

fmt:
    {{uv}} run ruff check --fix .
    {{uv}} run ruff format .

# Allt sem CI keyrir: lint, migrations í takt og próf
check: lint
    {{manage}} makemigrations --check --dry-run
    {{uv}} run pytest

# ---------- Gagnagrunnur ----------

db-shell:
    docker compose exec db psql -U jolahjol -d jolahjol

# Eyðir þróunargagnagrunninum (öll gögn hverfa)
db-reset:
    docker compose down -v
    docker compose up -d db

# ---------- Docker ----------

docker-build:
    docker build -t jolahjol:dev .

# Öryggisathugun Django með prod-stillingum í Docker-myndinni
docker-check-deploy: docker-build
    docker run --rm --entrypoint python -e SECRET_KEY=check-only-not-a-real-key -e SECURE_SSL_REDIRECT=True -e SECURE_HSTS_SECONDS=31536000 -e SESSION_COOKIE_SECURE=True -e CSRF_COOKIE_SECURE=True -e SECURE_PROXY_SSL_HEADER=1 jolahjol:dev manage.py check --deploy --settings=config.settings.prod

docker-logs:
    docker compose logs -f

# ---------- Hreinsun ----------

clean:
    {{uv}} run python -c "import pathlib, shutil; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__') if '.venv' not in p.parts]"
