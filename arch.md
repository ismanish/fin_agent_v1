# Dealio MVP - Solution Architecture Documentation

## Executive Summary

The Dealio MVP is an enterprise-grade, AI-powered financial analysis platform built on Microsoft Azure that automates the generation of Automated Quarterly Research Reports (AQRR) for public companies. The solution leverages serverless computing, cloud storage, and Azure AI services to deliver scalable, secure, and intelligent financial analysis capabilities.

The platform ingests SEC EDGAR filings, processes financial statements, and generates comprehensive analytical outputs including Historical Financial Analysis (HFA), Capitalization Tables (CAP), Comparable Company Analysis (COMP), Financial Statement Analysis (FSA), and Credit Risk Metrics. All components are orchestrated through a unified API layer with robust AI governance and security controls.

---

## System Overview

### Architecture Principles

1. **Serverless-First**: Leverages Azure Functions for elastic scaling and cost optimization
2. **API-Driven**: RESTful API design enables modular integration and extensibility
3. **Cloud-Native**: Built entirely on Azure PaaS services for high availability and minimal operational overhead
4. **AI-Augmented**: Azure OpenAI integration provides intelligent data extraction and analysis
5. **Security by Design**: Multi-layer security with authentication, secrets management, and data lineage tracking
6. **Observable**: Comprehensive logging to Azure Blob Storage for audit trails and debugging

### High-Level Data Flow

```
User Request → Azure Static Web Apps (Frontend)
    ↓
Azure Functions (Backend Logic)
    ↓
SEC EDGAR API (External Data Source) ← Azure Key Vault (Credentials)
    ↓
Azure Blob Storage (Raw Data)
    ↓
Processing Pipeline (Data Transformation)
    ↓
Azure OpenAI (AI/LLM Analysis) ← Azure AI Foundry
    ↓
Azure Blob Storage (Processed Outputs + Logs)
    ↓
Response to User
```

---

## Architecture Components

### 1. Presentation Layer

#### Azure Static Web Apps
- **Purpose**: Hosts the client-side web application (HTML, CSS, JavaScript)
- **Features**:
  - Single-page application (SPA) for AQRR generation workflow
  - Authentication integration with backend APIs
  - Direct access to Azure Blob Storage for file downloads
  - Responsive dashboard for company selection and analysis requests

- **Implementation Details**:
  - Directory: `client/templates/`, `client/static/`
  - Login page: `client/templates/login.html`
  - Dashboard: `client/templates/index.html`
  - Protected routes with cookie-based authentication

---

### 2. Compute Layer

#### Azure Functions (Serverless Backend)

The backend is implemented using both a FastAPI application (`app.py`) and Azure Functions for specific workloads.

##### **Primary API Application** (`app.py`)
- **Hosting**: Can be deployed as Azure App Service or Container Instance
- **Port**: 9259 (configurable)
- **Framework**: FastAPI with Uvicorn ASGI server

##### **Azure Functions** (Directory: `azure-functions/`)

###### **HFA Function** (`HFAFunction/__init__.py`)
- **Trigger**: HTTP POST
- **Purpose**: Historical Financial Analysis generation
- **Input**: `{"ticker": "ELME", "filing": "10-K"}`
- **Process**:
  1. Receives ticker symbol from user request
  2. Retrieves latest HFA output from Azure Blob Storage
  3. Returns JSON and CSV outputs with blob URLs
- **Logging**: Integrated with Azure Blob Storage logging
- **File**: `azure-functions/HFAFunction/__init__.py`

###### **CapTable Function** (`CapTableFunction/__init__.py`)
- **Trigger**: HTTP POST
- **Purpose**: Capitalization table generation
- **Input**: `{"ticker": "ELME"}`
- **Process**:
  1. Extracts PDF text from SEC filings (10-K, 10-Q)
  2. Uses Azure OpenAI to structure cap table data
  3. Saves JSON and CSV outputs to blob storage
- **File**: `azure-functions/CapTableFunction/__init__.py`

##### **API Endpoints** (Implemented in `app.py`)

###### **Quantitative Endpoints**

1. **HFA Generation** - `POST /api/v1/hfa`
   - Full end-to-end HFA workflow
   - Implementation: `src/build_hfa_log.py:build_hfa_outputs()`
   - Orchestrates: filing fetch, processing, LLM mapping, computation

2. **Cap Table Generation** - `POST /api/v1/cap-table`
   - PDF parsing and LLM-based extraction
   - Implementation: `src/build_cap_log.py:build_cap_table()`

3. **Comparable Analysis** - `POST /api/v1/comp`
   - Peer discovery via Finnhub API
   - LTM and 3-year average metrics computation
   - Implementation: `src/comp_analysis_log.py:run_comp_analysis()`

4. **Financial Statement Analysis** - `POST /api/v1/fsa`
   - LLM-based qualitative analysis of financial statements
   - Implementation: `src/fsa.py:analyze_ticker()`

5. **Credit Risk Metrics** - `POST /api/v1/credit_table`
   - Credit risk assessment and metrics computation
   - Implementation: `src/credit_risk_metrics.py:generate_credit_risk_metrics()`

6. **SEC Filings Fetch** - `POST /api/v1/filings`
   - Fetches 10-K, 10-Q, 8-K filings from SEC EDGAR
   - Implementation: `src/sec_filing.py:get_financial_statements()`

7. **Data Processing** - `POST /api/v1/process`
   - Transforms raw SEC data into processed JSON/CSV
   - Implementation: `src/data_manipulation.py:process_all_filings()`

###### **Qualitative Endpoints (On-Demand Insights)**

8. **On-Demand Insights (RAG-based Q&A)** - `POST /api/v1/odi/chat/message`
   - Context-aware financial Q&A using RAG
   - Implementation: `src/on_demand_insights/chat_engine.py:chat()`
   - Uses FAISS vector database for semantic search
   - Maintains conversation history per ticker

9. **Query Endpoint** - `POST /api/v1/query`
   - Simplified wrapper for ODI chat system
   - Maps to internal ODI chat endpoints

###### **AQRR Composer Endpoints**

10. **AQRR PDF Generation** - `POST /api/v1/aqrr-pdf`
    - Composes final AQRR report in PDF format
    - Implementation: `src/aqrr_pdf_generate.py:build_pdf_bytes_from_ticker()`
    - Combines HFA, CAP, COMP, FSA outputs

11. **AQRR Word Generation** - `POST /api/v1/aqrr-word`
    - Generates AQRR in Microsoft Word format
    - Implementation: `src/aqrr_word_generate.py:build_word_bytes_from_ticker()`

12. **AQRR PDF + Word Generation** - `POST /api/v1/aqrr-pdf-word`
    - Generates both PDF and Word formats in a single API call
    - Optimized to fetch data once and generate both outputs

---

### 3. Data Layer

#### Azure Blob Storage

The solution uses Azure Blob Storage for persistent storage across multiple containers:

##### **Container: `hfa-outputs`**
- Stores Historical Financial Analysis outputs
- Structure: `{ticker}/HFA_{ticker}_{timestamp}.{json|csv}`
- Implementation: `utils/azure_blob_storage.py:upload_hfa_output()`

##### **Container: `cap-outputs`**
- Stores Capitalization Table outputs
- Structure: `{ticker}/CAP_{ticker}_{timestamp}.{json|csv}`
- Implementation: `utils/azure_blob_storage.py:upload_cap_output()`

##### **Container: `comp-outputs`**
- Stores Comparable Analysis outputs
- Structure: `{ticker}/COMP_{ticker}_{timestamp}.{json|csv}`
- Implementation: `utils/azure_blob_storage.py:upload_comp_output()`

##### **Container: `outputs`**
- General outputs including credit risk metrics
- Structure: `json/credit_risk_analysis/{ticker}_CREDIT.json`
- Implementation: `utils/azure_blob_storage.py:upload_credit_risk_output()`

##### **Container: `logs`**
- Centralized logging for all operations
- Structure: `{LOG_TYPE}/{LOG_TYPE}_{ticker}_{timestamp}.json`
- Log types: HFA, COMP, CAP, FSA
- Purpose: Audit trails, debugging, data lineage tracking
- Implementation: `azure-functions/shared_code/logging_to_blob.py`

##### **Local Data Storage** (`output/` directory)
- **Raw SEC API Data**: `output/json/raw_sec_api/`
  - Cached SEC filing responses
  - Format: `{ticker}_10-K_{year}_{statement}.json`

- **Processed Data**: `output/json/llm_input_processed/`
  - Transformed and normalized financial data
  - Per-ticker directories with combined annual and quarterly JSON

- **HFA Outputs**: `output/json/hfa_output/` and `output/csv/HFA/`
- **Cap Table Outputs**: `output/json/cap_table/` and `output/csv/cap_table/`
- **Comparable Analysis**: `output/json/comp/` and `output/csv/comp/`
- **FSA Outputs**: `output/json/financial_analysis/`
- **AQRR Outputs**: `output/pdf/AQRR/` and `output/word/AQRR/`

---

### 4. AI/ML Layer

#### Azure AI Foundry

Azure AI Foundry provides the enterprise AI capabilities for the platform.

##### **Azure OpenAI Service**

###### **Model Deployments**
- **Chat Model**: `gpt-4.1` (configurable)
  - Used for: LLM mapping, FSA analysis, cap table extraction, ODI chat
  - Endpoint: Configured via `AZURE_OPENAI_ENDPOINT`
  - API Version: `2024-12-01-preview`

- **Embedding Model**: Configured via `AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME`
  - Used for: Vector embeddings in RAG system
  - Powers semantic search in On-Demand Insights

###### **LLM Mapping Service** (`src/llm.py`)
- **Purpose**: Translates financial statement line items to AQRR metrics
- **Process**:
  1. Loads AQRR key schema from `static/aqrr_key_schema.yaml`
  2. Sends processed financial JSON to Azure OpenAI
  3. Receives calculation formulas for each metric
  4. Caches results in `utils/mapping_calculation.json`
- **Prompt Management**: `utils/prompt.yaml`, `utils/cap_prompt.yaml`, `utils/comp_prompt.yaml`

##### **RAG System (Research RAG)**

###### **Document Processing** (`src/on_demand_insights/document_processor.py`)
- Converts financial JSON files to vector embeddings
- Stores embeddings in local FAISS index
- Metadata: ticker, report_type, fiscal_period

###### **Chat Engine** (`src/on_demand_insights/chat_engine.py`)
- Implements Retrieval-Augmented Generation (RAG)
- **Components**:
  1. **Vector Store**: FAISS index in `utils/vector_store/`
  2. **Embeddings**: Azure OpenAI Embeddings API
  3. **LLM**: Azure OpenAI Chat Completions
  4. **Memory**: Per-ticker chat history in `utils/chat/{ticker}.json`

- **Query Process**:
  1. User submits financial question
  2. System performs semantic search on FAISS index (filtered by ticker)
  3. Retrieves top-k relevant context chunks (default k=5)
  4. Formats prompt with context + chat history + user query
  5. Generates response via Azure OpenAI
  6. Saves conversation to chat history

- **Prompt Template**: `utils/odi_prompt.yaml`

##### **Azure AI Safety Context**
- Content filtering and guardrails
- Configured at the Azure OpenAI deployment level
- Ensures responsible AI practices

---

### 5. Security & Secrets Management

#### Azure Key Vault

While the diagram shows Azure Key Vault, the current implementation uses environment variables for secrets management:

- `SEC_API_KEY`: SEC Edgar API authentication
- `AZURE_OPENAI_API_KEY`: Azure OpenAI service authentication
- `AZURE_OPENAI_ENDPOINT`: Azure OpenAI service endpoint
- `AZURE_STORAGE_CONNECTION_STRING`: Blob Storage connection
- `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`: Service Principal authentication
- `FINNHUB_API_KEY`: Finnhub API for peer discovery (COMP analysis)

**Production Recommendation**: Migrate to Azure Key Vault for enhanced security:
- Secrets rotation
- Access control via Managed Identity
- Audit logging

---

### 6. AI Governance Layer

The platform implements a multi-faceted AI governance framework:

#### **Authentication** (`src/Authentication/`)

##### **User Authentication** (`app.py:login()`)
- Cookie-based session management
- Credentials stored in-memory (VALID_CREDENTIALS dictionary)
- Token generation using `secrets.token_urlsafe(32)`
- HTTP-only cookies for dashboard access
- **Endpoints**:
  - `POST /api/v1/auth/login`
  - `POST /api/v1/auth/logout`
  - `GET /api/v1/auth/verify`

##### **Azure Service Principal Authentication** (`src/Authentication/azure_auth.py`)
- Used for Azure resource access
- Implements Azure Identity SDK
- Configured via environment variables

**Production Recommendation**:
- Replace in-memory credentials with Azure AD B2C
- Implement JWT-based authentication
- Add role-based access control (RBAC)

#### **Data Lineage** (`src/agents/data_lineage_agent.py`)

- **Purpose**: Provides transparency into data transformations and AI decisions
- **Implementation**:
  - Chat interface for querying processing logs
  - Retrieves HFA, COMP, CAP logs from Azure Blob Storage
  - Combines logs into context for Azure OpenAI
  - Allows users to ask: "How was this metric calculated?" or "What data sources were used?"

- **Endpoints**:
  - `POST /api/v1/lineage/chat/start`: Initializes lineage session
  - `POST /api/v1/lineage/chat/message`: Query lineage information

- **System Prompt**: `utils/data-lineage-agent-prompt.yaml`

#### **Oversight**

##### **Logging** (`azure-functions/shared_code/logging_to_blob.py`)
- Comprehensive operation logging to Azure Blob Storage
- Structured JSON logs with timestamps
- Logs include:
  - Input parameters
  - Processing steps
  - LLM prompts and responses
  - Calculation mappings
  - Output file locations
  - Error traces

##### **Guardrails and Meta Prompting**

###### **System Prompts**
Located in `utils/` directory:
- `prompt.yaml`: Core AQRR mapping prompt
- `cap_prompt.yaml`: Cap table extraction prompt
- `comp_prompt.yaml`: Comparable analysis prompt
- `odi_prompt.yaml`: On-Demand Insights system prompt
- `data-lineage-agent-prompt.yaml`: Data lineage agent prompt

###### **Prompt Engineering Principles**
- Strict output format requirements (JSON schemas)
- Chain-of-thought reasoning for complex calculations
- Explicit instructions to avoid hallucination
- Context window management (token limits)

###### **Guardrails Implementation**
- Input validation (ticker format, filing types, quarters)
- Output validation (JSON schema compliance)
- Error handling with fallback mechanisms
- Cache checks to avoid redundant LLM calls
- Temperature setting: 0.0 for deterministic financial calculations

---

## Data Flow Pipelines

### End-to-End AQRR Generation Workflow

```
1. User selects company ticker (e.g., "ELME")
   ↓
2. Frontend sends POST request to /api/v1/aqrr-pdf-word
   ↓
3. Backend triggers sequential API calls:
   a. POST /api/v1/hfa (Historical Financial Analysis)
   b. POST /api/v1/cap-table (Capitalization Table)
   c. POST /api/v1/comp (Comparable Analysis)
   d. POST /api/v1/fsa (Financial Statement Analysis)
   e. POST /api/v1/credit_table (Credit Risk Metrics)
   ↓
4. Each API endpoint executes:
   a. Fetch raw SEC filings from SEC EDGAR API (or cache)
   b. Save raw JSON to output/json/raw_sec_api/
   c. Process raw data → output/json/llm_input_processed/
   d. Generate or retrieve LLM mapping (utils/mapping_calculation.json)
   e. Compute metrics/analysis
   f. Upload outputs to Azure Blob Storage
   g. Save logs to Azure Blob Storage (logs container)
   ↓
5. AQRR Composer (src/aqrr_pdf_generate.py or src/aqrr_word_generate.py):
   a. Fetches all generated outputs
   b. Combines into unified report structure
   c. Generates PDF/Word document
   d. Saves to output/pdf/AQRR/ or output/word/AQRR/
   ↓
6. Returns download URL to user
```

### HFA (Historical Financial Analysis) Pipeline

```
Input: {"ticker": "ELME"}
   ↓
1. Filing Fetch (src/sec_filing.py)
   - Fetch 10-K: 2020, 2022, 2024
   - Fetch 10-Q: 2024-Q1, 2024-Q2, 2024-Q3, 2025-Q1
   - Cache check: output/json/raw_sec_api/
   - Save raw: income_statement.json, balance_sheet.json, cash_flow.json
   ↓
2. Data Processing (src/data_manipulation.py)
   - Combine 10-K data (2020-2024)
   - Periodize 10-Q data (per quarter)
   - Output: output/json/llm_input_processed/{ticker}/
   ↓
3. LLM Mapping (src/llm.py)
   - Load AQRR schema: static/aqrr_key_schema.yaml
   - Check cache: utils/mapping_calculation.json
   - If cache miss:
     * Send processed JSON to Azure OpenAI
     * Receive calculation formulas
     * Save to cache
   ↓
4. HFA Computation (src/build_hfa_log.py)
   - Load mappings from cache
   - Load CSV data for required periods
   - Compute:
     * Annual metrics (2020, 2022, 2024)
     * YTD 2024, YTD 2025
     * LTM 2025 (FY2024 + YTD2025 - YTD2024)
   - Generate HFA table
   ↓
5. Output & Upload
   - Save JSON: output/json/hfa_output/{ticker}_HFA.json
   - Save CSV: output/csv/HFA/{ticker}_HFA.csv
   - Upload to Azure Blob: hfa-outputs container
   - Upload logs: logs container (HFA/{ticker}_{timestamp}.json)
   ↓
Output: {
  "status": "ok",
  "ticker": "ELME",
  "blob_urls": {...},
  "rows": [...]
}
```

### CAP (Capitalization Table) Pipeline

```
Input: {"ticker": "ELME"}
   ↓
1. PDF Text Extraction (src/build_cap_log.py)
   - Read PDF files:
     * data/{ticker}/10k.pdf
     * data/{ticker}/10q.pdf
   - Extract text using PyMuPDF (fitz)
   ↓
2. Prompt Construction
   - Load base prompt from utils/cap_prompt.yaml
   - Add ticker-specific instructions (if exists)
   - Combine with extracted text
   ↓
3. LLM Processing (Azure OpenAI)
   - Send prompt to GPT-4
   - Request structured JSON response
   - Schema: shares, debt, convertible notes, options, etc.
   ↓
4. Post-Processing
   - Validate JSON structure
   - Compute totals and ratios
   - Convert to CSV format
   ↓
5. Output & Upload
   - Save JSON: output/json/cap_table/{ticker}_CAP.json
   - Save CSV: output/csv/cap_table/{ticker}_CAP.csv
   - Upload to Azure Blob: cap-outputs container
   - Upload logs: logs container (CAP/{ticker}_{timestamp}.json)
   ↓
Output: {
  "status": "ok",
  "ticker": "ELME",
  "blob_urls": {...},
  "json_data": {...}
}
```

### COMP (Comparable Analysis) Pipeline

```
Input: {"ticker": "PAYX"}
   ↓
1. Peer Discovery (src/comp_analysis_log.py)
   - Call Finnhub API: company_peers(ticker)
   - Include input ticker
   - Limit to 5 companies
   - Tickers: ["PAYX", "ADP", "CDAY", "PCTY", "WDAY"]
   ↓
2. Data Collection (for each ticker)
   - Fetch 10-K: 2022, 2023, 2024
   - Fetch 10-Q: 2024-Q1, 2025-Q1
   - Process into combined JSON
   ↓
3. LLM Mapping (src/llm.py)
   - Load comp prompt: utils/comp_prompt.yaml
   - Generate calculation formulas for:
     * Revenue, EBITDA, EBITDAR
     * Interest, Rents, Total Debt, COL
     * Free Cash Flow (FCF)
   - Cache: utils/comp_mapping.json
   ↓
4. Metrics Computation
   - LTM Calculation: FY2024 + YTD2025 - YTD2024
   - Ratios:
     * EBITDA Margin %
     * EBITDAR / (Interest + Rents)
     * (Total Debt + COL) / EBITDAR
     * (Net Debt + COL) / EBITDAR
     * (Total Debt + COL) / Total Capitalization
     * (FCF + Rents) / (Total Debt + COL)
   - 3-Year Averages (FY 2022-2024)
   ↓
5. Aggregation
   - Create row per ticker
   - Add AVERAGE row (mean across tickers)
   - Add MEDIAN row
   ↓
6. Output & Upload
   - Save JSON: output/json/comp/{ticker}_2025_Q1.json
   - Save CSV: output/csv/comp/{ticker}_2025_Q1.csv
   - Upload to Azure Blob: comp-outputs container
   - Upload logs: logs container (COMP/{ticker}_{timestamp}.json)
   ↓
Output: {
  "status": "ok",
  "ticker": "PAYX",
  "tickers": [...],
  "rows": [...],
  "blob_urls": {...}
}
```

### FSA (Financial Statement Analysis) Pipeline

```
Input: {"ticker": "ELME"}
   ↓
1. RAG Context Retrieval (src/fsa.py → src/rag_query.py)
   - Query FAISS vector database
   - Retrieve relevant financial statement chunks
   - Filter by ticker
   ↓
2. LLM Analysis (Azure OpenAI)
   - System prompt: Financial analyst role
   - Context: Retrieved chunks + full JSON data
   - User query: Predefined FSA questions
   - Temperature: 0.0 (deterministic)
   ↓
3. Response Processing
   - Parse LLM output
   - Extract JSON structure
   - Clean and validate
   ↓
4. Output & Upload
   - Save JSON: output/json/financial_analysis/{ticker}_FSA.json
   - Upload logs: logs container
   ↓
Output: {
  "status": "ok",
  "ticker": "ELME",
  "analysis_response_json": {...}
}
```

### On-Demand Insights (ODI) Pipeline

```
Input: {
  "ticker": "ELME",
  "message": "What drove revenue growth in 2024?"
}
   ↓
1. Session Management
   - Load chat history: utils/chat/{ticker}.json
   - Format previous conversation
   ↓
2. RAG Retrieval (src/on_demand_insights/chat_engine.py)
   - Embed user query (Azure OpenAI Embeddings)
   - Semantic search on FAISS index
   - Filter: ticker = "ELME"
   - Retrieve top-5 chunks with scores
   ↓
3. Prompt Construction
   - System prompt: utils/odi_prompt.yaml
   - Variables:
     * company_ticker
     * relevant_context_from_rag
     * financial_statements_json (full data)
     * chat_history
     * user_query
   ↓
4. LLM Generation (Azure OpenAI)
   - Model: gpt-4.1
   - Temperature: 0.0
   - Messages:
     * System: Formatted prompt with all context
     * User: Current query
   ↓
5. Memory Update
   - Append user message to history
   - Append assistant response to history
   - Save: utils/chat/{ticker}.json
   ↓
Output: {
  "ticker": "ELME",
  "reply": "Revenue growth in 2024 was primarily driven by..."
}
```

---

## Technology Stack

### Cloud Infrastructure
- **Platform**: Microsoft Azure
- **Hosting**: Azure Static Web Apps, Azure Functions (or Azure App Service)
- **Storage**: Azure Blob Storage
- **Secrets**: Environment variables (migration to Azure Key Vault recommended)
- **AI Services**: Azure OpenAI Service (Azure AI Foundry)

### Backend Technologies
- **Language**: Python 3.9+
- **Web Framework**: FastAPI 0.104+
- **ASGI Server**: Uvicorn
- **Serverless**: Azure Functions Python Runtime

### AI/ML Stack
- **LLM Provider**: Azure OpenAI
- **Models**: GPT-4.1 (chat), Embeddings model
- **Vector Database**: FAISS (Facebook AI Similarity Search)
- **Embeddings Framework**: LangChain Community
- **RAG Implementation**: Custom (LangChain + FAISS + Azure OpenAI)

### Data Processing
- **Data Validation**: Pydantic v2
- **HTTP Client**: Requests library
- **PDF Parsing**: PyMuPDF (fitz)
- **CSV/Excel**: Pandas
- **YAML Parsing**: PyYAML

### External APIs
- **SEC EDGAR**: sec-api.io (SEC_API_KEY required)
- **Finnhub**: finnhub.com (peer discovery for COMP analysis)

### Security & Authentication
- **Azure SDK**: azure-identity, azure-storage-blob
- **Token Generation**: secrets module (Python standard library)
- **Session Management**: HTTP-only cookies

### Development Tools
- **Environment Management**: python-dotenv
- **Type Hints**: Python typing module
- **Logging**: Python logging module + custom blob logging

---

## Scalability & Performance Considerations

### Current Architecture Strengths

1. **Serverless Scaling**: Azure Functions automatically scale based on request load
2. **Caching Strategy**:
   - Raw SEC filings cached locally (`output/json/raw_sec_api/`)
   - LLM mappings cached (`utils/mapping_calculation.json`)
   - Reduces API calls and improves response time
3. **Asynchronous Processing**: FastAPI async endpoints enable concurrent request handling
4. **Blob Storage**: Horizontally scalable storage for outputs and logs

### Performance Optimization Opportunities

1. **LLM Token Usage**:
   - **Challenge**: Large context windows for financial JSON data
   - **Solution**: Implement prompt compression or summarization
   - **Benefit**: Reduced Azure OpenAI costs and latency

2. **Vector Database**:
   - **Current**: Local FAISS index
   - **Recommendation**: Migrate to Azure Cognitive Search or Azure AI Search
   - **Benefit**: Distributed search, better scalability, managed service

3. **Parallel Processing**:
   - **Current**: Sequential API calls in AQRR generation
   - **Recommendation**: Implement parallel execution for HFA, CAP, COMP, FSA
   - **Benefit**: Reduced total generation time (potential 3-4x speedup)

4. **API Rate Limiting**:
   - **Recommendation**: Implement rate limiting and throttling
   - **Tools**: Azure API Management or FastAPI middleware
   - **Benefit**: Protect backend from abuse, ensure fair usage

5. **CDN Integration**:
   - **Recommendation**: Use Azure CDN for static assets and generated reports
   - **Benefit**: Global distribution, reduced latency for end users

---

## Security Architecture

### Current Security Measures

1. **Authentication**:
   - Cookie-based session management
   - Token validation on protected routes
   - Logout endpoint with token invalidation

2. **Secrets Management**:
   - Environment variables for API keys
   - Connection strings stored securely
   - No hardcoded credentials in codebase

3. **Network Security**:
   - HTTPS enforcement (SSL configured)
   - HTTP-only cookies (prevents XSS attacks)
   - Secure cookie attributes (SameSite=Lax)

4. **Data Security**:
   - Azure Blob Storage encryption at rest
   - Secure transmission (TLS 1.2+)
   - Access control via connection strings

### Security Recommendations for Production

1. **Identity & Access Management**:
   - Migrate to Azure AD B2C for user authentication
   - Implement OAuth 2.0 / OpenID Connect
   - Add multi-factor authentication (MFA)
   - Implement role-based access control (RBAC)

2. **Secrets Management**:
   - **Critical**: Migrate to Azure Key Vault
   - Use Managed Identity for Azure Functions
   - Implement secrets rotation policies
   - Audit access to secrets

3. **Network Security**:
   - Deploy Azure Application Gateway with WAF (Web Application Firewall)
   - Implement DDoS protection
   - Use Azure Private Link for backend services
   - Restrict Blob Storage access to specific VNets

4. **Data Protection**:
   - Implement data classification (PII, financial data)
   - Enable Azure Blob Storage soft delete
   - Implement backup and disaster recovery
   - Add data retention policies

5. **Monitoring & Compliance**:
   - Enable Azure Security Center
   - Implement Azure Sentinel for SIEM
   - Set up alerts for suspicious activity
   - Maintain audit logs (SOC 2, GDPR compliance)

---

## Deployment Architecture

### Recommended Production Deployment

```
Internet
    ↓
Azure Front Door (CDN + WAF)
    ↓
Azure Static Web Apps (Frontend)
    |
    ↓
Azure Application Gateway
    ↓
[Azure Functions] ←→ [Azure App Service]
    ↓
Azure Virtual Network (VNet)
    |
    ├─→ Azure OpenAI (Private Endpoint)
    ├─→ Azure Blob Storage (Private Endpoint)
    ├─→ Azure Key Vault (Private Endpoint)
    └─→ Azure Cognitive Search (Future: Vector DB)
```

### Continuous Integration / Continuous Deployment (CI/CD)

**GitLab CI/CD** (`.gitlab-ci.yml` present)

Recommended pipeline stages:
1. **Build**: Install dependencies, run linters
2. **Test**: Unit tests, integration tests
3. **Security Scan**: Dependency vulnerability scanning
4. **Deploy to Staging**: Azure Functions deployment
5. **Integration Tests**: API endpoint validation
6. **Deploy to Production**: Blue-green deployment
7. **Post-Deployment**: Health checks, smoke tests

---

## Monitoring & Observability

### Current Logging Implementation

- **Blob Logging**: All operations logged to `logs` container
- **Structured Logs**: JSON format with timestamps
- **Log Types**: HFA, COMP, CAP, FSA logs
- **Implementation**: `azure-functions/shared_code/logging_to_blob.py`

### Recommended Monitoring Stack

1. **Azure Application Insights**:
   - Request telemetry
   - Dependency tracking (Azure OpenAI, SEC API)
   - Exception logging
   - Custom metrics

2. **Azure Log Analytics**:
   - Centralized log aggregation
   - KQL (Kusto Query Language) queries
   - Dashboard creation

3. **Key Metrics to Track**:
   - API response times (p50, p95, p99)
   - Azure OpenAI token usage and costs
   - SEC API rate limit consumption
   - Blob Storage throughput
   - Error rates by endpoint
   - User authentication failures

4. **Alerting**:
   - High error rate alerts
   - Azure OpenAI quota alerts
   - Storage capacity alerts
   - Slow query alerts (>30s)

---

## Cost Optimization

### Current Cost Drivers

1. **Azure OpenAI**: Token usage (input + output tokens)
2. **Azure Blob Storage**: Storage volume + transactions
3. **Azure Functions**: Execution time + memory consumption
4. **SEC API**: Potential API usage fees
5. **Finnhub API**: Peer discovery API calls

### Cost Optimization Strategies

1. **LLM Cost Reduction**:
   - Implement aggressive caching (already done)
   - Use smaller models where possible (gpt-4-mini)
   - Optimize prompts to reduce output tokens
   - Batch requests when possible

2. **Storage Optimization**:
   - Implement lifecycle policies (move to cool tier after 30 days)
   - Compress large JSON files
   - Delete temporary files after AQRR generation

3. **Compute Optimization**:
   - Use Azure Functions Consumption Plan (pay-per-execution)
   - Optimize function execution time
   - Reduce cold start times (function warm-up)

4. **API Rate Limiting**:
   - Implement request throttling
   - Cache external API responses
   - Use free tier APIs where available

---

## Future Enhancements

### Short-Term (Next 3-6 Months)

1. **Azure Key Vault Integration**: Migrate all secrets to Key Vault
2. **Azure AD B2C Authentication**: Replace custom auth with enterprise SSO
3. **API Rate Limiting**: Implement request throttling
4. **Enhanced Error Handling**: Retry logic for transient failures
5. **Unit Tests**: Increase test coverage to >80%

### Medium-Term (6-12 Months)

1. **Azure Cognitive Search**: Replace local FAISS with managed vector database
2. **Real-Time Notifications**: WebSocket support for long-running operations
3. **Batch Processing**: Support bulk AQRR generation for multiple tickers
4. **Advanced RAG**: Multi-modal RAG with charts and tables
5. **API Versioning**: Support multiple API versions

### Long-Term (12+ Months)

1. **Multi-Tenant Architecture**: Support multiple client organizations
2. **Custom Model Training**: Fine-tune models on proprietary financial data
3. **Mobile App**: iOS and Android clients
4. **Advanced Analytics**: Trend analysis, predictive modeling
5. **Integration Marketplace**: Connect to Bloomberg, FactSet, Refinitiv

---

## Conclusion

The Dealio MVP represents a modern, cloud-native financial analysis platform that successfully leverages Azure's PaaS services and AI capabilities. The architecture demonstrates:

- **Scalability**: Serverless functions and cloud storage enable elastic scaling
- **Intelligence**: Azure OpenAI provides advanced NLP and data extraction
- **Security**: Multi-layer security with authentication and data lineage
- **Observability**: Comprehensive logging enables debugging and audit trails
- **Maintainability**: Modular design with clear separation of concerns

The platform is production-ready with the recommended enhancements outlined in the Security and Future Enhancements sections. The serverless architecture ensures cost-effective scaling, while the AI governance layer provides transparency and compliance capabilities essential for enterprise financial applications.

---

## Appendix: Key File Locations

### Backend Core
- `app.py`: Main FastAPI application (lines 1-1049)
- `azure-functions/HFAFunction/__init__.py`: HFA Azure Function
- `azure-functions/CapTableFunction/__init__.py`: Cap Table Azure Function

### Data Processing
- `src/sec_filing.py`: SEC EDGAR data fetching
- `src/data_manipulation.py`: Raw data processing
- `src/build_hfa_log.py`: HFA computation logic
- `src/build_cap_log.py`: Cap table generation
- `src/comp_analysis_log.py`: Comparable analysis
- `src/fsa.py`: Financial statement analysis
- `src/credit_risk_metrics.py`: Credit risk computation

### AI/ML Components
- `src/llm.py`: Azure OpenAI integration and LLM mapping
- `src/on_demand_insights/chat_engine.py`: RAG-based Q&A system
- `src/on_demand_insights/document_processor.py`: Vector embedding generation
- `src/agents/data_lineage_agent.py`: Data lineage tracking

### AQRR Generation
- `src/aqrr_pdf_generate.py`: PDF report generation
- `src/aqrr_word_generate.py`: Word document generation
- `utils/fetch_aqrr_data.py`: Unified data fetching utility

### Storage & Utilities
- `utils/azure_blob_storage.py`: Azure Blob Storage operations
- `azure-functions/shared_code/logging_to_blob.py`: Blob logging implementation
- `azure-functions/shared_code/blob_utils.py`: Blob utility functions

### Configuration
- `utils/prompt.yaml`: Core AQRR mapping prompt
- `utils/cap_prompt.yaml`: Cap table extraction prompt
- `utils/comp_prompt.yaml`: Comparable analysis prompt
- `utils/odi_prompt.yaml`: On-Demand Insights system prompt
- `static/aqrr_key_schema.yaml`: AQRR metrics schema

### Frontend
- `client/templates/login.html`: Login page
- `client/templates/index.html`: Main dashboard
- `client/static/`: Static assets (CSS, JavaScript)

---

**Document Version**: 1.0
**Last Updated**: 2025-10-19
**Author**: Architecture Documentation (Generated based on codebase analysis)
**Contact**: Technical Architecture Team
