import csv
import json
import os
from typing import Dict, List, Optional, Any
import argparse

try:
    import yaml  # pyyaml is in requirements.txt
except Exception:
    yaml = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA_PATH = os.path.join(ROOT, "static", "aqrr_key_schema.yaml")
MAPPING_PATH = os.path.join(ROOT, "utils", "mapping_calculation.json")

YEARS = [2024, 2023, 2022, 2021, 2020]

Number = Optional[float]


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


class DataStore:
    def __init__(self, income: Dict[str, Dict[int, Number]], balance: Dict[str, Dict[int, Number]], cashflow: Dict[str, Dict[int, Number]]):
        self.sources = [income, balance, cashflow]

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


def safe_eval_expr(expr: str, year: int, store: DataStore) -> Number:
    # Build variables dict for all candidate tokens (A-Za-z0-9_ only)
    import re
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr))
    local_vars: Dict[str, float] = {}
    for t in tokens:
        v = store.get(t, year)
        # Treat missing values as 0 for additive formulas; ratios will handle None/zero later
        local_vars[t] = 0.0 if v is None else float(v)
    # Evaluate arithmetic expression only
    try:
        return float(eval(expr, {"__builtins__": {}}, local_vars))
    except ZeroDivisionError:
        return None
    except Exception:
        return None


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


def safe_eval_expr_q(expr: str, default_date: str, store_q: DataStoreQ, computed: Dict[str, Number]) -> Number:
    # Support tokens like Name[YYYY-MM-DD]; tokens without date try computed AQRR first, else FS at default_date
    import re
    # Replace bracketed tokens with unique variable names
    pattern = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\[(\d{4}-\d{2}-\d{2})\]")
    subs: Dict[str, float] = {}

    def repl(m):
        name, date = m.group(1), m.group(2)
        var = f"__{name}_{date}__"
        val = store_q.get(name, date)
        subs[var] = 0.0 if val is None else float(val)
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
            v = store_q.get(t, default_date)
            local_vars[t] = 0.0 if v is None else float(v)
    try:
        return float(eval(expr2, {"__builtins__": {}}, local_vars))
    except ZeroDivisionError:
        return None
    except Exception:
        return None


def compute_period_rows_q(mapping_items: List[Dict[str, Any]], store_q: DataStoreQ, default_date: str) -> List[Dict[str, Any]]:
    computed: Dict[str, Number] = {}
    rows: List[Dict[str, Any]] = []
    for item in mapping_items:
        aqrr_key = item.get("aqrr_key")
        calc = item.get("calculation", "")
        dep_aqrr = item.get("aqrr_keys", []) or []

        # Special cases align with 10-K logic
        val: Number = None
        if aqrr_key == "% Margin" and len(dep_aqrr) == 2:
            num = computed.get(dep_aqrr[0])
            den = computed.get(dep_aqrr[1])
            if den in (None, 0):
                val = None
            else:
                try:
                    val = float(num) / float(den) * 100.0
                except Exception:
                    val = None
        elif aqrr_key == "EBITDA / Int. Exp.":
            ebitda = computed.get("Adjusted EBITDA")
            interest = store_q.get("InterestExpenseNonoperating", default_date)
            if interest in (None, 0):
                val = None
            else:
                try:
                    val = float(ebitda if ebitda is not None else 0.0) / float(interest)
                except Exception:
                    val = None
        elif aqrr_key in ("Total Debt / EBITDA", "Total Debt + Leases / EBITDA"):
            # Use stock total debt at period end, EBITDA from computed
            total_debt = store_q.get("NotesPayable", default_date) or 0.0
            total_debt += store_q.get("LineOfCredit", default_date) or 0.0
            ebitda = computed.get("Adjusted EBITDA")
            if ebitda in (None, 0):
                val = None
            else:
                try:
                    val = float(total_debt) / float(ebitda)
                except Exception:
                    val = None
        elif aqrr_key in ("Total Debt / Book Capital", "Total Debt + Leases / Book Capital"):
            notes = store_q.get("NotesPayable", default_date) or 0.0
            loc = store_q.get("LineOfCredit", default_date) or 0.0
            equity = store_q.get("StockholdersEquity", default_date)
            denom = (notes + loc + (0.0 if equity is None else float(equity)))
            if denom in (None, 0):
                val = None
            else:
                val = (notes + loc) / denom * 100.0
        else:
            if "Not available" in calc:
                val = None
            elif calc:
                val = safe_eval_expr_q(calc, default_date, store_q, computed)
            else:
                val = None

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

    output_rows: List[Dict[str, Any]] = []

    for item in ordered_items:
        aqrr_key = item.get("aqrr_key")
        calc = item.get("calculation", "")
        dep_aqrr = item.get("aqrr_keys", []) or []
        fin_keys = item.get("financial_statement_keys", []) or []

        row: Dict[str, Any] = {"Metric": aqrr_key}

        for year in YEARS:
            val: Number = None

            # Special handling for % YoY Growth (compute from Revenue YoY)
            if aqrr_key == "% YoY Growth":
                # Requires Revenue of this and previous year
                prev_year = year - 1
                if prev_year in YEARS:
                    rev_curr = computed.get("Revenue", {}).get(year)
                    rev_prev = computed.get("Revenue", {}).get(prev_year)
                    if rev_curr is None:
                        rev_curr = store.get("Revenues", year)
                    if rev_prev is None:
                        rev_prev = store.get("Revenues", prev_year)
                    if rev_prev in (None, 0):
                        val = None
                    else:
                        try:
                            val = (float(rev_curr) - float(rev_prev)) / float(rev_prev) * 100.0
                        except Exception:
                            val = None
                else:
                    val = None

            # Margin rows: if depends on two AQRR keys, compute ratio * 100
            elif aqrr_key == "% Margin" and len(dep_aqrr) == 2:
                num_key, den_key = dep_aqrr[0], dep_aqrr[1]
                num = computed.get(num_key, {}).get(year)
                den = computed.get(den_key, {}).get(year)
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
                interest = store.get("InterestExpenseNonoperating", year)
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
                if ebitda in (None, 0):
                    val = None
                else:
                    try:
                        val = float(total_debt if total_debt is not None else 0.0) / float(ebitda)
                    except Exception:
                        val = None

            elif aqrr_key == "Total Debt / Book Capital":
                notes = store.get("NotesPayable", year) or 0.0
                loc = store.get("LineOfCredit", year) or 0.0
                equity = store.get("StockholdersEquity", year)
                denom = (notes + loc + (0.0 if equity is None else float(equity)))
                if denom in (None, 0):
                    val = None
                else:
                    try:
                        val = (notes + loc) / denom * 100.0  # express as % to match schema examples
                    except Exception:
                        val = None

            elif aqrr_key == "Total Debt + Leases / Book Capital":
                notes = store.get("NotesPayable", year) or 0.0
                loc = store.get("LineOfCredit", year) or 0.0
                equity = store.get("StockholdersEquity", year)
                denom = (notes + loc + (0.0 if equity is None else float(equity)))
                if denom in (None, 0):
                    val = None
                else:
                    try:
                        val = (notes + loc) / denom * 100.0
                    except Exception:
                        val = None

            # Generic expression evaluation using financial statement keys
            else:
                if "Not available" in calc:
                    val = None
                elif calc:
                    # Normalize expression: no year-specific tokens here for 10-K except YoY which we handled
                    expr = calc
                    val = safe_eval_expr(expr, year, store)
                else:
                    # If no calculation provided but there is a single financial key, pass-through
                    if fin_keys:
                        v = store.get(fin_keys[0], year)
                        val = None if v is None else float(v)
                    else:
                        val = None

            row[str(year)] = val

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


def build_hfa_outputs(ticker: str, filing: str, write_files: bool = True) -> Dict[str, Any]:
    """Compute HFA table for ticker/filing, append YTD and LTM, and optionally write CSV/JSON.
    Returns a dict: {"ticker", "filing", "rows", "csv_path", "json_path"}.
    """
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
        else:
            a = fy2024_vals[idx]
            b = ytd2025_vals[idx]
            c = ytd2024_vals[idx]
            try:
                if a is None or b is None or c is None:
                    base_ltm_vals.append(None)
                else:
                    base_ltm_vals.append(float(a) + float(b) - float(c))
            except Exception:
                base_ltm_vals.append(None)

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
            if gp_idx is not None and base_ltm_vals[gp_idx] is not None:
                num = base_ltm_vals[gp_idx]
                den = base_ltm_vals[rev_idx] if rev_idx is not None else None
            elif ebitda_idx is not None and base_ltm_vals[ebitda_idx] is not None:
                num = base_ltm_vals[ebitda_idx]
                den = base_ltm_vals[rev_idx] if rev_idx is not None else None
            if den in (None, 0):
                ltm_vals.append(None)
            else:
                try:
                    ltm_vals.append(float(num) / float(den) * 100.0)
                except Exception:
                    ltm_vals.append(None)
        elif name == "EBITDA / Int. Exp.":
            ebitda_idx = find_row_index("Adjusted EBITDA", 0)
            int_idx = find_row_index("Interest Expense", 0)
            num = base_ltm_vals[ebitda_idx] if ebitda_idx is not None else None
            den = base_ltm_vals[int_idx] if int_idx is not None else None
            if den in (None, 0):
                ltm_vals.append(None)
            else:
                ltm_vals.append(float(num if num is not None else 0.0) / float(den))
        elif name in ("Total Debt / EBITDA", "Total Debt + Leases / EBITDA"):
            debt_idx = find_row_index("Total Debt", 0)
            ebitda_idx = find_row_index("Adjusted EBITDA", 0)
            num = ytd2025_vals[debt_idx] if debt_idx is not None else None
            den = base_ltm_vals[ebitda_idx] if ebitda_idx is not None else None
            if den in (None, 0):
                ltm_vals.append(None)
            else:
                ltm_vals.append(float(num if num is not None else 0.0) / float(den))
        elif name in ("Total Debt / Book Capital", "Total Debt + Leases / Book Capital"):
            debt_idx = find_row_index("Total Debt", 0)
            equity_idx = find_row_index("Book Equity", 0)
            notes_loc = ytd2025_vals[debt_idx] if debt_idx is not None else None
            equity = ytd2025_vals[equity_idx] if equity_idx is not None else None
            denom = None if notes_loc is None or equity is None else float(notes_loc) + float(equity)
            if denom in (None, 0):
                ltm_vals.append(None)
            else:
                ltm_vals.append(float(notes_loc) / denom * 100.0)
        elif name == "EBITDAR / Interest + Rent":
            ebitda_idx = find_row_index("Adjusted EBITDA", 0)
            int_idx = find_row_index("Interest Expense", 0)
            num = base_ltm_vals[ebitda_idx] if ebitda_idx is not None else None
            den = base_ltm_vals[int_idx] if int_idx is not None else None
            if den in (None, 0):
                ltm_vals.append(None)
            else:
                ltm_vals.append(float(num if num is not None else 0.0) / float(den))
        else:
            ltm_vals.append(base_ltm_vals[idx])

    for i, r in enumerate(rows):
        r["YTD 2024"] = ytd2024_vals[i]
        r["YTD 2025"] = ytd2025_vals[i]
        r["LTM 2025"] = ltm_vals[i]

    csv_path = None
    json_path = None
    if write_files:
        hfa_csv_dir = os.path.join(ROOT, "output", "csv", "HFA")
        hfa_json_dir = os.path.join(ROOT, "output", "json", "hfa_output")
        os.makedirs(hfa_csv_dir, exist_ok=True)
        os.makedirs(hfa_json_dir, exist_ok=True)
        csv_path = os.path.join(hfa_csv_dir, f"{ticker}_HFA.csv")
        json_path = os.path.join(hfa_json_dir, f"{ticker}_HFA.json")
        write_output(rows, csv_path)
        write_output_json(rows, json_path)

    return {"ticker": ticker, "filing": filing, "rows": rows, "csv_path": csv_path, "json_path": json_path}


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
