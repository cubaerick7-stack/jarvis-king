# Bolha (Jarvis para Windows): regras para quem mexe no código

Dois assistentes trabalham juntos neste repositório, a pedido do João (o dono):
o **Codex**, no PC dele (`G:\Jarvis\jarvis-king`), e o **Claude**, na nuvem.
O ponto de encontro é o GitHub: o que não tiver `push` o outro não enxerga.

## Ramo e sincronia
- Trabalhe sempre no ramo `fix/roteador-e-testes` (PR #1). Não crie ramo novo só no PC.
- Antes de começar qualquer tarefa: `git pull origin fix/roteador-e-testes`.
- Ao terminar: testes passando, commit e `git push origin fix/roteador-e-testes`.
- Commits pequenos, um assunto por commit, mensagem em português dizendo o que mudou para o João.
- Conflito no pull: mantenha as duas mudanças (as duas foram pedidas pelo João). Na dúvida, pergunte a ele.
- Nunca `git push --force`, nunca reescreva o histórico, nunca apague o trabalho do outro.

## Testes
- `python -m pytest -q` passa antes de todo push. O CI roda no Linux e no Windows (Python 3.14).
- Testes nunca chamam nuvem, WhatsApp, ElevenLabs, ngrok etc. de verdade: veja `tests/conftest.py`.
- Bug corrigido ganha um teste que falharia sem a correção.

## Regras do projeto
- Tudo em português: falas do Bolha, comentários, LEIA-ME.txt. O PC é um i3-6100U com 8 GB: nada pesado.
- Chaves e senhas (GEMINI_API_KEY, GROQ_API_KEY, ELEVENLABS_API_KEY, WAHA_API_KEY, INSTAGRAM_TOKEN,
  BOLHA_SENHA, token do ngrok) só em variável de ambiente (`setx`). Nunca em arquivo, commit, teste ou log.
- Autonomia: abrir, fechar, tocar, pesquisar rodam sem perguntar. Apagar, mandar mensagem e publicar
  SEMPRE pedem "sim" (função `confirm` em `windows/jarvis_ai.py`).
- Instagram só pela API oficial. Nada de burlar detecção de robô ou CAPTCHA.
- A IA é na nuvem: Gemini, depois Groq (`windows/nuvem.py`). Ollama local só com `JARVIS_LOCAL=1`.
- Ferramenta nova: função em `windows/ferramentas.py` + entrada em `TOOLS` (`windows/jarvis_ai.py`) + teste,
  e uma linha no LEIA-ME.txt.
- A página `windows/interface/reator.html` serve o PC (pywebview) e o celular (`windows/celular.py`).
  Texto vindo de arquivo ou da IA entra com `textContent`, nunca `innerHTML`.

## Mapa
- `windows/jarvis_ai.py`: laço de pedidos, roteador rápido, catálogo `TOOLS`, confirmação.
- `windows/ferramentas.py`: ferramentas do Windows. `windows/navegador.py`: Edge via Playwright (YouTube, WhatsApp Web).
- `windows/voz.py`: "Bolha" pelo Vosk, Whisper, voz (Bing -> ElevenLabs -> Google).
- `windows/nuvem.py`: Gemini e Groq. `windows/memoria.py`: memória em `G:\Jarvis\config`.
- `windows/ui.py` + `windows/interface/reator.html`: a tela do reator. `windows/celular.py`: o reator no celular.
- `windows/waha.py`: WhatsApp pelo WAHA. `windows/instagram.py`: API oficial do Instagram.
