"""WhatsApp (responder, resumo, áudios, mandar áudio), navegador (abas, favoritos, retomar), tema e downloads."""
import importlib.util
import time
from pathlib import Path

import pytest

import maos
import navegador as B
import waha as W

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def jarvis(monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_ai", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for fn in ("heard", "speech", "card", "state", "behind", "front", "theme"):
        monkeypatch.setattr(mod.U, fn, lambda *a, **k: None)
    monkeypatch.setenv("WAHA_URL", "http://waha:3000")
    mod.origin = "teste"
    return mod


def test_responde_a_ultima_mensagem_com_sim(jarvis, monkeypatch):
    monkeypatch.setattr(W, "incoming", lambda limit=15: [("1@c.us", "Ana", "vem?", 100), ("2@c.us", "Erick", "oi", 200)])
    sent = []
    monkeypatch.setattr(W, "send_text", lambda cid, text: sent.append((cid, text)))
    monkeypatch.setattr(jarvis, "confirm", lambda q: False)
    assert jarvis.whatsapp_reply("já vou") is False and sent == []
    monkeypatch.setattr(jarvis, "confirm", lambda q: True)
    jarvis.whatsapp_reply("já vou")
    assert sent == [("2@c.us", "Já vou")]


def test_roteador_responde(jarvis, monkeypatch):
    calls = []
    monkeypatch.setattr(jarvis, "tool", lambda _n, /, **a: calls.append((_n, a)) or True)
    for frase, esperado in [("responde que já vou", ("whatsapp_reply", {"message": "já vou"})),
                            ("resumo do zap", ("whatsapp_summary", {})),
                            ("ouve os áudios da Ana", ("whatsapp_audios", {"contact": "ana"})),
                            ("grava um áudio de 15 segundos pra mãe", ("whatsapp_send_audio", {"contact": "mae", "seconds": 15})),
                            ("fecha as abas do youtube", ("close_tabs", {"word": "youtube"})),
                            ("volta para a aba do gmail", ("switch_tab", {"word": "gmail"})),
                            ("resume essa página", ("summarize_page", {})),
                            ("salva essa página nos favoritos como receitas", ("favorite_add", {"name": "receitas"})),
                            ("abre o favorito receitas", ("favorite_open", {"name": "receitas"})),
                            ("continua o vídeo de onde parei", ("resume_video", {})),
                            ("manda o primeiro pro celular", ("send_to_phone", {"path": "1"})),
                            ("tema vermelho", ("set_theme", {"name": "vermelho"}))]:
        calls.clear()
        assert jarvis.fast_local_router(frase), frase
        assert calls[0] == esperado, frase


def test_resumo_dos_nao_lidos_por_pessoa(jarvis, monkeypatch, capsys):
    monkeypatch.setattr(W, "unread_chats", lambda: [("1@c.us", "Ana", 2)])
    monkeypatch.setattr(W, "received", lambda cid, n: [("chega às 8?", "10:00"), ("me liga", "10:01")])
    seen = {}

    def think(system, user, **kw):
        seen["user"] = user
        return "Ana quer saber se o senhor chega às 8 e pede uma ligação."
    monkeypatch.setattr(jarvis, "think", think)
    assert jarvis.whatsapp_summary()
    assert "Ana (2 não lidas)" in seen["user"] and "pede uma ligação" in capsys.readouterr().out


def test_ouve_os_audios_recebidos(jarvis, monkeypatch, capsys):
    monkeypatch.setattr(W, "last_incoming", lambda: ("1@c.us", "Ana", "(mídia)", 100))
    monkeypatch.setattr(W, "audio_messages", lambda cid: [("10:00", "http://waha/f.ogg", "audio/ogg; codecs=opus")])
    monkeypatch.setattr(W, "download", lambda url: b"OggS")
    monkeypatch.setattr(jarvis.N, "transcribe", lambda audio, name, mime: "tô chegando")
    assert jarvis.whatsapp_audios()
    assert "10:00: tô chegando" in capsys.readouterr().out


def test_nao_lidas_sem_contador_usa_as_ultimas_12_horas(monkeypatch):
    now = int(time.time())
    monkeypatch.setattr(W, "_call", lambda *a, **k: [
        {"id": "1@c.us", "name": "Ana", "lastMessage": {"fromMe": False, "timestamp": now - 60, "body": "oi"}},
        {"id": "2@c.us", "name": "Bia", "lastMessage": {"fromMe": True, "timestamp": now, "body": "ok"}},
        {"id": "3@c.us", "name": "Caio", "unreadCount": 4, "lastMessage": {"fromMe": False, "timestamp": 1}}])
    assert W.unread_chats() == [("1@c.us", "Ana", 1), ("3@c.us", "Caio", 4)]


def test_favoritos(jarvis, monkeypatch, tmp_path):
    monkeypatch.setattr(jarvis, "FAVORITES", tmp_path / "favoritos.json")
    monkeypatch.setattr(B, "current_url", lambda: ("https://tudogostoso.com.br/bolo", "Bolo de cenoura"))
    opened = []
    monkeypatch.setattr(jarvis, "open_url", lambda url: opened.append(url) or True)
    assert jarvis.favorite_add("receitas")
    assert jarvis.favorite_open("receitas") and opened == ["https://tudogostoso.com.br/bolo"]


def test_retoma_o_video_de_onde_parou(jarvis, monkeypatch):
    monkeypatch.setattr(B, "youtube_position", lambda: ("https://www.youtube.com/watch?v=abc", 125))
    jarvis.remember_video()
    opened = []
    monkeypatch.setattr(jarvis, "open_url", lambda url: opened.append(url) or True)
    jarvis.resume_video()
    assert opened == ["https://www.youtube.com/watch?v=abc&t=125s"]


def test_tema(jarvis, capsys):
    assert jarvis.set_theme("homem de ferro")
    import aprende
    assert aprende.pref("tema") == "vermelho"
    assert jarvis.set_theme("roxo") is False


def test_avisa_quando_o_download_termina(tmp_path):
    got = []
    (tmp_path / "velho.zip").write_text("x")
    maos.watch_downloads(tmp_path, got.append, every=0.05)
    time.sleep(0.15)
    (tmp_path / "jogo.exe.crdownload").write_text("x")
    time.sleep(0.15)
    assert got == []
    (tmp_path / "jogo.exe.crdownload").rename(tmp_path / "jogo.exe")
    time.sleep(0.2)
    assert got and "jogo.exe" in got[0][1]
