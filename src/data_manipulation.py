import os
import re
import json
import csv
from typing import Dict, Any, List, Set, Optional

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir, "output", "json", "raw_sec_api"))
PROCESSED_BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir, "output", "json", "llm_input_processed"))
CSV_BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir, "output", "csv"))

# --- Provided Functions ---
def write_csv_from_year_values(data: Dict[str, Dict[str, str]], output_file: str, target_keys: List[str]) -> None:
    """Writes a CSV from a structured dictionary, handling either years or full dates."""
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["key"] + target_keys
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for key, year_data in data.items():
            row = {"key": key}
            row.update(year_data)
            writer.writerow(row)

def write_json(data: Dict[str, Any], output_file: str) -> None:
    """Writes a dictionary to a JSON file."""
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# --- Updated Extraction Functions ---
def extract_10q_values(filepath: str) -> Dict[str, Dict[str, str]]:
    """
    Extracts financial data from a single 10-Q JSON file, preserving the full date
    in the output dictionary keys.
    """
    result = {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

    for key, value in data.items():
        result[key] = {}
        entries = []
        if isinstance(value, list):
            entries = [entry for entry in value if isinstance(entry, dict)]
        elif isinstance(value, dict):
            entries = [value]
        
        for entry in entries:
            # Added a check to ensure entry is a dictionary
            if not isinstance(entry, dict):
                continue
            period = entry.get("period", {})
            date = period.get("instant") or period.get("endDate")
            if date:
                # Use the full date as the key, e.g., "2024-03-31"
                result[key][date] = str(entry.get("value", ""))

    return {key: val for key, val in result.items() if val}


# --- Main Orchestration Logic ---
def process_all_filings(ticker: str) -> None:
    """
    Discovers, processes, and writes all 10-K and 10-Q filings for a given ticker.
    """
    ticker_upper = ticker.strip().upper()
    
    annual_re = re.compile(rf"^{re.escape(ticker_upper)}_10-K_(\d{{4}})_(\w+)\.json$")
    quarter_re = re.compile(rf"^{re.escape(ticker_upper)}_10-Q_(\d{{4}})_Q([1-4])_(\w+)\.json$")
    
    # Dictionaries to hold file paths grouped by filing type
    annual_files = {'balance': [], 'income': [], 'cashflow': []}
    quarter_files = {} # Key: (year, quarter), Value: {statement_type: filepath}
    
    if not os.path.isdir(RAW_DIR):
        print(f"Error: Raw data directory not found at {RAW_DIR}")
        return

    # Discover and group files
    for fname in os.listdir(RAW_DIR):
        fpath = os.path.join(RAW_DIR, fname)
        match_annual = annual_re.match(fname)
        if match_annual:
            year, stype = match_annual.groups()
            annual_files[stype].append(fpath)
            continue
        
        match_quarter = quarter_re.match(fname)
        if match_quarter:
            year, qnum, stype = match_quarter.groups()
            key = (int(year), f'Q{qnum}')
            if key not in quarter_files:
                quarter_files[key] = {}
            quarter_files[key][stype] = fpath
            continue

    if not annual_files and not quarter_files:
        print(f"No financial statement files found for ticker {ticker_upper} in {RAW_DIR}")
        return

    # --- Process 10-K Files (Combined) ---
    print("Processing 10-K files...")
    
    # Aggregate all 10-K files for all years (2020-2024)
    annual_filepaths = {}
    for stype in ['balance', 'income', 'cashflow']:
        annual_filepaths[stype] = []
        for year in range(2020, 2025):
            fname = f"{ticker_upper}_10-K_{year}_{stype}.json"
            fpath = os.path.join(RAW_DIR, fname)
            if os.path.exists(fpath):
                annual_filepaths[stype].append(fpath)

    # Process each statement type, combining data from all years
    combined_10k_data = {}
    target_years = sorted(list(range(2020, 2025)), reverse=True)
    for stype in ['balance', 'income', 'cashflow']:
        extracted = {}
        for fpath in annual_filepaths[stype]:
            # This is a bit of a manual workaround but necessary to read all
            # and merge data based on year.
            try:
                with open(fpath, 'r') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                continue
            for key, values in data.items():
                if key not in extracted:
                    extracted[key] = {str(y): "" for y in target_years}
                
                entries = values if isinstance(values, list) else [values]
                
                for entry in entries:
                    # Added a check to ensure entry is a dictionary
                    if not isinstance(entry, dict):
                        continue
                        
                    period = entry.get("period", {})
                    date = period.get("instant") or period.get("endDate")
                    if date and date[:4].isdigit():
                        year_str = date[:4]
                        if year_str in extracted[key] and not extracted[key][year_str]:
                            extracted[key][year_str] = str(entry.get("value", ""))
        
        combined_10k_data[stype] = {k: v for k, v in extracted.items() if any(v.values())}

    # Write the combined 10-K JSON and CSVs
    json_out_dir_10k = os.path.join(PROCESSED_BASE_DIR, ticker_upper)
    json_out_name_10k = f"{ticker_upper}_10-K_2020-2024_combined.json"
    json_out_path_10k = os.path.join(json_out_dir_10k, json_out_name_10k)
    write_json(combined_10k_data, json_out_path_10k)
    print(f"✅ Wrote combined 10-K data to {json_out_path_10k}")
    
    csv_out_dir_10k = os.path.join(CSV_BASE_DIR, ticker_upper, "10-K_2020-2024_combined")
    for name, data in combined_10k_data.items():
        if data:
            csv_out_path = os.path.join(csv_out_dir_10k, f"{name}.csv")
            write_csv_from_year_values(data, csv_out_path, [str(y) for y in target_years])
            print(f"✅ Wrote combined 10-K CSV for {name} to {csv_out_path}")


    # --- Process 10-Q Files (Separately with Full Dates) ---
    print("\nProcessing 10-Q files...")
    
    for (year, quarter), statements in sorted(quarter_files.items()):
        combined_10q_data = {}
        dates_in_filing = set()
        
        # Extract data for all three statements and collect unique dates
        for stype in ['balance', 'income', 'cashflow']:
            if stype in statements:
                extracted = extract_10q_values(statements[stype])
                combined_10q_data[stype] = extracted
                for key, date_values in extracted.items():
                    dates_in_filing.update(date_values.keys())
        
        if not combined_10q_data:
            continue
            
        # Write the combined 10-Q JSON and CSVs
        json_out_dir_10q = os.path.join(PROCESSED_BASE_DIR, ticker_upper)
        json_out_name_10q = f"{ticker_upper}_10-Q_{year}_{quarter}.json"
        json_out_path_10q = os.path.join(json_out_dir_10q, json_out_name_10q)
        write_json(combined_10q_data, json_out_path_10q)
        print(f"✅ Wrote 10-Q data to {json_out_path_10q}")
        
        sorted_dates = sorted(list(dates_in_filing), reverse=True)
        
        csv_out_dir_10q = os.path.join(CSV_BASE_DIR, ticker_upper, f"10-Q_{year}_{quarter}")
        for name, data in combined_10q_data.items():
            if data:
                csv_out_path = os.path.join(csv_out_dir_10q, f"{name}.csv")
                write_csv_from_year_values(data, csv_out_path, sorted_dates)
                print(f"✅ Wrote 10-Q CSV for {name} to {csv_out_path}")


# --- Main Execution ---
if __name__ == "__main__":
    try:
        target_ticker = input("Enter ticker symbol (e.g., ELME): ").strip()
        if not target_ticker:
            print("Error: Ticker cannot be empty.")
        else:
            process_all_filings(target_ticker)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")