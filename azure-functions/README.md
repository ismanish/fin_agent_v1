# PGIM Dealio - Azure Functions

This directory contains Azure Functions for the PGIM Dealio application. These functions provide a scalable, serverless backend for processing financial data and generating analysis outputs.

## Overview

The Azure Functions in this project handle various aspects of financial data processing:

- **HFAFunction**: Historical Financial Analysis function that processes SEC filings and generates HFA outputs
- **CapTableFunction**: Capitalization Table function that generates cap tables for companies

## Prerequisites

- **Azure CLI**: https://learn.microsoft.com/cli/azure/install-azure-cli
- **Azure Functions Core Tools v4**: https://learn.microsoft.com/azure/azure-functions/functions-run-local
- **Python 3.12 (x64)**: https://www.python.org/downloads/
- **Node.js 18+ (LTS)** for Core Tools: https://nodejs.org/
- **PowerShell 7+** (to use `manage.ps1` on Windows): https://learn.microsoft.com/powershell/
- Optional: **Azurite** (local Storage emulator) if not using an actual Storage account locally: https://learn.microsoft.com/azure/storage/common/storage-use-azurite

## Local Development Setup

1. **Clone the repository**:
   ```
   git clone <repository-url>
   cd pgim-dealio
   ```

2. **Set up Python virtual environment**:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```
   cd azure-functions
   pip install -r requirements.txt
   ```

4. **Configure local settings**:
   - Create or edit `azure-functions/local.settings.json` (not checked in for production). Example keys used by these functions:
     - `FUNCTIONS_WORKER_RUNTIME` = `python`
     - `AzureWebJobsStorage` = `UseDevelopmentStorage=true` (or a real connection string)
     - Storage (one of): `AZURE_STORAGE_CONNECTION_STRING` or `AZURE_STORAGE_ACCOUNT`
     - Service Principal (optional; falls back to `DefaultAzureCredential`): `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`
     - Azure subscription id (optional, for scripts): `AZURE_SUBSCRIPTION_ID`
     - Azure OpenAI: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, optional `AZURE_OPENAI_API_KEY`, optional `AZURE_OPENAI_API_VERSION`
     - External APIs as needed: e.g., `SEC_API_KEY`, `FINNHUB_API_KEY`
   - Do not commit real secrets. Prefer environment variables or an untracked `local.settings.json`.
   - Tip: add `local.settings.json` to `.funcignore`/`.gitignore` to avoid accidental check-in or deployment.

5. **Run locally**:
   - Start the host (default port 7071):
     ```
     func start
     ```
   - Or specify a port (e.g., 7073):
     ```
     func start --port 7073
     ```
   - Quick test helper (PowerShell):
     ```
     .\manage.ps1 -Action testLocal -Port 7071 -Ticker ELME
     ```
   The host will start at `http://localhost:<port>`.

## Available Functions

### HFA Function (Historical Financial Analysis)

**Endpoint**: `POST /api/hfa`

**Request Body**:
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
  "filename_csv": "hfa_ELME_10-K_20250925.csv",
  "filename_json": "hfa_ELME_10-K_20250925.json",
  "blob_urls": {
    "json_url": "https://pgimdealio.blob.core.windows.net/hfa-outputs/ELME/hfa_ELME_20250925_123456.json",
    "csv_url": "https://pgimdealio.blob.core.windows.net/hfa-outputs/ELME/hfa_ELME_20250925_123456.csv"
  },
  "rows": [...],
  "warnings": []
}
```

### CAP Table Function (Capitalization Table)

**Endpoint**: `POST /api/cap-table`

**Request Body**:
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
  "filename_csv": "cap_ELME_20250925.csv",
  "filename_json": "cap_ELME_20250925.json",
  "json_data": {...},
  "blob_urls": {
    "json_url": "https://pgimdealio.blob.core.windows.net/cap-outputs/ELME/cap_ELME_20250925_123456.json",
    "csv_url": "https://pgimdealio.blob.core.windows.net/cap-outputs/ELME/cap_ELME_20250925_123456.csv"
  },
  "cached": false
}
```

## Logging

Logs are written to Azure Blob Storage in the `logs` container by `shared_code/logging_to_blob.py`:
- Path format: `logs/{function-name}/{YYYY-MM-DD}/{timestamp}.log`
- Container is auto-created if missing.

To stream logs from a deployed Function App (PowerShell):
```
./manage.ps1 -Action checkLogs -FunctionName HFAFunction
```

## Deployment

Use the PowerShell helper `azure-functions/manage.ps1`. First sign in:

```
az login
```

Default values in the script:
- Resource Group: `PGIM-Dealio`
- Function App: `pgim-dealio`
- Storage Account: `pgimdealio`
- Location: `eastus2`
- Python version: `3.12`

1) Deploy to existing resources:
```
./manage.ps1 -Action deployExisting -ResourceGroup PGIM-Dealio -FunctionAppName pgim-dealio -StorageAccountName pgimdealio
```
This updates app settings from your `local.settings.json` (excluding `FUNCTIONS_WORKER_RUNTIME` and `AzureWebJobsStorage`) and publishes with Core Tools.

2) Create new resources and deploy:
```
./manage.ps1 -Action deployNew -ResourceGroup <rg> -FunctionAppName <func-app> -StorageAccountName <storage> -Location <region>
```

3) Verify deployment and list keys:
```
./manage.ps1 -Action testDeployment -ResourceGroup PGIM-Dealio -FunctionAppName pgim-dealio
```
This prints the Function App URL, lists functions, and shows default function keys.

4) Call deployed endpoints (PowerShell examples):
```
$base = "https://<your-func-app>.azurewebsites.net"
$hfaKey = "<HFAFunction default key>"
$capKey = "<CapTableFunction default key>"

Invoke-RestMethod -Uri "$base/api/hfa" -Method Post -Headers @{ 'Content-Type'='application/json'; 'x-functions-key'=$hfaKey } -Body (ConvertTo-Json @{ ticker='ELME' })
Invoke-RestMethod -Uri "$base/api/cap-table" -Method Post -Headers @{ 'Content-Type'='application/json'; 'x-functions-key'=$capKey } -Body (ConvertTo-Json @{ ticker='ELME' })
```

## Authentication

HTTP triggers are configured with `authLevel: function`. When deployed, include a function key via header `x-functions-key` or query string `?code=...`.

Access to Azure resources uses either:
- Service Principal via `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`; or
- `DefaultAzureCredential` (managed identity, developer login, etc.)

Configure these as Application Settings on the Function App or in `local.settings.json` for local runs.

## Troubleshooting

- **Local start issues**: Ensure Core Tools v4 is installed and the venv is active. Verify `FUNCTIONS_WORKER_RUNTIME=python`.
- **Missing modules**: Re-run `pip install -r requirements.txt` in `azure-functions/`.
- **Auth to Azure services fails**: Confirm SP credentials or that managed identity/`az login` is available to the host.
- **Function keys/401**: Use `x-functions-key` with the correct function’s key when calling deployed endpoints.
- **Permissions**: For `AuthorizationFailed`, review role assignments: `az role assignment list --assignee <principalId or email> --all --output table`.
- **Platform note**: Python Functions are best hosted on Linux plans. The helper script creates a Windows/Node placeholder if needed; for production, prefer a Linux plan with Python runtime.

## Python dependencies

- The Python packages for the Functions host are defined in `azure-functions/requirements.txt`.
- Install locally with:
  ```
  pip install -r requirements.txt
  ```
  Key libraries include: `azure-functions`, `azure-identity`, `azure-storage-blob`, `azure-data-tables`, `openai`, `pandas`, `numpy`, `PyMuPDF`, etc.

