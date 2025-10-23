"""
Blob utilities for Azure Functions.
Uses AZURE_STORAGE_CONNECTION_STRING if present, otherwise falls back to auth.get_blob_service_client.
"""
from __future__ import annotations
import os
from typing import Optional, Tuple

from .auth import get_blob_service_client


def get_container_client(container: str):
    bsc = get_blob_service_client()
    cc = bsc.get_container_client(container)
    try:
        cc.get_container_properties()
    except Exception:
        cc.create_container()
    return cc


def upload_text(container: str, blob_name: str, text: str, content_type: str = "application/json") -> str:
    cc = get_container_client(container)
    bc = cc.get_blob_client(blob_name)
    bc.upload_blob(text.encode("utf-8"), overwrite=True, content_type=content_type)
    return bc.url


def upload_bytes(container: str, blob_name: str, data: bytes, content_type: Optional[str] = None) -> str:
    cc = get_container_client(container)
    bc = cc.get_blob_client(blob_name)
    bc.upload_blob(data, overwrite=True, content_type=content_type)
    return bc.url


def download_text(container: str, blob_name: str) -> Optional[str]:
    try:
        cc = get_container_client(container)
        bc = cc.get_blob_client(blob_name)
        stream = bc.download_blob()
        return stream.readall().decode("utf-8")
    except Exception:
        return None


def exists(container: str, blob_name: str) -> bool:
    try:
        cc = get_container_client(container)
        bc = cc.get_blob_client(blob_name)
        return bc.exists()
    except Exception:
        return False
