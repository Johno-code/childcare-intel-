"""
financial.py
------------
100% real maths on the user's own assumptions. No external data.
Outputs revenue scenarios, EBITDA, net profit, payback, ROI,
break-even occupancy, max defensible purchase price, and a
sensitivity grid (occupancy x daily fee).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class FinancialInputs:
    licensed_places: int = 90
    occupancy_pct: float = 85.0
    avg_daily_fee: float = 145.0
    days_open: int = 250
    wage_pct: float = 55.0          # % of revenue
    rent_pct: float = 12.0
    food_pct: float = 4.0
    other_pct: float = 9.0
    purchase_price: float = 3_000_000.0
    ebitda_multiple: float = 5.0
    loan_amount: float = 2_000_000.0
    interest_rate: float = 7.0       # annual %
    target_roi_pct: float = 20.0     # used for max-price calc


def _revenue(places: int, occ_pct: float, fee: float, days: int) -> float:
    return places * (occ_pct / 100.0) * fee * days


def _ebitda(revenue: float, i: FinancialInputs) -> float:
    opex_pct = i.wage_pct + i.rent_pct + i.food_pct + i.other_pct
    return revenue * (1 - opex_pct / 100.0)


@dataclass
class FinancialResult:
    revenue: float
    revenue_scenarios: Dict[int, float]
    ebitda: float
    interest_cost: float
    net_profit: float
    ebitda_margin_pct: float
    payback_years: float
    roi_pct: float
    breakeven_occupancy_pct: float
    implied_value_at_multiple: float
    max_price_for_target_roi: float
    sensitivity: List[dict]
    warnings: List[str] = field(default_factory=list)


def run_model(i: FinancialInputs) -> FinancialResult:
    rev = _revenue(i.licensed_places, i.occupancy_pct, i.avg_daily_fee, i.days_open)
    scenarios = {
        occ: _revenue(i.licensed_places, occ, i.avg_daily_fee, i.days_open)
        for occ in (70, 80, 90, 95)
    }
    ebitda = _ebitda(rev, i)
    interest = i.loan_amount * i.interest_rate / 100.0
    net = ebitda - interest
    margin = (ebitda / rev * 100.0) if rev else 0.0
    payback = (i.purchase_price / ebitda) if ebitda > 0 else float("inf")
    equity = max(i.purchase_price - i.loan_amount, 1.0)
    roi = (net / equity * 100.0)

    # Break-even occupancy: occupancy where EBITDA == interest cost
    opex_pct = i.wage_pct + i.rent_pct + i.food_pct + i.other_pct
    rev_per_occ_pt = i.licensed_places * 0.01 * i.avg_daily_fee * i.days_open  # revenue per 1% occ
    contrib_per_occ_pt = rev_per_occ_pt * (1 - opex_pct / 100.0)
    be_occ = (interest / contrib_per_occ_pt) if contrib_per_occ_pt > 0 else float("inf")

    implied_value = ebitda * i.ebitda_multiple
    # Max price such that net_profit / equity >= target_roi, assuming same loan
    # net = ebitda - interest ; equity = price - loan ; roi = net/equity
    # price <= loan + net/(target_roi/100)
    max_price = (i.loan_amount + net / (i.target_roi_pct / 100.0)) if i.target_roi_pct > 0 else float("inf")

    # Sensitivity grid: EBITDA across occupancy x fee
    fees = [round(i.avg_daily_fee * m) for m in (0.9, 1.0, 1.1)]
    occs = [70, 80, 90, 95]
    grid = []
    for occ in occs:
        row = {"occupancy_%": occ}
        for f in fees:
            r = _revenue(i.licensed_places, occ, f, i.days_open)
            row[f"${f}/day EBITDA"] = round(_ebitda(r, i))
        grid.append(row)

    warns = []
    if opex_pct >= 100:
        warns.append("Operating cost % sums to ≥100% — model will show losses; check inputs.")
    if i.wage_pct < 45 or i.wage_pct > 70:
        warns.append("Wage % outside the typical 45–70% LDC range — verify against payroll.")
    if payback != float("inf") and payback > 12:
        warns.append("Payback >12 years — return looks weak at this price.")

    return FinancialResult(
        revenue=round(rev), revenue_scenarios={k: round(v) for k, v in scenarios.items()},
        ebitda=round(ebitda), interest_cost=round(interest), net_profit=round(net),
        ebitda_margin_pct=round(margin, 1), payback_years=round(payback, 1),
        roi_pct=round(roi, 1), breakeven_occupancy_pct=round(be_occ, 1),
        implied_value_at_multiple=round(implied_value),
        max_price_for_target_roi=round(max_price), sensitivity=grid, warnings=warns,
    )


DISCLAIMER = (
    "These are ESTIMATES from your assumptions only. Verify everything with an "
    "accountant, broker, lawyer, lease review, payroll records, CCS data, "
    "room-by-room occupancy reports and full due diligence before any offer."
)
