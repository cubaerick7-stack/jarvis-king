# -*- coding: utf-8 -*-
"""Instagram pela API OFICIAL da Meta (Instagram API com login do Instagram). Nada de robô no navegador.

Precisa de uma conta profissional (Criador de Conteúdo ou Empresa, grátis) e de um token de acesso.
O token vem SÓ da variável de ambiente (nunca de arquivo):
  setx INSTAGRAM_TOKEN "seu-token"
e abra um PowerShell novo. Passo a passo no LEIA-ME (INSTAGRAM).

Publicar e responder comentário são nível 3: o Jarvis SEMPRE pergunta antes.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

API = "https://graph.instagram.com/v21.0"
TIMEOUT = 20


class InstagramError(Exception):
    pass


def token():
    return os.environ.get("INSTAGRAM_TOKEN", "").strip()


def available():
    return bool(token())


def _call(path, params=None, post=False):
    """GET ou POST na API. Devolve o JSON; erro vira InstagramError com o motivo em português."""
    key = token()
    if not key:
        raise InstagramError("falta o INSTAGRAM_TOKEN (veja INSTAGRAM no LEIA-ME)")
    params = dict(params or {}, access_token=key)
    data = urllib.parse.urlencode(params).encode()
    url = f"{API}/{path.lstrip('/')}"
    req = urllib.request.Request(url, data=data, method="POST") if post else \
        urllib.request.Request(url + "?" + data.decode())
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read().decode("utf-8", "replace"))["error"]["message"]
        except Exception:
            message = f"HTTP {e.code}"
        if e.code in (400, 401) and "token" in message.lower():
            message = "o token venceu ou está errado; gere outro e faça setx INSTAGRAM_TOKEN de novo"
        raise InstagramError(message) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise InstagramError(f"sem conexão com o Instagram ({getattr(e, 'reason', e)})") from e


def profile():
    return _call("me", {"fields": "username,followers_count,follows_count,media_count"})


def recent_posts(limit=5):
    data = _call("me/media", {"fields": "id,caption,timestamp,like_count,comments_count,permalink", "limit": limit})
    return data.get("data", [])


def comments(media_id, limit=10):
    data = _call(f"{media_id}/comments", {"fields": "id,text,username,timestamp", "limit": limit})
    return data.get("data", [])


def reply_comment(comment_id, message):
    return _call(f"{comment_id}/replies", {"message": message}, post=True)


def publish_image(image_url, caption=""):
    """Publica uma foto. A API só aceita foto que já está na internet (link público https)."""
    created = _call("me/media", {"image_url": image_url, "caption": caption}, post=True)
    return _call("me/media_publish", {"creation_id": created["id"]}, post=True)
