import json
import os
import re
import requests
import urllib3
import warnings
from typing import Dict, Optional, Tuple
from dotenv import load_dotenv

# Suppress only the specific InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Resolve key directories
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FLOW_V2_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
PROJECT_ROOT = os.path.abspath(os.path.join(FLOW_V2_DIR, os.pardir))

# Load environment variables from a .env file if present in preferred locations
_dotenv_candidates = [
    os.path.join(FLOW_V2_DIR, ".env"),
    os.path.join(PROJECT_ROOT, ".env"),
]
for _env_path in _dotenv_candidates:
    if os.path.isfile(_env_path):
        load_dotenv(dotenv_path=_env_path)
        break
else:
    # Fallback: default search (CWD upwards)
    load_dotenv()

# Configure session for all requests
session = requests.Session()
session.headers.update({
    "User-Agent": "STRAIVE Demo straive.demo@example.com",
    "Accept": "application/json"
})

def get_sec_api_key() -> str:
    """Get SEC API key from environment variables.

    Raises a helpful error if the key is not set to avoid passing None to XbrlApi.
    """
    api_key = os.getenv('SEC_API_KEY')
    if not api_key:
        raise ValueError(
            "SEC_API_KEY is not set. Please set it in your environment or in a .env file. "
            "You can create a .env file with a line like: SEC_API_KEY=your_api_key_here"
        )
    return api_key

def detect_identifier_type(identifier: str) -> Tuple[str, bool]:
    """Detect if the identifier is a CIK or ticker
    
    Args:
        identifier (str): Input identifier
        
    Returns:
        Tuple[str, bool]: (processed_identifier, is_cik)
    """
    # Remove any spaces and convert to uppercase
    identifier = identifier.strip().upper()
    
    # Check if it's a CIK (all digits)
    if identifier.isdigit():
        return (identifier.zfill(10), True)
    
    # Check if it's a valid ticker (alphanumeric, 1-5 characters)
    if re.match(r'^[A-Z0-9]{1,5}$', identifier):
        return (identifier, False)
        
    raise ValueError("Invalid input: Must be either a CIK number or a valid ticker symbol (1-5 characters)")

def normalize_filing_type(filing_type: str) -> str:
    """Normalize user-provided filing type strings to SEC standard forms.

    Accepts variants like "10K", "10-K", "10k" etc. and returns "10-K".
    """
    f = (filing_type or "").strip().upper().replace(" ", "")
    if f in ("10K", "10-K"):  # Annual report
        return "10-K"
    if f in ("10Q", "10-Q"):  # Quarterly report
        return "10-Q"
    if f in ("8K", "8-K"):    # Current report
        return "8-K"
    return (filing_type or "").strip().upper()

def normalize_quarter(quarter: Optional[str]) -> Optional[str]:
    """Normalize quarter input to Q1/Q2/Q3/Q4 or return None if not provided.

    Accepts inputs like "Q1", "q1", "1", 1, etc. Returns "Q1".."Q4".
    Raises ValueError if provided but invalid.
    """
    if quarter is None or str(quarter).strip() == "":
        return None
    q = str(quarter).strip().upper().replace(" ", "")
    if q in {"Q1", "1"}:
        return "Q1"
    if q in {"Q2", "2"}:
        return "Q2"
    if q in {"Q3", "3"}:
        return "Q3"
    if q in {"Q4", "4"}:
        return "Q4"
    raise ValueError("Invalid quarter. Use Q1, Q2, Q3, Q4 or 1-4")

def get_filing_url(cik: str, filing_type: str = '10-K', year: Optional[int] = None, quarter: Optional[str] = None) -> Optional[Dict]:
    """Get the filing URL for a given CIK, filing type and optional year.
    
    Args:
        cik: Company CIK number
        filing_type: Type of filing (e.g., '10-K', '10-Q', '8-K')
        year: Optional specific year to fetch. If None, returns latest.
        
    Returns:
        Optional[str]: URL to the filing or None if not found
    """
    try:
        filing_type = normalize_filing_type(filing_type)
        quarter = normalize_quarter(quarter)
        # SEC EDGAR API endpoint for company filings
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        response = session.get(url, verify=False)
        response.raise_for_status()
        data = response.json()
        
        # Get filings data
        recent_filings = data.get('filings', {}).get('recent', {})
        if not recent_filings:
            return None
            
        form_types = recent_filings.get('form', [])
        accession_numbers = recent_filings.get('accessionNumber', [])
        filing_dates = recent_filings.get('filingDate', [])
        report_dates = recent_filings.get('reportDate', [])
        
        # Find matching filings
        matches = []
        for i, form_type in enumerate(form_types):
            if form_type == filing_type:
                filing_year = int(filing_dates[i][:4]) if i < len(filing_dates) and filing_dates[i] else None
                report_year = None
                qtr = None
                if i < len(report_dates) and report_dates[i]:
                    try:
                        report_year = int(report_dates[i][:4])
                        # Derive quarter from report date month
                        month = int(report_dates[i][5:7])
                        if month in (1,2,3):
                            qtr = "Q1"
                        elif month in (4,5,6):
                            qtr = "Q2"
                        elif month in (7,8,9):
                            qtr = "Q3"
                        elif month in (10,11,12):
                            qtr = "Q4"
                    except Exception:
                        report_year = None
                        qtr = None
                matches.append({
                    'filing_year': filing_year,
                    'report_year': report_year,
                    'quarter': qtr,
                    'date': filing_dates[i] if i < len(filing_dates) else '',
                    'accession': accession_numbers[i].replace('-', '')
                })
        
        if not matches:
            return None
            
        # Sort by filing date descending
        matches.sort(key=lambda x: x['date'], reverse=True)

        # Filter by year if specified
        if year:
            # Prefer matching on report_year (fiscal year). Fallback to filing_year.
            filtered = [m for m in matches if m['report_year'] == year]
            if not filtered:
                filtered = [m for m in matches if m['filing_year'] == year]
            matches = filtered
            if not matches:
                return None
        
        # Filter by quarter if specified and filing_type is 10-Q
        if filing_type == "10-Q" and quarter:
            matches = [m for m in matches if m.get('quarter') == quarter]
            if not matches:
                return None
        
        # Return URL for the most recent matching filing
        selected = matches[0]
        return {
            'url': f"https://www.sec.gov/Archives/edgar/data/{cik}/{selected['accession']}/",
            'report_year': selected.get('report_year'),
            'quarter': selected.get('quarter'),
        }
                
        return None
    except Exception as e:
        print(f"Error fetching filing URL: {str(e)}")
        return None

def get_cik_from_ticker(ticker: str) -> str:
    """Get CIK number from ticker using SEC API"""
    try:
        url = "https://www.sec.gov/files/company_tickers.json"
        response = session.get(url, verify=False)
        response.raise_for_status()
        
        # Parse the JSON response
        companies = response.json()
        for _, company in companies.items():
            if company['ticker'].upper() == ticker.upper():
                return str(company['cik_str']).zfill(10)
        
        raise ValueError(f"Ticker {ticker} not found in SEC database")
    except requests.exceptions.RequestException as e:
        raise ValueError(f"Error accessing SEC API: {str(e)}")
    except Exception as e:
        raise ValueError(f"Error looking up ticker {ticker}: {str(e)}")

def xbrl_to_json_via_sec_api(htm_url: str) -> Dict:
    """Call SEC-API xbrl-to-json endpoint using requests with SSL verification disabled.

    This avoids SSL certificate errors in environments with SSL inspection.
    """
    api_key = get_sec_api_key()
    try:
        url = "https://api.sec-api.io/xbrl-to-json"
        params = {"token": api_key, "htm-url": htm_url}
        resp = session.get(url, params=params, verify=False, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        raise ValueError(f"Error calling SEC-API xbrl-to-json: {str(e)}")

def _output_dir() -> str:
    return os.path.join(FLOW_V2_DIR, "output", "json", "raw_sec_api")

def _build_base_name(identifier: str, is_cik: bool) -> str:
    return f"cik_{identifier}" if is_cik else f"{identifier.upper()}"

def _load_json_if_valid(path: str):
    try:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Consider it valid if it's truthy (non-empty)
        if data:
            return data
    except Exception:
        return None
    return None

def load_cached_statements(identifier: str, is_cik: bool, filing_type: str, year: Optional[int], quarter: Optional[str]):
    """Try to load previously saved statements from disk.

    Returns a dict with keys income_statement, balance_sheet, cash_flow if all exist and are valid.
    Otherwise returns None.
    """
    filing_type = normalize_filing_type(filing_type)
    quarter = normalize_quarter(quarter)
    year_str = str(year) if year is not None else "latest"
    base_name = _build_base_name(identifier, is_cik)
    out_dir = _output_dir()
    if not os.path.isdir(out_dir):
        return None

    # For 10-Q there may be a quarter suffix (_Q1.._Q4). If quarter specified, require exact quarter; else allow either.
    def find_file(statement_key: str) -> Optional[str]:
        # statement_key in {"income", "balance", "cashflow"}
        # If a quarter is specified for 10-Q, only accept quarter-specific filenames.
        if filing_type == "10-Q" and quarter:
            pattern = re.compile(rf"^{re.escape(base_name)}_{re.escape(filing_type)}_{re.escape(year_str)}_{re.escape(quarter)}_{re.escape(statement_key)}\.json$")
            for fname in os.listdir(out_dir):
                if pattern.match(fname):
                    return os.path.join(out_dir, fname)
            return None
        
        # Otherwise, prefer exact non-quarter filename, then any quarter-specific.
        exact = f"{base_name}_{filing_type}_{year_str}_{statement_key}.json"
        exact_path = os.path.join(out_dir, exact)
        if os.path.isfile(exact_path):
            return exact_path
        pattern = re.compile(rf"^{re.escape(base_name)}_{re.escape(filing_type)}_{re.escape(year_str)}_Q[1-4]_{re.escape(statement_key)}\.json$")
        for fname in os.listdir(out_dir):
            if pattern.match(fname):
                return os.path.join(out_dir, fname)
        return None

    paths = {
        "income_statement": find_file("income"),
        "balance_sheet": find_file("balance"),
        "cash_flow": find_file("cashflow"),
    }
    if not all(paths.values()):
        return None

    loaded = {k: _load_json_if_valid(p) for k, p in paths.items()}
    if any(v is None for v in loaded.values()):
        return None

    return loaded

def get_financial_statements(identifier: str, is_cik: bool = False, filing_type: str = '10-K', year: Optional[int] = None, quarter: Optional[str] = None) -> Dict:
    """
    Retrieve financial statements for a given ticker or CIK.
    
    Args:
        identifier (str): Company ticker or CIK number
        is_cik (bool): True if identifier is CIK, False if ticker
        filing_type (str): Type of filing to fetch (e.g., '10-K', '10-Q')
        year (Optional[int]): Specific year to fetch, or None for latest
    
    Returns:
        Dict: Dictionary containing the three financial statements and metadata
    """
    try:
        filing_type = normalize_filing_type(filing_type)
        quarter = normalize_quarter(quarter)
        # Process CIK
        if is_cik:
            cik = identifier.zfill(10)
            processed_identifier = cik
        else:
            cik = get_cik_from_ticker(identifier)
            processed_identifier = identifier

        # 1) Try cache first
        cached = load_cached_statements(processed_identifier, is_cik, filing_type, year, quarter)
        if cached:
            return {
                "metadata": {
                    "cik": cik,
                    "filing_type": filing_type,
                    "year": year,
                    "filing_url": None,
                    "quarter": quarter,
                    "from_cache": True,
                },
                "statements": cached,
            }

        # 2) No cache -> find filing URL and call SEC-API
        base_info = get_filing_url(cik, filing_type=filing_type, year=year, quarter=quarter)
        if not base_info:
            raise ValueError(
                f"No {filing_type} filing found for {identifier}" + (f" in year {year}" if year else "")
            )

        base_url = base_info['url']
        # If quarter was not provided, but we derived one, carry it forward in metadata
        if not quarter:
            quarter = base_info.get('quarter')

        xbrl_json = xbrl_to_json_via_sec_api(htm_url=f"{base_url}index.htm")

        return {
            "metadata": {
                "cik": cik,
                "filing_type": filing_type,
                "year": year,
                "filing_url": base_url,
                "quarter": quarter,
                "from_cache": False,
            },
            "statements": {
                "income_statement": xbrl_json.get("StatementsOfIncome"),
                "balance_sheet": xbrl_json.get("BalanceSheets"),
                "cash_flow": xbrl_json.get("StatementsOfCashFlows"),
            },
        }

    except Exception as e:
        return {"error": str(e)}

# ----------- MODIFIED FUNCTION STARTS HERE -----------
def save_statements_to_files(statements: Dict, meta: Dict, identifier: str, is_cik: bool) -> None:
    """Save statements dict to separate JSON files under the local output directory.

    Filenames:
    ticker_{filetype}_{year}_{quarter}_{statementtype}.json
    or
    cik_{filetype}_{year}_{quarter}_{statementtype}.json

    Files written to: flow_v2/output/json/raw_sec_api/
    """
    try:
        output_dir = _output_dir()
        os.makedirs(output_dir, exist_ok=True)

        # Determine base name: ticker or cik
        base_name = _build_base_name(meta['cik'] if is_cik else identifier, is_cik)

        # Filing type and year
        filing_type = normalize_filing_type(meta.get("filing_type", "10-K"))
        year = meta.get("year") or "latest"

        # Determine quarter for 10-Q filings: prefer provided meta quarter, else try to infer
        quarter = ""
        if filing_type.upper() == "10-Q":
            q_meta = meta.get("quarter")
            if q_meta:
                quarter = normalize_quarter(q_meta) or ""
            if not quarter:
                # Try to extract from URL paths (best-effort)
                filing_url = meta.get("filing_url", "")
                match = re.search(r'/(\d{4})-(\d{2})-(\d{2})/', filing_url)
                if match:
                    month = int(match.group(2))
                    if month in [1,2,3]:
                        quarter = "Q1"
                    elif month in [4,5,6]:
                        quarter = "Q2"
                    elif month in [7,8,9]:
                        quarter = "Q3"
                    elif month in [10,11,12]:
                        quarter = "Q4"

        # Statement types and their keys
        statement_map = {
            "income": "income_statement",
            "balance": "balance_sheet",
            "cashflow": "cash_flow"
        }

        for statement_type, key in statement_map.items():
            filename = f"{base_name}_{filing_type}_{year}"
            if quarter:
                filename += f"_{quarter}"
            filename += f"_{statement_type}.json"
            path = os.path.join(output_dir, filename)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(statements.get(key), f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: failed to write output files: {e}")
# ----------- MODIFIED FUNCTION ENDS HERE -----------

def main():
    try:
        # Get user input
        identifier = input("Enter company ticker or CIK number: ").strip()
        filing_type = input("Enter filing type (10-K, 10-Q, 8-K) [default: 10-K]: ").strip() or '10-K'
        year_input = input("Enter year (YYYY) or press Enter for latest: ").strip()
        year = int(year_input) if year_input else None
        # Quarter prompt for 10-Q (required)
        quarter = None
        if normalize_filing_type(filing_type) == "10-Q":
            while True:
                q_input = input("Enter quarter (Q1/Q2/Q3/Q4 or 1-4): ").strip()
                try:
                    quarter = normalize_quarter(q_input)
                    if quarter:
                        break
                except Exception as _:
                    pass
                print("Invalid quarter. Please enter Q1, Q2, Q3, Q4 or 1-4.")
        
        # Auto-detect if it's a CIK or ticker
        processed_identifier, is_cik = detect_identifier_type(identifier)
        msg = f"\nFetching {filing_type}"
        if year:
            msg += f" from {year}"
        if normalize_filing_type(filing_type) == "10-Q" and (quarter and quarter.strip()):
            msg += f" ({quarter.strip().upper()})"
        msg += f" for {'CIK' if is_cik else 'Ticker'}: {processed_identifier}"
        print(msg)
        
        # Get financial statements
        result = get_financial_statements(
            identifier=processed_identifier,
            is_cik=is_cik,
            filing_type=filing_type,
            year=year,
            quarter=quarter
        )
        
        # Print results
        if "error" in result:
            print(f"\nError: {result['error']}")
        else:
            # Print metadata
            meta = result['metadata']
            print(f"\nFiling Details:")
            print(f"CIK: {meta['cik']}")
            print(f"Type: {meta['filing_type']}")
            print(f"Year: {meta['year'] or 'Latest'}")
            if meta.get('quarter'):
                print(f"Quarter: {meta['quarter']}")
            print(f"URL: {meta['filing_url'] or 'Loaded from cache'}")
            print(f"Source: {'cache' if meta.get('from_cache') else 'fresh API'}")
            
            # Save only if fetched freshly (not from cache)
            if not meta.get('from_cache'):
                save_statements_to_files(result['statements'], meta, processed_identifier, is_cik)
                print(f"\nStatements saved to flow_v2/output/json/raw_sec_api/")
            else:
                print("\nUsing cached files; no API call made and no files overwritten.")
            
            # Print preview
            print("\nIncome Statement:")
            print(json.dumps(result['statements']['income_statement'], indent=2)[:500] + '...')
            print("\nBalance Sheet:")
            print(json.dumps(result['statements']['balance_sheet'], indent=2)[:500] + '...')
            print("\nCash Flow Statement:")
            print(json.dumps(result['statements']['cash_flow'], indent=2)[:500] + '...')
            
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {str(e)}")

if __name__ == "__main__":
    main()