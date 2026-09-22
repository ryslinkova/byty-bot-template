# Návod na nastavení

Postup, jak tohohle bota rozjet od nuly. Psaný tak, aby ho mohl vzít
**libovolný AI agent** (Claude Code, Cursor, Copilot, Codex, Gemini CLI…)
a provést jím člověka, který programovat neumí. Když jsi člověk, čti to jako
běžný návod a příkazy si pouštěj sám — kroky jsou stejné.

Ostatní soubory (`CLAUDE.md`, `.github/copilot-instructions.md`) jen odkazují sem,
ať to funguje i v nástrojích, které hledají vlastní jméno souboru.

## Jak postupovat (pravidla pro agenta)

- **Jeden krok = jedna otázka.** Počkej na odpověď, pak pokračuj. Neházej celý návod najednou.
- **Nikdy nezapisuj heslo ani e-mailovou adresu do souboru, který je v gitu.**
  Přístupové údaje patří jen do `.env` (lokálně, je v `.gitignore`) nebo do GitHub Secrets.
  Když uživatel napíše App Password do chatu, ulož ho do `.env` a upozorni,
  že si ho má v chatu považovat za prozrazený a případně vygenerovat nový.
- **Necommituj za uživatele do cizího repa.** Tohle repo je sdílená šablona;
  když si chce dělat vlastní úpravy, ať si udělá fork nebo vlastní repozitář.
- Mluv česky, pokud uživatel nezačne jinak.
- Než něco spustíš, řekni jednou větou co to udělá a zda to něco odešle.

## Co ten bot dělá

Projde inzeráty na Sreality, Bezrealitky a iDNES Reality, vyfiltruje je podle
`config.py` (typ, cena, plocha, vzdálenost od zvoleného bodu), zahodí ty,
které už jednou poslal (`seen.db`), a zbytek pošle jako HTML e-mail přes Gmail SMTP.
Žádné externí knihovny — stačí Python 3.12+ a standardní knihovna.

Soubory: `main.py` (orchestrace) · `config.py` (veškeré nastavení) ·
`sources/*.py` (parsery portálů) · `email_report.py` (HTML + odeslání) ·
`dedup.py` (`seen.db`) · `geo.py` (vzdálenost) · `models.py` (datový model).

## Průvodce nastavením — pořadí kroků

### 1. Python
Ověř `python3 --version` (potřeba 3.12+; na Windows zkus i `python --version` a `py -3 --version`).
Když chybí, pošli ho na python.org a počkej, než to doinstaluje.

### 2. Kde má chodit mail a odkud
Zeptej se na dvě věci:
1. **Odesílací Gmail** — z jakého účtu se bude posílat (klidně jeho vlastní; mail si pošle sám sobě).
2. **Příjemci** — kam to má chodit, může být víc adres oddělených čárkou.

Pak vytvoř `.env` podle `.env.example` (`cp .env.example .env`) a vyplň `GMAIL_USER`
a `REPORT_RECIPIENT`. `GMAIL_APP_PASSWORD` nech zatím prázdné.

### 3. App Password pro Gmail
Tohle uživatele nejčastěji zasekne, proveď ho tím pomalu:

1. Google účet → **Zabezpečení** → musí mít zapnuté **dvoufázové ověření**.
   Bez něj se App Passwords vůbec nenabídnou — když je nevidí, tohle je důvod.
2. Pak <https://myaccount.google.com/apppasswords> → zadá libovolný název (např. „byty-bot“) → **Vytvořit**.
3. Google ukáže 16 znaků ve čtyřech skupinách. **Mezery se mažou** — do `.env` patří slitých 16 znaků.
4. Heslo se ukáže jen jednou. Zapiš ho do `.env` jako `GMAIL_APP_PASSWORD=`.

Běžné heslo k účtu přes SMTP **nefunguje**, na to se neptej ani to nezkoušej.

### 4. Nastavení hledání (`config.py`)
Zeptej se, co má hledat, a přepiš hodnoty. Default je Písek + 15 km, do 6 mil. Kč, od 40 m².

| Chce změnit | Uprav |
|---|---|
| typ nemovitosti | `PROPERTY_TYPES` (`byty`, `domy`, `chaty`) |
| dispozici (jen byty) | `DISPOSITIONS`, prázdný seznam = všechny |
| cenu / plochu | `MAX_PRICE_CZK`, `MIN_AREA_M2` (`None` = bez limitu) |
| jinou oblast | `OKRESY`, `BEZREALITKY_KRAJ`, `CENTER_LAT`, `CENTER_LON`, `RADIUS_KM` |
| texty v mailu | `CENTER_NAME`, `SEARCH_AREA_LABEL` |
| obce pro iDNES | `IDNES_OKRESY`, `TOWNS_NEAR` |

Na co si dát pozor při změně oblasti:
- `OKRESY` a `BEZREALITKY_KRAJ` jsou **slugy z URL** daného portálu (`pisek`, `jihocesky-kraj`) — ověř si je tím, že si otevřeš odpovídající výpis na webu portálu.
- `CENTER_LAT` / `CENTER_LON` si najdi (mapy.cz, Google Maps) — na tomhle stojí filtr radiusu.
- `CENTER_NAME` se v mailu skládá do věty „…km od **Písku**“, takže patří ve **2. pádu**. `SEARCH_AREA_LABEL` je do předmětu v 1. pádu.
- iDNES nemá v inzerátech souřadnice, filtruje se výčtem obcí v `TOWNS_NEAR`. Když ho uživatel nechá prázdný / nesedící k `IDNES_OKRESY`, iDNES prostě nic nevrátí. Doplň obce v okolí ručně.

### 5. Zkušební běh bez odesílání
```bash
python3 main.py --dry-run
```
Vytvoří `preview_email.html`. **Otevři ho uživateli** a nech ho říct, jestli výsledky
odpovídají. Když je prázdný, projdi s ním filtry — obvykle je moc přísná cena,
plocha nebo malý radius. (Soubor je v `.gitignore`, do gitu se nedostane.)

Testy kódu: `python3 -m unittest discover -s tests -t .`

### 6. Ostrý e-mail
```bash
python3 main.py
```
Odešle mail **a zapíše inzeráty do `seen.db`** — podruhé už se stejné nabídky neposílají.
Řekni to dopředu. Když uživatel chce začít nanovo, smaž `seen.db`.

### 7. Automatický provoz (nepovinné, ale o to většinou jde)
Bez tohohle si musí bota pouštět ručně. Přes GitHub Actions poběží sám dvakrát denně.

1. Uživatel potřebuje **vlastní repozitář** na svém GitHub účtu — fork téhle šablony,
   nebo nové repo, do kterého nahraje tyhle soubory. Do cizího repa secrets nastavit nemůže.
2. V jeho repu: **Settings → Secrets and variables → Actions → New repository secret**,
   třikrát: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `REPORT_RECIPIENT`.
   (Stejné hodnoty jako v `.env`. `.env` se do GitHubu nenahrává.)
3. Záložka **Actions** → u forku jsou workflowy defaultně vypnuté, musí je povolit tlačítkem.
4. Workflow „Denní přehled bytů“ → **Run workflow** → ruční první běh. Nech ho zkontrolovat,
   že mail dorazil, a v logu běhu ukaž, kde se případná chyba objeví.
5. Dál běží podle cronu v `.github/workflows/daily.yml`: 5:00 a 17:00 UTC
   (7:00 a 19:00 v létě, 6:00 a 18:00 v zimě). Když chce jiný čas, uprav cron — **je v UTC**.

Poznámka k `seen.db`: Actions nemají trvalý disk, databáze se proto ukládá jako
asset v releasu `db-store`, který si workflow sám vytvoří. Ten release **nemazat**,
jinak přijdou znovu všechny staré inzeráty.

## Když to nefunguje

| Projev | Příčina |
|---|---|
| `Chybí GMAIL_USER / GMAIL_APP_PASSWORD` | `.env` neexistuje, je jinde než v kořeni repa, nebo běží CI bez nastavených Secrets |
| `Chybí příjemce e-mailu` | prázdné `REPORT_RECIPIENT` i `RECIPIENT_EMAILS` |
| SMTP `535` / authentication failed | běžné heslo místo App Password, mezery v App Password, nebo vypnuté 2FA |
| Mail dorazí prázdný | filtry jsou moc přísné (cena/plocha/radius), ověř `--dry-run` |
| iDNES nevrací nic | prázdný nebo nesedící `TOWNS_NEAR`; portál taky občas blokuje boty |
| Jeden portál nevrací nic, ostatní jo | portál nejspíš změnil HTML/JSON — parser v `sources/` potřebuje opravit, to je práce pro tebe, ne pro uživatele |
| Druhý den zase stejné inzeráty | ztracené `seen.db` (lokálně smazané, v CI smazaný release `db-store`) |

Portály si své stránky občas přestaví a parser přestane vracet výsledky. Není to
chyba uživatele — v takovém případě se podívej do `sources/` a strukturu doparsuj znovu.
