# Inicia o Ollama (se ainda nao estiver rodando) e abre o Jarvis.
# Uso: powershell -ExecutionPolicy Bypass -File iniciar.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$model = "qwen3:1.7b"

# Onde procurar o Ollama. Se o seu estiver em outro lugar, coloque o caminho no topo da lista.
$ollamaCandidates = @(
    "G:\Jarvis\Ollama\ollama.exe",
    "G:\Ollama\ollama.exe",
    "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
    "C:\Program Files\Ollama\ollama.exe"
)
$ollama = $ollamaCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $ollama) {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { $ollama = $cmd.Source }
}
if (-not $ollama) { Write-Host "Nao achei o ollama.exe. Edite a lista no topo do iniciar.ps1." }

# Modelos guardados no G:, como no plano
if (-not $env:OLLAMA_MODELS -and (Test-Path "G:\Jarvis\Ollama\models")) {
    $env:OLLAMA_MODELS = "G:\Jarvis\Ollama\models"
}

function Test-Ollama {
    try { Invoke-RestMethod http://localhost:11434/api/tags -TimeoutSec 2 | Out-Null; return $true }
    catch { return $false }
}

if ($ollama -and -not (Test-Ollama)) {
    Write-Host "Iniciando o Ollama: $ollama"
    Start-Process $ollama -ArgumentList "serve" -WindowStyle Hidden
    $tries = 0
    while (-not (Test-Ollama)) {
        Start-Sleep 1
        $tries++
        if ($tries -ge 30) { Write-Host "Ollama nao respondeu. Os comandos rapidos funcionam mesmo assim."; break }
    }
}

if ($ollama -and (Test-Ollama) -and -not (& $ollama list | Select-String -SimpleMatch $model)) {
    Write-Host "Baixando o modelo $model..."
    & $ollama pull $model
}

python windows\jarvis_ai.py
