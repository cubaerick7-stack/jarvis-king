# -*- coding: utf-8 -*-
"""O reator no ritmo da voz: o volume do microfone (ouvindo) e o da voz dele (falando) chegam à tela."""

import array
import math
import sys
import threading
import time
import types

import pytest

import ui as U
import voz as V


def tom(segundos, rate=24000, volume=8000, freq=200):
    n = int(segundos * rate)
    return array.array("h", (int(volume * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)))


# ---------- medidas ----------

def test_silencio_nao_tem_volume_nem_agudo():
    assert V.voice_shape(array.array("h", [0] * 400).tobytes()) == (0.0, 0.0)
    assert V.voice_shape(b"") == (0.0, 0.0)


def test_chiado_cruza_mais_o_zero_que_vogal():
    vogal = tom(0.04, freq=150).tobytes()
    chiado = array.array("h", [3000, -3000] * 480).tobytes()
    _, cruza_vogal = V.voice_shape(vogal)
    _, cruza_chiado = V.voice_shape(chiado)
    assert cruza_chiado > cruza_vogal
    assert V.sharpness(cruza_vogal) < 0.1
    assert V.sharpness(cruza_chiado) == 1.0


def test_volume_do_microfone_em_quatro_pedacos():
    limiar = 400.0
    quieto = array.array("h", [50, -50] * 800).tobytes()  # 0,1 s de barulho baixinho
    alto = tom(0.1, rate=16000, volume=12000).tobytes()
    assert V.mic_levels(quieto, limiar) == [0.0, 0.0, 0.0, 0.0]
    niveis = V.mic_levels(alto, limiar)
    assert len(niveis) == 4 and all(0.9 <= v <= 1.0 for v in niveis)


def test_gravar_o_pedido_manda_o_volume_para_o_reator(monkeypatch):
    recebidos = []
    monkeypatch.setattr(V, "level_hook", lambda valores, passo, agudo: recebidos.append((valores, passo, agudo)))
    monkeypatch.setattr(V, "is_speech", lambda block: True)
    alto = tom(0.1, rate=16000, volume=9000).tobytes()
    quieto = array.array("h", [0] * 1600).tobytes()
    blocos = iter([alto] * 12 + [quieto] * 30)
    V.record_command(lambda: next(blocos), noise=100.0)
    assert recebidos, "nenhum volume chegou ao reator"
    valores, passo, agudo = recebidos[5]
    assert len(valores) == 4 and passo == 25 and 0 <= agudo <= 1
    assert max(max(v) for v, _, _ in recebidos) > 0.5
    assert recebidos[-1][0] == [0.0, 0.0, 0.0, 0.0]


# ---------- tocar a fala medindo ----------

def test_sem_reator_toca_pelo_windows(monkeypatch):
    tocados = []
    monkeypatch.setattr(V, "level_hook", None)
    monkeypatch.setattr(V, "_play_mp3", lambda path: tocados.append(path))
    monkeypatch.setattr(V, "_play_measured", lambda path: pytest.fail("não devia medir sem o reator"))
    V._play("fala.mp3")
    assert tocados == ["fala.mp3"]


def test_sem_miniaudio_volta_para_o_windows(monkeypatch):
    tocados = []
    monkeypatch.setattr(V, "level_hook", lambda *a: None)
    monkeypatch.setattr(V, "_play_mp3", lambda path: tocados.append(path))
    monkeypatch.setitem(sys.modules, "miniaudio", None)  # import miniaudio falha
    V._play("fala.mp3")
    assert tocados == ["fala.mp3"]


def test_tocando_medido_nao_toca_duas_vezes(monkeypatch):
    monkeypatch.setattr(V, "level_hook", lambda *a: None)
    monkeypatch.setattr(V, "_play_measured", lambda path: True)
    monkeypatch.setattr(V, "_play_mp3", lambda path: pytest.fail("já tocou pelo Bolha"))
    V._play("fala.mp3")


class SaidaFalsa:
    """Uma saída de som de mentira: guarda o que foi tocado."""
    latency = 0.0

    def __init__(self, **kw):
        self.kw, self.escrito, self.parou, self.abortou, self.fechou = kw, bytearray(), False, False, False

    def start(self):
        pass

    def write(self, dados):
        self.escrito += dados
        if self.ao_escrever:
            self.ao_escrever()

    def stop(self):
        self.parou = True

    def abort(self):
        self.abortou = True

    def close(self):
        self.fechou = True

    ao_escrever = None


def falsos(monkeypatch, segundos=0.2):
    som = tom(segundos)
    saidas = []

    def saida(**kw):
        s = SaidaFalsa(**kw)
        saidas.append(s)
        return s

    mini = types.SimpleNamespace(
        SampleFormat=types.SimpleNamespace(SIGNED16="s16"),
        decode_file=lambda path, **kw: types.SimpleNamespace(samples=som, sample_rate=kw["sample_rate"]))
    monkeypatch.setitem(sys.modules, "miniaudio", mini)
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(RawOutputStream=saida))
    return som, saidas


def test_fala_medida_toca_tudo_e_manda_o_ritmo(monkeypatch):
    som, saidas = falsos(monkeypatch)
    niveis = []
    monkeypatch.setattr(V, "level_hook", lambda valores, passo, agudo: niveis.append(valores))
    V._stop_talk.clear()
    assert V._play_measured("fala.mp3") is True
    s = saidas[0]
    assert bytes(s.escrito) == som.tobytes()
    assert s.kw == {"samplerate": V.PLAY_RATE, "channels": 1, "dtype": "int16"}
    assert s.parou and s.fechou and not s.abortou
    assert any(isinstance(v, float) and v > 0.5 for v in niveis)
    assert niveis[-1] == 0.0  # no fim o reator volta a ficar quieto


def test_bolha_para_corta_a_fala_medida(monkeypatch):
    som, saidas = falsos(monkeypatch, segundos=1.0)
    monkeypatch.setattr(V, "level_hook", lambda *a: None)
    V._stop_talk.clear()
    original = SaidaFalsa.ao_escrever
    try:
        SaidaFalsa.ao_escrever = lambda self: V._stop_talk.set() if len(self.escrito) > 4000 else None
        assert V._play_measured("fala.mp3") is True
    finally:
        SaidaFalsa.ao_escrever = original
        V._stop_talk.clear()
    s = saidas[0]
    assert s.abortou and s.fechou
    assert len(s.escrito) < len(som.tobytes())


def test_arquivo_que_nao_abre_nao_conta_como_tocado(monkeypatch):
    def quebra(path, **kw):
        raise OSError("arquivo estranho")

    monkeypatch.setitem(sys.modules, "miniaudio", types.SimpleNamespace(SampleFormat=types.SimpleNamespace(SIGNED16=1),
                                                                         decode_file=quebra))
    assert V._play_measured("fala.mp3") is False


# ---------- a tela ----------

class JanelaFalsa:
    def __init__(self):
        self.js = []
        self.chegou = threading.Event()

    def evaluate_js(self, code):
        self.js.append(code)
        self.chegou.set()


@pytest.fixture
def janela(monkeypatch):
    j = JanelaFalsa()
    monkeypatch.setattr(U, "_window", j)
    monkeypatch.setattr(U, "_estado", "parado")
    monkeypatch.setattr(U, "_nivel", None)
    yield j
    U._window = None  # a bomba percebe e termina
    if U._bomba is not None:
        U._bomba.join(3)


def test_volume_so_vai_para_a_tela_ouvindo_ou_falando(janela):
    U.level(0.7)
    time.sleep(0.15)
    assert janela.js == []
    U.state("falando")
    U.level(0.7, 0, 0.4)
    assert janela.chegou.wait(2)
    assert "window.setNivel&&setNivel([0.7],0,0.4)" in janela.js


def test_volume_do_microfone_vai_em_lista(janela):
    U.state("ouvindo")
    janela.js.clear()
    janela.chegou.clear()
    U.level([0.1, 1.7, -2, 0.5], 25, 0)
    assert janela.chegou.wait(2)
    assert janela.js[-1] == "window.setNivel&&setNivel([0.1, 1.0, 0.0, 0.5],25,0.0)"


def test_sem_janela_o_volume_nao_faz_nada(monkeypatch):
    monkeypatch.setattr(U, "_window", None)
    monkeypatch.setattr(U, "_estado", "falando")
    U.level(0.9)  # não pode travar nem dar erro


def test_a_pagina_do_reator_recebe_o_volume():
    from pathlib import Path
    html = (Path(U.__file__).parent / "interface" / "reator.html").read_text(encoding="utf-8")
    assert "window.setNivel = " in html
    assert "nivelDeVerdade" in html
