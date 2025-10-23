import os
import glob
import json
import re
import yaml
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional

# LangChain/Vector Store dependencies
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

# OpenAI for final generation
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()

# --- Configuration & Path Setup ---
# Assuming this script lives in utils/
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..', '..'))

VECTOR_STORE_DIR = os.path.join(root_dir, 'utils', 'vector_store')
CHAT_MEMORY_DIR = os.path.join(root_dir, 'utils', 'chat')
JSON_DATA_DIR = os.path.join(root_dir, 'output', 'json', 'llm_input_processed')
PROMPT_FILE = os.path.join(root_dir, 'utils', 'odi_prompt.yaml')

# OpenAI Configuration
EMBEDDING_MODEL = "text-embedding-3-small"  # Using OpenAI's embedding model
CHAT_MODEL = "gpt-4o"  # Using GPT-4o for chat

# --- Utility Functions for JSON Parsing (Copied for self-containment) ---

def extract_text_from_json(data: Any) -> str:
    """
    Recursively extracts all text from a dictionary or list, ensuring
    parent keys are included to maintain context in the text representation.
    """
    text_content = ""
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                nested_content = extract_text_from_json(value)
                if nested_content.strip():
                    text_content += f"--- {key} ---\n"
                    text_content += nested_content
                    text_content += f"--- End {key} ---\n\n"
            elif isinstance(value, (str, int, float)):
                text_content += f"{key}: {value}\n"
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                text_content += extract_text_from_json(item)
            elif isinstance(item, (str, int, float)):
                text_content += f"{item}\n"
    return text_content

def extract_ticker_from_query(query: str) -> Optional[str]:
    """
    Attempts to extract a 2-4 letter uppercase ticker from the query.
    This is useful for filtering when the ticker isn't explicitly passed.
    """
    # Look for 2 to 4 uppercase letters, possibly at the start or surrounded by spaces/punctuation
    match = re.search(r'\b([A-Z]{2,4})\b', query)
    return match.group(1) if match else None

# --- Memory Management ---

def load_chat_history(ticker: str) -> List[Dict[str, str]]:
    """Loads chat history for a given ticker from a JSON file."""
    os.makedirs(CHAT_MEMORY_DIR, exist_ok=True)
    history_file = os.path.join(CHAT_MEMORY_DIR, f"{ticker.upper()}.json")
    
    if not os.path.exists(history_file):
        return []
    
    with open(history_file, 'r') as f:
        return json.load(f)

def save_chat_history(ticker: str, history: List[Dict[str, str]]):
    """Saves the updated chat history for a given ticker."""
    history_file = os.path.join(CHAT_MEMORY_DIR, f"{ticker.upper()}.json")
    with open(history_file, 'w') as f:
        json.dump(history, f, indent=2)

def format_chat_history(history: List[Dict[str, str]]) -> str:
    """Formats the history list into a readable string for the LLM prompt."""
    formatted_history = ""
    for entry in history:
        formatted_history += f"[{entry['role'].upper()}]: {entry['content']}\n"
    return formatted_history

# --- Data Loading and Retrieval ---

def load_financial_statements_json(ticker: str) -> str:
    """
    Loads all financial JSON files for the given ticker, converts them to text,
    and returns a single, concatenated string.
    """
    json_dir = os.path.join(JSON_DATA_DIR, ticker.upper())
    all_text = []

    if not os.path.exists(json_dir):
        print(f"Warning: JSON data directory not found for ticker: {ticker}")
        return ""

    json_files = glob.glob(os.path.join(json_dir, '*.json'))
    
    for file_path in json_files:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            file_name = os.path.basename(file_path)
            # Add file context header
            text_content = f"----- BEGIN FILE: {file_name} -----\n"
            text_content += extract_text_from_json(data)
            text_content += f"----- END FILE: {file_name} -----\n\n"
            all_text.append(text_content)

        except Exception as e:
            print(f"Error loading or processing JSON file {file_path}: {e}")
            continue

    return "\n".join(all_text)

def get_rag_context(query: str, ticker: str, k: int = 5) -> str:
    """
    Performs a filtered similarity search on the local FAISS index.
    """
    faiss_index_path = os.path.join(VECTOR_STORE_DIR)
    
    if not os.path.exists(faiss_index_path):
        print("❌ Error: FAISS index not found. Please run document_processor.py first.")
        return "RAG_ERROR: FAISS index missing."

    try:
        # Initialize embeddings client for the query
        embeddings_client = OpenAIEmbeddings(
            api_key=os.getenv("OPENAI_API_KEY"),
            model=EMBEDDING_MODEL
        )
        
        # Load the local FAISS index
        vector_db = FAISS.load_local(faiss_index_path, embeddings_client, allow_dangerous_deserialization=True)
        
        # Define the filter to restrict search to the specific ticker
        filter_dict = {"ticker": ticker.upper()}
        
        # Perform filtered similarity search
        results_with_scores = vector_db.similarity_search_with_score(
            query=query, 
            k=k, 
            filter=filter_dict
        )

        context_chunks = []
        for doc, score in results_with_scores:
            # Format the metadata and content for the LLM
            metadata_str = f"Source Ticker: {doc.metadata.get('ticker', 'N/A')}, Report: {doc.metadata.get('report_type', 'N/A')}, Fiscal Period: {doc.metadata.get('fiscal_period', 'N/A')}"
            context_chunks.append(f"[Chunk Score: {score:.4f}, {metadata_str}]\n{doc.page_content}")
            
        return "\n\n---\n\n".join(context_chunks)

    except Exception as e:
        print(f"❌ Error during RAG context retrieval: {e}")
        return f"RAG_ERROR: {e}"


# --- Main Chat Function ---

def chat(user_query: str, company_ticker: str) -> str:
    """
    Main function to process a user query using RAG and LLM generation.
    """
    company_ticker = company_ticker.upper()
    print(f"\nProcessing query for {company_ticker}...")
    
    # 1. Load Resources and History
    try:
        # Load prompt template
        with open(PROMPT_FILE, 'r') as f:
            prompt_template = yaml.safe_load(f)['system_prompt']
        
        # Load memory
        chat_history = load_chat_history(company_ticker)
        formatted_history = format_chat_history(chat_history)

        # Load raw JSON data (for LLM verification/detailed lookup)
        financial_statements_json = load_financial_statements_json(company_ticker)

    except Exception as e:
        return f"System Error: Failed to load required resources (prompt/history/json). Error: {e}"

    # 2. RAG Retrieval
    relevant_context = get_rag_context(user_query, company_ticker, k=5)
    
    if "RAG_ERROR" in relevant_context:
        return relevant_context # Return error message directly

    # 3. Format Final Prompt
    final_prompt = prompt_template.format(
        company_ticker=company_ticker,
        relevant_context_from_rag=relevant_context,
        financial_statements_json=financial_statements_json,
        chat_history=formatted_history,
        user_query=user_query
    )
    
    # 4. LLM Generation
    try:
        openai_client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
        )
        
        # We send the system prompt, followed by the user's current query
        messages = [
            {"role": "system", "content": final_prompt},
            {"role": "user", "content": user_query}
        ]
        
        response = openai_client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            temperature=0.0 # Keep temperature low for factual financial analysis
        )
        
        llm_response = response.choices[0].message.content
        
        # 5. Update and Save History
        chat_history.append({"role": "user", "content": user_query})
        chat_history.append({"role": "assistant", "content": llm_response})
        save_chat_history(company_ticker, chat_history)

        return llm_response

    except Exception as e:
        return f"❌ LLM API Error: Failed to generate response from OpenAI. Error: {e}"

if __name__ == "__main__":
    # --- Example Usage ---
    
    # NOTE: Before running, ensure:
    # 1. Your .env file is set up with Azure OpenAI credentials (ENDPOINT, API_KEY, DEPLOYMENT NAMES).
    # 2. The FAISS index 'faiss_index.faiss' exists in utils/vector_store.
    # 3. Financial statements JSON files exist in output/json/llm_input_processed/ELME (or whichever ticker you use).

    try:
        # Example 1: Initial query
        query1 = "What have been the drivers behind revenue growth/decline in the past fiscal year and LTM period?"
        ticker1 = "ELME" # Must match a ticker in your data
        
        print("-" * 50)
        print(f"Query: {query1} | Ticker: {ticker1}")
        response1 = chat(query1, ticker1)
        print("\n--- LLM RESPONSE ---")
        print(response1)
        print("-" * 50)
        
        # # Example 2: Follow-up query leveraging chat history (if successful)
        # query2 = "Compared to that value, what was the value in the previous year?"
        # ticker2 = "ELME"
        
        # print("-" * 50)
        # print(f"Query: {query2} | Ticker: {ticker2}")
        # response2 = chat(query2, ticker2)
        # print("\n--- LLM RESPONSE ---")
        # print(response2)
        # print("-" * 50)
        
    except Exception as e:
        print(f"\nFatal error during execution: {e}")
