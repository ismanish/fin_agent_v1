param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('deploy','deployExisting','deployNew','checkResources','checkLogs','testLocal','testDeployment','testDeployed','switchMode','fixEmoji')]
    [string]$Action,

    # Common defaults (change as needed)
    [string]$ResourceGroup = 'PGIM-Dealio',
    [string]$FunctionAppName = 'pgim-dealio',
    [string]$StorageAccountName = 'pgimdealio',
    [string]$Location = 'eastus2',
    [string]$PythonVersion = '3.12',

    # Local test
    [string]$Port = '7073',
    [string]$Ticker = 'ELME',

    # Remote test
    [string]$BaseUrl = '',
    [string]$HfaKey = '',
    [string]$CapTableKey = '',

    # Logs
    [string]$FunctionName = 'HFAFunction',
    [int]$Limit = 50,

    # Switch-mode
    [ValidateSet('real','mock')]
    [string]$Mode = 'real',
    [ValidateSet('HFAFunction','CapTableFunction','both')]
    [string]$Function = 'both',

    # Deploy-new toggle
    [switch]$SkipResourceCreation
)

function Ensure-AzLogin {
    $null = az account show 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Not logged in to Azure. Launching az login...' -ForegroundColor Yellow
        az login | Out-Null
    }
}

function Update-AppSettingsFromLocal($FunctionAppName, $ResourceGroup) {
    if (-not (Test-Path 'local.settings.json')) { return }
    try {
        $settings = Get-Content -Path 'local.settings.json' | ConvertFrom-Json
        foreach ($key in $settings.Values.PSObject.Properties.Name) {
            if ($key -ne 'FUNCTIONS_WORKER_RUNTIME' -and $key -ne 'AzureWebJobsStorage') {
                $value = $settings.Values.$key
                if ($value) {
                    az functionapp config appsettings set --name $FunctionAppName --resource-group $ResourceGroup --settings "$key=$value" --output none
                }
            }
        }
        Write-Host 'Application settings updated from local.settings.json' -ForegroundColor Green
    } catch {
        Write-Host 'Warning: Could not update all application settings (permissions?)' -ForegroundColor Yellow
    }
}

function Publish-Functions($FunctionAppName) {
    # Default to python publish. If your app is Windows on node, adjust this.
    Write-Host "Publishing to $FunctionAppName..." -ForegroundColor Cyan
    func azure functionapp publish $FunctionAppName --python
}

function Deploy-Existing {
    Ensure-AzLogin

    $rgExists = az group exists --name $ResourceGroup
    if ($rgExists -eq 'false') { throw "Resource group $ResourceGroup does not exist." }

    az storage account show --name $StorageAccountName --resource-group $ResourceGroup 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Storage account $StorageAccountName not found in $ResourceGroup." }

    az functionapp show --name $FunctionAppName --resource-group $ResourceGroup 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Function app $FunctionAppName not found in $ResourceGroup." }

    Update-AppSettingsFromLocal $FunctionAppName $ResourceGroup
    Publish-Functions $FunctionAppName
}

function Deploy-New {
    Ensure-AzLogin

    if (-not $SkipResourceCreation) {
        $rgExists = az group exists --name $ResourceGroup
        if ($rgExists -eq 'false') {
            Write-Host "Creating resource group $ResourceGroup..." -ForegroundColor Cyan
            az group create --name $ResourceGroup --location $Location | Out-Null
        } else { Write-Host "Using existing resource group $ResourceGroup" -ForegroundColor Gray }

        az storage account show --name $StorageAccountName --resource-group $ResourceGroup 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Creating storage account $StorageAccountName..." -ForegroundColor Cyan
            az storage account create --name $StorageAccountName --resource-group $ResourceGroup --location $Location --sku Standard_LRS | Out-Null
        } else { Write-Host "Using existing storage account $StorageAccountName" -ForegroundColor Gray }

        az functionapp show --name $FunctionAppName --resource-group $ResourceGroup 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Creating function app $FunctionAppName..." -ForegroundColor Cyan
            # Windows plan with Node runtime placeholder (adjust if needed)
            az functionapp create --name $FunctionAppName --storage-account $StorageAccountName --consumption-plan-location $Location --resource-group $ResourceGroup --os-type Windows --runtime node --runtime-version 18 | Out-Null
        } else { Write-Host "Using existing function app $FunctionAppName" -ForegroundColor Gray }

        # If you need AzureWebJobsStorage explicitly set from connection string:
        try {
            $connectionString = az storage account show-connection-string --name $StorageAccountName --resource-group $ResourceGroup --query connectionString -o tsv
            az functionapp config appsettings set --name $FunctionAppName --resource-group $ResourceGroup --settings "AzureWebJobsStorage=$connectionString" --output none
        } catch { }

        Update-AppSettingsFromLocal $FunctionAppName $ResourceGroup
    }

    Publish-Functions $FunctionAppName
}

function Check-Resources {
    Ensure-AzLogin
    Write-Host '=== Your Azure Subscriptions ===' -ForegroundColor Cyan
    az account list --output table
    Write-Host "`n=== Current Subscription ===" -ForegroundColor Cyan
    az account show --output table
    Write-Host "`n=== Resource Groups ===" -ForegroundColor Cyan
    az group list --output table
    Write-Host "`n=== Storage Accounts ===" -ForegroundColor Cyan
    az storage account list --output table
    Write-Host "`n=== Function Apps ===" -ForegroundColor Cyan
    az functionapp list --output table
}

function Check-Logs {
    Ensure-AzLogin
    Write-Host "Getting logs for $FunctionName in $FunctionAppName..." -ForegroundColor Cyan
    $funcCmd = Get-Command func -ErrorAction SilentlyContinue
    if ($funcCmd) {
        # Core Tools log stream (works well with Function Apps)
        func azure functionapp logstream $FunctionAppName
    } else {
        # Fallback to WebApp log tail (no function-name filter support)
        az webapp log tail --name $FunctionAppName --resource-group $ResourceGroup
    }
}

function Test-Local {
    Write-Host "Testing local Azure Functions on port $Port (ticker=$Ticker)" -ForegroundColor Cyan
    try {
        Write-Host "\nHFA /api/hfa" -ForegroundColor Yellow
        $hfa = Invoke-RestMethod -Uri "http://localhost:$Port/api/hfa" -Method Post -Headers @{ 'Content-Type'='application/json' } -Body (ConvertTo-Json @{ ticker=$Ticker }) -ErrorAction Stop
        $hfa | ConvertTo-Json -Depth 6
    } catch { Write-Host "HFA error: $($_.Exception.Message)" -ForegroundColor Red }

    try {
        Write-Host "\nCAP /api/cap-table" -ForegroundColor Yellow
        $cap = Invoke-RestMethod -Uri "http://localhost:$Port/api/cap-table" -Method Post -Headers @{ 'Content-Type'='application/json' } -Body (ConvertTo-Json @{ ticker=$Ticker }) -ErrorAction Stop
        $cap | ConvertTo-Json -Depth 6
    } catch { Write-Host "CAP error: $($_.Exception.Message)" -ForegroundColor Red }
}

function Test-Deployment {
    Ensure-AzLogin
    Write-Host "Testing Azure Functions deployment for $FunctionAppName" -ForegroundColor Cyan
    $fa = az functionapp show --name $FunctionAppName --resource-group $ResourceGroup 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Function app not found: $FunctionAppName" }
    $hostName = az functionapp show --name $FunctionAppName --resource-group $ResourceGroup --query 'defaultHostName' -o tsv
    Write-Host "Function app URL: https://$hostName" -ForegroundColor Green
    Write-Host "\nFunctions:" -ForegroundColor Yellow
    az functionapp function list --name $FunctionAppName --resource-group $ResourceGroup --output table
    Write-Host "\nKeys (default):" -ForegroundColor Yellow
    az functionapp function keys list --name $FunctionAppName --resource-group $ResourceGroup --function-name HFAFunction --query 'default' -o tsv
    az functionapp function keys list --name $FunctionAppName --resource-group $ResourceGroup --function-name CapTableFunction --query 'default' -o tsv
}

function Test-Deployed {
    if (-not $BaseUrl) { throw 'Please provide -BaseUrl for Test-Deployed.' }
    Write-Host "Testing deployed endpoints at $BaseUrl (ticker=$Ticker)" -ForegroundColor Cyan
    try {
        Write-Host "\nHFA /api/hfa" -ForegroundColor Yellow
        $hfa = Invoke-RestMethod -Uri "$BaseUrl/api/hfa" -Method Post -Headers @{ 'Content-Type'='application/json'; 'x-functions-key'=$HfaKey } -Body (ConvertTo-Json @{ ticker=$Ticker }) -ErrorAction Stop
        $hfa | ConvertTo-Json -Depth 6
    } catch { Write-Host "HFA error: $($_.Exception.Message)" -ForegroundColor Red }

    try {
        Write-Host "\nCAP /api/cap-table" -ForegroundColor Yellow
        $cap = Invoke-RestMethod -Uri "$BaseUrl/api/cap-table" -Method Post -Headers @{ 'Content-Type'='application/json'; 'x-functions-key'=$CapTableKey } -Body (ConvertTo-Json @{ ticker=$Ticker }) -ErrorAction Stop
        $cap | ConvertTo-Json -Depth 6
    } catch { Write-Host "CAP error: $($_.Exception.Message)" -ForegroundColor Red }
}

function Switch-Mode {
    $HFAPath = Join-Path $PSScriptRoot 'HFAFunction\__init__.py'
    $HFAMockPath = Join-Path $PSScriptRoot 'HFAFunction\__init__.py.clean'
    $HFARealPath = Join-Path $PSScriptRoot 'HFAFunction\__init__.py.bak'

    $CapPath = Join-Path $PSScriptRoot 'CapTableFunction\__init__.py'
    $CapMockPath = Join-Path $PSScriptRoot 'CapTableFunction\__init__.py.mock'
    $CapRealPath = Join-Path $PSScriptRoot 'CapTableFunction\__init__.py.bak'

    if ($Function -in @('HFAFunction','both')) {
        if ($Mode -eq 'mock' -and (Test-Path $HFAMockPath)) { Copy-Item $HFAMockPath $HFAPath -Force }
        elseif ($Mode -eq 'real' -and (Test-Path $HFARealPath)) { Copy-Item $HFARealPath $HFAPath -Force }
        else { Write-Host 'HFA switch-mode: no matching source found.' -ForegroundColor Yellow }
    }
    if ($Function -in @('CapTableFunction','both')) {
        if ($Mode -eq 'mock' -and (Test-Path $CapMockPath)) { Copy-Item $CapMockPath $CapPath -Force }
        elseif ($Mode -eq 'real' -and (Test-Path $CapRealPath)) { Copy-Item $CapRealPath $CapPath -Force }
        else { Write-Host 'Cap switch-mode: no matching source found.' -ForegroundColor Yellow }
    }
    Write-Host 'Done! Restart the Azure Functions host to apply changes.' -ForegroundColor Green
}

function Fix-Emoji {
    # Minimal placeholder: replace problematic characters if needed.
    $paths = @((Join-Path $PSScriptRoot '..\src'), $PSScriptRoot)
    $replacements = @{}
    $fixed = 0
    foreach ($base in $paths) {
        if (-not (Test-Path $base)) { continue }
        Get-ChildItem -Path $base -Recurse -Include *.py | ForEach-Object {
            $content = Get-Content $_.FullName -Raw -Encoding UTF8
            $orig = $content
            foreach ($k in $replacements.Keys) { $content = $content.Replace($k, $replacements[$k]) }
            if ($content -ne $orig) {
                Set-Content $_.FullName -Value $content -Encoding UTF8
                $fixed++
                Write-Host "Fixed: $($_.FullName)" -ForegroundColor Green
            }
        }
    }
    Write-Host "Sanitized $fixed files." -ForegroundColor Cyan
}

try {
    switch ($Action) {
        'deployExisting' { Deploy-Existing }
        'deployNew'      { Deploy-New }
        'deploy'         { Deploy-Existing }
        'checkResources' { Check-Resources }
        'checkLogs'      { Check-Logs }
        'testLocal'      { Test-Local }
        'testDeployment' { Test-Deployment }
        'testDeployed'   { Test-Deployed }
        'switchMode'     { Switch-Mode }
        'fixEmoji'       { Fix-Emoji }
    }
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
