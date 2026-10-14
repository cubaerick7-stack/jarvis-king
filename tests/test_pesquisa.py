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



def test_research_answer_is_what_he_says_not_the_ai_reply_written_before(monkeypatch, capsys):
    j = load_jarvis()
    calls = []
    monkeypatch.setattr(j, "think", lambda *a, **k: calls.append(1) or {
        "actions": [{"name": "research", "args": {"query": "segundo turno"}}],
        "reply": "Buscando informações sobre o segundo turno, senhor.", "continue": True})
    monkeypatch.setitem(j.TOOLS_BY_NAME["research"], "run",
                        lambda a: print("Jarvis > Verifiquei, senhor. Flávio tem 52 por cento.") or True)
    j.ask_ai_router("como está o segundo turno")
    out = capsys.readouterr().out
    assert "Buscando informações" not in out and out.strip().endswith("Flávio tem 52 por cento.")
    assert calls == [1]  # não gasta outra volta da IA depois da pesquisa


def test_research_window_never_grows_sideways():
    for rule in (".j-pesquisa .corpo { padding: 0; gap: 0; max-height: min(70vh, 900px); overflow-x: hidden;",
                 "grid-template-columns: repeat(2, minmax(0, 1fr))", ".pq-fonte { display: flex; min-width: 0;"):
        assert rule in HTML, rule


def test_research_uses_the_request_when_the_ai_forgets_the_query(monkeypatch):
    j = load_jarvis()
    j._pedido = "como está o segundo turno"
    assert j._research_query({"query": "eleição 2026"}) == "eleição 2026"
    assert j._research_query({"pergunta": "segundo turno"}) == "segundo turno"
    assert j._research_query({}) == "como está o segundo turno"
    assert j._research_query({"query": "  "}) == "como está o segundo turno"


def test_news_questions_are_left_for_the_ai_to_decide(monkeypatch):
    j = load_jarvis()
    asked = []
    monkeypatch.setattr(j, "research", lambda q: asked.append(q) or True)
    for text in ("OLÁ AS ELEIÇOES ESTAO COMO AGR????", "como está o segundo turno", "quanto está o dólar hoje"):
        assert j.fast_local_router(text) is False, text  # sem atalho: a IA escolhe research e escreve a busca
    assert asked == []
    prompt = j.TOOLS_BY_NAME["research"]["args"]
    assert "palavras-chave" in prompt

def test_news_query_keeps_only_what_matters():
    j = load_jarvis()
    year = __import__("time").strftime("%Y")
    assert j._news_query("OPA TUDO BEM E AS ELEIÇÕES ESTAO COMO") == f"eleições {year}"
    assert j._news_query("como está o segundo turno das eleições 2026?") == "segundo turno eleições 2026"
    assert j._news_query("quanto está o dólar hoje") == "dólar"


def test_big_cards_take_turns_in_the_center_and_minimize_to_the_side():
    for marker in ("const PALCO = new Set(['pesquisa', 'lista', 'texto', 'clima', 'zap'])", "function minimiza(j)",
                   "function restaura(chave)", "doca.id = 'doca'", "'Minimizar para a lateral'"):
        assert marker in HTML, marker


def test_whatsapp_print_takes_screenshot_asks_and_sends(monkeypatch, tmp_path):
    j = load_jarvis()
    shot = tmp_path / "print_1.png"
    shot.write_bytes(b"x")
    sent, asked = [], []
    monkeypatch.setenv("WAHA_URL", "http://x:3000")
    monkeypatch.setattr(j, "_new_screenshot", lambda: shot)
    monkeypatch.setattr(j.W, "find_contact", lambda c, same: ("55@c.us", "Erick Cuba"))
    monkeypatch.setattr(j.W, "send_file", lambda cid, path, cap: sent.append((cid, path)))
    monkeypatch.setattr(j, "confirm", lambda q: asked.append(q) or True)
    assert j.whatsapp_send_file("erick cuba", "print") is True
    assert asked == ["Mando print_1.png para Erick Cuba?"] and sent == [("55@c.us", shot)]
    monkeypatch.setattr(j, "confirm", lambda q: False)
    sent.clear()
    assert j.whatsapp_send_file("erick cuba", "print") is False and sent == []  # sem "sim", não manda


def test_voice_noise_does_not_cancel_the_confirmation(monkeypatch):
    j = load_jarvis()
    j.queue_mode = True
    for fn in ("speak", "set_state"):
        monkeypatch.setattr(j, fn, lambda *a: None)
    monkeypatch.setattr(j.U, "card", lambda *a, **k: None)
    monkeypatch.setattr(j.U, "speech", lambda *a: None)
    j.commands.put(("voz", "Obrigado."))  # ruído que o reconhecimento virou frase
    j.commands.put(("janela", "sim"))
    assert j.confirm("Mando oi para Ana?") is True


def test_lonely_yes_does_not_repeat_the_last_action(monkeypatch, capsys):
    j = load_jarvis()
    monkeypatch.setattr(j, "think", lambda *a, **k: (_ for _ in ()).throw(AssertionError("foi para a IA")))
    for text in ("sim", "Sim, senhor.", "pode mandar", "não"):
        assert j.fast_local_router(text) is True, text
    assert "Não há nada esperando confirmação" in capsys.readouterr().out


def test_whatsapp_sent_line_is_the_caption_not_the_ai_reply(monkeypatch, capsys):
    j = load_jarvis()
    monkeypatch.setattr(j, "think", lambda *a, **k: {"actions": [{"name": "whatsapp_send_file", "args": {"contact": "Erick"}}],
                                                     "reply": "Enviando o print para o senhor Erick Cuba."})
    monkeypatch.setitem(j.TOOLS_BY_NAME["whatsapp_send_file"], "run",
                        lambda a: print("Jarvis > Enviei print_1.png para Erick Cuba.") or True)
    j.ask_ai_router("manda um print pro erick")
    assert capsys.readouterr().out.strip().endswith("Enviei print_1.png para Erick Cuba.")


def test_scheduled_request_arriving_during_a_question_waits_its_turn(monkeypatch):
    j = load_jarvis()
    j.queue_mode = True
    for fn in ("speak", "set_state"):
        monkeypatch.setattr(j, fn, lambda *a: None)
    monkeypatch.setattr(j.U, "card", lambda *a, **k: None)
    monkeypatch.setattr(j.U, "speech", lambda *a: None)
    j.commands.put(("agendado", "toca evidências"))  # chegou a hora no meio do "Posso enviar?"
    j.commands.put(("janela", "sim"))
    assert j.confirm("Mando oi para Ana?") is True  # não cancelou
    assert j.commands.get_nowait() == ("agendado", "toca evidências")  # e ele faz logo depois
    assert any(t["name"] == "schedule_request" for t in j.TOOLS)
