import os
import requests
import json
import re

def fetch_all_ticker_data(ticker: str) -> dict:
    """
    Fetch all required data for a ticker from APIs once.
    Returns a dictionary with all the data needed for both PDF and Word generation.
    """
    if not ticker:
        raise ValueError("No ticker provided.")

    api_base = os.getenv('APP_BASE_URL', 'http://127.0.0.1:9259')
    
    # Initialize result dictionary
    result = {
        'ticker': ticker,
        'hfa_rows': None,
        'cap_json': None,
        'comp_rows': None,
        'fsa_data': None,
        'credit_data': None,
        'company_exposure': None
    }
    
    # Fetch HFA data
    try:
        hfa_url = f"{api_base.rstrip('/')}/api/v1/hfa"
        resp = requests.post(hfa_url, json={"ticker": ticker}, timeout=300)
        if resp.status_code == 200:
            payload = resp.json()
            result['hfa_rows'] = payload.get("rows")
    except Exception as e:
        raise RuntimeError(f"Failed to fetch HFA data: {e}")
    
    if not isinstance(result['hfa_rows'], list) or not result['hfa_rows']:
        raise RuntimeError("HFA API response missing 'rows' list with data")
    
    # Fetch Credit Risk Metrics data (non-fatal)
    try:
        credit_url = f"{api_base.rstrip('/')}/api/v1/credit_table"
        credit_resp = requests.post(credit_url, json={"ticker": ticker}, timeout=300)
        if credit_resp.status_code == 200:
            credit_payload = credit_resp.json()
            if isinstance(credit_payload, dict):
                result['credit_data'] = credit_payload.get("json_data")
                # Fallback: parse raw JSON string if provided by API
                if result['credit_data'] is None and isinstance(credit_payload.get("json_data_raw"), str):
                    raw = credit_payload.get("json_data_raw")
                    def _try_parse_json_text(s: str):
                        try:
                            return json.loads(s)
                        except Exception:
                            s2 = s.strip()
                            if s2.startswith("```"):
                                s2 = s2.strip('`')
                            s2 = re.sub(r",\s*([}\\]])", r"\1", s2)
                            if '{' in s2 and '}' in s2:
                                s2 = s2[s2.find('{'): s2.rfind('}') + 1]
                            try:
                                return json.loads(s2)
                            except Exception:
                                return None
                    result['credit_data'] = _try_parse_json_text(raw)
    except Exception:
        result['credit_data'] = None

    # Fetch Company Expose Details (non-fatal)
    try:
        company_url = f"{api_base.rstrip('/')}/api/v1/company-table"
        company_resp = requests.post(company_url, json={"ticker": ticker}, timeout=120)
        if company_resp.status_code == 200:
            company_payload = company_resp.json()
            if isinstance(company_payload, dict):
                result['company_exposure'] = company_payload.get('table')
    except Exception:
        result['company_exposure'] = None

    # Fetch CAP table data (non-fatal)
    try:
        cap_url = f"{api_base.rstrip('/')}/api/v1/cap-table"
        cap_resp = requests.post(cap_url, json={"ticker": ticker}, timeout=300)
        if cap_resp.status_code == 200:
            cap_payload = cap_resp.json()
            if isinstance(cap_payload, dict):
                result['cap_json'] = cap_payload.get("json_data")
                # Fallback: parse raw JSON string if provided by API
                if result['cap_json'] is None and isinstance(cap_payload.get("json_data_raw"), str):
                    raw = cap_payload.get("json_data_raw")
                    def _try_parse_json_text(s: str):
                        try:
                            return json.loads(s)
                        except Exception:
                            s2 = s.strip()
                            if s2.startswith("```"):
                                s2 = s2.strip('`')
                            s2 = re.sub(r",\s*([}\\]])", r"\1", s2)
                            if '{' in s2 and '}' in s2:
                                s2 = s2[s2.find('{'): s2.rfind('}') + 1]
                            try:
                                return json.loads(s2)
                            except Exception:
                                return None
                    result['cap_json'] = _try_parse_json_text(raw)
    except Exception:
        result['cap_json'] = None
    
    # Fetch COMP data (non-fatal)
    try:
        comp_url = f"{api_base.rstrip('/')}/api/v1/comp"
        comp_resp = requests.post(comp_url, json={"ticker": ticker}, timeout=300)
        if comp_resp.status_code == 200:
            comp_payload = comp_resp.json()
            if isinstance(comp_payload, dict):
                result['comp_rows'] = comp_payload.get("rows")
    except Exception:
        result['comp_rows'] = None
    
    # Fetch FSA data from file
    fsa_dir = os.path.join('output', 'json', 'financial_analysis')
    fsa_path = os.path.join(fsa_dir, f"{ticker}_FSA.json")
    if os.path.exists(fsa_path):
        try:
            with open(fsa_path, 'r') as f:
                result['fsa_data'] = json.load(f)
        except Exception:
            result['fsa_data'] = None
    
    return result