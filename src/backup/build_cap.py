import json
import csv
import os
from decimal import Decimal
import fitz  # PyMuPDF
from typing import Dict, Any, Tuple, Optional, List
import requests
from dotenv import load_dotenv
from openai import AzureOpenAI
import yaml
import io
import tempfile
from datetime import datetime
from sec_api import QueryApi, RenderApi, PdfGeneratorApi
import time
import re

# Root directory path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
        os.makedirs(os.path.dirname(os.path.join(ROOT, file_path)), exist_ok=True)
        
        # Write the PDF content to file
        with open(os.path.join(ROOT, file_path), 'wb') as f:
            f.write(pdf_content)
        
        print(f"Saved filing to {file_path}")
        return True
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
    
    # Check if we have recent filings in local filesystem
    k_files = []
    q_files = []
    
    if os.path.exists(full_data_folder):
        for file in os.listdir(full_data_folder):
            file_path = os.path.join(data_folder, file)
            if ("10-K" in file.upper() or "10K" in file.upper()) and file.endswith(".pdf"):
                k_files.append(file_path)
            elif ("10-Q" in file.upper() or "10Q" in file.upper()) and file.endswith(".pdf"):
                q_files.append(file_path)
    
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

def get_response_from_llm(pdf_text: str, ticker: str) -> Tuple[Optional[str], Optional[str]]:
    """Send PDF text to LLM and get updated JSON and CSV response"""
    # Load environment variables from .env file
    load_dotenv()
    
    # Get Azure OpenAI credentials from environment variables
    azure_api_key = os.getenv("AZURE_OPENAI_API_KEY")
    
    # Ensure the API key is set
    if not azure_api_key:
        raise ValueError("AZURE_OPENAI_API_KEY must be set in the .env file")
    
    prompt = get_prompt_for_ticker(ticker)
    
    # Initialize Azure OpenAI client
    client = AzureOpenAI(
        api_version="2024-12-01-preview",
        azure_endpoint="https://pgim-dealio.cognitiveservices.azure.com/",
        api_key=azure_api_key,
    )
    
    try:
        # Create messages for the chat completion
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Here is the SEC filing text:\n\n{pdf_text}"},
            {"role": "user", "content": "Please update the cap table with the most recent financial data and return it in JSON format."}
        ]
        
        # Call the Azure OpenAI API
        chat_completion = client.chat.completions.create(
            messages=messages,
            model="gpt-4.1",
            max_completion_tokens=13107,
            temperature=0,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        )
        
        content = chat_completion.choices[0].message.content
        
        # Extract JSON and CSV parts from the response
        json_part = None
        csv_part = None
        
        # Try to extract JSON part
        if "```json" in content and "```" in content.split("```json", 1)[1]:
            json_part = content.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "{" in content and "}" in content:
            # Try to extract JSON by finding the first { and last }
            start_idx = content.find("{")
            end_idx = content.rfind("}") + 1
            if start_idx < end_idx:
                json_part = content[start_idx:end_idx].strip()
        
        # Try to extract CSV part
        if "```csv" in content and "```" in content.split("```csv", 1)[1]:
            csv_part = content.split("```csv", 1)[1].split("```", 1)[0].strip()
        elif "CSV" in content or "csv" in content:
            # If there's a CSV section marker, try to extract after that
            csv_markers = ["CSV:", "CSV Format:", "In CSV format:", "CSV representation:"]
            for marker in csv_markers:
                if marker in content:
                    csv_part = content.split(marker, 1)[1].strip()
                    break

        if not json_part:
            print("Warning: Could not extract JSON part from LLM response. Using full response.")
            return content, None
        
        # Compute and update the JSON data
        updated_json = compute_and_update_json(json_part, ticker)
        
        # If CSV part wasn't extracted, generate it from the updated JSON
        if not csv_part:
            csv_part = json_to_csv(updated_json)
        
        return updated_json, csv_part
    except Exception as e:
        print(f"Error in get_response_from_llm: {e}")
        return None, None

# Modify build_cap_table function to work with local files
def build_cap_table(ticker: str, write_files: bool = True) -> Dict[str, Any]:
    """Build capitalization table for the given ticker and optionally write to local filesystem.
    Returns a dict with results and file paths.
    """
    # Ensure all required directories exist
    ensure_directories_exist()
    
    # Define output file paths
    json_output_path = f"output/json/cap_table/{ticker}_CAP.json"
    csv_output_path = f"output/csv/cap_table/{ticker}_CAP.csv"
    
    # Get the latest filings for the ticker
    k_file_path, q_file_path = get_filings_for_ticker(ticker)
    
    if not k_file_path:
        raise FileNotFoundError(f"No 10-K filing found for {ticker}")
    
    # Check if we're using existing filings and if a cached JSON output exists
    json_output_full_path = os.path.join(ROOT, json_output_path)
    csv_output_full_path = os.path.join(ROOT, csv_output_path)
    
    # Determine if we're using existing filings by checking if they were already on disk
    using_existing_filings = False
    if k_file_path and os.path.exists(os.path.join(ROOT, k_file_path)):
        # Check if the file was created before this run (not just downloaded)
        k_file_creation_time = os.path.getctime(os.path.join(ROOT, k_file_path))
        k_file_age_seconds = time.time() - k_file_creation_time
        # If file is older than 5 minutes, it was likely not just downloaded in this run
        if k_file_age_seconds > 300:
            using_existing_filings = True
            
            # If using Q file, check that too
            if q_file_path and os.path.exists(os.path.join(ROOT, q_file_path)):
                q_file_creation_time = os.path.getctime(os.path.join(ROOT, q_file_path))
                q_file_age_seconds = time.time() - q_file_creation_time
                # Both files need to be existing files
                using_existing_filings = using_existing_filings and (q_file_age_seconds > 300)
    
    # If using existing filings and cached JSON exists, use it
    if using_existing_filings and os.path.exists(json_output_full_path):
        print(f"Using cached JSON output for {ticker}")
        
        # Read the cached JSON data
        with open(json_output_full_path, 'r') as f:
            updated_json_data = f.read()
        
        # Check if CSV exists, if not generate it
        if os.path.exists(csv_output_full_path):
            with open(csv_output_full_path, 'r') as f:
                updated_csv_data = f.read()
        else:
            # Generate CSV from JSON
            updated_csv_data = json_to_csv(updated_json_data)
            # Write CSV if requested
            if write_files:
                with open(csv_output_full_path, 'w') as f:
                    f.write(updated_csv_data)
        
        result = {
            "ticker": ticker,
            "json_data": updated_json_data,
            "csv_data": updated_csv_data,
            "json_path": json_output_path,
            "csv_path": csv_output_path,
            "cached": True
        }
        
        return result
    
    # If no cached data or not using existing filings, proceed with normal flow
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
    
    # Get updated JSON and CSV data from LLM
    updated_json_data, updated_csv_data = get_response_from_llm(combined_text, ticker)
    
    if not updated_json_data:
        raise Exception(f"Failed to generate cap table for {ticker}")
    
    result = {
        "ticker": ticker,
        "json_data": updated_json_data,
        "csv_data": updated_csv_data,
        "cached": False
    }
    
    # Write the updated data to local filesystem if requested
    if write_files:
        # Write JSON
        with open(json_output_full_path, 'w') as f:
            f.write(updated_json_data)
        result["json_path"] = json_output_path
        
        # Write CSV
        if updated_csv_data:
            with open(csv_output_full_path, 'w') as f:
                f.write(updated_csv_data)
            result["csv_path"] = csv_output_path
    
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