import yaml
import json
import os
import requests
import fitz # PyMuPDF
from typing import Dict, Any
from dotenv import load_dotenv
from openai import OpenAI
import re
import json

# Load environment variables from the .env file in the root directory
load_dotenv(dotenv_path=os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, '.env')))

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir, "data"))
PROCESSED_DATA_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir, "output", "json", "llm_input_processed"))
UTILS_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir, "utils"))
OUTPUT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir, "output", "json", "financial_analysis"))
# --- Helper Functions ---

def _read_prompt(file_path: str) -> str:
    """
    Reads the prompt template from a YAML file.

    Args:
        file_path: The path to the YAML file.

    Returns:
        The prompt string.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            return data.get('financial_statement_analysis', '')
    except FileNotFoundError:
        print(f"Error: Prompt file not found at '{file_path}'")
        return ""
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file '{file_path}': {e}")
        return ""

def _extract_text_from_pdf(folder_path: str) -> str:
    """
    Extracts and concatenates text from all PDF documents in a given folder.

    Args:
        folder_path: The path to the folder containing PDF files.

    Returns:
        The extracted text as a single string.
    """
    text_content = ""
    try:
        files = os.listdir(folder_path)
    except FileNotFoundError:
        print(f"Warning: PDF folder not found at '{folder_path}'. Skipping.")
        return "PDF documents not found."

    for file_name in files:
        if file_name.endswith('.pdf'):
            pdf_path = os.path.join(folder_path, file_name)
            try:
                document = fitz.open(pdf_path)
                for page_num in range(len(document)):
                    page = document.load_page(page_num)
                    text_content += page.get_text()
                document.close()
            except Exception as e:
                print(f"An error occurred while reading the PDF '{file_name}': {e}")
                text_content += f"Error extracting text from '{file_name}'."
    
    if not text_content:
        return "No PDF documents were found in the folder."
    
    return text_content

def _read_and_format_json(folder_path: str, ticker: str) -> str:
    """
    Reads all JSON files in a given folder and formats their content
    into a single string, prefixed with the file name.

    Args:
        folder_path: The path to the folder containing JSON files.
        ticker: The company's stock ticker (used to filter files).

    Returns:
        A formatted string containing all financial statements.
    """
    all_content = ""
    try:
        files = os.listdir(folder_path)
    except FileNotFoundError:
        print(f"Warning: JSON folder not found at '{folder_path}'. Skipping.")
        return "No financial statements were found."

    for file_name in files:
        if file_name.startswith(f'{ticker}_') and file_name.endswith('.json'):
            file_path = os.path.join(folder_path, file_name)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # Use the file name as a section title
                    section_name = file_name.replace(f'{ticker}_', '').replace('.json', '').replace('_', ' ').title()
                    all_content += f"#### {section_name}\n"
                    all_content += "```json\n"
                    all_content += json.dumps(data, indent=2)
                    all_content += "\n```\n\n"
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON from '{file_path}': {e}. Skipping.")
    
    if not all_content:
        return "No financial statements were found."
    
    return "### Financial Statements in JSON Format\n\n" + all_content

# --- Main Function ---

def analyze_ticker(ticker: str) -> dict:
    """
    Performs a Financial Statement Analysis using Azure OpenAI.
    It combines a prompt, PDF text, and JSON financial statements
    to send to the gpt-4.1 model.

    Args:
        ticker: The stock ticker of the company to analyze.

    Returns:
        dict: A dictionary containing the 'text_result' (raw LLM response 
              or error message) and 'saved_path' (path to the saved JSON file 
              or None if saving failed).
    """

    # --- Configuration ---
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    OPENAI_MODEL = "gpt-4o"  # Using GPT-4o for OpenAI

    # Construct paths based on the new structure (assuming constants are available)
    try:
        PROMPT_FILE_PATH = os.path.join(UTILS_DIR, 'fsa_prompt.yaml')
        DOC_FOLDER = os.path.join(DATA_DIR, ticker)
        FINANCIAL_DATA_FOLDER = os.path.join(PROCESSED_DATA_DIR, ticker)
    except NameError:
        return {
            "text_result": "Error: Required constants (UTILS_DIR, DATA_DIR, PROCESSED_DATA_DIR) are not defined.",
            "saved_path": None
        }

    # Check for missing environment variables
    if not openai_api_key:
        return {
            "text_result": "❌ Error: OPENAI_API_KEY not found in .env file.",
            "saved_path": None
        }

    # Initialize the OpenAI client
    client = OpenAI(
        api_key=openai_api_key,
    )
    
    # --- Prepare Context ---
    # 1. Read prompt from YAML
    prompt_template = _read_prompt(PROMPT_FILE_PATH)
    if not prompt_template:
        return {
            "text_result": "Failed to load the prompt template. Aborting.",
            "saved_path": None
        }

    # 2. Extract text from PDF
    pdf_text = _extract_text_from_pdf(DOC_FOLDER)

    # 3. Read and format JSON financial statements
    json_text = _read_and_format_json(FINANCIAL_DATA_FOLDER, ticker)

    
    # --- Construct Final Prompt ---
    final_prompt = prompt_template.format(
        Company = ticker, 
        financial_statements=json_text,
        documents=pdf_text
    )

    try:
        print("Sending request to OpenAI...")
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": final_prompt}],
            model=OPENAI_MODEL,
            max_tokens=8192,
            temperature=0.0,  # Set to 0.0 for deterministic financial analysis
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        )
        analysis_result = chat_completion.choices[0].message.content
        saved_path = None
        cleaned_data = clean_and_convert_to_json(analysis_result)
        
        if cleaned_data:
            # Construct the desired file name
            file_name = f"{ticker}_FSA.json"
            # The save_json_file function is assumed to return the file path or None
            saved_path = save_json_file(cleaned_data, file_name, OUTPUT_DIR)
            
            return {
                "text_result": analysis_result,
                "saved_path": saved_path
            }
        else:
            # If LLM response was received but could not be parsed/saved as JSON
            return {
                "text_result": "❌ Failed to generate and save a valid JSON analysis.",
                "saved_path": None
            }

    except Exception as e:
        print(f"❌ An error occurred while calling the LLM API: {e}")
        return {
            "text_result": f"❌ An error occurred while calling the LLM API: {e}",
            "saved_path": None
        }


def clean_and_convert_to_json(llm_output_text: str):
    """
    Cleans the raw text from the LLM to extract a valid JSON string,
    then converts it into a Python dictionary.

    Args:
        llm_output_text (str): The raw text output from the LLM.

    Returns:
        dict: A Python dictionary representing the cleaned JSON data.
        None: If a valid JSON object cannot be found or parsed.
    """
    # Use a regex to find a valid JSON object, including markdown code blocks
    # This pattern looks for the first '{' and the last '}'
    match = re.search(r'```json\s*(\{[\s\S]*\})\s*```|(\{[\s\S]*\})', llm_output_text, re.DOTALL)
    
    if match:
        json_string = match.group(1) or match.group(2)
        try:
            # Parse the cleaned string into a Python dictionary
            json_data = json.loads(json_string)
            return json_data
        except json.JSONDecodeError as e:
            print(f"❌ JSON decoding failed: {e}")
            return None
    else:
        print("❌ No valid JSON object found in the LLM output.")
        return None
    

import json
import os

def save_json_file(json_data: dict, file_name: str, output_dir: str):
    """
    Saves a Python dictionary as a pretty-printed JSON file.

    Args:
        json_data (dict): The Python dictionary to save.
        file_name (str): The name of the file to save (e.g., "ELME_FSA.json").
        output_dir (str): The absolute path to the directory where the file
                          should be saved.
    
    Returns:
        str: The full path to the saved file if successful, otherwise None.
    """
    # Create the output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"✅ Created directory: {output_dir}")

    # Construct the full file path
    file_path = os.path.join(output_dir, file_name)

    try:
        # Use json.dump() to write the dictionary to the file
        # The 'indent=4' parameter makes the file human-readable
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=4)
        print(f"✅ Successfully saved JSON to: {file_path}")
        return file_path
    except Exception as e:
        print(f"❌ An error occurred while saving the JSON file: {e}")
        return None
    


# --- Example Usage ---
# --- Example Usage ---
if __name__ == '__main__':
    # NOTE: You will need to create the folders and files below for this example to run.
    # The folders 'documents' and 'financial_statements/AAPL' must exist.
    # Place your example PDF and JSON files in the corresponding paths.

    # Example setup:
    # 1. Create a folder 'data/{ticker}' and place '{ticker}_10k_10q.pdf' inside.
    # 2. Create a folder 'output/json/llm_input_processed/{ticker}'
    # 3. Place '{ticker}_income_statement.json', '{ticker}_balance_sheet.json', and '{ticker}_cash_flow.json' inside the '{ticker}' folder.
    # 4. Create the 'fsa_prompt.yaml' file in the 'utils' folder.
    # 5. Create a .env file with your API keys.

    TICKER = input("Please enter the ticker: ")
    
    # 1. Call the function and get the returned dictionary
    analysis_result_dict = analyze_ticker(TICKER)
    
    # 2. Extract results
    analysis_result = analysis_result_dict["text_result"]
    saved_path = analysis_result_dict["saved_path"]
    
    print("\n--- FSA Analysis Result ---")
    print(analysis_result)
    
    if saved_path:
        print(f"\n✅ Analysis JSON saved to: {saved_path}")
    elif analysis_result.startswith("❌"):
        print("\n❌ Analysis failed. See error message above.")
    else:
        print("\n⚠️ Analysis completed, but no structured JSON was saved.")

