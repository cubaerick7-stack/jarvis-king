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
import time
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Tentados em ordem: se um estiver sobrecarregado (503) ou aposentado (404), vai para o próximo.
DEFAULT_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]
TIMEOUT = 20


GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
COOLDOWN = 300  # segundos que um modelo sem cota fica de lado (para não gastar uma ida e volta à toa)
_limited = {}  # modelo -> quando deu 429
_no_thinking_cfg = set()  # modelos que recusaram o thinkingConfig


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


def _detail(e):
    """O corpo da resposta de erro (onde vem o motivo, ex.: API_KEY_INVALID)."""
    try:
        return e.read().decode("utf-8", "replace")
    except Exception:
        return ""


def _message(body):
    try:
        err = json.loads(body).get("error", {})
        return str(err.get("message") if isinstance(err, dict) else err)[:160]
    except Exception:
        return ""


def _http_fail(name, e, body=""):
    """Erros que não adianta tentar outro modelo do mesmo serviço. O 429 não está aqui:
    no plano grátis o limite é por modelo, então o próximo modelo ainda pode ter cota."""
    if e.code in (401, 403) or "API_KEY_INVALID" in body or "API key not valid" in body:
        return CloudError(f"chave do {name} recusada (confira o setx)")
    return None


class _Http(Exception):
    """HTTPError com o corpo já lido (o corpo só pode ser lido uma vez)."""

    def __init__(self, e):
        super().__init__(f"HTTP {e.code}")
        self.code, self.body = e.code, _detail(e)


def _call(fn, *args):
    try:
        return fn(*args)
    except urllib.error.HTTPError as e:
        raise _Http(e) from e


def _in_order(names):
    """Modelos que deram 429 há pouco vão para o fim da fila."""
    now = time.time()
    fresh = [m for m in names if now - _limited.get(m, -COOLDOWN) >= COOLDOWN]
    return fresh + [m for m in names if m not in fresh]


def _all_failed(name, last, limited):
    if limited:
        return CloudError(f"limite grátis do {name} atingido por agora ({last})")
    return CloudError(f"nenhum modelo do {name} respondeu ({last})")


def _with_thinking(body, on):
    if not on:
        return body
    config = {**body["generationConfig"], "thinkingConfig": {"thinkingBudget": 0}}
    return {**body, "generationConfig": config}


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

    last, limited = None, False
    for model in _in_order(models()):
        # sem "pensar" antes de responder: o Jarvis fala, cada segundo conta (e o raciocínio gasta tokens)
        thinking = model not in _no_thinking_cfg
        try:
            try:
                data = _call(_post, model, _with_thinking(body, thinking), key)
            except _Http as h:
                if not (h.code == 400 and thinking and "API_KEY" not in h.body):
                    raise
                _no_thinking_cfg.add(model)  # modelo que não aceita o thinkingConfig: repete sem
                data = _call(_post, model, body, key)
        except _Http as h:
            last = f"{model}: HTTP {h.code} {_message(h.body)}".strip()
            fail = _http_fail("Gemini", h, h.body)
            if fail:
                raise fail from h
            if h.code == 429:
                limited = True
                _limited[model] = time.time()
            continue  # 429 (cota do modelo), 404 (aposentado), 503 (sobrecarga)...: tenta o próximo
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise CloudError(f"sem conexão com o Gemini ({e})") from e
        try:
            cand = data["candidates"][0]
            parts = cand["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        except (KeyError, IndexError, TypeError):
            last = f"{model}: resposta vazia"
            continue
        if json_mode and cand.get("finishReason") == "MAX_TOKENS":
            last = f"{model}: resposta cortada"  # JSON pela metade não serve
            continue
        if text.strip():
            return text
        last = f"{model}: resposta vazia"
    raise _all_failed("Gemini", last, limited)


def groq_models():
    custom = os.environ.get("GROQ_MODEL", "").strip()
    return ([custom] if custom else []) + [m for m in GROQ_MODELS if m != custom]


def groq_generate(system, user, json_mode=False, max_tokens=2048, temperature=0.0):
    """Mesmo contrato do generate(), usando o Groq (API no formato da OpenAI)."""
    key = groq_key()
    if not key:
        raise CloudError("sem GROQ_API_KEY")
    last, limited = None, False
    for model in _in_order(groq_models()):
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
            detail = _detail(e)
            last = f"{model}: HTTP {e.code} {_message(detail)}".strip()
            fail = _http_fail("Groq", e, detail)
            if fail:
                raise fail from e
            if e.code == 429:
                limited = True
                _limited[model] = time.time()
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
    raise _all_failed("Groq", last, limited)


# ------------------------- ouvir (voz -> texto) -------------------------
GROQ_STT = "https://api.groq.com/openai/v1/audio/transcriptions"
STT_MODEL = "whisper-large-v3-turbo"


def _multipart(fields, filename, content, mime):
    boundary = "----jarvis" + os.urandom(8).hex()
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 f"Content-Type: {mime}\r\n\r\n".encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# Frases que o Whisper inventa quando só tem barulho (tosse, porta, TV baixa).
HALLUCINATIONS = {"obrigado", "obrigada", "tchau", "tchau tchau", "legendas pela comunidade amaraorg",
                  "inscrevase no canal", "obrigado por assistir"}


def _plain(text):
    import unicodedata
    text = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return " ".join("".join(c for c in text if c.isalnum() or c.isspace()).split())


def _groq_transcribe(wav, key):
    body, ctype = _multipart({"model": STT_MODEL, "language": "pt", "temperature": "0",
                              "response_format": "verbose_json", "prompt": "Jarvis"},
                             "fala.wav", wav, "audio/wav")
    req = urllib.request.Request(GROQ_STT, data=body, method="POST", headers={
        "Content-Type": ctype, "Authorization": f"Bearer {key}", "User-Agent": "jarvis/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read().decode("utf-8"))
    segments = data.get("segments")
    if segments:  # trechos que o Whisper acha que não são fala ficam de fora (mesma regra do Whisper)
        text = " ".join(str(seg.get("text", "")).strip() for seg in segments
                        if not (seg.get("no_speech_prob", 0) > 0.6 and seg.get("avg_logprob", 0) < -1.0))
    else:
        text = data.get("text", "")
    return "" if _plain(text) in HALLUCINATIONS else text.strip()


def _gemini_transcribe(wav, key):
    import base64
    body = {"contents": [{"role": "user", "parts": [
        {"text": "Transcreva exatamente o que foi falado neste áudio, em português. Responda só com o texto."},
        {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(wav).decode()}},
    ]}], "generationConfig": {"temperature": 0}}
    for model in models():
        try:
            data = _post(model, body, key)
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except urllib.error.HTTPError as e:
            if _http_fail("Gemini", e):
                raise
        except (KeyError, IndexError):
            continue
    return ""


def transcribe(wav):
    """Texto falado num WAV: Whisper no Groq; se faltar (ou falhar), o Gemini ouve o áudio.
    Se o Whisper respondeu "nada", é nada mesmo (o Gemini só inventaria algo como "não há fala")."""
    errors = []
    for name, key, fn in (("Groq", groq_key(), _groq_transcribe), ("Gemini", api_key(), _gemini_transcribe)):
        if not key:
            continue
        try:
            return fn(wav, key).strip()
        except Exception as e:
            errors.append(f"{name}: {e}")
    if errors:
        raise CloudError("não consegui entender o áudio (" + "; ".join(errors) + ")")
    return ""
