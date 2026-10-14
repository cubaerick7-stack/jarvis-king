# -*- coding: utf-8 -*-
"""WhatsApp pelo WAHA (WhatsApp HTTP API), rodando no Docker (no seu PC ou no outro PC sempre ligado).

Configuração só por variável de ambiente (nunca em arquivo):
  setx WAHA_URL "http://192.168.0.15:3000"   (o endereço do WAHA; com ngrok, o link https dele)
  setx WAHA_API_KEY "a-senha-do-waha"        (a mesma do WAHA_API_KEY do container)
  setx WAHA_SESSION "default"                (opcional; o nome da sessão no painel do WAHA)
Sem WAHA_URL, o Jarvis continua usando o WhatsApp Web no navegador dele.
Mandar mensagem é nível 3: SEMPRE pergunta antes. Ler é livre.
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TIMEOUT = 15


class WahaError(Exception):
    pass


def base():
    return os.environ.get("WAHA_URL", "").strip().rstrip("/")


def configured():
    return bool(base())


def session():
    return os.environ.get("WAHA_SESSION", "").strip() or "default"


def _call(path, params=None, body=None, timeout=TIMEOUT):
    if not configured():
        raise WahaError("falta o WAHA_URL (veja WHATSAPP no LEIA-ME)")
    url = base() + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    headers = {"Accept": "application/json"}
    key = os.environ.get("WAHA_API_KEY", "").strip()
    if key:
        headers["X-Api-Key"] = key
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise WahaError("o WAHA recusou a senha: confira o WAHA_API_KEY") from e
        if e.code == 404:
            raise WahaError(f"o WAHA não achou isso (a sessão \"{session()}\" existe e está conectada?)") from e
        raise WahaError(f"o WAHA respondeu HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise WahaError(f"o WAHA não respondeu em {base()} (o outro PC e o Docker estão ligados?)") from e


def status():
    """WORKING = conectado; SCAN_QR_CODE = falta ler o QR no painel; STOPPED/FAILED = parado."""
    return str(_call(f"/api/sessions/{session()}", timeout=5).get("status", "")).upper()


def _name(c):
    return str(c.get("name") or c.get("pushname") or c.get("pushName") or "").strip()


def _chat_id(c):
    cid = c.get("id")
    if isinstance(cid, dict):
        cid = cid.get("_serialized") or ""
    return str(cid or "")


def _digits(text):
    return re.sub(r"\D", "", str(text))


def find_contact(asked, same_person):
    """(chat_id, nome) do contato que bate com o nome pedido, ou (None, None). Aceita número também."""
    asked = str(asked).strip()
    digits = _digits(asked)
    if len(digits) >= 10 and not re.search(r"[A-Za-zÀ-ú]", asked):
        if len(digits) <= 11:  # DDD + número: põe o 55 do Brasil
            digits = "55" + digits
        found = _call("/api/contacts/check-exists", {"phone": digits, "session": session()})
        if not found.get("numberExists"):
            return None, None
        return found.get("chatId") or digits + "@c.us", asked
    # primeiro nas conversas recentes (rápido); a lista inteira de contatos demora e estourava o tempo
    try:
        recent = _call(f"/api/{session()}/chats/overview", {"limit": 100})
    except WahaError:
        recent = []
    people = [(_chat_id(c), _name(c)) for c in recent if isinstance(c, dict) and _name(c)]
    people = [(cid, n) for cid, n in people if cid.endswith("@c.us") and same_person(asked, n)]
    if people:
        exact = [p for p in people if p[1].lower() == asked.lower()]
        return (exact or people)[0]
    contacts = _call("/api/contacts/all", {"session": session()}, timeout=60)
    people = [(_chat_id(c), _name(c)) for c in contacts if isinstance(c, dict) and _name(c)]
    people = [(cid, n) for cid, n in people if cid.endswith("@c.us") and same_person(asked, n)]
    if not people:
        return None, None
    exact = [p for p in people if p[1].lower() == asked.lower()]
    return (exact or people)[0]


def send_text(chat_id, text):
    return _call("/api/sendText", body={"session": session(), "chatId": chat_id, "text": text})


IMAGES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def send_file(chat_id, path, caption=""):
    """Manda uma imagem (print, foto) ou outro arquivo. O WAHA grátis (Core) pode não mandar arquivos: aí avisa."""
    import base64
    import mimetypes
    path = Path(path)
    ext = path.suffix.lower()
    mime = IMAGES.get(ext) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = {"session": session(), "chatId": chat_id, "caption": caption,
            "file": {"mimetype": mime, "filename": path.name, "data": base64.b64encode(path.read_bytes()).decode("ascii")}}
    try:
        return _call("/api/sendImage" if ext in IMAGES else "/api/sendFile", body=body, timeout=90)
    except WahaError as e:
        if re.search(r"HTTP (?:403|422|501)", str(e)):
            raise WahaError("este WAHA não manda arquivos (na versão grátis só texto; imagem precisa do WAHA Plus)") from e
        raise


def _when(ts):
    try:
        return time.strftime("%H:%M", time.localtime(int(ts)))
    except (TypeError, ValueError, OSError):
        return ""


def _text(m):
    body = str(m.get("body") or "").strip()
    if not body and m.get("hasMedia"):
        return "(mídia)"
    return body.replace("\n", " ")


def recent_chats(limit=8):
    """As últimas conversas: [(nome, quem falou por último, texto, hora)]."""
    chats = _call(f"/api/{session()}/chats/overview", {"limit": limit})
    out = []
    for c in chats if isinstance(chats, list) else []:
        last = c.get("lastMessage") or {}
        if not last:
            continue
        name = _name(c) or _digits(_chat_id(c))
        out.append((name, "você" if last.get("fromMe") else name, _text(last), _when(last.get("timestamp"))))
    return out


def messages(chat_id, limit=6):
    """As últimas mensagens de uma conversa, da mais antiga para a mais nova: [(de_mim, texto, hora)]."""
    msgs = _call(f"/api/{session()}/chats/{urllib.parse.quote(chat_id)}/messages",
                 {"limit": limit, "downloadMedia": "false"})
    msgs = sorted((m for m in msgs if isinstance(m, dict)), key=lambda m: m.get("timestamp") or 0)
    return [(bool(m.get("fromMe")), _text(m), _when(m.get("timestamp"))) for m in msgs]
