# ADR-005 — Odds Persistence Design: Governance Closure

**Status**: Accepted
**Affects**: `docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md`
**Authority**: Principal Software Architect

---

## Context

`ODDS_PERSISTENCE_DESIGN.md` a trecut prin mai multe runde succesive de review arhitectural (contradicția §6/§7 privind mutabilitatea `closing_*`; contractele de Scheduler și Concurență Atomică; clarificări privind bookmaker dispărut, date invalide, idempotență, scope 1X2, terminologie).

Ultima rundă de clarificări a fost integrată **direct în document**, înainte ca disciplina de guvernanță ("orice modificare a unui document Frozen necesită un ADR nou, nu editare directă") să fie aplicată strict asupra acestui document specific. Documentul fusese declarat `FROZEN` într-un pas intermediar, apoi redeschis pentru completări suplimentare prin editare directă, repetat — o secvențiere care nu a respectat, retroactiv, propria regulă de guvernanță pe care o descrie.

## Decision

1. Versiunea curentă a `ODDS_PERSISTENCE_DESIGN.md` (cea rezultată din toate rundele de clarificare deja aplicate) este declarată **versiunea canonică Frozen**.
2. Acest ADR **nu schimbă nicio regulă tehnică** din document și **nu introduce nicio cerință nouă**. Conținutul tehnic (contractul Service, schema, trigger-ul de imutabilitate, Scheduler, Concurență Atomică, regulile pentru bookmaker/date invalide/idempotență) rămâne exact cum a fost ultima dată validat.
3. **Începând cu acest ADR**, orice modificare viitoare a `ODDS_PERSISTENCE_DESIGN.md` necesită un ADR nou, dedicat — nu se mai face prin editare directă a documentului, indiferent de mărimea schimbării.

## Rationale

Rescrierea documentului acum, pentru a muta retroactiv clarificările deja integrate într-un ADR separat, ar produce zgomot în istoric (o editare suplimentară a unui document deja declarat stabil) fără niciun beneficiu tehnic — conținutul e deja corect, coerent și validat. Se preferă păstrarea versiunii curente, stabile, împreună cu o consemnare explicită, formală, a modului în care s-a ajuns la ea și a regulii care se aplică de acum înainte.

## Consequences

- `ODDS_PERSISTENCE_DESIGN.md` rămâne neschimbat de la acest ADR încolo.
- `ADR-005` devine punctul de pornire al aplicării stricte a regulii de guvernanță pentru acest document specific.
- Toate documentele Frozen (`ARCHITECTURE.md`, `DATABASE_SPEC.md`, `PIPELINE_SPEC.md`, `ENGINE_SPEC.md`, `CONFIG_SPEC.md`, `ODDS_PERSISTENCE_DESIGN.md`) urmează, de acum, aceeași disciplină uniformă: separare clară între documentele de specificație (descriu arhitectura) și ADR-uri (descriu istoricul și deciziile de schimbare).
