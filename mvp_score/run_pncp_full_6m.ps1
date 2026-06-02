$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$env:PNCP_DAYS_BACK = '184'
$env:PNCP_PAGE_SIZE = '500'
$env:PNCP_SLEEP_SECONDS = '0.02'
$env:PNCP_PAGE_BATCH = '120'
$env:PNCP_RESUME = '1'

$validationPath = 'resultados/pncp_download_validation.json'

while ($true) {
    python gerar_pncp_csv.py

    if (Test-Path $validationPath) {
        $v = Get-Content -Raw $validationPath | ConvertFrom-Json
        if ($v.download_finalizado_paginas -eq $true) {
            break
        }
    }

    Start-Sleep -Seconds 5
}
