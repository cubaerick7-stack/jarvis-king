# -*- coding: utf-8 -*-
"""O Bolha se cuidando: autoteste ao abrir (105), atualizar sozinho com "sim" (106) e modo sem internet (108).

O autoteste olha microfone, voz, IA, WhatsApp (WAHA), internet, índice de arquivos e modelo de voz, e mostra num
card o que está fora e como arrumar. Não gasta cota de IA: só pergunta se a chave existe e se o serviço responde.
"""

import json
import os
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
online_state = {"online": True, "desde": time.time()}


def _say(text):
    print(f"Jarvis > {text}")


def internet(timeout=2.0):
    for host in (("1.1.1.1", 53), ("8.8.8.8", 53)):
        try:
            socket.create_connection(host, timeout=timeout).close()
            return True
        except OSError:
            continue
    return False


def _get(url, headers=None, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "Bolha/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def check_all(voice=None, waha=None, everything=None, net=None, mic=None):
    """[(item, ok, detalhe, como arrumar)]. Cada verificação é rápida e nunca derruba o Bolha."""
    rows = []
    online = internet() if net is None else net
    rows.append(("Internet", online, "conectado" if online else "sem conexão",
                 "" if online else "confira o Wi-Fi/cabo; sem internet eu só faço os comandos locais"))
    try:
        mic_name = mic() if mic else _mic()
    except Exception as e:
        mic_name = ""
        rows.append(("Microfone", False, str(e)[:80], "ligue o microfone e libere em Configurações > Privacidade"))
    else:
        rows.append(("Microfone", bool(mic_name), mic_name or "não achei microfone",
                     "" if mic_name else "conecte um microfone e libere em Configurações > Privacidade > Microfone"))
    if voice is not None:
        missing = voice.missing()
        rows.append(("Voz (ouvir e falar)", not missing, "pronta" if not missing else "faltam " + ", ".join(missing),
                     "" if not missing else "python -m pip install " + " ".join(missing)))
        model = voice.find_model()
        rows.append(("Modelo do nome (Vosk)", model is not None, str(model or "não baixado"),
                     "" if model else "abre o Bolha com internet que ele baixa sozinho (30 MB)"))
    gem, groq = bool(os.environ.get("GEMINI_API_KEY", "").strip()), bool(os.environ.get("GROQ_API_KEY", "").strip())
    if gem and online:
        try:
            _get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                 {"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip()})
            rows.append(("IA Gemini", True, "respondendo", ""))
        except Exception as e:
            rows.append(("IA Gemini", False, _why(e), "confira a GEMINI_API_KEY (setx) e a internet"))
    else:
        rows.append(("IA Gemini", False, "sem chave" if not gem else "sem internet",
                     "setx GEMINI_API_KEY \"sua-chave\"" if not gem else ""))
    if groq and online:
        try:
            _get("https://api.groq.com/openai/v1/models",
                 {"Authorization": "Bearer " + os.environ["GROQ_API_KEY"].strip()})
            rows.append(("IA Groq", True, "respondendo", ""))
        except Exception as e:
            rows.append(("IA Groq", False, _why(e), "confira a GROQ_API_KEY (setx)"))
    else:
        rows.append(("IA Groq", False, "sem chave" if not groq else "sem internet",
                     "setx GROQ_API_KEY \"sua-chave\"" if not groq else ""))
    if waha is not None and waha.configured():
        try:
            st = waha.status()
            ok = st == "WORKING"
            rows.append(("WhatsApp (WAHA)", ok, st.lower() or "?",
                         "" if ok else "abra o painel do WAHA e leia o QR code (ou rode iniciar-waha.ps1)"))
        except Exception as e:
            rows.append(("WhatsApp (WAHA)", False, str(e)[:80], "ligue o Docker e rode iniciar-waha.ps1"))
    elif waha is not None:
        rows.append(("WhatsApp (WAHA)", False, "não configurado", "veja WHATSAPP no LEIA-ME (opcional)"))
    if everything is not None:
        has = everything()
        rows.append(("Busca rápida (Everything)", bool(has), "instalado" if has else "não achei",
                     "" if has else "instale pelo voidtools.com (ou diga \"instala o Everything\")"))
    return rows


def _why(e):
    m = re.search(r"HTTP Error (\d+)", str(e))
    if m:
        return {"400": "chave recusada", "401": "chave recusada", "403": "chave recusada",
                "429": "cota do minuto acabou"}.get(m.group(1), f"erro {m.group(1)}")
    return str(e)[:60]


def _mic():
    import sounddevice as sd
    return sd.query_devices(kind="input")["name"]


def report(rows, card=None):
    bad = [r for r in rows if not r[1]]
    if card:
        card("Autoteste", json.dumps({"itens": [{"nome": n, "ok": ok, "detalhe": d, "como": c} for n, ok, d, c in rows]},
                                     ensure_ascii=False))
    if not bad:
        _say("Autoteste: todos os sistemas online, senhor.")
        return True
    _say(f"Autoteste: {len(rows) - len(bad)} de {len(rows)} ok. Fora: " + "; ".join(n for n, *_ in bad) + ".")
    for name, _, detail, how in bad:
        print(f"  ✗ {name}: {detail}" + (f". Como arrumar: {how}" if how else ""))
    return False


# ========================= ATUALIZAR SOZINHO (106) =========================

def _git(*args, timeout=60):
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def update_check():
    """(quantas novidades, resumo) no GitHub para o ramo atual, ou (None, motivo)."""
    if not (REPO / ".git").exists():
        return None, "esta pasta não veio do git"
    try:
        branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        f = _git("fetch", "origin", branch, timeout=120)
        if f.returncode != 0:
            return None, "não consegui falar com o GitHub"
        behind = _git("rev-list", "--count", f"HEAD..origin/{branch}").stdout.strip()
        log = _git("log", "--format=- %s", f"HEAD..origin/{branch}", "-n", "8").stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"o git não respondeu ({e})"
    try:
        return int(behind or 0), log
    except ValueError:
        return None, "o git respondeu algo estranho"


def update(confirm):
    n, info = update_check()
    if n is None:
        _say(f"Não consegui ver atualizações: {info}.")
        return False
    if n == 0:
        _say("Já estou na versão mais nova, senhor.")
        return True
    print(info)
    if not confirm(f"Tenho {n} novidade{'s' if n > 1 else ''} no GitHub. Atualizo?"):
        _say("Ok, fico como estou.")
        return False
    if _git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        _say("Tem mudança local nos arquivos do Bolha; não atualizei para não perder nada. Peça ao Codex para "
             "guardar (commit) antes.")
        return False
    r = _git("pull", "--ff-only", timeout=180)
    if r.returncode != 0:
        _say("O git não conseguiu atualizar sozinho (as versões se separaram). Peça ao Codex.")
        return False
    _say("Atualizado, senhor. Feche e abra o Bolha para usar a versão nova"
         + (" (e rode python -m pip install -r requirements.txt)" if "requirements.txt" in r.stdout else "") + ".")
    return True


# ========================= SEM INTERNET (108) =========================

OFFLINE_MSG = ("Estou sem internet, senhor. Sigo fazendo os comandos locais: volume, abrir programas, arquivos, "
               "janelas, timers e lembretes. A IA, pesquisa, clima, voz do Bing e WhatsApp voltam junto com a internet.")


def connection_changed(now_online):
    """Mudou o estado da internet? Devolve a frase para avisar (ou "")."""
    if now_online == online_state["online"]:
        return ""
    online_state.update(online=now_online, desde=time.time())
    return "A internet voltou, senhor. Tudo online de novo." if now_online else OFFLINE_MSG
