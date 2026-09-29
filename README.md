# byty-bot

Bot, který dvakrát denně projde inzeráty **prodeje nebo pronájmu nemovitostí** v zadané oblasti
a pošle e-mail jen s **novými** nabídkami. Vše se nastavuje v `config.py`
(defaultně: prodej bytů/domů/chat do 15 km od Písku, do 6 mil. Kč, od 40 m²;
volitelně i pozemky nebo pronájem).

Bez závislostí — čistá standardní knihovna Pythonu (3.12+).

> **Nastavuješ to poprvé?** Celý postup krok za krokem (App Password, `.env`,
> filtry, automatické spouštění) je v [`AGENTS.md`](AGENTS.md). Buď si ho přečti sám,
> nebo otevři složku ve svém AI nástroji (Claude Code, Cursor, Copilot, Codex…)
> a napiš „proveď mě nastavením“ — návod je psaný tak, aby tě jím agent provedl.

## Autoři

Původní autorkou bota je **[@MarketaAnt](https://github.com/MarketaAnt)** —
postavila celou kostru: datový model, parsery všech tří portálů, dedup přes SQLite,
skládání HTML e-mailu i běh v GitHub Actions s databází uloženou jako asset releasu.

**[@ryslinkova](https://github.com/ryslinkova)** verzi rozvinula do dnešní podoby:

- přepnutí z pronájmů na **prodej** a rozšíření na byty, domy i chaty,
- zobecnění filtrů — cena, minimální plocha, radius hledání v km,
- oprava obrázků ze Sreality v e-mailu (CDN vyžaduje `fl` parametry v URL),
- načítání `.env` při lokálním spuštění,
- allowlist obcí pro iDNES, který nemá v inzerátech GPS,
- víc příjemců přehledu najednou (`REPORT_RECIPIENT` oddělený čárkami),
- spouštění dvakrát denně místo jednou,
- tahle sdílená verze: nastavení oddělené od přístupových údajů a průvodce nastavením v `AGENTS.md`.

Na obou stranách u toho asistoval Claude (Claude Code / Cursor).

## Zdroje

| Zdroj | Metoda | Geo filtr |
|-------|--------|-----------|
| Sreality.cz | SSR JSON (`__NEXT_DATA__`) | přesný radius dle GPS |
| Bezrealitky.cz | Apollo cache (`__NEXT_DATA__`) | přesný radius dle GPS |
| iDNES Reality | HTML (regex, browser hlavičky kvůli anti-botu) | okres + seznam obcí (bez GPS) |

Stejná nemovitost na více portálech se v mailu slučuje (priorita: Bezrealitky → Sreality → iDNES).

## Rychlý start

```bash
gh repo create byty-bot --template ryslinkova/byty-bot-template --private --clone
cd byty-bot
cp .env.example .env        # a vyplň hodnoty (viz níže)
python3 main.py --dry-run   # vytvoří preview_email.html, nic neodešle
python3 main.py             # odešle e-mail
python3 -m unittest discover -s tests -t .   # testy
```

## Konfigurace hledání

Vše na jednom místě v `config.py`:

- `OFFER_TYPE` — `"prodej"` nebo `"pronajem"` (jedno nastavení na bota; chceš-li obojí, pusť si dvě kopie)
- `PROPERTY_TYPES` — libovolná kombinace `byty`, `domy`, `chaty`, `pozemky`
- `DISPOSITIONS` (jen pro byty), `MAX_PRICE_CZK` (u pronájmu **měsíční nájem**), `MIN_AREA_M2` (byty/domy/chaty),
  `MIN_LAND_AREA_M2` (plocha pozemku) — co hledat
- `OKRESY`, `BEZREALITKY_KRAJ` — hrubá síť pro Sreality/Bezrealitky
- `CENTER_LAT` / `CENTER_LON` / `RADIUS_KM` — přesné dofiltrování podle GPS
- `CENTER_NAME`, `SEARCH_AREA_LABEL` — texty v e-mailu (pozor na skloňování: „km od **Písku**“)
- `IDNES_OKRESY` + `TOWNS_NEAR` — iDNES nemá v inzerátech GPS, filtruje se seznamem obcí

## Proměnné prostředí (nutné pro odeslání)

Lokálně přes `.env` (viz `.env.example`), v CI přes GitHub Secrets.
**Žádná z těchto hodnot nepatří do repozitáře** — `.env` je v `.gitignore`.

| Proměnná | Význam |
|----------|--------|
| `GMAIL_USER` | odesílací Gmail adresa |
| `GMAIL_APP_PASSWORD` | [App Password](https://myaccount.google.com/apppasswords) (Google účet → Zabezpečení → Dvoufázové ověření → Hesla aplikací). Běžné heslo k účtu přes SMTP **nefunguje**. |
| `REPORT_RECIPIENT` | kam poslat přehled; víc adres odděl čárkou. Když je prázdné, použije se `RECIPIENT_EMAILS` z `config.py`. |

## Provoz přes GitHub Actions

`.github/workflows/daily.yml` spouští bota dvakrát denně v 5:00 a 17:00 UTC
(7:00 a 19:00 v létě, 6:00 a 18:00 v zimě). Pro vlastní provoz:

1. Vytvoř si z šablony vlastní **soukromé** repo (**Use this template** → Private).
   Ne fork — fork veřejného repa je vždycky veřejný i s tvým `config.py`.
2. Settings → Secrets and variables → Actions → přidej `GMAIL_USER`,
   `GMAIL_APP_PASSWORD` a `REPORT_RECIPIENT`.
3. Actions → když jsou workflowy vypnuté, povol je.
4. První běh spusť ručně přes **Run workflow**.

Dedup databáze `seen.db` (co už bylo odesláno) nemá kde v Actions přežít mezi běhy,
proto se ukládá jako asset v releasu `db-store` — workflow si ho sám vytvoří.

## Známé problémy

- **Zpožděné spouštění na GitHub Actions.** GitHub naplánované (`cron`) běhy v době vysoké
  zátěže odkládá, zvlášť na začátku hodiny. Tester naměřil zpoždění až 5 hodin, mail tedy
  dorazí později, než je v `daily.yml` nastaveno. Nic se neztratí, jen přijde pozdě.
  Případná náprava: posunout minutu v cronu na neokrouhlou hodnotu (např. `"23 5,17 * * *"`),
  nebo bota provozovat mimo GitHub (např. Railway s volume pro `seen.db`).
