"""
================================================================================
FOOTBALL ORACLE — Blend Engine (ADR-051, Vision Shift / ADR-052)
================================================================================
Module: blend_engine.py

Motor independent — al treilea motor al platformei, alături de Oracle
(`oracle_engine.py`) și ML (viitor). Nu este un Challenger, nu este un
model ML separat, nu este un element de UI: rolul lui e să consume
predicțiile deja produse de unul sau mai multe motoare și să genereze
propria predicție.

Zero coupling, verificabil static: acest modul NU importă
`oracle_engine`/`ml_predictor`/`feature_engine`/`learning_core.*`. Nu
cunoaște cum au fost calculate `EngineOutput`-urile primite — doar
contractul lor. Oracle nu importă acest modul; un viitor ML Engine nu-l va
importa nici el — singurul care cunoaște `BlendEngine` e orchestratorul
(`oracle_engine.py`).

Separare de responsabilitate față de Machine Learning Engine (fixată
explicit, cerință a proprietarului produsului): `BlendEngine` NU își
antrenează propriul model, NU implementează învățare continuă, NU
dublează responsabilitatea ML Engine. Strategiile interne (vezi
`BlendStrategy` mai jos) sunt exclusiv metode de COMBINARE a unor
predicții deja calculate — niciodată algoritmi de învățare. Chiar și o
viitoare strategie de tip meta-learning/stacking ar aplica un model deja
antrenat ÎN ALTĂ PARTE (Learning Core, proces separat) — `combine()`
rămâne întotdeauna o funcție de inferență, niciodată o buclă de antrenare.

API-ul public — `BlendEngine.predict()` — descrie CE face, nu CUM.
Strategia activă (`BlendConfig.strategy`) și parametrii ei (`weights`)
sunt complet substituibili fără nicio schimbare a acestui contract: V1
(`WeightedAverageStrategy`) e prima implementare, nu definiția Blend.

Configurabilitate: acest modul nu citește NICIODATĂ Supabase/`model_config`
direct — rămâne pur, fără I/O, testabil complet izolat. `oracle_engine.py`
(orchestratorul) citește configurarea din `model_config` (mecanismul deja
existent în proiect) și o pasează explicit prin `BlendConfig`.
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class EngineOutput:
    """Contractul comun pe care orice motor (Oracle, ML, oricare viitor)
    trebuie să-l respecte pentru a fi consumat de Blend. Nimic altceva —
    Blend nu are nevoie de, și nu primește, nimic despre cum a fost
    calculată această predicție."""
    engine: str
    prob_home: float
    prob_draw: float
    prob_away: float


@dataclass(frozen=True)
class BlendConfig:
    """Config public, tipizat — nu dict generic, ca să păstreze contractul
    clar și extensibil (câmpuri noi, aditive, cu default sigur, niciodată
    prin slăbirea tipului)."""
    strategy: str = "weighted_average"
    weights: dict[str, float] = field(default_factory=dict)  # engine -> pondere; lipsă = 1.0 (neutru)

    @classmethod
    def from_dict(cls, raw: dict | None) -> "BlendConfig":
        """Parsare defensivă dintr-o sursă externă (ex. `model_config`,
        Supabase) — chei necunoscute ignorate, chei lipsă => default-uri
        sigure, niciodată o excepție pe o configurare parțială."""
        raw = raw or {}
        return cls(
            strategy=raw.get("strategy", cls.strategy),
            weights=dict(raw.get("weights", {})),
        )


class BlendStrategy(Protocol):
    """Contractul intern pe care orice strategie de combinare trebuie
    să-l respecte. Interschimbabile, selectate prin `BlendConfig.strategy`
    — niciodată hardcodate în `BlendEngine`."""
    name: str

    def combine(self, outputs: list[EngineOutput], config: BlendConfig) -> tuple[float, float, float]: ...


class WeightedAverageStrategy:
    """V1 — prima implementare, NU definiția Blend. Medie ponderată simplă;
    o strategie viitoare (calibrare, meta-learning, stacking, Bayesian)
    înlocuiește doar această clasă, niciodată contractul `BlendEngine.predict()`."""
    name = "weighted_average"

    def combine(self, outputs: list[EngineOutput], config: BlendConfig) -> tuple[float, float, float]:
        total_weight = 0.0
        ph = pd_ = pa = 0.0
        for o in outputs:
            w = config.weights.get(o.engine, 1.0)  # 1.0 = neutru, niciodată o opinie hardcodată
            ph += o.prob_home * w
            pd_ += o.prob_draw * w
            pa += o.prob_away * w
            total_weight += w
        if total_weight <= 0:
            total_weight = 1.0
        ph, pd_, pa = ph / total_weight, pd_ / total_weight, pa / total_weight
        total = ph + pd_ + pa
        if total > 0:
            ph, pd_, pa = ph / total, pd_ / total, pa / total
        return ph, pd_, pa


class BlendEngine:
    """Motor independent, nu o funcție de calcul. Instanțiat o dată de
    orchestrator (`oracle_engine.FootballOracleEngine.__init__`), reutilizat
    per predicție — exact tiparul deja folosit pentru `self.ml`."""

    _STRATEGIES: dict[str, BlendStrategy] = {
        "weighted_average": WeightedAverageStrategy(),
    }

    def __init__(self, config: BlendConfig | None = None) -> None:
        self.config = config or BlendConfig()

    def predict(self, outputs: list[EngineOutput]) -> dict | None:
        """CE face: produce o singură predicție 1X2 din N ieșiri de motor.
        CUM o face — complet ascuns de acest contract, determinat de
        strategia activă. None dacă `outputs` e gol (nimic de combinat —
        stare legitimă, nu se aproximează)."""
        if not outputs:
            return None
        strategy = self._STRATEGIES.get(self.config.strategy, self._STRATEGIES["weighted_average"])
        ph, pd_, pa = strategy.combine(outputs, self.config)
        return {"prob_home": ph, "prob_draw": pd_, "prob_away": pa}
