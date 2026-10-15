import sys
from pathlib import Path

import pytest

# Disponível antes de qualquer fixture, inclusive ao rodar um único arquivo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows"))


@pytest.fixture(autouse=True)
def sem_nuvem(monkeypatch):
    """Os testes nunca chamam a nuvem de verdade, mesmo com a chave configurada no PC."""
    for var in ("GEMINI_API_KEY", "GROQ_API_KEY", "GROQ_MODEL", "JARVIS_LOCAL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("JARVIS_NUVEM", raising=False)
    for var in ("WAHA_URL", "WAHA_API_KEY", "WAHA_SESSION", "ELEVENLABS_API_KEY", "JARVIS_YOUTUBE",
                "BOLHA_SENHA", "BOLHA_NGROK", "BOLHA_CELULAR_PORTA", "BOLHA_TOM"):
        monkeypatch.delenv(var, raising=False)  # testes nunca falam com o WhatsApp nem com a ElevenLabs de verdade
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows"))
    import nuvem
    monkeypatch.setattr(nuvem, "_limited", {})
    monkeypatch.setattr(nuvem, "_no_thinking_cfg", set())
    monkeypatch.setattr(nuvem, "_dead", set())
    monkeypatch.setattr(nuvem, "_groq_listed", [])  # nunca pergunta ao Groq de verdade quais modelos existem
    monkeypatch.delenv("JARVIS_TELA", raising=False)


@pytest.fixture(autouse=True)
def nome_padrao():
    """Todo teste começa com o nome padrão ("Bolha"), mesmo com JARVIS_NOME no PC."""
    import voz
    voz.set_name("Bolha")
    yield
    voz.set_name("Bolha")


@pytest.fixture(autouse=True)
def sem_everything(monkeypatch):
    """Os testes não perguntam ao Everything do PC; quem testa a busca simula o es.exe."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows"))
    import ferramentas
    monkeypatch.setattr(ferramentas, "find_es", lambda: None)
    monkeypatch.setattr(ferramentas, "_drives", {})
    monkeypatch.setattr(ferramentas, "_store_apps", {})  # nunca roda o PowerShell do PC nos testes


@pytest.fixture(autouse=True)
def sem_navegador(monkeypatch):
    """Os testes nunca abrem o Edge de verdade; quem testa o navegador usa uma página falsa."""
    import navegador
    monkeypatch.setattr(navegador, "available", lambda: False)
    monkeypatch.setattr(navegador, "_page", None)
    monkeypatch.setattr(navegador, "_tabs", {})


@pytest.fixture(autouse=True)
def memoria_temporaria(tmp_path, monkeypatch):
    """Cada teste tem a própria memória e o próprio log, longe do G:\\Jarvis de verdade."""
    import memoria
    monkeypatch.setattr(memoria, "FILE", tmp_path / "memoria.json")
    monkeypatch.setattr(memoria, "ACTION_LOG", tmp_path / "acoes.log")
    monkeypatch.setenv("JARVIS_LOG", str(tmp_path / "acoes.log"))


# Módulos novos do plano 3.0: tudo o que eles guardam em G:\Jarvis vai para a pasta do teste.
MODULOS_COM_ARQUIVO = ["diario", "aprende", "habilidades", "maos"]


@pytest.fixture(autouse=True)
def arquivos_temporarios(tmp_path, monkeypatch):
    import importlib
    for name in MODULOS_COM_ARQUIVO:
        mod = importlib.import_module(name)
        for attr, value in list(vars(mod).items()):
            if isinstance(value, Path) and str(value).lower().startswith("g:\\"):
                monkeypatch.setattr(mod, attr, tmp_path / "G" / str(value)[3:].replace("\\", "_"))
    import diario
    monkeypatch.setattr(diario, "current", None)
    monkeypatch.setattr(diario, "last", None)
