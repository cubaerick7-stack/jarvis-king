import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))
import memoria as M  # noqa: E402


def test_profile_facts_and_forget(capsys):
    M.set_profile("cidade", "Recife")
    M.remember("sou alérgico a camarão")
    M.remember("Sou alérgico a camarão")  # repetido não duplica
    data = M.load()
    assert data["perfil"] == {"cidade": "Recife"} and len(data["fatos"]) == 1
    assert "Recife" in M.context() and "camarão" in M.context()
    assert M.forget("camarao") is True
    assert M.load()["fatos"] == []


def test_reminder_fires_once_when_due():
    M.add_reminder("prova de história", "2026-10-16", "07:30")
    assert M.due_reminders(datetime(2026, 10, 16, 7, 0)) == []
    assert M.due_reminders(datetime(2026, 10, 16, 7, 31)) == ["prova de história"]
    assert M.due_reminders(datetime(2026, 10, 16, 8, 0)) == []


def test_reminder_without_hour_is_at_nine():
    M.add_reminder("pagar a conta", "2026-10-20")
    assert M.due_reminders(datetime(2026, 10, 20, 8, 59)) == []
    assert M.due_reminders(datetime(2026, 10, 20, 9, 0)) == ["pagar a conta"]


def test_bad_date_is_refused():
    assert M.add_reminder("x", "sexta") is False


def test_conversation_keeps_only_recent():
    for i in range(10):
        M.add_talk(f"pergunta {i}", f"resposta {i}")
    talk = M.load()["conversa"]
    assert len(talk) == M.MAX_TALK and talk[-1]["voce"] == "pergunta 9"


def write_log(lines):
    M.ACTION_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_history_of_yesterday(capsys):
    y = datetime.now() - timedelta(days=1)
    write_log([f"{y:%Y-%m-%dT10:00:00}\tia:play_youtube\t{{\"query\": \"lofi\"}}",
               f"{datetime.now():%Y-%m-%dT10:00:00}\tset_volume\t30"])
    out = M.history("ontem")
    assert "play_youtube" in out and "set_volume" not in out


def test_habit_needs_three_different_days():
    now = datetime(2026, 10, 11, 22, 0)
    lines = [f"{now - timedelta(days=d):%Y-%m-%dT21:40:00}\tia:play_youtube\t{{\"query\": \"lofi\"}}" for d in (1, 2)]
    write_log(lines)
    assert M.habit_hint(now) == ""
    write_log(lines + [f"{now - timedelta(days=3):%Y-%m-%dT22:30:00}\tia:play_youtube\t{{\"query\": \"lofi\"}}"])
    assert M.habit_hint(now) == "Senhor, a essa hora o senhor costuma ouvir lofi. Quer que eu faça?"


def load_jarvis():
    spec = importlib.util.spec_from_file_location("jmem", ROOT / "windows" / "jarvis_ai.py")
    j = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(j)
    return j


def test_jarvis_routes_and_ai_sees_memory(monkeypatch):
    j = load_jarvis()
    assert j.fast_local_router("meu nome é joão aguiar") is True
    assert M.load()["perfil"]["nome"] == "João Aguiar"
    seen = []
    monkeypatch.setattr(j, "think", lambda s, u, **k: seen.append(u) or json.dumps({"actions": [], "reply": "Boa noite, João."}))
    j.respond("quem ganhou a copa de 2002?")
    j.respond("e quem foi o artilheiro?")
    assert "nome: João Aguiar" in seen[1] and "Usuário: quem ganhou a copa de 2002?" in seen[1]


def test_weather_uses_city_from_profile(monkeypatch):
    j = load_jarvis()
    M.set_profile("cidade", "Recife")
    asked = []
    monkeypatch.setattr(j.F, "weather", lambda city: asked.append(city) or True)
    j.execute_ai_action("weather", {})
    assert asked == ["Recife"]


def test_weather_url_is_ascii(monkeypatch):
    urls = []

    def fake_open(req, timeout):
        urls.append(req.full_url)
        raise OSError("sem rede no teste")

    import ferramentas as F
    monkeypatch.setattr(F.urllib.request, "urlopen", fake_open)
    F.weather("São Paulo")
    urls[0].encode("ascii")
