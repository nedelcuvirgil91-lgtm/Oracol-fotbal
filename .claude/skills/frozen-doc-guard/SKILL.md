---
name: frozen-doc-guard
description: Blochează orice editare directă a unui document declarat Frozen în docs/00_GOVERNANCE/FROZEN_REGISTRY.md, fără un ADR care s-o autorizeze explicit. Se invocă automat la orice Edit/Write asupra unui fișier Frozen, pre-commit.
---

# frozen-doc-guard

## Scop

Protejează integritatea disciplinei de guvernanță a proiectului (ADR-uri, `FROZEN_REGISTRY.md`), de care depind toate celelalte reguli documentate în `CLAUDE.md`. Dacă un document Frozen se poate edita tăcut, o singură dată, întreaga disciplină devine opțională de facto.

## Când se declanșează

Automat, pre-commit, ori de câte ori un `Edit` sau `Write` țintește un fișier listat ca `FROZEN` în `docs/00_GOVERNANCE/FROZEN_REGISTRY.md`.

La data acestui skill, lista de documente Frozen confirmate în registru este:

- `ARCHITECTURE.md` — **declarat Frozen în registru, dar nu există fizic în acest repo** (gol de trasabilitate cunoscut, vezi mai jos)
- `DATABASE_SPEC.md` — idem, nu există fizic
- `PIPELINE_SPEC.md` — idem, nu există fizic
- `ENGINE_SPEC.md` — idem, nu există fizic
- `CONFIG_SPEC.md` — idem, nu există fizic
- `docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md` — există, Frozen confirmat (ADR-005, clarificat ADR-006)

## Reguli de respectat

- North Star #4: niciun document Frozen nu se editează direct — doar printr-un ADR nou.
- `FROZEN_REGISTRY.md`, secțiunea "Frozen Rule": redeschiderea unui document Frozen e permisă exclusiv dacă auditul unui document dependent relevă o contradicție tehnică demonstrabilă, imposibil de reconciliat altfel.
- ADR-005: motivul exact pentru care disciplina se aplică strict de la acel ADR încolo — editare directă repetată, chiar și pentru clarificări legitime, a fost identificată explicit ca practică de evitat.

## Verificare obligatorie înainte de orice modificare

1. Fișierul țintă e listat în `FROZEN_REGISTRY.md`? Dacă da, continuă la pasul 2; dacă nu, acest skill nu se aplică.
2. Există deja un ADR (`architecture/ADR-*.md` sau `docs/00_GOVERNANCE/ADR-*.md`) care autorizează explicit exact această schimbare? Dacă nu → **oprire**, nu edita. Explică utilizatorului că schimbarea necesită un ADR nou întâi.
3. Pentru cele 5 documente declarate Frozen dar absente fizic din repo: nu se poate verifica conformitatea unei schimbări cu un conținut care nu există. Semnalează explicit acest gol utilizatorului — nu presupune, nu inventează conținutul lor ca să continui.

## Fișiere de cunoscut

`docs/00_GOVERNANCE/FROZEN_REGISTRY.md` (sursa listei), `docs/00_GOVERNANCE/ADR-005-odds-persistence-clarifications.md`, `docs/00_GOVERNANCE/ADR-006-odds-persistence-operational-clarifications.md`, `docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md`.

## Dacă declanșează un conflict de arhitectură

Acesta e chiar scopul skill-ului — orice declanșare e, prin definiție, un semnal de oprire, nu de continuare. Nu modifica documentul; raportează utilizatorului ce ADR lipsește.

## Obligatoriu / Opțional

**Obligatoriu, fără excepție.**
