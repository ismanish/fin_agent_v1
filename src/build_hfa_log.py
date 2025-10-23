import csv
import json
import os
import copy
from typing import Dict, List, Optional, Any
import argparse
from datetime import datetime
import re

try:
    import yaml  # pyyaml is in requirements.txt
except Exception:
    yaml = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(ROOT, "static", "aqrr_key_schema.yaml")
MAPPING_PATH = os.path.join(ROOT, "utils", "mapping_calculation.json")
YEARS = [2024, 2023, 2022, 2021, 2020]
Number = Optional[float]

# Global logging dictionary
hfa_log = {
    "ticker": "",
    "timestamp": "",
    "metrics": {}
}

def read_keyed_csv(path: str) -> Dict[str, Dict[int, Number]]:
    table: Dict[str, Dict[int, Number]] = {}
    if not os.path.exists(path):
        return table
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get("key")
            if not key:
                continue
            table[key] = {}
            for y in YEARS:
                v = row.get(str(y), "").strip()
                if v == "" or v is None:
                    table[key][y] = None
                else:
                    try:
                        table[key][y] = float(v)
                    except Exception:
                        table[key][y] = None
    return table

def load_schema_keys() -> List[str]:
    # File is JSON-like content with .yaml extension
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        raw = f.read()
    # Try JSON first
    try:
        obj = json.loads(raw)
        return list(obj.get("aqrr_keys", []))
    except Exception:
        pass
    # Fallback to yaml if available
    if yaml is None:
        raise RuntimeError("Failed to parse schema; install pyyaml or fix JSON format.")
    data = yaml.safe_load(raw)
    return list(data.get("aqrr_keys", []))

def load_mapping(ticker: str, filing_type: str) -> List[Dict[str, Any]]:
    with open(MAPPING_PATH, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    if ticker not in mapping:
        raise KeyError(f"Ticker '{ticker}' not found in mapping_calculation.json")
    ticker_map = mapping[ticker]
    if filing_type not in ticker_map:
        raise KeyError(f"Filing type '{filing_type}' not found for ticker '{ticker}' in mapping_calculation.json")
    arr = ticker_map[filing_type]
    if not isinstance(arr, list) or not arr:
        raise ValueError(f"Invalid mapping structure for {ticker} {filing_type}")
    # Each filing type holds a list of one list (array of items)
    return arr[0]

def format_final_value(metric_name: str, value: Number) -> Any:
    """
    Format the given value to match how it appears in the PDF output:
    - Divide raw numbers by 1000 and format with commas and parentheses for negatives.
    - Format certain metrics as percentages or ratios with 'x' suffix.
    - Return None if value is None.
    """
    if value is None:
        return None
    
    # Define the categories without modifying mapping_calculation.json
    percentage_metrics = {"% YoY Growth", "% Margin", "Total Debt / Book Capital", "Total Debt + Leases / Book Capital"}
    ratio_metrics = {
        "EBITDA / Int. Exp.",
        "Total Debt / EBITDA",
        "Total Debt + Leases / EBITDA",
        "EBITDAR / Interest + Rent",
    }
    
    # Handle percentage metrics
    if metric_name in percentage_metrics:
        try:
            # percentage is stored as raw percentage number (e.g. 7.5 for 7.5%)
            f = float(value)
            if f < 0:
                return f"({abs(f):.1f}%)"
            else:
                return f"{f:.1f}%"
        except Exception:
            return str(value)
    
    # Handle ratio metrics - format as x.xx (no scaling) - UPDATED TO 2 DECIMAL PLACES
    if metric_name in ratio_metrics:
        try:
            f = float(value)
            if f < 0:
                return f"({abs(f):.2f}x)"  # Changed from .1f to .2f
            else:
                return f"{f:.2f}x"        # Changed from .1f to .2f
        except Exception:
            return str(value)
    
    # Default: treat as raw number, divide by 1000 and format
    try:
        f = float(value) / 1000.0
        if abs(f - int(f)) < 1e-6:
            if f < 0:
                return f"({int(abs(f)):,})"
            else:
                return f"{int(f):,}"
        else:
            if f < 0:
                return f"({abs(f):,.1f})"
            else:
                return f"{f:,.1f}"
    except Exception:
        return str(value)

class DataStore:
    def __init__(self, income: Dict[str, Dict[int, Number]], balance: Dict[str, Dict[int, Number]], cashflow: Dict[str, Dict[int, Number]]):
        self.sources = [income, balance, cashflow]
        self.table_names = ["income", "balance", "cashflow"]
    
    def get(self, key: str, year: int) -> Number:
        # Fallback InterestExpenseNonoperating -> InterestExpense when missing
        search_keys = [key]
        if key == "InterestExpenseNonoperating":
            search_keys.append("InterestExpense")
        for src in self.sources:
            for k in search_keys:
                if k in src:
                    val = src[k].get(year)
                    if val is not None:
                        return val
        return None
    
    def get_with_source_info(self, key: str, year: int) -> tuple[Number, Optional[Dict[str, Any]]]:
        """Returns value and source information for logging"""
        search_keys = [key]
        if key == "InterestExpenseNonoperating":
            search_keys.append("InterestExpense")
        
        for i, src in enumerate(self.sources):
            for k in search_keys:
                if k in src:
                    val = src[k].get(year)
                    if val is not None:
                        source_info = {
                            "value": val,
                            "filing_type": "10-K",
                            "table": self.table_names[i],
                            "period": str(year),
                            "location": {
                                "row": k,
                                "column": str(year)
                            }
                        }
                        return val, source_info
        return None, None

def safe_eval_expr(expr: str, year: int, store: DataStore) -> tuple[Number, List[Dict[str, Any]]]:
    # Build variables dict for all candidate tokens (A-Za-z0-9_ only)
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr))
    local_vars: Dict[str, float] = {}
    sources_used = []
    
    for t in tokens:
        v, source_info = store.get_with_source_info(t, year)
        # Treat missing values as 0 for additive formulas; ratios will handle None/zero later
        local_vars[t] = 0.0 if v is None else float(v)
        if source_info:
            sources_used.append({t: source_info})
    
    # Evaluate arithmetic expression only
    try:
        result = float(eval(expr, {"__builtins__": {}}, local_vars))
        return result, sources_used
    except ZeroDivisionError:
        return None, sources_used
    except Exception:
        return None, sources_used

# ---------- 10-Q helpers (date-keyed) ----------
def read_keyed_csv_dates(path: str) -> Dict[str, Dict[str, Number]]:
    table: Dict[str, Dict[str, Number]] = {}
    if not os.path.exists(path):
        return table
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get("key")
            if not key:
                continue
            table[key] = {}
            for col, v in row.items():
                if col == "key":
                    continue
                v = (v or "").strip()
                if v == "":
                    table[key][col] = None
                else:
                    try:
                        table[key][col] = float(v)
                    except Exception:
                        table[key][col] = None
    return table

class DataStoreQ:
    def __init__(self, income_q: Dict[str, Dict[str, Number]], balance_q: Dict[str, Dict[str, Number]], cashflow_q: Dict[str, Dict[str, Number]]):
        self.sources = [income_q, balance_q, cashflow_q]
        self.table_names = ["income", "balance", "cashflow"]
    
    def get(self, key: str, date: str) -> Number:
        search_keys = [key]
        if key == "InterestExpenseNonoperating":
            search_keys.append("InterestExpense")
        for src in self.sources:
            for k in search_keys:
                if k in src:
                    val = src[k].get(date)
                    if val is not None:
                        return val
        return None
    
    def get_with_source_info(self, key: str, date: str) -> tuple[Number, Optional[Dict[str, Any]]]:
        """Returns value and source information for logging"""
        search_keys = [key]
        if key == "InterestExpenseNonoperating":
            search_keys.append("InterestExpense")
        
        # Determine filing type and period from date
        year = date[:4]
        if date.endswith("03-31"):
            filing_type = "10-Q"
            period = f"Q1 {year}"
        elif date.endswith("06-30"):
            filing_type = "10-Q"
            period = f"Q2 {year}"
        elif date.endswith("09-30"):
            filing_type = "10-Q"
            period = f"Q3 {year}"
        elif date.endswith("12-31"):
            filing_type = "10-Q"
            period = f"Q4 {year}"
        else:
            filing_type = "10-Q"
            period = f"Q1 {year}"  # default
        
        for i, src in enumerate(self.sources):
            for k in search_keys:
                if k in src:
                    val = src[k].get(date)
                    if val is not None:
                        source_info = {
                            "value": val,
                            "filing_type": filing_type,
                            "table": self.table_names[i],
                            "period": period,
                            "location": {
                                "row": k,
                                "column": date
                            }
                        }
                        return val, source_info
        return None, None

def safe_eval_expr_q(expr: str, default_date: str, store_q: DataStoreQ, computed: Dict[str, Number]) -> tuple[Number, List[Dict[str, Any]]]:
    # Support tokens like Name[YYYY-MM-DD]; tokens without date try computed AQRR first, else FS at default_date
    pattern = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\[(\d{4}-\d{2}-\d{2})\]")
    subs: Dict[str, float] = {}
    sources_used = []
    
    def repl(m):
        name, date = m.group(1), m.group(2)
        var = f"__{name}_{date}__"
        val, source_info = store_q.get_with_source_info(name, date)
        subs[var] = 0.0 if val is None else float(val)
        if source_info:
            sources_used.append({name: source_info})
        return var
    
    expr2 = pattern.sub(lambda m: repl(m), expr)
    # Collect remaining tokens (unbracketed)
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr2))
    local_vars: Dict[str, float] = {k: v for k, v in subs.items()}
    
    for t in tokens:
        if t in {"x"}:  # allow literals like '3.2x' not expected here
            continue
        if t in computed:
            local_vars[t] = 0.0 if computed[t] is None else float(computed[t])
        else:
            v, source_info = store_q.get_with_source_info(t, default_date)
            local_vars[t] = 0.0 if v is None else float(v)
            if source_info:
                sources_used.append({t: source_info})
    
    try:
        result = float(eval(expr2, {"__builtins__": {}}, local_vars))
        return result, sources_used
    except ZeroDivisionError:
        return None, sources_used
    except Exception:
        return None, sources_used
    
def get_sources_from_logged_metric(metric_name: str, period: str) -> List[Dict[str, Any]]:
    """Get sources from previously logged metric calculation"""
    global hfa_log
    if metric_name in hfa_log.get("metrics", {}) and period in hfa_log["metrics"][metric_name]:
        sources_dict = hfa_log["metrics"][metric_name][period]["sources"]
        return [{k: v} for k, v in sources_dict.items()]
    return []

def log_metric_calculation(metric_name: str, period: str, value: Number, calculation: str, sources: List[Dict[str, Any]]):
    """Add metric calculation to the global log with an additional final_value key."""
    global hfa_log
    
    if metric_name not in hfa_log["metrics"]:
        hfa_log["metrics"][metric_name] = {}
    
    # Flatten sources list into a single sources dict
    sources_dict = {}
    for source_item in sources:
        for source_name, source_info in source_item.items():
            sources_dict[source_name] = source_info
    
    # Calculate final_value for display consistency with PDF
    final_value = format_final_value(metric_name, value)
    
    hfa_log["metrics"][metric_name][period] = {
        "value": value,
        "final_value": final_value,
        "calculation": calculation,
        "sources": sources_dict
    }

def compute_period_rows_q(mapping_items: List[Dict[str, Any]], store_q: DataStoreQ, default_date: str) -> List[Dict[str, Any]]:
    computed: Dict[str, Number] = {}
    rows: List[Dict[str, Any]] = []
    
    # Determine period string for logging
    year = default_date[:4]
    if default_date.endswith("03-31"):
        period_str = f"YTD {year}"
    else:
        period_str = f"YTD {year}"
    
    for item in mapping_items:
        aqrr_key = item.get("aqrr_key")
        calc = item.get("calculation", "")
        dep_aqrr = item.get("aqrr_keys", []) or []
        
        # Special cases align with 10-K logic
        val: Number = None
        sources_used = []
        
        if aqrr_key == "% Margin" and len(dep_aqrr) == 2:
            num = computed.get(dep_aqrr[0])
            den = computed.get(dep_aqrr[1])
            calc_formula = f"{dep_aqrr[0]} / {dep_aqrr[1]} * 100"
            # Get sources from previously logged computed values
            if dep_aqrr[0] in hfa_log.get("metrics", {}) and period_str in hfa_log["metrics"][dep_aqrr[0]]:
                num_sources = hfa_log["metrics"][dep_aqrr[0]][period_str]["sources"]
                sources_used.extend([{k: v} for k, v in num_sources.items()])
            if dep_aqrr[1] in hfa_log.get("metrics", {}) and period_str in hfa_log["metrics"][dep_aqrr[1]]:
                den_sources = hfa_log["metrics"][dep_aqrr[1]][period_str]["sources"]
                sources_used.extend([{k: v} for k, v in den_sources.items()])
            if den in (None, 0):
                val = None
            else:
                try:
                    val = float(num) / float(den) * 100.0
                except Exception:
                    val = None
        elif aqrr_key == "EBITDA / Int. Exp.":
            ebitda = computed.get("Adjusted EBITDA")
            interest, interest_source = store_q.get_with_source_info("InterestExpenseNonoperating", default_date)
            calc_formula = "Adjusted EBITDA / InterestExpenseNonoperating"
            if interest_source:
                sources_used.append({"InterestExpenseNonoperating": interest_source})
            if interest in (None, 0):
                val = None
            else:
                try:
                    val = float(ebitda if ebitda is not None else 0.0) / float(interest)
                except Exception:
                    val = None
        elif aqrr_key in ("Total Debt / EBITDA", "Total Debt + Leases / EBITDA"):
            # Use stock total debt at period end, EBITDA from computed
            notes, notes_source = store_q.get_with_source_info("NotesPayable", default_date)
            loc, loc_source = store_q.get_with_source_info("LineOfCredit", default_date)
            total_debt = (notes or 0.0) + (loc or 0.0)
            ebitda = computed.get("Adjusted EBITDA")
            calc_formula = "(NotesPayable + LineOfCredit) / Adjusted EBITDA"
            if notes_source:
                sources_used.append({"NotesPayable": notes_source})
            if loc_source:
                sources_used.append({"LineOfCredit": loc_source})
            if ebitda in (None, 0):
                val = None
            else:
                try:
                    val = float(total_debt) / float(ebitda)
                except Exception:
                    val = None
        elif aqrr_key in ("Total Debt / Book Capital", "Total Debt + Leases / Book Capital"):
            notes, notes_source = store_q.get_with_source_info("NotesPayable", default_date)
            loc, loc_source = store_q.get_with_source_info("LineOfCredit", default_date)
            equity, equity_source = store_q.get_with_source_info("StockholdersEquity", default_date)
            calc_formula = "(NotesPayable + LineOfCredit) / (NotesPayable + LineOfCredit + StockholdersEquity) * 100"
            if notes_source:
                sources_used.append({"NotesPayable": notes_source})
            if loc_source:
                sources_used.append({"LineOfCredit": loc_source})
            if equity_source:
                sources_used.append({"StockholdersEquity": equity_source})
            denom = ((notes or 0.0) + (loc or 0.0) + (0.0 if equity is None else float(equity)))
            if denom in (None, 0):
                val = None
            else:
                val = ((notes or 0.0) + (loc or 0.0)) / denom * 100.0
        else:
            if "Not available" in calc:
                val = None
                calc_formula = "Not available"
            elif calc:
                val, sources_used = safe_eval_expr_q(calc, default_date, store_q, computed)
                calc_formula = calc
            else:
                val = None
                calc_formula = ""
        
        # Log this metric calculation
        log_metric_calculation(aqrr_key, period_str, val, calc_formula, sources_used)
        
        rows.append({"Metric": aqrr_key, "value": val})
        computed[aqrr_key] = val
    return rows

def align_period_values_by_schema(schema_keys: List[str], period_rows: List[Dict[str, Any]]) -> List[Number]:
    name_to_rows: Dict[str, List[Number]] = {}
    for r in period_rows:
        name_to_rows.setdefault(r["Metric"], []).append(r["value"])
    aligned: List[Number] = []
    used_counts: Dict[str, int] = {}
    for name in schema_keys:
        cnt = used_counts.get(name, 0)
        if name in name_to_rows and cnt < len(name_to_rows[name]):
            aligned.append(name_to_rows[name][cnt])
            used_counts[name] = cnt + 1
        else:
            aligned.append(None)
    return aligned

def compute_table(schema_keys: List[str], mapping_items: List[Dict[str, Any]], store: DataStore) -> List[Dict[str, Any]]:
    # Map aqrr_key -> mapping item and preserve order from mapping
    ordered_items: List[Dict[str, Any]] = mapping_items[:]
    # For metrics that depend on previously computed AQRR keys, we'll store computed values here
    computed: Dict[str, Dict[int, Number]] = {}
    # Store sources for computed values
    computed_sources: Dict[str, Dict[int, List[Dict[str, Any]]]] = {}
    output_rows: List[Dict[str, Any]] = []
    
    for item in ordered_items:
        aqrr_key = item.get("aqrr_key")
        calc = item.get("calculation", "")
        dep_aqrr = item.get("aqrr_keys", []) or []
        fin_keys = item.get("financial_statement_keys", []) or []
        row: Dict[str, Any] = {"Metric": aqrr_key}
        
        for year in YEARS:
            val: Number = None
            sources_used = []
            calc_formula = calc
            
            # Special handling for % YoY Growth (compute from Revenue YoY)
            if aqrr_key == "% YoY Growth":
                # Requires Revenue of this and previous year
                prev_year = year - 1
                if prev_year in YEARS:
                    rev_curr = computed.get("Revenue", {}).get(year)
                    rev_prev = computed.get("Revenue", {}).get(prev_year)
                    
                    # Get sources from computed Revenue if available, otherwise from financial statements
                    if rev_curr is not None and "Revenue" in computed_sources and year in computed_sources["Revenue"]:
                        curr_sources = computed_sources["Revenue"][year]
                        sources_used.extend(curr_sources)
                    elif rev_curr is None:
                        rev_curr, curr_source = store.get_with_source_info("Revenues", year)
                        if curr_source:
                            sources_used.append({"Revenues": curr_source})
                    else:
                        # rev_curr from computed but no sources tracked, get from financial statements
                        _, curr_source = store.get_with_source_info("Revenues", year)
                        if curr_source:
                            sources_used.append({"Revenues": curr_source})
                    
                    if rev_prev is not None and "Revenue" in computed_sources and prev_year in computed_sources["Revenue"]:
                        prev_sources = computed_sources["Revenue"][prev_year]
                        sources_used.extend(prev_sources)
                    elif rev_prev is None:
                        rev_prev, prev_source = store.get_with_source_info("Revenues", prev_year)
                        if prev_source:
                            sources_used.append({"Revenues": prev_source})
                    else:
                        # rev_prev from computed but no sources tracked, get from financial statements
                        _, prev_source = store.get_with_source_info("Revenues", prev_year)
                        if prev_source:
                            sources_used.append({"Revenues": prev_source})
                    
                    calc_formula = f"(Revenues[{year}] - Revenues[{prev_year}]) / Revenues[{prev_year}] * 100"
                    if rev_prev in (None, 0):
                        val = None
                    else:
                        try:
                            val = (float(rev_curr) - float(rev_prev)) / float(rev_prev) * 100.0
                        except Exception:
                            val = None
                else:
                    val = None
                    calc_formula = "Previous year data not available"
            # Margin rows: if depends on two AQRR keys, compute ratio * 100
            elif aqrr_key == "% Margin" and len(dep_aqrr) == 2:
                num_key, den_key = dep_aqrr[0], dep_aqrr[1]
                num = computed.get(num_key, {}).get(year)
                den = computed.get(den_key, {}).get(year)
                calc_formula = f"{num_key} / {den_key} * 100"
                # Get sources from computed dependencies
                num_sources = computed_sources.get(num_key, {}).get(year, [])
                den_sources = computed_sources.get(den_key, {}).get(year, [])
                sources_used.extend(num_sources + den_sources)
                if den in (None, 0):
                    val = None
                else:
                    try:
                        val = float(num) / float(den) * 100.0
                    except Exception:
                        val = None
            # Ratios that are better derived from already computed AQRR keys
            elif aqrr_key == "EBITDA / Int. Exp.":
                ebitda = computed.get("Adjusted EBITDA", {}).get(year)
                interest, interest_source = store.get_with_source_info("InterestExpenseNonoperating", year)
                calc_formula = "Adjusted EBITDA / InterestExpenseNonoperating"
                # Get sources from computed EBITDA
                ebitda_sources = computed_sources.get("Adjusted EBITDA", {}).get(year, [])
                sources_used.extend(ebitda_sources)
                if interest_source:
                    sources_used.append({"InterestExpenseNonoperating": interest_source})
                if interest in (None, 0):
                    val = None
                else:
                    try:
                        val = float(ebitda if ebitda is not None else 0.0) / float(interest)
                    except Exception:
                        val = None
            elif aqrr_key == "Total Debt / EBITDA":
                total_debt = computed.get("Total Debt", {}).get(year)
                ebitda = computed.get("Adjusted EBITDA", {}).get(year)
                calc_formula = "Total Debt / Adjusted EBITDA"
                # Get sources from computed dependencies
                debt_sources = computed_sources.get("Total Debt", {}).get(year, [])
                ebitda_sources = computed_sources.get("Adjusted EBITDA", {}).get(year, [])
                sources_used.extend(debt_sources + ebitda_sources)
                if ebitda in (None, 0):
                    val = None
                else:
                    try:
                        val = float(total_debt if total_debt is not None else 0.0) / float(ebitda)
                    except Exception:
                        val = None
            elif aqrr_key == "Total Debt + Leases / EBITDA":
                total_debt = computed.get("Total Debt", {}).get(year)
                ebitda = computed.get("Adjusted EBITDA", {}).get(year)
                calc_formula = "Total Debt / Adjusted EBITDA"
                # Get sources from computed dependencies
                debt_sources = computed_sources.get("Total Debt", {}).get(year, [])
                ebitda_sources = computed_sources.get("Adjusted EBITDA", {}).get(year, [])
                sources_used.extend(debt_sources + ebitda_sources)
                if ebitda in (None, 0):
                    val = None
                else:
                    try:
                        val = float(total_debt if total_debt is not None else 0.0) / float(ebitda)
                    except Exception:
                        val = None
            elif aqrr_key == "Total Debt / Book Capital":
                notes, notes_source = store.get_with_source_info("NotesPayable", year)
                loc, loc_source = store.get_with_source_info("LineOfCredit", year)
                equity, equity_source = store.get_with_source_info("StockholdersEquity", year)
                calc_formula = "(NotesPayable + LineOfCredit) / (NotesPayable + LineOfCredit + StockholdersEquity) * 100"
                if notes_source:
                    sources_used.append({"NotesPayable": notes_source})
                if loc_source:
                    sources_used.append({"LineOfCredit": loc_source})
                if equity_source:
                    sources_used.append({"StockholdersEquity": equity_source})
                denom = ((notes or 0.0) + (loc or 0.0) + (0.0 if equity is None else float(equity)))
                if denom in (None, 0):
                    val = None
                else:
                    try:
                        val = ((notes or 0.0) + (loc or 0.0)) / denom * 100.0
                    except Exception:
                        val = None
            elif aqrr_key == "Total Debt + Leases / Book Capital":
                notes, notes_source = store.get_with_source_info("NotesPayable", year)
                loc, loc_source = store.get_with_source_info("LineOfCredit", year)
                equity, equity_source = store.get_with_source_info("StockholdersEquity", year)
                calc_formula = "(NotesPayable + LineOfCredit) / (NotesPayable + LineOfCredit + StockholdersEquity) * 100"
                if notes_source:
                    sources_used.append({"NotesPayable": notes_source})
                if loc_source:
                    sources_used.append({"LineOfCredit": loc_source})
                if equity_source:
                    sources_used.append({"StockholdersEquity": equity_source})
                denom = ((notes or 0.0) + (loc or 0.0) + (0.0 if equity is None else float(equity)))
                if denom in (None, 0):
                    val = None
                else:
                    try:
                        val = ((notes or 0.0) + (loc or 0.0)) / denom * 100.0
                    except Exception:
                        val = None
            # Generic expression evaluation using financial statement keys
            else:
                if "Not available" in calc:
                    val = None
                    calc_formula = "Not available"
                elif calc:
                    # Normalize expression: no year-specific tokens here for 10-K except YoY which we handled
                    expr = calc
                    val, sources_used = safe_eval_expr(expr, year, store)
                    calc_formula = calc
                else:
                    # If no calculation provided but there is a single financial key, pass-through
                    if fin_keys:
                        v, source_info = store.get_with_source_info(fin_keys[0], year)
                        val = None if v is None else float(v)
                        calc_formula = fin_keys[0]
                        if source_info:
                            sources_used.append({fin_keys[0]: source_info})
                    else:
                        val = None
                        calc_formula = ""
            
            # Log this metric calculation
            log_metric_calculation(aqrr_key, str(year), val, calc_formula, sources_used)
            
            row[str(year)] = val
            
            # Save sources for this metric and year
            if aqrr_key not in computed_sources:
                computed_sources[aqrr_key] = {}
            computed_sources[aqrr_key][year] = sources_used
        
        # Save into computed for reuse
        computed[aqrr_key] = {y: row[str(y)] for y in YEARS}
        output_rows.append(row)
    
    # Reorder rows to match schema order, preserving duplicates where names repeat
    # Build a mapping from name to list of rows encountered in order
    name_to_rows: Dict[str, List[Dict[str, Any]]] = {}
    for r in output_rows:
        name_to_rows.setdefault(r["Metric"], []).append(r)
    final_rows: List[Dict[str, Any]] = []
    used_counts: Dict[str, int] = {}
    for name in schema_keys:
        cnt = used_counts.get(name, 0)
        if name in name_to_rows and cnt < len(name_to_rows[name]):
            final_rows.append(name_to_rows[name][cnt])
            used_counts[name] = cnt + 1
        else:
            # If a schema name wasn't computed, add a blank row
            blank = {"Metric": name}
            for y in YEARS:
                blank[str(y)] = None
            final_rows.append(blank)
    return final_rows

def write_output(rows: List[Dict[str, Any]], path: str) -> None:
    # Dynamically derive fieldnames from first row
    fieldnames = list(rows[0].keys()) if rows else ["Metric"] + [str(y) for y in YEARS]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

def write_output_json(rows: List[Dict[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

def save_hfa_log(ticker: str, timestamp: str) -> str:
    """Save the HFA log to a JSON file and return the path"""
    logs_dir = os.path.join(ROOT, "logs", "HFA")
    os.makedirs(logs_dir, exist_ok=True)
    log_filename = f"HFA_{ticker}_{timestamp}.json"
    log_path = os.path.join(logs_dir, log_filename)
    
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(hfa_log, f, ensure_ascii=False, indent=2)
    
    print(f"HFA calculation log saved to: {log_path}")
    return log_path

def find_data_dir(ticker: str, filing_type: str) -> str:
    base = os.path.join(ROOT, "output", "csv", ticker)
    # Default expected directory name pattern
    expected = os.path.join(base, f"{filing_type}_2020-2024_combined")
    if os.path.isdir(expected):
        return expected
    # Fallback: search for a subdirectory containing filing_type with required files
    if not os.path.isdir(base):
        raise FileNotFoundError(f"Data directory not found: {base}")
    candidates = []
    for name in os.listdir(base):
        p = os.path.join(base, name)
        if os.path.isdir(p) and filing_type in name:
            income_p = os.path.join(p, "income.csv")
            balance_p = os.path.join(p, "balance.csv")
            cashflow_p = os.path.join(p, "cashflow.csv")
            if os.path.exists(income_p) and os.path.exists(balance_p) and os.path.exists(cashflow_p):
                candidates.append(p)
    if candidates:
        # Prefer lexicographically last (e.g., latest combined)
        candidates.sort()
        return candidates[-1]
    raise FileNotFoundError(f"Could not locate data subdirectory under {base} for filing type {filing_type}")

def build_hfa_outputs(ticker: str, filing: str, write_files: bool = True, upload_to_azure: bool = False) -> Dict[str, Any]:
    """Compute HFA table for ticker/filing, append YTD and LTM, and optionally write CSV/JSON.
    Returns a dict: {"ticker", "filing", "rows", "csv_path", "json_path"}.
    """
    global hfa_log
    
    # Initialize the log
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    hfa_log = {
        "ticker": ticker,
        "timestamp": timestamp,
        "metrics": {}
    }
    
    data_dir = find_data_dir(ticker, filing)
    income_csv = os.path.join(data_dir, "income.csv")
    balance_csv = os.path.join(data_dir, "balance.csv")
    cashflow_csv = os.path.join(data_dir, "cashflow.csv")
    income = read_keyed_csv(income_csv)
    balance = read_keyed_csv(balance_csv)
    cashflow = read_keyed_csv(cashflow_csv)
    store = DataStore(income, balance, cashflow)
    schema_keys = load_schema_keys()
    mapping_items = load_mapping(ticker, filing)
    rows = compute_table(schema_keys, mapping_items, store)
    
    # --- Append YTD 2024, YTD 2025 using 10-Q mappings ---
    mapping_items_q = load_mapping(ticker, "10-Q")
    q2024_dir = find_data_dir(ticker, "10-Q_2024_Q1") if filing == "10-K" else find_data_dir(ticker, filing)
    q2025_dir = find_data_dir(ticker, "10-Q_2025_Q1") if filing == "10-K" else find_data_dir(ticker, filing)
    
    def load_q_store(qdir: str) -> DataStoreQ:
        inc = read_keyed_csv_dates(os.path.join(qdir, "income.csv"))
        bal = read_keyed_csv_dates(os.path.join(qdir, "balance.csv"))
        cfl = read_keyed_csv_dates(os.path.join(qdir, "cashflow.csv"))
        return DataStoreQ(inc, bal, cfl)
    
    store_q_2024 = load_q_store(q2024_dir)
    store_q_2025 = load_q_store(q2025_dir)
    ytd2024_rows = compute_period_rows_q(mapping_items_q, store_q_2024, "2024-03-31")
    ytd2025_rows = compute_period_rows_q(mapping_items_q, store_q_2025, "2025-03-31")
    ytd2024_vals = align_period_values_by_schema(schema_keys, ytd2024_rows)
    ytd2025_vals = align_period_values_by_schema(schema_keys, ytd2025_rows)
    
    # --- Compute LTM 2025 ---
    stock_metrics = {"Cash - End of Period", "Total Debt", "Book Equity"}
    ltm_vals: List[Number] = []
    fy2024_vals = [r.get("2024") for r in rows]
    base_ltm_vals: List[Number] = []
    
    for idx, r in enumerate(rows):
        name = r["Metric"]
        if name in stock_metrics:
            base_ltm_vals.append(ytd2025_vals[idx])
            # Get YTD 2025 sources from log
            ytd_sources = []
            if name in hfa_log["metrics"] and "YTD 2025" in hfa_log["metrics"][name]:
                ytd_sources = list(hfa_log["metrics"][name]["YTD 2025"]["sources"].items())
                ytd_sources = [{k: v} for k, v in ytd_sources]
            log_metric_calculation(name, "LTM 2025", ytd2025_vals[idx], "YTD 2025 value (stock metric)", ytd_sources)
        else:
            a = fy2024_vals[idx]
            b = ytd2025_vals[idx]
            c = ytd2024_vals[idx]
            # Get sources from previous periods
            ltm_sources = []
            if name in hfa_log["metrics"]:
                for period in ["2024", "YTD 2025", "YTD 2024"]:
                    if period in hfa_log["metrics"][name]:
                        period_sources = hfa_log["metrics"][name][period]["sources"]
                        ltm_sources.extend([{k: v} for k, v in period_sources.items()])
            try:
                if a is None or b is None or c is None:
                    ltm_val = None
                else:
                    ltm_val = float(a) + float(b) - float(c)
                base_ltm_vals.append(ltm_val)
                # Log LTM calculation
                log_metric_calculation(name, "LTM 2025", ltm_val, f"2024 + YTD 2025 - YTD 2024", ltm_sources)
            except Exception:
                base_ltm_vals.append(None)
                log_metric_calculation(name, "LTM 2025", None, f"2024 + YTD 2025 - YTD 2024", ltm_sources)
    
    def find_row_index(metric_name: str, occurrence: int = 0) -> Optional[int]:
        count = 0
        for i, rr in enumerate(rows):
            if rr["Metric"] == metric_name:
                if count == occurrence:
                    return i
                count += 1
        return None
    
    for idx, r in enumerate(rows):
        name = r["Metric"]
        if name == "% Margin":
            gp_idx = find_row_index("Gross Profit", 0)
            rev_idx = find_row_index("Revenue", 0)
            ebitda_idx = find_row_index("Adjusted EBITDA", 0)
            num = None
            den = None
            calc_formula = ""
            
            if gp_idx is not None and base_ltm_vals[gp_idx] is not None:
                num = base_ltm_vals[gp_idx]
                den = base_ltm_vals[rev_idx] if rev_idx is not None else None
                calc_formula = "Gross Profit / Revenue * 100"
            elif ebitda_idx is not None and base_ltm_vals[ebitda_idx] is not None:
                num = base_ltm_vals[ebitda_idx]
                den = base_ltm_vals[rev_idx] if rev_idx is not None else None
                calc_formula = "Adjusted EBITDA / Revenue * 100"
            
            if den in (None, 0):
                ltm_vals.append(None)
            else:
                try:
                    ltm_val = float(num) / float(den) * 100.0
                    ltm_vals.append(ltm_val)
                except Exception:
                    ltm_vals.append(None)
            # Get sources from underlying components
            ltm_margin_sources = []
            if gp_idx is not None and "Gross Profit" in hfa_log["metrics"] and "LTM 2025" in hfa_log["metrics"]["Gross Profit"]:
                gp_sources = hfa_log["metrics"]["Gross Profit"]["LTM 2025"]["sources"]
                ltm_margin_sources.extend([{k: v} for k, v in gp_sources.items()])
            elif ebitda_idx is not None and "Adjusted EBITDA" in hfa_log["metrics"] and "LTM 2025" in hfa_log["metrics"]["Adjusted EBITDA"]:
                ebitda_sources = hfa_log["metrics"]["Adjusted EBITDA"]["LTM 2025"]["sources"]
                ltm_margin_sources.extend([{k: v} for k, v in ebitda_sources.items()])
            if rev_idx is not None and "Revenue" in hfa_log["metrics"] and "LTM 2025" in hfa_log["metrics"]["Revenue"]:
                rev_sources = hfa_log["metrics"]["Revenue"]["LTM 2025"]["sources"]
                ltm_margin_sources.extend([{k: v} for k, v in rev_sources.items()])
            # Log LTM margin calculation
            log_metric_calculation(name, "LTM 2025", ltm_vals[idx] if idx < len(ltm_vals) else None, calc_formula, ltm_margin_sources)
            
        elif name == "EBITDA / Int. Exp.":
            ebitda_idx = find_row_index("Adjusted EBITDA", 0)
            int_idx = find_row_index("Interest Expense", 0)
            num = base_ltm_vals[ebitda_idx] if ebitda_idx is not None else None
            den = base_ltm_vals[int_idx] if int_idx is not None else None
            calc_formula = "Adjusted EBITDA / Interest Expense"
            # Get sources from component metrics
            ltm_sources = []
            if ebitda_idx is not None:
                ltm_sources.extend(get_sources_from_logged_metric("Adjusted EBITDA", "LTM 2025"))
            if int_idx is not None:
                ltm_sources.extend(get_sources_from_logged_metric("Interest Expense", "LTM 2025"))
            if den in (None, 0):
                ltm_vals.append(None)
            else:
                ltm_val = float(num if num is not None else 0.0) / float(den)
                ltm_vals.append(ltm_val)
            # Log LTM calculation
            log_metric_calculation(name, "LTM 2025", ltm_vals[-1], calc_formula, ltm_sources)
            
        elif name in ("Total Debt / EBITDA", "Total Debt + Leases / EBITDA"):
            debt_idx = find_row_index("Total Debt", 0)
            ebitda_idx = find_row_index("Adjusted EBITDA", 0)
            num = ytd2025_vals[debt_idx] if debt_idx is not None else None
            den = base_ltm_vals[ebitda_idx] if ebitda_idx is not None else None
            calc_formula = "Total Debt (YTD 2025) / Adjusted EBITDA (LTM)"
            # Get sources from component metrics
            ltm_sources = []
            if debt_idx is not None:
                ltm_sources.extend(get_sources_from_logged_metric("Total Debt", "YTD 2025"))
            if ebitda_idx is not None:
                ltm_sources.extend(get_sources_from_logged_metric("Adjusted EBITDA", "LTM 2025"))
            if den in (None, 0):
                ltm_vals.append(None)
            else:
                ltm_val = float(num if num is not None else 0.0) / float(den)
                ltm_vals.append(ltm_val)
            # Log LTM calculation
            log_metric_calculation(name, "LTM 2025", ltm_vals[-1], calc_formula, ltm_sources)
            
        elif name in ("Total Debt / Book Capital", "Total Debt + Leases / Book Capital"):
            debt_idx = find_row_index("Total Debt", 0)
            equity_idx = find_row_index("Book Equity", 0)
            notes_loc = ytd2025_vals[debt_idx] if debt_idx is not None else None
            equity = ytd2025_vals[equity_idx] if equity_idx is not None else None
            calc_formula = "Total Debt / (Total Debt + Book Equity) * 100"
            # Get sources from component metrics
            ltm_sources = []
            if debt_idx is not None:
                ltm_sources.extend(get_sources_from_logged_metric("Total Debt", "YTD 2025"))
            if equity_idx is not None:
                ltm_sources.extend(get_sources_from_logged_metric("Book Equity", "YTD 2025"))
            denom = None if notes_loc is None or equity is None else float(notes_loc) + float(equity)
            if denom in (None, 0):
                ltm_vals.append(None)
            else:
                ltm_val = float(notes_loc) / denom * 100.0
                ltm_vals.append(ltm_val)
            # Log LTM calculation
            log_metric_calculation(name, "LTM 2025", ltm_vals[-1], calc_formula, ltm_sources)
            
        elif name == "EBITDAR / Interest + Rent":
            ebitda_idx = find_row_index("Adjusted EBITDA", 0)
            int_idx = find_row_index("Interest Expense", 0)
            num = base_ltm_vals[ebitda_idx] if ebitda_idx is not None else None
            den = base_ltm_vals[int_idx] if int_idx is not None else None
            calc_formula = "Adjusted EBITDA / Interest Expense"
            # Get sources from component metrics
            ltm_sources = []
            if ebitda_idx is not None:
                ltm_sources.extend(get_sources_from_logged_metric("Adjusted EBITDA", "LTM 2025"))
            if int_idx is not None:
                ltm_sources.extend(get_sources_from_logged_metric("Interest Expense", "LTM 2025"))
            if den in (None, 0):
                ltm_vals.append(None)
            else:
                ltm_val = float(num if num is not None else 0.0) / float(den)
                ltm_vals.append(ltm_val)
            # Log LTM calculation
            log_metric_calculation(name, "LTM 2025", ltm_vals[-1], calc_formula, ltm_sources)
        else:
            ltm_vals.append(base_ltm_vals[idx])
    
    for i, r in enumerate(rows):
        r["YTD 2024"] = ytd2024_vals[i]
        r["YTD 2025"] = ytd2025_vals[i]
        r["LTM 2025"] = ltm_vals[i]
    
    csv_path = None
    json_path = None
    log_path = None
    blob_urls = {}
    
    # Handle local file writing
    if write_files:
        hfa_csv_dir = os.path.join(ROOT, "output", "csv", "HFA")
        hfa_json_dir = os.path.join(ROOT, "output", "json", "hfa_output")
        os.makedirs(hfa_csv_dir, exist_ok=True)
        os.makedirs(hfa_json_dir, exist_ok=True)
        
        csv_path = os.path.join(hfa_csv_dir, f"{ticker}_HFA.csv")
        json_path = os.path.join(hfa_json_dir, f"{ticker}_HFA.json")
        
        write_output(rows, csv_path)
        write_output_json(rows, json_path)
        
        # Save the HFA calculation log locally
        log_path = save_hfa_log(ticker, timestamp)
    
    # Handle Azure Blob Storage upload
    if upload_to_azure:
        try:
            from utils.azure_blob_storage import upload_json_to_blob_direct, upload_csv_to_blob_direct
            
            container_name = "hfa-outputs"
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Upload JSON directly
            json_blob_name = f"{ticker}/HFA_{ticker}_{timestamp_str}.json"
            json_url = upload_json_to_blob_direct(rows, container_name, json_blob_name)
            blob_urls["json_url"] = json_url
            
            # Upload CSV directly
            csv_blob_name = f"{ticker}/HFA_{ticker}_{timestamp_str}.csv"
            csv_url = upload_csv_to_blob_direct(rows, container_name, csv_blob_name)
            blob_urls["csv_url"] = csv_url
            
            # Upload log directly to separate 'logs' container
            log_container_name = "logs"
            log_blob_name = f"HFA/HFA_{ticker}_{timestamp_str}.json"
            log_url = upload_json_to_blob_direct(hfa_log, log_container_name, log_blob_name)
            blob_urls["log_url"] = log_url
            
            print(f"✅ HFA data uploaded to Azure Blob Storage: {blob_urls}")
        except Exception as e:
            print(f"Warning: Failed to upload HFA data to Azure Blob Storage: {e}")


    # Prepare API response rows: ensure "Taxes" shows "-" if all periods are null
    rows_for_api = copy.deepcopy(rows)
    try:
        for r in rows_for_api:
            if r.get("Metric") == "Taxes":
                period_keys = [k for k in r.keys() if k != "Metric"]
                if period_keys and all(r.get(k) is None for k in period_keys):
                    for k in period_keys:
                        r[k] = "-"
                break
    except Exception:
        # Non-fatal; keep original rows if normalization fails
        rows_for_api = rows
    return {
        "ticker": ticker, 
        "filing": filing, 
        "rows": rows_for_api, 
        "csv_path": csv_path, 
        "json_path": json_path, 
        "log_path": log_path,
        "blob_urls": blob_urls
    }

def main() -> None:
    parser = argparse.ArgumentParser(description="Build AQRR output table from financial statements.")
    parser.add_argument("--ticker", default="ELME", help="Ticker key to use for mapping and data directory (default: ELME)")
    parser.add_argument("--filing-type", default="10-K", choices=["10-K", "10-Q"], help="Filing type to use for mapping and data (default: 10-K)")
    args = parser.parse_args()
    result = build_hfa_outputs(args.ticker, args.filing_type, write_files=True)
    if result["csv_path"] and result["json_path"]:
        print(f"Wrote {result['csv_path']} and {result['json_path']} with {len(result['rows'])} rows for {result['ticker']} {result['filing']}")

if __name__ == "__main__":
    main()
