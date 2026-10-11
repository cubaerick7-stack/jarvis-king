import pytest


@pytest.fixture(autouse=True)
def sem_nuvem(monkeypatch):
    """Os testes nunca chamam o Gemini de verdade, mesmo com a chave configurada no PC."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_NUVEM", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
