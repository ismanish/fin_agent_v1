# PGIM Dealio - Complete Project Explanation

## Table of Contents
1. [Project Overview](#project-overview)
2. [System Architecture](#system-architecture)
3. [Directory Structure](#directory-structure)
4. [Core Components Deep Dive](#core-components-deep-dive)
5. [Data Flow & Execution](#data-flow--execution)
6. [API Endpoints](#api-endpoints)
7. [LLM Integration & Prompting](#llm-integration--prompting)
8. [Complete Workflows](#complete-workflows)
9. [Setup & Configuration](#setup--configuration)

---

## Project Overview

**PGIM Dealio** is an automated financial analysis system that generates **Automated Quarterly Research Reports (AQRR)** for companies by analyzing SEC filings. The system combines multiple financial analysis components into comprehensive PDF and Word reports.

### What Does This System Do?

The system:
1. **Fetches** SEC financial filings (10-K and 10-Q) from the SEC EDGAR API
2. **Processes** raw XBRL financial data into structured formats
3. **Generates** calculation mappings using LLMs (Azure OpenAI GPT-4)
4. **Computes** five major financial analysis components:
   - **HFA (Historical Financial Analysis)**: Multi-year financial metrics
   - **CAP (Capitalization Table)**: Debt structure and capitalization
   - **COMP (Comparable Analysis)**: Peer company comparisons
   - **FSA (Financial Statement Analysis)**: Qualitative analysis
   - **Credit Risk Metrics**: Leverage and liquidity ratios
5. **Composes** all components into professional PDF and Word reports
6. **Provides** an interactive Q&A system for on-demand insights using RAG (Retrieval-Augmented Generation)

### Key Technologies

- **Backend**: Python with FastAPI
- **LLM**: Azure OpenAI (GPT-4.1 and GPT-4.1-mini)
- **Vector Database**: FAISS (Facebook AI Similarity Search)
- **Data Sources**: SEC EDGAR API, SEC-API.io
- **Cloud Storage**: Azure Blob Storage
- **Frontend**: HTML/CSS/JavaScript with Jinja2 templates
- **RAG Framework**: LangChain

---

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       User Interface                         │
│              (Web Dashboard - HTML/JS)                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
│                        (app.py)                              │
│  ┌─────────────┬──────────────┬──────────────┬───────────┐ │
│  │  HFA API    │   CAP API    │  COMP API    │  FSA API  │ │
│  └─────────────┴──────────────┴──────────────┴───────────┘ │
│  ┌─────────────┬──────────────┬──────────────┬───────────┐ │
│  │ Credit API  │  AQRR API    │   ODI API    │ Auth API  │ │
│  └─────────────┴──────────────┴──────────────┴───────────┘ │
└────────────────────────┬────────────────────────────────────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
    ┌───────────┐  ┌──────────┐  ┌──────────────┐
    │  SEC API  │  │ Azure    │  │ Azure Blob   │
    │  (EDGAR)  │  │ OpenAI   │  │  Storage     │
    └───────────┘  └──────────┘  └──────────────┘
                         │
                         ▼
            ┌────────────────────────┐
            │  FAISS Vector Store    │
            │  (On-Demand Insights)  │
            └────────────────────────┘
```

### Component Flow

```
SEC Filings → Data Manipulation → LLM Mapping → Component Generation → AQRR Composition
     │              │                   │                │                    │
  (Raw JSON)   (Processed CSV)    (Calculation     (CSV/JSON)          (PDF/Word)
                                   Formulas)
```

---

## Directory Structure

```
pgim-dealio-main/
│
├── app.py                          # Main FastAPI application with all endpoints
│
├── src/                            # Source code for all components
│   ├── Authentication/             # Azure AD authentication (legacy)
│   ├── agents/                     # Data lineage chat agents
│   │   └── data_lineage_agent.py
│   │
│   ├── on_demand_insights/         # RAG-based Q&A system
│   │   ├── chat_engine.py         # Main chat interface with FAISS retrieval
│   │   └── document_processor.py  # FAISS index creation (manual script)
│   │
│   ├── sec_filing.py              # SEC EDGAR API integration & input validation
│   ├── data_manipulation.py        # Raw JSON → Processed CSV converter
│   ├── llm.py                     # Azure OpenAI integration & caching
│   │
│   ├── build_hfa_log.py           # HFA component generator
│   ├── build_cap_log.py           # CAP component generator
│   ├── comp_analysis_log.py       # COMP component generator
│   ├── fsa.py                     # FSA component generator
│   ├── credit_risk_metrics.py     # Credit risk metrics generator
│   │
│   ├── aqrr_pdf_generate.py       # PDF report composer
│   ├── aqrr_word_generate.py      # Word report composer
│   ├── company_detail.py          # Company metadata fetcher
│   └── rag_query.py               # RAG query utilities
│
├── utils/                          # Utility scripts and prompts
│   ├── prompt.yaml                # HFA calculation mapping prompt
│   ├── comp_prompt.yaml           # COMP calculation mapping prompt
│   ├── cap_prompt.yaml            # CAP extraction prompt
│   ├── odi_prompt.yaml            # On-Demand Insights system prompt
│   ├── fsa_prompt.yaml            # FSA analysis prompt
│   ├── fetch_aqrr_data.py         # Component orchestrator (fetches all data)
│   ├── azure_blob_storage.py      # Azure Blob Storage operations
│   ├── mapping_calculation.json   # Cached LLM calculation mappings
│   ├── comp_mapping.json          # COMP calculation mappings
│   └── vector_store/              # FAISS vector database
│
├── static/                         # Static assets
│   ├── aqrr_key_schema.yaml       # AQRR metrics schema (60 metrics)
│   └── company_ticker.json        # SEC company ticker mapping
│
├── client/                         # Frontend web dashboard
│   ├── templates/                 # Jinja2 HTML templates
│   │   ├── login.html
│   │   └── index.html            # Main dashboard
│   └── static/                    # CSS, JavaScript, images
│
├── output/                         # All generated outputs
│   ├── csv/                       # CSV outputs by component
│   │   ├── HFA/
│   │   ├── cap_table/
│   │   └── comp/
│   ├── json/                      # JSON outputs
│   │   ├── llm_input_processed/  # Processed financial statements
│   │   ├── hfa_output/
│   │   ├── cap_table/
│   │   ├── comp/
│   │   ├── financial_analysis/   # FSA outputs
│   │   └── credit_risk_analysis/
│   ├── pdf/AQRR/                  # Final PDF reports
│   └── word/AQRR/                 # Final Word reports
│
├── logs/                           # Detailed calculation logs
│   ├── HFA/                       # HFA calculation lineage
│   ├── CAP/                       # CAP calculation lineage
│   └── COMP/                      # COMP calculation lineage
│
├── data/                           # Raw SEC filing PDFs
│   └── {TICKER}/                  # Per-ticker filing storage
│
└── azure-functions/                # Azure Functions (deprecated)
```

---

## Core Components Deep Dive

### 1. Main Application (`app.py`)

**Purpose**: Central FastAPI application that exposes all API endpoints.

**Key Features**:
- **Authentication**: Simple token-based auth with hardcoded credentials
- **Static file serving**: Serves dashboard UI and output files
- **API routing**: All component endpoints
- **Error handling**: HTTP exception handling with detailed messages

**Main Endpoints** (see [API Endpoints](#api-endpoints) for details):
```python
# Authentication
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/verify

# Core Components
POST /api/v1/hfa              # Historical Financial Analysis
POST /api/v1/cap-table        # Capitalization Table
POST /api/v1/comp             # Comparable Analysis
POST /api/v1/fsa              # Financial Statement Analysis
POST /api/v1/credit_table     # Credit Risk Metrics

# AQRR Composition
POST /api/v1/aqrr-pdf         # Generate PDF only
POST /api/v1/aqrr-word        # Generate Word only
POST /api/v1/aqrr-pdf-word    # Generate both (recommended)

# On-Demand Insights (RAG-based Q&A)
POST /api/v1/odi/chat/start   # Initialize chat session
POST /api/v1/odi/chat/message # Send question
POST /api/v1/query            # Legacy query endpoint

# Data Lineage Chat
POST /api/v1/lineage/chat/start   # Start lineage chat
POST /api/v1/lineage/chat/message # Ask about calculations

# Utility
GET  /api/v1/companies        # List available companies
POST /api/v1/company-table    # Company exposure table
POST /api/v1/filings          # Fetch raw SEC filings
POST /api/v1/process          # Process raw filings
```

**Example Usage**:
```python
# Start the server
uvicorn.run("app:app", host="0.0.0.0", port=9259, reload=True)
```

---

### 2. SEC Filing Integration (`src/sec_filing.py`)

**Purpose**: Fetches and validates SEC financial filings from EDGAR API.

**Key Functions**:

#### `detect_identifier_type(identifier: str) -> Tuple[str, bool]`
Validates and normalizes ticker symbols or CIK numbers.

```python
# Example
detect_identifier_type("AAPL")  # Returns: ("AAPL", False)
detect_identifier_type("0000320193")  # Returns: ("0000320193", True)
```

#### `normalize_filing_type(filing_type: str) -> str`
Standardizes filing type inputs.

```python
# Example
normalize_filing_type("10K")   # Returns: "10-K"
normalize_filing_type("10-q")  # Returns: "10-Q"
```

#### `normalize_quarter(quarter: str) -> Optional[str]`
Validates quarter inputs for 10-Q filings.

```python
# Example
normalize_quarter("1")    # Returns: "Q1"
normalize_quarter("Q3")   # Returns: "Q3"
normalize_quarter(None)   # Returns: None
```

#### `get_financial_statements(identifier, is_cik, filing_type, year, quarter)`
Main function to fetch XBRL financial data from SEC API.

**Returns**: Dictionary with three statement types:
- `income`: Income statement (revenues, expenses, net income)
- `balance`: Balance sheet (assets, liabilities, equity)
- `cashflow`: Cash flow statement (operating, investing, financing)

**Example**:
```python
result = get_financial_statements(
    identifier="ELME",
    is_cik=False,
    filing_type="10-K",
    year=2024,
    quarter=None
)

# Returns:
{
    "statements": {
        "income": {...},
        "balance": {...},
        "cashflow": {...}
    },
    "metadata": {
        "ticker": "ELME",
        "filing_type": "10-K",
        "fiscal_year": 2024,
        "from_cache": False
    }
}
```

**Guardrails**:
- Input validation for ticker/CIK format
- Quarter requirement enforcement for 10-Q
- SEC API rate limiting (built into sec-api library)
- Error handling for missing filings

---

### 3. Data Manipulation (`src/data_manipulation.py`)

**Purpose**: Converts raw SEC XBRL JSON data into structured CSV files suitable for LLM consumption and calculation.

**Process**:
1. Reads raw JSON files from `data/raw/{TICKER}/{FILING_TYPE}_.../*.json`
2. Extracts financial statement data by type (income, balance, cashflow)
3. Pivots data into year-column format for 10-K or date-column format for 10-Q
4. Saves to `output/csv/{TICKER}/{FILING_TYPE}_combined/`

**Key Function**:

#### `process_all_filings(ticker: str)`
Processes all available filings for a ticker.

**Output Structure** (10-K example):
```csv
key,2020,2021,2022,2023,2024
RevenueFromContractWithCustomerExcludingAssessedTax,1500000,1650000,1820000,2010000,2200000
CostOfRevenue,800000,880000,970000,1070000,1180000
GrossProfit,700000,770000,850000,940000,1020000
...
```

**Output Structure** (10-Q example):
```csv
key,2024-03-31,2024-06-30,2024-09-30,2024-12-31
RevenueFromContractWithCustomerExcludingAssessedTax,550000,560000,540000,550000
...
```

**Guardrails**:
- Validates JSON structure before processing
- Handles missing data gracefully (empty cells)
- Preserves XBRL key names for lineage tracking

---

### 4. LLM Integration (`src/llm.py`)

**Purpose**: Manages Azure OpenAI API calls with caching and prompt management.

**Key Features**:
- **Response caching**: Saves LLM responses to avoid redundant API calls
- **Prompt templating**: Loads prompts from YAML files
- **Error handling**: Retries and graceful degradation
- **Temperature control**: Uses temperature=0.0 for deterministic financial calculations

**Key Functions**:

#### `get_llm_response(prompt_template, combined_json, aqrr_keys_string)`
Sends calculation mapping request to Azure OpenAI.

**Example**:
```python
# Load prompt from YAML
prompt_data = load_yaml("utils/prompt.yaml")
prompt_template = prompt_data["calculate_aqrr_keys"]

# Get processed financial data
combined_json = get_combined_json_data("ELME", 2024, "10-K")

# Get schema
aqrr_keys = get_aqrr_keys("static/aqrr_key_schema.yaml")
aqrr_keys_string = json.dumps(aqrr_keys, indent=2)

# Call LLM
response = get_llm_response(prompt_template, combined_json, aqrr_keys_string)

# Response is a JSON array like:
[
  {
    "aqrr_key": "Revenue",
    "financial_statement_keys": ["RevenueFromContractWithCustomerExcludingAssessedTax"],
    "calculation": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "notes": "Revenue from contracts with customers"
  },
  {
    "aqrr_key": "Adjusted EBITDA",
    "financial_statement_keys": ["NetIncomeLoss", "InterestExpense", "IncomeTaxExpense", "DepreciationAndAmortization"],
    "calculation": "NetIncomeLoss + InterestExpense + IncomeTaxExpense + DepreciationAndAmortization",
    "notes": "EBITDA calculation"
  }
]
```

#### `check_cache_and_get_response(ticker, filing_type, aqrr_keys_to_check)`
Checks if a mapping already exists in the cache.

**Returns**: Cached response or None if cache miss.

#### `save_llm_response_to_file(response_content, output_dir, ticker, filing_type)`
Saves LLM mapping response to `utils/mapping_calculation.json`.

**File Structure**:
```json
{
  "ELME": {
    "10-K": [
      [ /* Array of mapping objects */ ]
    ],
    "10-Q": [
      [ /* Array of mapping objects */ ]
    ]
  }
}
```

**Guardrails**:
- **Temperature = 0.0**: Ensures deterministic outputs for financial calculations
- **JSON validation**: Parses and validates LLM output before saving
- **Caching**: Prevents duplicate API calls for the same ticker/filing
- **Retry logic**: Handles transient API failures

---

### 5. HFA Component (`src/build_hfa_log.py`)

**Purpose**: Generates Historical Financial Analysis table with 5-year trends + LTM.

**What It Does**:
1. Loads calculation mappings from `utils/mapping_calculation.json`
2. Reads processed CSV files (income, balance, cashflow)
3. Executes calculation formulas for each AQRR metric
4. Computes LTM (Last Twelve Months) values
5. Generates comprehensive calculation log with data lineage
6. Outputs CSV and JSON files

**Key Metrics** (60 total):
- **Revenue & Profitability**: Revenue, Gross Profit, EBITDA, Net Income
- **Margins**: Gross Margin %, EBITDA Margin %, Net Margin %
- **Cash Flow**: Operating Cash Flow, CapEx, Free Cash Flow
- **Balance Sheet**: Total Assets, Total Debt, Book Equity
- **Leverage Ratios**: Debt/EBITDA, Debt/Capital
- **Returns**: ROIC, ROE, ROA

**Example Calculation** (EBITDA):
```python
# From mapping:
{
  "aqrr_key": "Adjusted EBITDA",
  "financial_statement_keys": [
    "NetIncomeLoss",
    "InterestExpenseNonoperating",
    "IncomeTaxExpenseBenefit",
    "DepreciationAndAmortization"
  ],
  "calculation": "NetIncomeLoss + InterestExpenseNonoperating + IncomeTaxExpenseBenefit + DepreciationAndAmortization"
}

# Execution for year 2024:
EBITDA_2024 = 150000 + 25000 + 35000 + 40000 = 250000
```

**LTM Calculation Example**:
```python
# LTM for flow metrics (non-stock):
LTM_2025 = FY_2024 + YTD_2025 - YTD_2024

# Example for Revenue:
LTM_Revenue_2025 = Revenue_2024 + Revenue_Q1_2025 - Revenue_Q1_2024
                 = 2200000 + 560000 - 550000
                 = 2210000

# For stock metrics (balance sheet), use latest period value:
LTM_TotalDebt_2025 = TotalDebt_Q1_2025
```

**Output Example** (`output/csv/HFA/ELME_HFA.csv`):
```csv
Metric,2020,2021,2022,2023,2024,YTD 2024,YTD 2025,LTM 2025
Revenue,1500000,1650000,1820000,2010000,2200000,550000,560000,2210000
Gross Profit,700000,770000,850000,940000,1020000,255000,260000,1025000
Adjusted EBITDA,300000,330000,365000,405000,450000,112000,115000,453000
% Margin,20.0,20.0,20.1,20.1,20.5,20.4,20.5,20.5
```

**Calculation Log** (`logs/HFA/HFA_ELME_20250119_143022.json`):
```json
{
  "ticker": "ELME",
  "timestamp": "20250119_143022",
  "metrics": {
    "Revenue": {
      "2024": {
        "value": 2200000,
        "final_value": "2,200",
        "calculation": "RevenueFromContractWithCustomerExcludingAssessedTax",
        "sources": {
          "RevenueFromContractWithCustomerExcludingAssessedTax": {
            "value": 2200000,
            "filing_type": "10-K",
            "table": "income",
            "period": "2024",
            "location": {
              "row": "RevenueFromContractWithCustomerExcludingAssessedTax",
              "column": "2024"
            }
          }
        }
      },
      "LTM 2025": {
        "value": 2210000,
        "final_value": "2,210",
        "calculation": "2024 + YTD 2025 - YTD 2024",
        "sources": {
          "RevenueFromContractWithCustomerExcludingAssessedTax": {...}
        }
      }
    }
  }
}
```

**Key Function**:

#### `build_hfa_outputs(ticker, filing, write_files=True, upload_to_azure=False)`

**Parameters**:
- `ticker`: Stock ticker (e.g., "ELME")
- `filing`: Filing type ("10-K" or "10-Q")
- `write_files`: Save to local files
- `upload_to_azure`: Upload to Azure Blob Storage

**Returns**:
```python
{
    "ticker": "ELME",
    "filing": "10-K",
    "rows": [...],  # List of metric dictionaries
    "csv_path": "output/csv/HFA/ELME_HFA.csv",
    "json_path": "output/json/hfa_output/ELME_HFA.json",
    "log_path": "logs/HFA/HFA_ELME_20250119_143022.json",
    "blob_urls": {
        "csv_url": "https://...",
        "json_url": "https://...",
        "log_url": "https://..."
    }
}
```

---

### 6. CAP Component (`src/build_cap_log.py`)

**Purpose**: Generates Capitalization Table showing debt structure and capital ratios.

**What It Does**:
1. Fetches latest 10-K and 10-Q PDFs from SEC (or uses cached local files)
2. Extracts text from PDFs using PyMuPDF
3. Sends to Azure OpenAI with ticker-specific prompt
4. Parses structured JSON response with debt details
5. Computes derived metrics (market cap, financial ratios)
6. Generates lineage log tracking all data sources

**Example Prompt** (from `utils/cap_prompt.yaml`):
```yaml
prompt_start: |
  You are a financial data extraction assistant...

ELME: |
  Extract the capitalization table for ELME Communities from the provided SEC filings.

  Return TWO sections:

  1. CAPITALIZATION_DATA:
  {...structure...}

  2. SOURCE_LINEAGE:
  {...lineage tracking...}
```

**Example LLM Output**:
```json
{
  "cap_table": {
    "company": "ELME COMMUNITIES",
    "as_of": "2024-12-31",
    "cash_and_equivalents": 15000,
    "debt": [
      {
        "type": "Revolving Credit Facility",
        "amount": 125000,
        "ppc_holdings": 125000,
        "coupon": "SOFR + 1.45%",
        "secured": "Yes",
        "maturity": "2027-09"
      },
      {
        "type": "Term Loan",
        "amount": 200000,
        "ppc_holdings": 200000,
        "coupon": "SOFR + 1.75%",
        "secured": "Yes",
        "maturity": "2028-03"
      }
    ],
    "total_debt": 325000,
    "book_value_of_equity": 450000,
    "market_value_of_equity": 520000,
    "ltm_adj_ebitda": 95000
  },
  "source_lineage": {
    "as_of_date": "2024-12-31",
    "metrics": {
      "cash_and_equivalents": {
        "final_value": 15000,
        "unit": "USD_thousands",
        "sources": {
          "10-Q_Q4_2024": {
            "page_number": 5,
            "section": "Consolidated Balance Sheets",
            "line_item": "Cash and cash equivalents"
          }
        }
      }
    }
  }
}
```

**Computed Metrics**:
```python
# Book Capitalization
book_capitalization = total_debt + book_value_of_equity

# Market Capitalization
market_capitalization = total_debt + market_value_of_equity

# Key Ratios
total_debt_to_adj_ebitda = total_debt / ltm_adj_ebitda
total_debt_to_market_cap = (total_debt / market_capitalization) * 100
```

**Output Files**:
- `output/csv/cap_table/ELME_CAP.csv` - Human-readable CSV
- `output/json/cap_table/ELME_CAP.json` - Full JSON with lineage
- `logs/CAP/CAP_ELME_20250119_143022.json` - Detailed calculation log

**Key Function**:

#### `build_cap_table(ticker, write_files=True, generate_lineage=True, upload_to_azure=False)`

**Returns**:
```python
{
    "ticker": "ELME",
    "json_data": {...},  # Cap table data
    "csv_data": "...",   # CSV formatted string
    "source_lineage": {...},  # LLM-provided lineage
    "lineage_log_path": "logs/CAP/...",
    "json_path": "output/json/cap_table/ELME_CAP.json",
    "csv_path": "output/csv/cap_table/ELME_CAP.csv",
    "blob_urls": {...},
    "cached": False
}
```

---

### 7. COMP Component (`src/comp_analysis_log.py`)

**Purpose**: Generates Comparable Company Analysis table with peer metrics.

**What It Does**:
1. Identifies peer companies for the target ticker
2. Fetches SEC filings for all peers
3. Processes financial data for each company
4. Generates LLM calculation mappings for standardized metrics
5. Computes comparable metrics across all peers
6. Calculates 3-year averages for key ratios
7. Generates detailed calculation logs for all companies

**Comparable Metrics** (11 total):
```python
COMP_METRICS = [
    "LTM Revenue",
    "LTM EBITDA",
    "EBITDA Margin %",
    "EBITDAR / (Int + Rents)",
    "(Total Debt + COL) / EBITDAR",
    "(Net Debt + COL) / EBITDAR",
    "(Total Debt + COL) / Total Cap",
    "(FCF + Rents) / (Total Debt + COL)",
    "3Y Avg (TD+COL)/EBITDAR",
    "3Y Avg (TD+COL)/Total Cap",
    "3Y Avg (FCF+Rents)/(TD+COL)"
]
```

**Example Prompt** (from `utils/comp_prompt.yaml`):
```yaml
calculate_comp_metrics: |
  You are generating calculation mappings for comparable-analysis metrics...

  STRICT INSTRUCTIONS:
  - Output only a JSON array
  - Use exact XBRL keys from the input JSON
  - Calculation must be executable arithmetic expression
  - Allowed: + - * / ( ) spaces
  - Variables: exact keys OR approved aliases (Revenue, EBITDA, EBITDAR, etc.)
  - DO NOT include "LTM", "FY_2024", "Q1_2025" in calculation

  Examples:
  - LTM Revenue: ["RevenueFromContractWithCustomerExcludingAssessedTax"], "RevenueFromContractWithCustomerExcludingAssessedTax"
  - EBITDA Margin %: ["AdjustedEBITDA", "Revenue"], "AdjustedEBITDA / Revenue * 100"
```

**Example Calculation** (EBITDAR / (Interest + Rent)):
```python
# Mapping:
{
  "metric": "EBITDAR / (Int + Rents)",
  "financial_statement_keys": [
    "AdjustedEBITDA",
    "OperatingLeaseCost",
    "InterestExpenseNonoperating"
  ],
  "calculation": "(EBITDA + Rent) / (Interest + Rent)"
}

# Execution:
EBITDA = 250000
Rent = 30000
Interest = 25000

EBITDAR_to_IntRent = (250000 + 30000) / (25000 + 30000)
                   = 280000 / 55000
                   = 5.09x
```

**3-Year Average Calculation**:
```python
# Example: 3Y Avg (TD+COL)/EBITDAR
values_2022 = 4.2
values_2023 = 4.5
values_2024 = 4.8

three_year_avg = (4.2 + 4.5 + 4.8) / 3 = 4.50x
```

**Output Example** (`output/csv/comp/ELME_COMP.csv`):
```csv
Metric,ELME,SAFE,STAG,KRG,Peer Median,Peer Mean
LTM Revenue,2210,1850,3100,2750,2480,2567
LTM EBITDA,453,385,682,595,524,552
EBITDA Margin %,20.5,20.8,22.0,21.6,21.2,21.1
EBITDAR / (Int + Rents),5.09,4.85,5.67,5.23,5.16,5.21
(Total Debt + COL) / EBITDAR,4.52,4.95,4.12,4.35,4.44,4.49
3Y Avg (TD+COL)/EBITDAR,4.50,4.88,4.25,4.42,4.46,4.51
```

**Calculation Log** (`logs/COMP/COMP_ELME_20250119_143022.json`):
```json
{
  "parent_ticker": "ELME",
  "timestamp": "20250119_143022",
  "comp_tickers": ["SAFE", "STAG", "KRG"],
  "metrics": {
    "ELME": {
      "LTM EBITDA": {
        "raw_value": 453000,
        "final_value": "453",
        "calculation": "AdjustedEBITDA",
        "calculation_steps": [
          {
            "step": "LTM Calculation",
            "formula": "FY_2024 + YTD_2025 - YTD_2024",
            "inputs": {
              "FY_2024": 450000,
              "YTD_2025": 115000,
              "YTD_2024": 112000
            },
            "result": 453000
          }
        ],
        "data_sources": {
          "AdjustedEBITDA_2024": {
            "value": 450000,
            "filing_type": "10-K",
            "period": "2024",
            "table": "income",
            "xbrl_key": "AdjustedEBITDA"
          }
        }
      }
    }
  }
}
```

**Key Function**:

#### `run_comp_analysis(ticker, write_files=True, upload_to_azure=False)`

**Process**:
1. Determine peer companies (hardcoded mapping or dynamic discovery)
2. Fetch and process all peer filings
3. Generate calculation mappings via LLM
4. Compute metrics for all companies
5. Calculate peer statistics (median, mean)
6. Generate output files and logs

**Returns**:
```python
{
    "ticker": "ELME",
    "tickers": ["ELME", "SAFE", "STAG", "KRG"],
    "rows": [...],
    "csv_path": "output/csv/comp/ELME_COMP.csv",
    "json_path": "output/json/comp/ELME_COMP.json",
    "blob_urls": {...},
    "warnings": []
}
```

---

### 8. FSA Component (`src/fsa.py`)

**Purpose**: Generates qualitative Financial Statement Analysis using LLM.

**What It Does**:
1. Reads all PDF filings from `data/{TICKER}/`
2. Extracts full text from PDFs
3. Loads processed JSON financial statements
4. Sends combined data to Azure OpenAI with FSA prompt
5. Parses structured JSON response with qualitative analysis
6. Saves analysis to JSON file

**FSA Prompt** (from `utils/fsa_prompt.yaml`):
```yaml
financial_statement_analysis: |
  You are a senior financial analyst. Perform a comprehensive financial statement analysis...

  Analyze the following aspects:
  1. Revenue Trends & Drivers
  2. Profitability Analysis
  3. Liquidity & Working Capital
  4. Debt Structure & Leverage
  5. Cash Flow Analysis
  6. Key Risks & Opportunities

  Output Format:
  {
    "executive_summary": "...",
    "revenue_analysis": {...},
    "profitability_analysis": {...},
    "liquidity_analysis": {...},
    "leverage_analysis": {...},
    "cash_flow_analysis": {...},
    "risks_and_opportunities": {...}
  }
```

**Example LLM Output**:
```json
{
  "executive_summary": "ELME Communities demonstrated strong operational performance in 2024, with revenue growth of 9.5% driven by higher occupancy rates and rental rate increases...",
  "revenue_analysis": {
    "ltm_revenue": 2210000,
    "yoy_growth_pct": 9.5,
    "key_drivers": [
      "Occupancy rate increased from 92% to 95%",
      "Average rental rates up 4.2% YoY",
      "New property acquisitions contributing $50M"
    ],
    "geographic_breakdown": {...}
  },
  "profitability_analysis": {
    "gross_margin_pct": 46.4,
    "ebitda_margin_pct": 20.5,
    "net_margin_pct": 6.8,
    "margin_trends": "EBITDA margin improved by 40 bps due to operational efficiencies..."
  },
  "liquidity_analysis": {
    "current_ratio": 1.2,
    "cash_and_equivalents": 15000,
    "undrawn_revolver": 75000,
    "total_liquidity": 90000,
    "commentary": "Strong liquidity position with..."
  },
  "leverage_analysis": {
    "total_debt": 325000,
    "net_debt": 310000,
    "debt_to_ebitda": 4.52,
    "interest_coverage": 5.09,
    "commentary": "Leverage within target range..."
  },
  "cash_flow_analysis": {
    "operating_cash_flow": 180000,
    "capex": 45000,
    "free_cash_flow": 135000,
    "commentary": "Strong FCF generation..."
  },
  "risks_and_opportunities": {
    "risks": [
      "Rising interest rate environment",
      "Regional economic slowdown"
    ],
    "opportunities": [
      "Acquisition pipeline robust",
      "Expansion into new markets"
    ]
  }
}
```

**Key Function**:

#### `analyze_ticker(ticker: str) -> dict`

**Process**:
1. Extract text from all PDFs in `data/{ticker}/`
2. Load processed JSON from `output/json/llm_input_processed/{ticker}/`
3. Format combined context
4. Call Azure OpenAI with FSA prompt
5. Parse and validate JSON response
6. Save to `output/json/financial_analysis/{ticker}_FSA.json`

**Returns**:
```python
{
    "text_result": "...",  # Raw LLM response or error message
    "saved_path": "output/json/financial_analysis/ELME_FSA.json"
}
```

---

### 9. Credit Risk Metrics (`src/credit_risk_metrics.py`)

**Purpose**: Generates credit risk metrics focusing on leverage and coverage ratios.

**What It Does**:
1. Similar to CAP component, fetches PDFs and processes them
2. Uses specialized prompt for credit metrics
3. Computes debt coverage and liquidity ratios
4. Outputs JSON with credit-focused analysis

**Key Metrics**:
- Debt Service Coverage Ratio (DSCR)
- Fixed Charge Coverage Ratio
- Debt-to-EBITDA (multiple definitions)
- Liquidity ratios
- Covenant compliance

**Output**: `output/json/credit_risk_analysis/{TICKER}_CREDIT.json`

---

### 10. On-Demand Insights - Chat Engine (`src/on_demand_insights/chat_engine.py`)

**Purpose**: Provides RAG-based Q&A system for interactive financial analysis.

**How It Works**:
1. **User asks question** about a company
2. **FAISS retrieval**: Finds top-k most relevant chunks from vector database
3. **Context assembly**: Combines retrieved chunks with full financial statements
4. **LLM generation**: Azure OpenAI generates answer using RAG context
5. **Memory management**: Saves conversation history per ticker

**RAG Architecture**:
```
User Query → Embedding → FAISS Search → Top-K Chunks → LLM Prompt → Answer
                                            ↓
                                  Full Financial JSON
                                            ↓
                                    System Prompt
```

**Key Functions**:

#### `get_rag_context(query: str, ticker: str, k: int = 5) -> str`
Retrieves top-k relevant document chunks from FAISS.

**Example**:
```python
query = "What were the drivers of revenue growth in 2024?"
ticker = "ELME"

# Searches FAISS index with metadata filter
context = get_rag_context(query, ticker, k=5)

# Returns formatted context:
"""
[Chunk Score: 0.1234, Source Ticker: ELME, Report: 10-K, Fiscal Period: 2024]
--- Revenue Analysis ---
Revenue grew from $2,010M to $2,200M in 2024, driven by:
1. Occupancy rate improvement from 92% to 95%
2. Rental rate increases averaging 4.2%
3. New property acquisitions

---

[Chunk Score: 0.1567, Source Ticker: ELME, Report: 10-Q, Fiscal Period: Q1_2025]
Q1 2025 revenue was $560M, up 1.8% from Q1 2024...
"""
```

#### `chat(user_query: str, company_ticker: str) -> str`
Main chat function that orchestrates the RAG pipeline.

**Process**:
1. Load chat history for ticker
2. Load system prompt from `utils/odi_prompt.yaml`
3. Retrieve RAG context via FAISS
4. Load full financial JSON for verification
5. Format complete prompt with all context
6. Call Azure OpenAI
7. Save updated chat history
8. Return answer

**Example**:
```python
# User question
user_query = "How much FCF did ELME generate in LTM 2025 and how does it compare to 2024?"
ticker = "ELME"

# Call chat engine
answer = chat(user_query, ticker)

# Answer:
"""
Based on the financial filings for ELME:

**Summary**: ELME Communities generated strong free cash flow in the LTM 2025 period, showing improvement over the prior year.

**Quantitative Data**:
- LTM 2025 Free Cash Flow: $135 million
- FY 2024 Free Cash Flow: $130 million
- Year-over-year increase: $5 million (+3.8%)

**Qualitative Drivers**:
The increase in FCF was primarily driven by:
1. Higher operating cash flow from improved occupancy rates
2. Disciplined capital expenditure management
3. Working capital improvements

**Strategic Initiatives**:
The company continues to prioritize FCF generation through operational efficiency programs and selective capital allocation.
"""
```

**System Prompt** (from `utils/odi_prompt.yaml`):
```yaml
system_prompt: |
  You are an expert financial analyst chatbot. Your task is to provide accurate and concise responses...

  **Strict Instructions:**
  1. ONLY use the provided Relevant Context and Financial Statements JSON
  2. If the question cannot be answered, state: "I cannot find the answer in the available financial reports for {ticker}"
  3. Maintain professional, objective, analytical tone
  4. Always reference year and report type

  Example Output Format:

  Question: What have been the drivers behind revenue growth?

  Answer: Based on the company's financial filings, revenue growth was primarily driven by:

  Summary: [Concise summary]

  Quantitative Data: [Specific numbers with sources]

  Qualitative Drivers: [Explanations from filings]

  Strategic Initiatives: [Company strategies mentioned]
```

**Chat History Management**:
```python
# Load history
history = load_chat_history("ELME")
# Returns: [
#   {"role": "user", "content": "What was revenue in 2024?"},
#   {"role": "assistant", "content": "Revenue in 2024 was..."},
#   ...
# ]

# Save history
save_chat_history("ELME", history)
# Saves to: utils/chat/ELME.json
```

---

### 11. On-Demand Insights - Document Processor (`src/on_demand_insights/document_processor.py`)

**Purpose**: Creates and maintains FAISS vector index for RAG system. **This is a manual script that must be run by administrators.**

**What It Does**:
1. Loads all processed JSON files from `output/json/llm_input_processed/`
2. Loads PDF filings from `data/`
3. Chunks text into 1000-character segments with 200-character overlap
4. Generates embeddings using Azure OpenAI embeddings model
5. Creates FAISS vector index with metadata
6. Saves index to `utils/vector_store/`

**IMPORTANT**: This script is **NOT** automatically triggered. Admins must run it manually whenever:
- New companies are added
- Financial data is updated
- New filings are processed

**How to Run**:
```bash
python src/on_demand_insights/document_processor.py
```

**Process**:
```
1. Find all JSON files in output/json/llm_input_processed/
   ├── ELME/ELME_10-K_2020-2024_combined.json
   ├── ELME/ELME_10-Q_2025_Q1.json
   ├── SAFE/...
   └── ...

2. Extract text from JSON (preserving structure)

3. Chunk text
   ├── Chunk 1: "--- Revenue Analysis --- Revenue: 2200000..."
   ├── Chunk 2: "...continued analysis..."
   └── ...

4. Generate embeddings (Azure OpenAI text-embedding-ada-002)

5. Create FAISS index with metadata
   {
     "ticker": "ELME",
     "report_type": "10-K",
     "fiscal_period": "2020-2024"
   }

6. Save to utils/vector_store/
```

**Configuration**:
```python
# From .env file
AZURE_OPENAI_ENDPOINT = "https://pgim-dealio.cognitiveservices.azure.com/"
AZURE_OPENAI_API_KEY = "..."
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME = "text-embedding-ada-002"

# Chunking parameters
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
```

**Metadata Structure**:
```python
# PDF metadata
{
    "ticker": "ELME",
    "report_type": "10-K",
    "fiscal_period": "2024"
}

# JSON metadata
{
    "ticker": "ELME",
    "report_type": "10-Q",
    "fiscal_period": "2025",
    "quarter": "Q1"
}
```

---

### 12. AQRR Composition (`utils/fetch_aqrr_data.py` + `src/aqrr_pdf_generate.py` + `src/aqrr_word_generate.py`)

**Purpose**: Orchestrates all components and composes final PDF/Word reports.

**Architecture**:
```
fetch_aqrr_data.py (Orchestrator)
    ↓
    ├─→ POST /api/v1/hfa          (HFA data)
    ├─→ POST /api/v1/cap-table    (CAP data)
    ├─→ POST /api/v1/comp         (COMP data)
    ├─→ Read FSA from file        (FSA data)
    └─→ POST /api/v1/credit_table (Credit data)
    ↓
aqrr_pdf_generate.py / aqrr_word_generate.py
    ↓
Generate final PDF/Word with all sections
```

**Key Function** (`utils/fetch_aqrr_data.py`):

#### `fetch_all_ticker_data(ticker: str) -> dict`

**What It Does**:
1. Makes sequential **blocking** HTTP requests to all component APIs
2. Waits for each component to complete before moving to next
3. Collects all responses in a dictionary
4. Returns unified data structure

**Example Execution**:
```python
ticker_data = fetch_all_ticker_data("ELME")

# Step 1: HFA (takes ~60 seconds)
#   - Fetches SEC filings
#   - Processes to CSV
#   - Generates LLM mappings
#   - Computes HFA table
print("HFA complete")

# Step 2: CAP (takes ~45 seconds)
#   - Fetches PDFs
#   - Extracts text
#   - LLM extraction
#   - Computes cap table
print("CAP complete")

# Step 3: COMP (takes ~90 seconds)
#   - Fetches peer filings
#   - Processes all peers
#   - LLM mappings for all
#   - Computes comp table
print("COMP complete")

# Step 4: FSA (read from file - instant)
print("FSA complete")

# Step 5: Credit (takes ~40 seconds)
print("Credit complete")

# Returns:
{
    "ticker": "ELME",
    "hfa_rows": [...],
    "cap_json": {...},
    "comp_rows": [...],
    "fsa_data": {...},
    "credit_data": {...},
    "company_exposure": {...}
}
```

**Important**: Each API call is **blocking** - meaning the system waits for component N to complete before starting component N+1. This ensures all files are saved before the composer runs.

**PDF/Word Generation**:

#### `build_pdf_bytes_from_ticker(ticker, prefetched_data=None)`

**What It Does**:
1. Loads all component data (from `prefetched_data` or files on disk)
2. Creates PDF document using ReportLab
3. Formats each section with tables, charts, and text
4. Returns PDF as bytes

**PDF Structure**:
```
┌────────────────────────────────────┐
│  Cover Page                        │
│  - Company Name                    │
│  - Report Date                     │
│  - AQRR Title                      │
├────────────────────────────────────┤
│  Table of Contents                 │
├────────────────────────────────────┤
│  Company Overview                  │
│  - Ticker, Sector, Description     │
├────────────────────────────────────┤
│  Historical Financial Analysis     │
│  - HFA Table (5 years + LTM)       │
│  - Charts                          │
├────────────────────────────────────┤
│  Capitalization Table              │
│  - Debt structure                  │
│  - Financial ratios                │
├────────────────────────────────────┤
│  Comparable Analysis               │
│  - Peer comparison table           │
│  - Benchmarking                    │
├────────────────────────────────────┤
│  Financial Statement Analysis      │
│  - Qualitative narrative           │
│  - Executive summary               │
├────────────────────────────────────┤
│  Credit Risk Metrics               │
│  - Leverage ratios                 │
│  - Coverage ratios                 │
└────────────────────────────────────┘
```

**Word Generation**: Similar structure using `python-docx`.

---

## Data Flow & Execution

### Complete AQRR Generation Flow

```
Step 1: SEC Filing Fetch
├─ User initiates: POST /api/v1/hfa {"ticker": "ELME"}
├─ System calls: detect_identifier_type("ELME") → ("ELME", False)
├─ For each filing:
│  ├─ get_financial_statements("ELME", is_cik=False, "10-K", 2024, None)
│  ├─ Fetch from SEC EDGAR XBRL API
│  ├─ Parse income, balance, cashflow statements
│  └─ Save to: data/raw/ELME/10-K_2024_.../*.json
└─ save_statements_to_files(...)

Step 2: Data Processing
├─ process_all_filings("ELME")
├─ Read all raw JSON files
├─ Pivot to year-based columns
└─ Save to: output/csv/ELME/10-K_2020-2024_combined/
   ├─ income.csv
   ├─ balance.csv
   └─ cashflow.csv

Step 3: LLM Mapping Generation
├─ Load AQRR schema: get_aqrr_keys("static/aqrr_key_schema.yaml")
├─ Load processed data: get_combined_json_data("ELME", 2024, "10-K")
├─ Load prompt: load_yaml("utils/prompt.yaml")
├─ Check cache: check_cache_and_get_response("ELME", "10-K", aqrr_keys)
├─ If cache miss:
│  ├─ Format prompt with financial data and schema
│  ├─ Call Azure OpenAI GPT-4.1 (temperature=0.0)
│  ├─ Parse JSON response
│  └─ save_llm_response_to_file(...) → utils/mapping_calculation.json
└─ Returns: [
     {"aqrr_key": "Revenue", "calculation": "...", ...},
     ...
   ]

Step 4: HFA Computation
├─ load_mapping("ELME", "10-K") from mapping_calculation.json
├─ Read CSV files (income, balance, cashflow)
├─ Create DataStore with all financial data
├─ For each AQRR metric:
│  ├─ Get calculation formula
│  ├─ Execute: safe_eval_expr(formula, year, datastore)
│  ├─ Log sources and calculation steps
│  └─ Append to results
├─ Compute LTM values
│  └─ LTM = FY_2024 + YTD_2025 - YTD_2024
├─ Format final values
│  └─ format_final_value(metric_name, value)
└─ Save outputs:
   ├─ output/csv/HFA/ELME_HFA.csv
   ├─ output/json/hfa_output/ELME_HFA.json
   └─ logs/HFA/HFA_ELME_20250119_143022.json

Step 5: CAP Generation (Parallel)
├─ get_filings_for_ticker("ELME")
│  ├─ Check local: data/ELME/10-K_*.pdf
│  ├─ If missing: fetch from SEC API
│  └─ save_filing_to_local(...)
├─ extract_text_from_pdf(...)
├─ get_prompt_for_ticker("ELME") from cap_prompt.yaml
├─ Call Azure OpenAI with PDF text
├─ Parse: parse_llm_response_with_lineage(...)
│  ├─ Extract CAPITALIZATION_DATA (cap table)
│  └─ Extract SOURCE_LINEAGE (data sources)
├─ Compute derived metrics
│  ├─ book_capitalization = total_debt + book_equity
│  ├─ market_capitalization = total_debt + market_equity
│  └─ Calculate ratios
├─ create_lineage_log(ticker, cap_table_data, source_lineage)
└─ Save:
   ├─ output/csv/cap_table/ELME_CAP.csv
   ├─ output/json/cap_table/ELME_CAP.json
   └─ logs/CAP/CAP_ELME_20250119_143022.json

Step 6: COMP Generation (Parallel)
├─ Identify peers: ["SAFE", "STAG", "KRG"]
├─ For each ticker (ELME + peers):
│  ├─ Fetch and process filings (Steps 1-2)
│  ├─ Generate LLM mapping (Step 3)
│  └─ Compute metrics
├─ Calculate peer statistics
│  ├─ Median
│  └─ Mean
└─ Save:
   ├─ output/csv/comp/ELME_COMP.csv
   ├─ output/json/comp/ELME_COMP.json
   └─ logs/COMP/COMP_ELME_20250119_143022.json

Step 7: FSA Generation
├─ Extract text from all PDFs
├─ Load processed JSON
├─ Load FSA prompt
├─ Call Azure OpenAI
├─ Parse qualitative analysis
└─ Save: output/json/financial_analysis/ELME_FSA.json

Step 8: Credit Risk Generation
├─ Similar to CAP
├─ Focus on credit metrics
└─ Save: output/json/credit_risk_analysis/ELME_CREDIT.json

Step 9: AQRR Composition
├─ fetch_all_ticker_data("ELME")
│  ├─ POST /api/v1/hfa (blocks ~60s)
│  ├─ POST /api/v1/cap-table (blocks ~45s)
│  ├─ POST /api/v1/comp (blocks ~90s)
│  ├─ Read FSA from file
│  └─ POST /api/v1/credit_table (blocks ~40s)
├─ build_pdf_bytes_from_ticker("ELME", prefetched_data)
│  ├─ Create PDF with all sections
│  └─ Returns PDF bytes
├─ build_word_bytes_from_ticker("ELME", prefetched_data)
│  ├─ Create Word doc with all sections
│  └─ Returns Word bytes
└─ Save final outputs:
   ├─ output/pdf/AQRR/ELME_AQRR.pdf
   └─ output/word/AQRR/ELME_AQRR.docx
```

**Total Time**: ~5-7 minutes for complete AQRR generation

---

## API Endpoints

### Authentication Endpoints

#### `POST /api/v1/auth/login`
Authenticates user and returns auth token.

**Request**:
```json
{
  "email": "admin@pgim.com",
  "password": "admin123"
}
```

**Response**:
```json
{
  "authenticated": true,
  "token": "eRt23kLm9pQz...",
  "message": "Login successful"
}
```

#### `POST /api/v1/auth/logout`
Invalidates the current session.

#### `GET /api/v1/auth/verify`
Verifies current token validity.

---

### Component Endpoints

#### `POST /api/v1/hfa`
Generates Historical Financial Analysis.

**Request**:
```json
{
  "ticker": "ELME"
}
```

**Response**:
```json
{
  "status": "ok",
  "ticker": "ELME",
  "filing": "10-K",
  "filename_csv": "ELME_HFA.csv",
  "filename_json": "ELME_HFA.json",
  "blob_urls": {
    "csv_url": "https://...",
    "json_url": "https://...",
    "log_url": "https://..."
  },
  "rows": [
    {
      "Metric": "Revenue",
      "2020": 1500000,
      "2021": 1650000,
      ...
    }
  ],
  "warnings": []
}
```

#### `POST /api/v1/cap-table`
Generates Capitalization Table.

**Request**:
```json
{
  "ticker": "ELME"
}
```

**Response**:
```json
{
  "status": "ok",
  "ticker": "ELME",
  "filename_csv": "ELME_CAP.csv",
  "filename_json": "ELME_CAP.json",
  "json_data": {
    "company": "ELME COMMUNITIES",
    "total_debt": 325000,
    ...
  },
  "blob_urls": {...},
  "cached": false
}
```

#### `POST /api/v1/comp`
Generates Comparable Analysis.

**Request**:
```json
{
  "ticker": "ELME"
}
```

**Response**:
```json
{
  "status": "ok",
  "ticker": "ELME",
  "tickers": ["ELME", "SAFE", "STAG", "KRG"],
  "rows": [...],
  "filename_csv": "ELME_COMP.csv",
  "filename_json": "ELME_COMP.json",
  "blob_urls": {...},
  "warnings": []
}
```

#### `POST /api/v1/fsa`
Generates Financial Statement Analysis.

**Request**:
```json
{
  "ticker": "ELME"
}
```

**Response**:
```json
{
  "status": "ok",
  "ticker": "ELME",
  "analysis_response_json": {
    "executive_summary": "...",
    "revenue_analysis": {...},
    ...
  },
  "message": "FSA generated successfully for ELME. Analysis JSON saved to: ..."
}
```

#### `POST /api/v1/credit_table`
Generates Credit Risk Metrics.

**Request**:
```json
{
  "ticker": "ELME"
}
```

**Response**: Similar to CAP endpoint.

---

### AQRR Composition Endpoints

#### `POST /api/v1/aqrr-pdf-word` (Recommended)
Generates both PDF and Word reports in a single call.

**Request**:
```json
{
  "ticker": "ELME"
}
```

**Response**:
```json
{
  "status": "ok",
  "ticker": "ELME",
  "pdf": {
    "path": "/output/pdf/AQRR/ELME_AQRR.pdf",
    "url": "http://localhost:9259/output/pdf/AQRR/ELME_AQRR.pdf"
  },
  "word": {
    "path": "/output/word/AQRR/ELME_AQRR.docx",
    "url": "http://localhost:9259/output/word/AQRR/ELME_AQRR.docx"
  }
}
```

**What Happens**:
1. Calls `fetch_all_ticker_data("ELME")` - orchestrates all component APIs
2. Waits for all components to complete (blocking, sequential)
3. Passes unified data to PDF/Word generators
4. Returns download URLs for both files

**Total Time**: ~5-7 minutes

---

### On-Demand Insights Endpoints

#### `POST /api/v1/odi/chat/start`
Initializes or loads chat session for a ticker.

**Request**:
```json
{
  "ticker": "ELME"
}
```

**Response**:
```json
{
  "ticker": "ELME",
  "message": "Chat session for ELME loaded successfully. 5 messages found."
}
```

#### `POST /api/v1/odi/chat/message`
Sends a question and gets an answer using RAG.

**Request**:
```json
{
  "ticker": "ELME",
  "message": "What were the key drivers of EBITDA growth in 2024?"
}
```

**Response**:
```json
{
  "ticker": "ELME",
  "reply": "Based on the financial filings for ELME:\n\nSummary: EBITDA grew by $45M in 2024...\n\nQuantitative Data: EBITDA increased from $405M to $450M...\n\nQualitative Drivers: The growth was driven by...\n\nStrategic Initiatives: The company implemented..."
}
```

**What Happens**:
1. Loads chat history
2. Retrieves top-5 relevant chunks from FAISS
3. Loads full financial JSON
4. Combines all context with system prompt
5. Calls Azure OpenAI
6. Saves updated history
7. Returns answer

---

### Data Lineage Endpoints

#### `POST /api/v1/lineage/chat/start`
Starts a data lineage chat session (for asking about calculations).

**Request**:
```json
{
  "ticker": "ELME"
}
```

**Response**:
```json
{
  "session_id": "a1b2c3d4e5f6..."
}
```

#### `POST /api/v1/lineage/chat/message`
Asks questions about how specific metrics were calculated.

**Request**:
```json
{
  "session_id": "a1b2c3d4e5f6...",
  "message": "How was EBITDA calculated for 2024?"
}
```

**Response**:
```json
{
  "session_id": "a1b2c3d4e5f6...",
  "reply": "EBITDA for 2024 was calculated as follows:\n\nFormula: NetIncomeLoss + InterestExpense + IncomeTaxExpense + DepreciationAndAmortization\n\nValues:\n- NetIncomeLoss: $150,000\n- InterestExpense: $25,000\n- IncomeTaxExpense: $35,000\n- DepreciationAndAmortization: $40,000\n\nResult: $250,000"
}
```

---

## LLM Integration & Prompting

### Azure OpenAI Configuration

All LLM calls use Azure OpenAI with the following configuration:

```python
# From .env file
AZURE_OPENAI_ENDPOINT = "https://pgim-dealio.cognitiveservices.azure.com/"
AZURE_OPENAI_API_KEY = "..."
AZURE_OPENAI_DEPLOYMENT = "gpt-4.1"  # Chat model
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME = "text-embedding-ada-002"  # Embeddings
AZURE_OPENAI_API_VERSION = "2024-12-01-preview"

# Standard parameters
temperature = 0.0  # Deterministic for financial calculations
max_tokens = 4096
top_p = 1.0
frequency_penalty = 0.0
presence_penalty = 0.0
```

### Meta Prompting Techniques

**1. Role Assignment**
```yaml
# From utils/prompt.yaml
"You are generating calculation mappings for AQRR metrics from a processed JSON of financial statements..."
```

**2. Output Schema Enforcement**
```yaml
# Strict output format requirement
"Output only a JSON array; no prose outside the JSON."
"Each item must have fields: metric, financial_statement_keys, calculation, notes"
```

**3. Constraint Specification**
```yaml
# Allowed operations
"The calculation MUST be a single arithmetic expression that is executable as-is."
"Allowed: + - * / ( ) spaces"

# Prohibited elements
"DO NOT include words like 'LTM', 'FY_2024', 'Q1_2025' in the calculation"
```

**4. Few-Shot Examples**
```yaml
Examples:
- LTM Revenue: financial_statement_keys: ["RevenueFromContractWithCustomerExcludingAssessedTax"], calculation: "RevenueFromContractWithCustomerExcludingAssessedTax"
- EBITDA Margin %: financial_statement_keys: ["AdjustedEBITDA", "Revenue"], calculation: "AdjustedEBITDA / Revenue * 100"
```

**5. Chain-of-Thought Reasoning**
```yaml
# From utils/odi_prompt.yaml
Chain of Thought:
1. Identify User Intent
2. Locate Relevant Documents
3. Extract Data
4. Perform Calculations/Comparisons
5. Synthesize and Explain
6. Format and Cite
```

### Guardrails Implementation

**1. Input Validation** (`src/sec_filing.py`):
```python
# Ticker/CIK validation
def detect_identifier_type(identifier: str) -> Tuple[str, bool]:
    identifier = identifier.strip().upper()
    if identifier.isdigit():
        return (identifier.zfill(10), True)  # CIK
    if re.match(r'^[A-Z0-9]{1,5}$', identifier):
        return (identifier, False)  # Ticker
    raise ValueError("Invalid input")

# Quarter validation
def normalize_quarter(quarter: str) -> str:
    if quarter not in {"Q1", "Q2", "Q3", "Q4", "1", "2", "3", "4"}:
        raise ValueError("Invalid quarter. Use Q1-Q4 or 1-4")
```

**2. Output Validation** (`src/llm.py`, `src/build_hfa_log.py`):
```python
# JSON parsing validation
try:
    parsed = json.loads(llm_response)
    if not isinstance(parsed, list):
        raise ValueError("LLM did not return a list")
except Exception as e:
    raise HTTPException(status_code=500, detail=f"LLM mapping generation failed: {e}")

# Value formatting
def format_final_value(metric_name: str, value: Number) -> Any:
    if value is None:
        return None
    # Apply formatting rules based on metric type
    ...
```

**3. Temperature Control**:
```python
# Deterministic calculations
response = client.chat.completions.create(
    model="gpt-4.1",
    temperature=0.0,  # No randomness for financial calculations
    ...
)
```

**4. Response Caching** (`src/llm.py`):
```python
def check_cache_and_get_response(ticker, filing_type, aqrr_keys):
    """Check if mapping exists before calling LLM"""
    mapping_path = os.path.join(UTILS_DIR, "mapping_calculation.json")
    if os.path.exists(mapping_path):
        with open(mapping_path, "r") as f:
            mappings = json.load(f)
        if ticker in mappings and filing_type in mappings[ticker]:
            return mappings[ticker][filing_type][0]  # Cache hit
    return None  # Cache miss
```

**5. Error Handling**:
```python
# API endpoint error handling
try:
    result = build_hfa_outputs(ticker, "10-K", write_files=True)
    return result
except HTTPException:
    raise  # Re-raise HTTP exceptions
except FileNotFoundError as e:
    raise HTTPException(status_code=404, detail=str(e))
except KeyError as e:
    raise HTTPException(status_code=400, detail=f"Mapping error: {str(e)}")
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
```

**6. Grounding to Source Data** (`utils/odi_prompt.yaml`):
```yaml
Strict Instructions:
1. ONLY use the provided Relevant Context and Financial Statements JSON
2. If the question cannot be answered, state: "I cannot find the answer..."
3. Do not use external knowledge or general training data
```

---

## Complete Workflows

### Workflow 1: Generate Complete AQRR Report

**User Action**: Click "Generate AQRR" in dashboard

**Backend Process**:
```
1. User → POST /api/v1/aqrr-pdf-word {"ticker": "ELME"}

2. fetch_all_ticker_data("ELME") starts
   │
   ├─ POST /api/v1/hfa {"ticker": "ELME"}
   │  ├─ Fetch SEC filings (10-K 2020-2024, 10-Q 2024-Q1,Q2,Q3, 10-Q 2025-Q1)
   │  ├─ Process to CSV
   │  ├─ Generate/load LLM mappings
   │  ├─ Compute HFA table
   │  ├─ Save outputs
   │  └─ Upload to Azure Blob
   │  ⏱ ~60 seconds
   │
   ├─ POST /api/v1/cap-table {"ticker": "ELME"}
   │  ├─ Fetch/load PDFs
   │  ├─ Extract text
   │  ├─ LLM extraction
   │  ├─ Compute cap table
   │  ├─ Save outputs
   │  └─ Upload to Azure Blob
   │  ⏱ ~45 seconds
   │
   ├─ POST /api/v1/comp {"ticker": "ELME"}
   │  ├─ Identify peers
   │  ├─ Fetch all peer filings
   │  ├─ Process all peers
   │  ├─ Generate LLM mappings
   │  ├─ Compute comp table
   │  ├─ Save outputs
   │  └─ Upload to Azure Blob
   │  ⏱ ~90 seconds
   │
   ├─ Read FSA from file
   │  └─ Load output/json/financial_analysis/ELME_FSA.json
   │  ⏱ <1 second
   │
   └─ POST /api/v1/credit_table {"ticker": "ELME"}
      ├─ Fetch/load PDFs
      ├─ LLM extraction
      ├─ Compute credit metrics
      ├─ Save outputs
      └─ Upload to Azure Blob
      ⏱ ~40 seconds

3. build_pdf_bytes_from_ticker("ELME", ticker_data)
   ├─ Load all component data
   ├─ Create PDF with ReportLab
   ├─ Add cover page
   ├─ Add table of contents
   ├─ Add HFA section with table
   ├─ Add CAP section with debt details
   ├─ Add COMP section with peer comparison
   ├─ Add FSA section with narrative
   ├─ Add Credit section with ratios
   └─ Return PDF bytes
   ⏱ ~20 seconds

4. build_word_bytes_from_ticker("ELME", ticker_data)
   ├─ Same structure as PDF
   └─ Return Word bytes
   ⏱ ~15 seconds

5. Save final outputs
   ├─ output/pdf/AQRR/ELME_AQRR.pdf
   └─ output/word/AQRR/ELME_AQRR.docx

6. Return download URLs to user
   {
     "pdf": {"url": "http://..."},
     "word": {"url": "http://..."}
   }

Total Time: ~280 seconds (~5 minutes)
```

**User Experience**:
```
Dashboard shows:
"Generating AQRR for ELME..."
[Progress bar]
"Fetching SEC filings... ✓"
"Computing HFA... ✓"
"Computing CAP... ✓"
"Computing COMP... ✓"
"Loading FSA... ✓"
"Computing Credit Metrics... ✓"
"Composing PDF... ✓"
"Composing Word... ✓"
"AQRR Complete!"
[Download PDF] [Download Word]
```

---

### Workflow 2: Ask Question via On-Demand Insights

**User Action**: Type question in ODI chat

**Backend Process**:
```
1. User → POST /api/v1/odi/chat/start {"ticker": "ELME"}
   └─ Response: {"ticker": "ELME", "message": "Chat session loaded"}

2. User → POST /api/v1/odi/chat/message {
     "ticker": "ELME",
     "message": "What was the EBITDA margin trend over the past 3 years?"
   }

3. chat_engine.py: chat("What was the EBITDA margin...", "ELME")
   │
   ├─ Load chat history
   │  └─ Read utils/chat/ELME.json
   │
   ├─ Load system prompt
   │  └─ Read utils/odi_prompt.yaml
   │
   ├─ Load financial statements JSON
   │  └─ Read all files in output/json/llm_input_processed/ELME/
   │
   ├─ RAG retrieval: get_rag_context(query, "ELME", k=5)
   │  ├─ Generate query embedding via Azure OpenAI
   │  ├─ Search FAISS index with filter {"ticker": "ELME"}
   │  ├─ Retrieve top-5 relevant chunks
   │  └─ Return formatted context
   │
   ├─ Format complete prompt
   │  ├─ System prompt
   │  ├─ Chat history
   │  ├─ RAG context (5 chunks)
   │  ├─ Full financial JSON
   │  └─ User query
   │
   ├─ Call Azure OpenAI
   │  ├─ model: "gpt-4.1"
   │  ├─ temperature: 0.0
   │  └─ max_tokens: 2048
   │
   ├─ Parse response
   │
   ├─ Update chat history
   │  └─ Append user message + assistant response
   │
   ├─ Save chat history
   │  └─ Write utils/chat/ELME.json
   │
   └─ Return answer

4. Response to user:
   {
     "ticker": "ELME",
     "reply": "Based on the financial filings for ELME:\n\n**Summary**: EBITDA margin showed consistent improvement...\n\n**Quantitative Data**:\n- 2022: 20.1%\n- 2023: 20.1%\n- 2024: 20.5%\n\n**Qualitative Drivers**: The margin expansion was driven by operational efficiencies..."
   }

Total Time: ~5-10 seconds
```

**User Experience**:
```
User types: "What was the EBITDA margin trend over the past 3 years?"
[Thinking...]
Assistant: "Based on the financial filings for ELME:

**Summary**: EBITDA margin showed consistent improvement...

**Quantitative Data**:
- 2022: 20.1%
- 2023: 20.1%
- 2024: 20.5%

**Qualitative Drivers**: The margin expansion was driven by operational efficiencies and higher-margin product mix.

**Strategic Initiatives**: The company's focus on cost optimization programs contributed to the improvement."
```

---

### Workflow 3: Update FAISS Vector Database

**Admin Action**: Run manual script after updating financial data

**Process**:
```bash
# Admin runs:
cd /path/to/pgim-dealio-main
python src/on_demand_insights/document_processor.py
```

**What Happens**:
```
1. Initialize Azure OpenAI embeddings client
   └─ Model: text-embedding-ada-002

2. Scan for JSON files
   └─ Find all files in output/json/llm_input_processed/

3. Process each JSON file
   ├─ Parse metadata from filename
   │  └─ Extract ticker, report_type, fiscal_period, quarter
   │
   ├─ Extract text from JSON
   │  └─ Recursively extract all key-value pairs
   │
   ├─ Chunk text
   │  ├─ Chunk size: 1000 characters
   │  ├─ Overlap: 200 characters
   │  └─ Preserve context by including section headers
   │
   └─ Attach metadata to each chunk
      {
        "ticker": "ELME",
        "report_type": "10-K",
        "fiscal_period": "2020-2024"
      }

4. Scan for PDF files
   └─ Find all files in data/*/

5. Process each PDF file
   ├─ Extract text using PyMuPDF
   ├─ Chunk text (same parameters)
   └─ Attach metadata

6. Generate embeddings (in batches)
   ├─ Batch size: 100 chunks
   ├─ Call Azure OpenAI embeddings API
   └─ Wait for all batches to complete

7. Create FAISS index
   ├─ Index type: Flat (exact search)
   ├─ Dimension: 1536 (ada-002 embedding size)
   └─ Add all vectors with metadata

8. Save FAISS index
   └─ Write to utils/vector_store/

Output:
✓ Processed 45 JSON files
✓ Processed 18 PDF files
✓ Created 1,234 chunks
✓ Generated 1,234 embeddings
✓ FAISS index saved to utils/vector_store/

Total Time: ~10-15 minutes (depends on number of files)
```

**IMPORTANT**: This must be run manually whenever:
- New companies are added to the system
- Financial data is updated (quarterly, annually)
- New SEC filings are processed

---

## Setup & Configuration

### Prerequisites

- Python 3.10+
- Azure OpenAI account with deployments:
  - `gpt-4.1` for chat
  - `gpt-4.1-mini` for data lineage
  - `text-embedding-ada-002` for embeddings
- SEC-API.io account (for SEC filing access)
- Azure Blob Storage account (optional, for cloud storage)

### Installation

```bash
# Clone repository
git clone <repository-url>
cd pgim-dealio-main

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Configuration

Create `.env` file in root directory:

```bash
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-instance.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4.1
AZURE_OPENAI_CHAT_DEPLOYMENT_NAME=gpt-4.1
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-ada-002
AZURE_API_VERSION=2024-12-01-preview
AZURE_OPENAI_MAX_TOKENS=4096
AZURE_OPENAI_TEMPERATURE=0.0

# SEC API
SEC_API_KEY=your-sec-api-key

# Azure Blob Storage (optional)
AZURE_STORAGE_CONNECTION_STRING=your-connection-string

# Application
APP_BASE_URL=http://127.0.0.1:9259
```

### Running the Application

```bash
# Start FastAPI server
python app.py

# Server starts at http://localhost:9259
# Dashboard at http://localhost:9259/dashboard
```

### Initial Setup Tasks

1. **Create FAISS Index**:
```bash
# Must be run before using On-Demand Insights
python src/on_demand_insights/document_processor.py
```

2. **Process Initial Companies**:
```python
# In Python or via API
import requests

# Process a company
requests.post("http://localhost:9259/api/v1/hfa", json={"ticker": "ELME"})
```

3. **Generate FSA** (if needed):
```python
requests.post("http://localhost:9259/api/v1/fsa", json={"ticker": "ELME"})
```

### Directory Permissions

Ensure write permissions for:
- `output/` - All generated outputs
- `logs/` - Calculation logs
- `data/` - SEC filing PDFs
- `utils/vector_store/` - FAISS index
- `utils/chat/` - Chat history

---

## Troubleshooting

### Common Issues

**1. "FAISS index not found" error in ODI**
- **Cause**: `document_processor.py` has not been run
- **Solution**: Run `python src/on_demand_insights/document_processor.py`

**2. "SEC_API_KEY must be set" error**
- **Cause**: Missing SEC API key in `.env`
- **Solution**: Add `SEC_API_KEY=your-key` to `.env` file

**3. "No 10-K filing found for ticker" error**
- **Cause**: Company doesn't exist or ticker misspelled
- **Solution**: Verify ticker symbol at sec.gov

**4. LLM returns non-JSON response**
- **Cause**: Prompt may be ambiguous or model hallucinating
- **Solution**: Check prompt template, verify temperature=0.0

**5. AQRR generation times out**
- **Cause**: One component is taking too long (usually COMP with many peers)
- **Solution**: Increase timeout or reduce number of peer companies

**6. "Mapping error" in HFA**
- **Cause**: Calculation formula references non-existent XBRL key
- **Solution**: Regenerate mapping by deleting cached entry in `mapping_calculation.json`

---

## Summary

This system is a comprehensive financial analysis automation platform that:

1. **Fetches** SEC financial data via EDGAR API
2. **Processes** XBRL data into structured formats
3. **Uses LLMs** to generate calculation mappings and extract unstructured data
4. **Computes** 60+ financial metrics across 5 components
5. **Tracks** complete data lineage for every calculation
6. **Composes** professional PDF and Word reports
7. **Provides** interactive RAG-based Q&A

**Key Strengths**:
- **Automated**: Minimal human intervention required
- **Traceable**: Complete data lineage from source to output
- **Flexible**: LLM-based mapping adapts to different company structures
- **Comprehensive**: Combines quantitative and qualitative analysis
- **Interactive**: RAG system allows ad-hoc questions

**Key Limitations**:
- **Manual FAISS Updates**: Administrators must run `document_processor.py` manually
- **Sequential Processing**: Components run sequentially, not in parallel (by design for safety)
- **Company-Specific Prompts**: CAP and FSA prompts may need customization per company
- **LLM Dependency**: System heavily relies on LLM accuracy

**Total Processing Time** for complete AQRR: **~5-7 minutes**

---

*This document provides a complete technical overview of the PGIM Dealio system. For additional questions, refer to the architecture diagram (`arch.md`) or contact the development team.*
