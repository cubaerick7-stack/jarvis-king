import pytest


@pytest.fixture(autouse=True)
def sem_nuvem(monkeypatch):
    """Os testes nunca chamam a nuvem de verdade, mesmo com a chave configurada no PC."""
    for var in ("GEMINI_API_KEY", "GROQ_API_KEY", "GROQ_MODEL", "JARVIS_LOCAL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("JARVIS_NUVEM", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
