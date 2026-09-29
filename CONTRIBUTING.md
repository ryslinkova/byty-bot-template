# Jak přispívat

Tohle repo je **sdílená šablona**. Chceš-li bota používat, vytvoř si z něj přes **Use this template**
vlastní soukromé repo (ne fork, ten by byl veřejný) a nastav ho podle [`AGENTS.md`](AGENTS.md). Svoje `config.py`, secrets ani `seen.db`
sem nikdy neposílej.

## Co je vítané jako pull request

- oprava parseru portálu (`sources/`), když portál změní HTML/JSON,
- oprava chyby nebo doplnění testů (`tests/`),
- zlepšení návodu v `README.md` a `AGENTS.md`.

Před PR pusť testy:

```bash
python3 -m unittest discover -s tests -t .
```

Žádné externí závislosti — zůstává čistá standardní knihovna Pythonu 3.12+.

## Co sem nepatří

- osobní nastavení hledání (oblast, cena, příjemci) — to patří do tvého vlastního repa,
- přístupové údaje jakéhokoli druhu (`.env` je v `.gitignore`, nedávej ho do commitu),
- nové portály nebo větší změny bez předchozí domluvy — nejdřív otevři issue.

Do `main` může přímo pushovat jen autorka repa, ostatní přes pull request.
Nový kód se posuzuje ručně, takže odpověď může chvíli trvat.
