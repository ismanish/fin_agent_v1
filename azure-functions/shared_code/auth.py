"""
Azure Authentication Module for PGIM Dealio Azure Functions.

This module provides authentication utilities for Azure services using Service Principal.
"""

import os
from typing import Optional, Union

from azure.identity import ClientSecretCredential, DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient

def get_credential() -> Union[ClientSecretCredential, DefaultAzureCredential]:
    """
    Get Azure credential for authentication.
    
    Returns:
        ClientSecretCredential if Service Principal credentials are available,
        otherwise DefaultAzureCredential which tries various authentication methods.
    """
    client_id = os.environ.get("AZURE_CLIENT_ID")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET")
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    
    if client_id and client_secret and tenant_id:
        return ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )
    else:
        # Fall back to DefaultAzureCredential which tries multiple authentication methods
        # This will use environment variables, managed identity, or developer tools
        return DefaultAzureCredential()

def get_blob_service_client(account_name: Optional[str] = None) -> BlobServiceClient:
    """
    Get a BlobServiceClient using Service Principal authentication.
    
    Args:
        account_name: Storage account name. If None, uses AZURE_STORAGE_ACCOUNT env var.
        
    Returns:
        BlobServiceClient instance
    """
    # First try connection string if available (for backward compatibility)
    connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if connection_string:
        return BlobServiceClient.from_connection_string(connection_string)
    
    # Otherwise use Service Principal auth
    # Default to pgimdealio which is the existing storage account in PGIM-Dealio resource group
    storage_account = account_name or os.environ.get("AZURE_STORAGE_ACCOUNT", "pgimdealio")
    credential = get_credential()
    account_url = f"https://{storage_account}.blob.core.windows.net"
    
    return BlobServiceClient(account_url=account_url, credential=credential)

def get_table_service_client(account_name: Optional[str] = None) -> TableServiceClient:
    """
    Get a TableServiceClient using Service Principal authentication.
    
    Args:
        account_name: Storage account name. If None, uses AZURE_STORAGE_ACCOUNT env var.
        
    Returns:
        TableServiceClient instance
    """
    # First try connection string if available (for backward compatibility)
    for key in ("AZURE_TABLES_CONNECTION_STRING", "AZURE_STORAGE_CONNECTION_STRING", "AZURE_TABLE_CONNECTION_STRING"):
        conn = os.environ.get(key)
        if conn:
            return TableServiceClient.from_connection_string(conn)
    
    # Otherwise use Service Principal auth
    # Default to pgimdealio which is the existing storage account in PGIM-Dealio resource group
    storage_account = account_name or os.environ.get("AZURE_STORAGE_ACCOUNT", "pgimdealio")
    credential = get_credential()
    account_url = f"https://{storage_account}.table.core.windows.net"
    
    return TableServiceClient(endpoint=account_url, credential=credential)

def get_azure_openai_client():
    """
    Get an Azure OpenAI client using Service Principal authentication.
    
    Returns:
        AzureOpenAI client instance
    """
    try:
        from openai import AzureOpenAI
    except ImportError:
        raise ImportError("OpenAI package is not installed. Install with: pip install openai")
    
    # First try API key if available (for backward compatibility)
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    # Default to the existing Azure OpenAI endpoint
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "https://pgim-dealio.cognitiveservices.azure.com/")
    
    if api_key:
        return AzureOpenAI(
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            azure_endpoint=endpoint,
            api_key=api_key,
        )
    
    # Otherwise use Service Principal auth
    credential = get_credential()
    return AzureOpenAI(
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        azure_endpoint=endpoint,
        azure_ad_token_provider=credential.get_token,
    )
