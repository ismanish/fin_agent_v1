"""Authentication utilities backed by Azure Table Storage.

This module provides:

- Domain-restricted user registration that appends a new row to an Azure Table.
- Secure password storage using bcrypt hashing (salted; salt embedded in the hash).
- Username/password authentication by verifying bcrypt hashes.

Configuration (environment variables):
- Preferred (any one of the following credential options):
  1) AZURE_TABLES_CONNECTION_STRING or AZURE_STORAGE_CONNECTION_STRING
     Example: DefaultEndpointsProtocol=...;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net
  2) AZURE_TABLE_ACCOUNT_URL + AZURE_TABLE_SAS_TOKEN
     Example: AZURE_TABLE_ACCOUNT_URL=https://<account>.table.core.windows.net
              AZURE_TABLE_SAS_TOKEN=?sv=... (full SAS token string starting with '?')
  3) AZURE_TABLE_ACCOUNT_NAME + AZURE_TABLE_ACCOUNT_KEY
     Example: AZURE_TABLE_ACCOUNT_NAME=pgimdealio
              AZURE_TABLE_ACCOUNT_KEY=<key>
- Optional: AZURE_TABLE_NAME (default: "Authentication").

Allowed email domains (default): {"gramener.com", "straive.com", "pgim.com"}

Usage example:
    from Authentication.data_append import register_user, authenticate_user

    # Register (append a new row)
    ok, msg = register_user("alice@pgim.com", "StrongP@ssw0rd")
    print(ok, msg)

    # Authenticate
    ok, msg = authenticate_user("alice@pgim.com", "StrongP@ssw0rd")
    print(ok, msg)
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional, Tuple

import bcrypt
from azure.data.tables import TableServiceClient, UpdateMode
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError, HttpResponseError
from dotenv import load_dotenv
from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential

from .azure_auth import get_table_service_client


# Load environment variables from a local .env if present
load_dotenv(override=False)

# Defaults
DEFAULT_ALLOWED_DOMAINS = {"gramener.com", "straive.com", "pgim.com"}
DEFAULT_TABLE_NAME = os.getenv("AZURE_TABLE_NAME", "Authentication")


def _get_table_service_client() -> TableServiceClient:
    """Resolve TableServiceClient using Service Principal or connection string.
    
    This function is a wrapper around the get_table_service_client function from azure_auth module.
    It's kept for backward compatibility with existing code.
    """
    return get_table_service_client()


def _get_table_client(table_name: Optional[str] = None):
    """Get a TableClient, creating the table if it does not exist."""
    table_name = (table_name or DEFAULT_TABLE_NAME).strip()
    if not table_name:
        raise ValueError("table_name cannot be empty")

    svc = _get_table_service_client()
    # Ensure table exists
    try:
        # Prefer create_table_if_not_exists if available; fall back to create_table
        create_if = getattr(svc, "create_table_if_not_exists", None)
        if callable(create_if):
            create_if(table_name=table_name)
        else:
            try:
                svc.create_table(table_name=table_name)
            except ResourceExistsError:
                pass
    except HttpResponseError as exc:
        # If there's a race condition or insufficient permissions, surface a clear message
        raise RuntimeError(f"Failed to ensure table '{table_name}' exists: {exc}") from exc

    return svc.get_table_client(table_name)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _extract_domain(email: str) -> str:
    try:
        return _normalize_email(email).rsplit("@", 1)[1]
    except Exception as exc:
        raise ValueError("Invalid email format") from exc


def is_allowed_domain(email: str, allowed_domains: Optional[Iterable[str]] = None) -> bool:
    """Check if the email belongs to one of the allowed domains."""
    allowed = set(allowed_domains or DEFAULT_ALLOWED_DOMAINS)
    domain = _extract_domain(email)
    return domain in allowed


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _filter_entity_props(props: Optional[Dict]) -> Dict:
    """Filter/flatten extra props to Azure Table allowed types.

    Azure Tables supports: str, int, float, bool, datetime, bytes (and Edm types).
    We will include only primitives and datetime/bytes, and stringify unknowns.
    """
    if not props:
        return {}
    allowed_types = (str, int, float, bool, datetime, bytes)
    filtered = {}
    for k, v in props.items():
        if isinstance(v, allowed_types):
            filtered[k] = v
        else:
            filtered[k] = str(v)
    return filtered


def register_user(
    email: str,
    password: str,
    *,
    table_name: Optional[str] = None,
    allowed_domains: Optional[Iterable[str]] = None,
    metadata: Optional[Dict] = None,
    overwrite: bool = False,
) -> Tuple[bool, str]:
    """Append a new user row with a bcrypt-hashed password.

    Returns (ok, message).
    - ok=True when a row is created (or replaced if overwrite=True).
    - ok=False when the user exists and overwrite=False, or on validation errors.
    """
    if not email or not _EMAIL_RE.match(email.strip()):
        return False, "Invalid email format"

    email_n = _normalize_email(email)
    domain = _extract_domain(email_n)

    if not is_allowed_domain(email_n, allowed_domains):
        return False, f"Registration restricted to domains: {sorted(set(allowed_domains or DEFAULT_ALLOWED_DOMAINS))}"

    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters"

    # Hash password (salt included)
    try:
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    except Exception as exc:
        return False, f"Failed to hash password: {exc}"

    entity = {
        "PartitionKey": domain,
        "RowKey": email_n,
        "email": email_n,
        "domain": domain,
        "password_hash": hashed,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    entity.update(_filter_entity_props(metadata))

    tc = _get_table_client(table_name)

    if overwrite:
        # Upsert (replace) to ensure we write the latest hash
        try:
            tc.upsert_entity(entity=entity, mode=UpdateMode.REPLACE)
            return True, "User created/updated successfully"
        except HttpResponseError as exc:
            return False, f"Failed to upsert user: {exc}"

    # Create only, fail if exists
    try:
        tc.create_entity(entity=entity)
        return True, "User registered successfully"
    except ResourceExistsError:
        return False, "User already exists"
    except HttpResponseError as exc:
        return False, f"Failed to create user: {exc}"


def authenticate_user(
    email: str,
    password: str,
    *,
    table_name: Optional[str] = None,
) -> Tuple[bool, str]:
    """Verify a user exists and the password matches the stored bcrypt hash."""
    if not email or not password:
        return False, "Email and password are required"

    email_n = _normalize_email(email)
    domain = _extract_domain(email_n)

    tc = _get_table_client(table_name)
    try:
        ent = tc.get_entity(partition_key=domain, row_key=email_n)
    except ResourceNotFoundError:
        return False, "User not found"
    except HttpResponseError as exc:
        return False, f"Failed to fetch user: {exc}"

    stored_hash = ent.get("password_hash")
    if not stored_hash:
        return False, "No password is set for this user"

    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except Exception as exc:
        return False, f"Failed to verify password: {exc}"

    if not ok:
        return False, "Invalid credentials"

    # Optionally update last_login_at (best-effort)
    try:
        ent["last_login_at"] = _now_iso()
        tc.upsert_entity(entity=ent, mode=UpdateMode.MERGE)
    except Exception:
        pass

    return True, "Authenticated"


def get_user(email: str, *, table_name: Optional[str] = None) -> Optional[Dict]:
    """Fetch a user entity by email. Returns None if not found."""
    email_n = _normalize_email(email)
    domain = _extract_domain(email_n)
    tc = _get_table_client(table_name)
    try:
        return dict(tc.get_entity(partition_key=domain, row_key=email_n))
    except ResourceNotFoundError:
        return None


def change_password(
    email: str,
    old_password: str,
    new_password: str,
    *,
    table_name: Optional[str] = None,
) -> Tuple[bool, str]:
    """Change an existing user's password after verifying the old one."""
    ok, msg = authenticate_user(email, old_password, table_name=table_name)
    if not ok:
        return False, msg

    if not new_password or len(new_password) < 8:
        return False, "New password must be at least 8 characters"

    email_n = _normalize_email(email)
    domain = _extract_domain(email_n)
    tc = _get_table_client(table_name)

    # Re-hash with a new salt
    try:
        new_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    except Exception as exc:
        return False, f"Failed to hash new password: {exc}"

    # Partial merge update
    patch = {
        "PartitionKey": domain,
        "RowKey": email_n,
        "password_hash": new_hash,
        "updated_at": _now_iso(),
    }
    try:
        tc.upsert_entity(entity=patch, mode=UpdateMode.MERGE)
        return True, "Password updated"
    except HttpResponseError as exc:
        return False, f"Failed to update password: {exc}"


__all__ = [
    "register_user",
    "authenticate_user",
    "get_user",
    "change_password",
    "is_allowed_domain",
]

