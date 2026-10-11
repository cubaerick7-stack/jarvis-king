import pytest


@pytest.fixture(autouse=True)
def sem_nuvem(monkeypatch):
    """Os testes nunca chamam a nuvem de verdade, mesmo com a chave configurada no PC."""
    for var in ("GEMINI_API_KEY", "GROQ_API_KEY", "GROQ_MODEL", "JARVIS_LOCAL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("JARVIS_NUVEM", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)


@pytest.fixture(autouse=True)
def sem_everything(monkeypatch):
    """Os testes não perguntam ao Everything do PC; quem testa a busca simula o es.exe."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows"))
    import ferramentas
    monkeypatch.setattr(ferramentas, "find_es", lambda: None)
