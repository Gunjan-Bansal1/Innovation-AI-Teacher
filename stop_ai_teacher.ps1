$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeDir = Join-Path $Root ".runtime"

if (-not (Test-Path -LiteralPath $RuntimeDir)) {
    Write-Host "No .runtime folder found. Nothing to stop."
    exit 0
}

Get-ChildItem -LiteralPath $RuntimeDir -Filter "*.pid" | ForEach-Object {
    $name = $_.BaseName
    $pidValue = Get-Content -LiteralPath $_.FullName -ErrorAction SilentlyContinue
    if ($pidValue -and (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $pidValue -Force
        Write-Host "Stopped $name (PID $pidValue)"
    } else {
        Write-Host "$name was not running"
    }
    Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
}

Write-Host "AI Teacher background processes stopped."
