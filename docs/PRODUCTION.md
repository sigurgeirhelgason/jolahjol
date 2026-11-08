# Prod

| | |
|---|---|
| Lén | jolahjol.is (aðallén) og jólahjól.is (`xn--jlahjl-bxae.is`), keypt hjá ISNIC |
| DNS + HTTPS | Cloudflare (bæði lénin), Cloudflare Tunnel inn á þjóninn |
| Þjónn | Hetzner CX23, sá sami og Maintenance Tracker (`root@204.168.218.98`), mappa `~/jolahjol` |
| Póstur | Gmail SMTP (app-lykilorð), hámark 500 á dag |
| Villur | Sentry, verkefnið `jolahjol` |
| Afrit | Hetzner-snapshots daglega + `just prod-backup` |

## Uppbygging

```
Notandi → Cloudflare (HTTPS) → Tunnel → cloudflared-gámur → web:8000 (gunicorn + whitenoise) → db
```

`compose.prod.yml` keyrir fjóra gáma: `db` (Postgres 17), `web` (migrate og síðan gunicorn),
`reminders` (afmælisáminningar á klukkutíma fresti eftir kl. 9) og `cloudflared`. Engin port eru
opnuð á þjóninum, svo Jólahjól rekst ekki á nginx Maintenance Trackers á porti 80.
`www.` og jólahjól.is fá 301 á `https://jolahjol.is` (`CanonicalHostMiddleware`).

## Daglegar skipanir (af eigin vél)

```bash
just deploy                      # git push + pull, build og endurræsing á þjóninum
just prod-ps                     # staða gámanna
just prod-logs                   # logs úr web; just prod-logs reminders / cloudflared
just prod-manage createsuperuser # hvaða manage.py skipun sem er
just prod-backup                 # pg_dump í backups/ (endurheimt: pg_restore)
```

## Fyrsta uppsetning

### 1. Cloudflare: bæði lénin

1. Cloudflare → **Add a domain** → `jolahjol.is` → Free. Eyddu öllum DNS-færslum sem Cloudflare
   stingur upp á (þær verða til í skrefi 3).
2. Sama fyrir `jólahjól.is` (Cloudflare breytir því í `xn--jlahjl-bxae.is`).
3. Skrifaðu hjá þér nafnaþjónana tvo sem Cloudflare úthlutar hvoru léni.
4. Hjá **ISNIC** → lénið → breyta nafnaþjónum → setja Cloudflare-þjónana inn. ISNIC athugar að
   þjónarnir svari fyrir lénið, svo skref 1–2 verða að vera búin. Slökktu á DNSSEC hjá ISNIC ef það
   er virkt (má kveikja aftur seinna í gegnum Cloudflare).
5. Í hvoru léni: **SSL/TLS → Full** og **Always Use HTTPS** á.

Það getur tekið allt að sólarhring þar til Cloudflare segir lénið „Active“.

### 2. Cloudflare Tunnel

1. Cloudflare → **Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared**, nafn `jolahjol`.
2. Afritaðu tokenið (langi strengurinn á eftir `--token` í uppsetningarskipuninni) í
   `CLOUDFLARE_TUNNEL_TOKEN`. Ekki keyra uppsetningarskipunina sjálfa; gámurinn sér um það.
3. Bættu við fjórum **public hostnames**, öllum með þjónustu **HTTP** → `web:8000`:
   `jolahjol.is`, `www.jolahjol.is`, `jólahjól.is`, `www.jólahjól.is`.
   Cloudflare býr sjálft til DNS-færslurnar.

### 3. GitHub og þjónninn

Á eigin vél (repo-ið er private, `sigurgeirhelgason/jolahjol`):

```bash
git remote add origin https://github.com/sigurgeirhelgason/jolahjol.git
git push -u origin main
```

Á þjóninum: deploy key svo hann geti sótt (aðeins lesaðgangur):

```bash
ssh root@204.168.218.98
ssh-keygen -t ed25519 -f ~/.ssh/jolahjol_deploy -N "" -C jolahjol-deploy
cat ~/.ssh/jolahjol_deploy.pub     # → GitHub repo → Settings → Deploy keys → Add (ekki write)
cat >> ~/.ssh/config <<'EOF'
Host github-jolahjol
    HostName github.com
    IdentityFile ~/.ssh/jolahjol_deploy
    IdentitiesOnly yes
EOF
git clone git@github-jolahjol:sigurgeirhelgason/jolahjol.git ~/jolahjol
cd ~/jolahjol
cp .env.prod.example .env && nano .env
```

### 4. Gildin í `.env`

Skýringar eru í `.env.prod.example`. Það sem þarf að sækja:

- **SECRET_KEY, POSTGRES_PASSWORD**: búa til á þjóninum með skipununum í skránni.
- **Gmail**: myaccount.google.com/apppasswords (2FA þarf að vera á) → app-lykilorð í
  `EMAIL_HOST_PASSWORD`, netfangið í `EMAIL_HOST_USER` og `DEFAULT_FROM_EMAIL`.
- **Sentry**: nýtt Django-verkefni `jolahjol` → DSN.
- **DJANGO_ADMIN_URL**: eitthvað sem ekki er hægt að giska á.

### 5. Ræsa

```bash
cd ~/jolahjol
docker compose -f compose.prod.yml up --build -d
docker compose -f compose.prod.yml ps        # allir „healthy“ / „running“
docker compose -f compose.prod.yml logs cloudflared | tail   # „Registered tunnel connection“
```

Svo af eigin vél:

```bash
just prod-manage createsuperuser
just prod-import-legacy jolahjol-afrit.json netfang@example.com   # gögnin úr gamla appinu
```

Prófa: innskráning á https://jolahjol.is með netfangi (kóðinn kemur í pósti),
https://www.jolahjol.is og https://jólahjól.is vísa á aðallénið, og Sentry tekur við:
`just prod-manage shell -c "import sentry_sdk; sentry_sdk.capture_message('prufa'); sentry_sdk.flush()"`.

### 6. Eftir að allt virkar

- Hækka `SECURE_HSTS_SECONDS` í `31536000` og `just deploy`.
- Uptime-vöktun (t.d. Sentry Uptime) á `https://jolahjol.is/healthz`.
- Google-innskráning (valfrjálst): OAuth-client í Google Cloud með redirect
  `https://jolahjol.is/accounts/google/login/callback/`, lyklarnir í `.env`.

## Þegar Gmail dugar ekki lengur

Gmail sendir frá Gmail-netfanginu, ekki @jolahjol.is, og leyfir 500 pósta á dag. Resend og Brevo
bjóða báðar SMTP, svo til að skipta þarf aðeins nýjar `EMAIL_*`-breytur og SPF/DKIM-færslur í
Cloudflare. Engar kóðabreytingar.
