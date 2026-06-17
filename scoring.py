"""
scoring.py
----------
The 0-100 "Childcare Acquisition Attractiveness Score".

Each sub-score is 0-100. The weighted blend uses the weights from the
brief. Crucially, the overall result also reports a DATA-CONFIDENCE level:
a high score built on DEMO/Missing inputs is explicitly untrustworthy.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .provenance import Confidence

WEIGHTS = {
    "demand": 0.25,
    "supply_gap": 0.20,
    "growth": 0.15,
    "competitor_opportunity": 0.15,
    "school_family": 0.10,
    "affordability": 0.10,
    "planning_risk": 0.05,
}


def _band(score: float) -> str:
    if score >= 85:  return "Strong buy zone"
    if score >= 70:  return "Attractive — investigate targets"
    if score >= 55:  return "Possible — needs deeper due diligence"
    if score >= 40:  return "Risky / competitive"
    return "Avoid unless special deal"


@dataclass
class ScoreInputs:
    demand_strength: str                  # Low/Medium/High/Very High/Unknown
    children_per_place: Optional[float]
    pop_growth_pct: Optional[float]
    competitor_opportunity_0_100: Optional[float]   # higher = weaker competitors
    schools_within_3km: Optional[int]
    median_income: Optional[int]
    avg_daily_fee: Optional[float]
    planning_risk: str = "Unknown"        # Low/Medium/High/Unknown
    data_confidence: Confidence = Confidence.MEDIUM


@dataclass
class ScoreResult:
    total: int
    band: str
    recommendation: str
    sub_scores: Dict[str, float]
    reasons: List[str]
    risks: List[str]
    data_confidence: Confidence
    confidence_warning: str


def _demand_score(s: str) -> float:
    return {"Very High": 100, "High": 80, "Medium": 55, "Low": 25,
            "Unknown": 40}.get(s, 40)


def _supply_gap_score(cpp: Optional[float]) -> float:
    if cpp is None: return 40
    if cpp == float("inf"): return 100
    # more children per place = bigger gap = better
    if cpp >= 5: return 100
    if cpp >= 4: return 85
    if cpp >= 3: return 70
    if cpp >= 2: return 50
    if cpp >= 1.2: return 30
    return 15


def _growth_score(g: Optional[float]) -> float:
    if g is None: return 45
    if g >= 4: return 100
    if g >= 3: return 85
    if g >= 2: return 70
    if g >= 1: return 55
    if g >= 0: return 40
    return 20


def _school_score(n: Optional[int]) -> float:
    if n is None: return 45
    if n >= 6: return 100
    if n >= 4: return 80
    if n >= 2: return 60
    if n >= 1: return 45
    return 25


def _afford_score(income: Optional[int], fee: Optional[float]) -> float:
    if income is None: return 50
    # weekly fee burden vs weekly household income
    if fee is None: 
        if income >= 110000: return 75
        if income >= 80000: return 60
        return 45
    weekly_income = income / 52.0
    weekly_fee = fee * 5
    burden = weekly_fee / weekly_income if weekly_income else 1
    if burden <= 0.15: return 90
    if burden <= 0.22: return 70
    if burden <= 0.30: return 50
    return 30


def _planning_score(risk: str) -> float:
    return {"Low": 90, "Medium": 60, "High": 25, "Unknown": 55}.get(risk, 55)


def _recommendation(total: int, conf: Confidence) -> str:
    if conf in (Confidence.DEMO, Confidence.MISSING):
        return "Insufficient real data — load live sources before deciding"
    if total >= 85:  return "Buy"
    if total >= 70:  return "Watchlist — investigate acquisition targets"
    if total >= 55:  return "Watchlist — deeper due diligence required"
    if total >= 40:  return "Only buy at discount"
    return "Avoid"


def compute_score(inp: ScoreInputs) -> ScoreResult:
    subs = {
        "demand": _demand_score(inp.demand_strength),
        "supply_gap": _supply_gap_score(inp.children_per_place),
        "growth": _growth_score(inp.pop_growth_pct),
        "competitor_opportunity": inp.competitor_opportunity_0_100 if inp.competitor_opportunity_0_100 is not None else 50,
        "school_family": _school_score(inp.schools_within_3km),
        "affordability": _afford_score(inp.median_income, inp.avg_daily_fee),
        "planning_risk": _planning_score(inp.planning_risk),
    }
    total = round(sum(subs[k] * WEIGHTS[k] for k in WEIGHTS))

    # Build reasons / risks from the strongest and weakest sub-scores
    ranked = sorted(subs.items(), key=lambda kv: kv[1], reverse=True)
    label = {
        "demand": "Demand strength",
        "supply_gap": "Supply gap (children per place)",
        "growth": "Population growth",
        "competitor_opportunity": "Competitor weakness/opportunity",
        "school_family": "School & family ecosystem",
        "affordability": "Income/fee affordability",
        "planning_risk": "Planning/property risk",
    }
    reasons = [f"{label[k]} scores {v:.0f}/100" for k, v in ranked[:5] if v >= 55]
    risks = [f"{label[k]} is weak at {v:.0f}/100" for k, v in ranked[::-1][:5] if v < 60]
    if not reasons:
        reasons = ["No strong positive driver — market looks marginal."]
    if not risks:
        risks = ["No single dominant risk, but verify all inputs with real data."]

    conf = inp.data_confidence
    warn = ""
    if conf in (Confidence.DEMO, Confidence.MISSING):
        warn = ("⚠ This score is built on DEMO/incomplete inputs. It demonstrates "
                "the engine only and must NOT be used for a real decision until "
                "live ACECQA + ABS + schools data are loaded.")
    elif conf == Confidence.LOW:
        warn = "Score uses low-confidence (stale/scraped/estimated) inputs — treat as directional."

    return ScoreResult(
        total=total, band=_band(total),
        recommendation=_recommendation(total, conf),
        sub_scores=subs, reasons=reasons[:5], risks=risks[:5],
        data_confidence=conf, confidence_warning=warn,
    )
