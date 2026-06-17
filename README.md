# West Melbourne Childcare Acquisition Intelligence — Streamlit MVP

A decision-support tool that screens west-Melbourne suburbs and answers one
question: **is this suburb a good childcare acquisition opportunity or not?**

Design principle: **no number without provenance.** Every value carries a
source, link, retrieved date, and a confidence badge (High / Medium / Low /
DEMO / Missing). Illustrative values are tagged **DEMO** in red and can never
be mistaken for real data. The app never invents missing data — it tells you
how to load the real source.

---

## 1. System architecture

```
Browser ── Streamlit (app.py, 8 pages, single process)
                │
   ┌────────────┼─────────────────────────────┐
   │            │                              │
 lib/        connectors/                    data/
 provenance  acecqa.py    (supply, NQS)     seed_suburbs.py  (real ref facts + DEMO demos)
 geo         datasources  (ABS/schools/      acecqa_services.csv      ← you drop the real register
 demand                    planning/listings) acecqa_services.SAMPLE.csv (column template)
 financial   analysis.py  (competition,       abs_<suburb>.csv         ← optional ABS DataPack
 scoring                   target scoring)     vic_schools.csv          ← optional DataVic schools
```

No backend server, no build step. Streamlit reruns `app.py` top-to-bottom on
each interaction; the analysis result is held in `st.session_state`.

## 2. Data model (in-memory; SQLite optional later)

The core record is the **DataPoint**: `{value, source{name,url,retrieved,
last_updated,method}, confidence, unit, warning}`. Everything the UI shows is
a DataPoint, so provenance travels with the value. Composite records:

- **Service** (one childcare centre): name, service_type, provider,
  approval_status, nqs_rating, address, suburb, postcode, places, lat, lng,
  phone, distance_km.
- **Suburb** (seed reference): name, postcode, lga, sa3, lat, lng + DEMO
  demographics tuple `(population, children_0_4, children_5_9, median_income,
  growth_pct)`.

To add caching later, mirror these as SQLite tables `suburbs`, `services`,
`fetch_log(source, retrieved_at, status)` — the schema is already implied by
the dataclasses.

## 3. Data source connector plan

| Source | Module | Real-data path | Confidence |
|---|---|---|---|
| ACECQA National Registers (supply, NQS, type, provider, status) | `connectors/acecqa.py` | drop export to `data/acecqa_services.csv` **or** set `ACECQA_REGISTER_URL` | High when loaded |
| StartingBlocks (fees/vacancy supplement) | manual | fill fees/vacancy; tag LOW if scraped | Low–Medium |
| ABS Census 2021 (demographics) | `connectors/abs_api.py` (live SDMX-JSON) → `datasources.py` | **live ABS Data API** once IDs confirmed via the Page 8 discovery panel; else drop DataPack to `data/abs_<suburb>.csv` | High when connected |
| DataVic Victorian School Locations | `connectors/datasources.py:nearby_schools` | drop CSV to `data/vic_schools.csv` | High when loaded |
| VicPlan / Vicmap Planning (zoning) | `connectors/datasources.py:planning_risk` | per-address lookup link; WFS for automation | Manual |
| Business-for-sale listings | `connectors/datasources.py:business_listings` | **disabled** — respects site Terms of Use | Low |
| OSM Nominatim (geocoding) | `lib/geo.py` | live, free, rate-limited; falls back to seed coords | Medium |

The ACECQA register is the authoritative source for ratings/type/status, so
the file-drop path is the recommended way to get real supply data instantly.

## 4. Scoring methodology

`Childcare Acquisition Attractiveness Score` = weighted blend of seven 0–100
sub-scores: demand 25%, supply gap 20%, growth 15%, competitor opportunity
15%, school/family 10%, affordability 10%, planning risk 5%.

Bands: 85–100 Strong buy · 70–84 Attractive · 55–69 Possible · 40–54 Risky ·
<40 Avoid. **Crucially**, the score also reports overall **data confidence**;
if inputs are DEMO/Missing the recommendation becomes *"Insufficient real
data — load live sources before deciding,"* so a pretty number built on
placeholders can't masquerade as a verdict.

## 5–7. Run locally

```bash
cd childcare-intel
python3 -m venv .venv && source .venv/bin/activate     # optional
pip install -r requirements.txt
streamlit run app.py
```
Open the local URL Streamlit prints (usually http://localhost:8501).

**Make it real (2 minutes):**
1. Download the ACECQA Approved Services register from
   <https://www.acecqa.gov.au/resources/national-registers>, save as
   `data/acecqa_services.csv` (see `acecqa_services.SAMPLE.csv` for columns).
2. (Optional) Drop `data/vic_schools.csv` from DataVic and
   `data/abs_<suburb>.csv` from the ABS for real schools/demographics.
3. Re-run a search — supply/competition/targets now show **High** confidence.

## 8. Deploy online (shareable link)

**Streamlit Community Cloud (recommended, free):**
1. Push this folder to a GitHub repo.
2. <https://share.streamlit.io> → New app → pick repo → main file `app.py`.
3. Share the `*.streamlit.app` URL with your friend.

Alternatives: **Render** / **Railway** with start command
`streamlit run app.py --server.port $PORT --server.address 0.0.0.0`.

> Note: `data/*.csv` you add locally must be committed (or uploaded via a file
> uploader you add) for the deployed app to see them.

## 9. Worked example (tested)

Search `3029` (Tarneit) with the SAMPLE register loaded → 3 services parsed,
293 approved places, quality split 1 Exceeding / 1 Meeting / 1 Working
Towards, top acquisition target = the independent "Working Towards" centre
(98 places, score 80/100: independent + turnaround upside + scale + in
catchment). Without the register the app correctly returns demand *Unknown*
and flags the score as built on incomplete data.

## 10. Improvement roadmap

1. **Auto-refresh + SQLite cache** with a `fetch_log` and the 24h/monthly/
   weekly freshness rules enforced programmatically.
2. **ABS Data API (DONE — needs one runtime confirmation).** `connectors/
   abs_api.py` is a live SDMX-JSON client + parser (tested against both 1.0
   and 2.0 response shapes). To switch demographics from DEMO to real:
   open **Page 8 → Live ABS Data API**, click *Run ABS connectivity diagnose*,
   use *List matching dataflows* (filter `C21`) to find the Census age/income
   dataflow IDs, use *Resolve* to get the suburb's ASGS region code, then save
   the verified config. Re-run the search — demographics now load live with
   High confidence and the real retrieved timestamp. (Dataflow IDs and region
   codes are confirmed at runtime rather than hardcoded, so the tool never
   ships fabricated identifiers.)
3. **VIF / .id population forecasts** for growth-adjusted future demand.
4. **Vicmap Planning WFS** to auto-resolve zone/overlays and child-care
   permissibility per address.
5. **Fees & vacancy** from StartingBlocks (clearly labelled LOW confidence).
6. **PDF export** of the one-page acquisition report.
7. **LLM summary** (optional) to draft the written investment narrative from
   the structured DataPoints.
8. **Next.js production rebuild** once the data layer is proven.

---

### Honesty notes
- Demographics ship as **DEMO** placeholders so the app runs end-to-end; they
  are not real and the UI says so. Load ABS data before any decision.
- Business-for-sale scraping is intentionally disabled (Terms of Use).
- Financial outputs are estimates from your assumptions — verify with an
  accountant, broker, lawyer, lease review, payroll, CCS data and full DD.
