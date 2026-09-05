param(
    [int]$Port = 8000,
    [switch]$InstallDeps,
    [switch]$NoBrowser,
    [switch]$SkipOllama,
    [switch]$SkipAvatar
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeDir = Join-Path $Root ".runtime"
$LogDir = Join-Path $Root "logs"
$BackendDir = Join-Path $Root "backend"
$EnvFile = Join-Path $Root ".env"
$EnvExample = Join-Path $Root ".env.example"

function Write-Step($Message) { Write-Host "[AI Teacher] $Message" -ForegroundColor Cyan }
function Write-Warn($Message) { Write-Host "[Warning] $Message" -ForegroundColor Yellow }

function Test-HttpOk($Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Import-DotEnv($Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $parts = $line.Split("=", 2)
        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($name) { [Environment]::SetEnvironmentVariable($name, $value, "Process") }
    }
}

function Get-PythonPath {
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) { return $venvPython }
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw "Python is not installed or not available on PATH." }
    return $pythonCommand.Source
}

function Start-LoggedProcess($Name, $FilePath, $Arguments, $WorkingDirectory) {
    $stdout = Join-Path $LogDir "$Name.log"
    $stderr = Join-Path $LogDir "$Name.error.log"
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    Set-Content -LiteralPath (Join-Path $RuntimeDir "$Name.pid") -Value $process.Id
    Write-Step "$Name started. PID: $($process.Id). Logs: logs\$Name.log"
}

Set-Location $Root
New-Item -ItemType Directory -Force -Path $RuntimeDir, $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path `
    (Join-Path $BackendDir "app\static\uploads"), `
    (Join-Path $BackendDir "app\static\generated_videos") | Out-Null

if (-not (Test-Path -LiteralPath $EnvFile) -and (Test-Path -LiteralPath $EnvExample)) {
    Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
    Write-Warn ".env was missing, so I created it from .env.example. Add API keys there."
}

Import-DotEnv $EnvFile
$Python = Get-PythonPath
$env:PYTHONDONTWRITEBYTECODE = "1"

if ($InstallDeps) {
    Write-Step "Installing Python dependencies from requirements.txt..."
    & $Python -m pip install -r (Join-Path $Root "requirements.txt")
}

if (-not $SkipOllama) {
    $ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaCommand) {
        if (-not (Test-HttpOk "http://127.0.0.1:11434/api/tags")) {
            Write-Step "Starting Ollama server..."
            Start-LoggedProcess "ollama" $ollamaCommand.Source @("serve") $Root
            for ($i = 0; $i -lt 20; $i++) {
                Start-Sleep -Seconds 1
                if (Test-HttpOk "http://127.0.0.1:11434/api/tags") { break }
            }
        } else {
            Write-Step "Ollama is already running."
        }

        $modelName = [Environment]::GetEnvironmentVariable("OLLAMA_MODEL", "Process")
        if (-not $modelName) { $modelName = "gemma4:31b-cloud" }
        try {
            $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
            $modelAvailable = $false
            foreach ($model in $tags.models) {
                if ($model.name -eq $modelName -or $model.name.StartsWith("$modelName`:")) { $modelAvailable = $true }
            }
            if (-not $modelAvailable) { Write-Warn "Ollama model '$modelName' is not installed. Run: ollama pull $modelName" }
        } catch {
            Write-Warn "Could not verify Ollama models. Run manually if needed: ollama pull $modelName"
        }
    } else {
        Write-Warn "Ollama command not found. Gemma needs Ollama running separately."
    }
}

$mongoService = Get-Service -Name MongoDB -ErrorAction SilentlyContinue
if ($mongoService -and $mongoService.Status -ne "Running") {
    try {
        Write-Step "Starting MongoDB Windows service..."
        Start-Service -Name MongoDB
    } catch {
        Write-Warn "Could not start MongoDB service automatically: $($_.Exception.Message)"
    }
}

if (Test-HttpOk "http://127.0.0.1:$Port/health") {
    Write-Step "FastAPI backend is already running at http://127.0.0.1:$Port"
} else {
    Write-Step "Starting FastAPI backend..."
    Start-LoggedProcess "backend" $Python @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port") $BackendDir
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-HttpOk "http://127.0.0.1:$Port/health") { break }
    }
}

if (-not [Environment]::GetEnvironmentVariable("SIMLI_API_KEY", "Process")) {
    Write-Warn "SIMLI_API_KEY missing. /video Simli generation needs it."
}
$ttsProvider = [Environment]::GetEnvironmentVariable("TTS_PROVIDER", "Process")
if (-not $ttsProvider) { $ttsProvider = "edge-tts" }
if ($ttsProvider -eq "elevenlabs" -and -not [Environment]::GetEnvironmentVariable("ELEVENLABS_API_KEY", "Process")) {
    Write-Warn "ELEVENLABS_API_KEY missing. /video Simli voice generation needs it when TTS_PROVIDER=elevenlabs."
}

$avatarRequired = @("SIMLI_API_KEY", "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
$missingAvatar = @()
foreach ($name in $avatarRequired) {
    if (-not [Environment]::GetEnvironmentVariable($name, "Process")) { $missingAvatar += $name }
}

if ($SkipAvatar) {
    Write-Step "Simli/LiveKit realtime worker skipped by request."
} elseif ($missingAvatar.Count -gt 0) {
    Write-Warn "Live avatar worker not started. Missing: $($missingAvatar -join ', '). /video Simli generation only needs SIMLI_API_KEY + ELEVENLABS_API_KEY."
} else {
    $avatarPidFile = Join-Path $RuntimeDir "simli-agent.pid"
    $alreadyRunning = $false
    if (Test-Path -LiteralPath $avatarPidFile) {
        $oldPid = Get-Content -LiteralPath $avatarPidFile -ErrorAction SilentlyContinue
        if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) { $alreadyRunning = $true }
    }
    if ($alreadyRunning) {
        Write-Step "Simli live avatar worker is already running."
    } else {
        Write-Step "Starting Simli/LiveKit realtime worker..."
        Start-LoggedProcess "simli-agent" $Python @("simli_agent.py", "dev") $Root
    }
}

$appUrl = "http://127.0.0.1:$Port"
Write-Host ""
Write-Host "AI Teacher is ready: $appUrl" -ForegroundColor Green
Write-Host "Topic-to-Simli video page: $appUrl/video" -ForegroundColor Green
Write-Host "Logs folder: $LogDir"
Write-Host "Stop: .\stop_ai_teacher.bat"

if (-not $NoBrowser) { Start-Process $appUrl }
