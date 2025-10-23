import os
import glob
import json
import time
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from typing import List, Optional # Added Optional import

# Load environment variables from .env file
load_dotenv()

# --- Path Configuration ---
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..', '..'))

DATA_PDF_DIR = os.path.join(root_dir, 'data')
DATA_JSON_DIR = os.path.join(root_dir, 'output', 'json', 'llm_input_processed')
VECTOR_STORE_DIR = os.path.join(root_dir, 'utils', 'vector_store')

# --- Embedding and Splitter Configuration ---
EMBEDDING_MODEL = "text-embedding-3-small"  # Using OpenAI's embedding model
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
BATCH_SIZE = 100 # Batch size for embedding API calls

def get_pdf_metadata_from_path(file_path):
    """
    Parses the file path to extract ticker, report type, and fiscal period for PDF files.
    Assumes the format: .../data/<ticker>/<report_type>_<fiscal_period>.pdf
    """
    path_parts = file_path.split(os.sep)
    try:
        ticker = path_parts[-2]
        filename = path_parts[-1]
        name_parts = os.path.splitext(filename)[0].split('_')
        report_type = name_parts[0]
        fiscal_period = name_parts[1]
        return {"ticker": ticker, "report_type": report_type, "fiscal_period": fiscal_period}
    except (IndexError, AttributeError) as e:
        print(f"Warning: Could not extract metadata from PDF path: {file_path}. Error: {e}")
        return {}
    
def get_json_metadata_from_path(file_path):
    """
    Parses the file path to extract metadata for JSON files.
    Assumes the format: .../llm_input_processed/<ticker>/<ticker>_<report-type>_<fiscal-period-in-year>_<quarter>.json
    """
    path_parts = file_path.split(os.sep)
    try:
        ticker_dir = path_parts[-2]
        filename = os.path.splitext(path_parts[-1])[0]
        name_parts = filename.split('_')
        
        if name_parts[0] != ticker_dir:
            raise ValueError("Ticker in filename does not match directory name.")

        ticker = name_parts[0]
        report_type = name_parts[1]
        fiscal_period = name_parts[2]
        quarter = name_parts[3]

        return {
            "ticker": ticker,
            "report_type": report_type,
            "fiscal_period": fiscal_period,
            "quarter": quarter
        }
    except (IndexError, ValueError, AttributeError) as e:
        print(f"Warning: Could not extract metadata from JSON path: {file_path}. Error: {e}")
        return {}

def extract_text_from_json(data):
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
        for i, item in enumerate(data):
            if isinstance(item, (dict, list)):
                text_content += extract_text_from_json(item)
            elif isinstance(item, (str, int, float)):
                text_content += f"{item}\n"
    return text_content


def process_documents(new_files_only: bool = False):
    """
    Loads, chunks, embeds, and indexes documents from both PDF and JSON sources
    into a single FAISS vector store. Can append to an existing index.
    """
    print("Starting document processing and indexing...")
    
    # --- Debugging Environment Variables ---
    print("\n--- Debugging Environment Variables ---")
    print(f"OPENAI_API_KEY: {'Set' if os.getenv('OPENAI_API_KEY') else 'Not set'}")
    print(f"EMBEDDING_MODEL: {EMBEDDING_MODEL}")
    print("---------------------------------------\n")

    if not os.getenv('OPENAI_API_KEY'):
        print("❌ Error: The 'OPENAI_API_KEY' environment variable is not set.")
        return

    # Initialize the OpenAIEmbeddings client
    try:
        embeddings_client = OpenAIEmbeddings(
            api_key=os.getenv("OPENAI_API_KEY"),
            model=EMBEDDING_MODEL
        )
    except Exception as e:
        print(f"Error initializing OpenAIEmbeddings client. Error: {e}")
        return

    # Check and create the vector store directory
    if not os.path.exists(VECTOR_STORE_DIR):
        os.makedirs(VECTOR_STORE_DIR)
        print(f"Created directory: {VECTOR_STORE_DIR}")

    # Initialize text splitter
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len
    )
    
    all_chunks: List[Document] = []
    
    # --- Process PDF Files ---
    print("Processing PDF files...")
    all_pdf_paths = glob.glob(os.path.join(DATA_PDF_DIR, '*', '*.pdf'))
    if not all_pdf_paths:
        print(f"No PDF files found in {DATA_PDF_DIR}")

    for pdf_path in all_pdf_paths:
        file_name = os.path.basename(pdf_path)
        try:
            print(f" - Loading PDF: {file_name}")
            loader = PyPDFLoader(pdf_path)
            documents = loader.load()

            metadata = get_pdf_metadata_from_path(pdf_path)
            for doc in documents:
                doc.metadata.update(metadata)

            chunks = text_splitter.split_documents(documents)
            all_chunks.extend(chunks)
            print(f"   - Split into {len(chunks)} chunks.")
        except Exception as e:
            print(f"   - Error processing {file_name}: {e}")

    # --- Process JSON Files ---
    print("\nProcessing JSON files...")
    all_json_paths = glob.glob(os.path.join(DATA_JSON_DIR, '*', '*.json'))
    if not all_json_paths:
        print(f"No JSON files found in {DATA_JSON_DIR}")

    for json_path in all_json_paths:
        file_name = os.path.basename(json_path)
        try:
            print(f" - Loading JSON: {file_name}")
            with open(json_path, 'r') as f:
                data = json.load(f)

            text_content = extract_text_from_json(data)

            if not text_content.strip():
                print(f"   - Warning: No text content found in JSON for {file_name}. Skipping.")
                continue

            metadata = get_json_metadata_from_path(json_path)
            document = Document(page_content=text_content, metadata=metadata)
            
            chunks = text_splitter.split_documents([document])
            all_chunks.extend(chunks)
            print(f"   - Split into {len(chunks)} chunks.")
        except Exception as e:
            print(f"   - Error processing {file_name}: {e}")

    # --- Create or Append to FAISS Index ---
    if not all_chunks:
        print("\nNo new documents found to process. Exiting.")
        return

    faiss_index_path = os.path.join(VECTOR_STORE_DIR, 'faiss_index.faiss')
    vector_db: Optional[FAISS] = None
    operation_type = "Creating"
    
    # 1. Check for and Load Existing Index
    if os.path.exists(faiss_index_path):
        try:
            print(f"\nLoading existing index from {faiss_index_path}...")
            # Load the existing index using the same embeddings client
            vector_db = FAISS.load_local(
                folder_path=VECTOR_STORE_DIR, 
                embeddings=embeddings_client, 
                index_name='faiss_index', 
                allow_dangerous_deserialization=True
            )
            operation_type = "Appending to"
            print(f"Index loaded successfully. {vector_db.index.ntotal} chunks already present. Adding {len(all_chunks)} new chunks.")
        except Exception as e:
            error_message = str(e)
            
            # Specific check for permission-related errors
            if "Permission denied" in error_message or "could not open" in error_message:
                 print(f"❌ Error loading existing index due to file access issues: {e}")
                 print("ACTION REQUIRED: The index file is likely locked by another process (e.g., another script instance, antivirus) or you lack read/write permissions.")
                 print("Please ensure the existing index file is not in use, adjust permissions, or delete the index files to force a full recreation.")
            else:
                 print(f"❌ Unhandled error loading existing index: {e}")
            
            print("Will attempt to create a BRAND NEW index (overwriting old data, assuming write permission is available for the directory).")
            vector_db = None
            
    print(f"\n{operation_type} FAISS index with {len(all_chunks)} new chunks...")

    retries = 0
    max_retries = 5
    
    # Split all new chunks into smaller batches
    chunk_batches = [all_chunks[i:i + BATCH_SIZE] for i in range(0, len(all_chunks), BATCH_SIZE)]
    
    # 2. Process Batches (Create or Append)
    while retries < max_retries:
        try:
            for batch_index, batch in enumerate(chunk_batches):
                print(f"Embedding batch {batch_index + 1}/{len(chunk_batches)}...")
                
                if vector_db is None:
                    # Case 1: New Index Creation (Only runs for the very first batch)
                    vector_db = FAISS.from_documents(batch, embeddings_client)
                else:
                    # Case 2: Appending to Existing Index (or subsequent batches of a new index)
                    vector_db.add_documents(batch)
                
                # Pause between batches to respect rate limits
                time.sleep(5) 

            # 3. Save the Updated Index
            if vector_db:
                vector_db.save_local(VECTOR_STORE_DIR, 'faiss_index')
                print(f"✅ Index update complete. Saved {operation_type.lower()} index to {faiss_index_path}")
                print(f"Total chunks in index: {vector_db.index.ntotal}")
                break # Exit the loop on success
            else:
                print("❌ No documents were successfully processed to create or update the vector store.")
                break

        except Exception as e:
            error_message = str(e)
            if '429' in error_message or 'rate limit' in error_message.lower():
                retries += 1
                wait_time = 60 * retries
                print(f"❌ Rate limit exceeded. Retrying in {wait_time} seconds... (Attempt {retries}/{max_retries})")
                time.sleep(wait_time)
            else:
                print(f"❌ Unhandled error during indexing: {e}")
                break # Exit the loop on unhandled error
    
    if retries == max_retries:
        print("❌ Max retries reached. Could not create or update the unified index.")

    
if __name__ == "__main__":
    process_documents()
