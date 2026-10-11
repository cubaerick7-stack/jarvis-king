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


def test_no_key_means_local_only():
    assert not N.available()


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


@pytest.mark.parametrize("mode, order", [
    ("primeiro", ["Gemini", "Qwen"]), ("reserva", ["Qwen", "Gemini"]), ("desligada", ["Qwen"]),
])
def test_backend_order(monkeypatch, mode, order):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("JARVIS_NUVEM", mode)
    j = load_jarvis()
    assert [n for n, _ in j.ai_backends()] == order


def test_cloud_failure_falls_back_to_qwen(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    j = load_jarvis()
    monkeypatch.setattr(j.N, "generate", lambda *a, **k: (_ for _ in ()).throw(N.CloudError("sem internet")))

    class Resp:
        class message:
            content = '{"actions":[],"reply":"respondi local"}'

    monkeypatch.setattr(j, "chat", lambda **kw: Resp())
    assert j.ask_ai_router("explica a fotossintese") is True
    out = capsys.readouterr().out
    assert "respondi local" in out and "Gemini falhou" in out


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
