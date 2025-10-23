"""
CAP (Capitalization) Table Azure Function.
This function generates a capitalization table for a given ticker.
"""
import json
import logging
import os
import azure.functions as func

# Add parent directory to path to import shared code modules
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if parent_dir not in os.sys.path:
    os.sys.path.append(parent_dir)

# Import shared code modules
from shared_code.logging_wrapper import init_logging_wrapper, restore_original_print
from shared_code.logging_to_blob import setup_blob_logging
from shared_code.cap_builder import build_cap_table

def main(req: func.HttpRequest) -> func.HttpResponse:
    # Set up blob logging
    logger = setup_blob_logging("CapTableFunction")
    logger.info('Python HTTP trigger function processed a request for CAP Table.')
    
    # Initialize logging wrapper to handle print statements
    init_logging_wrapper()

    try:
        # Parse request body
        req_body = req.get_json()
        ticker = req_body.get('ticker')

        if not ticker:
            return func.HttpResponse(
                json.dumps({"error": "Please provide a ticker parameter"}),
                status_code=400,
                mimetype="application/json"
            )

        ticker = ticker.strip().upper()
        
        # Build CAP table (self-contained; uploads JSON/CSV to Blob Storage)
        result = build_cap_table(ticker)
        
        try:
            parsed_json = json.loads(result["json_data"]) if isinstance(result.get("json_data"), str) else result.get("json_data")
            blob_urls = result.get("blob_urls", {})
            
            # Convert absolute paths to relative paths or filenames only
            csv_filename = ""
            json_filename = ""
            
            return func.HttpResponse(
                json.dumps({
                    "status": "ok",
                    "ticker": result["ticker"],
                    "filename_csv": csv_filename,
                    "filename_json": json_filename,
                    "json_data": parsed_json,
                    "blob_urls": blob_urls,
                    "cached": result.get("cached", False)
                }),
                mimetype="application/json"
            )
        except Exception as e:
            # Return raw JSON string with an error hint instead of 500
            csv_filename = ""
            json_filename = ""
            
            return func.HttpResponse(
                json.dumps({
                    "status": "warning",
                    "ticker": result.get("ticker"),
                    "filename_csv": csv_filename,
                    "filename_json": json_filename,
                    "json_data_raw": result.get("json_data"),
                    "json_error": f"Failed to parse JSON: {e}",
                }),
                mimetype="application/json"
            )
    except Exception as e:
        logger.error(f"Error processing CAP Table request: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
    finally:
        # Restore original print function
        restore_original_print()
        # Flush logs to blob storage
        for handler in logger.handlers:
            handler.flush()

def upload_cap_output(ticker, json_path, csv_path=None):
    """
    Upload CAP table output files to Azure Blob Storage.
    
    Args:
        ticker: Company ticker symbol
        json_path: Path to the JSON file
        csv_path: Path to the CSV file (optional)
        
    Returns:
        Dictionary with URLs of uploaded blobs
    """
    from datetime import datetime
    import os
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    container_name = "cap-outputs"
    
    result = {}
    
    # Get blob service client
    blob_service_client = get_blob_service_client()
    
    # Get a reference to the container
    container_client = blob_service_client.get_container_client(container_name)
    
    # Create the container if it doesn't exist
    try:
        container_client.get_container_properties()
    except Exception:
        container_client.create_container()
    
    # Upload JSON file
    if json_path and os.path.exists(json_path):
        json_blob_name = f"{ticker}/cap_{ticker}_{timestamp}.json"
        blob_client = container_client.get_blob_client(json_blob_name)
        
        with open(json_path, "rb") as data:
            blob_client.upload_blob(data, overwrite=True)
        
        result["json_url"] = blob_client.url
    
    # Upload CSV file if provided
    if csv_path and os.path.exists(csv_path):
        csv_blob_name = f"{ticker}/cap_{ticker}_{timestamp}.csv"
        blob_client = container_client.get_blob_client(csv_blob_name)
        
        with open(csv_path, "rb") as data:
            blob_client.upload_blob(data, overwrite=True)
        
        result["csv_url"] = blob_client.url
    
    return result

def load_cached_cap_output(ticker, logger=None):
    """
    Load cached CAP table output from disk under output/json/cap_table and output/csv/cap_table.
    Returns a result dict compatible with build_cap_table output, or None if not found.
    """
    try:
        # parent_dir points to the project root (one level above azure-functions/)
        json_path = os.path.join(parent_dir, "output", "json", "cap_table", f"{ticker}_CAP.json")
        csv_path = os.path.join(parent_dir, "output", "csv", "cap_table", f"{ticker}_CAP.csv")
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                json_data = f.read()
            if logger:
                logger.info("Using cached CAP table output from disk.")
            result = {
                "ticker": ticker,
                "json_data": json_data,
                "json_path": json_path,
                "cached": True,
            }
            if os.path.exists(csv_path):
                result["csv_path"] = csv_path
            return result
        else:
            if logger:
                logger.warning("No cached CAP table output found on disk.")
            return None
    except Exception as e:
        if logger:
            logger.error(f"Cached fallback failed: {e}")
        return None
