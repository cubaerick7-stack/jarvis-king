import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))

import navegador as B  # noqa: E402
import waha as W  # noqa: E402


class FakeWaha:
    """O WAHA de mentira: guarda as chamadas e responde como o de verdade."""

    def __init__(self, monkeypatch):
        self.calls = []
        monkeypatch.setenv("WAHA_URL", "http://192.168.0.15:3000/")
        monkeypatch.setenv("WAHA_API_KEY", "senha")
        monkeypatch.delenv("WAHA_SESSION", raising=False)
        monkeypatch.setattr(W.urllib.request, "urlopen", self.open)

    def open(self, req, timeout=0):
        url = req.full_url
        body = json.loads(req.data) if req.data else None
        self.calls.append((req.get_method(), url, body, req.get_header("X-api-key")))
        if "/api/contacts/all" in url:
            data = [{"id": "5541911112222@c.us", "name": "Ana Paula"}, {"id": "5541933334444@c.us", "name": "Mariana"},
                    {"id": "120363@g.us", "name": "Ana grupo"}]
        elif "/api/contacts/check-exists" in url:
            data = {"numberExists": True, "chatId": "554191112222@c.us"}
        elif "/chats/overview" in url:
            data = [{"id": "5541911112222@c.us", "name": "Ana Paula",
                     "lastMessage": {"body": "chego às 8", "fromMe": False, "timestamp": 1760300000}}]
        elif "/messages" in url:
            data = [{"body": "oi", "fromMe": True, "timestamp": 1760299000},
                    {"body": "tudo bem?", "fromMe": False, "timestamp": 1760299500}]
        else:
            data = {"id": "msg1"}
        return Resp(data)


class Resp:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.data


def test_without_waha_url_it_is_off(monkeypatch):
    monkeypatch.delenv("WAHA_URL", raising=False)
    assert not W.configured()


def test_send_asks_first_then_sends_by_waha(monkeypatch):
    fake = FakeWaha(monkeypatch)
    asked = []
    result = B.whatsapp_send("Ana", "chego às 8", lambda q: asked.append(q) or True)
    assert asked == ['Mando "chego às 8" para Ana Paula?']
    assert result == "Enviado para Ana Paula: chego às 8"
    method, url, body, key = fake.calls[-1]
    assert method == "POST" and url == "http://192.168.0.15:3000/api/sendText" and key == "senha"
    assert body == {"session": "default", "chatId": "5541911112222@c.us", "text": "chego às 8"}


def test_no_answer_no_message(monkeypatch):
    fake = FakeWaha(monkeypatch)
    assert B.whatsapp_send("Ana", "oi", lambda q: False) is False
    assert not any("sendText" in c[1] for c in fake.calls)


def test_phone_number_gets_brazil_code(monkeypatch):
    fake = FakeWaha(monkeypatch)
    assert B.whatsapp_send("41 99111-2222", "oi", lambda q: True)
    assert any("check-exists" in c[1] and "phone=5541991112222" in c[1] for c in fake.calls)
    assert fake.calls[-1][2]["chatId"] == "554191112222@c.us"  # o chatId que o WAHA devolveu


def test_waha_down_falls_back_to_whatsapp_web(monkeypatch, capsys):
    monkeypatch.setenv("WAHA_URL", "http://192.168.0.15:3000")

    def down(req, timeout=0):
        raise OSError("connection refused")

    monkeypatch.setattr(W.urllib.request, "urlopen", down)
    monkeypatch.setattr(B, "page", lambda kind="web": (_ for _ in ()).throw(RuntimeError("web")))
    try:
        B.whatsapp_send("Ana", "oi", lambda q: True)
    except RuntimeError as e:
        assert str(e) == "web"  # foi para o WhatsApp Web
    assert "vou pelo WhatsApp Web" in capsys.readouterr().out


def test_read_recent_and_from_contact(monkeypatch, capsys):
    FakeWaha(monkeypatch)
    assert B.whatsapp_read() is True
    out = capsys.readouterr().out
    assert "Últimas conversas no WhatsApp:" in out and "Ana Paula: chego às 8" in out
    assert B.whatsapp_read("Ana") is True
    out = capsys.readouterr().out
    assert "Últimas mensagens com Ana Paula:" in out
    assert out.index("Você: oi") < out.index("Ana Paula: tudo bem?")


def test_bolha_sends_by_waha_without_moving_the_reactor(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("jarvis_waha", ROOT / "windows" / "jarvis_ai.py")
    J = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(J)
    fake = FakeWaha(monkeypatch)
    moved = []
    monkeypatch.setattr(J, "confirm", lambda q: True)
    monkeypatch.setattr(J.U, "behind", lambda: moved.append("atrás"))
    J.execute_ai_action("whatsapp_send", {"contact": "Ana", "message": "oi"})
    assert fake.calls[-1][2]["text"] == "oi"
    assert moved == []  # pelo WAHA nada abre na tela, então o reator fica onde está
