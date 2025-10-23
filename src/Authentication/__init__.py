# Authentication package
# Expose key functions for convenience
from .data_append import (
    register_user,
    authenticate_user,
    get_user,
    change_password,
    is_allowed_domain,
)

from .azure_auth import (
    get_credential,
    get_blob_service_client,
    get_table_service_client,
    get_resource_client,
    get_web_client,
    get_azure_openai_client,
)

__all__ = [
    # User authentication
    "register_user",
    "authenticate_user",
    "get_user",
    "change_password",
    "is_allowed_domain",
    
    # Azure authentication
    "get_credential",
    "get_blob_service_client",
    "get_table_service_client",
    "get_resource_client",
    "get_web_client",
    "get_azure_openai_client",
]
