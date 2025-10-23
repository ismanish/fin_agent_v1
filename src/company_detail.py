import os
import json
import time
from typing import List, Dict, Any, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "finagent/1.0 (admin@fin.com)"
)

# Simple in-memory cache to avoid hitting SEC repeatedly
_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_TTL_SECONDS = 3600  # 1 hour


def _fetch_raw() -> Dict[str, Any]:
    """Fetch raw JSON dict from SEC endpoint."""
    try:
        req = Request(
            SEC_TICKERS_URL,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        with urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return json.loads(raw)
    except HTTPError as e:
        raise RuntimeError(f"SEC request failed: {e.code} {e.reason}") from e
    except URLError as e:
        raise RuntimeError(f"SEC request error: {e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected SEC request error: {e}") from e


def _load_data() -> List[Dict[str, Any]]:
    """Load and normalize SEC tickers into a list of rows."""
    now = time.time()
    if _CACHE["data"] is not None and (now - float(_CACHE["ts"])) < _TTL_SECONDS:
        return _CACHE["data"]  # type: ignore

    payload = _fetch_raw()
    rows: List[Dict[str, Any]] = []
    for _, item in payload.items():
        cik_val = item.get("cik_str")
        try:
            cik_int = int(cik_val) if cik_val is not None else None
        except Exception:
            cik_int = None
        rows.append({
            "cik": cik_int,
            "ticker": item.get("ticker"),
            "title": item.get("title"),
        })

    _CACHE["data"] = rows
    _CACHE["ts"] = now
    return rows


def get_company_table(q: Optional[str] = None, ticker: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """
    Build a JSON table from SEC company tickers.

    - If `ticker` is provided, returns the exact match (case-insensitive).
    - Else if `q` is provided, filters by substring in ticker or title.
    - `limit` caps the number of returned rows.
    """
    data = _load_data()

    filtered = data
    if ticker:
        t = ticker.strip().upper()
        filtered = [r for r in data if (r.get("ticker") or "").upper() == t]
    elif q:
        ql = q.strip().lower()
        filtered = [
            r for r in data
            if ql in (r.get("ticker") or "").lower() or ql in (r.get("title") or "").lower()
        ]

    if isinstance(limit, int) and limit > 0:
        filtered = filtered[:limit]

    table = {
        "columns": [
            {"key": "title", "label": "Company Name"},
            {"key": "ticker", "label": "Ticker"},
            {"key": "cik", "label": "CIK"},
        ],
        "rows": filtered,
        "count": len(filtered),
        "source": SEC_TICKERS_URL,
    }
    return table


def build_exposure_table_for_ticker(ticker: str) -> Dict[str, Any]:
    """
    Build the screenshot-style table for a single ticker using only
    the SEC tickers dataset as the data source.

    Any fields not available in the SEC dataset will be set to null.
    """
    if not ticker:
        raise ValueError("ticker is required")

    data = _load_data()
    t = ticker.strip().upper()
    match = next((r for r in data if (r.get("ticker") or "").upper() == t), None)
    if not match:
        raise ValueError(f"Ticker not found in SEC dataset: {ticker}")

    title: Optional[str] = match.get("title")
    cik = match.get("cik")

    # Desired labels from the screenshot
    labels = [
        "Credit Exposure Name",
        "iRisk Parent Name",
        "Industry",
        "Real Assets Category",
        "Stat. Country",
        "Economic Risk Country",
        "Valuation Country",
        "Public / Private",
        "Headquarters",
        "Region",
        "MD",
        "Team Leader",
        "Secondary",
        "Analyst",
        "Servicing Category",
        "PruScore",
        "NAIC Designation",
        "S&P / M / Fitch",
        "Other Ratings",
        "Unqualified Audit",
    ]

    table_map: Dict[str, Any] = {key: None for key in labels}

    # Fill what we can from SEC data
    table_map["Credit Exposure Name"] = title
    # The screenshot shows uppercase for parent name; use upper-cased title if present
    table_map["iRisk Parent Name"] = title.upper() if isinstance(title, str) else None

    # Everything else remains None (null in JSON)

    return {
        "ticker": t,
        "cik": cik,
        "table": table_map,
        "source": SEC_TICKERS_URL,
    }

