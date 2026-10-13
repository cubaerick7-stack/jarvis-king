# Revisão da base da Bolha — 13/10/2026

A base usada é o commit 52bcf6b da branch `fix/roteador-e-testes` do GitHub.
A `main` continua no Jarvis Lite V2; a base completa possui 45 commits além dela.
A branch `fix/estabilizar-base-bolha` incorpora essa base e contém esta revisão.

## Recursos já presentes

- Assistente Windows com voz, interface de reator, memória, lembretes e rotinas.
- Comandos locais, IA Gemini/Groq e opção local Ollama/Qwen.
- Navegador, mídia, ferramentas do PC e integração WhatsApp via WAHA.
- Acesso pelo celular com senha, ngrok, texto, áudio e confirmação.
- Testes automatizados e workflow para Linux e Windows.

## Correções desta revisão

- Seleções como “abre o quarto” e “mostra o segundo na pasta”, sem resultados anteriores,
  pedem uma busca primeiro e não seguem para a IA.
- O caminho dos módulos é configurado antes das fixtures: testes isolados também funcionam.
- Regressões cobrem seleção vazia, abertura de programa pelo nome e seleção de links web.

## Verificação

- 317 testes passaram no Windows com Python 3.14.
- Os casos antigos de volume relativo, busca web antes de arquivos e acentos já passam.
- `git diff --check` passou.
- Os testes usam simulações; voz, microfone, reprodução real, WAHA e celular precisam
  de validação prática com as integrações configuradas.

Neste PC, a pasta temporária padrão do pytest não estava acessível. Para repetir:

```powershell
New-Item -ItemType Directory -Path G:\Jarvis\tmp -Force | Out-Null
python -m pytest -q -p no:cacheprovider --basetemp=G:\Jarvis\tmp\pytest-validacao-bolha
```

O pytest limpa a pasta indicada por `--basetemp`; reserve esse caminho apenas para os testes.

## Próxima etapa

Validar o acesso pelo celular já existente antes de criar outra integração. Telegram permanece
uma proposta do documento de ideias e pode reutilizar o catálogo de ferramentas e a fila
central de comandos. Esta revisão não implementa Telegram.
