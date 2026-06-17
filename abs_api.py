"""
connectors/abs_api.py
---------------------
Live client for the ABS Data API (https://data.api.abs.gov.au), which serves
SDMX-JSON. Used to pull real Census 2021 demographics so the app stops relying
on DEMO placeholders.

WHY THERE IS A "VERIFY AT RUNTIME" STEP
---------------------------------------
The SDMX-JSON *wire format* is stable and fully parsed here (tested). What is
NOT safe to hardcode blindly is:
   * the exact dataflow IDs for Census tables (they evolve), and
   * the ASGS region codes for each suburb (SA2/LGA codes are not memorised
     facts and must not be fabricated).
So this module ships discovery tools — discover_dataflows(), resolve_region(),
diagnose() — that you run once to confirm the real IDs. Confirmed IDs are
saved to data/abs_config.json and reused. Until confirmed, the app falls back
to clearly-flagged DEMO data. Nothing is invented.

Docs: https://www.abs.gov.au/about/data-services/application-programming-interfaces-apis/data-api-user-guide
"""
from __future__ import annotations
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

from provenance import DataPoint, Source, Confidence, Method

BASE = "https://data.api.abs.gov.au"
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(DATA_DIR, ".abs_cache")
CONFIG_PATH = os.path.join(DATA_DIR, "abs_config.json")
HEADERS = {"Accept": "application/vnd.sdmx.data+json",
           "User-Agent": "childcare-acquisition-intel/0.2"}

# Candidate Census dataflow IDs to *verify* with discover_dataflows().
# These are documented patterns, treated as guesses until confirmed at runtime.
CANDIDATE_FLOWS = {
    "population_by_age": ["C21_G04_SA2", "C21_T01_SA2", "ABS_C21_T04_SA2"],
    "household_income":  ["C21_G33_SA2", "C21_G02_SA2"],
}


# --------------------------------------------------------------------------
# tiny disk cache (Census is static, so caching is safe; we still stamp time)
# --------------------------------------------------------------------------
def _cache_path(url: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, hashlib.md5(url.encode()).hexdigest() + ".json")


def _get(url: str, max_age_h: float = 24 * 30) -> Tuple[Optional[dict], str]:
    """GET with cache. Returns (json|None, status_note)."""
    cp = _cache_path(url)
    if os.path.exists(cp):
        age_h = (time.time() - os.path.getmtime(cp)) / 3600.0
        if age_h <= max_age_h:
            try:
                with open(cp) as f:
                    return json.load(f), f"cache ({age_h:.0f}h old)"
            except Exception:
                pass
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        with open(cp, "w") as f:
            json.dump(data, f)
        return data, "live"
    except Exception as e:
        return None, f"error: {e}"


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# --------------------------------------------------------------------------
# SDMX-JSON parser (handles both 1.0 'structure' and 2.0 'structures')
# --------------------------------------------------------------------------
def parse_sdmx_json(payload: dict) -> List[dict]:
    """
    Flatten an SDMX-JSON data message into a list of observations:
      [{dim_id: value_id, ..., "value": float}, ...]
    Works for SDMX-JSON 1.0 (data.structure) and 2.0 (data.structures[0]).
    """
    data = payload.get("data", payload)
    datasets = data.get("dataSets") or []
    if not datasets:
        return []

    # structure can be singular ('structure') or a list ('structures')
    struct = data.get("structure")
    if struct is None:
        structs = data.get("structures") or []
        struct = structs[0] if structs else {}

    dims = struct.get("dimensions", {})
    series_dims = dims.get("series", []) or []
    obs_dims = dims.get("observation", []) or []
    # ordered dimension list as used in the observation key "i:j:k:..."
    ordered = series_dims + obs_dims

    def value_at(dim_index: int, val_index: int):
        vals = ordered[dim_index].get("values", [])
        if 0 <= val_index < len(vals):
            v = vals[val_index]
            return v.get("id"), v.get("name")
        return None, None

    out: List[dict] = []
    ds = datasets[0]

    # SDMX-JSON 2.0 flat 'observations' OR 1.0 with 'series'
    if "observations" in ds and ds["observations"]:
        for key, arr in ds["observations"].items():
            idx = [int(x) for x in key.split(":")]
            row = {}
            for d, vi in enumerate(idx):
                did = ordered[d].get("id")
                vid, vname = value_at(d, vi)
                row[did] = vid
                row[f"{did}__name"] = vname
            row["value"] = arr[0] if isinstance(arr, list) and arr else arr
            out.append(row)
    elif "series" in ds:
        for skey, sobj in ds["series"].items():
            sidx = [int(x) for x in skey.split(":")]
            base = {}
            for d, vi in enumerate(sidx):
                did = series_dims[d].get("id")
                vid, vname = value_at(d, vi)
                base[did] = vid
                base[f"{did}__name"] = vname
            for okey, arr in sobj.get("observations", {}).items():
                oidx = [int(x) for x in okey.split(":")]
                row = dict(base)
                for d, vi in enumerate(oidx):
                    did = obs_dims[d].get("id")
                    vid, vname = value_at(len(series_dims) + d, vi)
                    row[did] = vid
                    row[f"{did}__name"] = vname
                row["value"] = arr[0] if isinstance(arr, list) and arr else arr
                out.append(row)
    return out


# --------------------------------------------------------------------------
# Discovery tools (run these once to confirm IDs; I cannot from the sandbox)
# --------------------------------------------------------------------------
def discover_dataflows(filter_substr: str = "C21") -> List[dict]:
    """List ABS dataflows whose id/name contains filter_substr (e.g. 'C21')."""
    url = f"{BASE}/rest/dataflow/ABS?detail=allstubs"
    payload, note = _get(url, max_age_h=24 * 7)
    if not payload:
        return [{"error": note}]
    flows = []
    data = payload.get("data", payload)
    structs = data.get("dataflows") or (data.get("structures") or [])
    if isinstance(structs, dict):
        structs = structs.get("dataflows", [])
    for fl in structs:
        fid = fl.get("id", "")
        name = (fl.get("name") or
                (fl.get("names", {}) or {}).get("en", "") if isinstance(fl.get("names"), dict) else "")
        if filter_substr.lower() in (fid + str(name)).lower():
            flows.append({"id": fid, "name": name, "_status": note})
    return flows or [{"note": f"no dataflows matched '{filter_substr}' ({note})"}]


def resolve_region(name: str, codelist: str = "CL_ASGS_2021_SA2") -> List[dict]:
    """
    Find ASGS region codes whose name matches `name`. Returns candidates so a
    human confirms — we never auto-pick and never fabricate a code.
    """
    url = f"{BASE}/rest/codelist/ABS/{codelist}"
    payload, note = _get(url, max_age_h=24 * 30)
    if not payload:
        return [{"error": note, "tried_codelist": codelist}]
    data = payload.get("data", payload)
    cls = data.get("codelists") or (data.get("structures") or [])
    if isinstance(cls, dict):
        cls = cls.get("codelists", [])
    matches = []
    nl = name.strip().lower()
    for cl in cls:
        for code in cl.get("codes", []):
            cid = code.get("id", "")
            cname = code.get("name") or (code.get("names", {}) or {}).get("en", "")
            if nl in str(cname).lower():
                matches.append({"code": cid, "name": cname, "codelist": codelist})
    return matches or [{"note": f"no region matched '{name}' in {codelist} ({note})"}]


def diagnose() -> dict:
    """One-call health check: connectivity + candidate flows + a sample region."""
    rep = {"base": BASE, "checked": Source.now()}
    test, note = _get(f"{BASE}/rest/dataflow/ABS?detail=allstubs", max_age_h=0.01)
    rep["connectivity"] = note
    rep["census_dataflows_sample"] = discover_dataflows("C21")[:8]
    rep["region_lookup_sample_tarneit"] = resolve_region("Tarneit")[:5]
    rep["saved_config"] = load_config()
    return rep


# --------------------------------------------------------------------------
# High-level demographics fetch (real -> HIGH confidence; else None)
# --------------------------------------------------------------------------
def fetch_demographics(suburb_key: str) -> Optional[Dict[str, DataPoint]]:
    """
    Returns real DataPoints if a verified config exists for this suburb,
    else None so the caller can fall back to DEMO. Config shape in
    data/abs_config.json:
      {
        "suburbs": {
          "tarneit": {
            "region_code": "SA2_CODE", "region_type": "SA2",
            "pop_flow": "C21_G04_SA2", "income_flow": "C21_G02_SA2",
            "datakey_pop": "...", "datakey_income": "..."
          }
        }
      }
    Each datakey is the SDMX key path the user confirmed via the API explorer.
    """
    cfg = load_config().get("suburbs", {}).get(suburb_key)
    if not cfg or not cfg.get("region_code"):
        return None

    src = Source(name="ABS Census 2021 via ABS Data API (SDMX-JSON)",
                 url=f"{BASE}/rest/data/", retrieved=Source.now(),
                 last_updated="2021 Census", method=Method.API)

    results: Dict[str, DataPoint] = {}

    def pull(flow, datakey):
        url = f"{BASE}/rest/data/{flow}/{datakey}?dimensionAtObservation=AllDimensions"
        payload, note = _get(url)
        if not payload:
            return None, note
        return parse_sdmx_json(payload), note

    # population / age bands
    if cfg.get("pop_flow") and cfg.get("datakey_pop"):
        obs, note = pull(cfg["pop_flow"], cfg["datakey_pop"])
        if obs:
            # The user's datakey should already pin the region; we map age codes.
            age_codes = cfg.get("age_codes", {})  # {"0_4": ["A0_4"], "5_9": [...], "total": [...]}
            def sum_age(codes):
                if not codes:
                    return None
                tot = 0.0; hit = False
                for o in obs:
                    if o.get(cfg.get("age_dim", "AGE")) in codes and o.get("value") is not None:
                        tot += float(o["value"]); hit = True
                return tot if hit else None
            c04 = sum_age(age_codes.get("0_4"))
            c59 = sum_age(age_codes.get("5_9"))
            pop = sum_age(age_codes.get("total"))
            if pop is not None:
                results["population"] = DataPoint(int(pop), src, Confidence.HIGH, "people")
            if c04 is not None:
                results["children_0_4"] = DataPoint(int(c04), src, Confidence.HIGH)
            if c59 is not None:
                results["children_5_9"] = DataPoint(int(c59), src, Confidence.HIGH)

    # household income (median)
    if cfg.get("income_flow") and cfg.get("datakey_income"):
        obs, note = pull(cfg["income_flow"], cfg["datakey_income"])
        if obs:
            vals = [float(o["value"]) for o in obs if o.get("value") is not None]
            if vals:
                results["median_income"] = DataPoint(int(vals[0]), src,
                                                     Confidence.HIGH, "AUD/yr")

    if not results:
        return None

    # growth is not a single Census field; mark Missing until VIF/.id wired
    results.setdefault("growth_pct", DataPoint.missing(
        "Population growth", "Wire VIF/.id forecasts (roadmap) for real growth."))
    # backfill any gaps as Missing so nothing silently looks complete
    for k in ("population", "children_0_4", "children_5_9", "median_income"):
        results.setdefault(k, DataPoint.missing(k, "Confirm datakey/age codes in abs_config.json."))
    return results
