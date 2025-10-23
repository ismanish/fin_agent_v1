"""
HFA service for Azure Functions independent of src/.
Provides read-only access to the latest HFA outputs stored in Blob Storage.
Container: hfa-outputs
Blob pattern: {ticker}/HFA_{ticker}_YYYYMMDD_HHMMSS.json and .csv
"""
from __future__ import annotations
import json
from typing import Optional, Dict, Any
from datetime import datetime

from .blob_utils import get_container_client


def get_latest_hfa_from_blob(ticker: str) -> Optional[Dict[str, Any]]:
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return None

    container = 'hfa-outputs'
    prefix = f"{ticker}/HFA_{ticker}_"
    cc = get_container_client(container)

    latest_name_json = None
    latest_time = None

    try:
        for blob in cc.list_blobs(name_starts_with=f"{ticker}/"):
            name = blob.name
            if not name.lower().endswith('.json'):
                continue
            if not name.startswith(prefix):
                continue
            lm = blob.last_modified
            if latest_time is None or (lm and lm > latest_time):
                latest_time = lm
                latest_name_json = name

        if not latest_name_json:
            return None

        # Download JSON
        json_client = cc.get_blob_client(latest_name_json)
        json_text = json_client.download_blob().readall().decode('utf-8')
        rows = json.loads(json_text)

        # Find matching CSV by timestamp
        ts_part = latest_name_json.rsplit('_', 1)[-1].split('.')[0]  # YYYYMMDD_HHMMSS
        csv_name = f"{ticker}/HFA_{ticker}_{ts_part}.csv"
        csv_url = None
        try:
            if cc.get_blob_client(csv_name).exists():
                csv_url = cc.get_blob_client(csv_name).url
        except Exception:
            pass

        return {
            'ticker': ticker,
            'rows': rows,
            'blob_urls': {
                'json_url': json_client.url,
                'csv_url': csv_url,
            },
            'cached': True,
        }
    except Exception:
        return None
