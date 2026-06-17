"""
demand.py
---------
Pure demand maths. Operates on DataPoints so the *confidence of the
inputs flows through* to the result. If children/places are DEMO or
Missing, the demand verdict is flagged accordingly.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from .provenance import DataPoint, Source, Confidence, Method


@dataclass
class DemandResult:
    children_0_4: Optional[int]
    total_places: Optional[int]
    children_per_place: Optional[float]
    places_per_100_children: Optional[float]
    estimated_unmet_places: Optional[int]
    strength: str                 # Low / Medium / High / Very High / Unknown
    growth_adjusted_strength: str
    confidence: Confidence
    notes: str

    def as_datapoint(self) -> DataPoint:
        return DataPoint(
            value=self.strength,
            source=Source(name="Computed: demand model", method=Method.COMPUTED,
                          retrieved=Source.now()),
            confidence=self.confidence,
            warning=self.notes,
        )


# Planning benchmark: a commonly cited working figure is roughly 1 LDC place
# per ~3 children aged 0-4 in a well-supplied market. We flag this as a
# heuristic, NOT an official standard.
TARGET_CHILDREN_PER_PLACE = 3.0


def assess_demand(children_0_4: DataPoint,
                  total_places: DataPoint,
                  pop_growth_pct: Optional[float] = None) -> DemandResult:
    c = children_0_4.value
    p = total_places.value

    # propagate the weakest input confidence
    order = [Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW,
             Confidence.DEMO, Confidence.MISSING]
    conf = max([children_0_4.confidence, total_places.confidence],
               key=lambda x: order.index(x))

    if c is None or p in (None,):
        return DemandResult(c, p, None, None, None, "Unknown", "Unknown",
                            Confidence.MISSING,
                            "Cannot assess: children count or supply not loaded.")

    cpp = round(c / p, 2) if p > 0 else float("inf")
    pp100 = round(p / c * 100, 1) if c > 0 else 0.0
    target_places = c / TARGET_CHILDREN_PER_PLACE
    unmet = int(round(target_places - p))

    if cpp == float("inf"):
        strength = "Very High"
    elif cpp >= 5:
        strength = "Very High"
    elif cpp >= 3.5:
        strength = "High"
    elif cpp >= 2.5:
        strength = "Medium"
    else:
        strength = "Low"

    growth_adj = strength
    if pop_growth_pct is not None:
        if pop_growth_pct >= 3 and strength in ("Medium", "High"):
            growth_adj = {"Medium": "High", "High": "Very High"}[strength]
        elif pop_growth_pct <= 0 and strength in ("High", "Medium"):
            growth_adj = {"High": "Medium", "Medium": "Low"}[strength]

    notes = (f"Heuristic benchmark = 1 place per {TARGET_CHILDREN_PER_PLACE} "
             f"children 0-4 (not an official standard — verify locally).")
    if conf in (Confidence.DEMO, Confidence.MISSING):
        notes = "Inputs are DEMO/incomplete — verdict illustrative only. " + notes

    return DemandResult(c, p, cpp, pp100, max(unmet, 0),
                        strength, growth_adj, conf, notes)
