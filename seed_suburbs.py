"""
seed_suburbs.py
---------------
Reference facts for the 10 west-Melbourne target suburbs.

WHAT IS REAL vs DEMO:
  * suburb name, postcode, LGA/council, approx lat/lng, SA3 region name:
    these are stable public reference facts (Method.MANUAL, Confidence.MEDIUM).
    Verify SA2/SA3 codes against the current ABS ASGS edition.
  * population / children / income / growth: these are *_DEMO placeholders.
    They render with a red DEMO badge and MUST be replaced by the ABS
    connector (or a Census table drop) before any real decision.

The point of the DEMO values is only so the app produces a complete
end-to-end report you can see. They are not real and the UI says so.
"""

# (name, postcode, lga, sa3_region, lat, lng)
SUBURBS = {
    "tarneit":         ("Tarneit", "3029", "City of Wyndham", "Wyndham", -37.8330, 144.6940),
    "werribee":        ("Werribee", "3030", "City of Wyndham", "Wyndham", -37.9000, 144.6600),
    "truganina":       ("Truganina", "3029", "City of Wyndham", "Wyndham", -37.8200, 144.7400),
    "point cook":      ("Point Cook", "3030", "City of Wyndham", "Wyndham", -37.9150, 144.7500),
    "hoppers crossing":("Hoppers Crossing", "3029", "City of Wyndham", "Wyndham", -37.8820, 144.7000),
    "wyndham vale":    ("Wyndham Vale", "3024", "City of Wyndham", "Wyndham", -37.8900, 144.6200),
    "melton":          ("Melton", "3337", "City of Melton", "Melton - Bacchus Marsh", -37.6830, 144.5860),
    "caroline springs":("Caroline Springs", "3023", "City of Melton", "Melton - Bacchus Marsh", -37.7430, 144.7400),
    "deer park":       ("Deer Park", "3023", "City of Brimbank", "Brimbank", -37.7700, 144.7720),
    "sunshine":        ("Sunshine", "3020", "City of Brimbank", "Brimbank", -37.7880, 144.8330),
    "altona":          ("Altona", "3018", "City of Hobsons Bay", "Hobsons Bay", -37.8680, 144.8300),
}

# postcode -> primary suburb key (first match) for postcode search
POSTCODE_INDEX = {}
for _k, _v in SUBURBS.items():
    POSTCODE_INDEX.setdefault(_v[1], _k)

# DEMO demographics keyed by suburb. NOT REAL. Order:
# (population, children_0_4, children_5_9, median_household_income_annual, pop_growth_pct)
DEMO_DEMOGRAPHICS = {
    "tarneit":          (62000, 7200, 6100, 95000, 6.5),
    "werribee":         (52000, 4300, 3900, 82000, 2.4),
    "truganina":        (38000, 5100, 3800, 98000, 8.1),
    "point cook":       (66000, 5400, 5600, 112000, 1.8),
    "hoppers crossing": (45000, 3100, 3000, 84000, 0.9),
    "wyndham vale":     (31000, 3600, 2900, 88000, 5.2),
    "melton":           (39000, 3400, 3100, 76000, 2.0),
    "caroline springs": (37000, 2900, 3000, 104000, 1.5),
    "deer park":        (32000, 2600, 2400, 79000, 1.7),
    "sunshine":         (11000, 900, 800, 71000, 1.1),
    "altona":           (11500, 700, 750, 99000, 0.6),
}


def resolve(query: str):
    """Return suburb key for a name or postcode query, or None."""
    q = query.strip().lower()
    if q in SUBURBS:
        return q
    if q in POSTCODE_INDEX:
        return POSTCODE_INDEX[q]
    # loose name match
    for k in SUBURBS:
        if q and (q in k or k in q):
            return k
    return None
