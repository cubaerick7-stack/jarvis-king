import array
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))
import nuvem as N  # noqa: E402
import voz as V  # noqa: E402


def block(level):
    return array.array("h", [level] * V.BLOCK).tobytes()


def test_wake_word_variants():
    assert V.is_wake("jarbas")
    assert V.is_wake("ei jarvis toca lofi")
    assert not V.is_wake("jardim")
    assert not V.is_wake("")


def test_record_stops_after_you_stop_talking():
    audio = iter([block(0)] * 3 + [block(3000)] * 10 + [block(0)] * 50)
    pcm = V.record_command(lambda: next(audio))
    seconds = len(pcm) / 2 / V.SAMPLE_RATE
    assert 2.4 <= seconds <= 2.7  # 0,3 s antes + 1 s falando + 1,2 s de silêncio


def test_record_gives_up_without_speech():
    assert V.record_command(lambda: block(0)) == b""


def test_wav_is_16khz_mono():
    import wave, io
    w = wave.open(io.BytesIO(V.wav_bytes(block(100))))
    assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)


def test_speech_text_has_no_links_or_emoji():
    assert V.clean_for_speech("Tocando **lofi** 🎵 https://youtube.com/x") == "Tocando lofi"


def test_transcribe_prefers_groq_then_gemini(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(N, "_groq_transcribe", lambda wav, key: (_ for _ in ()).throw(OSError("caiu")))
    monkeypatch.setattr(N, "_gemini_transcribe", lambda wav, key: " toca lofi ")
    assert N.transcribe(b"x") == "toca lofi"


def test_multipart_has_file_and_fields():
    body, ctype = N._multipart({"model": "whisper"}, "fala.wav", b"RIFFdata", "audio/wav")
    boundary = ctype.split("boundary=")[1]
    assert body.startswith(f"--{boundary}".encode()) and body.endswith(f"--{boundary}--\r\n".encode())
    assert b'name="model"\r\n\r\nwhisper' in body and b"RIFFdata" in body


def load_jarvis():
    spec = importlib.util.spec_from_file_location("jvoz", ROOT / "windows" / "jarvis_ai.py")
    j = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(j)
    return j


def test_spoken_request_answers_out_loud(monkeypatch):
    j = load_jarvis()
    said, states = [], []
    j.listener = object()
    monkeypatch.setattr(j.V, "say", lambda text, on_state: said.append(text))
    monkeypatch.setattr(j, "set_state", states.append)
    monkeypatch.setattr(j, "think", lambda *a, **k: json.dumps({"actions": [], "reply": "Pois não, senhor. São 3 horas."}))
    j.handle_spoken("me conta uma coisa")
    assert said == ["Pois não, senhor. São 3 horas."]
    assert states[0] == "pensando"


def test_confirm_waits_for_typed_or_spoken_answer(monkeypatch):
    j = load_jarvis()
    j.queue_mode = True
    j.commands.put(("voz", "Sim."))
    assert j.confirm("Mando oi para Ana?") is True
    j.commands.put(("teclado", "não"))
    assert j.confirm("Mando oi para Ana?") is False


def test_reator_shows_reply_and_playing_card(monkeypatch):
    j = load_jarvis()
    shown, cards = [], []
    monkeypatch.setattr(j.U, "speech", shown.append)
    monkeypatch.setattr(j.U, "card", lambda t, x: cards.append((t, x)))
    monkeypatch.setattr(j.B, "available", lambda: True)
    monkeypatch.setattr(j.B, "play_youtube", lambda q: "Tocando: Evidências")
    j.respond("toca evidências")
    assert cards == [("Tocando agora", "Evidências")]
    monkeypatch.setattr(j, "think", lambda *a, **k: json.dumps({"actions": [], "reply": "Às suas ordens, senhor."}))
    j.respond("me conta uma coisa")
    assert shown[-1] == "Às suas ordens, senhor."


def test_reator_html_has_python_hooks():
    html = (ROOT / "windows" / "interface" / "reator.html").read_text(encoding="utf-8")
    for hook in ("window.setEstado", "window.mostraFala", "window.cartao", "background: transparent"):
        assert hook in html
