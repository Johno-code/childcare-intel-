"""
connectors/acecqa.py
--------------------
Childcare SUPPLY data: approved services, NQS ratings, service type, provider.

PRIMARY real-data path (most reliable):
    Download the ACECQA "National Registers" export (Approved Services) as
    CSV/XLSX and drop it in  data/acecqa_services.csv  (or .xlsx).
    The ACECQA registers are the authoritative source for NQS ratings,
    service type and approval status.
        https://www.acecqa.gov.au/resources/national-registers
    StartingBlocks (https://www.startingblocks.gov.au) is the consumer
    search and can supplement fees/vacancy where published.

SECONDARY path: attempt a live download from a configurable URL.

If neither works the connector returns an EMPTY result with a loud warning.
It NEVER fabricates services.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd

from provenance import Source, Confidence, Method
from geo import haversine_km

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_CSV = os.path.join(DATA_DIR, "acecqa_services.csv")
LOCAL_XLSX = os.path.join(DATA_DIR, "acecqa_services.xlsx")

# Put the current register export URL here if you have a stable one.
LIVE_URL = os.environ.get("ACECQA_REGISTER_URL", "")

# Column-name candidates so we tolerate schema drift in the export.
COLMAP = {
    "name": ["Service Name", "ServiceName", "service_name", "Name"],
    "type": ["Service Type", "ServiceType", "service_type", "Care Type"],
    "provider": ["Provider Legal Name", "Provider Name", "ProviderName", "Approved Provider"],
    "status": ["Service Approval Status", "Approval Status", "Status"],
    "rating": ["Overall Rating", "Overall NQS Rating", "OverallRating", "Rating"],
    "address": ["Service Address", "Physical Address", "Address"],
    "suburb": ["Service Suburb", "Suburb"],
    "postcode": ["Service Postcode", "Postcode", "Post Code"],
    "places": ["Approved Places", "Licensed Places", "Places"],
    "lat": ["Latitude", "Lat"],
    "lng": ["Longitude", "Lng", "Long"],
    "phone": ["Phone", "Contact Phone"],
}


@dataclass
class Service:
    name: str
    service_type: str
    provider: str
    approval_status: str
    nqs_rating: str
    address: str
    suburb: str
    postcode: str
    places: Optional[int]
    lat: Optional[float]
    lng: Optional[float]
    phone: str = ""
    distance_km: Optional[float] = None


@dataclass
class SupplyResult:
    services: List[Service]
    source: Source
    confidence: Confidence
    warning: str = ""
    total_places: Optional[int] = None


def _pick(df: pd.DataFrame, keys: List[str]):
    for k in keys:
        if k in df.columns:
            return k
    return None


def _load_local() -> Optional[pd.DataFrame]:
    try:
        if os.path.exists(LOCAL_CSV):
            return pd.read_csv(LOCAL_CSV, dtype=str)
        if os.path.exists(LOCAL_XLSX):
            return pd.read_excel(LOCAL_XLSX, dtype=str)
    except Exception:
        return None
    return None


def _fetch_live() -> Optional[pd.DataFrame]:
    if not LIVE_URL:
        return None
    try:
        return pd.read_csv(LIVE_URL, dtype=str)
    except Exception:
        return None


def get_services(centre_lat: float, centre_lng: float, postcode: str,
                 radius_km: float = 5.0) -> SupplyResult:
    df = _load_local()
    method = Method.DOWNLOAD
    file_origin = "Local register file (data/acecqa_services.*)"
    last_updated = None
    if df is not None and os.path.exists(LOCAL_CSV):
        last_updated = datetime.fromtimestamp(
            os.path.getmtime(LOCAL_CSV), tz=timezone.utc).strftime("%Y-%m-%d")

    if df is None:
        df = _fetch_live()
        file_origin = f"Live download: {LIVE_URL}" if LIVE_URL else file_origin

    src = Source(
        name="ACECQA National Registers (Approved Services)",
        url="https://www.acecqa.gov.au/resources/national-registers",
        retrieved=Source.now(), last_updated=last_updated, method=method,
    )

    if df is None or df.empty:
        return SupplyResult(
            services=[], source=src, confidence=Confidence.MISSING,
            warning=("No ACECQA register loaded. Download the Approved Services "
                     "register from acecqa.gov.au and save it as "
                     "data/acecqa_services.csv (or set ACECQA_REGISTER_URL). "
                     "Supply analysis cannot run on real data until then."),
            total_places=None,
        )

    cols = {k: _pick(df, v) for k, v in COLMAP.items()}
    services: List[Service] = []
    for _, r in df.iterrows():
        def g(key, default=""):
            c = cols.get(key)
            return (r[c] if c and pd.notna(r[c]) else default)

        # geo filter: prefer lat/lng, else postcode match
        lat = lng = None
        try:
            lat = float(g("lat")) if g("lat") else None
            lng = float(g("lng")) if g("lng") else None
        except ValueError:
            pass

        dist = None
        if lat is not None and lng is not None:
            dist = haversine_km(centre_lat, centre_lng, lat, lng)
            if dist > radius_km:
                continue
        else:
            if postcode and g("postcode") and str(g("postcode")).strip() != str(postcode):
                continue

        places = None
        try:
            places = int(float(g("places"))) if g("places") else None
        except ValueError:
            pass

        services.append(Service(
            name=g("name", "Unknown"), service_type=g("type", "Unknown"),
            provider=g("provider", "Unknown"), approval_status=g("status", "Unknown"),
            nqs_rating=g("rating", "Not rated"), address=g("address"),
            suburb=g("suburb"), postcode=str(g("postcode")), places=places,
            lat=lat, lng=lng, phone=g("phone"), distance_km=dist,
        ))

    services.sort(key=lambda s: (s.distance_km if s.distance_km is not None else 999))
    total_places = sum(s.places for s in services if s.places) or None
    conf = Confidence.HIGH if last_updated else Confidence.MEDIUM
    warn = "" if last_updated else "Register freshness unknown — confirm export date."
    return SupplyResult(services, src, conf, warn, total_places)
