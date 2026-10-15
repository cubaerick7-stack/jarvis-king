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
import re
import socket
import time
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Tentados em ordem: se um estiver sobrecarregado (503), aposentado (404) ou demorando, vai para o próximo.
DEFAULT_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]
TIMEOUT = 20
GEN_TIMEOUT = 15  # o Gemini que passa disso costuma estar "pensando" demais: o lite responde em segundos
SEARCH_TIMEOUT = 40  # pesquisar no Google antes de responder demora mais que uma resposta comum
# A busca do Google no Gemini tem cota própria, separada do chat (no plano grátis pode ser zero).
# Sem cota, a pesquisa do Jarvis lê as notícias pelo RSS (ferramentas.web_snippets) e a IA resume.
# Primeiro os modelos que o próprio Google indicou (os 2.5 saíram para contas novas); depois os do chat.
SEARCH_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]


GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
GROQ_LIST = "https://api.groq.com/openai/v1/models"
# Preferidos, em ordem. O Groq aposenta modelos de tempos em tempos: os que sumiram (404) ficam de lado
# e a lista de modelos da própria conta (GROQ_LIST) completa com os que existem hoje.
GROQ_MODELS = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.1-8b-instant"]
NOT_CHAT = ("whisper", "guard", "tts", "playai", "orpheus", "compound", "distil")
COOLDOWN = 300  # segundos que um modelo sem cota fica de lado (para não gastar uma ida e volta à toa)
_limited = {}  # modelo -> quando deu 429
_no_thinking_cfg = set()  # modelos que recusaram o thinkingConfig
_dead = set()  # modelos que responderam 404 (não existem mais): pulados até fechar o Jarvis
_groq_listed = None  # modelos que a conta do Groq tem hoje ([] = não deu para perguntar)


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


def _request(url, body, headers, timeout=TIMEOUT):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(model, body, key):
    return _request(API.format(model=model), body, {"x-goog-api-key": key}, GEN_TIMEOUT)


def _search_post(model, body, key):
    return _request(API.format(model=model), body, {"x-goog-api-key": key}, SEARCH_TIMEOUT)


def _timed_out(e):
    """Demorou para responder (o modelo, não a internet)."""
    if isinstance(e, urllib.error.URLError) and not isinstance(e, urllib.error.HTTPError):
        e = e.reason
    return isinstance(e, (TimeoutError, socket.timeout)) or "timed out" in str(e).lower()


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


def _all_failed(name, errors, limited):
    detail = "; ".join(errors) or "nenhum modelo disponível"
    if limited:
        return CloudError(f"limite grátis do {name} atingido por agora ({detail})")
    return CloudError(f"nenhum modelo do {name} respondeu ({detail})")


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

    errors, limited = [], False
    for model in _in_order([m for m in models() if m not in _dead]):
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
            errors.append(f"{model}: HTTP {h.code} {_message(h.body)}".strip())
            fail = _http_fail("Gemini", h, h.body)
            if fail:
                raise fail from h
            if h.code == 429:
                limited = True
                _limited[model] = time.time()
            elif h.code == 404:
                _dead.add(model)
            continue  # 429 (cota do modelo), 404 (aposentado), 503 (sobrecarga)...: tenta o próximo
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if _timed_out(e):  # esse modelo demorou: o próximo (mais leve) costuma responder rápido
                errors.append(f"{model}: demorou mais de {GEN_TIMEOUT} s")
                continue
            raise CloudError(f"sem conexão com o Gemini ({getattr(e, 'reason', e)})") from e
        try:
            cand = data["candidates"][0]
            parts = cand["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        except (KeyError, IndexError, TypeError):
            errors.append(f"{model}: resposta vazia")
            continue
        if json_mode and cand.get("finishReason") == "MAX_TOKENS":
            errors.append(f"{model}: resposta cortada")  # JSON pela metade não serve
            continue
        if text.strip():
            return text
        errors.append(f"{model}: resposta vazia")
    raise _all_failed("Gemini", errors, limited)


def search_generate(system, user, max_tokens=1800):
    """Gemini com a busca do Google: responde com informação atual e devolve (texto, fontes).
    As fontes vêm como [{"nome": "g1.globo.com", "titulo": "...", "url": "..."}]. Levanta CloudError se falhar
    (aí o Jarvis usa a reserva pelo RSS)."""
    if not available():
        raise CloudError("sem GEMINI_API_KEY")
    return _gemini_search(system, user, max_tokens)


def search_models():
    custom = os.environ.get("GEMINI_SEARCH_MODEL", "").strip()
    order = ([custom] if custom else []) + SEARCH_MODELS + models()
    return list(dict.fromkeys(order))


def _gemini_search(system, user, max_tokens):
    key = api_key()
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
    }
    errors, limited = [], False
    for model in _in_order([m for m in search_models() if m not in _dead]):
        try:
            data = _call(_search_post, model, _with_thinking(body, model not in _no_thinking_cfg), key)
        except _Http as h:
            errors.append(f"{model}: HTTP {h.code} {_message(h.body)}".strip())
            fail = _http_fail("Gemini", h, h.body)
            if fail:
                raise fail from h
            if h.code == 400 and model not in _no_thinking_cfg:
                _no_thinking_cfg.add(model)  # talvez só recuse o thinkingConfig: repete sem
                try:
                    data = _call(_search_post, model, body, key)
                except _Http as h2:
                    errors.append(f"{model}: HTTP {h2.code} {_message(h2.body)}".strip())
                    continue
            else:
                if h.code == 429:
                    limited = True  # cota da BUSCA: não tira o modelo do chat (a cota do chat é outra)
                elif h.code == 404:
                    _dead.add(model)
                continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if _timed_out(e):
                errors.append(f"{model}: demorou mais de {SEARCH_TIMEOUT} s")
                continue
            raise CloudError(f"sem conexão com o Gemini ({getattr(e, 'reason', e)})") from e
        try:
            cand = data["candidates"][0]
            text = "".join(p.get("text", "") for p in cand["content"]["parts"] if not p.get("thought"))
        except (KeyError, IndexError, TypeError):
            errors.append(f"{model}: resposta vazia")
            continue
        if not text.strip():
            errors.append(f"{model}: resposta vazia")
            continue
        sources, seen = [], set()
        for chunk in (cand.get("groundingMetadata") or {}).get("groundingChunks", []):
            web = chunk.get("web") or {}
            name = str(web.get("title") or "").strip()
            if name and name not in seen:
                seen.add(name)
                sources.append({"nome": name[:40], "titulo": "", "url": str(web.get("uri") or "")})
        return text, sources
    raise _all_failed("Gemini", errors, limited)


def _groq_list(key):
    """Os modelos que a conta do Groq tem hoje (uma pergunta por vez que o Jarvis abre)."""
    global _groq_listed
    if _groq_listed is None:
        try:
            req = urllib.request.Request(GROQ_LIST, headers={"Authorization": f"Bearer {key}", "User-Agent": "jarvis/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            _groq_listed = [str(m["id"]) for m in data.get("data", [])
                            if isinstance(m, dict) and m.get("id") and m.get("active", True) is not False]
        except Exception:
            _groq_listed = []  # sem a lista, tenta os preferidos mesmo
    return _groq_listed


def groq_models(key=None):
    custom = os.environ.get("GROQ_MODEL", "").strip()
    names = ([custom] if custom else []) + [m for m in GROQ_MODELS if m != custom]
    listed = _groq_list(key) if key else []
    if listed:  # só os que existem hoje, e depois qualquer outro modelo de conversa da conta
        names = [m for m in names if m in listed or m == custom]
        names += [m for m in listed if m not in names and not any(x in m.lower() for x in NOT_CHAT)]
    return [m for m in names if m not in _dead]


def groq_generate(system, user, json_mode=False, max_tokens=2048, temperature=0.0):
    """Mesmo contrato do generate(), usando o Groq (API no formato da OpenAI)."""
    key = groq_key()
    if not key:
        raise CloudError("sem GROQ_API_KEY")
    errors, limited = [], False
    for model in _in_order(groq_models(key)):
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"  # raciocina pouco: responde rápido e sobra resposta no max_tokens
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            data = _groq_post(body, key)
        except urllib.error.HTTPError as e:
            detail = _detail(e)
            errors.append(f"{model}: HTTP {e.code} {_message(detail)}".strip())
            fail = _http_fail("Groq", e, detail)
            if fail:
                raise fail from e
            if e.code == 429:
                limited = True
                _limited[model] = time.time()
            elif e.code == 404:
                _dead.add(model)  # o Groq aposentou esse modelo
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if _timed_out(e):
                errors.append(f"{model}: demorou mais de {TIMEOUT} s")
                continue
            raise CloudError(f"sem conexão com o Groq ({getattr(e, 'reason', e)})") from e
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            text = ""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)  # modelos que "pensam alto" na resposta
        if text.strip():
            return text
        errors.append(f"{model}: resposta vazia")
    raise _all_failed("Groq", errors, limited)


# ------------------------- ouvir (voz -> texto) -------------------------
GROQ_STT = "https://api.groq.com/openai/v1/audio/transcriptions"
STT_MODEL = "whisper-large-v3-turbo"
STT_PROMPT = "Bolha"  # o nome do assistente, para o Whisper escrever certo (a voz.py troca)


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


def _groq_transcribe(wav, key, name="fala.wav", mime="audio/wav"):
    body, ctype = _multipart({"model": STT_MODEL, "language": "pt", "temperature": "0",
                              "response_format": "verbose_json", "prompt": STT_PROMPT},
                             name, wav, mime)
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


def _gemini_transcribe(wav, key, name="fala.wav", mime="audio/wav"):
    import base64
    body = {"contents": [{"role": "user", "parts": [
        {"text": "Transcreva exatamente o que foi falado neste áudio, em português. Responda só com o texto."},
        {"inlineData": {"mimeType": mime, "data": base64.b64encode(wav).decode()}},
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


def transcribe(wav, name="fala.wav", mime="audio/wav"):
    """Texto falado num áudio (WAV do microfone do PC; webm/m4a do celular): Whisper no Groq; se faltar
    (ou falhar), o Gemini ouve o áudio.
    Se o Whisper respondeu "nada", é nada mesmo (o Gemini só inventaria algo como "não há fala")."""
    errors = []
    for backend, key, fn in (("Groq", groq_key(), _groq_transcribe), ("Gemini", api_key(), _gemini_transcribe)):
        if not key:
            continue
        try:
            return fn(wav, key, name, mime).strip()
        except Exception as e:
            errors.append(f"{backend}: {e}")
    if errors:
        raise CloudError("não consegui entender o áudio (" + "; ".join(errors) + ")")
    return ""


# ------------------------- ver (imagem -> texto) -------------------------
GROQ_VISION = ["meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct"]


def vision(prompt, image, mime="image/png", max_tokens=1200):
    """A IA olha uma imagem (print da tela) e responde: Gemini; se faltar ou falhar, um modelo de visão do Groq."""
    import base64
    data = base64.b64encode(image).decode()
    errors = []
    key = api_key()
    if key:
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}, {"inlineData": {"mimeType": mime, "data": data}}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": max_tokens}}
        for model in _in_order([m for m in models() if m not in _dead]):
            try:
                out = _call(_search_post, model, _with_thinking(body, model not in _no_thinking_cfg), key)
                text = "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"] if not p.get("thought"))
                if text.strip():
                    return text
            except _Http as h:
                errors.append(f"{model}: HTTP {h.code}")
                fail = _http_fail("Gemini", h, h.body)
                if fail:
                    raise fail from h
                if h.code == 429:
                    _limited[model] = time.time()
            except (KeyError, IndexError, TypeError):
                errors.append(f"{model}: resposta vazia")
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                errors.append(f"{model}: {getattr(e, 'reason', e)}")
    gkey = groq_key()
    if gkey:
        for model in GROQ_VISION:
            if model in _dead:
                continue
            body = {"model": model, "max_tokens": max_tokens, "temperature": 0.1, "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}]}]}
            try:
                out = _groq_post(body, gkey)
                text = out["choices"][0]["message"]["content"] or ""
                if text.strip():
                    return text
            except urllib.error.HTTPError as e:
                errors.append(f"{model}: HTTP {e.code}")
                if e.code == 404:
                    _dead.add(model)
            except (KeyError, IndexError, TypeError, urllib.error.URLError, TimeoutError, OSError) as e:
                errors.append(f"{model}: {e}")
    if not key and not gkey:
        raise CloudError("para ver a tela preciso da chave do Gemini (setx GEMINI_API_KEY)")
    raise CloudError("nenhuma IA conseguiu olhar a imagem (" + "; ".join(errors[-3:]) + ")")


# ------------------------- ferramentas nativas (Groq) -------------------------

def groq_tools(system, user, tools, temperature=0.0, max_tokens=1024):
    """Pedido com as ferramentas na chamada nativa (function calling), não JSON no texto.
    Devolve {"actions": [{"name", "args"}], "reply": texto}. Levanta CloudError se não der."""
    key = groq_key()
    if not key:
        raise CloudError("sem GROQ_API_KEY")
    errors, limited = [], False
    for model in _in_order(groq_models(key)):
        body = {"model": model, "temperature": temperature, "max_tokens": max_tokens, "tools": tools,
                "tool_choice": "auto", "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"
        try:
            data = _groq_post(body, key)
        except urllib.error.HTTPError as e:
            detail = _detail(e)
            errors.append(f"{model}: HTTP {e.code} {_message(detail)}".strip())
            fail = _http_fail("Groq", e, detail)
            if fail:
                raise fail from e
            if e.code == 429:
                limited = True
                _limited[model] = time.time()
            elif e.code == 404:
                _dead.add(model)
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if _timed_out(e):
                errors.append(f"{model}: demorou mais de {TIMEOUT} s")
                continue
            raise CloudError(f"sem conexão com o Groq ({getattr(e, 'reason', e)})") from e
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            errors.append(f"{model}: resposta vazia")
            continue
        actions = []
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            if fn.get("name"):
                actions.append({"name": fn["name"], "args": args if isinstance(args, dict) else {}})
        reply = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
        if actions or reply:
            return {"actions": actions, "reply": reply}
        errors.append(f"{model}: resposta vazia")
    raise _all_failed("Groq", errors, limited)
