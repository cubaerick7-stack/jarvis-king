# -*- coding: utf-8 -*-
"""IA na nuvem (Gemini) para o Jarvis.

A chave vem SÓ da variável de ambiente GEMINI_API_KEY (nunca de arquivo).
Defina uma vez no PowerShell:   setx GEMINI_API_KEY "sua-chave"
e abra um PowerShell novo. Sem a chave, o Jarvis segue 100% local (Qwen).

JARVIS_NUVEM controla o uso:
  primeiro  (padrão) -> Gemini primeiro, Qwen se a nuvem falhar ou estiver sem internet
  reserva           -> Qwen primeiro, Gemini só se o Qwen falhar
  desligada         -> nunca usa a nuvem
"""

import json
import os
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Tentados em ordem: se um estiver sobrecarregado (503) ou aposentado (404), vai para o próximo.
DEFAULT_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]
TIMEOUT = 20


def api_key():
    return os.environ.get("GEMINI_API_KEY", "").strip()


def mode():
    m = os.environ.get("JARVIS_NUVEM", "primeiro").strip().lower()
    return m if m in {"primeiro", "reserva", "desligada"} else "primeiro"


def available():
    return bool(api_key()) and mode() != "desligada"


def models():
    custom = os.environ.get("GEMINI_MODEL", "").strip()
    return ([custom] if custom else []) + [m for m in DEFAULT_MODELS if m != custom]


class CloudError(Exception):
    pass


def _post(model, body, key):
    req = urllib.request.Request(
        API.format(model=model),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def generate(system, user, json_mode=False, max_tokens=2048, temperature=0.0):
    """Texto gerado pelo Gemini. Levanta CloudError se nenhum modelo responder."""
    key = api_key()
    if not key:
        raise CloudError("sem GEMINI_API_KEY")
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    last = None
    for model in models():
        try:
            data = _post(model, body, key)
        except urllib.error.HTTPError as e:
            last = f"{model}: HTTP {e.code}"
            if e.code in (401, 403):
                raise CloudError("chave do Gemini recusada (confira GEMINI_API_KEY)") from e
            if e.code == 429:
                raise CloudError("limite grátis do Gemini atingido por agora") from e
            continue  # 404 (modelo aposentado), 503 (sobrecarga), 500...: tenta o próximo
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise CloudError(f"sem conexão com o Gemini ({e})") from e
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        except (KeyError, IndexError):
            last = f"{model}: resposta vazia"
            continue
        if text.strip():
            return text
        last = f"{model}: resposta vazia"
    raise CloudError(f"nenhum modelo do Gemini respondeu ({last})")
