"""Tudo pela IA (pedido do João, 02/11/2026): nada de atalho de palavra-chave antes da IA; os atalhos só
valem quando nenhuma IA responde. E a resposta da IA nunca é falada como JSON."""
import importlib.util
from pathlib import Path

import pytest

import nuvem as N

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def jarvis(monkeypatch):
    monkeypatch.delenv("BOLHA_ATALHOS", raising=False)
    spec = importlib.util.spec_from_file_location("jarvis_ai", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.calls = []
    for fn in ("heard", "speech", "card", "state", "behind", "front"):
        monkeypatch.setattr(mod.U, fn, lambda *a, **k: None)
    monkeypatch.setattr(mod.F, "foreground_window", lambda: None)
    monkeypatch.setattr(mod.F, "second_monitor", lambda: None)
    monkeypatch.setattr(mod, "execute_ai_action", lambda name, args: mod.calls.append((name, args)) or True)
    mod.origin = "teste"
    return mod


def test_alarme_com_volume_nao_vira_volume_agora(jarvis, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setattr(jarvis, "fast_local_router", lambda t: pytest.fail("não pode usar atalho com a IA no ar"))
    seen = {}

    def groq_tools(system, user, tools, **kw):
        seen["tools"] = [t["function"]["name"] for t in tools]
        seen["system"] = system
        return {"actions": [{"name": "set_alarm", "args": {"hour": "05:50", "music": "Eye of the Tiger"}},
                            {"name": "schedule_request", "args": {"hour": "05:50", "request": "volume em 100"}}],
                "reply": "Às 5:50, senhor."}
    monkeypatch.setattr(N, "groq_tools", groq_tools)
    jarvis.handle("alarme 5:50 com eye of the tiger no começo no volume 100")
    assert [c[0] for c in jarvis.calls] == ["set_alarm", "schedule_request"]
    assert "set_alarm" in seen["tools"] and "schedule_request" in seen["tools"]
    assert "TUDO o que ele pede acontece naquele horário" in seen["system"]


def test_sem_ia_os_atalhos_ainda_funcionam(jarvis, monkeypatch):
    used = []
    monkeypatch.setattr(jarvis, "fast_local_router", lambda t: used.append(t) or True)
    jarvis.handle("volume 30")
    assert used == ["volume 30"]


def test_sim_solto_nao_vai_para_a_ia(jarvis, monkeypatch, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setattr(N, "groq_tools", lambda *a, **k: pytest.fail("um sim solto não é pedido"))
    jarvis.handle("sim")
    assert "Não há nada esperando confirmação" in capsys.readouterr().out


def test_para_nao_vai_para_a_ia(jarvis, monkeypatch, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setattr(N, "groq_tools", lambda *a, **k: pytest.fail("o para é na hora"))
    jarvis.handle("Bolha, para")
    assert "par" in capsys.readouterr().out.lower()


def test_resposta_em_json_nao_e_falada_como_codigo(jarvis, monkeypatch, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setattr(N, "groq_tools", lambda *a, **k: {
        "actions": [], "reply": '{"actions":[],"reply":"Desculpe, senhor. Diga o que precisa."}'})
    jarvis.handle("vc nao espera eu falar")
    out = capsys.readouterr().out
    assert "Jarvis > Desculpe, senhor. Diga o que precisa." in out
    assert '"actions"' not in out


def test_json_cortado_usa_o_modo_texto(jarvis, monkeypatch, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setattr(N, "groq_tools", lambda *a, **k: {"actions": [], "reply": "{"})
    monkeypatch.setattr(jarvis, "think", lambda s, p, parse=None, **k: parse('{"actions":[],"reply":"Pois não, senhor."}'))
    jarvis.handle("q num horario especifico vc mecha no volume")
    out = capsys.readouterr().out
    assert "Jarvis > Pois não, senhor." in out
    assert "Jarvis > {" not in out
