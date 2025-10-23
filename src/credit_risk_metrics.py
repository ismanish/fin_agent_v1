import json
import os
from decimal import Decimal
import fitz  # PyMuPDF
from typing import Dict, Any, Tuple, Optional
import requests
from dotenv import load_dotenv
from openai import OpenAI
import yaml
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

def ensure_directories_exist():
    """Ensure all required directories exist in the local filesystem"""
    directories = [
        os.path.join(ROOT, "data"),
        os.path.join(ROOT, "output", "json", "credit_risk_analysis"),
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
    print(f"🔍 Fetching latest filings from SEC API for {ticker}: {filing_types}")
    
    sec_api_key = get_sec_api_key()
    query_api = QueryApi(api_key=sec_api_key)
    pdf_generator_api = PdfGeneratorApi(api_key=sec_api_key)
    
    # Disable SSL warnings and modify requests
    import requests
    requests.packages.urllib3.disable_warnings()
    old_get = requests.get
    def new_get(*args, **kwargs):
        kwargs['verify'] = False
        return old_get(*args, **kwargs)
    requests.get = new_get
    
    results = {}
    
    for filing_type in filing_types:
        print(f"🔄 Searching for latest {filing_type} for {ticker}...")
        
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
        
        try:
            response = query_api.get_filings(query)
            
            if response['total']['value'] > 0:
                filing = response['filings'][0]
                filing_url = filing['linkToFilingDetails']
                filing_date = filing['filedAt']
                
                # Generate PDF from the filing URL
                print(f"📥 Downloading {filing_type} PDF for {ticker}...")
                pdf_content = pdf_generator_api.get_pdf(filing_url)
                results[filing_type] = {
                    'url': filing_url,
                    'date': filing_date,
                    'content': pdf_content
                }
                print(f"✅ Successfully retrieved {filing_type} for {ticker}, filed on {filing_date}")
                
                # Add a small delay to avoid rate limiting
                time.sleep(1)
            else:
                print(f"⚠️ No {filing_type} filings found for {ticker}")
        except Exception as e:
            print(f"❌ Error retrieving {filing_type} for {ticker}: {e}")
            continue
    
    return results

def save_filing_to_local(pdf_content, file_path):
    """Save a filing PDF to local filesystem"""
    try:
        # Ensure directory exists
        full_dir_path = os.path.dirname(os.path.join(ROOT, file_path))
        os.makedirs(full_dir_path, exist_ok=True)
        
        # Check if pdf_content is valid
        if not pdf_content:
            print(f"❌ Error: No PDF content to save for {file_path}")
            return False
        
        # Write the PDF content to file
        full_file_path = os.path.join(ROOT, file_path)
        with open(full_file_path, 'wb') as f:
            f.write(pdf_content)
        
        # Verify file was created and has content
        if os.path.exists(full_file_path) and os.path.getsize(full_file_path) > 0:
            print(f"💾 Saved filing to {file_path} ({os.path.getsize(full_file_path)} bytes)")
            return True
        else:
            print(f"❌ Error: File {file_path} was not created properly")
            return False
            
    except Exception as e:
        print(f"❌ Error saving filing to {file_path}: {e}")
        return False

def get_filings_for_ticker(ticker):
    """Get the latest filings for a ticker, either from local filesystem or SEC API"""
    print(f"🔍 Checking for filings for ticker: {ticker}")
    
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
    
    print(f"📁 Found local files - 10-K: {len(k_files)}, 10-Q: {len(q_files)}")
    
    k_file_path = k_files[0] if k_files else None
    q_file_path = q_files[0] if q_files else None
    
    # Download missing files if not found locally
    if not k_file_path or not q_file_path:
        missing_types = []
        if not k_file_path:
            missing_types.append("10-K")
        if not q_file_path:
            missing_types.append("10-Q")
        
        print(f"📥 Missing local files: {missing_types}. Downloading from SEC API...")
        
        try:
            latest_filings = get_latest_filings(ticker, missing_types)
            
            # Save 10-K if needed
            if "10-K" in latest_filings and not k_file_path:
                k_file_path = f"{data_folder}/10-K_{datetime.now().strftime('%Y%m%d')}.pdf"
                if save_filing_to_local(latest_filings["10-K"]["content"], k_file_path):
                    print(f"✅ Downloaded and saved 10-K: {k_file_path}")
                else:
                    print(f"❌ Failed to save 10-K for {ticker}")
                    return None, None
            
            # Save 10-Q if needed
            if "10-Q" in latest_filings and not q_file_path:
                q_file_path = f"{data_folder}/10-Q_{datetime.now().strftime('%Y%m%d')}.pdf"
                if save_filing_to_local(latest_filings["10-Q"]["content"], q_file_path):
                    print(f"✅ Downloaded and saved 10-Q: {q_file_path}")
                else:
                    print(f"⚠️ Warning: Failed to save 10-Q for {ticker}, continuing with 10-K only")
            
        except Exception as e:
            print(f"❌ Error downloading filings from SEC API: {e}")
            if not k_file_path:
                print(f"❌ Cannot proceed without 10-K filing for {ticker}")
                return None, None
    
    if k_file_path:
        print(f"📄 Using 10-K: {k_file_path}")
    if q_file_path:
        print(f"📄 Using 10-Q: {q_file_path}")
    else:
        print(f"⚠️ No 10-Q available for {ticker}")
    
    return k_file_path, q_file_path

def extract_text_from_pdf(file_path: str) -> str:
    """Extract text content from a PDF file using PyMuPDF"""
    
    text = ""
    try:
        full_path = os.path.join(ROOT, file_path)
        doc = fitz.open(full_path)
        total_pages = len(doc)
                
        for page_num in range(total_pages):
            text += doc[page_num].get_text()
        
        doc.close()
        print(f"✅ Successfully extracted text from {file_path}")
        return text
        
    except Exception as e:
        print(f"❌ Error extracting text from PDF {file_path}: {e}")
        return ""

def get_credit_risk_prompt() -> str:
    """Get the credit risk metrics prompt from YAML file"""
    yaml_file_path = os.path.join(ROOT, "utils", "credit_risk_metrics_prompt.yaml")
    
    try:
        with open(yaml_file_path, "r") as f:
            prompt_data = yaml.safe_load(f)
        
        # Get the prompt text (assuming it's stored under a 'prompt' key)
        if isinstance(prompt_data, dict):
            prompt = prompt_data.get("prompt", "") or prompt_data.get("credit_risk_prompt", "")
        else:
            prompt = str(prompt_data)
        
        if prompt:
            print(f"✅ Successfully loaded prompt: {yaml_file_path}")
        else:
            print(f"⚠️ Warning: Empty prompt loaded from {yaml_file_path}")
        
        return prompt
        
    except Exception as e:
        print(f"❌ Error reading prompt file {yaml_file_path}: {e}")
        return ""

def get_response_from_llm(pdf_text: str, ticker: str) -> Optional[str]:
    """Send PDF text to LLM and get credit risk metrics response"""
    
    # Load environment variables
    load_dotenv()
    
    # Get OpenAI credentials
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY must be set in the .env file")

    # Get prompt
    prompt = get_credit_risk_prompt()
    if not prompt:
        print("❌ Error: Could not load credit risk prompt")
        return None

    # Initialize OpenAI client
    client = OpenAI(
        api_key=openai_api_key,
    )

    try:
        # Create messages for the chat completion
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Here are the SEC filing documents for {ticker}:\n\n{pdf_text}"},
            {"role": "user", "content": f"Please analyze the credit risk metrics for {ticker} and return the response in the requested JSON format."}
        ]

        print(f"🤖 Making API call to OpenAI...")

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
        print(f"✅ Successfully received response from LLM")
        
        return content
        
    except Exception as e:
        print(f"❌ Error in LLM API call: {e}")
        return None

def parse_llm_response(content: str) -> Optional[str]:
    """Parse LLM response to extract JSON"""
    
    try:
        # Try to find JSON in the response
        if "```json" in content:
            json_part = content.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "{" in content and "}" in content:
            # Find the JSON object in the content
            start_idx = content.find("{")
            # Find the last closing brace
            end_idx = content.rfind("}") + 1
            if start_idx < end_idx:
                json_part = content[start_idx:end_idx].strip()
            else:
                print("❌ Could not find valid JSON structure in response")
                return None
        else:
            print("❌ No JSON found in LLM response")
            return None
        
        # Validate JSON
        try:
            parsed_json = json.loads(json_part)
            return json_part
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON in response: {e}")
            return None
        
    except Exception as e:
        print(f"❌ Error parsing LLM response: {e}")
        return None

def save_json_to_file(json_data: str, file_path: str) -> bool:
    """Save JSON data to local file"""
    try:
        # Ensure directory exists
        full_dir_path = os.path.dirname(os.path.join(ROOT, file_path))
        os.makedirs(full_dir_path, exist_ok=True)
        
        # Parse and re-format JSON for pretty printing
        parsed_json = json.loads(json_data)
        formatted_json = json.dumps(parsed_json, indent=2)
        
        # Write to file
        full_file_path = os.path.join(ROOT, file_path)
        with open(full_file_path, 'w') as f:
            f.write(formatted_json)
        
        print(f"💾 Saved JSON to: {file_path}")
        return True
        
    except Exception as e:
        print(f"❌ Error saving JSON file {file_path}: {e}")
        return False

def generate_credit_risk_metrics(ticker: str, write_files: bool = False, upload_to_azure: bool = False) -> Dict[str, Any]:
    """Generate credit risk metrics for a given ticker"""
    print(f"Starting credit risk analysis for {ticker}")
    
    # Configure environment
    configure_requests_for_corporate_environment()
    
    # Ensure directories exist
    ensure_directories_exist()
    
    # Define output file path
    json_output_path = f"output/json/credit_risk_analysis/{ticker}_CREDIT.json"
    
    # Check for cached results
    json_output_full_path = os.path.join(ROOT, json_output_path)
    if os.path.exists(json_output_full_path):
        print(f"📦 Found cached credit risk analysis for {ticker}, using existing file")
        try:
            with open(json_output_full_path, 'r') as f:
                cached_json_data = f.read()
            
            # Handle Azure upload if requested
            blob_url = None
            if upload_to_azure:
                blob_url = upload_to_azure_blob(cached_json_data, ticker)
            
            return {
                "ticker": ticker,
                "json_data": cached_json_data,
                "json_path": json_output_path if write_files else None,
                "blob_url": blob_url,
                "cached": True,
                "success": True
            }
        except Exception as e:
            print(f"❌ Error reading cached file: {e}")
            # Continue with fresh analysis
    
    # Get filings for the ticker
    k_file_path, q_file_path = get_filings_for_ticker(ticker)
    
    if not k_file_path:
        error_msg = f"❌ No 10-K filing found for {ticker}"
        print(error_msg)
        return {
            "ticker": ticker,
            "json_data": None,
            "json_path": None,
            "blob_url": None,
            "cached": False,
            "success": False,
            "error": error_msg
        }
    
    # Extract text from filings
    combined_text = ""
    
    # Process 10-K file
    print(f"📖 Processing 10-K filing...")
    k_text = extract_text_from_pdf(k_file_path)
    if k_text:
        combined_text += "\n\n=== 10-K FILING ===\n" + k_text + "\n\n"
    else:
        error_msg = f"❌ Failed to extract text from 10-K filing for {ticker}"
        print(error_msg)
        return {
            "ticker": ticker,
            "json_data": None,
            "json_path": None,
            "blob_url": None,
            "cached": False,
            "success": False,
            "error": error_msg
        }
    
    # Process 10-Q file if available
    if q_file_path:
        q_text = extract_text_from_pdf(q_file_path)
        if q_text:
            combined_text += "\n\n=== 10-Q FILING ===\n" + q_text
        else:
            print(f"⚠️ Warning: Failed to extract text from 10-Q filing, continuing with 10-K only")
    else:
        print(f"ℹ️ No 10-Q filing available, proceeding with 10-K only")
    
    # Get response from LLM
    llm_response = get_response_from_llm(combined_text, ticker)
    
    if not llm_response:
        error_msg = f"❌ Failed to get response from LLM for {ticker}"
        print(error_msg)
        return {
            "ticker": ticker,
            "json_data": None,
            "json_path": None,
            "blob_url": None,
            "cached": False,
            "success": False,
            "error": error_msg
        }
    
    # Parse LLM response
    json_data = parse_llm_response(llm_response)
    
    if not json_data:
        error_msg = f"❌ Failed to parse JSON from LLM response for {ticker}"
        print(error_msg)
        return {
            "ticker": ticker,
            "json_data": None,
            "json_path": None,
            "blob_url": None,
            "cached": False,
            "success": False,
            "error": error_msg
        }
    
    # Validate JSON structure
    try:
        parsed_json = json.loads(json_data)
        if "credit_risk_metrics" not in parsed_json:
            print(f"⚠️ Warning: 'credit_risk_metrics' key not found in response")
        else:
            credit_metrics = parsed_json["credit_risk_metrics"]
            if "key_credit_metrics" in credit_metrics and "key_credit_risks" in credit_metrics:
                print(f"✅ Valid credit risk metrics structure found")
            else:
                print(f"⚠️ Warning: Expected structure not found in credit_risk_metrics")
        
    except json.JSONDecodeError:
        print(f"⚠️ Warning: Could not validate JSON structure")
    
    # Save to local file if requested
    json_path = None
    if write_files:
        if save_json_to_file(json_data, json_output_path):
            json_path = json_output_path
        else:
            print(f"❌ Failed to save JSON file for {ticker}")
    
    # Upload to Azure if requested
    blob_url = None
    if upload_to_azure:
        blob_url = upload_to_azure_blob(json_data, ticker)
        
    return {
        "ticker": ticker,
        "json_data": json_data,
        "json_path": json_path,
        "blob_url": blob_url,
        "cached": False,
        "success": True
    }

def upload_to_azure_blob(json_data: str, ticker: str) -> Optional[str]:
    """Upload JSON data to Azure Blob Storage"""
    try:
        from utils.azure_blob_storage import upload_credit_risk_output
        
        # Parse JSON to ensure it's valid
        parsed_json = json.loads(json_data)
        
        # Upload using the azure_blob_storage utility
        container_name = "outputs"
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        blob_name = f"json/credit_risk_analysis/{ticker}_CREDIT.json"
        
        # Use the direct upload function
        from utils.azure_blob_storage import upload_json_to_blob_direct
        blob_url = upload_json_to_blob_direct(parsed_json, container_name, blob_name)
        
        print(f"Successfully uploaded to Azure Blob Storage: {blob_url}")
        return blob_url
        
    except ImportError:
        print(f"⚠️ Warning: azure_blob_storage module not available, skipping Azure upload")
        return None
    except Exception as e:
        print(f"❌ Error uploading to Azure Blob Storage: {e}")
        return None

if __name__ == "__main__":
    import argparse
    
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Generate credit risk metrics for a given ticker symbol')
    parser.add_argument('ticker', type=str, help='Ticker symbol of the company')
    parser.add_argument('--no-write', action='store_true', help='Do not write files to local storage')
    parser.add_argument('--upload-azure', action='store_true', help='Upload results to Azure Blob Storage')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Configure parameters
    write_files = not args.no_write
    upload_to_azure = args.upload_azure
    
    print(f"🎯 Generating credit risk metrics for {args.ticker}")
    
    # Generate credit risk metrics
    result = generate_credit_risk_metrics(
        ticker=args.ticker,
        write_files=write_files,
        upload_to_azure=upload_to_azure
    )
    
    if result["success"]:
        print(f"🎉 Credit risk analysis completed successfully!")
        if result["json_path"]:
            print(f"📄 JSON output: {result['json_path']}")
        if result["blob_url"]:
            print(f"☁️ Azure Blob URL: {result['blob_url']}")
        if result["cached"]:
            print(f"📦 Result was loaded from cache")
    else:
        print(f"💥 Credit risk analysis failed: {result.get('error', 'Unknown error')}")
        exit(1)