# -*- coding: utf-8 -*-
"""O Bolha no celular: a mesma tela do reator, aberta no navegador do celular (de qualquer lugar).

No PC, uma vez (veja CELULAR no LEIA-ME):
  setx BOLHA_SENHA "uma-senha-sua"                  (8 ou mais caracteres; sem ela o celular fica desligado)
  setx BOLHA_NGROK "seu-dominio.ngrok-free.app"     (o domínio grátis do ngrok; o Bolha abre o ngrok sozinho)
No celular: abra o link, digite a senha uma vez e use "Adicionar à tela inicial" (vira um app).

O servidor só atende o próprio PC (127.0.0.1): quem leva o celular até ele é o ngrok, com https, que o
microfone do celular exige. Tudo além da página pede a senha, e 5 senhas erradas bloqueiam por 10 minutos.
Apagar, mandar e publicar continuam pedindo "sim", igual no PC.
"""

import hashlib
import hmac
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from collections import deque
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HOST = "127.0.0.1"
PORT = 8765
FOLDER = Path(__file__).resolve().parent / "interface"
PAGE = FOLDER / "reator.html"
FILES = {"/icone.svg": "image/svg+xml", "/icone-192.png": "image/png", "/icone-512.png": "image/png"}
MIN_PASSWORD = 8
MAX_TRIES, LOCK_SECONDS = 5, 600
WAIT = 25  # o celular pergunta "tem novidade?" e espera até 25 s pela resposta
KEEP_EVENTS, KEEP_AUDIO = 200, 4
MAX_JSON, MAX_AUDIO, MAX_TEXT = 64 * 1024, 8 * 1024 * 1024, 2000
MAX_UPLOAD = 300 * 1024 * 1024  # arquivo do celular para o PC (102)
OFFER_HOURS = 12  # o link de um arquivo do PC para o celular vale por 12 horas
COOKIE = "bolha"
COOKIE_DAYS = 30
# Formatos que o microfone do celular grava (Chrome: webm; iPhone: mp4) -> nome do arquivo para o Whisper
AUDIO = {"audio/webm": "fala.webm", "audio/mp4": "fala.m4a", "audio/x-m4a": "fala.m4a", "audio/aac": "fala.m4a",
         "audio/ogg": "fala.ogg", "audio/wav": "fala.wav", "audio/x-wav": "fala.wav", "audio/mpeg": "fala.mp3"}
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; media-src 'self' data: blob:; connect-src 'self'; "
       "manifest-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


class PhoneError(Exception):
    pass


def password():
    return os.environ.get("BOLHA_SENHA", "").strip()


def configured():
    return len(password()) >= MIN_PASSWORD


def port():
    try:
        return int(os.environ.get("BOLHA_CELULAR_PORTA", "").strip() or PORT)
    except ValueError:
        return PORT


def ngrok_domain():
    """O domínio do ngrok, aceitando colado com https:// ou barra no fim."""
    domain = os.environ.get("BOLHA_NGROK", "").strip().strip("\"'")
    for prefix in ("https://", "http://"):
        if domain.lower().startswith(prefix):
            domain = domain[len(prefix):]
    return domain.strip("/")


def _token(secret):
    """O que fica guardado no celular depois da senha: muda se a senha mudar (e aí todos saem)."""
    return hmac.new(secret.encode("utf-8"), b"bolha-celular-1", hashlib.sha256).hexdigest()


def audio_name(mime):
    """("fala.webm", "audio/webm") para o Whisper, ou None se não for um áudio conhecido."""
    mime = (mime or "").split(";")[0].strip().lower()
    return (AUDIO[mime], mime) if mime in AUDIO else None


class Events:
    """O que o reator mostrou (estado, sua fala, a dele, janelas, voz), numerado, para o celular buscar."""

    def __init__(self, name="Bolha"):
        self.cond = threading.Condition()
        self.items = deque(maxlen=KEEP_EVENTS)
        self.last = 0
        self.now = {"nome": name, "estado": "parado", "voce": "", "fala": ""}
        self.audio = {}

    def publish(self, kind, data):
        with self.cond:
            self.last += 1
            self.items.append({"id": self.last, "tipo": kind, **data})
            if kind in ("estado", "voce", "fala"):
                self.now[kind] = data.get("valor", "")
                if kind == "voce":
                    self.now["fala"] = ""
            self.cond.notify_all()
            return self.last

    def add_audio(self, mp3):
        with self.cond:  # o Condition usa RLock: o publish() dentro daqui não trava
            n = self.last + 1
            self.audio[n] = mp3
            for old in sorted(self.audio)[:-KEEP_AUDIO]:
                del self.audio[old]
            return self.publish("audio", {"url": f"/fala/{n}.mp3"})

    def since(self, after, wait=None):
        """(último número, novidades depois de `after`). after=0 (ou de antes do Bolha reabrir) = como está agora."""
        wait = WAIT if wait is None else wait
        with self.cond:
            if after <= 0 or after > self.last:
                start = [{"id": 0, "tipo": k, "valor": self.now[k]} for k in ("nome", "estado", "voce", "fala")]
                return self.last, start
            if wait > 0:
                self.cond.wait_for(lambda: self.last > after, timeout=wait)
            return self.last, [e for e in self.items if e["id"] > after]


class Guard:
    """5 senhas erradas seguidas bloqueiam a entrada por 10 minutos (para ninguém ficar chutando)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.tries = 0
        self.until = 0.0

    def locked(self):
        return time.time() < self.until

    def failed(self):
        with self.lock:
            self.tries += 1
            if self.tries >= MAX_TRIES:
                self.tries, self.until = 0, time.time() + LOCK_SECONDS

    def passed(self):
        with self.lock:
            self.tries = 0


class Handler(BaseHTTPRequestHandler):
    server_version = "Bolha"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # nada de linha no console a cada pergunta do celular

    @property
    def phone(self):
        return self.server.phone

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", headers=()):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, code, message):
        self._send(code, {"erro": message})

    def _authed(self):
        secret = password()
        if len(secret) < MIN_PASSWORD:
            return False
        try:
            got = cookies.SimpleCookie(self.headers.get("Cookie", "")).get(COOKIE)
        except cookies.CookieError:
            return False
        return got is not None and hmac.compare_digest(got.value, _token(secret))

    def _body(self, limit):
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise PhoneError("411") from None
        if size < 0 or size > limit:
            raise PhoneError("413")
        return self.rfile.read(size)

    def _json(self):
        try:
            data = json.loads(self._body(MAX_JSON).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            data = None
        return data if isinstance(data, dict) else {}

    # ------------------------- GET -------------------------
    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            return self._page()
        if path == "/manifest.webmanifest":
            return self._manifest()
        if path in FILES:
            file = FOLDER / path.lstrip("/")
            if file.is_file():
                return self._send(200, file.read_bytes(), FILES[path], [("Cache-Control", "max-age=86400")])
            return self._error(404, "não achei")
        if not self._authed():
            return self._error(401, "falta a senha")
        if path == "/eventos":
            query = parse_qs(urlsplit(self.path).query)
            try:
                after = int(query.get("desde", ["0"])[0])
            except ValueError:
                after = 0
            last, items = self.phone.events.since(after)
            return self._send(200, {"ultimo": last, "eventos": items})
        if path.startswith("/baixar/"):
            return self._download(path[len("/baixar/"):])
        if path.startswith("/fala/") and path.endswith(".mp3"):
            try:
                mp3 = self.phone.events.audio.get(int(path[len("/fala/"):-len(".mp3")]))
            except ValueError:
                mp3 = None
            if mp3 is None:
                return self._error(404, "essa fala já passou")
            return self._send(200, mp3, "audio/wav" if mp3[:4] == b"RIFF" else "audio/mpeg")  # Piper faz WAV
        return self._error(404, "não achei")

    do_HEAD = do_GET

    def _download(self, token):
        """Arquivo que o PC ofereceu ao celular ("manda esse arquivo pro celular")."""
        file = self.phone.offered(token)
        if file is None:
            return self._error(404, "esse link já venceu")
        try:
            size = file.stat().st_size
            from urllib.parse import quote
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(file.name)}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                with file.open("rb") as f:
                    shutil.copyfileobj(f, self.wfile, 256 * 1024)
        except OSError:
            return self._error(404, "o arquivo sumiu do PC")

    def _page(self):
        html = PAGE.read_text(encoding="utf-8")
        name = self.phone.name
        extra = ('<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                 '<meta name="theme-color" content="#02080b">\n'
                 '<meta name="apple-mobile-web-app-capable" content="yes">\n'
                 '<meta name="mobile-web-app-capable" content="yes">\n'
                 '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">\n'
                 f'<meta name="apple-mobile-web-app-title" content="{_html(name)}">\n'
                 '<link rel="manifest" href="/manifest.webmanifest">\n'
                 '<link rel="icon" href="/icone.svg" type="image/svg+xml">\n'
                 '<link rel="apple-touch-icon" href="/icone-192.png">\n')
        html = html.replace("<title>Jarvis</title>", f"<title>{_html(name)}</title>\n{extra}", 1)
        html = html.replace("<body>", '<body class="celular">', 1)  # a página sabe que está no celular
        self._send(200, html, "text/html; charset=utf-8", [("Content-Security-Policy", CSP)])

    def _manifest(self):
        name = self.phone.name
        self._send(200, {
            "name": name, "short_name": name, "lang": "pt-BR", "start_url": "/", "scope": "/",
            "display": "standalone", "orientation": "portrait", "background_color": "#02080b", "theme_color": "#02080b",
            "icons": [{"src": "/icone-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png"},
                      {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
                      {"src": "/icone.svg", "sizes": "any", "type": "image/svg+xml"}],
        }, "application/manifest+json; charset=utf-8")

    # ------------------------- POST -------------------------
    def do_POST(self):
        path = urlsplit(self.path).path
        if self.headers.get("X-Bolha") != "1":  # só a página do Bolha manda isso (outro site não consegue)
            return self._error(403, "pedido de fora da página do Bolha")
        try:
            if path == "/entrar":
                return self._login()
            if path == "/sair":
                return self._send(200, {"ok": True}, headers=[("Set-Cookie", _cookie("", 0))])
            if not self._authed():
                return self._error(401, "falta a senha")
            if path == "/pedido":
                return self._request()
            if path == "/ouvir":
                return self._hear()
            if path == "/arquivo":
                return self._upload()
            return self._error(404, "não achei")
        except PhoneError as e:
            code = int(str(e)) if str(e).isdigit() else 400
            return self._error(code, "pedido grande demais" if code == 413 else "pedido inválido")

    def _login(self):
        guard = self.phone.guard
        if guard.locked():
            return self._error(429, "Muitas senhas erradas. Espere 10 minutos.")
        secret = password()
        typed = str(self._json().get("senha", "")).strip()
        if len(secret) >= MIN_PASSWORD and hmac.compare_digest(typed.encode("utf-8"), secret.encode("utf-8")):
            guard.passed()
            return self._send(200, {"ok": True, "nome": self.phone.name},
                              headers=[("Set-Cookie", _cookie(_token(secret), COOKIE_DAYS * 86400))])
        guard.failed()
        if guard.locked():
            return self._error(429, "Muitas senhas erradas. Espere 10 minutos.")
        return self._error(401, "Senha errada.")

    def _request(self):
        text = str(self._json().get("texto", "")).strip()[:MAX_TEXT]
        if not text:
            return self._error(400, "pedido vazio")
        self.phone.on_text(text)
        return self._send(200, {"ok": True})

    def _upload(self):
        """Arquivo do celular para o PC: cai na pasta "Bolha do celular" dentro dos Downloads."""
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise PhoneError("411") from None
        if size <= 0 or size > MAX_UPLOAD:
            raise PhoneError("413")
        if self.phone.inbox is None:
            return self._error(503, "o PC não está recebendo arquivos agora")
        target = _upload_into(self, size)
        if self.phone.on_file:
            try:
                self.phone.on_file(target)
            except Exception:
                pass
        return self._send(200, {"ok": True, "nome": target.name})

    def _hear(self):
        kind = audio_name(self.headers.get("Content-Type", ""))
        if kind is None:
            return self._error(415, "formato de áudio desconhecido")
        audio = self._body(MAX_AUDIO)
        if not audio:
            return self._send(200, {"texto": ""})
        if self.phone.hear is None:
            return self._error(503, "o Bolha não está ouvindo áudio agora")
        try:
            text = (self.phone.hear(audio, *kind) or "").strip()
        except Exception as e:
            return self._error(502, f"Não entendi o áudio: {e}")
        if text:
            self.phone.on_text(text)
        return self._send(200, {"texto": text})


def safe_name(name):
    """Nome de arquivo sem pastas nem caracteres proibidos no Windows."""
    import re
    from urllib.parse import unquote
    name = Path(unquote(str(name or ""))).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name[:120] or f"arquivo-{time.strftime('%Y%m%d-%H%M%S')}"


def _upload_into(handler, size):
    phone = handler.phone
    if phone.inbox is None:
        raise PhoneError("503")
    folder = Path(phone.inbox)
    folder.mkdir(parents=True, exist_ok=True)
    name = safe_name(handler.headers.get("X-Nome", ""))
    target = folder / name
    n = 1
    while target.exists():
        target = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    left = size
    with target.open("wb") as f:
        while left > 0:
            chunk = handler.rfile.read(min(left, 256 * 1024))
            if not chunk:
                break
            f.write(chunk)
            left -= len(chunk)
    if left:
        target.unlink(missing_ok=True)
        raise PhoneError("400")
    return target


def _cookie(value, seconds):
    return f"{COOKIE}={value}; Max-Age={seconds}; Path=/; HttpOnly; Secure; SameSite=Strict"


def _html(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # no Windows, reusar deixaria dois Bolhas na mesma porta


class Phone:
    """O servidor do celular: pedidos (texto e áudio) entram por on_text; o que o reator mostra sai por events."""

    def __init__(self, on_text, name="Bolha", hear=None, synth=None, inbox=None, on_file=None):
        self.on_text = on_text
        self.inbox = inbox  # pasta onde chegam os arquivos do celular
        self.on_file = on_file  # avisa o Bolha quando um arquivo chega
        self.files = {}  # token -> (caminho, vale até)
        self.name = name
        self.hear = hear  # (áudio, nome do arquivo, mime) -> texto
        self.synth = synth  # texto -> mp3
        self.events = Events(name)
        self.guard = Guard()
        self.httpd = None

    def start(self, host=HOST, port_=None):
        self.httpd = Server((host, PORT if port_ is None else port_), Handler)
        self.httpd.phone = self
        threading.Thread(target=self.httpd.serve_forever, name="celular", daemon=True).start()
        return self.httpd.server_address[1]

    def stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def say(self, text):
        mp3 = self.synth(text) if self.synth else b""
        if mp3:
            self.events.add_audio(mp3)

    def offer(self, path):
        """Oferece um arquivo do PC ao celular: aparece lá um card com o botão de baixar."""
        import secrets
        path = Path(path)
        token = secrets.token_urlsafe(18)
        now = time.time()
        self.files = {k: v for k, v in self.files.items() if v[1] > now}
        self.files[token] = (path, now + OFFER_HOURS * 3600)
        size = path.stat().st_size
        self.events.publish("arquivo", {"nome": path.name, "tamanho": size, "url": f"/baixar/{token}"})
        return token

    def offered(self, token):
        item = self.files.get(str(token))
        if not item or item[1] < time.time() or not item[0].is_file():
            return None
        return item[0]


# ------------------------- ngrok -------------------------
_jobs = []


def find_ngrok():
    found = shutil.which("ngrok")
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "ngrok" / "ngrok.exe"
    for path in (Path(r"G:\Jarvis\ngrok.exe"), Path(r"G:\Jarvis\ngrok\ngrok.exe"), local):
        if path.is_file():
            return str(path)
    return None


def _close_with_me(proc):
    """O ngrok fecha junto com o Bolha, até se ele cair (um "Job" do Windows que morre com ele)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32")
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # 9 = ExtendedLimitInformation
        k32.AssignProcessToJobObject(job, int(proc._handle))
        _jobs.append(job)  # fica aberto enquanto o Bolha roda
    except Exception:
        pass


def _ngrok_error(log):
    """A última linha de erro do log do ngrok, sem o resto."""
    try:
        lines = [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if "err=" in line]
    except OSError:
        return ""
    if not lines:
        return ""
    err = lines[-1].split("err=", 1)[1].strip().strip('"')
    return err.replace("\\n", " ")[:220]


def _ngrok_online(domain, api="http://127.0.0.1:4040/api/tunnels"):
    try:
        with urllib.request.urlopen(api, timeout=1) as r:
            tunnels = json.loads(r.read().decode("utf-8")).get("tunnels", [])
        return any(domain in str(t.get("public_url", "")) for t in tunnels)
    except Exception:
        return False


def start_ngrok(domain, port_, wait=8.0):
    """Abre o ngrok escondido levando https://domínio até a porta do Bolha. Volta o processo ou PhoneError."""
    exe = find_ngrok()
    if not exe:
        raise PhoneError("não achei o ngrok.exe (veja CELULAR no LEIA-ME)")
    log = Path(tempfile.gettempdir()) / "bolha_ngrok.log"
    with open(log, "w", encoding="utf-8") as out:
        proc = subprocess.Popen([exe, "http", str(port_), f"--url=https://{domain}", "--log=stdout", "--log-format=logfmt"],
                                stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _close_with_me(proc)
    deadline = time.time() + wait
    while time.time() < deadline:
        if proc.poll() is not None:
            raise PhoneError(f"o ngrok fechou: {_ngrok_error(log) or 'rode ngrok http ' + str(port_) + ' para ver o erro'}")
        if _ngrok_online(domain):
            break
        time.sleep(0.3)
    return proc


# ------------------------- o celular do Bolha -------------------------
_phone = None
_ngrok = None


def start(on_text, name="Bolha", hear=None, synth=None, inbox=None, on_file=None):
    """Liga o celular. Volta a linha para o console (ou None se nem foi configurado)."""
    global _phone, _ngrok
    if not password():
        return None
    if not configured():
        return f"Celular desligado: a BOLHA_SENHA precisa de {MIN_PASSWORD} ou mais caracteres."
    phone = Phone(on_text, name, hear, synth, inbox, on_file)
    try:
        used = phone.start(port_=port())
    except OSError as e:
        return f"Celular desligado: a porta {port()} está ocupada ({e.strerror or e})."
    _phone = phone
    domain = ngrok_domain()
    if not domain:
        return (f"Celular: http://localhost:{used} (para abrir no celular, falta o ngrok: veja CELULAR no LEIA-ME)")
    try:
        _ngrok = start_ngrok(domain, used)
    except (PhoneError, OSError) as e:
        return f"Celular: o ngrok não abriu ({e}). No PC funciona em http://localhost:{used}"
    return f"Celular: abra https://{domain} no celular"


def publish(kind, data):
    """Liga no ui.watch: tudo o que o reator mostra vai também para o celular."""
    if _phone is not None:
        _phone.events.publish(kind, data)


def running():
    return _phone is not None


def offer_file(path):
    """ "manda esse arquivo pro celular": um card com o botão de baixar aparece no celular."""
    path = Path(path)
    if _phone is None:
        print("Jarvis > O celular não está ligado (veja CELULAR no LEIA-ME).")
        return False
    if not path.is_file():
        print(f"Jarvis > Não achei o arquivo {path}.")
        return False
    _phone.offer(path)
    print(f"Jarvis > Mandei {path.name} para o celular: toque em Baixar lá.")
    return True


def say(text):
    if _phone is not None:
        _phone.say(text)


def stop():
    global _phone, _ngrok
    if _ngrok is not None:
        try:
            _ngrok.terminate()
        except OSError:
            pass
        _ngrok = None
    if _phone is not None:
        _phone.stop()
        _phone = None
