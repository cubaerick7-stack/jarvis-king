"""Piper: a voz feita no PC, de reserva quando falta internet (ou a principal, se o senhor quiser)."""
import importlib.util
import io
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))
import voz as V  # noqa: E402


def _edge(monkeypatch, fail):
    calls = []

    class Communicate:
        def __init__(self, text, *a, **k):
            self.text = text

        async def save(self, path):
            calls.append(self.text)
            if fail:
                raise RuntimeError("Cannot connect to host speech.platform.bing.com")
            Path(path).write_bytes(b"ID3mp3")

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=Communicate))
    monkeypatch.setattr(V, "_edge_off_until", 0.0)
    monkeypatch.setattr(V, "_play_mp3", lambda path: None)
    monkeypatch.setattr(V, "_has_gtts", lambda: False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("BOLHA_VOZ", raising=False)
    return calls


@pytest.fixture
def piper(monkeypatch):
    used = []
    monkeypatch.setattr(V, "has_piper", lambda: True)
    monkeypatch.setattr(V, "_piper_wav", lambda text, path: used.append(text) or Path(path).write_bytes(b"RIFFwav"))
    return used


def test_piper_e_a_voz_padrao_e_nao_usa_o_cache_do_bing(monkeypatch, piper):
    edge = _edge(monkeypatch, fail=False)
    V.CACHE.mkdir(parents=True, exist_ok=True)
    V._cache_file("Pronto.").write_bytes(b"ID3bing antigo")  # frase que o Bing já tinha gravado
    V.say("Pronto.")
    assert piper == ["Pronto."] and edge == []


def test_piper_falhou_fala_pelo_bing(monkeypatch, capsys):
    edge = _edge(monkeypatch, fail=False)
    monkeypatch.setattr(V, "has_piper", lambda: True)
    monkeypatch.setattr(V, "_piper_wav", lambda text, path: (_ for _ in ()).throw(RuntimeError("modelo quebrado")))
    V.say("Oi.")
    assert edge == ["Oi."] and "o Piper falhou" in capsys.readouterr().out


def test_escolheu_o_bing_e_sem_internet_o_piper_cobre(monkeypatch, piper):
    edge = _edge(monkeypatch, fail=False)
    V.set_main_voice("bing")
    V.say("Boa noite.")
    assert edge == ["Boa noite."] and piper == []
    _edge(monkeypatch, fail=True)
    V.say("Abrindo o bloco de notas.")
    assert piper == ["Abrindo o bloco de notas."]
    assert not V._cache_file("Abrindo o bloco de notas.").exists()  # com internet, volta a voz do Bing
    V.set_main_voice("piper")
    assert V.main_voice() == "piper"


def test_sem_piper_baixado_nao_entra_na_fila():
    assert V.has_piper() is False  # a pasta do teste está vazia
    assert "Piper" not in V.voices_summary()


def test_reconhece_o_wav_do_piper(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"RIFF....WAVE")
    (tmp_path / "b.mp3").write_bytes(b"ID3....")
    assert V._is_wav(tmp_path / "a.mp3") and not V._is_wav(tmp_path / "b.mp3")


def test_baixa_a_voz_escolhida(monkeypatch):
    monkeypatch.setenv("JARVIS_PIPER_VOZ", "cadu")
    urls = []

    def fake_open(url, timeout=0):
        urls.append(url)
        return io.BytesIO(b"modelo")
    monkeypatch.setattr(V.urllib.request, "urlopen", fake_open)
    model = V.download_piper()
    assert model.name == "pt_BR-cadu-medium.onnx" and model.read_bytes() == b"modelo"
    assert Path(str(model) + ".json").is_file()
    assert urls[-1] == ("https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/cadu/medium/"
                        "pt_BR-cadu-medium.onnx")


def test_razo_e_a_voz_padrao(monkeypatch):
    monkeypatch.delenv("JARVIS_PIPER_VOZ", raising=False)
    urls = []
    monkeypatch.setattr(V.urllib.request, "urlopen", lambda url, timeout=0: urls.append(url) or io.BytesIO(b"x"))
    model = V.download_piper()
    assert model.name == "pt-BR-razo-medium.onnx" and Path(str(model) + ".json").is_file()
    assert urls == ["https://huggingface.co/Lucasllfs/Razo-piper-voice/resolve/main/config.json",
                    "https://huggingface.co/Lucasllfs/Razo-piper-voice/resolve/main/pt-BR-razo-medium.onnx"]


@pytest.fixture
def jarvis(monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_ai", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for fn in ("heard", "speech", "card", "state", "behind", "front", "theme"):
        monkeypatch.setattr(mod.U, fn, lambda *a, **k: None)
    mod.origin = "teste"
    return mod


def test_frases_da_voz(jarvis, monkeypatch):
    calls = []
    monkeypatch.setattr(jarvis, "tool", lambda _n, /, **a: calls.append((_n, a)) or True)
    for frase, esperado in [("testa a voz piper", ("test_piper", {})), ("Bolha, testa o Piper", ("test_piper", {})),
                            ("usa sempre a voz piper", ("set_voice", {"name": "piper"})),
                            ("volta para a voz do Bing", ("set_voice", {"name": ""})),
                            ("tira a voz piper", ("set_voice", {"name": ""}))]:
        calls.clear()
        assert jarvis.fast_local_router(frase), frase
        assert calls[0] == esperado, frase


def test_testa_sem_instalar_explica_o_pip(jarvis, monkeypatch, capsys):
    monkeypatch.setattr(V, "piper_installed", lambda: False)
    assert jarvis.test_piper() is False
    assert "pip install piper-tts" in capsys.readouterr().out


def test_testa_baixa_e_fala(jarvis, monkeypatch, capsys):
    monkeypatch.setattr(V, "piper_installed", lambda: True)
    baixou, falou = [], []
    monkeypatch.setattr(V, "download_piper", lambda: baixou.append(1))
    monkeypatch.setattr(V, "say_piper", lambda text, on_state=None: falou.append(text))
    assert jarvis.test_piper()
    assert baixou == [1] and falou == [jarvis.PIPER_SAMPLE]
    out = capsys.readouterr().out
    assert all(line.startswith("Jarvis > (") for line in out.splitlines() if line.startswith("Jarvis >"))  # não fala 2x


def test_so_vira_principal_com_a_voz_baixada(jarvis, monkeypatch):
    assert jarvis.set_voice("piper") is False
    monkeypatch.setattr(V, "has_piper", lambda: True)
    assert jarvis.set_voice("piper") and V.main_voice() == "piper"
    assert jarvis.set_voice("") and V.main_voice() == "bing"


def test_ritmo_da_voz(jarvis, monkeypatch):
    assert V.piper_pace() == V.PIPER_PACE > 1  # já começa mais tranquilo que o modelo
    calls = []
    monkeypatch.setattr(jarvis, "tool", lambda _n, /, **a: calls.append((_n, a)) or True)
    for frase, slower in [("fala mais devagar", True), ("fala um pouco mais tranquilo", True),
                          ("fala mais rápido", False)]:
        calls.clear()
        assert jarvis.fast_local_router(frase), frase
        assert calls[0] == ("voice_pace", {"slower": slower}), frase
    jarvis.voice_pace(True)
    assert V.piper_pace() == round(V.PIPER_PACE + 0.1, 2)
    for _ in range(20):
        jarvis.voice_pace(False)
    assert V.piper_pace() == 0.8
