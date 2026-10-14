# Sobe o WAHA (WhatsApp do Bolha) no Docker SEMPRE com a mesma senha da API e do painel.
# Rode no PC onde fica o WAHA. As senhas vêm do setx deste PC (nunca ficam neste arquivo):
#   setx WAHA_API_KEY "uma-senha-forte"        (a mesma que o PC do Bolha usa)
#   setx WAHA_PAINEL_SENHA "senha-do-painel"   (login do http://localhost:3000/dashboard, usuário admin)
# e abra um PowerShell novo. Depois é só:  powershell -ExecutionPolicy Bypass -File iniciar-waha.ps1
# O container fica com --restart always: ele volta sozinho quando o Docker abre. Não use o botão "Run"
# do Docker Desktop (ele cria outro container sem as senhas, e aí elas mudam toda vez).

$api = $env:WAHA_API_KEY
$painel = $env:WAHA_PAINEL_SENHA
if (-not $api -or -not $painel) {
    Write-Host "Falta a senha. Rode antes:  setx WAHA_API_KEY ""..."" e setx WAHA_PAINEL_SENHA ""..."" e abra outro PowerShell."
    exit 1
}

docker pull devlikeapro/waha
docker rm -f waha 2>$null | Out-Null   # o container antigo sai; a conexão do WhatsApp fica no volume waha_data
docker run -d --name waha --restart always -p 3000:3000 `
  -e WAHA_API_KEY=$api `
  -e WAHA_DASHBOARD_USERNAME=admin -e WAHA_DASHBOARD_PASSWORD=$painel `
  -e WHATSAPP_SWAGGER_USERNAME=admin -e WHATSAPP_SWAGGER_PASSWORD=$painel `
  -v waha_data:/app/.sessions `
  devlikeapro/waha

Write-Host "WAHA no ar: http://localhost:3000/dashboard (usuario admin). A senha da API nao muda mais."
