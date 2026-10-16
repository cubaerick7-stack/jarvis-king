"""O botão IA local do reator: troca quem pensa (Qwen no PC ou a nuvem) e guarda a escolha."""
import importlib.util
from pathlib import Path

import pytest

import aprende

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def jarvis(monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_ai", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for fn in ("heard", "speech", "card", "state", "behind", "front", "theme"):
        monkeypatch.setattr(mod.U, fn, lambda *a, **k: None)
    acesos = []
    monkeypatch.setattr(mod.U, "ai_mode", lambda local: acesos.append(local))
    monkeypatch.setattr(mod.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    mod.acesos = acesos
    mod.origin = "teste"
    return mod


def test_frases_trocam_a_ia(jarvis, monkeypatch):
    calls = []
    monkeypatch.setattr(jarvis, "tool", lambda _n, /, **a: calls.append((_n, a)) or True)
    for frase, local in [("usa a IA local", True), ("liga a inteligência artificial local", True),
                         ("troca para a IA local", True), ("usa o Qwen", True),
                         ("volta para a nuvem", False), ("desliga a IA local", False), ("usa a IA da nuvem", False)]:
        calls.clear()
        assert jarvis.fast_local_router(frase), frase
        assert calls[0] == ("set_ai_mode", {"local": local}), frase


def test_ia_local_vem_primeiro_e_a_nuvem_fica_de_reserva(jarvis, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    assert [n for n, _ in jarvis.ai_backends()] == ["Gemini", "Groq"]
    aprende.set_pref("ia_local", True)
    assert [n for n, _ in jarvis.ai_backends()] == ["Qwen", "Gemini", "Groq"]
    assert [n for n, _ in jarvis.ai_backends(prefer="Groq")] == ["Qwen", "Groq", "Gemini"]
    aprende.set_pref("ia_local", False)
    assert [n for n, _ in jarvis.ai_backends()] == ["Gemini", "Groq"]


def test_liga_e_desliga_pelo_botao(jarvis, monkeypatch, capsys):
    monkeypatch.setattr(jarvis, "chat", lambda **k: None)
    monkeypatch.setattr(jarvis, "start_ollama", lambda: {"models": [{"name": "qwen3:1.7b"}]})
    assert jarvis.set_ai_mode(True)
    assert aprende.pref("ia_local") is True and jarvis.acesos == [True]
    assert "IA local ligada" in capsys.readouterr().out
    assert jarvis.set_ai_mode(False)
    assert aprende.pref("ia_local") is False and jarvis.acesos == [True, False]


def test_sem_ollama_nao_liga(jarvis, monkeypatch, capsys):
    monkeypatch.setattr(jarvis, "chat", lambda **k: None)
    monkeypatch.setattr(jarvis, "start_ollama", lambda: None)
    assert jarvis.set_ai_mode(True) is False
    assert aprende.pref("ia_local") is None and jarvis.acesos == []
    assert "Ollama" in capsys.readouterr().out


def test_avisa_quando_o_modelo_nao_esta_baixado(jarvis, monkeypatch, capsys):
    monkeypatch.setattr(jarvis, "chat", lambda **k: None)
    monkeypatch.setattr(jarvis, "start_ollama", lambda: {"models": [{"name": "gemma3:latest"}]})
    assert jarvis.set_ai_mode(True)
    assert "ollama pull qwen3:1.7b" in capsys.readouterr().out
