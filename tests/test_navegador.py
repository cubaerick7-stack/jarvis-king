import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))
import navegador as B  # noqa: E402


class FakeLocator:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    @property
    def first(self):
        return self

    def wait_for(self, timeout=None):
        pass

    def get_attribute(self, name):
        if self.sel in B.WA_TITLE:  # cabeçalho da conversa aberta no WhatsApp
            return self.page.chat if name == "title" else None
        return "Evidências - Chitãozinho & Xororó"

    def inner_text(self, timeout=None):
        return self.page.chat

    def click(self, timeout=None):
        self.page.log.append(("click", self.sel))

    def is_visible(self):
        return True


class FakeKeyboard:
    def __init__(self, page):
        self.page = page

    def press(self, key):
        self.page.log.append(("press", key))

    def type(self, text):
        self.page.log.append(("type", text))


class FakePage:
    def __init__(self):
        self.log, self.url, self.chat = [], "about:blank", "Ana"
        self.keyboard = FakeKeyboard(self)

    def goto(self, url, **kw):
        self.url = url
        self.log.append(("goto", url))

    def bring_to_front(self):
        pass

    def title(self):
        return "Página"

    def locator(self, sel):
        return FakeLocator(self, sel)

    def is_closed(self):
        return False

    def wait_for_timeout(self, ms):
        pass


def use_fake(monkeypatch):
    p = FakePage()
    monkeypatch.setattr(B, "page", lambda kind="web": p)
    monkeypatch.setattr(B, "_page", p)
    monkeypatch.setattr(B, "_tabs", {"midia": p, "web": p, "zap": p})
    return p


def test_play_youtube_clicks_first_video_in_same_tab(monkeypatch):
    p = use_fake(monkeypatch)
    assert "Evidências" in B.play_youtube("evidências")
    assert p.log[0][0] == "goto" and "search_query=evid" in p.log[0][1]
    assert ("click", B.YT_FIRST_VIDEO) in p.log
    assert B.on_youtube()


def test_youtube_control_keys(monkeypatch):
    p = use_fake(monkeypatch)
    assert B.youtube_control("proximo") is True
    assert B.youtube_control("legenda") is True
    assert B.youtube_control("dança") is False
    assert [k for a, k in p.log if a == "press"] == ["Shift+N", "c"]


def fake_clock(monkeypatch):
    """Relógio falso: o sleep só avança o tempo, para os testes não esperarem de verdade."""
    from types import SimpleNamespace
    now = [1000.0]

    def sleep(s):
        now[0] += s

    monkeypatch.setattr(B, "time", SimpleNamespace(time=lambda: now[0], sleep=sleep))


def test_whatsapp_asks_before_sending(monkeypatch):
    p = use_fake(monkeypatch)
    fake_clock(monkeypatch)
    assert B.whatsapp_send("Ana", "chego às 8", confirm=lambda q: False) is False
    assert ("type", "chego às 8") not in p.log
    asked = []
    assert B.whatsapp_send("Ana", "chego às 8", confirm=lambda q: asked.append(q) or True)
    assert ("type", "chego às 8") in p.log and p.log[-1] == ("press", "Enter")
    assert "Ana" in asked[0]


def test_whatsapp_refuses_wrong_chat(monkeypatch):
    p = use_fake(monkeypatch)
    fake_clock(monkeypatch)
    p.chat = "Mariana"  # a busca por "Ana" abriu a conversa errada
    asked = []
    assert B.whatsapp_send("Ana", "chego às 8", confirm=lambda q: asked.append(q) or True) is False
    assert not asked and ("type", "chego às 8") not in p.log


def test_same_person():
    assert B.same_person("Ana", "Ana Paula")
    assert B.same_person("mãe", "Mãe ❤️")
    assert B.same_person("joao silva", "João")
    assert not B.same_person("Ana", "Mariana")
    assert not B.same_person("Ana", "")


def load_jarvis():
    spec = importlib.util.spec_from_file_location("jnav", ROOT / "windows" / "jarvis_ai.py")
    j = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(j)
    return j


def test_cycle_sees_result_and_decides_next_step(monkeypatch, capsys):
    j = load_jarvis()
    prompts = []
    answers = iter([
        {"actions": [{"name": "web_search", "args": {"query": "receita bolo de cenoura"}}],
         "reply": "Pesquisando.", "continue": True},
        {"actions": [], "reply": "A melhor é a do Tudo Gostoso: 4,8 estrelas.", "continue": False},
    ])
    monkeypatch.setattr(j, "think", lambda system, user, **kw: prompts.append(user) or json.dumps(next(answers)))
    monkeypatch.setattr(j.B, "search", lambda q: "Resultados:\n1. Bolo de cenoura fofinho - https://tudogostoso.com.br/x")
    assert j.ask_ai_router("escolhe a melhor receita de bolo de cenoura") is True
    assert len(prompts) == 2
    assert "Bolo de cenoura fofinho" in prompts[1]  # a IA viu o resultado da pesquisa
    out = capsys.readouterr().out
    assert "Pesquisando." in out and "4,8 estrelas" in out


def test_cycle_has_step_limit(monkeypatch):
    j = load_jarvis()
    calls = []
    forever = json.dumps({"actions": [{"name": "web_read", "args": {}}], "reply": "", "continue": True})
    monkeypatch.setattr(j, "think", lambda *a, **k: calls.append(1) or forever)
    monkeypatch.setattr(j.B, "read_page", lambda: "texto")
    j.ask_ai_router("fica lendo")
    assert len(calls) == j.MAX_STEPS


def test_youtube_uses_jarvis_browser_when_installed(monkeypatch):
    j = load_jarvis()
    monkeypatch.setattr(j.B, "available", lambda: True)
    monkeypatch.setattr(j.B, "play_youtube", lambda q: f"Tocando: {q}")
    monkeypatch.setattr(j.F, "play_youtube", lambda q: (_ for _ in ()).throw(AssertionError("jeito antigo")))
    assert j.execute_ai_action("play_youtube", {"query": "lofi"}) == "Tocando: lofi"
