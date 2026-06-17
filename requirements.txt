"""
West Melbourne Childcare Acquisition Intelligence — Streamlit MVP
================================================================
Run:   streamlit run app.py

Honest-data design:
  * Every number carries a source + date + confidence badge.
  * DEMO values render with a red badge and a banner; they are NOT real.
  * Real supply data appears the moment you drop the ACECQA register into
    data/acecqa_services.csv (see README). Same for ABS and schools.
"""
from __future__ import annotations
import datetime as dt

import pandas as pd
import streamlit as st

from lib.provenance import (DataPoint, Source, Confidence, Method,
                            metric_with_source, badge_html)
from lib.demand import assess_demand
from lib.financial import FinancialInputs, run_model, DISCLAIMER
from lib.scoring import ScoreInputs, compute_score
from lib.geo import geocode
from data.seed_suburbs import SUBURBS, DEMO_DEMOGRAPHICS, resolve
from connectors.acecqa import get_services
from connectors import datasources as ds
import analysis

try:
    import plotly.express as px
    HAVE_PLOTLY = True
except Exception:
    HAVE_PLOTLY = False

st.set_page_config(page_title="Childcare Acquisition Intel — West Melbourne",
                   page_icon="🏫", layout="wide")

# --------------------------------------------------------------------------
# Worst-confidence helper
# --------------------------------------------------------------------------
_ORDER = [Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW,
          Confidence.DEMO, Confidence.MISSING]
def worst(*cs): return max(cs, key=lambda c: _ORDER.index(c))


# --------------------------------------------------------------------------
# Analysis runner (cached per inputs in session_state)
# --------------------------------------------------------------------------
def run_analysis(query: str, radius_km: float):
    key = resolve(query)
    if key is None:
        return None
    name, postcode, lga, sa3, lat, lng = SUBURBS[key]

    # try a live geocode to refine centre; fall back to seed coords
    geo = geocode(f"{name} {postcode}")
    used_live_geo = geo is not None
    if geo:
        lat, lng = geo

    demo = DEMO_DEMOGRAPHICS.get(key)
    demog = ds.census_demographics(key, demo, "seed-demo")

    supply = get_services(lat, lng, postcode, radius_km)
    schools, school_dp = ds.nearby_schools(lat, lng, radius_km)
    schools_3km = [s for s in schools if s["distance_km"] <= 3]
    planning = ds.planning_risk(name)
    listings, listings_dp = ds.business_listings(name)

    # demand
    total_places_dp = (DataPoint(supply.total_places, supply.source, supply.confidence, "places")
                       if supply.total_places is not None
                       else DataPoint.missing("Total approved places",
                                              "Load ACECQA register."))
    demand = assess_demand(demog["children_0_4"], total_places_dp,
                           demog["growth_pct"].value)

    # competition
    qbreak = analysis.quality_breakdown(supply.services)
    risk_table = analysis.competitor_risk_table(supply.services)
    targets = analysis.acquisition_targets(supply.services)
    comp_opp = analysis.competitor_opportunity_score(supply.services)

    # overall data confidence (drives whether the score is trustworthy)
    data_conf = worst(demog["children_0_4"].confidence, supply.confidence)

    score = compute_score(ScoreInputs(
        demand_strength=demand.growth_adjusted_strength,
        children_per_place=demand.children_per_place,
        pop_growth_pct=demog["growth_pct"].value,
        competitor_opportunity_0_100=comp_opp,
        schools_within_3km=len(schools_3km) if school_dp.confidence != Confidence.MISSING else None,
        median_income=demog["median_income"].value,
        avg_daily_fee=None,
        planning_risk="Unknown",
        data_confidence=data_conf,
    ))

    return dict(
        key=key, name=name, postcode=postcode, lga=lga, sa3=sa3,
        lat=lat, lng=lng, used_live_geo=used_live_geo, radius_km=radius_km,
        demog=demog, supply=supply, total_places_dp=total_places_dp,
        schools=schools, schools_3km=schools_3km, school_dp=school_dp,
        planning=planning, listings=listings, listings_dp=listings_dp,
        demand=demand, qbreak=qbreak, risk_table=risk_table,
        targets=targets, comp_opp=comp_opp, score=score,
        ran_at=Source.now(),
    )


# --------------------------------------------------------------------------
# Sidebar nav
# --------------------------------------------------------------------------
st.sidebar.title("🏫 Childcare Acquisition Intel")
st.sidebar.caption("West Melbourne MVP · provenance-first")
PAGE = st.sidebar.radio("Navigate", [
    "1 · Suburb Search",
    "2 · Executive Summary",
    "3 · Competition Map",
    "4 · Demand & Demographics",
    "5 · Schools & Family",
    "6 · Acquisition Targets",
    "7 · Financial Model",
    "8 · Data Sources & Freshness",
])

if "result" not in st.session_state:
    st.session_state.result = None


def need_result():
    if not st.session_state.result:
        st.info("Run an analysis on **Page 1 · Suburb Search** first.")
        return False
    return True


# ==========================================================================
# PAGE 1 — SEARCH
# ==========================================================================
if PAGE.startswith("1"):
    st.title("Suburb Search")
    st.caption("West Melbourne childcare acquisition screening. "
               "Enter a suburb or postcode and run the analysis.")
    c1, c2 = st.columns([3, 1])
    with c1:
        q = st.text_input("Suburb name or postcode",
                          placeholder="e.g. Tarneit, Werribee, 3029, 3030")
    with c2:
        radius = st.selectbox("Radius (km)", [3, 5, 7, 10], index=1)

    st.caption("Seeded suburbs: " + ", ".join(v[0] for v in SUBURBS.values()))

    if st.button("▶ Run analysis", type="primary"):
        if not q.strip():
            st.warning("Enter a suburb or postcode.")
        else:
            with st.spinner("Resolving location, pulling supply/demand, scoring…"):
                res = run_analysis(q, float(radius))
            if res is None:
                st.error(f"'{q}' not in the seeded west-Melbourne set. "
                         "Add it to data/seed_suburbs.py.")
            else:
                st.session_state.result = res
                st.success(f"Analysed {res['name']} {res['postcode']} "
                           f"({res['lga']}). Open Page 2 for the summary.")
                if res["supply"].confidence == Confidence.MISSING:
                    st.warning(res["supply"].warning)
                if res["demog"]["children_0_4"].confidence == Confidence.DEMO:
                    st.error("⚠ Demographics are DEMO placeholders. Load ABS data "
                             "before trusting any verdict (see Page 8).")


# ==========================================================================
# PAGE 2 — EXECUTIVE SUMMARY
# ==========================================================================
elif PAGE.startswith("2"):
    st.title("Executive Summary")
    if need_result():
        r = st.session_state.result
        sc = r["score"]
        st.subheader(f"{r['name']} · {r['postcode']} · {r['lga']}")
        if sc.confidence_warning:
            st.error(sc.confidence_warning)

        a, b, c = st.columns([1, 1, 2])
        a.metric("Acquisition Score", f"{sc.total}/100")
        b.metric("Band", sc.band.split(" — ")[0])
        c.metric("Recommendation", sc.recommendation)
        st.markdown(f"Overall data confidence: {badge_html(sc.data_confidence)}",
                    unsafe_allow_html=True)

        st.divider()
        l, rr = st.columns(2)
        with l:
            st.markdown("**Top reasons**")
            for x in sc.reasons: st.markdown(f"- {x}")
        with rr:
            st.markdown("**Top risks**")
            for x in sc.risks: st.markdown(f"- {x}")

        st.divider()
        st.markdown("**Demand vs supply**")
        d = r["demand"]
        k1, k2, k3, k4 = st.columns(4)
        with k1: metric_with_source(st, "Children 0–4", r["demog"]["children_0_4"])
        with k2: metric_with_source(st, "Total approved places", r["total_places_dp"])
        with k3:
            cpp = d.children_per_place
            st.metric("Children per place", f"{cpp}" if cpp is not None else "—")
        with k4:
            st.metric("Demand (growth-adj.)", d.growth_adjusted_strength)

        st.divider()
        best = r["targets"][0] if r["targets"] else None
        st.markdown("**Biggest opportunity**")
        if best:
            st.success(f"Top acquisition target: **{best['Centre']}** "
                       f"(score {best['Target score']}/100) — {best['Why']}")
        else:
            st.info("No competitor centres loaded — load the ACECQA register to find targets.")
        st.markdown("**Biggest risk**")
        st.warning(sc.risks[0] if sc.risks else "Verify all inputs with real data.")


# ==========================================================================
# PAGE 3 — COMPETITION MAP
# ==========================================================================
elif PAGE.startswith("3"):
    st.title("Childcare Competition Map")
    if need_result():
        r = st.session_state.result
        sv = r["supply"].services
        if not sv:
            st.warning(r["supply"].warning or "No services loaded.")
        else:
            rows = []
            for s in sv:
                if s.lat and s.lng:
                    rows.append(dict(lat=s.lat, lon=s.lng, name=s.name,
                                     rating=s.nqs_rating, type=s.service_type,
                                     provider=s.provider, distance=s.distance_km))
            # centre point
            rows.append(dict(lat=r["lat"], lon=r["lng"], name=f"◎ {r['name']} centre",
                             rating="(catchment centre)", type="", provider="", distance=0))
            dfm = pd.DataFrame(rows)
            if HAVE_PLOTLY and dfm["lat"].notna().any():
                fig = px.scatter_mapbox(
                    dfm, lat="lat", lon="lon", color="rating",
                    hover_name="name", hover_data=["type", "provider", "distance"],
                    zoom=11, height=520)
                fig.update_layout(mapbox_style="open-street-map",
                                  margin=dict(l=0, r=0, t=0, b=0))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.map(dfm.rename(columns={"lon": "lon"})[["lat", "lon"]])
                st.caption("Install plotly for coloured rating markers.")

            st.markdown("**All services in radius**")
            st.dataframe(pd.DataFrame([{
                "Centre": s.name, "Type": s.service_type, "Provider": s.provider,
                "Rating": s.nqs_rating, "Status": s.approval_status,
                "Places": s.places, "Dist km": s.distance_km, "Address": s.address,
            } for s in sv]), use_container_width=True, hide_index=True)


# ==========================================================================
# PAGE 4 — DEMAND & DEMOGRAPHICS
# ==========================================================================
elif PAGE.startswith("4"):
    st.title("Demand & Demographics")
    if need_result():
        r = st.session_state.result
        dg = r["demog"]
        if dg["children_0_4"].confidence == Confidence.DEMO:
            st.error("⚠ All demographics on this page are DEMO placeholders — not real.")
        cols = st.columns(3)
        with cols[0]: metric_with_source(st, "Population", dg["population"])
        with cols[1]: metric_with_source(st, "Children 0–4", dg["children_0_4"])
        with cols[2]: metric_with_source(st, "Children 5–9", dg["children_5_9"])
        cols2 = st.columns(3)
        with cols2[0]: metric_with_source(st, "Median household income", dg["median_income"])
        with cols2[1]: metric_with_source(st, "Population growth", dg["growth_pct"])
        with cols2[2]:
            d = r["demand"]
            st.markdown(f"**Demand strength** {badge_html(d.confidence)}",
                        unsafe_allow_html=True)
            st.markdown(f"<span style='font-size:1.4rem;font-weight:700'>"
                        f"{d.growth_adjusted_strength}</span>", unsafe_allow_html=True)
            st.caption(d.notes)

        st.divider()
        d = r["demand"]
        m = st.columns(4)
        m[0].metric("Children per place", d.children_per_place if d.children_per_place else "—")
        m[1].metric("Places / 100 children", d.places_per_100_children if d.places_per_100_children else "—")
        m[2].metric("Est. unmet places", d.estimated_unmet_places if d.estimated_unmet_places is not None else "—")
        m[3].metric("Base demand", d.strength)
        st.caption("Forecasts: label the forecast version when you wire VIF/.id "
                   "population projections (see roadmap).")


# ==========================================================================
# PAGE 5 — SCHOOLS & FAMILY
# ==========================================================================
elif PAGE.startswith("5"):
    st.title("Schools & Family Drivers")
    if need_result():
        r = st.session_state.result
        if r["school_dp"].confidence == Confidence.MISSING:
            st.warning(r["school_dp"].warning)
        else:
            within = {km: len([s for s in r["schools"] if s["distance_km"] <= km])
                      for km in (1, 3, 5)}
            c = st.columns(3)
            c[0].metric("Schools ≤1 km", within[1])
            c[1].metric("Schools ≤3 km", within[3])
            c[2].metric("Schools ≤5 km", within[5])
            st.dataframe(pd.DataFrame([{
                "School": s["name"], "Type": s["type"], "Dist km": s["distance_km"],
            } for s in r["schools"]]), use_container_width=True, hide_index=True)


# ==========================================================================
# PAGE 6 — ACQUISITION TARGETS
# ==========================================================================
elif PAGE.startswith("6"):
    st.title("Acquisition Targets")
    if need_result():
        r = st.session_state.result
        st.markdown("**Possible target ranking** (existing centres scored for buy-appeal)")
        if r["targets"]:
            st.dataframe(pd.DataFrame(r["targets"]), use_container_width=True, hide_index=True)
        else:
            st.warning("No centres loaded — load the ACECQA register (Page 8 / README).")

        st.divider()
        st.markdown("**Competitor risk table**")
        if r["risk_table"]:
            st.dataframe(pd.DataFrame(r["risk_table"]), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**Businesses for sale**")
        st.info(r["listings_dp"].warning)

        st.divider()
        st.markdown("**Due-diligence checklist**")
        for item in [
            "Request last 3 years financials", "Verify occupancy by room and age group",
            "Check CCS income", "Check wage percentage",
            "Check lease terms and rent increases", "Check staff qualifications and retention",
            "Check NQS rating and compliance history", "Check enrolment pipeline",
            "Check waiting list", "Check local competition",
            "Check maintenance / capex needs", "Check council / planning restrictions",
            "Get accountant and lawyer review",
        ]:
            st.checkbox(item, key=f"dd_{item}")


# ==========================================================================
# PAGE 7 — FINANCIAL MODEL
# ==========================================================================
elif PAGE.startswith("7"):
    st.title("Financial Opportunity Model")
    st.caption("Real maths on YOUR assumptions. No external data is used here.")
    with st.form("fin"):
        c = st.columns(4)
        places = c[0].number_input("Licensed places", 10, 300, 90)
        occ = c[1].number_input("Occupancy %", 10.0, 100.0, 85.0)
        fee = c[2].number_input("Avg daily fee $", 50.0, 250.0, 145.0)
        days = c[3].number_input("Days open / yr", 200, 365, 250)
        c = st.columns(4)
        wage = c[0].number_input("Wage % of rev", 0.0, 100.0, 55.0)
        rent = c[1].number_input("Rent %", 0.0, 50.0, 12.0)
        food = c[2].number_input("Food %", 0.0, 20.0, 4.0)
        other = c[3].number_input("Other %", 0.0, 40.0, 9.0)
        c = st.columns(4)
        price = c[0].number_input("Purchase price $", 0.0, 50_000_000.0, 3_000_000.0, step=50000.0)
        mult = c[1].number_input("EBITDA multiple", 0.0, 15.0, 5.0)
        loan = c[2].number_input("Loan amount $", 0.0, 50_000_000.0, 2_000_000.0, step=50000.0)
        rate = c[3].number_input("Interest %", 0.0, 20.0, 7.0)
        target_roi = st.number_input("Target ROI % (for max-price calc)", 0.0, 100.0, 20.0)
        go = st.form_submit_button("Calculate", type="primary")

    if go:
        res = run_model(FinancialInputs(places, occ, fee, days, wage, rent, food,
                                        other, price, mult, loan, rate, target_roi))
        m = st.columns(4)
        m[0].metric("Revenue (at your occ.)", f"${res.revenue:,.0f}")
        m[1].metric("EBITDA", f"${res.ebitda:,.0f}", f"{res.ebitda_margin_pct}% margin")
        m[2].metric("Net profit (post-interest)", f"${res.net_profit:,.0f}")
        m[3].metric("ROI on equity", f"{res.roi_pct}%")
        m = st.columns(4)
        m[0].metric("Payback", f"{res.payback_years} yrs")
        m[1].metric("Break-even occupancy", f"{res.breakeven_occupancy_pct}%")
        m[2].metric("Implied value @ multiple", f"${res.implied_value_at_multiple:,.0f}")
        m[3].metric("Max price @ target ROI", f"${res.max_price_for_target_roi:,.0f}")

        st.markdown("**Revenue by occupancy scenario**")
        st.dataframe(pd.DataFrame([{"Occupancy %": k, "Revenue $": f"{v:,.0f}"}
                                   for k, v in res.revenue_scenarios.items()]),
                     hide_index=True, use_container_width=True)
        st.markdown("**Sensitivity — EBITDA by occupancy × daily fee**")
        st.dataframe(pd.DataFrame(res.sensitivity), hide_index=True, use_container_width=True)
        for w in res.warnings:
            st.warning(w)
        st.error(DISCLAIMER)


# ==========================================================================
# PAGE 8 — DATA SOURCES & FRESHNESS
# ==========================================================================
elif PAGE.startswith("8"):
    st.title("Data Sources & Freshness")
    st.caption("Every source, its method, confidence and how to make it real.")
    if not st.session_state.result:
        st.info("Run an analysis to populate live freshness timestamps.")
    rows = [
        ["ACECQA National Registers (supply, NQS, type, provider)",
         "https://www.acecqa.gov.au/resources/national-registers",
         "download / file-drop", "High when loaded",
         "Drop export to data/acecqa_services.csv, or set ACECQA_REGISTER_URL"],
        ["StartingBlocks (fees/vacancy supplement)",
         "https://www.startingblocks.gov.au", "manual/scrape", "Low–Medium",
         "Use to fill fees & vacancy; label LOW if scraped"],
        ["ABS Census 2021 (demographics)",
         "https://www.abs.gov.au/census", "download / API", "High when loaded",
         "Drop DataPack to data/abs_<suburb>.csv; 2021 is latest Census"],
        ["DataVic — Victorian School Locations",
         "https://discover.data.vic.gov.au", "download", "High when loaded",
         "Drop CSV to data/vic_schools.csv"],
        ["VicPlan / Vicmap Planning (zoning, overlays)",
         "https://mapshare.vic.gov.au/vicplan/", "manual / WFS", "Manual",
         "Check per-address; wire WFS for automation"],
        ["Business-for-sale listings",
         "(various marketplaces)", "manual / scrape", "Low",
         "Disabled by default — respect site Terms of Use"],
        ["OSM Nominatim (geocoding)",
         "https://nominatim.openstreetmap.org", "api", "Medium",
         "Free, rate-limited; falls back to seed coords"],
    ]
    st.dataframe(pd.DataFrame(rows, columns=[
        "Source", "Link", "Method", "Confidence", "How to make it real / fresh"]),
        use_container_width=True, hide_index=True)

    if st.session_state.result:
        r = st.session_state.result
        st.divider()
        st.markdown(f"**This report**")
        st.caption(f"Run at: {r['ran_at']}")
        st.caption(f"Geocode: {'live OSM' if r['used_live_geo'] else 'seed fallback coords'}")
        st.caption(f"Supply confidence: {r['supply'].confidence.value} — {r['supply'].warning or 'ok'}")
        st.caption(f"Demographics confidence: {r['demog']['children_0_4'].confidence.value}")
        st.markdown("**Freshness rules enforced:** ACECQA cache ≤24h / refresh on search · "
                    "schools monthly · ABS labelled by Census year · listings on-demand · "
                    "planning weekly/on-demand. Blocked sources show a warning and never invent data.")
