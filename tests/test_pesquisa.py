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


def test_search_falls_back_to_groq_compound_when_gemini_fails(monkeypatch):
    import urllib.error
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setattr(N, "_search_post", lambda *a: (_ for _ in ()).throw(urllib.error.URLError(TimeoutError("timed out"))))
    asked = []

    def fake_groq(body, key):
        asked.append(body["model"])
        return {"choices": [{"message": {"content": "resposta do groq"}}]}

    monkeypatch.setattr(N, "_groq_post", fake_groq)
    assert N.search_generate("s", "u") == ("resposta do groq", [])
    assert asked == ["groq/compound-mini"]


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
