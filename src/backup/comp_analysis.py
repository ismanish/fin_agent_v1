import os
import json
import csv
import statistics
from typing import Dict, List, Optional, Tuple, Any

# External deps already in requirements.txt
import urllib3

from .sec_filing import (
    detect_identifier_type,
    get_financial_statements,
    save_statements_to_files,
)
from .data_manipulation import process_all_filings
from .llm import load_yaml, get_combined_json_data, get_llm_response


# Disable SSL warnings (to mirror the Finnhub usage instruction)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(ROOT, "output", "json", "llm_input_processed")
OUTPUT_JSON_DIR = os.path.join(ROOT, "output", "json", "comp")
OUTPUT_CSV_DIR = os.path.join(ROOT, "output", "csv", "comp")
UTILS_DIR = os.path.join(ROOT, "utils")
COMP_MAPPING_PATH = os.path.join(UTILS_DIR, "comp_mapping.json")

COMP_METRICS = [
    "LTM Revenue",
    "LTM EBITDA",
    "EBITDA Margin %",
    "EBITDAR / (Int + Rents)",
    "(Total Debt + COL) / EBITDAR",
    "(Net Debt + COL) / EBITDAR",
    "(Total Debt + COL) / Total Cap",
    "(FCF + Rents) / (Total Debt + COL)",
    "3Y Avg (TD+COL)/EBITDAR",
    "3Y Avg (TD+COL)/Total Cap",
    "3Y Avg (FCF+Rents)/(TD+COL)",
]

def _save_comp_mapping(response_content: str, ticker: str, label: str) -> None:
    try:
        parsed = json.loads(response_content)
        if not isinstance(parsed, list):
            return
    except Exception:
        return

    os.makedirs(UTILS_DIR, exist_ok=True)
    data = {}
    if os.path.exists(COMP_MAPPING_PATH) and os.path.getsize(COMP_MAPPING_PATH) > 0:
        try:
            with open(COMP_MAPPING_PATH, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}
    data.setdefault(ticker.upper(), {})
    data[ticker.upper()].setdefault(label, [])
    data[ticker.upper()][label].append(parsed)
    try:
        with open(COMP_MAPPING_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def _mapping_labels() -> List[str]:
    return ["10-K-2024", "10-Q-2025"]

def _ticker_has_mapping(ticker: str, required_labels: Optional[List[str]] = None) -> bool:
    if not os.path.exists(COMP_MAPPING_PATH) or os.path.getsize(COMP_MAPPING_PATH) == 0:
        return False
    try:
        with open(COMP_MAPPING_PATH, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        tmap = data.get(ticker.upper())
        if not isinstance(tmap, dict):
            return False
        labels = required_labels or _mapping_labels()
        for lb in labels:
            arrs = tmap.get(lb)
            if not isinstance(arrs, list) or not arrs:
                return False
            last = arrs[-1]
            if not isinstance(last, list) or not last:
                return False
            # ensure list contains dicts
            if not any(isinstance(x, dict) for x in last):
                return False
        return True
    except Exception:
        return False

def _maybe_generate_comp_mapping_for(ticker: str) -> None:
    try:
        # Cache check: if mapping exists for both labels, skip LLM
        if _ticker_has_mapping(ticker):
            return
        prompt_data = load_yaml(os.path.join(UTILS_DIR, "comp_prompt.yaml"))
        template = prompt_data.get("calculate_comp_metrics", "")
        if not template:
            return
        metrics_str = json.dumps(COMP_METRICS, indent=2)
        # 10-K FY 2024 mapping
        combined_10k = get_combined_json_data(ticker, 2024, "10-K")
        if combined_10k and not _ticker_has_mapping(ticker, ["10-K-2024"]):
            resp = get_llm_response(template, combined_10k, metrics_str)
            _save_comp_mapping(resp, ticker, "10-K-2024")
        # 10-Q 2025 (latest quarter) mapping (should be Q1)
        combined_10q = get_combined_json_data(ticker, 2025, "10-Q")
        if not combined_10q:
            combined_10q = get_combined_json_data(ticker, 2024, "10-Q")
        if combined_10q and not _ticker_has_mapping(ticker, ["10-Q-2025"]):
            resp = get_llm_response(template, combined_10q, metrics_str)
            _save_comp_mapping(resp, ticker, "10-Q-2025")
    except Exception:
        # Non-fatal
        pass

def _load_comp_mapping_entries(ticker: str) -> List[Dict[str, Any]]:
    if not os.path.exists(COMP_MAPPING_PATH):
        return []
    try:
        with open(COMP_MAPPING_PATH, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        tmap = data.get(ticker.upper(), {})
        # prefer newest entries; flatten lists
        entries: List[Dict[str, Any]] = []
        for label in ("10-K-2024", "10-Q-2025"):
            arrs = tmap.get(label) or []
            if arrs:
                last = arrs[-1]
                if isinstance(last, list):
                    for item in last:
                        if isinstance(item, dict):
                            entries.append(item)
        return entries
    except Exception:
        return []

def _derive_key_sets_from_mapping(entries: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    keysets: Dict[str, List[str]] = {
        "rev_keys": [],
        "ebitda_keys": [],
        "ni_keys": [],
        "int_keys": [],
        "tax_keys": [],
        "da_keys": [],
        "rent_keys": [],
        "cash_keys": ["CashAndCashEquivalentsAtCarryingValue"],
        "std_keys": ["ShortTermBorrowings", "DebtCurrent", "LongTermDebtCurrent"],
        "ltd_keys": ["LongTermDebt"],
        "equity_keys": ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"],
        "ol_current_keys": ["OperatingLeaseLiabilityCurrent"],
        "ol_noncurrent_keys": ["OperatingLeaseLiabilityNoncurrent", "OperatingLeaseLiability"],
        "cfo_keys": ["NetCashProvidedByUsedInOperatingActivities"],
        "capex_keys": ["PaymentsToAcquirePropertyPlantAndEquipment", "CapitalExpenditures"],
    }
    def add_keys(target: str, keys: List[Any]):
        for k in keys or []:
            if isinstance(k, str) and k not in keysets[target]:
                keysets[target].append(k)
    for e in entries:
        metric = (e.get("metric") or e.get("aqrr_key") or "").strip()
        fkeys = e.get("financial_statement_keys") or []
        if metric == "LTM Revenue":
            add_keys("rev_keys", fkeys)
        elif metric == "LTM EBITDA":
            add_keys("ebitda_keys", [k for k in fkeys if "EBITDA" in k])
            # Fallback components
            for k in fkeys:
                if "NetIncome" in k:
                    add_keys("ni_keys", [k])
                if "InterestExpense" in k:
                    add_keys("int_keys", [k])
                if "Depreciation" in k or "Amortization" in k:
                    add_keys("da_keys", [k])
                if "IncomeTax" in k:
                    add_keys("tax_keys", [k])
        elif metric == "EBITDAR / (Int + Rents)":
            for k in fkeys:
                if "Lease" in k or "Rent" in k:
                    add_keys("rent_keys", [k])
                if "InterestExpense" in k:
                    add_keys("int_keys", [k])
        elif metric in ("(Total Debt + COL) / EBITDAR", "(Net Debt + COL) / EBITDAR", "(Total Debt + COL) / Total Cap"):
            # debt, equity, lease liabilities
            for k in fkeys:
                if "Debt" in k and "Cash" not in k:
                    if "Short" in k or "Current" in k:
                        add_keys("std_keys", [k])
                    else:
                        add_keys("ltd_keys", [k])
                if "Equity" in k:
                    add_keys("equity_keys", [k])
                if "OperatingLeaseLiabilityCurrent" == k:
                    add_keys("ol_current_keys", [k])
                if k in ("OperatingLeaseLiabilityNoncurrent", "OperatingLeaseLiability"):
                    add_keys("ol_noncurrent_keys", [k])
        elif metric == "(FCF + Rents) / (Total Debt + COL)":
            for k in fkeys:
                if "NetCashProvidedByUsedInOperatingActivities" == k:
                    add_keys("cfo_keys", [k])
                if "Capital" in k and ("Expend" in k or "PropertyPlantAndEquipment" in k):
                    add_keys("capex_keys", [k])
                if "Lease" in k or "Rent" in k:
                    add_keys("rent_keys", [k])
    # Provide sensible fallbacks if lists are empty
    if not keysets["rev_keys"]:
        keysets["rev_keys"] = ["Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax"]
    if not keysets["ebitda_keys"]:
        keysets["ebitda_keys"] = ["Adjusted EBITDA", "EBITDA"]
    if not keysets["ni_keys"]:
        keysets["ni_keys"] = ["NetIncomeLoss"]
    if not keysets["int_keys"]:
        keysets["int_keys"] = ["InterestExpenseNonoperating", "InterestExpense"]
    if not keysets["tax_keys"]:
        keysets["tax_keys"] = ["IncomeTaxExpenseBenefit"]
    if not keysets["da_keys"]:
        keysets["da_keys"] = ["DepreciationAndAmortization"]
    if not keysets["rent_keys"]:
        keysets["rent_keys"] = ["OperatingLeaseCost", "LeaseCost", "OperatingLeaseExpense", "RentExpense"]
    return keysets


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _read_processed_10q(ticker: str, year: int, quarter: str) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Load processed 10-Q JSON created by data_manipulation.process_all_filings.

    Returns structure: {"income": {xbrl_key: {date: value}}, "balance": {...}, "cashflow": {...}}
    Missing file returns empty dict.
    """
    p = os.path.join(PROCESSED_DIR, ticker.upper(), f"{ticker.upper()}_10-Q_{year}_{quarter}.json")
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _read_processed_10k_combined(ticker: str) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Load processed combined 10-K JSON 2020-2024.

    Returns structure: {"income": {xbrl_key: {"2024": value, ...}}, "balance": {...}, "cashflow": {...}}
    Missing file returns empty dict.
    """
    p = os.path.join(PROCESSED_DIR, ticker.upper(), f"{ticker.upper()}_10-K_2020-2024_combined.json")
    if not os.path.exists(p):
        # Some tickers may only have a single year 10-K combined (e.g., 2024 only)
        p_alt = os.path.join(PROCESSED_DIR, ticker.upper(), f"{ticker.upper()}_10-K_2024.json")
        if os.path.exists(p_alt):
            p = p_alt
        else:
            return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _get_latest_date(values_by_date: Dict[str, Any]) -> Optional[str]:
    if not values_by_date:
        return None
    try:
        return sorted(values_by_date.keys(), reverse=True)[0]
    except Exception:
        return None


def _pick_value(container: Dict[str, Dict[str, Any]], section: str, keys: List[str], index_key: str) -> Optional[float]:
    """Pick a numeric value from a processed container for 10-Q style (date-keyed).

    - section: "income" | "balance" | "cashflow"
    - keys: candidate XBRL keys in order of preference
    - index_key: a specific date string to fetch; if not present, use latest
    """
    sec = container.get(section, {}) if container else {}
    for k in keys:
        d = sec.get(k)
        if not isinstance(d, dict):
            continue
        if index_key and index_key in d:
            v = _safe_float(d.get(index_key))
            if v is not None:
                return v
        # fallback: latest date
        latest = _get_latest_date(d)
        if latest:
            v = _safe_float(d.get(latest))
            if v is not None:
                return v
    return None


def _pick_value_year(container: Dict[str, Dict[str, Any]], section: str, keys: List[str], year: int) -> Optional[float]:
    """Pick a numeric value from a processed 10-K combined container (year-keyed)."""
    sec = container.get(section, {}) if container else {}
    for k in keys:
        d = sec.get(k)
        if not isinstance(d, dict):
            continue
        v = _safe_float(d.get(str(year)))
        if v is not None:
            return v
    return None


def _compute_ebitda_fallback(net_income: Optional[float], interest: Optional[float], taxes: Optional[float], da: Optional[float]) -> Optional[float]:
    comps = [net_income, interest, taxes, da]
    if all(v is None for v in comps):
        return None
    try:
        return (net_income or 0.0) + (interest or 0.0) + (taxes or 0.0) + (da or 0.0)
    except Exception:
        return None


def _ensure_filings_for_ticker(ticker: str) -> List[str]:
    """Fetch required filings (if not cached) and process them for a ticker.

    Uses the same plan as /api/v1/hfa.
    Returns a list of warnings encountered (non-fatal).
    """
    warnings_list: List[str] = []
    try:
        processed_identifier, is_cik = detect_identifier_type(ticker)
        # Minimal set required for Q1 2025 comparable metrics:
        # - 10-K for 2022, 2023, 2024 (for 3Y averages and FY anchors)
        # - 10-Q for 2024 Q1 (YTD 2024) and 2025 Q1 (YTD 2025 + stock items)
        fetch_plan = [
            {"filing_type": "10-K", "year": 2022, "quarter": None},
            {"filing_type": "10-K", "year": 2023, "quarter": None},
            {"filing_type": "10-K", "year": 2024, "quarter": None},
            {"filing_type": "10-Q", "year": 2024, "quarter": "Q1"},
            {"filing_type": "10-Q", "year": 2025, "quarter": "Q1"},
        ]
        for item in fetch_plan:
            res = get_financial_statements(
                identifier=processed_identifier,
                is_cik=is_cik,
                filing_type=item["filing_type"],
                year=item["year"],
                quarter=item["quarter"],
            )
            if isinstance(res, dict) and "error" in res:
                warnings_list.append(f"Fetch failed for {item['filing_type']} {item['year']} {item['quarter'] or ''}: {res['error']}")
                continue
            try:
                meta = res.get("metadata", {})
                if not meta.get("from_cache"):
                    save_statements_to_files(res["statements"], meta, processed_identifier, is_cik)
            except Exception as e:
                warnings_list.append(f"Save failed for {item['filing_type']} {item['year']} {item['quarter'] or ''}: {e}")

        # Process raw to combined
        process_all_filings(ticker)
    except Exception as e:
        warnings_list.append(str(e))
    return warnings_list


def _compute_ltm(ytd_2025: Optional[float], fy_2024: Optional[float], ytd_2024: Optional[float]) -> Optional[float]:
    try:
        if ytd_2025 is None or fy_2024 is None or ytd_2024 is None:
            return None
        return float(fy_2024) + float(ytd_2025) - float(ytd_2024)
    except Exception:
        return None


def _compute_company_metrics(ticker: str) -> Dict[str, Optional[float]]:
    """Compute required metrics for a single ticker for Q1 2025.

    LTM constructed as FY2024 + YTD2025 - YTD2024 for flow items.
    Balance/stock items taken from latest 2025 Q1 balance.
    """
    t = ticker.upper()
    q2025 = _read_processed_10q(t, 2025, "Q1")
    q2024 = _read_processed_10q(t, 2024, "Q1")
    k10k = _read_processed_10k_combined(t)

    # Dates: pick latest date within each 10-Q file
    def latest_date(container: Dict[str, Dict[str, Dict[str, float]]]) -> Optional[str]:
        # use Revenues key as anchor, else any
        keys = ["Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax"]
        for k in keys:
            d = (container.get("income", {}) or {}).get(k)
            if isinstance(d, dict):
                dt = _get_latest_date(d)
                if dt:
                    return dt
        # fallback: scan any income key
        inc = container.get("income", {}) or {}
        for _, d in inc.items():
            if isinstance(d, dict):
                dt = _get_latest_date(d)
                if dt:
                    return dt
        return None

    d_q1_2025 = latest_date(q2025)
    d_q1_2024 = latest_date(q2024)

    # Candidate keys
    rev_keys = ["Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax"]
    ebitda_keys = ["Adjusted EBITDA", "EBITDA"]  # Adjusted 'metric' may exist only in HFA; fallback to calc
    ni_keys = ["NetIncomeLoss"]
    int_keys = ["InterestExpenseNonoperating", "InterestExpense"]
    tax_keys = ["IncomeTaxExpenseBenefit"]
    da_keys = ["DepreciationAndAmortization"]
    rent_keys = ["OperatingLeaseCost", "LeaseCost", "OperatingLeaseExpense", "RentExpense"]
    rev_keys = ["Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax", "OperatingLeaseLeaseIncome"]
    cash_keys = ["CashAndCashEquivalentsAtCarryingValue"]
    std_keys = ["ShortTermBorrowings", "DebtCurrent", "LongTermDebtCurrent"]
    ltd_keys = ["LongTermDebt"]
    equity_keys = ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"]
    ol_current_keys = ["OperatingLeaseLiabilityCurrent"]
    ol_noncurrent_keys = ["OperatingLeaseLiabilityNoncurrent", "OperatingLeaseLiability"]
    cfo_keys = ["NetCashProvidedByUsedInOperatingActivities"]
    capex_keys = ["PaymentsToAcquirePropertyPlantAndEquipment", "CapitalExpenditures"]

    # YTD 2025 values
    rev_ytd_2025 = _pick_value(q2025, "income", rev_keys, d_q1_2025)
    ebitda_ytd_2025 = _pick_value(q2025, "income", ebitda_keys, d_q1_2025)
    if ebitda_ytd_2025 is None:
        ni_25 = _pick_value(q2025, "income", ni_keys, d_q1_2025)
        int_25 = _pick_value(q2025, "income", int_keys, d_q1_2025)
        tax_25 = _pick_value(q2025, "income", tax_keys, d_q1_2025)
        da_25 = _pick_value(q2025, "income", da_keys, d_q1_2025)
        ebitda_ytd_2025 = _compute_ebitda_fallback(ni_25, int_25, tax_25, da_25)
    rent_ytd_2025 = _pick_value(q2025, "income", rent_keys, d_q1_2025)
    int_ytd_2025 = _pick_value(q2025, "income", int_keys, d_q1_2025)
    cfo_ytd_2025 = _pick_value(q2025, "cashflow", cfo_keys, d_q1_2025)
    capex_ytd_2025 = _pick_value(q2025, "cashflow", capex_keys, d_q1_2025)

    # YTD 2024 values
    rev_ytd_2024 = _pick_value(q2024, "income", rev_keys, d_q1_2024)
    ebitda_ytd_2024 = _pick_value(q2024, "income", ebitda_keys, d_q1_2024)
    if ebitda_ytd_2024 is None:
        ni_24 = _pick_value(q2024, "income", ni_keys, d_q1_2024)
        int_24 = _pick_value(q2024, "income", int_keys, d_q1_2024)
        tax_24 = _pick_value(q2024, "income", tax_keys, d_q1_2024)
        da_24 = _pick_value(q2024, "income", da_keys, d_q1_2024)
        ebitda_ytd_2024 = _compute_ebitda_fallback(ni_24, int_24, tax_24, da_24)
    rent_ytd_2024 = _pick_value(q2024, "income", rent_keys, d_q1_2024)
    int_ytd_2024 = _pick_value(q2024, "income", int_keys, d_q1_2024)
    cfo_ytd_2024 = _pick_value(q2024, "cashflow", cfo_keys, d_q1_2024)
    capex_ytd_2024 = _pick_value(q2024, "cashflow", capex_keys, d_q1_2024)

    # FY 2024 values (10-K)
    rev_fy_2024 = _pick_value_year(k10k, "income", rev_keys, 2024)
    ebitda_fy_2024 = _pick_value_year(k10k, "income", ebitda_keys, 2024)
    if ebitda_fy_2024 is None:
        ni_fy_24 = _pick_value_year(k10k, "income", ni_keys, 2024)
        int_fy_24 = _pick_value_year(k10k, "income", int_keys, 2024)
        tax_fy_24 = _pick_value_year(k10k, "income", tax_keys, 2024)
        da_fy_24 = _pick_value_year(k10k, "income", da_keys, 2024)
        ebitda_fy_2024 = _compute_ebitda_fallback(ni_fy_24, int_fy_24, tax_fy_24, da_fy_24)
    rent_fy_2024 = _pick_value_year(k10k, "income", rent_keys, 2024)
    int_fy_2024 = _pick_value_year(k10k, "income", int_keys, 2024)
    cfo_fy_2024 = _pick_value_year(k10k, "cashflow", cfo_keys, 2024)
    capex_fy_2024 = _pick_value_year(k10k, "cashflow", capex_keys, 2024)

    # Balance (latest Q1 2025)
    cash = _pick_value(q2025, "balance", cash_keys, d_q1_2025)
    std = _pick_value(q2025, "balance", std_keys, d_q1_2025)
    ltd = _pick_value(q2025, "balance", ltd_keys, d_q1_2025)
    equity = _pick_value(q2025, "balance", equity_keys, d_q1_2025)
    olc = _pick_value(q2025, "balance", ol_current_keys, d_q1_2025) or 0.0
    olnc = _pick_value(q2025, "balance", ol_noncurrent_keys, d_q1_2025) or 0.0
    col = (olc or 0.0) + (olnc or 0.0)

    total_debt = (std or 0.0) + (ltd or 0.0)
    net_debt = total_debt - (cash or 0.0)
    total_cap = (total_debt + col) + (equity or 0.0 if equity is not None else 0.0)

    # LTM constructs
    rev_ltm = _compute_ltm(rev_ytd_2025, rev_fy_2024, rev_ytd_2024)
    ebitda_ltm = _compute_ltm(ebitda_ytd_2025, ebitda_fy_2024, ebitda_ytd_2024)
    rent_ltm = _compute_ltm(rent_ytd_2025, rent_fy_2024, rent_ytd_2024)
    int_ltm = _compute_ltm(int_ytd_2025, int_fy_2024, int_ytd_2024)
    fcf_ytd_2025 = None if (cfo_ytd_2025 is None or capex_ytd_2025 is None) else (cfo_ytd_2025 - capex_ytd_2025)
    fcf_ytd_2024 = None if (cfo_ytd_2024 is None or capex_ytd_2024 is None) else (cfo_ytd_2024 - capex_ytd_2024)
    fcf_fy_2024 = None if (cfo_fy_2024 is None or capex_fy_2024 is None) else (cfo_fy_2024 - capex_fy_2024)
    fcf_ltm = _compute_ltm(fcf_ytd_2025, fcf_fy_2024, fcf_ytd_2024)

    # LTM metrics
    ebitda_margin = None
    if rev_ltm not in (None, 0) and ebitda_ltm is not None:
        try:
            ebitda_margin = (ebitda_ltm / rev_ltm) * 100.0
        except Exception:
            ebitda_margin = None

    ebitdar_ltm = None if ebitda_ltm is None else (ebitda_ltm + (rent_ltm or 0.0))

    ebitdar_over_int_plus_rents = None
    denom = None if int_ltm is None else int_ltm + (rent_ltm or 0.0)
    if denom not in (None, 0) and ebitdar_ltm is not None:
        ebitdar_over_int_plus_rents = ebitdar_ltm / denom

    td_col_over_ebitdar = None
    if ebitdar_ltm not in (None, 0):
        td_col_over_ebitdar = (total_debt + col) / ebitdar_ltm

    nd_col_over_ebitdar = None
    if ebitdar_ltm not in (None, 0):
        nd_col_over_ebitdar = (net_debt + col) / ebitdar_ltm

    td_col_over_total_cap = None
    if total_cap not in (None, 0):
        td_col_over_total_cap = (total_debt + col) / total_cap

    fcf_plus_rents_over_td_col = None
    num = None if fcf_ltm is None else fcf_ltm + (rent_ltm or 0.0)
    den = (total_debt + col)
    if den not in (None, 0) and num is not None:
        fcf_plus_rents_over_td_col = num / den

    # 3-year averages (FY 2022-2024)
    def per_year_ratio(year: int) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        # (td+col)/ebitdar, (td+col)/total_cap, (fcf+rents)/(td+col)
        # Use FY values; stock items from FY balance
        # EBITDA fallback per-year
        ebitda_y = _pick_value_year(k10k, "income", ebitda_keys, year)
        if ebitda_y is None:
            ni_y = _pick_value_year(k10k, "income", ni_keys, year)
            int_y = _pick_value_year(k10k, "income", int_keys, year)
            tax_y = _pick_value_year(k10k, "income", tax_keys, year)
            da_y = _pick_value_year(k10k, "income", da_keys, year)
            ebitda_y = _compute_ebitda_fallback(ni_y, int_y, tax_y, da_y)
        rent_y = _pick_value_year(k10k, "income", rent_keys, year) or 0.0
        ebitdar_y = None if ebitda_y is None else (ebitda_y + rent_y)
        # stock items
        cash_y = _pick_value_year(k10k, "balance", cash_keys, year) or 0.0
        std_y = _pick_value_year(k10k, "balance", std_keys, year) or 0.0
        ltd_y = _pick_value_year(k10k, "balance", ltd_keys, year) or 0.0
        eq_y = _pick_value_year(k10k, "balance", equity_keys, year) or 0.0
        olc_y = _pick_value_year(k10k, "balance", ol_current_keys, year) or 0.0
        olnc_y = _pick_value_year(k10k, "balance", ol_noncurrent_keys, year) or 0.0
        col_y = (olc_y or 0.0) + (olnc_y or 0.0)
        td_y = std_y + ltd_y
        nd_y = td_y - cash_y
        totcap_y = td_y + col_y + eq_y
        # fcf
        cfo_y = _pick_value_year(k10k, "cashflow", cfo_keys, year)
        capex_y = _pick_value_year(k10k, "cashflow", capex_keys, year)
        fcf_y = None if (cfo_y is None or capex_y is None) else (cfo_y - capex_y)
        r1 = None if ebitdar_y in (None, 0) else (td_y + col_y) / ebitdar_y
        r2 = None if totcap_y in (None, 0) else (td_y + col_y) / totcap_y
        r3 = None
        denom = (td_y + col_y)
        num = None if fcf_y is None else (fcf_y + rent_y)
        if denom not in (None, 0) and num is not None:
            r3 = num / denom
        return r1, r2, r3

    yrs = [2024, 2023, 2022]
    vals_r1: List[float] = []
    vals_r2: List[float] = []
    vals_r3: List[float] = []
    for y in yrs:
        r1, r2, r3 = per_year_ratio(y)
        if r1 is not None:
            vals_r1.append(r1)
        if r2 is not None:
            vals_r2.append(r2)
        if r3 is not None:
            vals_r3.append(r3)

    def avg_or_none(arr: List[float]) -> Optional[float]:
        return None if not arr else sum(arr) / len(arr)

    metrics = {
        "LTM Revenue": rev_ltm,
        "LTM EBITDA": ebitda_ltm,
        "EBITDA Margin %": ebitda_margin,
        "EBITDAR / (Int + Rents)": ebitdar_over_int_plus_rents,
        "(Total Debt + COL) / EBITDAR": td_col_over_ebitdar,
        "(Net Debt + COL) / EBITDAR": nd_col_over_ebitdar,
        "(Total Debt + COL) / Total Cap": td_col_over_total_cap,
        "(FCF + Rents) / (Total Debt + COL)": fcf_plus_rents_over_td_col,
        "3Y Avg (TD+COL)/EBITDAR": avg_or_none(vals_r1),
        "3Y Avg (TD+COL)/Total Cap": avg_or_none(vals_r2),
        "3Y Avg (FCF+Rents)/(TD+COL)": avg_or_none(vals_r3),
    }
    return metrics


def _get_peers(ticker: str, limit: int = 5) -> List[str]:
    """Get comparable tickers via Finnhub. Always include the input ticker.
    If API/key not available, return just [ticker].
    """
    out: List[str] = []
    t_up = ticker.upper()
    out.append(t_up)
    try:
        api_key = os.environ.get("FINNHUB_API_KEY") or os.environ.get("FINNHUB_KEY") or os.environ.get("FINNHUBTOKEN") or ""
        if not api_key:
            return list(dict.fromkeys(out))[:limit]
        import finnhub  # type: ignore
        client = finnhub.Client(api_key=api_key)
        # Disable SSL verify on the underlying session per instruction
        try:
            client._session.verify = False  # noqa: SLF001
        except Exception:
            pass
        peers = client.company_peers(t_up) or []
        for p in peers:
            if isinstance(p, str) and p.strip():
                out.append(p.strip().upper())
    except Exception:
        # Silent fallback
        pass
    # Deduplicate, ensure input first, cap to limit
    uniq = []
    seen = set()
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq[:limit]


def build_comp_table(ticker: str, ensure_fetch: bool = True) -> Dict[str, Any]:
    """Build comparable analysis table for up to 5 tickers including input.

    Returns dict with keys: rows (list of dict), tickers (list), warnings (list).
    """
    warnings_list: List[str] = []
    peers = _get_peers(ticker, limit=5)

    if ensure_fetch:
        for tk in peers:
            warnings_list.extend(_ensure_filings_for_ticker(tk))
        # Generate LLM-based comp mapping for each ticker
        for tk in peers:
            _maybe_generate_comp_mapping_for(tk)
        # Generate LLM-based comp mapping for each ticker
        for tk in peers:
            _maybe_generate_comp_mapping_for(tk)

    rows: List[Dict[str, Any]] = []
    for tk in peers:
        # Compute via explicit mapping-driven evaluation; fallback to heuristic if mapping missing
        mapping = _load_comp_mapping_as_dict(tk)
        if mapping:
            metrics = _compute_company_metrics_from_mapping(tk, mapping)
        else:
            entries = _load_comp_mapping_entries(tk)
            keysets = _derive_key_sets_from_mapping(entries)
            metrics = _compute_company_metrics_with_keysets(tk, keysets)
        row = {"Ticker": tk}
        row.update(metrics)
        rows.append(row)

    # Overall average and median across companies for all metric columns
    if rows:
        metric_cols = [k for k in rows[0].keys() if k != "Ticker"]
        avg_row = {"Ticker": "AVERAGE"}
        med_row = {"Ticker": "MEDIAN"}
        for col in metric_cols:
            vals = [ _safe_float(r.get(col)) for r in rows if _safe_float(r.get(col)) is not None ]
            if vals:
                avg_row[col] = sum(vals) / len(vals)
                try:
                    med_row[col] = statistics.median(vals)
                except Exception:
                    med_row[col] = None
            else:
                avg_row[col] = None
                med_row[col] = None
        rows.extend([avg_row, med_row])

    return {"tickers": peers, "rows": rows, "warnings": warnings_list}


def _compute_company_metrics_with_keysets(ticker: str, keysets: Dict[str, List[str]]) -> Dict[str, Optional[float]]:
    # Clone of _compute_company_metrics but using provided keysets
    t = ticker.upper()
    q2025 = _read_processed_10q(t, 2025, "Q1")
    q2024 = _read_processed_10q(t, 2024, "Q1")
    k10k = _read_processed_10k_combined(t)

    def latest_date(container: Dict[str, Dict[str, Dict[str, float]]]) -> Optional[str]:
        for k in keysets.get("rev_keys", []):
            d = (container.get("income", {}) or {}).get(k)
            if isinstance(d, dict):
                dt = _get_latest_date(d)
                if dt:
                    return dt
        inc = container.get("income", {}) or {}
        for _, d in inc.items():
            if isinstance(d, dict):
                dt = _get_latest_date(d)
                if dt:
                    return dt
        return None

    d_q1_2025 = latest_date(q2025)
    d_q1_2024 = latest_date(q2024)

    rev_keys = keysets.get("rev_keys", [])
    ebitda_keys = keysets.get("ebitda_keys", [])
    ni_keys = keysets.get("ni_keys", [])
    int_keys = keysets.get("int_keys", [])
    tax_keys = keysets.get("tax_keys", [])
    da_keys = keysets.get("da_keys", [])
    rent_keys = keysets.get("rent_keys", [])
    cash_keys = keysets.get("cash_keys", [])
    std_keys = keysets.get("std_keys", [])
    ltd_keys = keysets.get("ltd_keys", [])
    equity_keys = keysets.get("equity_keys", [])
    ol_current_keys = keysets.get("ol_current_keys", [])
    ol_noncurrent_keys = keysets.get("ol_noncurrent_keys", [])
    cfo_keys = keysets.get("cfo_keys", [])
    capex_keys = keysets.get("capex_keys", [])

    rev_ytd_2025 = _pick_value(q2025, "income", rev_keys, d_q1_2025)
    ebitda_ytd_2025 = _pick_value(q2025, "income", ebitda_keys, d_q1_2025)
    if ebitda_ytd_2025 is None:
        ni_25 = _pick_value(q2025, "income", ni_keys, d_q1_2025)
        int_25 = _pick_value(q2025, "income", int_keys, d_q1_2025)
        tax_25 = _pick_value(q2025, "income", tax_keys, d_q1_2025)
        da_25 = _pick_value(q2025, "income", da_keys, d_q1_2025)
        ebitda_ytd_2025 = _compute_ebitda_fallback(ni_25, int_25, tax_25, da_25)
    rent_ytd_2025 = _pick_value(q2025, "income", rent_keys, d_q1_2025)
    int_ytd_2025 = _pick_value(q2025, "income", int_keys, d_q1_2025)
    cfo_ytd_2025 = _pick_value(q2025, "cashflow", cfo_keys, d_q1_2025)
    capex_ytd_2025 = _pick_value(q2025, "cashflow", capex_keys, d_q1_2025)

    rev_ytd_2024 = _pick_value(q2024, "income", rev_keys, d_q1_2024)
    ebitda_ytd_2024 = _pick_value(q2024, "income", ebitda_keys, d_q1_2024)
    if ebitda_ytd_2024 is None:
        ni_24 = _pick_value(q2024, "income", ni_keys, d_q1_2024)
        int_24 = _pick_value(q2024, "income", int_keys, d_q1_2024)
        tax_24 = _pick_value(q2024, "income", tax_keys, d_q1_2024)
        da_24 = _pick_value(q2024, "income", da_keys, d_q1_2024)
        ebitda_ytd_2024 = _compute_ebitda_fallback(ni_24, int_24, tax_24, da_24)
    rent_ytd_2024 = _pick_value(q2024, "income", rent_keys, d_q1_2024)
    int_ytd_2024 = _pick_value(q2024, "income", int_keys, d_q1_2024)
    cfo_ytd_2024 = _pick_value(q2024, "cashflow", cfo_keys, d_q1_2024)
    capex_ytd_2024 = _pick_value(q2024, "cashflow", capex_keys, d_q1_2024)

    rev_fy_2024 = _pick_value_year(k10k, "income", rev_keys, 2024)
    ebitda_fy_2024 = _pick_value_year(k10k, "income", ebitda_keys, 2024)
    if ebitda_fy_2024 is None:
        ni_fy_24 = _pick_value_year(k10k, "income", ni_keys, 2024)
        int_fy_24 = _pick_value_year(k10k, "income", int_keys, 2024)
        tax_fy_24 = _pick_value_year(k10k, "income", tax_keys, 2024)
        da_fy_24 = _pick_value_year(k10k, "income", da_keys, 2024)
        ebitda_fy_2024 = _compute_ebitda_fallback(ni_fy_24, int_fy_24, tax_fy_24, da_fy_24)
    rent_fy_2024 = _pick_value_year(k10k, "income", rent_keys, 2024)
    int_fy_2024 = _pick_value_year(k10k, "income", int_keys, 2024)
    cfo_fy_2024 = _pick_value_year(k10k, "cashflow", cfo_keys, 2024)
    capex_fy_2024 = _pick_value_year(k10k, "cashflow", capex_keys, 2024)

    cash = _pick_value(q2025, "balance", cash_keys, d_q1_2025)
    std = _pick_value(q2025, "balance", std_keys, d_q1_2025)
    ltd = _pick_value(q2025, "balance", ltd_keys, d_q1_2025)
    equity = _pick_value(q2025, "balance", equity_keys, d_q1_2025)
    olc = _pick_value(q2025, "balance", ol_current_keys, d_q1_2025) or 0.0
    olnc = _pick_value(q2025, "balance", ol_noncurrent_keys, d_q1_2025) or 0.0
    col = (olc or 0.0) + (olnc or 0.0)

    total_debt = (std or 0.0) + (ltd or 0.0)
    net_debt = total_debt - (cash or 0.0)
    total_cap = (total_debt + col) + (equity or 0.0 if equity is not None else 0.0)

    rev_ltm = _compute_ltm(rev_ytd_2025, rev_fy_2024, rev_ytd_2024)
    ebitda_ltm = _compute_ltm(ebitda_ytd_2025, ebitda_fy_2024, ebitda_ytd_2024)
    rent_ltm = _compute_ltm(rent_ytd_2025, rent_fy_2024, rent_ytd_2024)
    int_ltm = _compute_ltm(int_ytd_2025, int_fy_2024, int_ytd_2024)
    fcf_ytd_2025 = None if (cfo_ytd_2025 is None or capex_ytd_2025 is None) else (cfo_ytd_2025 - capex_ytd_2025)
    fcf_ytd_2024 = None if (cfo_ytd_2024 is None or capex_ytd_2024 is None) else (cfo_ytd_2024 - capex_ytd_2024)
    fcf_fy_2024 = None if (cfo_fy_2024 is None or capex_fy_2024 is None) else (cfo_fy_2024 - capex_fy_2024)
    fcf_ltm = _compute_ltm(fcf_ytd_2025, fcf_fy_2024, fcf_ytd_2024)

    ebitda_margin = None
    if rev_ltm not in (None, 0) and ebitda_ltm is not None:
        try:
            ebitda_margin = (ebitda_ltm / rev_ltm) * 100.0
        except Exception:
            ebitda_margin = None

    ebitdar_ltm = None if ebitda_ltm is None else (ebitda_ltm + (rent_ltm or 0.0))

    ebitdar_over_int_plus_rents = None
    denom = None if int_ltm is None else int_ltm + (rent_ltm or 0.0)
    if denom not in (None, 0) and ebitdar_ltm is not None:
        ebitdar_over_int_plus_rents = ebitdar_ltm / denom

    td_col_over_ebitdar = None
    if ebitdar_ltm not in (None, 0):
        td_col_over_ebitdar = (total_debt + col) / ebitdar_ltm

    nd_col_over_ebitdar = None
    if ebitdar_ltm not in (None, 0):
        nd_col_over_ebitdar = (net_debt + col) / ebitdar_ltm

    td_col_over_total_cap = None
    if total_cap not in (None, 0):
        td_col_over_total_cap = (total_debt + col) / total_cap

    fcf_plus_rents_over_td_col = None
    num = None if fcf_ltm is None else fcf_ltm + (rent_ltm or 0.0)
    den = (total_debt + col)
    if den not in (None, 0) and num is not None:
        fcf_plus_rents_over_td_col = num / den

    yrs = [2024, 2023, 2022]
    vals_r1: List[float] = []
    vals_r2: List[float] = []
    vals_r3: List[float] = []
    def per_year_ratio(year: int) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        ebitda_y = _pick_value_year(k10k, "income", ebitda_keys, year)
        if ebitda_y is None:
            ni_y = _pick_value_year(k10k, "income", ni_keys, year)
            int_y = _pick_value_year(k10k, "income", int_keys, year)
            tax_y = _pick_value_year(k10k, "income", tax_keys, year)
            da_y = _pick_value_year(k10k, "income", da_keys, year)
            ebitda_y = _compute_ebitda_fallback(ni_y, int_y, tax_y, da_y)
        rent_y = _pick_value_year(k10k, "income", rent_keys, year) or 0.0
        ebitdar_y = None if ebitda_y is None else (ebitda_y + rent_y)
        cash_y = _pick_value_year(k10k, "balance", cash_keys, year) or 0.0
        std_y = _pick_value_year(k10k, "balance", std_keys, year) or 0.0
        ltd_y = _pick_value_year(k10k, "balance", ltd_keys, year) or 0.0
        eq_y = _pick_value_year(k10k, "balance", equity_keys, year) or 0.0
        olc_y = _pick_value_year(k10k, "balance", ol_current_keys, year) or 0.0
        olnc_y = _pick_value_year(k10k, "balance", ol_noncurrent_keys, year) or 0.0
        col_y = (olc_y or 0.0) + (olnc_y or 0.0)
        td_y = std_y + ltd_y
        totcap_y = td_y + col_y + eq_y
        cfo_y = _pick_value_year(k10k, "cashflow", cfo_keys, year)
        capex_y = _pick_value_year(k10k, "cashflow", capex_keys, year)
        fcf_y = None if (cfo_y is None or capex_y is None) else (cfo_y - capex_y)
        r1 = None if ebitdar_y in (None, 0) else (td_y + col_y) / ebitdar_y
        r2 = None if totcap_y in (None, 0) else (td_y + col_y) / totcap_y
        r3 = None
        denom = (td_y + col_y)
        num = None if fcf_y is None else (fcf_y + rent_y)
        if denom not in (None, 0) and num is not None:
            r3 = num / denom
        return r1, r2, r3
    for y in yrs:
        r1, r2, r3 = per_year_ratio(y)
        if r1 is not None:
            vals_r1.append(r1)
        if r2 is not None:
            vals_r2.append(r2)
        if r3 is not None:
            vals_r3.append(r3)

    def avg_or_none(arr: List[float]) -> Optional[float]:
        return None if not arr else sum(arr) / len(arr)

    return {
        "LTM Revenue": rev_ltm,
        "LTM EBITDA": ebitda_ltm,
        "EBITDA Margin %": ebitda_margin,
        "EBITDAR / (Int + Rents)": ebitdar_over_int_plus_rents,
        "(Total Debt + COL) / EBITDAR": td_col_over_ebitdar,
        "(Net Debt + COL) / EBITDAR": nd_col_over_ebitdar,
        "(Total Debt + COL) / Total Cap": td_col_over_total_cap,
        "(FCF + Rents) / (Total Debt + COL)": fcf_plus_rents_over_td_col,
        "3Y Avg (TD+COL)/EBITDAR": avg_or_none(vals_r1),
        "3Y Avg (TD+COL)/Total Cap": avg_or_none(vals_r2),
        "3Y Avg (FCF+Rents)/(TD+COL)": avg_or_none(vals_r3),
    }


# ---------------- Mapping-driven evaluation ----------------

def _load_comp_mapping_as_dict(ticker: str) -> Dict[str, Dict[str, Any]]:
    entries = _load_comp_mapping_entries(ticker)
    mapping: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        name = (e.get("metric") or e.get("aqrr_key") or "").strip()
        if not name:
            continue
        mapping[name] = e
    return mapping


def _index_sections(q_container: Dict[str, Any], k_container: Dict[str, Any]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for sec_name in ("income", "cashflow", "balance"):
        for key, d in (q_container.get(sec_name, {}) or {}).items():
            if key not in index:
                index[key] = sec_name
        for key, d in (k_container.get(sec_name, {}) or {}).items():
            if key not in index:
                index[key] = sec_name
    return index


def _resolve_token_value_ltm(token: str,
                             q2025: Dict[str, Any], d_q1_2025: Optional[str],
                             q2024: Dict[str, Any], d_q1_2024: Optional[str],
                             k10k: Dict[str, Any],
                             sec_index: Dict[str, str]) -> Optional[float]:
    # Alias handling for common composite tokens
    t = token.strip()
    # strip section prefix like 'income.Key'
    if "." in t:
        t = t.split(".")[-1]
    tu = t.replace("_", "").upper()

    # Default candidate keys
    rent_keys = ["OperatingLeaseCost", "LeaseCost", "OperatingLeaseExpense", "RentExpense"]
    rev_keys = ["Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax", "OperatingLeaseLeaseIncome"]
    int_keys = ["InterestExpenseNonoperating", "InterestExpense"]
    ebitda_keys = ["Adjusted EBITDA", "EBITDA"]
    ni_keys = ["NetIncomeLoss"]
    tax_keys = ["IncomeTaxExpenseBenefit"]
    da_keys = ["DepreciationAndAmortization"]
    cash_keys = ["CashAndCashEquivalentsAtCarryingValue"]
    std_keys = ["ShortTermBorrowings", "DebtCurrent", "LongTermDebtCurrent"]
    ltd_keys = ["LongTermDebt"]
    equity_keys = ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"]
    ol_current_keys = ["OperatingLeaseLiabilityCurrent"]
    ol_noncurrent_keys = ["OperatingLeaseLiabilityNoncurrent", "OperatingLeaseLiability"]
    cfo_keys = ["NetCashProvidedByUsedInOperatingActivities"]
    capex_keys = ["PaymentsToAcquirePropertyPlantAndEquipment", "CapitalExpenditures"]

    def ltm_of(keys: List[str], section: str) -> Optional[float]:
        y25 = _pick_value(q2025, section, keys, d_q1_2025)
        fy24 = _pick_value_year(k10k, section, keys, 2024)
        y24 = _pick_value(q2024, section, keys, d_q1_2024)
        return _compute_ltm(y25, fy24, y24)

    if tu in {"COL", "CAPITALIZEDOPERATINGLEASES"}:
        olc = _pick_value(q2025, "balance", ol_current_keys, d_q1_2025) or 0.0
        olnc = _pick_value(q2025, "balance", ol_noncurrent_keys, d_q1_2025) or 0.0
        return (olc or 0.0) + (olnc or 0.0)
    if tu in {"TOTALDEBT", "TD", "DEBT"}:
        std = _pick_value(q2025, "balance", std_keys, d_q1_2025) or 0.0
        ltd = _pick_value(q2025, "balance", ltd_keys, d_q1_2025) or 0.0
        return (std or 0.0) + (ltd or 0.0)
    if tu in {"NETDEBT", "ND"}:
        td = _resolve_token_value_ltm("TotalDebt", q2025, d_q1_2025, q2024, d_q1_2024, k10k, sec_index)
        cash = _pick_value(q2025, "balance", cash_keys, d_q1_2025) or 0.0
        return None if td is None else float(td) - float(cash)
    if tu in {"EQUITY", "BOOKEQUITY"}:
        return _pick_value(q2025, "balance", equity_keys, d_q1_2025)
    if tu in {"TOTALCAP", "TOTALCAPITAL", "BOOKCAPITAL", "CAPITAL"}:
        td = _resolve_token_value_ltm("TotalDebt", q2025, d_q1_2025, q2024, d_q1_2024, k10k, sec_index) or 0.0
        col = _resolve_token_value_ltm("COL", q2025, d_q1_2025, q2024, d_q1_2024, k10k, sec_index) or 0.0
        eq = _resolve_token_value_ltm("Equity", q2025, d_q1_2025, q2024, d_q1_2024, k10k, sec_index) or 0.0
        return float(td) + float(col) + float(eq)
    if tu in {"RENT", "RENTS"}:
        return ltm_of(rent_keys, "income")
    if tu in {"REVENUE"}:
        return ltm_of(rev_keys, "income")
    if tu in {"INTEREST", "INTERESTEXPENSE"}:
        return ltm_of(int_keys, "income")
    if tu in {"CASH"}:
        return _pick_value(q2025, "balance", cash_keys, d_q1_2025)
    if tu in {"EBITDA"}:
        v = ltm_of(ebitda_keys, "income")
        if v is None:
            ni = ltm_of(ni_keys, "income") or 0.0
            intr = ltm_of(int_keys, "income") or 0.0
            tax = ltm_of(tax_keys, "income") or 0.0
            da = ltm_of(da_keys, "income") or 0.0
            return float(ni) + float(intr) + float(tax) + float(da)
        return v
    if tu in {"EBITDAR"}:
        e = _resolve_token_value_ltm("EBITDA", q2025, d_q1_2025, q2024, d_q1_2024, k10k, sec_index)
        r = _resolve_token_value_ltm("Rent", q2025, d_q1_2025, q2024, d_q1_2024, k10k, sec_index) or 0.0
        return None if e is None else float(e) + float(r)
    if tu in {"FCF", "FREECASHFLOW"}:
        cfo = ltm_of(cfo_keys, "cashflow")
        capex = ltm_of(capex_keys, "cashflow")
        if cfo is None or capex is None:
            return None
        return float(cfo) - float(capex)
    section = sec_index.get(token)
    if section == "balance":
        return _pick_value(q2025, "balance", [token], d_q1_2025)
    # treat as flow -> LTM = FY2024 + YTD2025 - YTD2024
    fy = _pick_value_year(k10k, "income", [token], 2024)
    if fy is None:
        fy = _pick_value_year(k10k, "cashflow", [token], 2024)
    y25 = _pick_value(q2025, "income", [token], d_q1_2025)
    if y25 is None:
        y25 = _pick_value(q2025, "cashflow", [token], d_q1_2025)
    y24 = _pick_value(q2024, "income", [token], d_q1_2024)
    if y24 is None:
        y24 = _pick_value(q2024, "cashflow", [token], d_q1_2024)
    return _compute_ltm(y25, fy, y24)


def _resolve_token_value_fy(token: str, year: int,
                            k10k: Dict[str, Any], sec_index: Dict[str, str]) -> Optional[float]:
    # Alias handling
    t = token.strip()
    if "." in t:
        t = t.split(".")[-1]
    tu = t.replace("_", "").upper()

    rent_keys = ["OperatingLeaseCost", "LeaseCost", "OperatingLeaseExpense", "RentExpense"]
    rev_keys = ["Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax", "OperatingLeaseLeaseIncome"]
    int_keys = ["InterestExpenseNonoperating", "InterestExpense"]
    ebitda_keys = ["Adjusted EBITDA", "EBITDA"]
    ni_keys = ["NetIncomeLoss"]
    tax_keys = ["IncomeTaxExpenseBenefit"]
    da_keys = ["DepreciationAndAmortization"]
    cash_keys = ["CashAndCashEquivalentsAtCarryingValue"]
    std_keys = ["ShortTermBorrowings", "DebtCurrent", "LongTermDebtCurrent"]
    ltd_keys = ["LongTermDebt"]
    equity_keys = ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"]
    ol_current_keys = ["OperatingLeaseLiabilityCurrent"]
    ol_noncurrent_keys = ["OperatingLeaseLiabilityNoncurrent", "OperatingLeaseLiability"]
    cfo_keys = ["NetCashProvidedByUsedInOperatingActivities"]
    capex_keys = ["PaymentsToAcquirePropertyPlantAndEquipment", "CapitalExpenditures"]

    if tu in {"COL", "CAPITALIZEDOPERATINGLEASES"}:
        olc = _pick_value_year(k10k, "balance", ol_current_keys, year) or 0.0
        olnc = _pick_value_year(k10k, "balance", ol_noncurrent_keys, year) or 0.0
        return (olc or 0.0) + (olnc or 0.0)
    if tu in {"TOTALDEBT", "TD", "DEBT"}:
        std = _pick_value_year(k10k, "balance", std_keys, year) or 0.0
        ltd = _pick_value_year(k10k, "balance", ltd_keys, year) or 0.0
        return (std or 0.0) + (ltd or 0.0)
    if tu in {"NETDEBT", "ND"}:
        td = _resolve_token_value_fy("TotalDebt", year, k10k, sec_index)
        cash = _pick_value_year(k10k, "balance", cash_keys, year) or 0.0
        return None if td is None else float(td) - float(cash)
    if tu in {"EQUITY", "BOOKEQUITY"}:
        return _pick_value_year(k10k, "balance", equity_keys, year)
    if tu in {"TOTALCAP", "TOTALCAPITAL", "BOOKCAPITAL", "CAPITAL"}:
        td = _resolve_token_value_fy("TotalDebt", year, k10k, sec_index) or 0.0
        col = _resolve_token_value_fy("COL", year, k10k, sec_index) or 0.0
        eq = _resolve_token_value_fy("Equity", year, k10k, sec_index) or 0.0
        return float(td) + float(col) + float(eq)
    if tu in {"RENT", "RENTS"}:
        return _pick_value_year(k10k, "income", rent_keys, year)
    if tu in {"REVENUE"}:
        return _pick_value_year(k10k, "income", rev_keys, year)
    if tu in {"INTEREST", "INTERESTEXPENSE"}:
        return _pick_value_year(k10k, "income", int_keys, year)
    if tu in {"CASH"}:
        return _pick_value_year(k10k, "balance", cash_keys, year)
    if tu in {"EBITDA"}:
        v = _pick_value_year(k10k, "income", ebitda_keys, year)
        if v is None:
            ni = _pick_value_year(k10k, "income", ni_keys, year) or 0.0
            intr = _pick_value_year(k10k, "income", int_keys, year) or 0.0
            tax = _pick_value_year(k10k, "income", tax_keys, year) or 0.0
            da = _pick_value_year(k10k, "income", da_keys, year) or 0.0
            return float(ni) + float(intr) + float(tax) + float(da)
        return v
    if tu in {"EBITDAR"}:
        e = _resolve_token_value_fy("EBITDA", year, k10k, sec_index)
        r = _resolve_token_value_fy("Rent", year, k10k, sec_index) or 0.0
        return None if e is None else float(e) + float(r)
    if tu in {"FCF", "FREECASHFLOW"}:
        cfo = _pick_value_year(k10k, "cashflow", cfo_keys, year)
        capex = _pick_value_year(k10k, "cashflow", capex_keys, year)
        if cfo is None or capex is None:
            return None
        return float(cfo) - float(capex)

    section = sec_index.get(token)
    if section == "balance":
        return _pick_value_year(k10k, "balance", [token], year)
    v = _pick_value_year(k10k, "income", [token], year)
    if v is None:
        v = _pick_value_year(k10k, "cashflow", [token], year)
    return v


def _eval_expr(tokens: List[str], expr: str, values: Dict[str, Optional[float]]) -> Optional[float]:
    locals_dict: Dict[str, float] = {}
    for t in tokens:
        v = values.get(t)
        locals_dict[t] = 0.0 if v is None else float(v)
    try:
        return float(eval(expr, {"__builtins__": {}}, locals_dict))
    except ZeroDivisionError:
        return None
    except Exception:
        return None


def _compute_company_metrics_from_mapping(ticker: str, mapping: Dict[str, Dict[str, Any]]) -> Dict[str, Optional[float]]:
    t = ticker.upper()
    q2025 = _read_processed_10q(t, 2025, "Q1")
    q2024 = _read_processed_10q(t, 2024, "Q1")
    k10k = _read_processed_10k_combined(t)

    # Dates
    def latest_date(container: Dict[str, Dict[str, Dict[str, float]]]) -> Optional[str]:
        # Try Revenues first else any income key
        for k in ["Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax"]:
            d = (container.get("income", {}) or {}).get(k)
            if isinstance(d, dict):
                dt = _get_latest_date(d)
                if dt:
                    return dt
        for _, d in (container.get("income", {}) or {}).items():
            if isinstance(d, dict):
                dt = _get_latest_date(d)
                if dt:
                    return dt
        return None

    d_q1_2025 = latest_date(q2025)
    d_q1_2024 = latest_date(q2024)
    sec_index = _index_sections(q2025, k10k)

    def eval_ltm_expr(expr: str) -> Optional[float]:
        import re
        tokens = list(set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr)))
        vals: Dict[str, Optional[float]] = {}
        for tok in tokens:
            vals[tok] = _resolve_token_value_ltm(tok, q2025, d_q1_2025, q2024, d_q1_2024, k10k, sec_index)
        return _eval_expr(tokens, expr, vals)

    def eval_fy_expr(expr: str, year: int) -> Optional[float]:
        import re
        tokens = list(set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr)))
        vals: Dict[str, Optional[float]] = {}
        for tok in tokens:
            vals[tok] = _resolve_token_value_fy(tok, year, k10k, sec_index)
        return _eval_expr(tokens, expr, vals)

    # Extract calculations
    def calc_of(name: str) -> Optional[str]:
        e = mapping.get(name)
        if not e:
            return None
        c = e.get("calculation")
        if isinstance(c, str) and c.strip():
            return c.strip()
        return None

    def base_key_from_fs(name: str) -> Optional[str]:
        e = mapping.get(name)
        if not e:
            return None
        keys = e.get("financial_statement_keys") or []
        for raw in keys:
            if not isinstance(raw, str):
                continue
            k = raw.split(".")[-1]
            if k and k.isidentifier():
                return k
        return None

    def default_expr_for_metric(name: str) -> Optional[str]:
        # Provide robust alias-based formulas when calculation is non-specific
        n = name.strip().upper()
        if n in {"LTM REVENUE", "REVENUE"}:
            k = base_key_from_fs(name)
            return k  # LTM handled by resolver
        if n in {"LTM EBITDA", "EBITDA", "ADJUSTED EBITDA"}:
            k = base_key_from_fs(name)
            return k or "EBITDA"
        if n == "EBITDA MARGIN %":
            return "EBITDA / Revenue * 100"
        if n == "EBITDAR / (INT + RENTS)":
            return "(EBITDA + Rent) / (Interest + Rent)"
        if n == "(TOTAL DEBT + COL) / EBITDAR":
            return "(TotalDebt + COL) / EBITDAR"
        if n == "(NET DEBT + COL) / EBITDAR":
            return "(NetDebt + COL) / EBITDAR"
        if n == "(TOTAL DEBT + COL) / TOTAL CAP":
            return "(TotalDebt + COL) / TotalCap"
        if n == "(FCF + RENTS) / (TOTAL DEBT + COL)":
            return "(FCF + Rent) / (TotalDebt + COL)"
        if n == "3Y AVG (TD+COL)/EBITDAR":
            return "(TotalDebt + COL) / EBITDAR"
        if n == "3Y AVG (TD+COL)/TOTAL CAP":
            return "(TotalDebt + COL) / TotalCap"
        if n == "3Y AVG (FCF+RENTS)/(TD+COL)":
            return "(FCF + Rent) / (TotalDebt + COL)"
        return None

    # LTM metrics via LLM-calculation expressions
    rev_expr = calc_of("LTM Revenue") or calc_of("Revenue") or default_expr_for_metric("LTM Revenue")
    ebitda_expr = calc_of("LTM EBITDA") or calc_of("EBITDA") or calc_of("Adjusted EBITDA") or default_expr_for_metric("LTM EBITDA")
    margin_expr = calc_of("EBITDA Margin %") or default_expr_for_metric("EBITDA Margin %")
    ebitdar_over_expr = calc_of("EBITDAR / (Int + Rents)") or default_expr_for_metric("EBITDAR / (Int + Rents)")
    td_col_over_ebitdar_expr = calc_of("(Total Debt + COL) / EBITDAR") or default_expr_for_metric("(Total Debt + COL) / EBITDAR")
    nd_col_over_ebitdar_expr = calc_of("(Net Debt + COL) / EBITDAR") or default_expr_for_metric("(Net Debt + COL) / EBITDAR")
    td_col_over_totcap_expr = calc_of("(Total Debt + COL) / Total Cap") or default_expr_for_metric("(Total Debt + COL) / Total Cap")
    fcf_plus_rents_over_td_col_expr = calc_of("(FCF + Rents) / (Total Debt + COL)") or default_expr_for_metric("(FCF + Rents) / (Total Debt + COL)")

    ltm_revenue = eval_ltm_expr(rev_expr) if rev_expr else None
    ltm_ebitda = eval_ltm_expr(ebitda_expr) if ebitda_expr else None

    if margin_expr:
        ebitda_margin = eval_ltm_expr(margin_expr)
    else:
        ebitda_margin = None
        if ltm_revenue not in (None, 0) and ltm_ebitda is not None:
            try:
                ebitda_margin = (ltm_ebitda / ltm_revenue) * 100.0
            except Exception:
                ebitda_margin = None

    ebitdar_over = eval_ltm_expr(ebitdar_over_expr) if ebitdar_over_expr else None
    td_col_over_ebitdar = eval_ltm_expr(td_col_over_ebitdar_expr) if td_col_over_ebitdar_expr else None
    nd_col_over_ebitdar = eval_ltm_expr(nd_col_over_ebitdar_expr) if nd_col_over_ebitdar_expr else None
    td_col_over_total_cap = eval_ltm_expr(td_col_over_totcap_expr) if td_col_over_totcap_expr else None
    fcf_plus_rents_over_td_col = eval_ltm_expr(fcf_plus_rents_over_td_col_expr) if fcf_plus_rents_over_td_col_expr else None

    # 3Y averages
    def avg3(name: str) -> Optional[float]:
        expr = calc_of(name)
        if not expr:
            return None
        vals: List[float] = []
        for y in [2024, 2023, 2022]:
            v = eval_fy_expr(expr, y)
            if v is not None:
                vals.append(float(v))
        if not vals:
            return None
        return sum(vals) / len(vals)

    r1_3y = avg3("3Y Avg (TD+COL)/EBITDAR")
    r2_3y = avg3("3Y Avg (TD+COL)/Total Cap")
    r3_3y = avg3("3Y Avg (FCF+Rents)/(TD+COL)")

    return {
        "LTM Revenue": ltm_revenue,
        "LTM EBITDA": ltm_ebitda,
        "EBITDA Margin %": ebitda_margin,
        "EBITDAR / (Int + Rents)": ebitdar_over,
        "(Total Debt + COL) / EBITDAR": td_col_over_ebitdar,
        "(Net Debt + COL) / EBITDAR": nd_col_over_ebitdar,
        "(Total Debt + COL) / Total Cap": td_col_over_total_cap,
        "(FCF + Rents) / (Total Debt + COL)": fcf_plus_rents_over_td_col,
        "3Y Avg (TD+COL)/EBITDAR": r1_3y,
        "3Y Avg (TD+COL)/Total Cap": r2_3y,
        "3Y Avg (FCF+Rents)/(TD+COL)": r3_3y,
    }


def save_table(rows: List[Dict[str, Any]], ticker: str, year: int = 2025, quarter: str = "Q1") -> Tuple[Optional[str], Optional[str]]:
    os.makedirs(OUTPUT_JSON_DIR, exist_ok=True)
    os.makedirs(OUTPUT_CSV_DIR, exist_ok=True)
    base = f"{ticker.upper()}_{year}_{quarter}"
    json_path = os.path.join(OUTPUT_JSON_DIR, f"{base}.json")
    csv_path = os.path.join(OUTPUT_CSV_DIR, f"{base}.csv")
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)
    except Exception:
        json_path = None
    try:
        if rows:
            cols = list(rows[0].keys())
        else:
            cols = ["Ticker"]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k) for k in cols})
    except Exception:
        csv_path = None
    return json_path, csv_path


def run_comp_analysis(ticker: str, write_files: bool = True) -> Dict[str, Any]:
    result = build_comp_table(ticker, ensure_fetch=True)
    json_path = None
    csv_path = None
    if write_files:
        json_path, csv_path = save_table(result.get("rows", []), ticker, 2025, "Q1")
    return {"ticker": ticker.upper(), "rows": result.get("rows", []), "tickers": result.get("tickers", []), "warnings": result.get("warnings", []), "json_path": json_path, "csv_path": csv_path}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build comparable analysis table (Q1 2025 focus)")
    parser.add_argument("--ticker", required=True, help="Input company ticker")
    args = parser.parse_args()
    out = run_comp_analysis(args.ticker, write_files=True)
    print(json.dumps(out, indent=2))
