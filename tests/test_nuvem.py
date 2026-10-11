import importlib.util
import io
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))
import nuvem as N  # noqa: E402


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"{}"))


def ok(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_no_key_means_no_cloud():
    assert not N.available() and not N.groq_available()


def test_overloaded_model_falls_to_next(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    tried = []

    def fake_post(model, body, key):
        tried.append(model)
        if model == "gemini-flash-latest":
            raise http_error(503)
        return ok('{"actions":[],"reply":"oi"}')

    monkeypatch.setattr(N, "_post", fake_post)
    assert N.generate("s", "u", json_mode=True) == '{"actions":[],"reply":"oi"}'
    assert tried == ["gemini-flash-latest", "gemini-flash-lite-latest"]


def test_bad_key_and_quota_are_clear(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(N, "_post", lambda *a: (_ for _ in ()).throw(http_error(401)))
    with pytest.raises(N.CloudError, match="chave"):
        N.generate("s", "u")
    monkeypatch.setattr(N, "_post", lambda *a: (_ for _ in ()).throw(http_error(429)))
    with pytest.raises(N.CloudError, match="limite"):
        N.generate("s", "u")


def test_custom_model_goes_first(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    assert N.models()[0] == "gemini-3.8-flash"


def load_jarvis():
    spec = importlib.util.spec_from_file_location("jn", ROOT / "windows" / "jarvis_ai.py")
    j = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(j)
    return j


@pytest.mark.parametrize("keys, local, order", [
    ({"GEMINI_API_KEY": "k", "GROQ_API_KEY": "g"}, "", ["Gemini", "Groq"]),
    ({"GROQ_API_KEY": "g"}, "", ["Groq"]),
    ({}, "", []),
    ({"GEMINI_API_KEY": "k"}, "1", ["Gemini", "Qwen"]),
])
def test_backend_order(monkeypatch, keys, local, order):
    for k, v in keys.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("JARVIS_LOCAL", local)
    j = load_jarvis()
    assert [n for n, _ in j.ai_backends()] == order


def test_gemini_limit_falls_back_to_groq(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    j = load_jarvis()
    monkeypatch.setattr(j.N, "_post", lambda *a: (_ for _ in ()).throw(http_error(429)))
    sent = []

    def fake_groq(body, key):
        sent.append(body)
        return {"choices": [{"message": {"content": '{"actions":[],"reply":"respondi pelo groq"}'}}]}

    monkeypatch.setattr(j.N, "_groq_post", fake_groq)
    assert j.ask_ai_router("explica a fotossintese") is True
    out = capsys.readouterr().out
    assert "respondi pelo groq" in out and "limite" in out
    assert sent[0]["response_format"] == {"type": "json_object"}
    assert sent[0]["model"] == "llama-3.3-70b-versatile"


def test_groq_skips_unavailable_model(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    tried = []

    def fake_groq(body, key):
        tried.append(body["model"])
        if len(tried) == 1:
            raise http_error(404)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(N, "_groq_post", fake_groq)
    assert N.groq_generate("s", "u") == "ok"
    assert tried == ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


def test_no_ai_configured_is_clear(capsys):
    j = load_jarvis()
    assert j.ask_ai_router("explica a fotossintese") is False
    assert "GEMINI_API_KEY" in capsys.readouterr().out


def test_cloud_json_with_code_fence(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    j = load_jarvis()
    monkeypatch.setattr(j.N, "generate", lambda *a, **k: '```json\n{"actions":[],"reply":"Deodoro foi o 1º presidente."}\n```')
    j.ask_ai_router("quem foi deodoro")
    assert "1º presidente" in capsys.readouterr().out


def test_warm_up_skips_qwen_when_cloud_first(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    j = load_jarvis()
    called = []
    monkeypatch.setattr(j, "chat", lambda **kw: called.append(kw))
    j.warm_up_ai()
    assert called == []  # não gasta CPU com o Qwen se o Gemini está na frente
