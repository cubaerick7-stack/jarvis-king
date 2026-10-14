"""O Bolha no celular: servidor com senha, pedidos, áudio e a voz indo para o celular.
Roda um servidor de verdade em 127.0.0.1 (porta livre qualquer); nada sai do PC."""
import importlib.util
import json
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))

import celular as C  # noqa: E402
import nuvem as N  # noqa: E402
import ui as U  # noqa: E402

SENHA = "senha-do-joao"


@pytest.fixture
def phone(monkeypatch):
    monkeypatch.setenv("BOLHA_SENHA", SENHA)
    got = []
    heard = []

    def hear(audio, name, mime):
        heard.append((audio, name, mime))
        return "que horas são"

    p = C.Phone(got.append, "Bolha", hear, synth=lambda text: b"ID3" + text.encode())
    p.port = p.start(port_=0)
    p.got, p.heard = got, heard
    yield p
    p.stop()


def call(p, method, path, body=None, headers=None, cookie=None, page=True):
    data = None
    headers = dict(headers or {})
    if isinstance(body, dict):
        data = json.dumps(body).encode()
        headers.setdefault("Content-Type", "application/json")
    elif body is not None:
        data = body
    if page and method == "POST":
        headers["X-Bolha"] = "1"
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(f"http://127.0.0.1:{p.port}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def login(p):
    code, headers, _ = call(p, "POST", "/entrar", {"senha": SENHA})
    assert code == 200
    return headers["Set-Cookie"].split(";")[0]


def test_off_without_password(monkeypatch):
    assert C.start(lambda t: None) is None
    monkeypatch.setenv("BOLHA_SENHA", "curta")
    assert "8 ou mais" in C.start(lambda t: None)
    assert not C.running()


def test_page_is_public_and_marked_for_the_phone(phone):
    code, headers, body = call(phone, "GET", "/")
    html = body.decode()
    assert code == 200
    assert '<body class="celular">' in html and 'rel="manifest"' in html and "<title>Bolha</title>" in html
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    code, _, body = call(phone, "GET", "/manifest.webmanifest")
    assert code == 200 and json.loads(body)["display"] == "standalone"
    assert call(phone, "GET", "/icone-192.png")[0] == 200
    assert call(phone, "GET", "/../celular.py")[0] in (401, 404)


def test_everything_else_needs_the_password(phone):
    assert call(phone, "GET", "/eventos")[0] == 401
    assert call(phone, "POST", "/pedido", {"texto": "desliga o pc"})[0] == 401
    assert call(phone, "POST", "/pedido", {"texto": "desliga o pc"}, cookie="bolha=chute")[0] == 401
    assert phone.got == []


def test_login_then_requests_reach_bolha(phone):
    assert call(phone, "POST", "/entrar", {"senha": "errada-123"})[0] == 401
    code, headers, _ = call(phone, "POST", "/entrar", {"senha": SENHA})
    cookie = headers["Set-Cookie"]
    assert code == 200
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Strict" in cookie and SENHA not in cookie
    assert call(phone, "POST", "/pedido", {"texto": "  abre o spotify "}, cookie=cookie.split(";")[0])[0] == 200
    assert phone.got == ["abre o spotify"]


def test_changing_the_password_logs_the_phone_out(phone, monkeypatch):
    cookie = login(phone)
    monkeypatch.setenv("BOLHA_SENHA", "outra-senha-nova")
    assert call(phone, "GET", "/eventos?desde=0", cookie=cookie)[0] == 401


def test_posts_only_from_the_bolha_page(phone):
    cookie = login(phone)
    assert call(phone, "POST", "/pedido", {"texto": "oi"}, cookie=cookie, page=False)[0] == 403
    assert phone.got == []


def test_five_wrong_passwords_lock_the_door(phone):
    codes = [call(phone, "POST", "/entrar", {"senha": f"chute-{n}"})[0] for n in range(5)]
    assert codes == [401, 401, 401, 401, 429]
    code, _, body = call(phone, "POST", "/entrar", {"senha": SENHA})
    assert code == 429 and "10 minutos" in json.loads(body)["erro"]


def test_phone_sees_what_the_reactor_shows(phone, monkeypatch):
    monkeypatch.setattr(U, "_watchers", [])
    U.watch(phone.events.publish)
    cookie = login(phone)
    U.heard("como está o clima")
    U.state("pensando")
    _, _, body = call(phone, "GET", "/eventos?desde=0", cookie=cookie)
    start = json.loads(body)
    now = {e["tipo"]: e["valor"] for e in start["eventos"]}
    assert now == {"nome": "Bolha", "estado": "pensando", "voce": "como está o clima", "fala": ""}

    answer = {}

    def wait():  # o celular fica esperando a novidade chegar
        answer["data"] = json.loads(call(phone, "GET", f"/eventos?desde={start['ultimo']}", cookie=cookie)[2])

    t = threading.Thread(target=wait)
    t.start()
    time.sleep(0.2)
    U.speech("Verifiquei, senhor. Faz 17 graus.")
    U.card("Clima", "Curitiba: nublado", 12000)
    t.join(5)
    kinds = [(e["tipo"], e.get("valor") or e.get("titulo")) for e in answer["data"]["eventos"]]
    assert kinds[0] == ("fala", "Verifiquei, senhor. Faz 17 graus.")


def test_a_broken_phone_never_stops_the_reactor(monkeypatch):
    monkeypatch.setattr(U, "_watchers", [])
    U.watch(lambda kind, data: 1 / 0)
    U.state("ouvindo")  # não levanta erro


def test_audio_from_the_phone_becomes_a_request(phone):
    cookie = login(phone)
    code, _, body = call(phone, "POST", "/ouvir", b"webm...", {"Content-Type": "audio/webm;codecs=opus"}, cookie)
    assert code == 200 and json.loads(body) == {"texto": "que horas são"}
    assert phone.heard == [(b"webm...", "fala.webm", "audio/webm")]
    assert phone.got == ["que horas são"]
    assert call(phone, "POST", "/ouvir", b"x", {"Content-Type": "image/png"}, cookie)[0] == 415


def test_iphone_audio_goes_as_m4a():
    assert C.audio_name("audio/mp4") == ("fala.m4a", "audio/mp4")
    assert C.audio_name("video/mp4") is None


def test_voice_is_sent_to_the_phone(phone):
    cookie = login(phone)
    seen = phone.events.publish("estado", {"valor": "pensando"})
    phone.say("Pronto, senhor.")
    _, _, body = call(phone, "GET", f"/eventos?desde={seen}", cookie=cookie)
    url = [e for e in json.loads(body)["eventos"] if e["tipo"] == "audio"][0]["url"]
    code, headers, mp3 = call(phone, "GET", url, cookie=cookie)
    assert code == 200 and headers["Content-Type"] == "audio/mpeg" and mp3 == b"ID3Pronto, senhor."
    assert call(phone, "GET", url)[0] == 401  # sem a senha, nem a voz


def test_ngrok_domain_accepts_pasted_link(monkeypatch):
    monkeypatch.setenv("BOLHA_NGROK", ' "https://bolha-joao.ngrok-free.app/" ')
    assert C.ngrok_domain() == "bolha-joao.ngrok-free.app"


def test_without_ngrok_installed_it_still_works_on_the_pc(monkeypatch):
    monkeypatch.setenv("BOLHA_SENHA", SENHA)
    monkeypatch.setenv("BOLHA_NGROK", "bolha-joao.ngrok-free.app")
    monkeypatch.setenv("BOLHA_CELULAR_PORTA", "0")
    monkeypatch.setattr(C, "find_ngrok", lambda: None)
    try:
        line = C.start(lambda t: None)
        assert "o ngrok não abriu (não achei o ngrok.exe" in line and "http://localhost:" in line
        assert C.running()
    finally:
        C.stop()
    assert not C.running()


def test_phone_audio_goes_to_whisper_with_its_format(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    sent = []
    monkeypatch.setattr(N, "_groq_transcribe", lambda audio, key, name, mime: sent.append((name, mime)) or " oi ")
    assert N.transcribe(b"...", "fala.webm", "audio/webm") == "oi"
    assert sent == [("fala.webm", "audio/webm")]


@pytest.fixture
def jarvis(monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_celular", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_answer_to_a_phone_request_is_spoken_on_the_phone(jarvis, monkeypatch):
    on_phone, on_pc = [], []
    monkeypatch.setattr(jarvis, "voice_out", True)
    monkeypatch.setattr(jarvis, "origin", "celular")
    monkeypatch.setattr(jarvis.C, "running", lambda: True)
    monkeypatch.setattr(jarvis.C, "say", on_phone.append)
    monkeypatch.setattr(jarvis.V, "say", lambda text, on_state=None: on_pc.append(text))
    jarvis.speak("Pronto, senhor.")
    assert on_phone == ["Pronto, senhor."] and on_pc == []
    monkeypatch.setattr(jarvis, "origin", "voz")
    jarvis.speak("Pronto, senhor.")
    assert on_pc == ["Pronto, senhor."]


def test_yes_from_the_phone_without_opening_the_pc_microphone(jarvis, monkeypatch):
    class Listener:
        asked = 0

        def ask_answer(self):
            Listener.asked += 1

    monkeypatch.setattr(jarvis, "queue_mode", True)
    monkeypatch.setattr(jarvis, "commands", queue.Queue())
    monkeypatch.setattr(jarvis, "listener", Listener())
    monkeypatch.setattr(jarvis, "origin", "celular")
    jarvis.commands.put(("celular", "sim"))
    assert jarvis.confirm('Mando "oi" para Ana?') is True
    assert Listener.asked == 0
