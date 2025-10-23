"""
HFA (Historical Financial Analysis) Azure Function - Simplified for Diagnostics.
This is a simplified version to diagnose the 500 error.
"""
import logging
import json
import azure.functions as func
import os

# Add parent directory to path to import shared code modules
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if parent_dir not in os.sys.path:
    os.sys.path.append(parent_dir)

# Import shared code modules
from shared_code.logging_to_blob import setup_blob_logging
from shared_code.logging_wrapper import init_logging_wrapper, restore_original_print
from shared_code.hfa_service import get_latest_hfa_from_blob

def main(req: func.HttpRequest) -> func.HttpResponse:
    # Set up blob logging
    logger = setup_blob_logging("HFAFunction")
    logger.info('Python HTTP trigger function processed a request.')
    
    # Initialize logging wrapper to handle print statements
    init_logging_wrapper()

    try:
        # Parse request body
        req_body = req.get_json()
        ticker = (req_body.get('ticker') or '').strip().upper()
        filing = (req_body.get('filing') or '10-K').strip().upper()

        if not ticker:
            return func.HttpResponse(
                json.dumps({"error": "Please provide a ticker parameter"}),
                status_code=400,
                mimetype="application/json"
            )

        # Serve HFA outputs from Blob Storage (no src dependency)
        result = get_latest_hfa_from_blob(ticker)
        if not result:
            return func.HttpResponse(
                json.dumps({
                    "status": "not_found",
                    "error": "No HFA output found in Blob Storage for this ticker.",
                    "ticker": ticker
                }),
                status_code=404,
                mimetype="application/json"
            )

        # Blob URLs are provided by the service if available
        blob_urls = result.get("blob_urls", {})

        # Convert absolute paths to filenames for response usability
        csv_filename = ""
        json_filename = ""

        return func.HttpResponse(
            json.dumps({
                "status": "ok",
                "ticker": result.get("ticker", ticker),
                "filing": result.get("filing", filing),
                "filename_csv": csv_filename,
                "filename_json": json_filename,
                "blob_urls": blob_urls,
                "rows": result.get("rows", []),
                "cached": result.get("cached", False)
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"Error processing HFA request: {str(e)}")
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
