"""
================================================================================
FOOTBALL ORACLE — Verificare live: servirea Campionului blend_v1 (ADR-061)
================================================================================
Module: scripts/verify_blend_v1_champion_serving.py

STRICT read-only. Nu scrie nimic, nicaieri.

DE CE EXISTA: ADR-061 a conectat Campionul PROMOVAT al familiei blend_v1 la
o cale noua de servire (learning_core/blend_v1_champion_loader.py +
oracle_engine._get_blend_v1_champion_prediction()). Testele unitare (mock-uite)
verifica orchestrarea, dar nu confirma ca lantul REAL functioneaza contra
Supabase de productie — mediul de dezvoltare nu are acces direct la
streamlit.app (blocat de politica de retea) sau la credentialele Supabase
locale, deci verificarea reala se face aici, prin CI, unde secretele exista.

CE FACE: reproduce exact calea din oracle_engine._get_blend_v1_champion_prediction()
— incarca Campionul blend_v1 activ (load_blend_v1_champion_or_none), apoi
calculeaza o predictie blend pe feature-uri sintetice (safe, deterministe,
nu ating niciun meci real) prin predict_with_blend_challenger(), exact
functia deja folosita de calea de servire live.

Utilizare:
    python scripts/verify_blend_v1_champion_serving.py
================================================================================
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78


def main() -> int:
    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    from learning_core.blend_v1_champion_loader import load_blend_v1_champion_or_none
    from learning_core.blend_challenger_shadow import predict_with_blend_challenger
    from ml_predictor import FEATURE_COLUMNS, _LEAGUE_SCOPE

    print(BAR)
    print("  VERIFICARE — servirea live a Campionului blend_v1 (ADR-061)")
    print(BAR)

    champion = load_blend_v1_champion_or_none(_LEAGUE_SCOPE)
    if champion is None:
        print("  REZULTAT: niciun Campion blend_v1 utilizabil (load_blend_v1_champion_or_none -> None).")
        print("  UI ar afisa: {'available': False, 'reason': 'champion_indisponibil'}")
        print(BAR)
        return 1

    print(f"  Campion gasit: training_run_id={champion.training_run_id}")
    print(f"    samples_used={champion.samples_used}  algorithm_version={champion.algorithm_version}")
    print(f"    accuracy={champion.accuracy}  log_loss={champion.log_loss}  trained_at={champion.trained_at}")
    print(f"    temperature={champion.temperature}")
    print(BAR)

    # Feature-uri sintetice, deterministe — nu ating niciun meci real,
    # doar confirma ca lantul de inferenta functioneaza capat la capat.
    synthetic_features = {c: 0.5 for c in FEATURE_COLUMNS}
    synthetic_features.update({"home_elo": 1550, "away_elo": 1500, "h2h_meetings": 3})
    oracle_probs = (0.45, 0.28, 0.27)

    result = predict_with_blend_challenger(
        oracle_probs=oracle_probs, features=synthetic_features, training_run_id=champion.training_run_id,
    )

    if result is None:
        print("  REZULTAT: predict_with_blend_challenger() a esuat (None).")
        print("  UI ar afisa: {'available': False, 'reason': 'predictie_esuata'}")
        print(BAR)
        return 1

    ph, pd_, pa = result
    total = ph + pd_ + pa
    print(f"  Predictie blend_v1 Champion (feature-uri sintetice): home={ph:.4f} draw={pd_:.4f} away={pa:.4f}")
    print(f"  Suma probabilitatilor: {total:.6f} (asteptat ~1.0)")
    print("  UI ar afisa: {'available': True, 'prob_home'/'prob_draw'/'prob_away': ...}")
    print(BAR)

    ok = abs(total - 1.0) < 0.01 and all(0.0 <= p <= 1.0 for p in (ph, pd_, pa))
    print(f"  Verificare incheiata. Lant complet functional: {ok}")
    print(BAR)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
