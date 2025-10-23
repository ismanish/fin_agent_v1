# PGIM-Dealio

## Project Structure

The project is organized into a modular structure with clear separation of concerns between backend and frontend components:

### Backend

```
backend/
├── api/                      # API endpoints organized by domain
│   ├── filings.py            # SEC filing endpoints
│   ├── hfa.py                # HFA analysis endpoints
│   ├── comp.py               # Comparable analysis endpoints
│   ├── cap.py                # Cap table endpoints
│   └── lineage.py            # Data lineage endpoints
├── core/                     # Core business logic
│   ├── sec_filing.py         # SEC filing logic
│   ├── data_manipulation.py  # Data processing logic
│   ├── llm.py                # LLM integration
│   ├── build_hfa.py          # HFA building logic
│   ├── build_cap.py          # Cap table building logic
│   ├── comp_analysis.py      # Comparable analysis logic
│   ├── aqrr_pdf_generate.py  # PDF generation logic
│   └── aqrr_word_generate.py # Word document generation logic
├── agents/                   # AI agents
│   └── data_lineage_agent.py # Data lineage agent
├── utils/                    # Utility functions
│   ├── azure_blob_storage.py # Azure storage utilities
│   └── file_utils.py         # File handling utilities
├── config/                   # Configuration management
│   ├── settings.py           # Central settings management
│   ├── company_ticker.json   # Company ticker data
│   ├── comp_mapping.json     # Comparable mapping data
│   ├── schemas/              # Schema definitions
│   │   └── aqrr_key_schema.yaml  # AQRR key schema
│   └── prompts/              # LLM prompts organized by domain
│       ├── cap_prompt.yaml
│       ├── comp_prompt.yaml
│       └── data_lineage_prompt.yaml
├── schemas/                  # Data models and schemas
│   ├── filings.py            # Filing data models
│   ├── hfa.py                # HFA data models
│   └── requests.py           # API request/response models
└── tests/                    # Backend tests
    ├── test_sec_filing.py
    └── test_data_manipulation.py
```

### Frontend

```
frontend/
├── public/                   # Static assets
│   ├── css/                  # CSS stylesheets
│   ├── images/               # Image assets
│   └── js/                   # JavaScript files
├── src/                      # Frontend source code
│   ├── components/           # Reusable UI components
│   │   ├── CompanySelector.js
│   │   ├── PDFViewer.js
│   │   └── LineageChat.js
│   ├── pages/                # Page components
│   │   ├── Analysis.js
│   │   └── Reports.js
│   ├── services/             # API service clients
│   │   ├── api.js            # API client setup
│   │   ├── filings.js        # Filing API client
│   │   └── reports.js        # Reports API client
│   └── utils/                # Frontend utilities
│       └── formatters.js     # Data formatting utilities
├── templates/                # Server-side templates
│   └── index.html            # Main template
└── tests/                    # Frontend tests
```

### Data Storage

```
data/
├── AME/                      # Data for AMETEK INC
│   ├── 10-K_20250918.pdf     # Annual report
│   └── 10-Q_20250918.pdf     # Quarterly report
├── ELME/                     # Data for ELME COMMUNITIES
│   ├── 10-K_20250918.pdf     # Annual report
│   └── 10-Q_20250918.pdf     # Quarterly report
└── [Other companies...]      # Similar structure for other companies
```

### Output Files

```
output/
├── csv/                      # CSV exports
│   ├── A/                    # Company-specific CSVs
│   ├── AME/                  # Company-specific CSVs
│   └── [Other companies...]  # Similar structure for other companies
├── json/                     # JSON outputs
│   ├── cap_table/            # Cap table JSON outputs
│   ├── comp/                 # Comparable analysis JSON outputs
│   ├── financial_analysis/   # Financial analysis JSON outputs
│   ├── raw_sec_api/          # Raw statements saved from filing fetches (cache)
│   └── llm_input_processed/  # Processed, periodized JSON outputs grouped by ticker
└── pdf/                      # PDF reports
    └── AQRR/                 # AQRR PDF reports
```

### Logs

```
logs/
├── CAP/                      # Cap table logs
├── COMP/                     # Comparable analysis logs
└── HFA/                      # Historical Financial Analysis logs
    └── ELME_HFA_2025-09-19_125842.json  # Example log file
```

## Key Components

### API Endpoints

- **Filings API**: Fetch SEC filings (10-K, 10-Q, 8-K)
- **HFA API**: Generate Historical Financial Analysis
- **Comp API**: Generate Comparable Analysis
- **Cap Table API**: Generate Cap Table Analysis
- **Data Lineage API**: Track data sources and transformations

### Core Business Logic

- **SEC Filing**: Fetch filings, normalize/validate, cache-first, auto-save raw data
- **Data Manipulation**: Build combined 10-K (by year range) and per-10Q JSON + CSVs
- **LLM Integration**: Uses Azure OpenAI for financial data analysis
- **HFA Builder**: Build HFA table using financial data and mappings
- **Cap Table Builder**: Generate cap table analysis
- **Comparable Analysis**: Compare financial metrics across similar companies
- **AQRR Generation**: Generate PDF and Word reports for AQRR (Automated Quarterly Research Report)

### AI Agents

- **Data Lineage Agent**: Track and explain data sources and transformations

### Configuration

- **Settings**: Central configuration management
- **Schemas**: Data models and validation schemas
- **Prompts**: LLM prompts for different analysis types

## Features

- **REST API** and **CLI** interfaces
- **Filing types**: 10-K (annual), 10-Q (quarterly), 8-K (current)
- **Normalized inputs**: Standardizes filing types and quarters
- **Cache-first approach**: Skip remote calls if raw files already exist
- **Auto-save raw data**: Save raw statements for future processing
- **LLM-powered analysis**: Use Azure OpenAI for financial metric calculations
- **HFA generation**: Build Historical Financial Analysis tables
- **Comparable Analysis**: Compare financial metrics across similar companies
- **Cap Table Analysis**: Analyze company capitalization structure
- **PDF and Word Report Generation**: Create formatted reports for analysis results
- **Data Lineage**: Track and explain data sources and transformations

## Getting Started

### Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env with required keys
echo "SEC_API_KEY=your_sec_api_key" > .env
echo "AZURE_OPENAI_API_KEY=your_azure_openai_key" >> .env
```

### Start API Server

```bash
python app.py
```

Server runs on: `http://localhost:3030`

## API Documentation

- **Swagger UI**: `http://localhost:3030/docs`
- **ReDoc**: `http://localhost:3030/redoc`

## Dependencies

- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `pydantic` - Data validation
- `requests` - HTTP client
- `python-dotenv` - Environment variables
- `pyyaml` - YAML parsing for prompts and schemas
- `openai` - Azure OpenAI client for LLM mapping
- `reportlab` - PDF generation
- `pymupdf` - PDF manipulation
- `pyPDF2` - PDF processing
- `jinja2` - Templating
- `azure-storage-blob` - Azure Blob Storage integration
- `sec-api` - SEC API client
- `finnhub-python` - Financial data API client
- `pandas` - Data manipulation
- `numpy` - Numerical operations

## Configuration

- **Port**: 3030 (configurable in `app.py`)
- **SSL**: Disabled by default for corporate environments
- **SEC API Key**: `.env` -> `SEC_API_KEY`
- **Azure OpenAI Key**: `.env` -> `AZURE_OPENAI_API_KEY`
