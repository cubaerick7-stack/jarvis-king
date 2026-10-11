# -*- coding: utf-8 -*-
"""Voz do Jarvis.

- Ouvir "Jarvis": Vosk, no próprio PC (grátis, leve). Modelo pequeno de português em
  G:\\Jarvis\\modelos\\vosk-pt  (baixe "vosk-model-small-pt-0.3" em alphacephei.com/vosk/models).
- Entender o pedido: Whisper no Groq (ou o Gemini, se não houver chave do Groq).
- Falar: edge-tts com a voz Antônio, mais grave e calma, como um mordomo.

Instalar uma vez:  python -m pip install vosk sounddevice edge-tts
"""

import array
import asyncio
import io
import json
import math
import os
import re
import tempfile
import threading
import time
import wave
from pathlib import Path

import nuvem as N

VOSK_MODEL = Path(os.environ.get("JARVIS_VOSK", r"G:\Jarvis\modelos\vosk-pt"))
VOICE = os.environ.get("JARVIS_VOZ_NOME", "pt-BR-AntonioNeural")
RATE, PITCH = "-6%", "-8Hz"  # um pouco mais devagar e mais grave
SAMPLE_RATE = 16000
BLOCK = 1600  # 0,1 s de áudio
# Como o Vosk em português costuma escrever "Jarvis" (a palavra em inglês não está no vocabulário).
WAKE_WORDS = ["jarvis", "jarbas", "jarve", "jervis"]
MAX_COMMAND = 10.0  # segundos
END_SILENCE = 1.2  # segundos de silêncio que encerram o pedido
NO_SPEECH = 5.0  # desiste se você não falar nada

speaking = threading.Event()  # enquanto ele fala, não se escuta (para não ativar sozinho)


def missing():
    """O que falta instalar para a voz funcionar (lista vazia = pronto)."""
    lacks = []
    for mod in ("vosk", "sounddevice", "edge_tts"):
        try:
            __import__(mod)
        except ImportError:
            lacks.append(mod.replace("_", "-"))
    if not VOSK_MODEL.exists():
        lacks.append(f"modelo do Vosk em {VOSK_MODEL}")
    return lacks


# ------------------------- áudio -------------------------

def rms(block):
    samples = array.array("h", bytes(block))
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def wav_bytes(pcm):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def record_command(read_block, noise=300.0):
    """Grava do microfone até você parar de falar. read_block() devolve 0,1 s de áudio."""
    threshold = max(500.0, noise * 3)
    chunks, spoke, quiet, elapsed = [], False, 0.0, 0.0
    step = BLOCK / SAMPLE_RATE
    while elapsed < MAX_COMMAND:
        block = read_block()
        chunks.append(bytes(block))
        elapsed += step
        if rms(block) >= threshold:
            spoke, quiet = True, 0.0
        else:
            quiet += step
        if spoke and quiet >= END_SILENCE:
            break
        if not spoke and elapsed >= NO_SPEECH:
            return b""
    return b"".join(chunks)


def is_wake(text):
    words = re.findall(r"\w+", (text or "").lower())
    return any(w in WAKE_WORDS for w in words)


# ------------------------- falar -------------------------

def clean_for_speech(text):
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_`#>|]", "", text)
    text = re.sub(r"[^\w\s.,;:!?%°ºª()'\"/-]", "", text)  # tira emojis e símbolos
    return re.sub(r"\s+", " ", text).strip()


def _play_mp3(path):
    """Toca o MP3 pelo próprio Windows (MCI), sem instalar player."""
    import ctypes
    mci = ctypes.windll.winmm.mciSendStringW
    mci(f'open "{path}" type mpegvideo alias jarvisvoz', None, 0, None)
    mci("play jarvisvoz wait", None, 0, None)
    mci("close jarvisvoz", None, 0, None)


def say(text, on_state=None):
    text = clean_for_speech(text)
    if not text:
        return
    import edge_tts
    path = Path(tempfile.gettempdir()) / "jarvis_fala.mp3"
    asyncio.run(edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH).save(str(path)))
    speaking.set()
    if on_state:
        on_state("falando")
    try:
        _play_mp3(path)
    finally:
        time.sleep(0.2)  # o eco da caixa de som some antes de voltar a ouvir
        speaking.clear()
        if on_state:
            on_state("parado")


def beep():
    try:
        import winsound
        winsound.Beep(880, 120)
    except Exception:
        pass


# ------------------------- ouvir -------------------------

class Listener(threading.Thread):
    """Fica ouvindo "Jarvis"; depois grava o pedido e manda o texto para put(("voz", texto))."""

    def __init__(self, put, on_state=None):
        super().__init__(daemon=True)
        self.put = put
        self.on_state = on_state or (lambda s: None)
        self.answer_wanted = threading.Event()  # confirmação: ouve sem precisar dizer "Jarvis"

    def ask_answer(self):
        self.answer_wanted.set()

    def _listen_command(self, read_block, noise):
        self.on_state("ouvindo")
        pcm = record_command(read_block, noise)
        if not pcm:
            self.on_state("parado")
            return ""
        self.on_state("pensando")
        try:
            return N.transcribe(wav_bytes(pcm))
        except Exception as e:
            print(f"\nJarvis > {e}")
            return ""

    def run(self):
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)
        rec = KaldiRecognizer(Model(str(VOSK_MODEL)), SAMPLE_RATE, json.dumps(WAKE_WORDS + ["[unk]"]))
        noise = 300.0
        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK, channels=1, dtype="int16") as stream:
            def read_block():
                return stream.read(BLOCK)[0]

            while True:
                if self.answer_wanted.is_set():
                    while speaking.is_set():
                        read_block()
                    beep()
                    text = self._listen_command(read_block, noise)
                    self.answer_wanted.clear()
                    self.put(("voz", text))
                    continue
                block = read_block()
                if speaking.is_set():
                    continue
                noise = noise * 0.98 + rms(block) * 0.02  # aprende o barulho do ambiente
                done = rec.AcceptWaveform(bytes(block))
                heard = json.loads(rec.Result() if done else rec.PartialResult())
                if is_wake(heard.get("text") or heard.get("partial")):
                    rec.Reset()
                    beep()
                    text = self._listen_command(read_block, noise)
                    if text:
                        self.put(("voz", text))
