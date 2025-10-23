"""
Self-contained CAP table builder for Azure Functions, independent of src/.
- Fetches latest 10-K and (optionally) 10-Q PDFs via SEC API
- Extracts text with PyMuPDF
- Calls Azure OpenAI to produce CAP JSON
- Computes additional fields and derives a CSV
- Uploads JSON/CSV to Azure Blob Storage (container: cap-outputs)
- Provides cached fallback by loading the latest JSON from blob
"""
from __future__ import annotations
import os
import io
import json
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

import fitz  # PyMuPDF
from sec_api import QueryApi, PdfGeneratorApi

from .auth import get_azure_openai_client
from .blob_utils import get_container_client, upload_text


def _get_env(name: str, required: bool = True, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(name, default)
    if required and not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


def _get_sec_clients() -> Tuple[QueryApi, PdfGeneratorApi]:
    api_key = _get_env("SEC_API_KEY")
    return QueryApi(api_key=api_key), PdfGeneratorApi(api_key=api_key)


def _get_prompt(ticker: str) -> str:
    # Keep it simple and self-contained; you can move this into blob or settings later
    base = (
        "You are a financial analyst. Extract and synthesize the latest capital structure "
        "from the company's SEC filings. Return a single JSON object with fields like "
        "cash_and_equivalents, debt[], total_debt, book_value_of_equity, market_value_of_equity, "
        "ltm_adj_ebitda, key_financial_ratios, debt_footnotes, as_of, company."
    )
    return f"{base}\nTicker: {ticker}"


def _extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    text = ""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                text += page.get_text()
    except Exception:
        pass
    return text


def _get_latest_filings_pdf_bytes(ticker: str) -> Dict[str, bytes]:
    query_api, pdf_api = _get_sec_clients()
    out: Dict[str, bytes] = {}
    for ftype in ("10-K", "10-Q"):
        query = {
            "query": {"query_string": {"query": f"ticker:{ticker} AND formType:\"{ftype}\" AND NOT formType:\"{ftype}/A\""}},
            "from": "0",
            "size": "1",
            "sort": [{"filedAt": {"order": "desc"}}],
        }
        try:
            resp = query_api.get_filings(query)
            if resp.get("total", {}).get("value", 0) > 0:
                filing = resp["filings"][0]
                url = filing["linkToFilingDetails"]
                pdf_bytes = pdf_api.get_pdf(url)
                out[ftype] = pdf_bytes
        except Exception:
            continue
    return out


def _compute_and_update_json(json_data: str, ticker: str) -> str:
    # Minimal post-processing passthrough; extend with full logic as needed
    try:
        data = json.loads(json_data)
        data.setdefault("ticker", ticker)
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        return json_data


def _json_to_csv(json_data: str) -> str:
    try:
        data = json.loads(json_data)
        rows = []
        rows.append(f"Company,{data.get('company','-')}")
        rows.append(f"As of,{data.get('as_of','-')}")
        rows.append("")
        rows.append(f"Cash & Equivalents,{data.get('cash_and_equivalents','-')}")
        rows.append("")
        rows.append("Debt,Amount,PPC Holdings,Coupon,Secured,Maturity")
        if isinstance(data.get("debt"), list):
            for d in data["debt"]:
                rows.append(
                    f"{d.get('type','-')},{d.get('amount','-')},{d.get('ppc_holdings','-')},{d.get('coupon','-')},{d.get('secured','-')},{d.get('maturity','-')}"
                )
        rows.append(f"Total Debt,{data.get('total_debt','-')}")
        rows.append(f"Book Value of Equity,{data.get('book_value_of_equity','-')}")
        rows.append(f"Market Value of Equity,{data.get('market_value_of_equity','-')}")
        return "\n".join(rows)
    except Exception:
        return ""


def _call_llm(combined_text: str, ticker: str) -> Optional[str]:
    client = get_azure_openai_client()
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")
    prompt = _get_prompt(ticker)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Here is the SEC filing text for {ticker}:\n\n{combined_text}"},
        {"role": "user", "content": "Return only a valid JSON object with the CAP table fields."},
    ]
    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=messages,
            temperature=0,
        )
        content = resp.choices[0].message.content or ""
        # Extract JSON
        if "```json" in content and "```" in content.split("```json", 1)[1]:
            json_part = content.split("```json", 1)[1].split("```", 1)[0].strip()
            return json_part
        # Fallback: bracket matching
        if "{" in content and "}" in content:
            start = content.find("{")
            end = content.rfind("}")
            return content[start : end + 1]
        return None
    except Exception:
        return None


def load_cached_cap_from_blob(ticker: str) -> Optional[Dict[str, Any]]:
    cc = get_container_client("cap-outputs")
    prefix = f"{ticker}/cap_"
    latest_json: Optional[str] = None
    latest_blob: Optional[str] = None
    try:
        blobs = cc.list_blobs(name_starts_with=f"{ticker}/")
        for b in blobs:
            name: str = b.name
            if name.lower().endswith(".json") and name.startswith(prefix):
                if latest_blob is None or b.last_modified > cc.get_blob_client(latest_blob).get_blob_properties().last_modified:
                    latest_blob = name
        if latest_blob:
            text = cc.get_blob_client(latest_blob).download_blob().readall().decode("utf-8")
            return {"ticker": ticker, "json_data": text, "blob_json": latest_blob, "cached": True}
    except Exception:
        return None
    return None


def build_cap_table(ticker: str) -> Dict[str, Any]:
    """Build CAP table and upload JSON/CSV to blob storage. Returns dict with json_data, csv_data, blob_urls."""
    filings = _get_latest_filings_pdf_bytes(ticker)
    if not filings:
        cached = load_cached_cap_from_blob(ticker)
        if cached:
            return cached
        raise RuntimeError("Failed to retrieve filings from SEC API and no cache available")

    combined = ""
    if b := filings.get("10-K"):
        combined += "\n\n10-K FILING:\n" + _extract_text_from_pdf_bytes(b)
    if b := filings.get("10-Q"):
        combined += "\n\n10-Q FILING:\n" + _extract_text_from_pdf_bytes(b)

    llm_json = _call_llm(combined, ticker)
    if not llm_json:
        cached = load_cached_cap_from_blob(ticker)
        if cached:
            return cached
        raise RuntimeError("LLM failed to return JSON and no cache available")

    updated_json = _compute_and_update_json(llm_json, ticker)
    csv_text = _json_to_csv(updated_json)

    # Upload to blob storage
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    json_blob = f"{ticker}/cap_{ticker}_{ts}.json"
    csv_blob = f"{ticker}/cap_{ticker}_{ts}.csv"
    json_url = upload_text("cap-outputs", json_blob, updated_json, content_type="application/json")
    csv_url = upload_text("cap-outputs", csv_blob, csv_text, content_type="text/csv")

    return {
        "ticker": ticker,
        "json_data": updated_json,
        "csv_data": csv_text,
        "blob_urls": {"json_url": json_url, "csv_url": csv_url},
        "cached": False,
    }
