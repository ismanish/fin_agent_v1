from fastapi import FastAPI, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import uvicorn
import os
import json
import io
from datetime import datetime
import uuid
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass
from src.sec_filing import (
    detect_identifier_type,
    get_financial_statements,
    save_statements_to_files,
    normalize_filing_type,
    normalize_quarter,
)
from src.data_manipulation import process_all_filings
from src.build_hfa_log import build_hfa_outputs
from src.comp_analysis_log import run_comp_analysis
from src.llm import (
    get_aqrr_keys,
    get_combined_json_data,
    check_cache_and_get_response,
    get_llm_response,
    load_yaml,
    save_llm_response_to_file,
)
from src.build_cap_log import build_cap_table
from src.aqrr_pdf_generate import build_pdf_bytes_from_ticker
from src.aqrr_word_generate import build_word_bytes_from_ticker
from utils.fetch_aqrr_data import fetch_all_ticker_data as fetch_data
from src.credit_risk_metrics import generate_credit_risk_metrics
# fsa import 
from src.fsa import analyze_ticker, clean_and_convert_to_json
# on demand insights import 
from src.on_demand_insights.chat_engine import chat, load_chat_history, save_chat_history
from src.company_detail import get_company_table, build_exposure_table_for_ticker

app = FastAPI(
    title="SEC Filings API",
    description="API to fetch financial statements from SEC EDGAR filings"
)

from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse, Response

import os
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import secrets

app.mount("/static", StaticFiles(directory="client/static"), name="static")

# Ensure output directory exists before mounting static files
_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(_OUTPUT_DIR, exist_ok=True)
app.mount("/output", StaticFiles(directory=_OUTPUT_DIR), name="output")
templates = Jinja2Templates(directory="client/templates")

# ---------- Data Lineage Chat (Azure OpenAI) ----------
try:  # pragma: no cover
    from openai import AzureOpenAI  # type: ignore
except Exception:  # pragma: no cover
    AzureOpenAI = None  # type: ignore

from src.agents.data_lineage_agent import (
    get_combined_json_data_from_local,
    _load_system_prompt,
)

_LINEAGE_SESSIONS: Dict[str, Dict[str, Any]] = {}

def _azure_openai_config() -> Dict[str, Optional[str]]:
    return {
        "endpoint": os.getenv("AZURE_OPENAI_ENDPOINT", "https://pgim-dealio.cognitiveservices.azure.com/"),
        "api_key": os.getenv("AZURE_OPENAI_API_KEY"),
        "deployment": os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini"),
        "api_version": os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        "max_tokens": int(os.getenv("AZURE_OPENAI_MAX_TOKENS", "2048")),
        "temperature": float(os.getenv("AZURE_OPENAI_TEMPERATURE", "0.0")),
        "top_p": float(os.getenv("AZURE_OPENAI_TOP_P", "1.0")),
        "frequency_penalty": float(os.getenv("AZURE_OPENAI_FREQ_PENALTY", "0.0")),
        "presence_penalty": float(os.getenv("AZURE_OPENAI_PRES_PENALTY", "0.0")),
    }

class LineageChatStartRequest(BaseModel):
    ticker: str

class LineageChatStartResponse(BaseModel):
    session_id: str

class LineageChatMessageRequest(BaseModel):
    session_id: str
    message: str

class LineageChatMessageResponse(BaseModel):
    session_id: str
    reply: str

# Add after existing imports
security = HTTPBearer()
from fastapi import Cookie

VALID_CREDENTIALS = {
    "admin@fin.com": "admin123",
    "user@fin.com": "user123"
}

# Simple token storage (in production, use proper session management)
ACTIVE_TOKENS = set()

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    authenticated: bool
    token: str
    message: str

@app.post("/api/v1/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response):
    """Authenticate user with credentials"""
    try:
        email = request.email.lower().strip()
        password = request.password
        
        if email in VALID_CREDENTIALS and VALID_CREDENTIALS[email] == password:
            # Generate a simple token
            token = secrets.token_urlsafe(32)
            ACTIVE_TOKENS.add(token)
            
            # Set HTTP-only cookie for dashboard access
            response.set_cookie(
                key="auth_token", 
                value=token, 
                httponly=True, 
                secure=True, 
                samesite="lax"
            )
            
            return LoginResponse(
                authenticated=True,
                token=token,
                message="Login successful"
            )
        else:
            raise HTTPException(
                status_code=401, 
                detail="Invalid email or password"
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/auth/logout")
async def logout(request: Request, response: Response, auth_token: Optional[str] = Cookie(None)):
    """Logout and invalidate token"""
    if auth_token:
        ACTIVE_TOKENS.discard(auth_token)
    
    # Clear the cookie
    response.delete_cookie(key="auth_token")
    return {"message": "Logged out successfully"}

@app.get("/api/v1/auth/verify")
async def verify_token(request: Request, auth_token: Optional[str] = Cookie(None)):
    """Verify if the current session is valid"""
    try:
        token_from_cookie = auth_token
        token_from_header = None
        
        authorization = request.headers.get("Authorization")
        if authorization and authorization.startswith("Bearer "):
            token_from_header = authorization[7:]
        
        # Use cookie token first, then header token
        token_to_check = token_from_cookie or token_from_header
        
        if token_to_check and token_to_check in ACTIVE_TOKENS:
            return {
                "authenticated": True,
                "token": token_to_check,
                "message": "Token is valid"
            }
        else:
            return {
                "authenticated": False,
                "message": "Invalid or expired token"
            }
    except Exception as e:
        return {
            "authenticated": False,
            "message": f"Verification failed: {str(e)}"
        }

@app.get("/")
async def read_root(request: Request):
    """Render the login page"""
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard")
async def dashboard(request: Request, auth_token: Optional[str] = Cookie(None)):
    """Render the main dashboard page (protected)"""
    # Check authentication via cookie first
    if auth_token and auth_token in ACTIVE_TOKENS:
        return templates.TemplateResponse("index.html", {"request": request})
    
    return RedirectResponse(url="/", status_code=302)
    
@app.get("/api/v1/companies")
async def get_companies():
    """Get list of available companies"""
    companies = [
        {"ticker": "AME", "title": "AMETEK INC"},
        {"ticker": "ELME", "title": "ELME COMMUNITIES"},
        {"ticker": "KRG", "title": "KITE REALTY GROUP TRUST"},
        {"ticker": "SAFE", "title": "SAFEHOLD INC."},
        {"ticker": "STAG", "title": "STAG INDUSTRIAL, INC."},
        {"ticker": "STE", "title": "STERIS PLC"},
        {"ticker": "TMO", "title": "THERMO FISHER SCIENTIFIC INC."},
        {"ticker": "WAT", "title": "WATERS CORPORATION"}
    ]

    return {"companies": companies}



@app.get("/api/v1/company-table")
async def company_table(q: Optional[str] = None, ticker: Optional[str] = None, limit: int = 100):
    """
    Return table JSON built from SEC's company_tickers.json.

    Query params:
    - ticker: exact ticker (e.g., NVDA)
    - q: substring filter over ticker or title (e.g., apple)
    - limit: max rows (default 100)
    """
    try:
        return get_company_table(q=q, ticker=ticker, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class CompanyTableRequest(BaseModel):
    ticker: str = Field(..., description="Ticker symbol, e.g., ELME")


@app.post("/api/v1/company-table")
async def company_table_post(req: CompanyTableRequest):
    """
    POST endpoint: accepts {"ticker": "ELME"} and returns the
    screenshot-style table JSON. Any non-SEC fields are null.
    """
    try:
        return build_exposure_table_for_ticker(req.ticker)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# ---------- Data Lineage Chat Endpoints ----------
@app.post("/api/v1/lineage/chat/start", response_model=LineageChatStartResponse)
async def lineage_chat_start(req: LineageChatStartRequest):
    ticker = (req.ticker or "").strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")

    data = get_combined_json_data_from_local(ticker)
    if not data:
        raise HTTPException(status_code=404, detail="No logs found in local storage for this ticker")

    # Since `data` is now a string, you can use it directly
    context_json = data

    # Truncate context if it's too large to avoid exceeding OpenAI token limit
    # Keep around 40,000 characters to stay well under the 30,000 token limit
    MAX_CONTEXT_LENGTH = 40000
    if len(context_json) > MAX_CONTEXT_LENGTH:
        context_json = context_json[:MAX_CONTEXT_LENGTH] + "\n\n[Content truncated due to size limits. Showing first portion of logs...]"

    system_prompt = _load_system_prompt() or """You are a Data Lineage Assistant for HFA, COMP, and CAP logs.
You help users understand how financial metrics are calculated and traced through the system.

IMPORTANT FORMATTING RULES:
- Use plain text formatting only. NO LaTeX syntax whatsoever.
- Never use \\[, \\], \\(, \\) or any other LaTeX delimiters.
- For formulas, write them as: Formula: MetricName = component1 + component2 - component3
- Use markdown for structure (** for bold, - for lists)
- Present numbers clearly with commas for thousands (e.g., 330,631 not 330631)"""

    session_id = uuid.uuid4().hex
    base_messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Here are the latest JSON logs for ticker {ticker}. Use only this content to answer questions about metric calculations and data lineage.\n\n"
                + context_json
            ),
        },
    ]
    _LINEAGE_SESSIONS[session_id] = {
        "ticker": ticker,
        "messages": base_messages,
        "created_at": datetime.utcnow().isoformat(),
    }

    return LineageChatStartResponse(session_id=session_id)


@app.post("/api/v1/lineage/chat/message", response_model=LineageChatMessageResponse)
async def lineage_chat_message(req: LineageChatMessageRequest):
    sess = _LINEAGE_SESSIONS.get(req.session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Invalid session_id")

    # Use OpenAI instead of Azure OpenAI
    try:
        from openai import OpenAI
    except ImportError:
        raise HTTPException(status_code=503, detail="OpenAI SDK not installed")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")

    client = OpenAI(api_key=api_key)

    try:
        # Compose messages for this turn
        messages: List[Dict[str, str]] = list(sess["messages"]) + [
            {"role": "user", "content": req.message}
        ]
        resp = client.chat.completions.create(
            messages=messages,
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_tokens=int(os.getenv("OPENAI_MAX_TOKENS", "2048")),
            temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.0")),
            top_p=float(os.getenv("OPENAI_TOP_P", "1.0")),
            frequency_penalty=float(os.getenv("OPENAI_FREQ_PENALTY", "0.0")),
            presence_penalty=float(os.getenv("OPENAI_PRES_PENALTY", "0.0")),
        )
        reply = ""
        try:
            if resp and getattr(resp, "choices", None):
                reply = resp.choices[0].message.content or ""
        except Exception:
            reply = ""

        # Update session history
        sess["messages"] = messages + ([{"role": "assistant", "content": reply}] if reply else [])

        return LineageChatMessageResponse(session_id=req.session_id, reply=reply or "")
    finally:
        try:
            client.close()
        except Exception:
            pass

# -------------- AQRR PDF (composed CAP + HFA + FSA + COMP) --------------

class AQRRRequest(BaseModel):
    ticker: str = Field(..., description="Ticker symbol, e.g., ELME")

@app.post("/api/v1/aqrr-pdf")
def aqrr_pdf(req: AQRRRequest, request: Request):
    try:
        t = (req.ticker or "").strip().upper()
        if not t:
            raise HTTPException(status_code=400, detail="ticker is required")
        # Generate PDF bytes
        pdf_bytes = build_pdf_bytes_from_ticker(t)

        # Ensure output directory exists: output/pdf/AQRR
        base_dir = os.path.dirname(__file__)
        output_dir = os.path.join(base_dir, "output", "pdf", "AQRR")
        os.makedirs(output_dir, exist_ok=True)

        # Save file as {TICKER}_AQRR.pdf (overwrite if exists)
        filename = f"{t}_AQRR.pdf"
        file_path = os.path.join(output_dir, filename)
        with open(file_path, "wb") as f:
             f.write(pdf_bytes)

        # Return public URL path for preview/download
        public_path = f"/output/pdf/AQRR/{filename}"
        base_url = str(request.base_url).rstrip('/')
        public_url = f"{base_url}{public_path}"
        return {"status": "ok", "ticker": t, "path": public_path, "url": public_url}
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/api/v1/aqrr-word")  
def aqrr_word_only(req: AQRRRequest, request: Request):
    try:
        t = (req.ticker or "").strip().upper()
        if not t:
            raise HTTPException(status_code=400, detail="ticker is required")
        
        # Generate Word bytes (will make API calls internally)
        word_bytes = build_word_bytes_from_ticker(t)
        
        # Ensure output directory exists
        base_dir = os.path.dirname(__file__)
        output_dir = os.path.join(base_dir, "output", "word", "AQRR")
        os.makedirs(output_dir, exist_ok=True)
        
        # Save file
        filename = f"{t}_AQRR.docx"
        file_path = os.path.join(output_dir, filename)
        with open(file_path, "wb") as f:
             f.write(word_bytes)
        
        # Return public URL path
        public_path = f"/output/word/AQRR/{filename}"
        base_url = str(request.base_url).rstrip('/')
        public_url = f"{base_url}{public_path}"
        
        return {"status": "ok", "ticker": t, "path": public_path, "url": public_url}
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/api/v1/aqrr-pdf-word")
def aqrr_pdf(req: AQRRRequest, request: Request):
    try:
        t = (req.ticker or "").strip().upper()
        if not t:
            raise HTTPException(status_code=400, detail="ticker is required")
        
        # Fetch all data once
        ticker_data = fetch_data(t)  # Use the fetch function from utils
        
        # Generate both PDF and Word bytes using the same data
        pdf_bytes = build_pdf_bytes_from_ticker(t, prefetched_data=ticker_data)
        word_bytes = build_word_bytes_from_ticker(t, prefetched_data=ticker_data)
        
        # Ensure output directories exist
        base_dir = os.path.dirname(__file__)
        pdf_output_dir = os.path.join(base_dir, "output", "pdf", "AQRR")
        word_output_dir = os.path.join(base_dir, "output", "word", "AQRR")
        os.makedirs(pdf_output_dir, exist_ok=True)
        os.makedirs(word_output_dir, exist_ok=True)
        
        # Save PDF file
        pdf_filename = f"{t}_AQRR.pdf"
        pdf_file_path = os.path.join(pdf_output_dir, pdf_filename)
        with open(pdf_file_path, "wb") as f:
            f.write(pdf_bytes)
        
        # Save Word file
        word_filename = f"{t}_AQRR.docx"
        word_file_path = os.path.join(word_output_dir, word_filename)
        with open(word_file_path, "wb") as f:
            f.write(word_bytes)
        
        # Return both file paths
        base_url = str(request.base_url).rstrip('/')
        pdf_public_path = f"/output/pdf/AQRR/{pdf_filename}"
        word_public_path = f"/output/word/AQRR/{word_filename}"
        
        return {
            "status": "ok", 
            "ticker": t, 
            "pdf": {
                "path": pdf_public_path,
                "url": f"{base_url}{pdf_public_path}"
            },
            "word": {
                "path": word_public_path,
                "url": f"{base_url}{word_public_path}"
            }
        }
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class FilingRequest(BaseModel):
    identifier: str = Field(..., description="Company ticker or CIK number")
    filing_type: str = Field(..., description="Type of filing to fetch, e.g., 10-K or 10Q (normalized internally)")
    year: Optional[int] = Field(None, description="Specific year to fetch. If None, fetches latest.")
    quarter: Optional[str] = Field(None, description="Required for 10-Q: Q1/Q2/Q3/Q4 or 1-4")

@app.post("/api/v1/filings")
async def get_filing_data(request: FilingRequest):
    """Fetch financial statements from SEC EDGAR filings."""
    try:
        # Standardize identifier and detect if it's CIK or ticker
        processed_identifier, is_cik = detect_identifier_type(request.identifier)
        ftype = normalize_filing_type(request.filing_type)
        # For 10-Q, quarter must be provided and valid
        try:
            qnorm = normalize_quarter(request.quarter)
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
        if ftype == "10-Q" and not qnorm:
            raise HTTPException(status_code=400, detail="Quarter is required for 10-Q. Provide Q1/Q2/Q3/Q4 or 1-4.")

        result = get_financial_statements(
            identifier=processed_identifier,
            is_cik=is_cik,
            filing_type=ftype,
            year=request.year,
            quarter=qnorm,
        )
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Auto-save when freshly fetched (not from cache)
        meta = result.get("metadata", {})
        if not meta.get("from_cache"):
            # Use processed identifier for filename stability
            save_statements_to_files(result["statements"], meta, processed_identifier, is_cik)
        
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------- HFA Build API --------------

class HFABuildRequest(BaseModel):
    ticker: str = Field(..., description="Ticker symbol, e.g., ELME")

@app.post("/api/v1/hfa")
async def hfa_build(req: HFABuildRequest):
    try:
        ticker = (req.ticker or "").strip().upper()
        if not ticker:
            raise HTTPException(status_code=400, detail="ticker is required")

        # 1) Fetch raw statements from SEC-API for required filings and save JSONs
        processed_identifier, is_cik = detect_identifier_type(ticker)
        fetch_plan = [
            {"filing_type": "10-K", "year": 2020, "quarter": None},
            {"filing_type": "10-K", "year": 2022, "quarter": None},
            {"filing_type": "10-K", "year": 2024, "quarter": None},
            {"filing_type": "10-Q", "year": 2025, "quarter": "Q1"},
            {"filing_type": "10-Q", "year": 2024, "quarter": "Q1"},
            {"filing_type": "10-Q", "year": 2024, "quarter": "Q2"},
            {"filing_type": "10-Q", "year": 2024, "quarter": "Q3"},
        ]
        fetch_warnings = []
        for item in fetch_plan:
            res = get_financial_statements(
                identifier=processed_identifier,
                is_cik=is_cik,
                filing_type=item["filing_type"],
                year=item["year"],
                quarter=item["quarter"],
            )
            if isinstance(res, dict) and "error" in res:
                fetch_warnings.append(f"Fetch failed for {item['filing_type']} {item['year']} {item['quarter'] or ''}: {res['error']}")
                continue
            try:
                meta = res.get("metadata", {})
                if not meta.get("from_cache"):
                    save_statements_to_files(res["statements"], meta, processed_identifier, is_cik)
            except Exception as e:
                fetch_warnings.append(f"Save failed for {item['filing_type']} {item['year']} {item['quarter'] or ''}: {e}")

        # 2) Process raw JSONs into processed combined JSON/CSVs for the ticker
        process_all_filings(ticker)

        # 3) Generate calculation mapping via LLM or use cache
        #    a) Load AQRR keys (schema)
        schema_path = os.path.join(os.path.dirname(__file__), "static", "aqrr_key_schema.yaml")
        aqrr_keys_list = get_aqrr_keys(schema_path)

        #    b) 10-K mapping for 2024 end-year
        cached_10k = check_cache_and_get_response(ticker, "10-K", aqrr_keys_list)
        if cached_10k is None:
            combined_10k = get_combined_json_data(ticker, 2024, "10-K")
            if not combined_10k:
                raise HTTPException(status_code=500, detail="Processed 10-K combined JSON not found; ensure processing step succeeded.")
            prompt_data = load_yaml(os.path.join(os.path.dirname(__file__), "utils", "prompt.yaml"))
            prompt_template = prompt_data.get("calculate_aqrr_keys", "")
            aqrr_keys_string = json.dumps(aqrr_keys_list, indent=2)
            llm_resp = get_llm_response(prompt_template, combined_10k, aqrr_keys_string)
            # Save only if response is a valid JSON list
            try:
                parsed = json.loads(llm_resp)
                if isinstance(parsed, list):
                    save_llm_response_to_file(llm_resp, os.path.join(os.path.dirname(__file__), "utils"), ticker, "10-K")
                else:
                    raise ValueError("LLM did not return a list")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"LLM mapping generation failed for 10-K: {e}")

        #    c) 10-Q mapping for 2025 (latest Q)
        cached_10q = check_cache_and_get_response(ticker, "10-Q", aqrr_keys_list)
        if cached_10q is None:
            combined_10q = get_combined_json_data(ticker, 2025, "10-Q")
            if not combined_10q:
                # fallback try 2024 if 2025 not present
                combined_10q = get_combined_json_data(ticker, 2024, "10-Q")
            if not combined_10q:
                raise HTTPException(status_code=500, detail="Processed 10-Q JSON not found; ensure processing step succeeded.")
            prompt_data = load_yaml(os.path.join(os.path.dirname(__file__), "utils", "prompt.yaml"))
            prompt_template = prompt_data.get("calculate_aqrr_keys", "")
            aqrr_keys_string = json.dumps(aqrr_keys_list, indent=2)
            llm_resp = get_llm_response(prompt_template, combined_10q, aqrr_keys_string)
            try:
                parsed = json.loads(llm_resp)
                if isinstance(parsed, list):
                    save_llm_response_to_file(llm_resp, os.path.join(os.path.dirname(__file__), "utils"), ticker, "10-Q")
                else:
                    raise ValueError("LLM did not return a list")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"LLM mapping generation failed for 10-Q: {e}")

        # 4) Build HFA table and write outputs
        result = build_hfa_outputs(ticker, "10-K", write_files=True, upload_to_azure=True)

        # --- Basic validation and success logging ---
        rows = result.get("rows", [])
        csv_path = result.get("csv_path")
        json_path = result.get("json_path")
        files_ok = True
        try:
            if csv_path and not os.path.exists(csv_path):
                files_ok = False
            if json_path and not os.path.exists(json_path):
                files_ok = False
            if json_path and os.path.exists(json_path):
                # ensure JSON file is loadable
                with open(json_path, "r", encoding="utf-8") as jf:
                    _ = json.load(jf)
        except Exception as _e:
            files_ok = False

        if rows and files_ok:
            print(f"✅ HFA successfully GENERATED and CHECKED for {ticker}. Rows: {len(rows)}. CSV: {csv_path}, JSON: {json_path}")
        else:
            print(f"Warning: HFA generated for {ticker} but validation checks failed. Rows: {len(rows)}, CSV exists: {os.path.exists(csv_path) if csv_path else False}, JSON exists: {os.path.exists(json_path) if json_path else False}")
        
        # Get blob URLs from result (already uploaded in build_hfa_outputs)
        blob_urls = result.get("blob_urls", {})

        # Convert absolute paths to relative paths or filenames only
        csv_filename = os.path.basename(result.get("csv_path", "")) if result.get("csv_path") else ""
        json_filename = os.path.basename(result.get("json_path", "")) if result.get("json_path") else ""
        
        return {
            "status": "ok",
            "ticker": result["ticker"],
            "filing": result["filing"],
            "filename_csv": csv_filename,
            "filename_json": json_filename,
            "blob_urls": blob_urls,  # Azure Blob Storage URLs
            "rows": result.get("rows", []),
            "warnings": fetch_warnings,
        }
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Mapping error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------- Data manipulation API --------------

class ProcessRequest(BaseModel):
    ticker: str = Field(..., description="Ticker symbol, e.g., ELME")
    filing_type: Optional[str] = Field("all", description="Filter by filing type: 10-K, 10-Q, or all")
    years: Optional[list[int]] = Field(None, description="List of years to include, e.g., [2024, 2023]")
    quarters: Optional[list[str]] = Field(None, description="List of quarters for 10-Q: Q1/Q2/Q3/Q4 or 1/2/3/4")
    overwrite: Optional[bool] = Field(False, description="Overwrite processed files if they already exist")

@app.post("/api/v1/process")
async def process_data(req: ProcessRequest):
    """Process previously saved raw SEC JSON into combined CSV/JSON under output/ for the given ticker.
    Note: current implementation ignores filters and processes all available 10-K and 10-Q files for the ticker.
    """
    try:
        if not req.ticker:
            raise HTTPException(status_code=400, detail="ticker is required")
        process_all_filings(req.ticker)
        return {"status": "ok", "message": f"Processed filings for {req.ticker}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------- Comparable Analysis API --------------

class CompRequest(BaseModel):
    ticker: str = Field(..., description="Ticker symbol, e.g., ELME")

@app.post("/api/v1/comp")
async def comp_build(req: CompRequest):
    try:
        ticker = (req.ticker or "").strip().upper()
        if not ticker:
            raise HTTPException(status_code=400, detail="ticker is required")

        result = run_comp_analysis(ticker, write_files=True, upload_to_azure=True)
        
        # Get blob URLs from result (already uploaded in run_comp_analysis)
        blob_urls = result.get("blob_urls", {})
        
        # Convert absolute paths to relative paths or filenames only
        csv_filename = os.path.basename(result.get("csv_path", "")) if result.get("csv_path") else ""
        json_filename = os.path.basename(result.get("json_path", "")) if result.get("json_path") else ""
        
        return {
            "status": "ok",
            "ticker": result.get("ticker"),
            "tickers": result.get("tickers", []),
            "rows": result.get("rows", []),
            "filename_csv": csv_filename,
            "filename_json": json_filename,
            "blob_urls": blob_urls,  # Azure Blob Storage URLs
            "warnings": result.get("warnings", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# -------------- Cap Table API --------------

class CapTableRequest(BaseModel):
    ticker: str = Field(..., description="Ticker symbol, e.g., ELME")

@app.post("/api/v1/cap-table")
async def generate_cap_table(req: CapTableRequest):
    """Generate a capitalization table for the given ticker using 10-K and 10-Q data."""
    try:
        ticker = (req.ticker or "").strip().upper()
        if not ticker:
            raise HTTPException(status_code=400, detail="ticker is required")
        
        result = build_cap_table(ticker, write_files=True, upload_to_azure=True)
        
        try:
            parsed_json = json.loads(result["json_data"]) if isinstance(result.get("json_data"), str) else result.get("json_data")
            
            # Get blob URLs from result (already uploaded in build_cap_table)
            blob_urls = result.get("blob_urls", {})
            
            # Convert absolute paths to relative paths or filenames only
            csv_filename = os.path.basename(result.get("csv_path", "")) if result.get("csv_path") else ""
            json_filename = os.path.basename(result.get("json_path", "")) if result.get("json_path") else ""
            
            return {
                "status": "ok",
                "ticker": result["ticker"],
                "filename_csv": csv_filename,
                "filename_json": json_filename,
                "json_data": parsed_json,
                "blob_urls": blob_urls,  # Azure Blob Storage URLs
                "cached": result.get("cached", False)  # Include whether result was cached
            }
        except Exception as e:
            # Return raw JSON string with an error hint instead of 500
            # Convert absolute paths to relative paths or filenames only
            csv_filename = os.path.basename(result.get("csv_path", "")) if result.get("csv_path") else ""
            json_filename = os.path.basename(result.get("json_path", "")) if result.get("json_path") else ""
            
            return {
                "status": "warning",
                "ticker": result.get("ticker"),
                "filename_csv": csv_filename,
                "filename_json": json_filename,
                "json_data_raw": result.get("json_data"),
                "json_error": f"Failed to parse JSON: {e}",
            }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

# -------------- Credit Risk Metrics API --------------
class CreditRiskRequest(BaseModel):
    ticker: str = Field(..., description="Ticker symbol, e.g., ELME")

@app.post("/api/v1/credit_table")
async def generate_credit_risk_table(req: CreditRiskRequest):
    """Generate credit risk metrics for the given ticker using 10-K and 10-Q data."""
    try:
        ticker = (req.ticker or "").strip().upper()
        if not ticker:
            raise HTTPException(status_code=400, detail="ticker is required")
                
        result = generate_credit_risk_metrics(
            ticker=ticker, 
            write_files=True, 
            upload_to_azure=True
        )
        
        if not result.get("success", False):
            error_msg = result.get("error", "Unknown error occurred")
            print(f"❌ Credit risk analysis failed for {ticker}: {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)
        
        try:
            # Parse JSON data if it's a string
            parsed_json = json.loads(result["json_data"]) if isinstance(result.get("json_data"), str) else result.get("json_data")
            
            # Convert absolute paths to relative paths or filenames only
            json_filename = os.path.basename(result.get("json_path", "")) if result.get("json_path") else ""
                        
            return {
                "status": "ok",
                "ticker": result["ticker"],
                "filename_json": json_filename,
                "json_data": parsed_json,
                "blob_url": result.get("blob_url"),
                "cached": result.get("cached", False),
                "success": True
            }
            
        except Exception as e:
            print(f"⚠️ Warning: JSON parsing failed for {ticker}: {e}")
            # Return raw JSON string with an error hint instead of 500
            json_filename = os.path.basename(result.get("json_path", "")) if result.get("json_path") else ""
            
            return {
                "status": "warning",
                "ticker": result.get("ticker"),
                "filename_json": json_filename,
                "json_data_raw": result.get("json_data"),
                "json_error": f"Failed to parse JSON: {e}",
                "cached": result.get("cached", False),
                "success": True
            }
            
    except HTTPException:
        raise
    except FileNotFoundError as e:
        print(f"❌ File not found error for {ticker}: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"❌ Unexpected error for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ... (Other endpoints like Credit Risk)

# -------------- Financial Statement Analysis (FSA) API --------------

class FSARequest(BaseModel):
    ticker: str = Field(..., description="Ticker symbol, e.g., ELME")

# Assuming you have updated the imports at the top of app.py to include:
# from src.fsa import analyze_ticker, clean_and_convert_to_json 
# and the Pydantic model FSARequest is defined.

@app.post("/api/v1/fsa")
async def financial_statement_analysis(req: FSARequest):
    """
    Performs a Financial Statement Analysis (FSA) for a given ticker 
    using LLM-based RAG, saves the resulting JSON, and returns the analysis.
    """
    try:
        ticker = (req.ticker or "").strip().upper()
        if not ticker:
            raise HTTPException(status_code=400, detail="ticker is required")

        # 1. Call the core function from fsa.py. It now returns a dict 
        #    containing the LLM text and the saved file path.
        analysis_result_dict = analyze_ticker(ticker)
        
        analysis_result_text = analysis_result_dict.get("text_result", "")
        saved_path = analysis_result_dict.get("saved_path") # Capture the path returned by fsa.py

        # 2. Parse the LLM output (text_result) into JSON for the API response
        cleaned_json_data = clean_and_convert_to_json(analysis_result_text)
        
        if not cleaned_json_data:
            # Check if the text is an error message from fsa.py
            if analysis_result_text.startswith("❌"):
                # Propagate the error message from the analysis function
                raise HTTPException(status_code=500, detail=analysis_result_text)
            else:
                # Generic failure message if clean_and_convert_to_json returns None
                raise Exception("LLM analysis successful, but failed to extract final JSON structure.")
        
        # 3. Successful response message generation
        message = f"FSA generated successfully for {ticker}."
        if saved_path:
            # Use the actual path returned by analyze_ticker
            message += f" Analysis JSON saved to: {saved_path}"
        else:
            # Should only happen if JSON was cleaned but saving failed inside analyze_ticker
            message += " WARNING: LLM output was valid, but the file was not saved."
            
        return {
            "status": "ok",
            "ticker": ticker,
            # The structure of the saved JSON is returned here
            "analysis_response_json": cleaned_json_data,
            "message": message
        }
        
    except HTTPException:
        # Re-raise explicit HTTP errors (like 400 for missing ticker or 500 for analysis errors)
        raise
    except Exception as e:
        print(f"❌ FSA processing failed for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"FSA processing failed: {str(e)}")


# In app.py, among other BaseModel definitions:
class ODIChatStartRequest(BaseModel):
    ticker: str

class ODIChatStartResponse(BaseModel):
    ticker: str
    message: str
    
class ODIChatMessageRequest(BaseModel):
    ticker: str
    message: str

class ODIChatMessageResponse(BaseModel):
    ticker: str
    reply: str


# ---------- On-Demand Insights (ODI) Chat Endpoints ----------

@app.post("/api/v1/odi/chat/start", response_model=ODIChatStartResponse)
async def odi_chat_start(req: ODIChatStartRequest):
    """
    Initializes or loads the chat history for a specific ticker. 
    Unlike Lineage, it doesn't return a session_id as memory is tied to the ticker file.
    """
    try:
        ticker = (req.ticker or "").strip().upper()
        if not ticker:
            raise HTTPException(status_code=400, detail="ticker is required")

        # Load history to check existence and potentially prime the memory file
        history = load_chat_history(ticker)
        
        if not history:
            # If no history exists, create an initial entry
            initial_message = {
                "role": "assistant",
                "content": f"Hello! I am the On-Demand Insights assistant for {ticker}. How can I help you with your financial analysis today?"
            }
            history.append(initial_message)
            save_chat_history(ticker, history)
            return ODIChatStartResponse(
                ticker=ticker,
                message=f"New chat session started for {ticker}. History initialized."
            )
        else:
            return ODIChatStartResponse(
                ticker=ticker,
                message=f"Chat session for {ticker} loaded successfully. {len(history)} messages found."
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start ODI chat session: {str(e)}")


@app.post("/api/v1/odi/chat/message", response_model=ODIChatMessageResponse)
async def odi_chat_message(req: ODIChatMessageRequest):
    """
    Sends a message to the ODI chat engine. The memory is managed internally 
    by chat_engine.py using the ticker as the session identifier.
    """
    try:
        ticker = (req.ticker or "").strip().upper()
        if not ticker:
            raise HTTPException(status_code=400, detail="ticker is required")
        
        message = (req.message or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="message cannot be empty")

        # The core function handles RAG, LLM call, and saving chat history
        reply = chat(user_query=message, company_ticker=ticker)

        # Check for error message returned by chat() function
        if reply.startswith("System Error:") or reply.startswith("❌ LLM API Error:") or "RAG_ERROR" in reply:
             raise HTTPException(status_code=500, detail=f"Chat execution failed: {reply}")

        return ODIChatMessageResponse(
            ticker=ticker,
            reply=reply
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process ODI chat message: {str(e)}")

# Pydantic Model Definitions for /api/v1/query, maintaining the original structure
class QueryRequest(BaseModel):
    company_id: str = Field(..., description="Company identifier")
    question: str = Field(..., description="Question to ask or analysis request")
    # mode: str = Field("Q&A", description="Analysis mode: Q&A or Report")

@app.post("/api/v1/query")
async def process_query(request: QueryRequest):
    """
    Processes financial analysis queries by orchestrating the ODI chat endpoints
    (/api/v1/odi/chat/start and /api/v1/odi/chat/message) directly.
    The original input/output signature, including 'mode', is maintained, 
    but the internal logic always uses the ODI chat system with the user's question.
    """
    try:
        ticker = request.company_id.strip().upper()
        user_query = request.question.strip()

        if not ticker:
            raise HTTPException(status_code=400, detail="company_id (ticker) is required.")
        
        # We allow an empty user_query here; the ODI message endpoint will validate it.
        # This skips the old logic that overrode the question for "Report" mode.

        # 1. Start or load the chat session (Direct ODI Call)
        start_req = ODIChatStartRequest(ticker=ticker)
        await odi_chat_start(req=start_req) 

        # 2. Send the message and get response (Direct ODI Call)
        # Note: 'mode' is ignored here as the ODI system handles context via chat history.
        message_req = ODIChatMessageRequest(ticker=ticker, message=user_query)
        chat_response = await odi_chat_message(req=message_req)
        
        # The chat_response is an ODIChatMessageResponse object (with a 'reply' attribute)
        response_text = chat_response.reply

        # 3. Format output to match the original endpoint's structure (including 'mode')
        return {
            "status": "success",
            "company_id": ticker,
            "question": request.question,
            "response": response_text
        }
        
    except HTTPException:
        # Re-raise explicit HTTP exceptions (e.g., 400s or 500s from ODI functions)
        raise
    except Exception as e:
        # Catch any remaining unexpected errors
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during ODI chat operation: {str(e)}")


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=9259, reload=True)


