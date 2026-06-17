"""
analysis.py
-----------
Turns the ACECQA service list into:
  * a competitor-quality breakdown (Exceeding/Meeting/Working Towards/None)
  * a competitor risk table
  * an "acquisition target" score per centre
  * a market-level competitor_opportunity score (0-100) feeding the main score
"""
from __future__ import annotations
from typing import List, Dict

from connectors.acecqa import Service

LARGE_PROVIDERS = [
    "g8 education", "goodstart", "affinity", "busy bees", "only about children",
    "guardian", "nido", "explorers", "kindercare", "story house",
]

RATING_RANK = {
    "Excellent": 5, "Exceeding National Quality Standard": 4, "Exceeding NQS": 4,
    "Exceeding": 4, "Meeting National Quality Standard": 3, "Meeting NQS": 3,
    "Meeting": 3, "Working Towards National Quality Standard": 2,
    "Working Towards NQS": 2, "Working Towards": 2,
    "Significant Improvement Required": 1,
}


def _rating_bucket(r: str) -> str:
    r = (r or "").strip()
    for key in RATING_RANK:
        if key.lower() in r.lower():
            return key
    return "Not rated / unknown"


def _is_large(provider: str) -> bool:
    p = (provider or "").lower()
    return any(lp in p for lp in LARGE_PROVIDERS)


def quality_breakdown(services: List[Service]) -> Dict[str, int]:
    out = {"Exceeding": 0, "Meeting": 0, "Working Towards": 0, "Not rated / unknown": 0}
    for s in services:
        b = _rating_bucket(s.nqs_rating)
        if "Exceeding" in b or "Excellent" in b:
            out["Exceeding"] += 1
        elif "Meeting" in b:
            out["Meeting"] += 1
        elif "Working Towards" in b or "Significant" in b:
            out["Working Towards"] += 1
        else:
            out["Not rated / unknown"] += 1
    return out


def competitor_risk_table(services: List[Service]) -> List[dict]:
    rows = []
    for s in services:
        bucket = _rating_bucket(s.nqs_rating)
        rank = next((v for k, v in RATING_RANK.items() if k.lower() in (s.nqs_rating or "").lower()), 0)
        large = _is_large(s.provider)
        # strength: strong if exceeding + large; weak if working-towards/unrated + independent
        if rank >= 4 and large:
            strength = "Strong"
        elif rank >= 4:
            strength = "Above average"
        elif rank == 3:
            strength = "Average"
        elif rank <= 2:
            strength = "Weak"
        else:
            strength = "Unknown"
        opp = []
        if rank <= 2 and rank != 0:
            opp.append("rating below Meeting — quality gap")
        if rank == 0:
            opp.append("no/old rating — investigate")
        if not large:
            opp.append("independent — possible succession/sale")
        rows.append({
            "Centre": s.name, "Distance km": s.distance_km,
            "Rating": bucket, "Provider type": "Large group" if large else "Independent",
            "Est. strength": strength,
            "Weakness / opportunity": "; ".join(opp) or "none obvious",
            "Places": s.places, "Address": s.address,
        })
    rows.sort(key=lambda r: (r["Distance km"] if r["Distance km"] is not None else 999))
    return rows


def acquisition_targets(services: List[Service]) -> List[dict]:
    """Score each existing centre as a possible *acquisition* target (0-100)."""
    targets = []
    for s in services:
        rank = next((v for k, v in RATING_RANK.items() if k.lower() in (s.nqs_rating or "").lower()), 0)
        large = _is_large(s.provider)
        score = 0
        notes = []
        if not large:
            score += 30; notes.append("independent operator (+30)")
        if rank in (2,):           # working towards = turnaround upside
            score += 25; notes.append("Working Towards rating — turnaround upside (+25)")
        elif rank == 0:
            score += 20; notes.append("no current rating — under-managed? (+20)")
        elif rank == 3:
            score += 10; notes.append("Meeting — solid base (+10)")
        elif rank >= 4:
            score += 0; notes.append("already Exceeding — premium price, low upside (+0)")
        if s.places and s.places >= 80:
            score += 15; notes.append("scale (≥80 places) (+15)")
        elif s.places and s.places >= 50:
            score += 10; notes.append("decent size (+10)")
        if s.distance_km is not None and s.distance_km <= 3:
            score += 10; notes.append("within 3km of catchment centre (+10)")
        score = min(score, 100)
        targets.append({
            "Centre": s.name, "Target score": score, "Distance km": s.distance_km,
            "Rating": _rating_bucket(s.nqs_rating),
            "Provider": "Large group" if large else "Independent",
            "Places": s.places, "Why": "; ".join(notes),
        })
    targets.sort(key=lambda t: t["Target score"], reverse=True)
    return targets


def competitor_opportunity_score(services: List[Service]) -> float:
    """Market-level 0-100: higher = weaker competition = more opportunity."""
    if not services:
        return 60.0  # empty market — but verify it's not just missing data
    ranks = []
    large_share = 0
    for s in services:
        rank = next((v for k, v in RATING_RANK.items() if k.lower() in (s.nqs_rating or "").lower()), 0)
        ranks.append(rank if rank else 2.5)  # unrated treated as mid-low
        if _is_large(s.provider):
            large_share += 1
    avg_rank = sum(ranks) / len(ranks)            # ~1..5
    # weaker average quality -> higher opportunity
    quality_opp = (5 - avg_rank) / 4 * 100        # 0..100
    large_share /= len(services)
    # lots of strong large groups -> tougher market, trim opportunity
    market_adj = -20 * large_share
    return round(max(0, min(100, quality_opp + market_adj)), 0)
