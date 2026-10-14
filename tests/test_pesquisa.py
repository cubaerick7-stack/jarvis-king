import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))
import ferramentas as F  # noqa: E402
import nuvem as N  # noqa: E402

HTML = (ROOT / "windows" / "interface" / "reator.html").read_text(encoding="utf-8")


def load_jarvis():
    spec = importlib.util.spec_from_file_location("jpesq", ROOT / "windows" / "jarvis_ai.py")
    j = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(j)
    return j


def grounded(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]},
                            "groundingMetadata": {"groundingChunks": [
                                {"web": {"uri": "https://g1.globo.com/x", "title": "g1.globo.com"}},
                                {"web": {"uri": "https://g1.globo.com/y", "title": "g1.globo.com"}},
                                {"web": {"uri": "https://elpais.com/z", "title": "elpais.com"}}]}}]}


def test_search_generate_turns_on_google_search_and_lists_sources_once(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    bodies = []

    def fake_post(model, body, key):
        bodies.append(body)
        return grounded("resposta")

    monkeypatch.setattr(N, "_search_post", fake_post)
    text, sources = N.search_generate("sistema", "pergunta")
    assert text == "resposta" and bodies[0]["tools"] == [{"google_search": {}}]
    assert [s["nome"] for s in sources] == ["g1.globo.com", "elpais.com"]


def test_research_shows_window_and_speaks_the_short_answer(monkeypatch, capsys):
    j = load_jarvis()
    cards = []
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    resposta = {"tema": "eleição", "titulo": "Flávio lidera", "ranking": [{"nome": "Flávio", "pct": 47}],
                "resumo": "Segundo turno em 25 de outubro.", "fala": "Verifiquei, senhor. Haverá segundo turno."}
    monkeypatch.setattr(j.N, "search_generate", lambda *a, **k: ("```json\n" + json.dumps(resposta) + "\n```",
                                                                  [{"nome": "g1.globo.com", "titulo": ""}]))
    monkeypatch.setattr(j.U, "card", lambda t, x, ms=7000: cards.append((t, x)))
    monkeypatch.setattr(j, "set_state", lambda s: None)
    assert j.research("como está a eleição") is True
    title, payload = cards[0]
    data = json.loads(payload)
    assert title == "Pesquisa · eleição" and data["ranking"][0]["pct"] == 47
    assert data["fontes"] == [{"nome": "g1.globo.com", "titulo": ""}] and "fala" not in data and data["hora"]
    assert "Jarvis > Verifiquei, senhor. Haverá segundo turno." in capsys.readouterr().out


def test_research_with_plain_text_answer_still_shows_a_window(monkeypatch, capsys):
    j = load_jarvis()
    cards = []
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(j.N, "search_generate", lambda *a, **k: ("O dólar fechou a R$ 5,40.", []))
    monkeypatch.setattr(j.U, "card", lambda t, x, ms=7000: cards.append((t, x)))
    monkeypatch.setattr(j, "set_state", lambda s: None)
    assert j.research("dólar") is True
    assert json.loads(cards[0][1])["resumo"] == "O dólar fechou a R$ 5,40."
    assert "O dólar fechou" in capsys.readouterr().out


def test_research_without_key_or_question_does_not_call_the_cloud(monkeypatch, capsys):
    j = load_jarvis()
    monkeypatch.setattr(j.N, "search_generate", lambda *a, **k: pytest_fail())
    assert j.research("") is False
    assert j.research("quem ganhou") is False  # sem GEMINI_API_KEY
    assert "GEMINI_API_KEY" in capsys.readouterr().out


def test_failed_tool_reason_stays_in_the_caption(monkeypatch, capsys):
    j = load_jarvis()
    monkeypatch.setattr(j, "think", lambda *a, **k: {"actions": [{"name": "research", "args": {"query": "eleição"}}],
                                                     "reply": "Pesquisei."})
    monkeypatch.setattr(j, "research", lambda q: print("Jarvis > Não consegui pesquisar agora, senhor.") or False)
    monkeypatch.setitem(j.TOOLS_BY_NAME["research"], "run", lambda a: j.research(a.get("query")))
    j.ask_ai_router("como está a eleição")
    out = capsys.readouterr().out
    assert "Não deu certo" not in out and out.strip().endswith("Não consegui pesquisar agora, senhor.")


def pytest_fail():
    raise AssertionError("não deveria chamar a nuvem")


def test_research_is_in_the_tool_catalog():
    j = load_jarvis()
    assert any(t["name"] == "research" for t in j.TOOLS)


def test_battery_and_system_widgets_use_real_numbers(monkeypatch):
    import types
    import psutil
    bat = types.SimpleNamespace(percent=34.0, power_plugged=False, secsleft=5400)
    monkeypatch.setattr(psutil, "sensors_battery", lambda: bat)
    data = F.battery_metric()
    assert data["icone"] == "bateria" and data["cor"] == "verde" and data["itens"][0]["v"] == "34%"
    assert data["itens"][1] == {"r": "autonomia", "v": "1h30", "s": "restantes"}
    bat.percent = 12.0
    assert F.battery_metric()["cor"] == "vermelho"
    monkeypatch.setattr(psutil, "sensors_battery", lambda: None)
    assert F.battery_metric() is None
    sistema = F.system_metric()
    assert sistema["icone"] == "cpu" and [i["r"] for i in sistema["itens"]] == ["processador", "memória", "disco"]


def test_battery_request_shows_the_widget_instead_of_the_text_window(monkeypatch):
    j = load_jarvis()
    cards = []
    monkeypatch.setattr(j.U, "card", lambda t, x, ms=7000: cards.append((t, x)))
    monkeypatch.setattr(j.F, "battery_metric", lambda: {"icone": "bateria", "cor": "verde", "itens": []})
    j._ran[:] = ["battery_status"]
    j.info_card("Jarvis > Bateria em 34%, na bateria.\n", "Bateria em 34%, na bateria.")
    assert cards == [("Métrica", json.dumps({"icone": "bateria", "cor": "verde", "itens": []}))]
    monkeypatch.setattr(j.F, "battery_metric", lambda: None)  # sem bateria: cai no cartão de texto de sempre
    cards.clear()
    j.info_card("Jarvis > Não achei bateria.\n", "x")
    assert cards and cards[0][0] == "Bateria"


def test_page_has_research_and_metric_windows_without_innerhtml():
    for marker in ("function pesquisa(", "function metrica(", "pesquisa: { pesquisa: true }", "window.camera", "id=\"orbe\"",
                   "FALANDO", "EM RESUMO", "function arrasta("):
        assert marker in HTML, marker
    assert "innerHTML" not in HTML


DDG = """<div class="result results_links results_links_deep web-result "><div class="links_main links_deep result__body">
<h2 class="result__title"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fg1.globo.com%2Felei%C3%A7%C3%B5es&amp;rut=x">Segundo turno &amp; <b>2026</b></a></h2>
<a class="result__snippet" href="x">Flávio e Lula disputam o <b>segundo turno</b> em 25 de outubro.</a></div></div>
<div class="result results_links"><div class="links_main result__body"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Anúncio</a></div></div>"""


def test_duckduckgo_results_are_read_without_browser(monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return DDG.encode("utf-8")

    monkeypatch.setattr(F.urllib.request, "urlopen", lambda req, timeout=10: Resp())
    found = F.web_snippets("segundo turno")
    assert found == [{"titulo": "Segundo turno & 2026", "site": "g1.globo.com",
                      "trecho": "Flávio e Lula disputam o segundo turno em 25 de outubro.",
                      "url": "https://g1.globo.com/eleições"}]


def test_research_uses_duckduckgo_and_any_ai_when_search_quota_is_over(monkeypatch, capsys):
    j = load_jarvis()
    cards = []
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(j.N, "search_generate", lambda *a, **k: (_ for _ in ()).throw(N.CloudError("HTTP 429")))
    monkeypatch.setattr(j.F, "web_snippets", lambda q: [{"titulo": "Segundo turno", "site": "g1.globo.com",
                                                         "trecho": "dia 25", "url": "https://g1.globo.com/x"}])
    seen = []
    monkeypatch.setattr(j, "think", lambda system, user, **k: seen.append(user) or json.dumps(
        {"titulo": "Segundo turno dia 25", "resumo": "Dia 25.", "fala": "Verifiquei, senhor. É dia 25."}))
    monkeypatch.setattr(j.U, "card", lambda t, x, ms=7000: cards.append((t, x)))
    monkeypatch.setattr(j.U, "speech", lambda t: None)
    monkeypatch.setattr(j, "set_state", lambda s: None)
    assert j.research("segundo turno") is True
    assert "g1.globo.com): dia 25" in seen[0]
    assert json.loads(cards[0][1])["fontes"] == [{"nome": "g1.globo.com", "titulo": "Segundo turno"}]
    assert capsys.readouterr().out.strip().endswith("Verifiquei, senhor. É dia 25.")


def test_search_tries_the_models_google_suggested_first_and_keeps_chat_quota(monkeypatch):
    import io
    import urllib.error
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    calls = []

    def quota(model, body, key):
        calls.append(model)
        raise urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(N, "_search_post", quota)
    for _ in range(2):
        try:
            N.search_generate("s", "u")
        except N.CloudError:
            pass
    assert calls == N.search_models() * 2  # sem pausa: toda pergunta tenta o Gemini de novo
    assert calls[:2] == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    assert not any(m in N._limited for m in calls)  # e a cota do chat não é afetada


NEWS_RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>x</title>
<item><title>Segundo turno será em 25 de outubro - g1</title><link>https://news.google.com/a</link>
<pubDate>Tue, 13 Oct 2026 10:00:00 GMT</pubDate><description>&lt;a href="x"&gt;Segundo turno será em 25 de outubro&lt;/a&gt;</description>
<source url="https://g1.globo.com">g1</source></item></channel></rss>"""
BING_RSS = """<?xml version="1.0" encoding="utf-8" ?><rss version="2.0"><channel><title>Bing</title>
<item><title>Pesquisa mostra empate técnico</title><link>https://www.cnnbrasil.com.br/b</link>
<description>Flávio tem 47% e Lula 45% no segundo turno.</description></item></channel></rss>"""


def fake_urlopen(pages):
    class Resp:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.body.encode("utf-8")

    def urlopen(req, timeout=10):
        for host, body in pages.items():
            if host in req.full_url:
                if body is None:
                    raise OSError("sem conexão")
                return Resp(body)
        raise OSError("host desconhecido")
    return urlopen


def test_news_comes_from_google_news_and_bing_rss_without_key(monkeypatch):
    monkeypatch.setattr(F.urllib.request, "urlopen", fake_urlopen({"news.google.com": NEWS_RSS, "bing.com": BING_RSS}))
    found = F.web_snippets("segundo turno")
    assert found[0] == {"titulo": "Segundo turno será em 25 de outubro", "site": "g1",
                        "trecho": "(publicado Tue, 13 Oct 2026)", "url": "https://news.google.com/a"}
    assert found[1] == {"titulo": "Pesquisa mostra empate técnico", "site": "cnnbrasil.com.br",
                        "trecho": "Flávio tem 47% e Lula 45% no segundo turno.", "url": "https://www.cnnbrasil.com.br/b"}


def test_news_falls_back_to_duckduckgo_and_empty_when_all_fail(monkeypatch):
    monkeypatch.setattr(F.urllib.request, "urlopen", fake_urlopen({"news.google.com": None, "bing.com": "<html>bloqueado",
                                                                   "duckduckgo.com": DDG}))
    assert [r["site"] for r in F.web_snippets("segundo turno")] == ["g1.globo.com"]
    monkeypatch.setattr(F.urllib.request, "urlopen", fake_urlopen({}))
    assert F.web_snippets("segundo turno") == []

