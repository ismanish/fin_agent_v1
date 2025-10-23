"""
Azure Authentication Module for PGIM Dealio.

This module provides authentication utilities for Azure services using Service Principal.
It supports authentication for various Azure services including:
- Azure Functions
- Azure Blob Storage
- Azure Tables
- Azure OpenAI

Configuration (environment variables):
- AZURE_CLIENT_ID: Service Principal client/app ID
- AZURE_CLIENT_SECRET: Service Principal password/secret
- AZURE_TENANT_ID: Azure Active Directory tenant ID
- AZURE_SUBSCRIPTION_ID: Azure subscription ID

Usage example:
    from Authentication.azure_auth import get_credential, get_blob_service_client
    
    # Get default credential
    credential = get_credential()
    
    # Get blob service client
    blob_service_client = get_blob_service_client()
"""

import os
from typing import Optional, Dict, Any, Union

from azure.identity import ClientSecretCredential, DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.web import WebSiteManagementClient

from dotenv import load_dotenv

# Load environment variables from a local .env if present
load_dotenv(override=False)

def get_credential() -> Union[ClientSecretCredential, DefaultAzureCredential]:
    """
    Get Azure credential for authentication.
    
    Returns:
        ClientSecretCredential if Service Principal credentials are available,
        otherwise DefaultAzureCredential which tries various authentication methods.
    """
    client_id = os.getenv("AZURE_CLIENT_ID")
    client_secret = os.getenv("AZURE_CLIENT_SECRET")
    tenant_id = os.getenv("AZURE_TENANT_ID")
    
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
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if connection_string:
        return BlobServiceClient.from_connection_string(connection_string)
    
    # Otherwise use Service Principal auth
    storage_account = account_name or os.getenv("AZURE_STORAGE_ACCOUNT", "pgimdealio")
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
        conn = os.getenv(key)
        if conn:
            return TableServiceClient.from_connection_string(conn)
    
    # Otherwise use Service Principal auth
    storage_account = account_name or os.getenv("AZURE_STORAGE_ACCOUNT", "pgimdealio")
    credential = get_credential()
    account_url = f"https://{storage_account}.table.core.windows.net"
    
    return TableServiceClient(endpoint=account_url, credential=credential)

def get_resource_client() -> ResourceManagementClient:
    """
    Get a ResourceManagementClient for managing Azure resources.
    
    Returns:
        ResourceManagementClient instance
    """
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
    if not subscription_id:
        raise ValueError("AZURE_SUBSCRIPTION_ID environment variable not set")
    
    credential = get_credential()
    return ResourceManagementClient(credential, subscription_id)

def get_web_client() -> WebSiteManagementClient:
    """
    Get a WebSiteManagementClient for managing Azure Web Apps and Functions.
    
    Returns:
        WebSiteManagementClient instance
    """
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
    if not subscription_id:
        raise ValueError("AZURE_SUBSCRIPTION_ID environment variable not set")
    
    credential = get_credential()
    return WebSiteManagementClient(credential, subscription_id)

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
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "https://pgim-dealio.cognitiveservices.azure.com/")
    
    if api_key:
        return AzureOpenAI(
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            azure_endpoint=endpoint,
            api_key=api_key,
        )
    
    # Otherwise use Service Principal auth
    credential = get_credential()
    return AzureOpenAI(
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        azure_endpoint=endpoint,
        azure_ad_token_provider=credential.get_token,
    )

__all__ = [
    "get_credential",
    "get_blob_service_client",
    "get_table_service_client",
    "get_resource_client",
    "get_web_client",
    "get_azure_openai_client",
]
