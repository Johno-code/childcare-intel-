"""
provenance.py
-------------
The backbone of the tool. NOTHING is displayed as a bare number.
Every value is wrapped in a DataPoint that carries where it came from,
when it was retrieved, how confident we are, and any warning.

This is what stops the app from "pretending old data is current" or
inventing numbers. If a value is illustrative it is tagged DEMO and
renders with a red badge so it can never be mistaken for real data.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class Confidence(str, Enum):
    HIGH = "High"        # official source, fetched live or <24h cache
    MEDIUM = "Medium"    # official but older, or derived
    LOW = "Low"          # scraped / stale / heavily estimated
    DEMO = "DEMO"        # NOT REAL — illustrative placeholder only
    MISSING = "Missing"  # could not be obtained

    @property
    def colour(self) -> str:
        return {
            "High": "#1a7f37",
            "Medium": "#9a6700",
            "Low": "#bc4c00",
            "DEMO": "#cf222e",
            "Missing": "#57606a",
        }[self.value]


class Method(str, Enum):
    API = "api"
    DOWNLOAD = "download"   # official file download (e.g. ACECQA register)
    SCRAPE = "scrape"       # third-party scrape (label loudly)
    MANUAL = "manual"       # hand-entered reference fact
    COMPUTED = "computed"   # derived from other DataPoints
    DEMO = "demo"


@dataclass
class Source:
    name: str
    url: str = ""
    retrieved: Optional[str] = None      # ISO date the app pulled it
    last_updated: Optional[str] = None   # publisher's "last updated", if known
    method: Method = Method.MANUAL

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


@dataclass
class DataPoint:
    value: Any
    source: Source
    confidence: Confidence = Confidence.MEDIUM
    unit: str = ""
    warning: str = ""

    @classmethod
    def demo(cls, value: Any, label: str, unit: str = "") -> "DataPoint":
        """Build a clearly-flagged illustrative value."""
        return cls(
            value=value,
            source=Source(name=f"DEMO placeholder — {label}", method=Method.DEMO),
            confidence=Confidence.DEMO,
            unit=unit,
            warning="NOT REAL DATA. Illustrative only. Replace by running the live connector.",
        )

    @classmethod
    def missing(cls, label: str, how_to_get: str = "") -> "DataPoint":
        return cls(
            value=None,
            source=Source(name=label, method=Method.MANUAL),
            confidence=Confidence.MISSING,
            warning=("Not loaded. " + how_to_get).strip(),
        )

    @property
    def is_real(self) -> bool:
        return self.confidence not in (Confidence.DEMO, Confidence.MISSING)

    def display(self) -> str:
        if self.value is None:
            return "—"
        if isinstance(self.value, float):
            v = f"{self.value:,.1f}".rstrip("0").rstrip(".")
        elif isinstance(self.value, int):
            v = f"{self.value:,}"
        else:
            v = str(self.value)
        return f"{v}{(' ' + self.unit) if self.unit else ''}"


# ---------------------------------------------------------------------------
# Streamlit rendering helpers (imported lazily so the module also works headless)
# ---------------------------------------------------------------------------
def badge_html(conf: Confidence) -> str:
    return (
        f'<span style="background:{conf.colour};color:white;padding:1px 7px;'
        f'border-radius:10px;font-size:0.70rem;font-weight:600;'
        f'vertical-align:middle;">{conf.value}</span>'
    )


def metric_with_source(st, label: str, dp: DataPoint, help_text: str = ""):
    """Render a labelled value with a confidence badge + a source expander."""
    st.markdown(
        f"**{label}**&nbsp;&nbsp;{badge_html(dp.confidence)}<br>"
        f"<span style='font-size:1.4rem;font-weight:700'>{dp.display()}</span>",
        unsafe_allow_html=True,
    )
    if dp.warning:
        st.markdown(
            f"<span style='color:{dp.confidence.colour};font-size:0.78rem'>⚠ {dp.warning}</span>",
            unsafe_allow_html=True,
        )
    with st.expander("source", expanded=False):
        s = dp.source
        st.caption(f"**Source:** {s.name}")
        if s.url:
            st.caption(f"**Link:** {s.url}")
        st.caption(f"**Method:** {s.method.value}")
        st.caption(f"**Retrieved:** {s.retrieved or '—'}")
        st.caption(f"**Publisher last-updated:** {s.last_updated or 'unknown'}")
        if help_text:
            st.caption(help_text)
