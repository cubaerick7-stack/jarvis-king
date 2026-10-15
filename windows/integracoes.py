# -*- coding: utf-8 -*-
"""Área de integrações (9): cada serviço liga sozinho com um setx e reabrir o Bolha.
"quais integrações eu tenho?" mostra o que está ligado e o que falta (com o comando para ligar).

Também moram aqui as integrações novas:
- Google (Gmail e Agenda, 73 e 74) pela API oficial e grátis. Precisa de um acesso criado uma vez no Google Cloud
  (GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET); depois "conecta o Google" abre o navegador para o senhor autorizar e
  o Bolha guarda a chave de acesso numa variável de ambiente (GOOGLE_REFRESH_TOKEN, pelo setx), nunca em arquivo.
- Casa inteligente (84) pelo Home Assistant (HA_URL e HA_TOKEN): "liga a luz da sala".
- Vigiar preço de produto (63) e rastrear encomenda dos Correios (64), verificados de tempos em tempos.

Chaves e senhas só em variável de ambiente. Mandar e-mail sempre pede "sim".
"""

import base64
import json
import os
import re
import secrets
import subprocess
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

CONFIG = Path(r"G:\Jarvis\config")
PRICES = CONFIG / "precos.json"
PARCELS = CONFIG / "encomendas.json"


def _say(text):
    print(f"Jarvis > {text}")


def norm(text):
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def env(name):
    return os.environ.get(name, "").strip()


# ========================= ÁREA DE INTEGRAÇÕES (9) =========================

INTEGRATIONS = [
    {"nome": "Gemini (IA principal e pesquisa)", "vars": ["GEMINI_API_KEY"], "obrigatorio": "uma das IAs",
     "como": "crie a chave em aistudio.google.com e: setx GEMINI_API_KEY \"sua-chave\""},
    {"nome": "Groq (IA rápida e ouvir a voz)", "vars": ["GROQ_API_KEY"], "obrigatorio": "uma das IAs",
     "como": "crie a chave em console.groq.com e: setx GROQ_API_KEY \"sua-chave\""},
    {"nome": "ElevenLabs (voz de reserva)", "vars": ["ELEVENLABS_API_KEY"],
     "como": "setx ELEVENLABS_API_KEY \"sk_...\" (a chave de elevenlabs.io)"},
    {"nome": "WhatsApp (WAHA)", "vars": ["WAHA_URL", "WAHA_API_KEY"],
     "como": "suba o WAHA (iniciar-waha.ps1) e: setx WAHA_URL \"http://localhost:3000\" e setx WAHA_API_KEY \"senha\""},
    {"nome": "Instagram (API oficial)", "vars": ["INSTAGRAM_TOKEN"],
     "como": "gere o token no Meta for Developers e: setx INSTAGRAM_TOKEN \"token\""},
    {"nome": "Celular (o reator no celular)", "vars": ["BOLHA_SENHA"],
     "como": "setx BOLHA_SENHA \"uma senha de 8+ letras\" (e o ngrok: veja CELULAR no LEIA-ME)"},
    {"nome": "Google: Gmail e Agenda", "vars": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"],
     "como": "crie o acesso OAuth (app de computador) no console.cloud.google.com, ative a Gmail API e a Calendar "
             "API, faça setx GOOGLE_CLIENT_ID e setx GOOGLE_CLIENT_SECRET, reabra e diga \"conecta o Google\""},
    {"nome": "Casa inteligente (Home Assistant)", "vars": ["HA_URL", "HA_TOKEN"],
     "como": "setx HA_URL \"http://homeassistant.local:8123\" e setx HA_TOKEN \"token de longa duração\""},
    {"nome": "Rastreio dos Correios (Linketrack)", "vars": ["LINKETRACK_USER", "LINKETRACK_TOKEN"], "opcional": True,
     "como": "crie a conta grátis em linketrack.com e faça setx LINKETRACK_USER e setx LINKETRACK_TOKEN"},
    {"nome": "Senha falada para ações perigosas", "vars": ["BOLHA_SENHA_FALADA"], "opcional": True,
     "como": "setx BOLHA_SENHA_FALADA \"uma palavra\" (pedida antes de apagar ou desinstalar)"},
]


def status():
    """[(nome, ligado, o que falta, como ligar)]."""
    out = []
    for it in INTEGRATIONS:
        missing = [v for v in it["vars"] if not env(v)]
        out.append((it["nome"], not missing, missing, it["como"]))
    return out


def integrations():
    """ "quais integrações eu tenho?" """
    rows = status()
    on = [r for r in rows if r[1]]
    _say(f"Tenho {len(on)} de {len(rows)} integrações ligadas.")
    for name, ok, missing, how in rows:
        if ok:
            print(f"  ✓ {name}")
        else:
            print(f"  ✗ {name}: falta {', '.join(missing)}. Para ligar: {how}")
    print("  Depois do setx, feche e abra o Bolha de novo (o Windows só entrega a variável para janelas novas).")
    return [{"nome": n, "ligado": ok, "falta": m, "como": h} for n, ok, m, h in rows]


def _http(url, data=None, headers=None, method=None, timeout=15):
    body = None
    if data is not None:
        body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "Bolha/1.0", **(headers or {})},
                                 method=method or ("POST" if body is not None else "GET"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
        return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw


# ========================= GOOGLE: GMAIL E AGENDA (73, 74) =========================

SCOPES = ["https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/calendar.events"]
_token = {"valor": "", "ate": 0.0}


def google_ready():
    return all(env(v) for v in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"))


def setx(name, value):
    """Guarda numa variável de ambiente do usuário (fica para as próximas vezes) e já usa agora."""
    os.environ[name] = value
    try:
        subprocess.run(["setx", name, value], capture_output=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False


def google_connect(open_browser=None, wait=180):
    """Autoriza o Bolha no Google (uma vez): abre o navegador, o senhor aceita e a chave fica no setx."""
    if not (env("GOOGLE_CLIENT_ID") and env("GOOGLE_CLIENT_SECRET")):
        _say("Antes preciso do acesso do Google: " + INTEGRATIONS[6]["como"] + ".")
        return False
    import http.server
    import socketserver
    import webbrowser
    state, got = secrets.token_urlsafe(16), {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if q.get("state", [""])[0] == state:
                got["code"] = q.get("code", [""])[0]
                got["erro"] = q.get("error", [""])[0]
            body = "Pronto! Pode fechar esta aba e voltar para o Bolha.".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as srv:
        redirect = f"http://127.0.0.1:{srv.server_address[1]}/"
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": env("GOOGLE_CLIENT_ID"), "redirect_uri": redirect, "response_type": "code",
            "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent", "state": state})
        (open_browser or webbrowser.open)(url)
        _say("Abri o Google no navegador: escolha sua conta e aceite. Espero até 3 minutos.")
        srv.timeout = 2
        end = time.time() + wait
        while time.time() < end and "code" not in got:
            srv.handle_request()
    if not got.get("code"):
        _say("O Google não autorizou" + (f" ({got['erro']})" if got.get("erro") else "") + ".")
        return False
    data = _http("https://oauth2.googleapis.com/token", urllib.parse.urlencode({
        "code": got["code"], "client_id": env("GOOGLE_CLIENT_ID"), "client_secret": env("GOOGLE_CLIENT_SECRET"),
        "redirect_uri": redirect, "grant_type": "authorization_code"}).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"})
    refresh = data.get("refresh_token") if isinstance(data, dict) else ""
    if not refresh:
        _say("O Google não mandou a chave de acesso. Tente de novo.")
        return False
    setx("GOOGLE_REFRESH_TOKEN", refresh)
    _token.update(valor=data.get("access_token", ""), ate=time.time() + int(data.get("expires_in", 0)) - 60)
    _say("Google conectado, senhor: Gmail e Agenda prontos.")
    return True


def _access_token():
    if _token["valor"] and time.time() < _token["ate"]:
        return _token["valor"]
    data = _http("https://oauth2.googleapis.com/token", urllib.parse.urlencode({
        "client_id": env("GOOGLE_CLIENT_ID"), "client_secret": env("GOOGLE_CLIENT_SECRET"),
        "refresh_token": env("GOOGLE_REFRESH_TOKEN"), "grant_type": "refresh_token"}).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"})
    _token.update(valor=data["access_token"], ate=time.time() + int(data.get("expires_in", 3600)) - 60)
    return _token["valor"]


def _google(url, data=None, method=None):
    return _http(url, data, {"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"}, method)


def _need_google():
    if google_ready():
        return True
    _say("O Gmail e a Agenda ainda não estão conectados. " + INTEGRATIONS[6]["como"] + ".")
    return False


GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
_last_mails = []


def _header(msg, name):
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def gmail_list(query="is:unread category:primary", limit=8):
    """Os e-mails (padrão: não lidos da caixa principal): quem mandou, assunto e o começo."""
    if not _need_google():
        return False
    global _last_mails
    try:
        found = _google(f"{GMAIL}/messages?" + urllib.parse.urlencode({"q": query, "maxResults": limit}))
        mails = []
        for m in found.get("messages", []) if isinstance(found, dict) else []:
            msg = _google(f"{GMAIL}/messages/{m['id']}?format=metadata&metadataHeaders=From&metadataHeaders=Subject")
            sender = re.sub(r"\s*<.*?>", "", _header(msg, "From")).strip('" ') or _header(msg, "From")
            mails.append({"id": m["id"], "thread": msg.get("threadId"), "de": sender, "assunto": _header(msg, "Subject"),
                          "trecho": msg.get("snippet", ""), "email": _header(msg, "From")})
    except Exception as e:
        _say(f"O Gmail não respondeu: {e}.")
        return False
    _last_mails = mails
    if not mails:
        _say("Nenhum e-mail novo na caixa principal, senhor.")
        return True
    _say(f"{len(mails)} e-mail{'s' if len(mails) > 1 else ''}:")
    for i, m in enumerate(mails, 1):
        print(f"{i}. {m['de']}: {m['assunto']} — {m['trecho'][:90]}")
    return True


def gmail_read(index=1):
    if not _need_google():
        return False
    if not _last_mails:
        gmail_list()
    index = int(index or 1)
    if not 1 <= index <= len(_last_mails):
        _say("Não achei esse e-mail.")
        return False
    m = _last_mails[index - 1]
    try:
        msg = _google(f"{GMAIL}/messages/{m['id']}?format=full")
    except Exception as e:
        _say(f"O Gmail não respondeu: {e}.")
        return False
    text = _mail_body(msg.get("payload", {})) or msg.get("snippet", "")
    _say(f"E-mail de {m['de']}, assunto {m['assunto']}:")
    print(re.sub(r"\n{3,}", "\n\n", text)[:3000])
    return text[:6000]


def _mail_body(part):
    if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(part["body"]["data"] + "==").decode("utf-8", "replace")
    for p in part.get("parts", []) or []:
        found = _mail_body(p)
        if found:
            return found
    if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
        html = base64.urlsafe_b64decode(part["body"]["data"] + "==").decode("utf-8", "replace")
        return re.sub(r"<[^>]+>", " ", html)
    return ""


def gmail_send(to, subject, body, confirm, reply_to=None):
    """Manda (ou responde) um e-mail. SEMPRE pergunta antes."""
    if not _need_google():
        return False
    thread = None
    if reply_to:
        try:
            m = _last_mails[int(reply_to) - 1]
        except (ValueError, IndexError):
            _say("Não achei o e-mail para responder.")
            return False
        to, thread = m["email"], m["thread"]
        subject = subject or ("Re: " + m["assunto"])
    if not to or "@" not in to:
        _say("Para qual e-mail, senhor?")
        return False
    if not confirm(f"Mando o e-mail \"{subject}\" para {to}: \"{body[:120]}\"?"):
        _say("Cancelado, não enviei.")
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"], msg["Subject"] = to, subject
    payload = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    if thread:
        payload["threadId"] = thread
    try:
        _google(f"{GMAIL}/messages/send", payload)
    except Exception as e:
        _say(f"Não consegui enviar: {e}.")
        return False
    _say(f"E-mail enviado para {to}.")
    return True


CAL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def calendar_events(day=""):
    """Eventos de um dia da Agenda (padrão: hoje)."""
    if not _need_google():
        return False
    d = date.today() + timedelta(days=1) if norm(day) == "amanha" else date.fromisoformat(day) if \
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day).strip()) else date.today()
    tz = datetime.now().astimezone().strftime("%z")
    tz = tz[:3] + ":" + tz[3:]
    try:
        data = _google(CAL + "?" + urllib.parse.urlencode({
            "timeMin": f"{d}T00:00:00{tz}", "timeMax": f"{d}T23:59:59{tz}", "singleEvents": "true",
            "orderBy": "startTime"}))
    except Exception as e:
        _say(f"A Agenda não respondeu: {e}.")
        return False
    items = data.get("items", []) if isinstance(data, dict) else []
    if not items:
        _say(f"Nada na agenda em {d:%d/%m}.")
        return True
    _say(f"Agenda de {d:%d/%m}:")
    for e in items:
        start = e.get("start", {})
        when = start.get("dateTime", "")[11:16] or "dia todo"
        print(f"  - {when} {e.get('summary', '(sem título)')}")
    return True


def calendar_add(title, day, hour="", minutes=60):
    if not _need_google():
        return False
    try:
        d = date.fromisoformat(str(day).strip())
    except ValueError:
        _say(f"Não entendi a data {day}.")
        return False
    if hour:
        m = re.match(r"(\d{1,2})(?:\D+(\d{2}))?", str(hour))
        start = datetime.combine(d, datetime.min.time()).replace(hour=int(m.group(1)), minute=int(m.group(2) or 0))
        tz = datetime.now().astimezone().tzinfo
        body = {"summary": title, "start": {"dateTime": start.replace(tzinfo=tz).isoformat()},
                "end": {"dateTime": (start + timedelta(minutes=int(minutes))).replace(tzinfo=tz).isoformat()},
                "reminders": {"useDefault": True}}
    else:
        body = {"summary": title, "start": {"date": d.isoformat()}, "end": {"date": (d + timedelta(days=1)).isoformat()}}
    try:
        _google(CAL, body)
    except Exception as e:
        _say(f"Não consegui marcar na agenda: {e}.")
        return False
    _say(f"Marquei na agenda: {title}, {d:%d/%m}" + (f" às {hour}" if hour else "") + ".")
    return True


# ========================= CASA INTELIGENTE (84) =========================

def home_ready():
    return bool(env("HA_URL") and env("HA_TOKEN"))


def _ha(path, data=None):
    return _http(env("HA_URL").rstrip("/") + path, data, {"Authorization": f"Bearer {env('HA_TOKEN')}",
                                                          "Content-Type": "application/json"})


def home_control(device, action="ligar"):
    """ "liga a luz da sala", "desliga a tomada do ventilador": acha o aparelho pelo nome no Home Assistant."""
    if not home_ready():
        _say("A casa inteligente não está ligada. " + INTEGRATIONS[7]["como"] + ".")
        return False
    try:
        states = _ha("/api/states")
    except Exception as e:
        _say(f"O Home Assistant não respondeu: {e}.")
        return False
    want = norm(device)
    best, score = None, 0
    for s in states if isinstance(states, list) else []:
        name = norm(s.get("attributes", {}).get("friendly_name", "") or s.get("entity_id", ""))
        domain = s.get("entity_id", "").split(".")[0]
        if domain not in ("light", "switch", "fan", "cover", "climate", "media_player", "lock"):
            continue
        words = set(want.split()) - {"a", "o", "da", "do", "de"}
        hit = len(words & set(name.split()))
        if want == name:
            hit += 10
        if hit > score:
            best, score = s, hit
    if best is None:
        _say(f"Não achei {device} na casa.")
        return False
    entity = best["entity_id"]
    domain = entity.split(".")[0]
    a = norm(action)
    service = "turn_off" if a.startswith(("deslig", "apag", "fech")) else "toggle" if a.startswith("alter") else "turn_on"
    if domain == "cover":
        service = "close_cover" if service == "turn_off" else "open_cover"
    try:
        _ha(f"/api/services/{domain}/{service}", {"entity_id": entity})
    except Exception as e:
        _say(f"O Home Assistant não fez: {e}.")
        return False
    _say(f"{best.get('attributes', {}).get('friendly_name', entity)}: {'desliguei' if 'off' in service or 'close' in service else 'liguei'}.")
    return True


# ========================= PREÇO DE PRODUTO (63, S57) =========================

PRICE = re.compile(r"R\$\s*([\d.]{1,9},\d{2})")


def extract_price(html):
    """O preço da página: o do JSON-LD (o oficial da loja) ou o primeiro R$ que aparece."""
    for m in re.finditer(r'"price"\s*:\s*"?([\d.,]+)"?', html):
        v = m.group(1)
        v = v.replace(".", "").replace(",", ".") if "," in v else v
        try:
            value = float(v)
            if value > 0:
                return value
        except ValueError:
            continue
    m = PRICE.search(html)
    if m:
        return float(m.group(1).replace(".", "").replace(",", "."))
    return None


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                                               "Accept-Language": "pt-BR,pt;q=0.9"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", "replace")


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def watch_price(url, name="", target=None, fetch=None):
    """Vigia o preço do produto (link da loja). Avisa quando cair (ou chegar no preço desejado)."""
    url = str(url or "").strip()
    if not url.startswith("http"):
        _say("Me mande o link do produto na loja, senhor (ex.: \"vigia o preço de https://...\").")
        return False
    try:
        price = extract_price((fetch or _fetch)(url))
    except Exception as e:
        _say(f"Não consegui abrir a página: {e}.")
        return False
    if price is None:
        _say("Não achei o preço nessa página.")
        return False
    items = [i for i in _load(PRICES, []) if i["url"] != url]
    label = name or urllib.parse.urlsplit(url).netloc.removeprefix("www.")
    items.append({"url": url, "nome": label, "preco": price, "menor": price, "alvo": target,
                  "desde": date.today().isoformat()})
    _save(PRICES, items)
    _say(f"Vigiando {label}: hoje está R$ {_brl(price)}. Aviso quando baixar.")
    return True


def _brl(value):
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def check_prices(fetch=None):
    """Confere os preços vigiados: [aviso] dos que baixaram."""
    items, news = _load(PRICES, []), []
    for it in items:
        try:
            price = extract_price((fetch or _fetch)(it["url"]))
        except Exception:
            continue
        if price is None:
            continue
        if price < it["menor"] - 0.009 or (it.get("alvo") and price <= float(it["alvo"])):
            news.append(f"Senhor, {it['nome']} baixou de R$ {_brl(it['menor'])} para R$ {_brl(price)}.")
            it["menor"] = min(price, it["menor"])
        it["preco"] = price
    _save(PRICES, items)
    return news


def list_prices():
    items = _load(PRICES, [])
    if not items:
        _say("Não estou vigiando preço nenhum.")
        return True
    _say("Preços vigiados:")
    for it in items:
        print(f"  - {it['nome']}: R$ {_brl(it['preco'])} (menor R$ {_brl(it['menor'])})")
    return True


# ========================= ENCOMENDAS DOS CORREIOS (64, S58) =========================

TRACK_CODE = re.compile(r"\b([A-Z]{2}\d{9}[A-Z]{2})\b", re.I)


def track(code, fetch=None):
    """Situação da encomenda: (último evento, data, local) ou None."""
    code = str(code).strip().upper()
    user, token = env("LINKETRACK_USER"), env("LINKETRACK_TOKEN")
    if not (user and token):
        raise RuntimeError("falta ligar o rastreio: " + INTEGRATIONS[8]["como"])
    url = f"https://api.linketrack.com/track/json?user={urllib.parse.quote(user)}&token={token}&codigo={code}"
    data = (fetch or (lambda u: _http(u)))(url)
    events = data.get("eventos", []) if isinstance(data, dict) else []
    if not events:
        return None
    e = events[0]
    return e.get("status", ""), f"{e.get('data', '')} {e.get('hora', '')}".strip(), e.get("local", "")


def track_parcel(code, name="", fetch=None):
    m = TRACK_CODE.search(str(code))
    if not m:
        _say("O código dos Correios tem 2 letras, 9 números e 2 letras (ex.: AB123456789BR).")
        return False
    code = m.group(1).upper()
    try:
        found = track(code, fetch)
    except Exception as e:
        _say(f"Não consegui rastrear agora ({e}). Abri o site dos Correios: digite {code}.")
        try:
            import webbrowser
            webbrowser.open("https://rastreamento.correios.com.br/app/index.php")
        except Exception:
            pass
        return False
    items = [i for i in _load(PARCELS, []) if i["codigo"] != code]
    items.append({"codigo": code, "nome": name or code, "status": found[0] if found else ""})
    _save(PARCELS, items)
    if not found:
        _say(f"A encomenda {code} ainda não tem movimentação. Vou acompanhando e aviso quando mudar.")
        return True
    status_, when, where = found
    _say(f"Encomenda {name or code}: {status_} ({when}{', ' + where if where else ''}). Aviso quando mudar.")
    return True


def check_parcels(fetch=None):
    items, news = _load(PARCELS, []), []
    keep = []
    for it in items:
        try:
            found = track(it["codigo"], fetch)
        except Exception:
            keep.append(it)
            continue
        if found and found[0] != it.get("status"):
            it["status"] = found[0]
            news.append(f"Senhor, a encomenda {it['nome']} mudou: {found[0]}.")
        if not (found and re.search(r"entregue", norm(found[0]))):
            keep.append(it)  # entregue sai da lista
    _save(PARCELS, keep)
    return news


# ========================= VIGIA (preços e encomendas) =========================

def watcher(put, every=3 * 3600):
    """De tempos em tempos (3 h), confere preços e encomendas e avisa o que mudou."""
    def loop():
        time.sleep(120)
        while True:
            for check in (check_prices, check_parcels):
                try:
                    for text in check():
                        put(("aviso", text))
                except Exception:
                    pass
            time.sleep(every)
    threading.Thread(target=loop, daemon=True).start()


# ========================= RESUMO DE VÍDEO PELA LEGENDA (S63) =========================

def video_id(url):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{11})", str(url or ""))
    return m.group(1) if m else None


def youtube_transcript(url, fetch=None):
    """O texto da legenda do vídeo (português se tiver, senão a primeira), sem chave de API. "" se não tiver."""
    import html as _html
    vid = video_id(url)
    if not vid:
        return ""
    get = fetch or _fetch
    page = get(f"https://www.youtube.com/watch?v={vid}&hl=pt-BR")
    tracks = re.findall(r'"baseUrl":"(https:[^"]+?timedtext[^"]+)"[^}]*?"languageCode":"([\w-]+)"', page)
    if not tracks:
        return ""
    tracks.sort(key=lambda t: 0 if t[1].startswith("pt") else 1)
    xml = get(tracks[0][0].encode().decode("unicode_escape"))
    lines = re.findall(r"<text[^>]*>(.*?)</text>", xml, re.S)
    return re.sub(r"\s+", " ", " ".join(_html.unescape(re.sub(r"<[^>]+>", "", line)) for line in lines)).strip()


def summarize_video(url, think, fetch=None):
    try:
        text = youtube_transcript(url, fetch)
    except Exception as e:
        _say(f"Não consegui pegar a legenda do vídeo: {e}.")
        return False
    if not text:
        _say("Esse vídeo não tem legenda que eu consiga ler.")
        return False
    try:
        out = think("Resuma o vídeo pela legenda, em português do Brasil, em até 6 tópicos curtos e uma frase de conclusão.",
                    text[:30000], json_mode=False, temperature=0.2)
    except Exception as e:
        _say(f"Não consegui resumir: {e}.")
        return False
    _say("Resumindo o vídeo...")
    print(re.sub(r"[*_#`]", "", str(out)).strip())
    return True
