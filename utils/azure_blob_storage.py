"""
Simple Azure Blob Storage utility module for PGIM Dealio.
This module provides basic functions to upload files to Azure Blob Storage.
"""
import os
import json
from datetime import datetime
from azure.storage.blob import BlobServiceClient
from typing import Optional, Dict, List

def upload_file_to_blob(file_path, container_name, blob_name=None):
    """
    Upload a file to Azure Blob Storage.
    
    Args:
        file_path: Path to the file to upload
        container_name: Name of the container to upload to
        blob_name: Name of the blob (file in Azure). If None, uses the file name
        
    Returns:
        URL of the uploaded blob
    """
    # Get connection string from environment variable
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING environment variable not set")
    
    # Create the BlobServiceClient
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    
    # Get a reference to the container
    container_client = blob_service_client.get_container_client(container_name)
    
    # Create the container if it doesn't exist
    try:
        container_client.get_container_properties()
    except Exception:
        container_client.create_container()
    
    # If blob_name is not provided, use the file name
    if blob_name is None:
        blob_name = os.path.basename(file_path)
    
    # Get a reference to the blob
    blob_client = container_client.get_blob_client(blob_name)
    
    # Upload the file
    with open(file_path, "rb") as data:
        blob_client.upload_blob(data, overwrite=True)
    
    # Return the URL of the blob
    return blob_client.url

def upload_json_to_blob(data, container_name, blob_name):
    """
    Upload JSON data to Azure Blob Storage.
    
    Args:
        data: Dictionary to be serialized as JSON
        container_name: Name of the container to upload to
        blob_name: Name of the blob (file in Azure)
        
    Returns:
        URL of the uploaded blob
    """
    # Get connection string from environment variable
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING environment variable not set")
    
    # Create the BlobServiceClient
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    
    # Get a reference to the container
    container_client = blob_service_client.get_container_client(container_name)
    
    # Create the container if it doesn't exist
    try:
        container_client.get_container_properties()
    except Exception:
        container_client.create_container()
    
    # Get a reference to the blob
    blob_client = container_client.get_blob_client(blob_name)
    
    # Convert data to JSON string
    json_data = json.dumps(data, indent=2)
    
    # Upload the JSON string
    blob_client.upload_blob(json_data, overwrite=True)
    
    # Return the URL of the blob
    return blob_client.url

def upload_hfa_output(ticker, json_path, csv_path=None, log_path=None):
    """
    Upload HFA output files to Azure Blob Storage.
    Args:
        ticker: Company ticker symbol
        json_path: Path to the JSON file
        csv_path: Path to the CSV file (optional)
        log_path: Path to the log file (optional)
    Returns:
        Dictionary with URLs of uploaded blobs
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    container_name = "hfa-outputs"
    result = {}
    
    # Upload JSON file
    if json_path and os.path.exists(json_path):
        json_blob_name = f"{ticker}/HFA_{ticker}_{timestamp}.json"
        json_url = upload_file_to_blob(json_path, container_name, json_blob_name)
        result["json_url"] = json_url
    
    # Upload CSV file if provided
    if csv_path and os.path.exists(csv_path):
        csv_blob_name = f"{ticker}/HFA_{ticker}_{timestamp}.csv"
        csv_url = upload_file_to_blob(csv_path, container_name, csv_blob_name)
        result["csv_url"] = csv_url
    
    # Upload log file if provided
    if log_path and os.path.exists(log_path):
        log_container_name = "logs"
        log_blob_name = f"HFA/HFA_{ticker}_{timestamp}.json"
        log_url = upload_file_to_blob(log_path, log_container_name, log_blob_name)
        result["log_url"] = log_url
    
    return result

def upload_json_to_blob_direct(data, container_name, blob_name):
    """
    Upload JSON data directly to Azure Blob Storage without local file.
    Args:
        data: Dictionary to be serialized as JSON
        container_name: Name of the container to upload to
        blob_name: Name of the blob (file in Azure)
    Returns:
        URL of the uploaded blob
    """
    # Get connection string from environment variable
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING environment variable not set")
    
    # Create the BlobServiceClient
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    
    # Get a reference to the container
    container_client = blob_service_client.get_container_client(container_name)
    
    # Create the container if it doesn't exist
    try:
        container_client.get_container_properties()
    except Exception:
        container_client.create_container()
    
    # Get a reference to the blob
    blob_client = container_client.get_blob_client(blob_name)
    
    # Convert data to JSON string
    json_data = json.dumps(data, indent=2)
    
    # Upload the JSON string
    blob_client.upload_blob(json_data, overwrite=True)
    
    # Return the URL of the blob
    return blob_client.url

def upload_csv_to_blob_direct(rows, container_name, blob_name):
    """
    Upload CSV data directly to Azure Blob Storage without local file.
    Args:
        rows: List of dictionaries representing CSV rows
        container_name: Name of the container to upload to
        blob_name: Name of the blob (file in Azure)
    Returns:
        URL of the uploaded blob
    """
    # Get connection string from environment variable
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING environment variable not set")
    
    # Create the BlobServiceClient
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    
    # Get a reference to the container
    container_client = blob_service_client.get_container_client(container_name)
    
    # Create the container if it doesn't exist
    try:
        container_client.get_container_properties()
    except Exception:
        container_client.create_container()
    
    # Get a reference to the blob
    blob_client = container_client.get_blob_client(blob_name)
    
    # Convert rows to CSV string
    if not rows:
        csv_data = ""
    else:
        import io
        import csv
        output = io.StringIO()
        fieldnames = list(rows[0].keys()) if rows else []
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        csv_data = output.getvalue()
        output.close()
    
    # Upload the CSV string
    blob_client.upload_blob(csv_data, overwrite=True)
    
    # Return the URL of the blob
    return blob_client.url

def upload_comp_output(ticker, json_path, csv_path=None, log_path=None):
    """
    Upload COMP output files to Azure Blob Storage.
    
    Args:
        ticker: Company ticker symbol
        json_path: Path to the JSON file
        csv_path: Path to the CSV file (optional)
        log_path: Path to the log file (optional)
        
    Returns:
        Dictionary with URLs of uploaded blobs
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    container_name = "comp-outputs"
    
    result = {}
    
    # Upload JSON file
    if json_path and os.path.exists(json_path):
        json_blob_name = f"{ticker}/COMP_{ticker}_{timestamp}.json"
        json_url = upload_file_to_blob(json_path, container_name, json_blob_name)
        result["json_url"] = json_url
    
    # Upload CSV file if provided
    if csv_path and os.path.exists(csv_path):
        csv_blob_name = f"{ticker}/COMP_{ticker}_{timestamp}.csv"
        csv_url = upload_file_to_blob(csv_path, container_name, csv_blob_name)
        result["csv_url"] = csv_url
    
    # Upload log file if provided
    if log_path and os.path.exists(log_path):
        log_container_name = "logs"
        log_blob_name = f"COMP/COMP_{ticker}_{timestamp}.json"
        log_url = upload_file_to_blob(log_path, log_container_name, log_blob_name)
        result["log_url"] = log_url
    
    return result

def upload_cap_output(ticker, json_path, csv_path=None, log_path=None):
    """
    Upload CAP table output files to Azure Blob Storage.
    
    Args:
        ticker: Company ticker symbol
        json_path: Path to the JSON file
        csv_path: Path to the CSV file (optional)
        log_path: Path to the log file (optional)
        
    Returns:
        Dictionary with URLs of uploaded blobs
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    container_name = "cap-outputs"
    
    result = {}
    
    # Upload JSON file
    if json_path and os.path.exists(json_path):
        json_blob_name = f"{ticker}/CAP_{ticker}_{timestamp}.json"
        json_url = upload_file_to_blob(json_path, container_name, json_blob_name)
        result["json_url"] = json_url
    
    # Upload CSV file if provided
    if csv_path and os.path.exists(csv_path):
        csv_blob_name = f"{ticker}/CAP_{ticker}_{timestamp}.csv"
        csv_url = upload_file_to_blob(csv_path, container_name, csv_blob_name)
        result["csv_url"] = csv_url
    
    # Upload log file if provided
    if log_path and os.path.exists(log_path):
        log_container_name = "logs"
        log_blob_name = f"CAP/CAP_{ticker}_{timestamp}.json"
        log_url = upload_file_to_blob(log_path, log_container_name, log_blob_name)
        result["log_url"] = log_url
    
    return result

def download_blob_content(container_name: str, blob_name: str) -> Optional[Dict]:
    """
    Download a JSON blob from Azure Blob Storage and return as dictionary.
    """
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING environment variable not set")
    
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(container_name)
    blob_client = container_client.get_blob_client(blob_name)
    
    try:
        downloader = blob_client.download_blob()
        content = downloader.readall()
        return json.loads(content)
    except Exception:
        return None

def list_blobs(container_name: str, prefix: str = "") -> List[str]:
    """
    List all blobs in a container optionally filtered by prefix.
    Returns list of blob names.
    """
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING environment variable not set")
    
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(container_name)
    
    return [b.name for b in container_client.list_blobs(name_starts_with=prefix)]


def upload_credit_risk_output(ticker, json_data=None, json_path=None):
    """
    Upload Credit Risk output files to Azure Blob Storage.
    
    Args:
        ticker: Company ticker symbol
        json_data: JSON data as string (optional if json_path provided)
        json_path: Path to the JSON file (optional if json_data provided)
        
    Returns:
        Dictionary with URL of uploaded blob
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    container_name = "outputs"
    
    result = {}
    
    # Upload JSON file
    if json_data:
        # Upload JSON data directly
        json_blob_name = f"json/credit_risk_analysis/{ticker}_CREDIT.json"
        json_url = upload_json_to_blob_direct(json.loads(json_data), container_name, json_blob_name)
        result["json_url"] = json_url
    elif json_path and os.path.exists(json_path):
        # Upload from file
        json_blob_name = f"json/credit_risk_analysis/{ticker}_CREDIT.json"
        json_url = upload_file_to_blob(json_path, container_name, json_blob_name)
        result["json_url"] = json_url
    
    return result