# -*- coding: utf-8 -*-
"""IA na nuvem para o Jarvis: Gemini (principal) e Groq (reserva).

As chaves vêm SÓ de variáveis de ambiente (nunca de arquivo). Defina uma vez no PowerShell:
  setx GEMINI_API_KEY "sua-chave"
  setx GROQ_API_KEY "sua-chave"
e abra um PowerShell novo. Se o Gemini bater no limite ou falhar, o Groq responde.
GEMINI_MODEL e GROQ_MODEL são opcionais para trocar o modelo.
"""

import json
import os
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Tentados em ordem: se um estiver sobrecarregado (503) ou aposentado (404), vai para o próximo.
DEFAULT_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]
TIMEOUT = 20


GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


def api_key():
    return os.environ.get("GEMINI_API_KEY", "").strip()


def groq_key():
    return os.environ.get("GROQ_API_KEY", "").strip()


def available():
    return bool(api_key())


def groq_available():
    return bool(groq_key())


def models():
    custom = os.environ.get("GEMINI_MODEL", "").strip()
    return ([custom] if custom else []) + [m for m in DEFAULT_MODELS if m != custom]


class CloudError(Exception):
    pass


def _request(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(model, body, key):
    return _request(API.format(model=model), body, {"x-goog-api-key": key})


def _groq_post(body, key):
    # O Groq fica atrás do Cloudflare, que recusa o User-Agent padrão do urllib.
    return _request(GROQ_API, body, {"Authorization": f"Bearer {key}", "User-Agent": "jarvis/1.0"})


def _http_fail(name, e):
    """Erros que não adianta tentar outro modelo do mesmo serviço."""
    if e.code in (401, 403):
        return CloudError(f"chave do {name} recusada")
    if e.code == 429:
        return CloudError(f"limite grátis do {name} atingido por agora")
    return None


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
            fail = _http_fail("Gemini", e)
            if fail:
                raise fail from e
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


def groq_models():
    custom = os.environ.get("GROQ_MODEL", "").strip()
    return ([custom] if custom else []) + [m for m in GROQ_MODELS if m != custom]


def groq_generate(system, user, json_mode=False, max_tokens=2048, temperature=0.0):
    """Mesmo contrato do generate(), usando o Groq (API no formato da OpenAI)."""
    key = groq_key()
    if not key:
        raise CloudError("sem GROQ_API_KEY")
    last = None
    for model in groq_models():
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            data = _groq_post(body, key)
        except urllib.error.HTTPError as e:
            last = f"{model}: HTTP {e.code}"
            fail = _http_fail("Groq", e)
            if fail:
                raise fail from e
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise CloudError(f"sem conexão com o Groq ({e})") from e
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            text = ""
        if text.strip():
            return text
        last = f"{model}: resposta vazia"
    raise CloudError(f"nenhum modelo do Groq respondeu ({last})")
