# Qual branch usar (atualizado em 02/11/2026)

**A branch mais nova é `claude/project-thread-on1we5`.** Ela tem tudo o que existe nas outras (inclusive o reator
novo de 22/10) e mais o que foi feito em 02/11: tudo pela IA, botão de falar, visão do PC e fotos no PhotoCraft.

| Branch | Última mudança | O que tem |
|---|---|---|
| **claude/project-thread-on1we5** | **02/11/2026** | **Tudo (use esta).** |
| claude/practical-albattani-k0k5jk | 22/10/2026 | Reator novo (holograma). Já está dentro da de cima. |
| claude/keen-pascal-z4kvji | 21/10/2026 | Voz do Piper. Já está dentro da de cima. |
| fix/roteador-e-testes | 14/10/2026 | O trabalho do Codex e do Claude até 14/10. Já está todo dentro da de cima. |
| claude/project-recognition-4gjax1 | 15/10/2026 | Onde o PLANO-100.md foi escrito. |
| fix/estabilizar-base-bolha | 13/10/2026 | Antiga. |
| main | 11/10/2026 | A versão original (Jarvis Lite V2). |

## Como pegar no PC

No PowerShell (confira que aparece `PS G:\Jarvis\jarvis-king>`):

```
G:
cd G:\Jarvis\jarvis-king
git fetch origin
git checkout claude/project-thread-on1we5
git pull origin claude/project-thread-on1we5
python -m pip install -U --no-cache-dir -r requirements.txt
```

Se você usa o Python do G (`G:\Jarvis\venv`), troque `python` por `G:\Jarvis\venv\Scripts\python`.

## O que entrou em 02/11

- Tudo passa pela IA: os atalhos de palavra-chave só funcionam quando nenhuma IA responde (sem internet ou sem
  chave). "Alarme 5:50 e volume 100" agora agenda as duas coisas para as 5:50. Para voltar aos atalhos:
  `setx BOLHA_ATALHOS 1`.
- Botão de falar no canto da tela do PC: aperta e fala, sem dizer "Bolha".
- Whisper large-v3 (erra menos em português), com o turbo de reserva e espera de 10 s.
- Visão do PC (pc_overview): área de trabalho, discos, o que mais pesa e o que pode ou não ser apagado.
  delete_paths apaga vários com uma pergunta só.
- Fotos no PhotoCraft (photo_edit, photo_commands, photo_open), procurado em G:\Jarvis\apps\photocraft.

## O que entrou depois de 14/10

- Plano 3.0 inteiro (PLANO-100.md): diário, "errou/boa", habilidades, mãos (UI Automation), documentos,
  rotina, integrações e autoteste.
- Interface nova do reator: temas, painel com CPU, RAM, clima e tarefa, atalhos e histórico.
- Slides da faculdade (PowerPoint ou Google Slides) e o passo a passo para conectar o Google (LEIA-ME).
- PLANO-CORRECOES.md: a lista do que falta corrigir. O item 9 (IA local) foi cancelado.
- Voz: o Bing (Antônio) continua sendo a padrão. O Piper fica opcional, só quando não há internet.
  Atualize o edge-tts: a versão 7.3.1 (13/10) voltou a falar com o Bing.
- A IA local (Ollama/Qwen) e o botão "IA local" foram tirados: ficaram pesados demais para o PC.

## Para o Codex

O AGENTS.md ainda diz para trabalhar na `fix/roteador-e-testes`, mas ela parou em 14/10. Antes de mudar
qualquer coisa, comece da `claude/project-thread-on1we5` (ou peça ao João para juntar as duas), senão o
trabalho parte de uma versão sem nada do que está acima.
