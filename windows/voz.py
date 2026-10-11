# -*- coding: utf-8 -*-
"""Voz do Jarvis.

- Ouvir "Jarvis": Vosk, no próprio PC (grátis, leve). O modelo pequeno de português é
  baixado sozinho na primeira vez para G:\\Jarvis\\modelos\\vosk-pt (uns 30 MB).
- Entender o pedido: Whisper no Groq (ou o Gemini, se não houver chave do Groq).
- Falar: edge-tts com a voz Antônio, mais grave e calma, como um mordomo.

Instalar uma vez:  python -m pip install vosk sounddevice edge-tts
"""

import array
import collections
import asyncio
import difflib
import io
import json
import math
import os
import re
import tempfile
import threading
import unicodedata
import time
import urllib.request
import wave
import zipfile
from pathlib import Path

import nuvem as N

VOSK_MODEL = Path(os.environ.get("JARVIS_VOSK", r"G:\Jarvis\modelos\vosk-pt"))
MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip"
VOICE = os.environ.get("JARVIS_VOZ_NOME", "pt-BR-AntonioNeural")
RATE, PITCH = "-6%", "-8Hz"  # um pouco mais devagar e mais grave
SAMPLE_RATE = 16000
BLOCK = 1600  # 0,1 s de áudio
# Como o Vosk em português pode escrever "Jarvis" (a palavra em inglês não está no vocabulário dele).
WAKE_WORDS = ["jarvis", "jarbas", "javis", "jarves", "jervis", "jarvi", "jarve", "garvis", "jarvas", "jabis"]
MAX_COMMAND = 10.0  # segundos
END_SILENCE = 1.2  # segundos de silêncio que encerram o pedido
NO_SPEECH = 5.0  # desiste se você não falar nada
PRE_BUFFER = 25  # 2,5 s antes do "Jarvis": pega o "Jarvis, toca lofi" dito de uma vez só

speaking = threading.Event()  # enquanto ele fala, não se escuta (para não ativar sozinho)


def missing():
    """Bibliotecas que faltam para a voz funcionar (lista vazia = pronto)."""
    lacks = []
    for mod in ("vosk", "sounddevice", "edge_tts"):
        try:
            __import__(mod)
        except ImportError:
            lacks.append(mod.replace("_", "-"))
    return lacks


# ------------------------- modelo do Vosk -------------------------

def _is_model(folder):
    return (folder / "am").is_dir() and (folder / "conf").is_dir()


def find_model(base=None):
    """A pasta do modelo, mesmo que o zip tenha sido descompactado com uma pasta a mais dentro."""
    base = Path(base or VOSK_MODEL)
    if _is_model(base):
        return base
    if base.is_dir():
        for conf in sorted(base.glob("*/conf")) + sorted(base.glob("*/*/conf")):
            if _is_model(conf.parent):
                return conf.parent
    return None


def download_model(base=None):
    """Baixa e descompacta o modelo pequeno de português (uns 30 MB)."""
    base = Path(base or VOSK_MODEL)
    base.mkdir(parents=True, exist_ok=True)
    zpath = base / "modelo.zip"
    print(f"Baixando o modelo de voz para {base} (uns 30 MB, só na primeira vez)...")
    urllib.request.urlretrieve(MODEL_URL, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(base)
    zpath.unlink()
    return find_model(base)


# ------------------------- microfone -------------------------

def mic_name():
    try:
        import sounddevice as sd
        return sd.query_devices(kind="input")["name"]
    except Exception:
        return ""


def open_mic_settings():
    try:
        os.startfile("ms-settings:privacy-microphone")
    except Exception:
        pass


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


def record_command(read_block, noise=300.0, before=()):
    """Grava do microfone até você parar de falar. read_block() devolve 0,1 s de áudio.
    before = o áudio de logo antes do "Jarvis" (se você já falou o pedido junto, ele vem junto)."""
    threshold = max(350.0, noise * 2.5)
    before = [bytes(b) for b in before]
    spoke_before = sum(rms(b) >= threshold for b in before) >= 3
    chunks, spoke, quiet, elapsed = list(before), False, 0.0, 0.0
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
        if not spoke and elapsed >= (1.5 if spoke_before else NO_SPEECH):
            return b"".join(chunks) if spoke_before else b""
    return b"".join(chunks)


def strip_wake(text):
    """Tira o "Jarvis" do começo do que foi transcrito."""
    words = (text or "").strip().split()
    if words and is_wake(words[0]):
        words = words[1:]
    elif len(words) > 1 and is_wake(words[0] + words[1]):  # "Já vis, toca lofi"
        words = words[2:]
    return " ".join(words).strip(" ,.!?;:-")


def _sounds_like_jarvis(word):
    return word in WAKE_WORDS or (len(word) >= 4 and max(
        difflib.SequenceMatcher(None, word, w).ratio() for w in ("jarvis", "jarbas")) >= 0.8)


def is_wake(text):
    """True se a frase tem "Jarvis" (ou o jeito que o reconhecedor escreve), junto ou separado."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c))
    words = re.findall(r"\w+", plain)
    pairs = [a + b for a, b in zip(words, words[1:])]  # "já vis" -> "javis"
    return any(_sounds_like_jarvis(w) for w in words + pairs)


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
    # Thread própria: o asyncio do edge-tts não se mistura com o loop do navegador (Playwright).
    errors = []

    def synth():
        try:
            asyncio.run(edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH).save(str(path)))
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=synth)
    t.start()
    t.join()
    if errors:
        raise errors[0]
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

    def __init__(self, put, on_state=None, model_path=None):
        super().__init__(daemon=True)
        self.put = put
        self.on_state = on_state or (lambda s: None)
        self.model_path = model_path or find_model()
        self.answer_wanted = threading.Event()  # confirmação: ouve sem precisar dizer "Jarvis"
        self.ready = threading.Event()
        self.error = None

    def ask_answer(self):
        self.answer_wanted.set()

    def _listen_command(self, read_block, noise, before=()):
        self.on_state("ouvindo")
        pcm = record_command(read_block, noise, before)
        if not pcm:
            self.on_state("parado")
            return ""
        self.on_state("pensando")
        try:
            return strip_wake(N.transcribe(wav_bytes(pcm)))
        except Exception as e:
            print(f"\nJarvis > {e}")
            self.on_state("parado")
            return ""

    def run(self):
        try:
            self._run()
        except Exception as e:
            self.error = e
            self.ready.set()
            print(f"\nJarvis > A voz parou: {e}")

    def _run(self):
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)
        # Sem gramática: o modelo escreve o que ouviu e is_wake() reconhece "Jarvis" de vários jeitos.
        rec = KaldiRecognizer(Model(str(self.model_path)), SAMPLE_RATE)
        noise, silent_blocks, warned = 300.0, 0, False
        recent = collections.deque(maxlen=PRE_BUFFER)
        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK, channels=1, dtype="int16") as stream:
            self.ready.set()

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
                    recent.clear()
                    continue
                recent.append(bytes(block))
                level = rms(block)
                # O Windows entrega silêncio absoluto quando bloqueia o microfone para programas.
                silent_blocks = silent_blocks + 1 if level == 0 else 0
                if silent_blocks == 50 and not warned:
                    warned = True
                    print("\nJarvis > O microfone está mudo. Ligue \"Permitir que aplicativos da área de trabalho"
                          " acessem o microfone\" na tela que abri e reinicie o Jarvis.")
                    open_mic_settings()
                noise = noise * 0.98 + level * 0.02  # aprende o barulho do ambiente
                done = rec.AcceptWaveform(bytes(block))
                heard = json.loads(rec.Result() if done else rec.PartialResult())
                if is_wake(heard.get("text") or heard.get("partial")):
                    rec.Reset()
                    beep()
                    text = self._listen_command(read_block, noise, list(recent))
                    recent.clear()
                    if not text:  # só disse "Jarvis": espera o pedido depois do bipe
                        text = self._listen_command(read_block, noise)
                    if text:
                        self.put(("voz", text))
                    else:
                        self.on_state("parado")
