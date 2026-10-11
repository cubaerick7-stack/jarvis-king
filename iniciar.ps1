# Inicia o Ollama (se ainda nao estiver rodando) e abre o Jarvis.
# Uso: powershell -ExecutionPolicy Bypass -File iniciar.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$model = "qwen3:1.7b"

function Test-Ollama {
    try { Invoke-RestMethod http://localhost:11434/api/tags -TimeoutSec 2 | Out-Null; return $true }
    catch { return $false }
}

if (-not (Test-Ollama)) {
    Write-Host "Iniciando o Ollama..."
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    $tries = 0
    while (-not (Test-Ollama)) {
        Start-Sleep 1
        $tries++
        if ($tries -ge 30) { Write-Host "Ollama nao respondeu. Os comandos rapidos funcionam mesmo assim."; break }
    }
}

if ((Test-Ollama) -and -not (ollama list | Select-String -SimpleMatch $model)) {
    Write-Host "Baixando o modelo $model..."
    ollama pull $model
}

python windows\jarvis_ai.py
