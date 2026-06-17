"""
connectors/datasources.py
-------------------------
Thin connectors for the remaining sources. Each returns real data when a
live source / local file is available, and a clearly-flagged DEMO or
MISSING result otherwise. None of them fabricate real-looking numbers.
"""
from __future__ import annotations
import os
from typing import List, Optional, Tuple

import pandas as pd

from provenance import DataPoint, Source, Confidence, Method
from geo import haversine_km

DATA_DIR = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------
# ABS Census (demographics)
# --------------------------------------------------------------------------
# Real path: drop ABS Census DataPacks / TableBuilder CSV for the suburb (SAL)
# or SA2 into data/abs_<suburb>.csv, OR query the ABS Data API at runtime.
# Reference: https://www.abs.gov.au/census  (2021 is the latest released Census)
def census_demographics(suburb_key: str, demo_tuple, source_label: str):
    """
    Resolution order (first real source wins; nothing is fabricated):
      1. LIVE ABS Data API (SDMX-JSON) if a verified config exists      -> HIGH
      2. Local ABS DataPack CSV at data/abs_<suburb>.csv                 -> HIGH
      3. DEMO placeholders from seed_suburbs (loudly flagged)            -> DEMO
    demo_tuple = (population, children_0_4, children_5_9, median_income, growth_pct)
    """
    # 1) live ABS Data API
    try:
        import abs_api
        live = abs_api.fetch_demographics(suburb_key)
        if live:
            # ensure all expected keys exist (fetch_demographics backfills Missing)
            return live
    except Exception:
        pass  # fall through to file / demo; never fabricate

    # 2) local DataPack CSV
    local = os.path.join(DATA_DIR, f"abs_{suburb_key.replace(' ', '_')}.csv")
    if os.path.exists(local):
        try:
            df = pd.read_csv(local)
            # expected single-row with named columns
            row = df.iloc[0]
            src = Source(name="ABS Census 2021 (local DataPack)",
                         url="https://www.abs.gov.au/census",
                         retrieved=Source.now(), last_updated="2021 Census",
                         method=Method.DOWNLOAD)
            return {
                "population": DataPoint(int(row["population"]), src, Confidence.HIGH, "people"),
                "children_0_4": DataPoint(int(row["children_0_4"]), src, Confidence.HIGH),
                "children_5_9": DataPoint(int(row["children_5_9"]), src, Confidence.HIGH),
                "median_income": DataPoint(int(row["median_income"]), src, Confidence.HIGH, "AUD/yr"),
                "growth_pct": DataPoint(float(row["growth_pct"]), src, Confidence.MEDIUM, "%/yr",
                                        warning="Growth is a trend estimate — confirm forecast version."),
            }
        except Exception:
            pass

    # DEMO fallback — loudly flagged
    pop, c04, c59, inc, growth = demo_tuple
    return {
        "population": DataPoint.demo(pop, "ABS population", "people"),
        "children_0_4": DataPoint.demo(c04, "ABS children 0-4"),
        "children_5_9": DataPoint.demo(c59, "ABS children 5-9"),
        "median_income": DataPoint.demo(inc, "ABS median household income", "AUD/yr"),
        "growth_pct": DataPoint.demo(growth, "population growth", "%/yr"),
    }


# --------------------------------------------------------------------------
# Victorian schools
# --------------------------------------------------------------------------
# Real path: download the DataVic "All Schools List / School Locations"
# dataset into data/vic_schools.csv (cols incl. School_Name, School_Type,
# Address, X/Longitude, Y/Latitude).
#   https://www.education.vic.gov.au/about/research/Pages/schoollocations.aspx
#   https://discover.data.vic.gov.au  (search "school locations")
SCHOOL_CSV = os.path.join(DATA_DIR, "vic_schools.csv")


def nearby_schools(lat: float, lng: float, radius_km: float = 5.0):
    if not os.path.exists(SCHOOL_CSV):
        return [], DataPoint.missing(
            "Victorian school locations",
            "Download DataVic 'School Locations' CSV to data/vic_schools.csv.")
    try:
        df = pd.read_csv(SCHOOL_CSV, dtype=str)
    except Exception:
        return [], DataPoint.missing("Victorian school locations", "Could not read vic_schools.csv.")

    def col(*names):
        for n in names:
            if n in df.columns: return n
        return None
    cn = col("School_Name", "SchoolName", "Name")
    ct = col("School_Type", "SchoolType", "Type")
    cx = col("X", "Longitude", "LONGITUDE", "Lng")
    cy = col("Y", "Latitude", "LATITUDE", "Lat")
    out = []
    for _, r in df.iterrows():
        try:
            slat, slng = float(r[cy]), float(r[cx])
        except (ValueError, TypeError):
            continue
        d = haversine_km(lat, lng, slat, slng)
        if d <= radius_km:
            out.append({"name": r.get(cn, "Unknown"), "type": r.get(ct, "Unknown"),
                        "distance_km": d, "lat": slat, "lng": slng})
    out.sort(key=lambda s: s["distance_km"])
    src = Source(name="DataVic — Victorian School Locations",
                 url="https://discover.data.vic.gov.au",
                 retrieved=Source.now(), method=Method.DOWNLOAD)
    return out, DataPoint(len(out), src, Confidence.HIGH, "schools")


# --------------------------------------------------------------------------
# Planning / zoning (VicPlan)
# --------------------------------------------------------------------------
# No clean public number to fetch automatically without the Vicmap Planning
# WFS/API. We return MISSING with the exact lookup path rather than guessing.
def planning_risk(address_or_suburb: str):
    return DataPoint.missing(
        "Zoning / overlays (VicPlan)",
        f"Check '{address_or_suburb}' manually at https://mapshare.vic.gov.au/vicplan/ "
        "for zone, overlays and whether a childcare (child care centre) use is "
        "Section 1/2/3. Wire the Vicmap Planning WFS for automation.")


# --------------------------------------------------------------------------
# Businesses for sale (third-party listings) — SCRAPE, label loudly
# --------------------------------------------------------------------------
def business_listings(suburb: str):
    """
    Intentionally NOT auto-scraped. Aggregator sites (e.g. business-for-sale
    marketplaces, commercial real-estate portals) have Terms of Use that often
    prohibit scraping. The honest MVP gives you the search links to check
    manually; if you have rights/an API, plug it in here and tag Method.SCRAPE
    with Confidence.LOW.
    """
    return [], DataPoint.missing(
        "Childcare businesses for sale",
        f"Check listings manually for '{suburb} childcare for sale'. "
        "Auto-scraping is disabled to respect site Terms of Use; any scraped "
        "data must be tagged LOW confidence and clearly marked.")
