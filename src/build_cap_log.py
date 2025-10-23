import json
import csv
import os
from decimal import Decimal
import fitz  # PyMuPDF
from typing import Dict, Any, Tuple, Optional, List
import requests
from dotenv import load_dotenv
from openai import OpenAI
import yaml
import io
import tempfile
from datetime import datetime
from sec_api import QueryApi, RenderApi, PdfGeneratorApi
import time
import re

# Root directory path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTING_MODE = True

def configure_requests_for_corporate_environment():
    """Configure requests to work in corporate environments with SSL inspection"""
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # Monkey patch the requests library to disable SSL verification
    old_merge_environment_settings = requests.Session.merge_environment_settings
    
    def new_merge_environment_settings(self, url, proxies, stream, verify, cert):
        settings = old_merge_environment_settings(self, url, proxies, stream, verify, cert)
        settings['verify'] = False
        return settings
    
    requests.Session.merge_environment_settings = new_merge_environment_settings

# Call this function at the beginning of your main code
configure_requests_for_corporate_environment()

def ensure_directories_exist():
    """Ensure all required directories exist in the local filesystem"""
    directories = [
        os.path.join(ROOT, "data"),
        os.path.join(ROOT, "output", "json", "cap_table"),
        os.path.join(ROOT, "output", "csv", "cap_table"),
    ]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)

def get_sec_api_key():
    """Get SEC API key from environment variables"""
    load_dotenv()
    sec_api_key = os.getenv("SEC_API_KEY")
    if not sec_api_key:
        raise ValueError("SEC_API_KEY must be set in the .env file")
    return sec_api_key

def get_latest_filings(ticker, filing_types=["10-K", "10-Q"]):
    """Get the latest 10-K and 10-Q filings for a ticker using SEC API"""
    sec_api_key = get_sec_api_key()
    query_api = QueryApi(api_key=sec_api_key)
    pdf_generator_api = PdfGeneratorApi(api_key=sec_api_key)
    
    # Instead of trying to access session directly, modify the underlying requests module
    # which is used by all HTTP clients including SEC API
    import requests
    requests.packages.urllib3.disable_warnings()
    old_get = requests.get
    def new_get(*args, **kwargs):
        kwargs['verify'] = False
        return old_get(*args, **kwargs)
    requests.get = new_get
    
    results = {}
    
    for filing_type in filing_types:
        query = {
            "query": {
                "query_string": {
                    "query": f"ticker:{ticker} AND formType:\"{filing_type}\" AND NOT formType:\"{filing_type}/A\""
                }
            },
            "from": "0",
            "size": "1",
            "sort": [{"filedAt": {"order": "desc"}}]
        }
        
        response = query_api.get_filings(query)
        
        if response['total']['value'] > 0:
            filing = response['filings'][0]
            filing_url = filing['linkToFilingDetails']
            filing_date = filing['filedAt']
            
            # Generate PDF from the filing URL
            try:
                pdf_content = pdf_generator_api.get_pdf(filing_url)
                results[filing_type] = {
                    'url': filing_url,
                    'date': filing_date,
                    'content': pdf_content
                }
                print(f"Retrieved latest {filing_type} for {ticker}, filed on {filing_date}")
                
                # Add a small delay to avoid rate limiting
                time.sleep(1)
            except Exception as e:
                print(f"Error generating PDF for {filing_type}: {e}")
                # Continue processing other filing types even if one fails
                continue
        else:
            print(f"No {filing_type} filings found for {ticker}")
    
    return results

# Replace check_filing_freshness function to work with local files
def check_filing_freshness(file_path, max_age_days=90):
    """Check if a filing in local filesystem is recent enough"""
    try:
        # Get file modification time
        file_path = os.path.join(ROOT, file_path)
        if not os.path.exists(file_path):
            return False
            
        mod_time = os.path.getmtime(file_path)
        mod_date = datetime.fromtimestamp(mod_time)
        
        # Calculate age in days
        age_days = (datetime.now() - mod_date).days
        
        return age_days <= max_age_days
    except Exception as e:
        # If there's an error, return False
        print(f"Error checking filing freshness for {file_path}: {e}")
        return False

# Replace save_filing_to_blob function to save to local filesystem
def save_filing_to_local(pdf_content, file_path):
    """Save a filing PDF to local filesystem"""
    try:
        # Ensure directory exists
        full_dir_path = os.path.dirname(os.path.join(ROOT, file_path))
        os.makedirs(full_dir_path, exist_ok=True)
        
        # Check if pdf_content is valid
        if not pdf_content:
            print(f"Error: No PDF content to save for {file_path}")
            return False
        
        # Write the PDF content to file
        full_file_path = os.path.join(ROOT, file_path)
        with open(full_file_path, 'wb') as f:
            f.write(pdf_content)
        
        # Verify file was created and has content
        if os.path.exists(full_file_path) and os.path.getsize(full_file_path) > 0:
            print(f"Saved filing to {file_path} ({os.path.getsize(full_file_path)} bytes)")
            return True
        else:
            print(f"Error: File {file_path} was not created properly")
            return False
            
    except Exception as e:
        print(f"Error saving filing to {file_path}: {e}")
        return False

# Replace get_filings_for_ticker function to work with local files and implement caching
def get_filings_for_ticker(ticker):
    """Get the latest filings for a ticker, either from local filesystem or SEC API"""
    data_folder = f"data/{ticker}"
    full_data_folder = os.path.join(ROOT, data_folder)
    
    # Create the data folder if it doesn't exist
    os.makedirs(full_data_folder, exist_ok=True)
    
    # Check for existing local files
    k_files = []
    q_files = []
    if os.path.exists(full_data_folder):
        for file in os.listdir(full_data_folder):
            file_path = os.path.join(data_folder, file)
            if ("10-K" in file.upper() or "10K" in file.upper()) and file.endswith(".pdf"):
                k_files.append(file_path)
            elif ("10-Q" in file.upper() or "10Q" in file.upper()) and file.endswith(".pdf"):
                q_files.append(file_path)
    
    # If in testing mode, check local files first, download if missing
    if TESTING_MODE:
        print(f"TESTING MODE: Checking for local files for {ticker}")
        k_file_path = k_files[0] if k_files else None
        q_file_path = q_files[0] if q_files else None
        
        # Download missing files if not found locally
        if not k_file_path or not q_file_path:
            missing_types = []
            if not k_file_path:
                missing_types.append("10-K")
            if not q_file_path:
                missing_types.append("10-Q")
            
            print(f"Missing local files: {missing_types}. Downloading from SEC API...")
            
            try:
                latest_filings = get_latest_filings(ticker, missing_types)
                
                # Save 10-K if needed
                if "10-K" in latest_filings and not k_file_path:
                    k_file_path = f"{data_folder}/10-K_{datetime.now().strftime('%Y%m%d')}.pdf"
                    if save_filing_to_local(latest_filings["10-K"]["content"], k_file_path):
                        print(f"Downloaded and saved 10-K: {k_file_path}")
                    else:
                        print(f"Failed to save 10-K for {ticker}")
                        return None, None
                
                # Save 10-Q if needed
                if "10-Q" in latest_filings and not q_file_path:
                    q_file_path = f"{data_folder}/10-Q_{datetime.now().strftime('%Y%m%d')}.pdf"
                    if save_filing_to_local(latest_filings["10-Q"]["content"], q_file_path):
                        print(f"Downloaded and saved 10-Q: {q_file_path}")
                    else:
                        print(f"Warning: Failed to save 10-Q for {ticker}, continuing with 10-K only")
                
            except Exception as e:
                print(f"Error downloading filings from SEC API: {e}")
                if not k_file_path:
                    print(f"Cannot proceed without 10-K filing for {ticker}")
                    return None, None
        
        print(f"Using local 10-K: {k_file_path}")
        if q_file_path:
            print(f"Using local 10-Q: {q_file_path}")
        else:
            print(f"No 10-Q available for {ticker}")
        
        return k_file_path, q_file_path
    
    k_file_path = None
    q_file_path = None
    
    # First, check with SEC API to get the latest filing dates
    sec_api_key = get_sec_api_key()
    query_api = QueryApi(api_key=sec_api_key)
    
    # Disable SSL verification for requests
    import requests
    requests.packages.urllib3.disable_warnings()
    old_get = requests.get
    def new_get(*args, **kwargs):
        kwargs['verify'] = False
        return old_get(*args, **kwargs)
    requests.get = new_get
    
    latest_k_date = None
    latest_q_date = None
    
    # Get latest 10-K filing date
    k_query = {
        "query": {
            "query_string": {
                "query": f"ticker:{ticker} AND formType:\"10-K\" AND NOT formType:\"10-K/A\""
            }
        },
        "from": "0",
        "size": "1",
        "sort": [{"filedAt": {"order": "desc"}}]
    }
    
    try:
        k_response = query_api.get_filings(k_query)
        if k_response['total']['value'] > 0:
            latest_k_date = datetime.fromisoformat(k_response['filings'][0]['filedAt'].replace('Z', '+00:00'))
            print(f"Latest 10-K for {ticker} was filed on {latest_k_date}")
    except Exception as e:
        print(f"Error checking latest 10-K date: {e}")
    
    # Get latest 10-Q filing date
    q_query = {
        "query": {
            "query_string": {
                "query": f"ticker:{ticker} AND formType:\"10-Q\" AND NOT formType:\"10-Q/A\""
            }
        },
        "from": "0",
        "size": "1",
        "sort": [{"filedAt": {"order": "desc"}}]
    }
    
    try:
        q_response = query_api.get_filings(q_query)
        if q_response['total']['value'] > 0:
            latest_q_date = datetime.fromisoformat(q_response['filings'][0]['filedAt'].replace('Z', '+00:00'))
            print(f"Latest 10-Q for {ticker} was filed on {latest_q_date}")
    except Exception as e:
        print(f"Error checking latest 10-Q date: {e}")
    
    # Flag to track if we need to remove outdated files
    outdated_files_exist = False
    
    # Check if we have the latest 10-K locally
    if k_files and latest_k_date:
        found_latest_k = False
        for k_file in sorted(k_files, key=lambda x: os.path.getmtime(os.path.join(ROOT, x)), reverse=True):
            # Extract date from filename if possible
            file_date_match = re.search(r'10-K_(\d{8})', os.path.basename(k_file))
            if file_date_match:
                file_date_str = file_date_match.group(1)
                file_date = datetime.strptime(file_date_str, '%Y%m%d')
                
                # If our local file was created after the latest filing date, use it
                if file_date >= latest_k_date.replace(tzinfo=None):
                    k_file_path = k_file
                    found_latest_k = True
                    print(f"Using existing 10-K file: {k_file_path} (matches or newer than latest SEC filing)")
                    break
            else:
                # If we can't extract date from filename, check file modification time
                mod_time = datetime.fromtimestamp(os.path.getmtime(os.path.join(ROOT, k_file)))
                if mod_time >= latest_k_date.replace(tzinfo=None):
                    k_file_path = k_file
                    found_latest_k = True
                    print(f"Using existing 10-K file: {k_file_path} (file modification time matches or newer than latest SEC filing)")
                    break
        
        if not found_latest_k:
            outdated_files_exist = True
    
    # Check if we have the latest 10-Q locally
    if q_files and latest_q_date:
        found_latest_q = False
        for q_file in sorted(q_files, key=lambda x: os.path.getmtime(os.path.join(ROOT, x)), reverse=True):
            # Extract date from filename if possible
            file_date_match = re.search(r'10-Q_(\d{8})', os.path.basename(q_file))
            if file_date_match:
                file_date_str = file_date_match.group(1)
                file_date = datetime.strptime(file_date_str, '%Y%m%d')
                
                # If our local file was created after the latest filing date, use it
                if file_date >= latest_q_date.replace(tzinfo=None):
                    q_file_path = q_file
                    found_latest_q = True
                    print(f"Using existing 10-Q file: {q_file_path} (matches or newer than latest SEC filing)")
                    break
            else:
                # If we can't extract date from filename, check file modification time
                mod_time = datetime.fromtimestamp(os.path.getmtime(os.path.join(ROOT, q_file)))
                if mod_time >= latest_q_date.replace(tzinfo=None):
                    q_file_path = q_file
                    found_latest_q = True
                    print(f"Using existing 10-Q file: {q_file_path} (file modification time matches or newer than latest SEC filing)")
                    break
        
        if not found_latest_q:
            outdated_files_exist = True
    
    # If we have outdated files, remove them
    if outdated_files_exist:
        print(f"Outdated filings found for {ticker}. Removing them and downloading latest filings...")
        
        # Remove all existing 10-K and 10-Q files
        for file_path in k_files + q_files:
            try:
                full_file_path = os.path.join(ROOT, file_path)
                if os.path.exists(full_file_path):
                    os.remove(full_file_path)
                    print(f"Removed outdated filing: {file_path}")
            except Exception as e:
                print(f"Error removing file {file_path}: {e}")
        
        # Reset file paths since we've removed the files
        k_file_path = None
        q_file_path = None
    
    # If we don't have the latest filings, fetch them from SEC API
    if not k_file_path or not q_file_path:
        print(f"Fetching latest filings for {ticker} from SEC API...")
        latest_filings = get_latest_filings(ticker)
        
        # Save 10-K if needed
        if "10-K" in latest_filings and not k_file_path:
            k_file_path = f"{data_folder}/10-K_{datetime.now().strftime('%Y%m%d')}.pdf"
            save_filing_to_local(latest_filings["10-K"]["content"], k_file_path)
        
        # Save 10-Q if needed
        if "10-Q" in latest_filings and not q_file_path:
            q_file_path = f"{data_folder}/10-Q_{datetime.now().strftime('%Y%m%d')}.pdf"
            save_filing_to_local(latest_filings["10-Q"]["content"], q_file_path)
    
    return k_file_path, q_file_path

# Replace extract_text_from_pdf function to work with local files
def extract_text_from_pdf(file_path: str) -> str:
    """Extract text content from a PDF file in local filesystem using PyMuPDF (fitz)"""
    text = ""
    try:
        # Extract text from the file
        full_path = os.path.join(ROOT, file_path)
        doc = fitz.open(full_path)
        for page_num in range(len(doc)):
            text += doc[page_num].get_text()
        doc.close()
        
        return text
    except Exception as e:
        print(f"Error extracting text from PDF {file_path}: {e}")
        return ""

def clean_value(value):
    """Convert string value with commas to Decimal"""
    if isinstance(value, str) and value:
        return Decimal(value.replace(',', ''))
    return Decimal('0')

def format_value(value):
    """Format Decimal value back to string with commas"""
    if isinstance(value, Decimal):
        return f"{value:,}"
    return value

# Replace get_prompt_for_ticker function to read YAML from local filesystem
def get_prompt_for_ticker(ticker: str) -> str:
    """Get the appropriate prompt for the given ticker symbol from a common YAML file"""
    yaml_file_path = os.path.join(ROOT, "utils", "cap_prompt.yaml")

    try:
        # Parse YAML content
        with open(yaml_file_path, "r") as f:
            prompts = yaml.safe_load(f)

        # Get prompt_start from YAML
        prompt_start = prompts.get("prompt_start", "")

        # Get ticker-specific prompt (or default)
        if ticker in prompts:
            prompt_rest = prompts[ticker]
        else:
            print(f"No specific prompt found for ticker {ticker} in cap_prompt.yaml. Using default prompt.")
            prompt_rest = prompts.get("default", "")

    except Exception as e:
        print(f"Error reading prompt file: {e}. Using default prompt.")
        prompt_start, prompt_rest = "", ""

    return prompt_start + prompt_rest

def compute_and_update_json(json_data: str, ticker: str) -> str:
    """Compute and update the capitalization values and ratios in the JSON data"""
    try:
        # Parse the JSON data
        data = json.loads(json_data)
        
        # Helper function to safely get numeric values
        def get_numeric_value(value):
            if value is None:
                return None
            if isinstance(value, str):
                return clean_value(value)
            elif isinstance(value, (int, float)):
                return Decimal(str(value))
            return None
        
        # Helper function to format ratio as string with 'x' suffix
        def format_ratio(value, decimal_places=1):
            if value is None:
                return "-"
            return f"{value:.{decimal_places}f}x"
        
        # Helper function to format percentage with '%' suffix
        def format_percentage(value, decimal_places=1):
            if value is None:
                return "-"
            return f"{value:.{decimal_places}f}%"
        
        # Calculate book capitalization
        total_debt = get_numeric_value(data.get("total_debt"))
        book_equity = get_numeric_value(data.get("book_value_of_equity"))
        
        if total_debt is not None and book_equity is not None:
            book_cap = total_debt + book_equity
            data["book_capitalization"] = int(book_cap) if book_cap == int(book_cap) else float(book_cap)
        
        # Calculate market capitalization
        market_equity = get_numeric_value(data.get("market_value_of_equity"))
        
        if total_debt is not None and market_equity is not None:
            market_cap = total_debt + market_equity
            data["market_capitalization"] = int(market_cap) if market_cap == int(market_cap) else float(market_cap)
        
        # Update financial ratios if the key exists
        if "key_financial_ratios" in data:
            ratios = data["key_financial_ratios"]
            
            # Total debt to adjusted EBITDA
            ltm_ebitda = get_numeric_value(data.get("ltm_adj_ebitda"))
            if total_debt is not None and ltm_ebitda is not None and ltm_ebitda != 0:
                ratio = float(total_debt / ltm_ebitda)
                ratios["total_debt_to_adj_ebitda"] = format_ratio(ratio)
            elif "total_debt_to_adj_ebitda" in ratios:
                ratios["total_debt_to_adj_ebitda"] = "-"
            
            # Total debt to market capitalization
            market_cap = get_numeric_value(data.get("market_capitalization"))
            if total_debt is not None and market_cap is not None and market_cap != 0:
                debt_to_market_cap = float((total_debt / market_cap) * 100)
                ratios["total_debt_to_market_capitalization"] = format_percentage(debt_to_market_cap)
            elif "total_debt_to_market_capitalization" in ratios:
                ratios["total_debt_to_market_capitalization"] = "-"
            
            # Total debt plus COLS to adjusted EBITDAR
            debt_cols = get_numeric_value(data.get("total_debt_plus_cols"))
            ebitdar = get_numeric_value(data.get("adj_ebitdar"))
            if debt_cols is not None and ebitdar is not None and ebitdar != 0:
                debt_cols_to_ebitdar = float(debt_cols / ebitdar)
                ratios["total_debt_plus_cols_to_adj_ebitdar"] = format_ratio(debt_cols_to_ebitdar, 2)
            elif "total_debt_plus_cols_to_adj_ebitdar" in ratios:
                ratios["total_debt_plus_cols_to_adj_ebitdar"] = "-"
            
            # Net debt plus COLS to adjusted EBITDAR
            cash = get_numeric_value(data.get("cash_and_equivalents"))
            if cash is not None and debt_cols is not None and ebitdar is not None and ebitdar != 0:
                net_debt = debt_cols - cash
                net_debt_to_ebitdar = float(net_debt / ebitdar)
                ratios["net_debt_plus_cols_to_adj_ebitdar"] = format_ratio(net_debt_to_ebitdar, 2)
            elif "net_debt_plus_cols_to_adj_ebitdar" in ratios:
                ratios["net_debt_plus_cols_to_adj_ebitdar"] = "-"
            
            # Total debt plus COLS to book capitalization
            book_cap = get_numeric_value(data.get("book_capitalization"))
            if debt_cols is not None and book_cap is not None and book_cap != 0:
                debt_to_book_cap = float((debt_cols / book_cap) * 100)
                ratios["total_debt_plus_cols_to_book_capitalization"] = format_percentage(debt_to_book_cap, 2)
            elif "total_debt_plus_cols_to_book_capitalization" in ratios:
                ratios["total_debt_plus_cols_to_book_capitalization"] = "-"
            
            # Total debt plus COLS to market capitalization
            if debt_cols is not None and market_cap is not None and market_cap != 0:
                debt_to_market_cap = float((debt_cols / market_cap) * 100)
                ratios["total_debt_plus_cols_to_market_capitalization"] = format_percentage(debt_to_market_cap, 2)
            elif "total_debt_plus_cols_to_market_capitalization" in ratios:
                ratios["total_debt_plus_cols_to_market_capitalization"] = "-"
        
        return json.dumps(data, indent=4)
    except Exception as e:
        print(f"Error in compute_and_update_json: {e}")
        return json_data

def json_to_csv(json_data: str) -> str:
    """Convert JSON data to CSV format"""
    try:
        data = json.loads(json_data)
        csv_lines = []
        
        # Add company and as_of date
        csv_lines.append(f"Company,{data.get('company', '-')}")
        csv_lines.append(f"As of,{data.get('as_of', '-')}")
        csv_lines.append("")
        
        # Add cash and equivalents
        csv_lines.append(f"Cash & Equivalents,{data.get('cash_and_equivalents', '-')}")
        csv_lines.append("")
        
        # Add debt section header
        csv_lines.append("Debt,Amount,PPC Holdings,Coupon,Secured,Maturity")
        
        # Add debt items
        if "debt" in data and isinstance(data["debt"], list):
            for debt_item in data["debt"]:
                amount = debt_item.get("amount", "-")
                # Format negative values with parentheses
                if isinstance(amount, (int, float, Decimal)) and amount < 0:
                    amount = f"({abs(amount)})"
                
                csv_lines.append(f"{debt_item.get('type', '-')},{amount},{debt_item.get('ppc_holdings', '-')},{debt_item.get('coupon', '-')},{debt_item.get('secured', '-')},{debt_item.get('maturity', '-')}")
        
        # Add totals
        csv_lines.append(f"Total Debt,{data.get('total_debt', '-')}")
        csv_lines.append(f"Total PPC Holdings,{data.get('total_ppc_holdings', '-')}")
        csv_lines.append("")
        # Add capitalization
        csv_lines.append(f"Book Value of Equity,{data.get('book_value_of_equity', '-')}")
        csv_lines.append(f"Book Capitalization,{data.get('book_capitalization', '-')}")
        csv_lines.append("")
        csv_lines.append(f"Market Value of Equity,{data.get('market_value_of_equity', '-')}")
        csv_lines.append(f"Market Capitalization,{data.get('market_capitalization', '-')}")
        csv_lines.append("")
        
        # Add other financial metrics
        csv_lines.append(f"LTM Adj. EBITDA,{data.get('ltm_adj_ebitda', '-')}")
        
        if "market_value_of_re_assets" in data:
            csv_lines.append(f"Market Value of RE Assets,{data.get('market_value_of_re_assets', '-')}")
        
        if "unencumbered_assets" in data:
            csv_lines.append(f"Unencumbered Assets,{data.get('unencumbered_assets', '-')}")
        
        csv_lines.append("")
        
        # Add key financial ratios
        csv_lines.append("Key Financial Ratios:")
        if "key_financial_ratios" in data:
            for key, value in data["key_financial_ratios"].items():
                # Format the ratio name for CSV display
                ratio_name = key.replace("_", " ").title().replace("To", "/").replace("Adj ", "Adj. ").replace("Re ", "RE ")
                csv_lines.append(f"{ratio_name},{value}")
        
        # Add footnotes
        if "debt_footnotes" in data:
            csv_lines.append("")
            csv_lines.append("Debt Footnotes:")
            for key, value in data["debt_footnotes"].items():
                footnote_num = key.replace("footnote_", "")
                csv_lines.append(f"({footnote_num}) {value}")
        
        return "\n".join(csv_lines)
    except Exception as e:
        print(f"Error in json_to_csv: {e}")
        return "Error converting JSON to CSV"


def get_response_from_llm(pdf_text: str, ticker: str) -> Tuple[Optional[str], Optional[dict], Optional[str]]:
    """Send PDF text to LLM and get cap table data, source lineage, and CSV response"""
    # Load environment variables from .env file
    load_dotenv()
    
    # Get OpenAI credentials from environment variables
    openai_api_key = os.getenv("OPENAI_API_KEY")

    # Ensure the API key is set
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY must be set in the .env file")

    prompt = get_prompt_for_ticker(ticker)

    # Initialize OpenAI client
    client = OpenAI(
        api_key=openai_api_key,
    )

    try:
        # Create messages for the chat completion
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Here is the SEC filing text:\n\n{pdf_text}"},
            {"role": "user", "content": "Please update the cap table with the most recent financial data and return it in the requested format with both CAPITALIZATION_DATA and SOURCE_LINEAGE sections."}
        ]

        # Call the OpenAI API
        chat_completion = client.chat.completions.create(
            messages=messages,
            model="gpt-4o",
            max_tokens=8192,
            temperature=0,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        )
        
        content = chat_completion.choices[0].message.content
        
        # Parse the response to extract cap table data and source lineage
        cap_table_json, source_lineage = parse_llm_response_with_lineage(content)
        
        if not cap_table_json:
            print("Warning: Could not extract cap table JSON from LLM response.")
            return None, None
        
        return cap_table_json, source_lineage
        
    except Exception as e:
        print(f"Error in get_response_from_llm: {e}")
        return None, None
    
def parse_llm_response_with_lineage(content: str) -> Tuple[Optional[str], Optional[dict], Optional[str]]:
    """Parse LLM response to extract cap table data, source lineage, and CSV"""
    try:
        cap_table_json = None
        source_lineage = None
        
        # Extract CAPITALIZATION_DATA
        if "CAPITALIZATION_DATA:" in content:
            cap_data_section = content.split("CAPITALIZATION_DATA:", 1)[1]
            if "SOURCE_LINEAGE:" in cap_data_section:
                cap_data_section = cap_data_section.split("SOURCE_LINEAGE:", 1)[0]
            
            # Extract JSON from the section
            if "```json" in cap_data_section:
                cap_table_json = cap_data_section.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "{" in cap_data_section:
                start_idx = cap_data_section.find("{")
                end_idx = cap_data_section.rfind("}") + 1
                if start_idx < end_idx:
                    cap_table_json = cap_data_section[start_idx:end_idx].strip()
        
        # Extract SOURCE_LINEAGE
        if "SOURCE_LINEAGE:" in content:
            lineage_section = content.split("SOURCE_LINEAGE:", 1)[1]
            
            # Extract JSON from the section
            if "```json" in lineage_section:
                lineage_json_str = lineage_section.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "{" in lineage_section:
                start_idx = lineage_section.find("{")
                end_idx = lineage_section.rfind("}") + 1
                if start_idx < end_idx:
                    lineage_json_str = lineage_section[start_idx:end_idx].strip()
            
            try:
                source_lineage = json.loads(lineage_json_str)
            except json.JSONDecodeError as e:
                print(f"Error parsing source lineage JSON: {e}")
                source_lineage = None
        
        return cap_table_json, source_lineage
        
    except Exception as e:
        print(f"Error parsing LLM response: {e}")
        return None, None, None
    
def format_numeric_value(value):
    """Format numeric value with commas for thousands separator"""
    if value is None:
        return None
    
    try:
        if isinstance(value, str):
            clean_value = value.replace(',', '')
            if clean_value.replace('-', '').replace('.', '').isdigit():
                value = float(clean_value) if '.' in clean_value else int(clean_value)
            else:
                return value  
        
        if isinstance(value, (int, float, Decimal)):
            if value < 0:
                return f"({abs(value):,.0f})"  
            else:
                return f"{value:,.0f}"
        
        return str(value)  
    except:
        return str(value) if value is not None else None
    
# def create_lineage_log(ticker: str, cap_table_data: dict, source_lineage: dict, calculated_values: dict = None) -> dict:
#     """Create comprehensive lineage log combining source data and calculations"""
    
#     # Fix timestamp format
#     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
#     # Start with the source lineage from LLM
#     lineage_log = {
#         "ticker": ticker,
#         "as_of_date": source_lineage.get("as_of_date", datetime.now().strftime("%Y-%m-%d")),
#         "timestamp": timestamp,  # Fixed format: YYYYMMDD_HHMMSS
#         "metrics": {}
#     }
    
#     # First, copy all LLM source lineage metrics (these contain raw data from filings)
#     if source_lineage and "metrics" in source_lineage:
#         for metric_name, metric_data in source_lineage["metrics"].items():
#             lineage_log["metrics"][metric_name] = {
#                 "final_value": metric_data.get("final_value"),
#                 "unit": metric_data.get("unit"),
#                 "calculation": metric_data.get("calculation"),
#                 "components": metric_data.get("components", {}),
#                 "sources": metric_data.get("sources", {})
#             }
    
#     # Now add calculated metrics dynamically based on what's in cap_table_data
#     calculated_metrics = []
    
#     # Process each metric from cap table to identify calculated ones
#     for metric_name, metric_value in cap_table_data.items():
#         if metric_name in ["company", "as_of"]:
#             continue
            
#         # Skip if already handled by LLM lineage or if it's the debt array
#         if metric_name in lineage_log["metrics"] or metric_name == "debt":
#             continue
            
#         # This is a calculated metric that needs lineage
#         calculated_metrics.append((metric_name, metric_value))
    
#     # Handle calculated metrics dynamically
#     for metric_name, metric_value in calculated_metrics:
#         lineage_entry = create_calculated_metric_lineage(metric_name, metric_value, cap_table_data, lineage_log["metrics"])
#         if lineage_entry:
#             lineage_log["metrics"][metric_name] = lineage_entry
    
#     # Handle financial ratios dynamically
#     if "key_financial_ratios" in cap_table_data and isinstance(cap_table_data["key_financial_ratios"], dict):
#         for ratio_name, ratio_value in cap_table_data["key_financial_ratios"].items():
#             if ratio_value and ratio_value != "-" and ratio_value is not None:
#                 ratio_entry = create_ratio_lineage_entry(ratio_name, ratio_value, cap_table_data)
#                 lineage_log["metrics"][f"ratio_{ratio_name}"] = ratio_entry
    
#     return lineage_log
def create_lineage_log(ticker: str, cap_table_data: dict, source_lineage: dict, calculated_values: dict = None) -> dict:
    """Create comprehensive lineage log combining source data and calculations"""
    
    # Fix timestamp format
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Start with the source lineage from LLM
    lineage_log = {
        "ticker": ticker,
        "as_of_date": source_lineage.get("as_of_date", datetime.now().strftime("%Y-%m-%d")),
        "timestamp": timestamp,  # Fixed format: YYYYMMDD_HHMMSS
        "metrics": {}
    }
    
    # First, copy all LLM source lineage metrics (these contain raw data from filings)
    if source_lineage and "metrics" in source_lineage:
        for metric_name, metric_data in source_lineage["metrics"].items():
            lineage_log["metrics"][metric_name] = {
                "final_value": metric_data.get("final_value"),
                "formatted_value": format_numeric_value(metric_data.get("final_value")),
                "unit": metric_data.get("unit"),
                "calculation": metric_data.get("calculation"),
                "components": metric_data.get("components", {}),
                "sources": metric_data.get("sources", {})
            }
    
    # Now add calculated metrics dynamically based on what's in cap_table_data
    calculated_metrics = []
    
    # Process each metric from cap table to identify calculated ones
    for metric_name, metric_value in cap_table_data.items():
        if metric_name in ["company", "as_of"]:
            continue
            
        # Skip if already handled by LLM lineage or if it's the debt array
        if metric_name in lineage_log["metrics"] or metric_name == "debt":
            continue
            
        # This is a calculated metric that needs lineage
        calculated_metrics.append((metric_name, metric_value))
    
    # Handle calculated metrics dynamically
    for metric_name, metric_value in calculated_metrics:
        lineage_entry = create_calculated_metric_lineage(metric_name, metric_value, cap_table_data, lineage_log["metrics"])
        if lineage_entry:
            # Add formatted_value to calculated metrics
            lineage_entry["formatted_value"] = format_numeric_value(lineage_entry["final_value"])
            lineage_log["metrics"][metric_name] = lineage_entry
    
    # Handle financial ratios dynamically
    if "key_financial_ratios" in cap_table_data and isinstance(cap_table_data["key_financial_ratios"], dict):
        for ratio_name, ratio_value in cap_table_data["key_financial_ratios"].items():
            if ratio_value and ratio_value != "-" and ratio_value is not None:
                ratio_entry = create_ratio_lineage_entry(ratio_name, ratio_value, cap_table_data)
                # Ratios already come formatted (with 'x' or '%'), so use final_value as formatted_value
                ratio_entry["formatted_value"] = str(ratio_entry["final_value"])
                lineage_log["metrics"][f"ratio_{ratio_name}"] = ratio_entry
    
    return lineage_log

def create_calculated_metric_lineage(metric_name: str, metric_value, cap_table_data: dict, existing_metrics: dict) -> dict:
    """Dynamically create lineage for calculated metrics"""
    
    # Determine unit
    unit = "USD_thousands" if isinstance(metric_value, (int, float)) and metric_value is not None else None
    
    metric_entry = {
        "final_value": metric_value,
        "unit": unit,
        "calculation": None,
        "components": {},
        "sources": {}
    }
    
    # Handle different types of calculated metrics
    
    # Total debt calculation
    if metric_name == "total_debt" and "debt" in cap_table_data and isinstance(cap_table_data["debt"], list):
        debt_components = {}
        component_names = []
        
        for debt_item in cap_table_data["debt"]:
            debt_type = debt_item.get("type", "unknown")
            debt_amount = debt_item.get("amount", 0)
            
            # Convert debt type to snake_case for component naming
            component_name = convert_to_snake_case(debt_type)
            debt_components[component_name] = debt_amount
            component_names.append(component_name)
        
        metric_entry["calculation"] = " + ".join(component_names)
        metric_entry["components"] = debt_components
        
        # Create sources referencing individual debt metrics from LLM
        for comp_name in component_names:
            # Look for corresponding debt item lineage in existing metrics
            debt_metric_key = find_debt_metric_key(comp_name, existing_metrics)
            if debt_metric_key:
                metric_entry["sources"][comp_name] = {"ref_metric": debt_metric_key}
            else:
                # Fallback - mark as calculated from debt array
                metric_entry["sources"][comp_name] = {"ref_metric": f"debt_item_{comp_name}"}
    
    # Capitalization calculations
    elif metric_name.endswith("_capitalization"):
        components = get_capitalization_components(metric_name, cap_table_data)
        if components:
            component_names = list(components.keys())
            metric_entry["calculation"] = " + ".join(component_names)
            metric_entry["components"] = components
            
            for comp_name, comp_value in components.items():
                if comp_name in existing_metrics:
                    metric_entry["sources"][comp_name] = {"ref_metric": comp_name}
                else:
                    # This component should exist in cap_table_data
                    metric_entry["sources"][comp_name] = {"ref_metric": comp_name}
    
    # Plus COLS calculations (for AME ticker)
    elif metric_name.endswith("_plus_cols"):
        base_metric = metric_name.replace("_plus_cols", "")
        cols_metric = "capitalized_operating_leases"
        
        base_value = cap_table_data.get(base_metric)
        cols_value = cap_table_data.get(cols_metric)
        
        if base_value is not None and cols_value is not None:
            metric_entry["calculation"] = f"{base_metric} + {cols_metric}"
            metric_entry["components"] = {
                base_metric: base_value,
                cols_metric: cols_value
            }
            metric_entry["sources"] = {
                base_metric: {"ref_metric": base_metric},
                cols_metric: {"ref_metric": cols_metric}
            }
    
    # Return None if we couldn't determine how to calculate this metric
    if not metric_entry["calculation"]:
        return None
        
    return metric_entry

def get_capitalization_components(metric_name: str, cap_table_data: dict) -> dict:
    """Get components for capitalization calculations"""
    components = {}
    
    if metric_name == "book_capitalization":
        total_debt = cap_table_data.get("total_debt")
        book_equity = cap_table_data.get("book_value_of_equity")
        
        if total_debt is not None and book_equity is not None:
            components["total_debt"] = total_debt
            components["book_value_of_equity"] = book_equity
    
    elif metric_name == "market_capitalization":
        total_debt = cap_table_data.get("total_debt")
        market_equity = cap_table_data.get("market_value_of_equity")
        
        if total_debt is not None and market_equity is not None:
            components["total_debt"] = total_debt
            components["market_value_of_equity"] = market_equity
    
    return components

def convert_to_snake_case(text: str) -> str:
    """Convert text to snake_case format"""
    if not text:
        return "unknown"
        
    # Remove special characters and parentheses
    text = text.replace("(", "").replace(")", "").replace(":", "").replace("-", "_")
    text = text.replace("Less: ", "").replace("less_", "")
    
    # Convert to snake_case
    text = text.lower().replace(" ", "_")
    
    # Clean up multiple underscores
    while "__" in text:
        text = text.replace("__", "_")
    
    # Remove leading/trailing underscores
    text = text.strip("_")
    
    return text if text else "unknown"

def find_debt_metric_key(component_name: str, existing_metrics: dict) -> str:
    """Find the corresponding debt metric key in existing metrics"""
    
    # Look for exact match first
    for metric_key in existing_metrics.keys():
        if metric_key == component_name:
            return metric_key
    
    # Look for similar names
    component_words = set(component_name.split("_"))
    
    for metric_key in existing_metrics.keys():
        if "debt" in metric_key.lower():
            metric_words = set(metric_key.split("_"))
            # If there's significant overlap in words, consider it a match
            if len(component_words.intersection(metric_words)) >= 2:
                return metric_key
    
    return None

def create_ratio_lineage_entry(ratio_name: str, ratio_value: str, cap_table_data: dict) -> dict:
    """Create lineage entry for financial ratios dynamically"""
    
    # Determine unit based on ratio value format
    if "x" in str(ratio_value):
        unit = "ratio"
    elif "%" in str(ratio_value):
        unit = "percentage" 
    else:
        unit = "ratio"
    
    ratio_entry = {
        "final_value": ratio_value,
        "unit": unit,
        "calculation": None,
        "components": {},
        "sources": {}
    }
    
    # Dynamic ratio calculation based on naming patterns
    ratio_parts = ratio_name.split("_to_")
    
    if len(ratio_parts) == 2:
        numerator_key = ratio_parts[0]
        denominator_key = ratio_parts[1]
        
        # Get values from cap_table_data
        numerator_value = cap_table_data.get(numerator_key)
        denominator_value = cap_table_data.get(denominator_key)
        
        # Handle special cases
        if "market_capitalization" in ratio_name and denominator_key == "market_capitalization":
            # This is a percentage calculation
            ratio_entry["calculation"] = f"( {numerator_key} / {denominator_key} ) * 100"
        elif "net_debt" in numerator_key:
            # Net debt calculation involves subtraction
            base_debt = numerator_key.replace("net_", "")
            cash_key = "cash_and_equivalents"
            
            base_value = cap_table_data.get(base_debt)
            cash_value = cap_table_data.get(cash_key)
            
            ratio_entry["calculation"] = f"( {base_debt} - {cash_key} ) / {denominator_key}"
            ratio_entry["components"] = {
                base_debt: base_value,
                cash_key: cash_value,
                denominator_key: denominator_value
            }
            ratio_entry["sources"] = {
                base_debt: {"ref_metric": base_debt},
                cash_key: {"ref_metric": cash_key},
                denominator_key: {"ref_metric": denominator_key}
            }
            return ratio_entry
        else:
            # Standard division
            ratio_entry["calculation"] = f"{numerator_key} / {denominator_key}"
        
        # Set components and sources
        ratio_entry["components"] = {
            numerator_key: numerator_value,
            denominator_key: denominator_value
        }
        ratio_entry["sources"] = {
            numerator_key: {"ref_metric": numerator_key},
            denominator_key: {"ref_metric": denominator_key}
        }
    
    return ratio_entry

def save_lineage_log(lineage_log: dict, ticker: str) -> str:
    """Save lineage log to local filesystem with correct timestamp format"""
    try:
        # Ensure directory exists
        log_dir = os.path.join(ROOT, "logs", "CAP")
        os.makedirs(log_dir, exist_ok=True)
        
        # Use the timestamp from the lineage_log itself
        timestamp = lineage_log.get("timestamp", datetime.now().strftime("%Y%m%d_%H%M%S"))
        log_filename = f"CAP_{ticker}_{timestamp}.json"
        log_path = os.path.join(log_dir, log_filename)
        
        # Write the log
        with open(log_path, 'w') as f:
            json.dump(lineage_log, f, indent=2, default=str)
        
        print(f"Lineage log saved to: logs/CAP/{log_filename}")
        return f"logs/CAP/{log_filename}"
        
    except Exception as e:
        print(f"Error saving lineage log: {e}")
        return None


# Modify build_cap_table function to work with local files
def build_cap_table(ticker: str, write_files: bool = True, generate_lineage: bool = True, upload_to_azure: bool = False) -> Dict[str, Any]:
    """Build capitalization table with optional lineage logging"""
    # Ensure all required directories exist
    ensure_directories_exist()
    
    # Define output file paths
    json_output_path = f"output/json/cap_table/{ticker}_CAP.json"
    csv_output_path = f"output/csv/cap_table/{ticker}_CAP.csv"
    
    # Get the latest filings for the ticker
    k_file_path, q_file_path = get_filings_for_ticker(ticker)
    
    if not k_file_path:
        error_msg = f"No 10-K filing found for {ticker}."
        if TESTING_MODE:
            error_msg += " Unable to download from SEC API or save to local folder."
        raise FileNotFoundError(error_msg)
    
    combined_text = ""
    
    # Process 10-K file
    print(f"Processing 10-K file for {ticker}: {k_file_path}")
    k_text = extract_text_from_pdf(k_file_path)
    combined_text += "\n\n10-K FILING:\n" + k_text + "\n\n"
    
    # Process 10-Q file if it exists
    if q_file_path:
        print(f"Processing 10-Q file for {ticker}: {q_file_path}")
        q_text = extract_text_from_pdf(q_file_path)
        combined_text += "\n\n10-Q FILING:\n" + q_text
    else:
        print(f"Note: No 10-Q filing found for {ticker}. Proceeding with 10-K only.")
    
    # Try cache first
    if os.path.exists(json_output_path):
        try:
            with open(json_output_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if "cap_table" in cached and "source_lineage" in cached and cached["source_lineage"]:
                print(f"✅ Using cached CAP table + lineage for {ticker}")
                cap_table_json = json.dumps(cached["cap_table"])
                source_lineage = cached["source_lineage"]
            else:
                print(f"⚠️ Legacy cache for {ticker} missing source lineage; regenerating with LLM.")
                cap_table_json, source_lineage = get_response_from_llm(combined_text, ticker)
        except Exception as e:
            print(f"⚠️ Failed to load cache for {ticker}: {e}")
            cap_table_json, source_lineage = get_response_from_llm(combined_text, ticker)
    else:
        cap_table_json, source_lineage = get_response_from_llm(combined_text, ticker)

    if not cap_table_json:
        raise Exception(f"Failed to generate cap table for {ticker}")
    
    # Parse and compute cap table data
    updated_json_data = compute_and_update_json(cap_table_json, ticker)
    updated_cap_table_data = json.loads(updated_json_data)
    
    # Generate CSV if not provided
    csv_data = None
    if not csv_data:
        csv_data = json_to_csv(updated_json_data)
    
    # Generate lineage log if requested
    lineage_log_path = None
    if write_files:
        if generate_lineage and source_lineage:
            lineage_log = create_lineage_log(ticker, updated_cap_table_data, source_lineage)
            lineage_log_path = save_lineage_log(lineage_log, ticker)
    
    json_path = None
    csv_path = None
    blob_urls = {}
    
    if write_files:
        try:
            # Save JSON
            os.makedirs(os.path.dirname(json_output_path), exist_ok=True)
            with open(json_output_path, "w", encoding="utf-8") as f:
                json.dump({
                    "cap_table": json.loads(updated_json_data),
                    "source_lineage": source_lineage
                }, f, indent=2)

            
            # Save CSV
            os.makedirs(os.path.dirname(csv_output_path), exist_ok=True)
            with open(csv_output_path, "w", encoding="utf-8") as f:
                f.write(csv_data)
            
            json_path = json_output_path
            csv_path = csv_output_path
            print(f"✅ CAP table saved locally: {json_output_path}, {csv_output_path}")
        except Exception as e:
            print(f"⚠️ Failed to save CAP table locally: {e}")
    
    # Handle Azure Blob Storage upload
    if upload_to_azure:
        try:
            from utils.azure_blob_storage import upload_json_to_blob_direct, upload_csv_to_blob_direct
            
            container_name = "cap-outputs"
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Upload JSON directly
            json_blob_name = f"{ticker}/CAP_{ticker}_{timestamp_str}.json"
            json_url = upload_json_to_blob_direct(json.loads(updated_json_data), container_name, json_blob_name)
            blob_urls["json_url"] = json_url
            
            # Convert CSV data to rows format for direct upload
            csv_rows = []
            for line in csv_data.split('\n'):
                if line.strip() and ',' in line:
                    parts = line.split(',', 1)
                    if len(parts) == 2:
                        csv_rows.append({"field": parts[0], "value": parts[1]})
            
            # Upload CSV directly
            csv_blob_name = f"{ticker}/CAP_{ticker}_{timestamp_str}.csv"
            csv_url = upload_csv_to_blob_direct(csv_rows, container_name, csv_blob_name)
            blob_urls["csv_url"] = csv_url
            
            # Upload lineage log directly
            if generate_lineage and source_lineage:
                lineage_log = create_lineage_log(ticker, updated_cap_table_data, source_lineage)
                log_container_name = "logs"
                log_blob_name = f"CAP/CAP_{ticker}_{timestamp_str}.json"
                log_url = upload_json_to_blob_direct(lineage_log, log_container_name, log_blob_name)
                blob_urls["log_url"] = log_url
            
            print(f"✅ CAP table data uploaded to Azure Blob Storage: {blob_urls}")
        except Exception as e:
            print(f"Warning: Failed to upload CAP table data to Azure Blob Storage: {e}")
    
    result = {
        "ticker": ticker,
        "json_data": updated_json_data,
        "csv_data": csv_data,
        "source_lineage": source_lineage,
        "lineage_log_path": lineage_log_path,
        "json_path": json_path,
        "csv_path": csv_path,
        "blob_urls": blob_urls,
        "cached": False
    }
    
    return result

if __name__ == "__main__":
    import argparse
    
    # Configure for corporate environment
    configure_requests_for_corporate_environment()
    
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Build capitalization table for a given ticker symbol')
    parser.add_argument('ticker', type=str, help='Ticker symbol of the company')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Use the provided ticker symbol
    ticker = args.ticker
    
    print(f"Building cap table for {ticker}...")
    result = build_cap_table(ticker)
    print("Cap table built successfully!")
    print("JSON path:", result.get("json_path"))
    print("CSV path:", result.get("csv_path"))