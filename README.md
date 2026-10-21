# Bolha: o Jarvis do João para Windows

Assistente de voz e texto para o Windows, todo em português. Você diz **"Bolha, toca lofi"** e ele faz:
os comandos rápidos (volume, programas, arquivos, mídia, janelas) rodam direto no Python, sem IA e sem
internet; o resto vai para a IA na nuvem (**Gemini**, com o **Groq** de reserva), então não pesa no PC.

Feito para rodar leve num i3 com 8 GB. A tela é um "reator" no estilo do Jarvis do Homem de Ferro, que
também abre no celular.

> Manual completo, com cada comando e cada configuração: **[LEIA-ME.txt](LEIA-ME.txt)**.

## O que ele faz

- **Voz:** acorda com "Bolha" (Vosk no próprio PC), entende o pedido pelo Whisper (Groq) e responde com a
  voz Antonio (Bing). Reservas: ElevenLabs, Google e Piper (sem internet). "Bolha, para" corta a fala.
- **Windows:** volume (geral e por programa), abrir e fechar programas e jogos (Steam e Epic), janelas lado a
  lado, Wi-Fi, Bluetooth, modo escuro, instalar programas pelo winget, limpar o PC e liberar memória.
- **Qualquer programa:** "clica em Salvar", "escreve João no campo Nome", "lê essa janela" (UI Automation) e o
  **modo agente**, que faz tarefas de vários passos com o botão PARAR.
- **Arquivos:** busca no PC inteiro (com o Everything), procura **dentro** de PDF, Word e Excel, lê em voz
  alta, ditado para Word e planilhas.
- **Internet:** pesquisa com resposta falada e fontes, YouTube no navegador dele (Edge via Playwright), resumo
  de páginas e de vídeos, vigiar preço e rastrear encomenda.
- **Comunicação:** WhatsApp (pelo WAHA), Gmail, Google Agenda e Instagram (API oficial).
- **Faculdade:** slides em PowerPoint ou Google Slides, com PDF, mandados pelo WhatsApp.
- **Rotina:** lembretes, despertador, modos (aula, estudo, jogo, dormir...), Pomodoro, listas, contas do mês
  e Home Assistant.
- **Memória e aprendizado:** lembra de você, das pessoas e dos apelidos; aprende com "errou" e "boa"; guarda
  um diário de cada pedido e monta o relatório da semana com o que mais falhou.
- **Habilidades:** mais de 70 receitas prontas em [`windows/skills`](windows/skills), e você cria novas
  por voz ("aprende: quando eu disser modo cinema, abre a Netflix e coloca o volume em 80").
- **Celular:** a mesma tela do reator no celular, de qualquer lugar (ngrok, com senha).

## Começar

No PowerShell, com o Python instalado:

```powershell
G:
cd G:\Jarvis\jarvis-king
python -m pip install -U -r requirements.txt

setx GEMINI_API_KEY "sua-chave"   # aistudio.google.com
setx GROQ_API_KEY "sua-chave"     # console.groq.com
```

Feche e abra o PowerShell de novo (o `setx` só vale nas janelas novas) e rode:

```powershell
python windows\jarvis_ai.py
```

ou `powershell -ExecutionPolicy Bypass -File iniciar.ps1`. Na primeira vez ele baixa o modelo de voz (uns
30 MB). Diga **"Bolha, toca lofi"** ou digite o pedido. Sem as chaves, só os comandos rápidos funcionam.

Opções: `--sem-voz` (só digitando) e `--sem-tela` (só o console).

Para atualizar: `git pull` e `python -m pip install -U -r requirements.txt` (ou diga "se atualiza").

## Segurança

- Abrir, fechar, tocar e pesquisar rodam sem perguntar. **Apagar, mandar mensagem, publicar e instalar
  sempre pedem "sim".**
- Chaves e senhas ficam **só** nas variáveis do Windows (`setx`), nunca em arquivo, commit ou log.
- Memória, diário e configurações ficam no seu PC, em `G:\Jarvis\config`.

## Como o código está organizado

| Arquivo | O que tem |
|---|---|
| `windows/jarvis_ai.py` | Laço dos pedidos, roteador rápido, catálogo de ferramentas (`TOOLS`) e confirmação |
| `windows/ferramentas.py` | Ferramentas do Windows (volume, arquivos, programas, clima, pesquisa) |
| `windows/maos.py` | UI Automation, janelas, configurações do Windows, winget, limpeza, macros e jogos |
| `windows/voz.py` | Escuta do "Bolha", transcrição e as vozes |
| `windows/nuvem.py` | Gemini e Groq |
| `windows/navegador.py` | Edge via Playwright (YouTube, pesquisa, WhatsApp Web) |
| `windows/memoria.py`, `aprende.py`, `diario.py` | Memória, aprendizado e diário de cada pedido |
| `windows/habilidades.py` + `windows/skills/` | As habilidades (receitas `SKILL.md`) |
| `windows/documentos.py`, `slides.py` | Documentos, planilhas, ditado e slides |
| `windows/rotina.py`, `integracoes.py` | Modos, lembretes, listas, Google, Home Assistant, Correios |
| `windows/waha.py`, `instagram.py`, `celular.py` | WhatsApp, Instagram e o reator no celular |
| `windows/ui.py` + `windows/interface/reator.html` | A tela do reator |
| `windows/autoteste.py` | Autoteste ao abrir e atualização pelo git |

Ferramenta nova: função em `windows/ferramentas.py`, entrada em `TOOLS` (`windows/jarvis_ai.py`), um teste
em `tests/` e uma linha no `LEIA-ME.txt`. O passo a passo está no LEIA-ME, em "COMO CRIAR UMA FERRAMENTA NOVA".

## Testes

```powershell
python -m pip install pytest
python -m pytest -q
```

Os testes simulam as ações (não mexem no volume nem chamam a nuvem) e rodam no GitHub a cada push, no Linux e
no Windows. Os pedidos para testar na mão, no PC, estão no [TESTES.txt](TESTES.txt).

## Outros documentos

- [LEIA-ME.txt](LEIA-ME.txt): o manual, com todos os comandos e as configurações (Google, WhatsApp, celular,
  Instagram, vozes).
- [TESTES.txt](TESTES.txt): o que testar no PC.
- [PLANO-CORRECOES.md](PLANO-CORRECOES.md): o que o João achou testando e ainda falta corrigir.
- [PLANO-100.md](PLANO-100.md): o plano do Bolha 3.0 e o que já está feito.
- [AGENTS.md](AGENTS.md): regras para o Claude e o Codex mexerem no código.
