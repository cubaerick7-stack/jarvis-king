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


def test_forget_my_name_and_short_values():
    M.set_profile("nome", "João")
    M.set_profile("cidade", "Rio")
    assert M.forget("a prova do rio grande") is False  # "Rio" só sai se for ele o assunto
    assert M.forget("meu nome") is True
    assert M.load()["perfil"] == {"cidade": "Rio"}
    assert M.forget("rio") is True and M.load()["perfil"] == {}


def test_broken_json_is_kept_aside_not_erased():
    M.FILE.write_text('{"perfil": {"nome": "João"},}', encoding="utf-8")  # vírgula a mais
    assert M.load()["perfil"] == {}
    assert list(M.FILE.parent.glob("memoria.estragada-*.json"))


def test_unreadable_file_is_never_overwritten(monkeypatch):
    M.set_profile("nome", "João")

    def locked(*a, **k):
        raise PermissionError("preso por outro programa")

    with monkeypatch.context() as m:
        m.setattr(M.time, "sleep", lambda s: None)
        m.setattr(type(M.FILE), "read_bytes", locked)
        assert M.context() == ""  # a IA segue sem memória naquele pedido
        try:
            M.add_talk("oi", "olá")
        except PermissionError:
            pass
    assert M.load()["perfil"] == {"nome": "João"}  # nada foi apagado


def test_reminder_hours_are_normalized():
    assert M.add_reminder("a", "2026-10-16", "7h") and M.load()["lembretes"][-1]["hora"] == "07:00"
    assert M.add_reminder("b", "2026-10-16", "19h30") and M.load()["lembretes"][-1]["hora"] == "19:30"
    assert M.add_reminder("c", "2026-10-16", "24:00")
    assert M.load()["lembretes"][-1]["data"] == "2026-10-17" and M.load()["lembretes"][-1]["hora"] == "00:00"
    assert M.add_reminder("d", "2026-10-16", "25:00") is False
    assert M.add_reminder("e", "2026-10-16", "9:60") is False


def test_broken_reminder_does_not_block_others():
    data = M.load()
    data["lembretes"] = [{"texto": "estragado", "data": "ontem", "hora": "x"},
                         {"texto": "certo", "data": "2026-10-16", "hora": "07:00"}]
    M.save(data)
    assert M.due_reminders(datetime(2026, 10, 16, 8, 0)) == ["estragado", "certo"]


def test_scheduled_request_is_done_on_time_and_late_ones_only_warn(tmp_path, monkeypatch):
    from datetime import datetime
    M.add_reminder("toca evidências", "2026-10-15", "7h", pedido=True)
    M.add_reminder("prova de inglês", "2026-10-15", "7h")
    assert M.due_items(datetime(2026, 10, 15, 6, 59)) == []
    assert M.due_items(datetime(2026, 10, 15, 7, 0, 20)) == [("agendado", "toca evidências"), ("lembrete", "prova de inglês")]
    assert M.due_items(datetime(2026, 10, 15, 7, 1)) == []  # cada um só uma vez
    M.add_reminder("abre o spotify", "2026-10-15", "08:00", pedido=True)
    late = M.due_items(datetime(2026, 10, 15, 9, 0))  # o Bolha estava fechado às 8h: não abre fora de hora
    assert late == [("lembrete", 'não fiz "abre o spotify" às 08:00 de 15/10 porque eu estava desligado')]


def test_alarm_rings_on_time_and_warns_when_missed():
    from datetime import datetime
    M.add_reminder("Evidências", "2026-10-15", "07:00", despertador=True)
    assert M.due_items(datetime(2026, 10, 15, 7, 0, 10)) == [("despertador", "Evidências")]
    M.add_reminder("", "2026-10-16", "07:00", despertador=True)
    assert M.due_items(datetime(2026, 10, 16, 9, 0)) == [("lembrete", "não toquei o despertador das 07:00 porque eu estava desligado")]
