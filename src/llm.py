import os
import json
import yaml
import re
from typing import Dict, Any, List, Optional
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from the .env file in the root directory
load_dotenv(dotenv_path=os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, '.env')))

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir, "static"))
PROCESSED_DATA_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir, "output", "json", "llm_input_processed"))
UTILS_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir, "utils"))

# --- Utility Functions ---

def load_yaml(filepath: str) -> Dict[str, Any]:
    """Loads a YAML file and returns its content as a dictionary."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"❌ Error: The file {filepath} was not found.")
        return {}
    except yaml.YAMLError as e:
        print(f"❌ Error parsing YAML file {filepath}: {e}")
        return {}

def get_combined_json_data(ticker: str, year: int, filing_type: str) -> str:
    """
    Constructs the path to the combined JSON file and loads its content as a string.
    For 10-K filings, it looks for the combined file format.
    For 10-Q filings, it automatically finds the most recent quarter for the given year.
    """
    ticker_dir = os.path.join(PROCESSED_DATA_DIR, ticker.upper())
    
    if not os.path.isdir(ticker_dir):
        print(f"❌ Error: Ticker directory not found at {ticker_dir}")
        return ""

    if filing_type.upper() == "10-K":
        # Find the combined 10-K file. The year parameter can be the end year.
        pattern = re.compile(rf"^{re.escape(ticker)}_10-K_\d+-{year}_combined\.json$", re.IGNORECASE)
        
        filepath = None
        for file in os.listdir(ticker_dir):
            if pattern.match(file):
                filepath = os.path.join(ticker_dir, file)
                break
        
        if not filepath:
            print(f"❌ Error: Combined 10-K filing not found for {ticker} ending in year {year}.")
            return ""
            
    elif filing_type.upper() == "10-Q":
        # Find the latest 10-Q file for the given year
        latest_file = None
        latest_quarter_num = 0
        
        pattern = re.compile(rf"^{re.escape(ticker)}_10-Q_{year}_Q(\d+)\.json$", re.IGNORECASE)
        
        for file in os.listdir(ticker_dir):
            match = pattern.match(file)
            if match:
                quarter_num = int(match.group(1))
                if quarter_num > latest_quarter_num:
                    latest_quarter_num = quarter_num
                    latest_file = file
        
        if latest_file:
            filepath = os.path.join(ticker_dir, latest_file)
        else:
            print(f"❌ Error: No 10-Q filing found for {ticker} in year {year}.")
            return ""
            
    else:
        print(f"❌ Error: Unsupported filing type '{filing_type}'.")
        return ""

    if not os.path.exists(filepath):
        print(f"❌ Error: Processed JSON file not found at {filepath}")
        return ""
    
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        return json.dumps(data, indent=2)


def get_aqrr_keys(filepath: str) -> List[str]:
    """
    Loads AQRR keys from a YAML file and returns them as a list.
    """
    data = load_yaml(filepath)
    return data.get("aqrr_keys", [])


def save_llm_response_to_file(response_content: str, output_dir: str, ticker: str, filing_type: str) -> None:
    """
    Saves the LLM's JSON response to a file, appending to the existing data.
    Ensures the output format is `Company_ticker: { 10k: [], 10q: []}`.
    """
    filename = "mapping_calculation.json"
    output_path = os.path.join(output_dir, filename)
    
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        response_data = json.loads(response_content)
        
        mappings_data = {}
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            with open(output_path, "r", encoding="utf-8") as f:
                mappings_data = json.load(f)
            if not isinstance(mappings_data, dict):
                print(f"⚠️ Warning: Existing file at {output_path} is not a dictionary. Overwriting.")
                mappings_data = {}

        if ticker not in mappings_data:
            mappings_data[ticker] = {"10-K": [], "10-Q": []}
            
        # Ensure the response data is a list of dictionaries as expected
        if not isinstance(response_data, list):
            print(f"❌ Error: LLM response is not a list. Skipping save.")
            return

        # Appends the new response to the list for the correct filing type
        if filing_type.upper() == "10-K":
            mappings_data[ticker]["10-K"].append(response_data)
        elif filing_type.upper() == "10-Q":
            mappings_data[ticker]["10-Q"].append(response_data)
        else:
            print(f"❌ Unknown filing type: {filing_type}. Skipping save.")
            return

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(mappings_data, f, indent=2)
        print(f"✅ Successfully saved LLM response to {output_path}")

    except json.JSONDecodeError:
        print(f"❌ Failed to parse LLM response as JSON. Saving as plain text.")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(response_content)
    except Exception as e:
        print(f"❌ An error occurred while saving the file: {e}")

def check_cache_and_get_response(ticker: str, filing_type: str, aqrr_keys_to_check: List[str]) -> Optional[str]:
    """
    Checks if a complete, valid response for the given ticker and filing type exists in the cache.
    Returns the cached response content as a JSON string if a cache hit occurs, otherwise returns None.
    """
    cache_path = os.path.join(UTILS_DIR, "mapping_calculation.json")
    
    if not os.path.exists(cache_path) or os.path.getsize(cache_path) == 0:
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            mappings_data = json.load(f)

        if ticker not in mappings_data or filing_type not in mappings_data[ticker] or not mappings_data[ticker][filing_type]:
            return None

        # Get the most recent cached response list
        cached_response_list = mappings_data[ticker][filing_type][-1]
        
        # Check if the retrieved item is a list
        if not isinstance(cached_response_list, list):
            print(f"⚠️ Warning: Cached item for {ticker} {filing_type} is not a list. Invalid cache entry.")
            return None

        all_cached_keys = set()
        for item in cached_response_list:
            if isinstance(item, dict) and "aqrr_key" in item:
                all_cached_keys.add(item["aqrr_key"])

        # Check if all required AQRR keys from the schema are a subset of the cached keys
        if set(aqrr_keys_to_check).issubset(all_cached_keys):
            print("✅ Cache hit! All AQRR keys found in the latest response. Skipping LLM call.")
            return json.dumps(cached_response_list, indent=2)

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"⚠️ Cache read failed or invalid format ({e}). Proceeding with LLM call.")
        return None
    
    print("❌ Cache miss. Data is incomplete or not found. Proceeding with LLM call.")
    return None

def get_llm_response(prompt_template: str, combined_json: str, aqrr_keys_str: str) -> str:
    """
    Populates the prompt template and sends the request to the LLM.
    """
    if not combined_json or not aqrr_keys_str:
        return "Missing required data to send to LLM."
        
    populated_prompt = prompt_template.format(
        aqrr_keys=aqrr_keys_str,
        combined_json=combined_json
    )
    
    # --- OpenAI Client Setup ---
    openai_api_key = os.environ.get("OPENAI_API_KEY")

    if not openai_api_key:
        return "❌ Error: OPENAI_API_KEY not found in .env file."

    client = OpenAI(
        api_key=openai_api_key,
    )

    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": populated_prompt}],
            model="gpt-4o",  # Using GPT-4o model for OpenAI
            max_tokens=8192,  # Adjusted for regular OpenAI
            temperature=0.0,  # Set to 0.0 for deterministic financial calculations
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"❌ An error occurred while calling the LLM API: {e}"

if __name__ == "__main__":
    try:
        # Prompt for inputs
        in_ticker = input("Enter ticker (e.g., ELME): ").strip().upper()
        in_year = input("Enter year (e.g., 2024): ").strip()
        in_type = input('Enter filing type ("10-K" or "10-Q"): ').strip().upper().replace(" ", "")

        if not in_ticker or not in_year or not in_type:
            print("Error: ticker, year, and filing type are required.")
            raise SystemExit(1)

        try:
            year = int(in_year)
        except ValueError:
            print("Error: year must be a 4-digit number, e.g., 2024.")
            raise SystemExit(1)

        if in_type in ("10K", "10-K"):
            filing_type = "10-K"
        elif in_type in ("10Q", "10-Q"):
            filing_type = "10-Q"
        else:
            print('Error: filing type must be "10-K" or "10-Q".')
            raise SystemExit(1)

        ticker = in_ticker

        aqrr_keys_list = get_aqrr_keys(os.path.join(STATIC_DIR, "aqrr_key_schema.yaml"))

        llm_response_content = check_cache_and_get_response(ticker, filing_type, aqrr_keys_list)

        if llm_response_content is None:
            combined_json_string = get_combined_json_data(ticker, year, filing_type)
            if combined_json_string:
                aqrr_keys_string = json.dumps(aqrr_keys_list, indent=2)
                prompt_data = load_yaml(os.path.join(UTILS_DIR, "prompt.yaml"))
                prompt_template = prompt_data.get("calculate_aqrr_keys", "")

                print("\n--- Sending request to LLM ---")
                llm_response_content = get_llm_response(prompt_template, combined_json_string, aqrr_keys_string)

                if "Error:" not in llm_response_content:
                    save_llm_response_to_file(llm_response_content, UTILS_DIR, ticker, filing_type)

        print("\n--- Final Response Content ---")
        print(llm_response_content)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")