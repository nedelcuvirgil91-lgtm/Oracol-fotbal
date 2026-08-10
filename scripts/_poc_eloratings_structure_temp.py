"""
================================================================================
POC IZOLAT, TEMPORAR — structura reală a eloratings.net (2026-08-10)
================================================================================
Investighează de ce `oracle_api._fetch_elo_ratings()` (R-Sync-4, ADR-039)
persistă de săptămâni EXACT `ELO_RATINGS_FALLBACK` (mappings.py), byte cu
byte — confirmat live, `national_team_elo_snapshot` are 64 rânduri identice
cu lista statică. Nicio eroare `[ELO] Scrape failed` în logurile reale
(rularea de 2026-08-09) — deci cererea HTTP probabil reușește, dar parsarea
(`soup.find("table")` + extragere celule) nu găsește nimic valid.

Acest script NU importă `oracle_api.py`/`key_manager.py`, NU scrie nicăieri,
NU modifică niciun workflow existent — doar reproduce exact cererea reală
(același URL, headere similare) și raportează ce găsește. Se șterge din
cod după închiderea investigației (dovada rămâne în istoricul rulărilor
GitHub Actions), per disciplina POC-urilor deja stabilită în proiect.
================================================================================
"""
from __future__ import annotations

import sys

import requests
from bs4 import BeautifulSoup

ELO_URL = "https://www.eloratings.net"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def main() -> int:
    print(f"[POC] GET {ELO_URL}")
    try:
        r = requests.get(
            ELO_URL,
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
            timeout=20,
        )
    except Exception as exc:
        print(f"[POC] Cerere eșuată (excepție): {exc!r}")
        return 1

    print(f"[POC] HTTP status: {r.status_code}")
    print(f"[POC] Content-Type: {r.headers.get('content-type')}")
    print(f"[POC] Lungime răspuns (bytes): {len(r.content)}")
    if not r.ok:
        print(f"[POC] Răspuns non-OK, primele 500 caractere:\n{r.text[:500]}")
        return 1

    text = r.text
    print(f"[POC] Lungime text: {len(text)}")
    print(f"[POC] Primele 1000 caractere din HTML:\n{text[:1000]}")

    # Semnale directe de randare client-side (React/Vue/Angular app shell) —
    # dacă găsim asta, parsarea BeautifulSoup e structural imposibilă fără
    # execuție JS, indiferent de selector.
    js_markers = ["id=\"root\"", "id=\"app\"", "__NEXT_DATA__", "ng-app", "data-reactroot"]
    found_markers = [m for m in js_markers if m in text]
    print(f"[POC] Markeri de randare client-side găsiți: {found_markers or 'niciunul'}")

    soup = BeautifulSoup(text, "html.parser")
    tables = soup.find_all("table")
    print(f"[POC] Număr total de <table> găsite: {len(tables)}")

    for i, table in enumerate(tables):
        rows = table.find_all("tr")
        print(f"[POC] --- Tabelul #{i}: {len(rows)} rânduri ---")
        for j, row in enumerate(rows[:5]):
            cells = row.find_all(["td", "th"])
            cell_texts = [c.get_text(strip=True) for c in cells]
            print(f"[POC]   rând {j} ({len(cells)} celule): {cell_texts}")

    if not tables:
        print("[POC] ZERO tabele găsite în HTML brut — fie pagina nu conține "
              "deloc <table>, fie conținutul e randat prin JavaScript după "
              "încărcare (BeautifulSoup vede doar shell-ul inițial, nu DOM-ul "
              "final din browser).")

    # Verificare suplimentară: căutăm text recognoscibil (nume de echipe/
    # cifre ELO) oriunde în pagină, chiar dacă nu într-un <table> — ar
    # confirma dacă datele există dar în altă structură (div/listă).
    body_text = soup.get_text(" ", strip=True)
    for needle in ["Argentina", "Brazil", "France", "Spain"]:
        idx = body_text.find(needle)
        print(f"[POC] '{needle}' găsit în text la offset {idx}" if idx >= 0
              else f"[POC] '{needle}' NU apare deloc în textul paginii")

    return 0


if __name__ == "__main__":
    sys.exit(main())
