# Qual branch usar (atualizado em 21/10/2026)

**A branch mais nova é `claude/keen-pascal-z4kvji`.** Ela tem tudo o que existe nas outras e mais o que foi
feito depois de 14/10.

| Branch | Última mudança | O que tem |
|---|---|---|
| **claude/keen-pascal-z4kvji** | **21/10/2026** | **Tudo (use esta).** |
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
git checkout claude/keen-pascal-z4kvji
git pull origin claude/keen-pascal-z4kvji
python -m pip install -U --no-cache-dir -r requirements.txt
```

Se você usa o Python do G (`G:\Jarvis\venv`), troque `python` por `G:\Jarvis\venv\Scripts\python`.

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
qualquer coisa, comece da `claude/keen-pascal-z4kvji` (ou peça ao João para juntar as duas), senão o
trabalho parte de uma versão sem nada do que está acima.
