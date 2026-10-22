# -*- coding: utf-8 -*-
"""Voz do Jarvis.

- Ouvir o nome dele ("Bolha"; troque com  setx JARVIS_NOME Jarvis): Vosk, no próprio PC (grátis, leve).
  O modelo pequeno de português é baixado sozinho na primeira vez para G:\\Jarvis\\modelos\\vosk-pt (uns 30 MB).
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
import queue
import re
import shutil
import tempfile
import threading
import unicodedata
import time
import urllib.parse
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
JARVIS_VOSK = ["jarvis", "jarbas", "javis", "jarves", "jervis", "jarvi", "jarve", "garvis", "jarvas", "jabis"]
# O Whisper escreve "Jarvis" certinho; estes são os jeitos que ele ainda erra.
JARVIS_WHISPER = {"jarvis", "jarbas", "jarbis", "javis", "jarves", "jervis", "jarvi", "jarvas", "garvis"}
MAX_COMMAND = 12.0  # segundos
END_SILENCE = 1.5  # segundos de silêncio que encerram o pedido (uma pausa para pensar não corta a frase)
END_SILENCE_LONG = 1.0  # depois de uma frase comprida, o fim chega mais rápido
NO_SPEECH = 5.0  # desiste se você não falar nada
FOLLOW_UP_WAIT = 6.0  # ele te fez uma pergunta: escuta a resposta sem precisar dizer o nome
GO_ON_WAIT = 4.0  # frase parou no meio ("abre o..."): espera até isso você continuar, sem bipe
# No fim da fala, estas palavras mostram que a frase ficou pela metade ("pesquisa sobre tipo", "abre o").
UNFINISHED = {"tipo", "e", "que", "pra", "para", "de", "do", "da", "dos", "das", "no", "na", "nos", "nas", "o", "a",
              "os", "as", "um", "uma", "com", "sobre", "em", "mas", "porque", "se", "meu", "minha", "eh", "hum",
              "hmm", "humm", "ahn", "tipoassim"}
# Antes do nome, estas palavras mostram que é o substantivo, não um chamado ("a bolha", "sair da bolha").
NOT_CALL = {"a", "as", "da", "das", "na", "nas", "numa", "numas", "uma", "umas", "de", "em", "essa", "dessa",
            "nessa", "esta", "desta", "nesta", "sua", "minha", "nossa", "pela", "plastico", "outra", "cada"}
PRE_BUFFER = 25  # 2,5 s antes do "Jarvis": pega o "Jarvis, toca lofi" dito de uma vez só
ECHO_BLOCKS = 2  # 0,2 s depois do bipe: o eco do bipe na caixa de som não conta como fala
DUCK_LEVEL = 0.15  # volume do PC enquanto você fala (música alta atrapalha ouvir o pedido)
# Mostra no console o que o Vosk ouviu:  $env:JARVIS_VOZ_DEBUG=1; python windows\jarvis_ai.py
DEBUG = os.environ.get("JARVIS_VOZ_DEBUG", "").strip() == "1"

speaking = threading.Event()  # enquanto ele fala, não se escuta (para não ativar sozinho)
CACHE = Path(os.environ.get("JARVIS_CACHE_VOZ", r"G:\Jarvis\cache\voz"))  # frases já faladas: tocam na hora (16)
SETTINGS = Path(r"G:\Jarvis\config\voz.json")  # calibração do microfone e barulho de cada hora
MIN_LEVEL = 350.0  # o mínimo para contar como fala; a calibração ("calibra o microfone") ajusta
CONVERSATION_WAIT = 8.0  # depois de responder, escuta mais 8 s sem precisar dizer o nome (6)
_stop_talk = threading.Event()  # "Bolha, para": corta a fala na hora (5)
_say_lock = threading.Lock()  # uma fala de cada vez (a frase pronta e a resposta não se atropelam)
VOCAB = []  # vocabulário pessoal (contatos, jogos, apelidos): ajuda o Whisper e corrige a transcrição (7, 8)
heard_seconds = 0.0  # quanto levou para ouvir (gravar + transcrever) o último pedido falado: vai para o cronômetro


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
    """Modelo novo (am/final.mdl) ou antigo, como o small-pt-0.3 (final.mdl solto na pasta)."""
    return (folder / "am" / "final.mdl").is_file() or (folder / "final.mdl").is_file()


def find_model(base=None):
    """A pasta do modelo, mesmo que o zip tenha sido descompactado com uma pasta a mais dentro."""
    base = Path(base or VOSK_MODEL)
    if _is_model(base):
        return base
    if base.is_dir():
        for mdl in sorted(base.glob("*/final.mdl")) + sorted(base.glob("*/*/final.mdl")):
            folder = mdl.parent.parent if mdl.parent.name == "am" else mdl.parent
            if _is_model(folder):
                return folder
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


last_levels = (0.0, 0.0)  # (maior nível ouvido, nível que precisava) da última gravação, para o aviso


def record_command(read_block, noise=300.0, before=(), recalibrate=False, no_speech=NO_SPEECH):
    """Grava do microfone até você parar de falar. read_block() devolve 0,1 s de áudio.
    before = o áudio de logo antes do "Jarvis" (se você já falou o pedido junto, ele vem junto).
    recalibrate = o som do PC acabou de ser abaixado: mede o barulho de novo nos primeiros blocos.
    no_speech = quanto esperar você começar a falar."""
    global last_levels
    threshold = max(MIN_LEVEL, noise * 2.5)
    before = [bytes(b) for b in before]
    spoke_before = sum(rms(b) >= threshold for b in before) >= 3
    chunks, spoke, quiet, elapsed, loudest, talked = list(before), False, 0.0, 0.0, 0.0, 0.0
    step = BLOCK / SAMPLE_RATE
    first = []
    while elapsed < MAX_COMMAND:
        block = read_block()
        chunks.append(bytes(block))
        elapsed += step
        level = rms(block)
        if level_hook is not None:  # o reator mexe no ritmo de quem está falando o pedido
            _tell_level(mic_levels(block, threshold), BLOCK / SAMPLE_RATE * 1000 / 4, sharpness(voice_shape(block)[1]))
        if len(first) <= ECHO_BLOCKS:
            first.append(level)
            if recalibrate and len(first) == ECHO_BLOCKS + 1:  # o menor bloco nunca fica abaixo do barulho real
                threshold = max(MIN_LEVEL, min(noise, min(first)) * 2.5)
        if len(first) > ECHO_BLOCKS and level >= threshold and is_speech(block):
            spoke, quiet = True, 0.0
            talked += step
        else:
            quiet += step
        if len(first) > ECHO_BLOCKS:
            loudest = max(loudest, level)
        last_levels = (loudest, threshold)
        # quem já falou uma frase inteira (mais de 2,5 s) terminou com 1 s de silêncio; no começo, 1,5 s (4)
        if spoke and quiet >= (END_SILENCE_LONG if talked >= 2.5 else END_SILENCE):
            break
        if not spoke and elapsed >= (2.0 if spoke_before else no_speech):
            return b"".join(chunks) if spoke_before else b""
    return b"".join(chunks)


_vad = None


def is_speech(block):
    """Detector de voz leve (4): com o webrtcvad instalado (opcional), barulho constante (ventilador, chuva) não
    conta como fala. Sem ele, só o volume decide."""
    global _vad
    if _vad is None:
        try:
            import webrtcvad
            _vad = webrtcvad.Vad(2)
        except Exception:
            _vad = False
    if not _vad:
        return True
    frame = int(SAMPLE_RATE * 0.02) * 2  # 20 ms em bytes
    data = bytes(block)
    frames = [data[i:i + frame] for i in range(0, len(data) - frame + 1, frame)]
    if not frames:
        return True
    try:
        voiced = sum(_vad.is_speech(f, SAMPLE_RATE) for f in frames)
    except Exception:
        return True
    return voiced * 2 >= len(frames)


def strip_wake(text):
    """Tira o nome ("Bolha, ...") do começo do que foi transcrito."""
    words = (text or "").strip().split()
    if words and is_wake(words[0]):
        words = words[1:]
    elif len(words) > 1 and is_wake(words[0] + words[1]):  # "Já vis, toca lofi"
        words = words[2:]
    return " ".join(words).strip(" ,.!?;:-")


def _plain(word):
    return re.sub(r"[^a-z]", "", "".join(
        c for c in unicodedata.normalize("NFKD", word.lower()) if not unicodedata.combining(c)))


NAME, WAKE_WORDS, WHISPER_WAKE, FUZZY_WAKE = "", set(), set(), False


def set_name(name):
    """O nome que acorda o assistente. "Jarvis" (inglês) vem escrito de vários jeitos, então é
    comparado por semelhança; um nome em português ("Bolha") o Vosk e o Whisper escrevem certo, e
    só vale igualzinho (senão "olha" e "bola", que aparecem toda hora, acordariam ele)."""
    global NAME, WAKE_WORDS, WHISPER_WAKE, FUZZY_WAKE
    NAME = str(name or "").strip()
    key = _plain(NAME)
    if not key:  # vazio ou sem letras: volta ao padrão
        NAME, key = "Bolha", "bolha"
    FUZZY_WAKE = key == "jarvis"
    if FUZZY_WAKE:
        WAKE_WORDS, WHISPER_WAKE = set(JARVIS_VOSK), set(JARVIS_WHISPER)
    else:
        WAKE_WORDS = WHISPER_WAKE = {key, key + "s"}  # "Bolha" e "Bolhas"
    N.STT_PROMPT = NAME  # o Whisper escreve o nome do jeito certo


set_name(os.environ.get("JARVIS_NOME", "Bolha"))


def _sounds_like_name(word):
    return word in WAKE_WORDS or (FUZZY_WAKE and len(word) >= 4 and max(
        difflib.SequenceMatcher(None, word, w).ratio() for w in ("jarvis", "jarbas")) >= 0.8)


def _called(words, i):
    """O nome na posição i é um chamado ("Bolha, toca lofi", "ei bolha") e não o substantivo
    ("a bolha imobiliária", "plástico bolha"), que a TV e os vídeos falam toda hora."""
    return FUZZY_WAKE or i == 0 or words[i - 1] not in NOT_CALL


def is_wake(text):
    """True se a frase tem o nome (ou o jeito que o reconhecedor escreve), junto ou separado."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c))
    words = re.findall(r"\w+", plain)
    pairs = [a + b for a, b in zip(words, words[1:])]  # "já vis" -> "javis"
    return (any(_sounds_like_name(w) and _called(words, i) for i, w in enumerate(words))
            or any(_sounds_like_name(p) for p in pairs))


def _near_name(word):
    key = _plain(NAME)
    return len(word) >= 4 and difflib.SequenceMatcher(None, word, key).ratio() >= 0.8


def after_wake(text, lenient_first=False):
    """O pedido que vem depois do nome na transcrição. None se o Whisper não ouviu o nome:
    aí foi conversa de fundo, a TV ou o próprio vídeo ("eu já vi esse..."), e não é para obedecer.
    lenient_first: o Vosk já ouviu o nome certinho, então a primeira palavra quase igual
    ("Bola, toca lofi", "Olha, toca lofi") também vale; no meio da frase, só o nome exato."""
    words = (text or "").split()
    plain = [_plain(w) for w in words]
    for i, p in enumerate(plain):
        if (p in WHISPER_WAKE and _called(plain, i)) or (FUZZY_WAKE and len(p) >= 5
                                                         and difflib.SequenceMatcher(None, p, "jarvis").ratio() >= 0.8):
            return " ".join(words[i + 1:]).strip(" ,.!?;:-")
        if i + 1 < len(plain) and p + plain[i + 1] in WHISPER_WAKE:  # "Já vis, toca lofi"
            return " ".join(words[i + 2:]).strip(" ,.!?;:-")
    if lenient_first and plain and _near_name(plain[0]) and (len(plain) == 1 or _looks_like_request(plain[1:])):
        # "Bola, toca lofi" vale (o Vosk ouviu o nome certo); "olha só que legal" não: depois não vem um pedido (9)
        return " ".join(words[1:]).strip(" ,.!?;:-")
    return None


REQUEST_START = set("""abre abra fecha feche toca toque coloca coloque poe bota aumenta abaixa baixa diminui muta desmuta
liga desliga manda mande envia pesquisa pesquise procura procure busca mostra minimiza maximiza bloqueia tira faz faca
cria escreve digita le leia resume deixa volta muda troca apaga limpa organiza instala atualiza lembra me qual quais
quanto quantos quem como onde que o a pausa pula para pare continua vai entra salva grava modo clica aperta""".split())


def _looks_like_request(words):
    return bool(words) and words[0] in REQUEST_START


def unfinished(text):
    """A fala parou no meio ("Bolha, pesquisa sobre tipo...", "abre o"): você ainda está pensando."""
    text = (text or "").strip()
    if not text or text.endswith("?"):
        return False
    if text.endswith(("...", "…")):
        return True
    words = [w for w in (_plain(w) for w in text.split()) if w]
    return bool(words) and (words[-1] in UNFINISHED or "".join(words[-2:]) in UNFINISHED)


# ------------------------- falar -------------------------

def clean_for_speech(text):
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_`#>|]", "", text)
    text = re.sub(r"[^\w\s.,;:!?%°ºª()'\"/-]", "", text)  # tira emojis e símbolos
    return re.sub(r"\s+", " ", text).strip()


def can_speak():
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return bool(eleven_key()) or _has_gtts() or has_piper()  # sem o edge-tts, ainda dá pelas reservas


def _mci(command):
    import ctypes
    winmm = ctypes.windll.winmm
    code = winmm.mciSendStringW(command, None, 0, None)
    if code:
        buf = ctypes.create_unicode_buffer(256)
        winmm.mciGetErrorStringW(code, buf, 256)
        raise RuntimeError(f"o Windows não tocou o áudio ({buf.value or code})")


def _is_wav(path):
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"RIFF"
    except OSError:
        return False


def _play_mp3(path):
    """Toca o MP3 (ou o WAV do Piper) pelo próprio Windows (MCI), sem instalar player."""
    alias = "jarvisvoz"
    try:
        _mci(f"close {alias}")  # se uma fala anterior ficou aberta
    except RuntimeError:
        pass
    wav = None
    if _is_wav(path):  # o Piper faz WAV: o Windows toca pelo waveaudio, com a extensão certa
        wav = Path(str(path) + ".wav")
        shutil.copyfile(path, wav)
        _mci(f'open "{wav}" type waveaudio alias {alias}')
    else:
        _mci(f'open "{path}" type mpegvideo alias {alias}')
    try:
        _mci(f"play {alias} wait")
    finally:
        try:
            _mci(f"close {alias}")
        except RuntimeError:
            pass
        if wav:
            try:
                wav.unlink()
            except OSError:
                pass


# ------------------------- o reator no ritmo da voz -------------------------
# A tela (ui.level) recebe o volume da voz para o reator mexer junto: o do microfone enquanto ele ouve o
# pedido e o da voz dele enquanto fala. O jarvis_ai liga isto quando o reator está aberto.
level_hook = None  # fn(valores 0 a 1, passo em ms entre eles, agudo 0 a 1)
PLAY_RATE = 24000  # a voz do Bing já vem em 24 kHz
PLAY_STEP = 0.04  # um volume a cada 40 ms (25 por segundo)


def _tell_level(values, step_ms=0, sharp=0.0):
    if level_hook is None:
        return
    try:
        level_hook(values, step_ms, sharp)
    except Exception:
        pass  # a tela nunca atrapalha a voz


def voice_shape(block):
    """(volume, cruzamentos) de um pedaço de áudio int16. Cruzamentos = quantas vezes a onda passa pelo zero,
    por amostra: "s", "x" e "f" cruzam muito (agudo), vogais cruzam pouco. Só somas, sem FFT: leve no i3."""
    samples = array.array("h", bytes(block))
    if not samples:
        return 0.0, 0.0
    total, cross, prev = 0, 0, samples[0] >= 0
    for s in samples:
        total += s * s
        pos = s >= 0
        if pos != prev:
            cross += 1
        prev = pos
    return math.sqrt(total / len(samples)), cross / len(samples)


def sharpness(cross):
    """Cruzamentos por amostra -> 0 (grave, vogal) a 1 (agudo, chiado)."""
    return round(min(1.0, max(0.0, (cross - 0.04) / 0.3)), 3)


def mic_levels(block, threshold, parts=4):
    """Os volumes de um bloco do microfone (0,1 s) em `parts` pedaços, de 0 a 1: abaixo da metade do limiar é
    silêncio; a voz normal chega perto de 1. Pedaços menores deixam o reator seguir as sílabas."""
    data = bytes(block)
    size = max(2, len(data) // parts // 2 * 2)
    out = []
    for i in range(0, len(data) - size + 1, size):
        level, _ = voice_shape(data[i:i + size])
        floor = threshold * 0.5
        out.append(round(min(1.0, max(0.0, (level - floor) / (threshold * 5))) ** 0.7, 3))
    return out


def _play(path):
    """Toca a fala. Com o reator aberto, toca pelo próprio Bolha e mede o volume a cada 40 ms (o reator mexe
    no ritmo da voz); sem o miniaudio, ou se a saída de som falhar, toca pelo Windows como antes."""
    if level_hook is not None:
        try:
            if _play_measured(path):
                return
        except Exception:
            pass
    _play_mp3(path)


def _play_measured(path):
    """True se tocou (inteira ou cortada pelo "Bolha, para"); False se nem começou (aí toca pelo Windows)."""
    try:
        import miniaudio
        import sounddevice as sd
        sound = miniaudio.decode_file(str(path), output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
                                      sample_rate=PLAY_RATE)
    except Exception:
        return False
    samples = sound.samples
    step = int(PLAY_RATE * PLAY_STEP)
    shapes = [voice_shape(samples[i:i + step]) for i in range(0, len(samples), step)]
    if not shapes:
        return False
    loudest = max([level for level, _ in shapes] + [1500.0])  # cada frase usa a escala toda, sem exagerar o silêncio
    try:
        stream = sd.RawOutputStream(samplerate=PLAY_RATE, channels=1, dtype="int16")
        stream.start()
    except Exception:
        return False
    sent = [-1]

    def tell_now(t0, latency):
        """Manda o volume do pedaço que está saindo na caixa de som agora (o buffer vai um pouco na frente)."""
        now = int((time.perf_counter() - t0 - latency) / PLAY_STEP)
        if 0 <= now < len(shapes) and now != sent[0]:
            sent[0] = now
            level, cross = shapes[now]
            _tell_level(round((level / loudest) ** 0.8, 3), 0, sharpness(cross))
        return now

    try:
        latency = float(stream.latency or 0.0)
        t0 = time.perf_counter()
        stopped = False
        for start in range(0, len(samples), step):
            if _stop_talk.is_set():
                stopped = True
                stream.abort()
                break
            stream.write(samples[start:start + step].tobytes())
            tell_now(t0, latency)
        if not stopped:
            while tell_now(t0, latency) < len(shapes) and not _stop_talk.is_set():
                time.sleep(PLAY_STEP / 2)  # o fim da frase ainda está no buffer
            if _stop_talk.is_set():
                stream.abort()
            else:
                stream.stop()  # espera tocar o que sobrou
    finally:
        try:
            stream.close()
        except Exception:
            pass
        _tell_level(0.0)
    return True


EDGE_RETRY = 600  # a voz do Bing (Edge) recusou: fala pela ElevenLabs e só tenta o Bing de novo depois disso (s)
_edge_off_until = 0.0
_told = {}  # último erro avisado de cada voz de reserva
ELEVEN_API = "https://api.elevenlabs.io/v1/text-to-speech/"
ELEVEN_VOICE = "Elvis"  # nome (procurado em "Minhas vozes" da conta) ou id; troca com setx ELEVENLABS_VOICE
ELEVEN_BACKUP_VOICE = "JBFqnCBsd6RMkjVDRZzb"  # George, voz pronta de toda conta: se não achar a Elvis
_eleven_voice_ids = {}  # nome -> id já encontrado
ELEVEN_MODEL = "eleven_flash_v2_5"  # o mais barato e rápido, fala português (troca com ELEVENLABS_MODEL)


def eleven_key():
    """A chave (sk_ + 48 letras/números). Se veio com sobra colada junto (aspas, espaço, texto), pega só a chave."""
    raw = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    m = re.search(r"sk_[A-Za-z0-9]{48}(?![A-Za-z0-9])", raw)
    return m.group(0) if m else raw.strip("\"' ")


def _short_error(e):
    text = str(e)
    if isinstance(e, ElevenError):
        return text[:220]
    if "403" in text:
        return "recusou (erro 403)"
    return re.sub(r"https?://\S+", "", text)[:120].strip()


def _edge_mp3(text, path):
    import edge_tts
    errors = []

    def synth():  # thread própria: o asyncio do edge-tts não se mistura com o loop do navegador (Playwright)
        try:
            asyncio.run(edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH).save(str(path)))
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=synth)
    t.start()
    t.join()
    if errors:
        raise errors[0]


def _eleven_get(url):
    req = urllib.request.Request(url, headers={"xi-api-key": eleven_key(), "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def eleven_voice():
    """O id da voz: ELEVENLABS_VOICE (nome como "Elvis" ou o id), procurada nas vozes da conta."""
    wanted = (os.environ.get("ELEVENLABS_VOICE", "") or os.environ.get("ELEVENLABS_VOICE_ID", "")).strip() \
        or ELEVEN_VOICE
    if wanted.lower() in _eleven_voice_ids:  # já achada (ou trocada pela George porque foi recusada)
        return _eleven_voice_ids[wanted.lower()]
    if re.fullmatch(r"[A-Za-z0-9]{20}", wanted):
        return wanted
    if wanted.lower() not in _eleven_voice_ids:
        found = ""
        try:
            data = _eleven_get("https://api.elevenlabs.io/v2/voices?page_size=100&search="
                               + urllib.parse.quote(wanted))
            voices = data.get("voices", [])
            names = [(str(v.get("name", "")), v.get("voice_id", "")) for v in voices]
            exact = [i for n, i in names if n.strip().lower() == wanted.lower()]
            starts = [i for n, i in names if n.strip().lower().startswith(wanted.lower())]
            found = (exact or starts or [""])[0]
        except Exception:
            pass
        if not found:
            print(f"\nJarvis > (não achei a voz {wanted} nas suas vozes da ElevenLabs; uso a George. "
                  "No site: Voices > Library > procure a voz > Add to my voices)")
        _eleven_voice_ids[wanted.lower()] = found or ELEVEN_BACKUP_VOICE
    return _eleven_voice_ids[wanted.lower()]


class ElevenError(RuntimeError):
    def __init__(self, message, code=0, detail=""):
        super().__init__(message)
        self.code, self.detail = code, detail


def eleven_delivery(text, model):
    """Entrega contida: neutra no dia a dia, mais estável em avisos e confirmações.

    São ajustes de síntese, não instruções escritas que a voz poderia ler em voz alta.
    """
    tone = os.environ.get("BOLHA_TOM", "auto").strip().lower()
    plain = unicodedata.normalize("NFD", text.lower())
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn")
    serious = tone in ("serio", "sério") or (tone == "auto" and re.search(
        r"\b(?:atencao|cuidado|confirma|confirmar|confirmacao|apagar|excluir|desligar|"
        r"reiniciar|falhou|falha|erro|nao consegui|nao deu certo|bateria fraca|mando|envio|posso mandar)\b", plain
    ))
    settings = {"stability": 0.72 if serious else 0.58, "similarity_boost": 0.75}
    # v3 usa presets de estabilidade; v4 não aceita style/speed.
    if model.startswith("eleven_v3"):
        settings["stability"] = 1.0 if serious else 0.5
    if not model.startswith("eleven_v4"):
        settings.update(style=0.0, speed=0.94 if serious else 0.98)
        if not model.startswith("eleven_v3"):
            settings["use_speaker_boost"] = True
    return settings


def _eleven_request(text, path, voice, model):
    import urllib.error
    body = {"text": text, "model_id": model, "voice_settings": eleven_delivery(text, model)}
    if model.endswith("_v2_5"):
        body["language_code"] = "pt"
    req = urllib.request.Request(
        ELEVEN_API + voice + "?output_format=mp3_44100_64", data=json.dumps(body).encode("utf-8"),
        headers={"xi-api-key": eleven_key(), "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            audio = r.read()
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8", "replace")).get("detail", {})
            detail = (detail.get("message") or detail.get("status") or "") if isinstance(detail, dict) else str(detail)
        except Exception:
            detail = ""
        low = detail.lower()
        if "key id used as api key" in low:
            raise ElevenError("você colocou o ID da chave, não a chave. A chave começa com sk_ e só aparece "
                              "quando é criada: crie outra e faça o setx com ela", e.code, detail) from e
        if e.code == 401 and "permission" not in low:
            raise ElevenError(f"a chave foi recusada ({detail or 'confira ELEVENLABS_API_KEY'})", e.code, detail) from e
        # a mensagem original da ElevenLabs vai junto: "quota" pode ser o limite da CHAVE, não da conta
        raise ElevenError(f"HTTP {e.code} {detail[:200]}".strip(), e.code, detail) from e
    if not audio:
        raise ElevenError("não mandou áudio")
    Path(path).write_bytes(audio)


def _voice_refused(e):
    """A voz escolhida não pode ser usada (voz da Library no plano grátis, voz não adicionada, sem permissão)."""
    low = e.detail.lower()
    return e.code in (400, 402, 403, 404) and not ("quota" in low or "credit" in low or "api key" in low)


def _eleven_mp3(text, path):
    """Voz da ElevenLabs (chave só na variável ELEVENLABS_API_KEY; o plano grátis tem créditos limitados).
    Se a voz escolhida (Elvis) for recusada, usa a George, que toda conta tem."""
    model = os.environ.get("ELEVENLABS_MODEL", "").strip() or ELEVEN_MODEL
    voice = eleven_voice()
    try:
        return _eleven_request(text, path, voice, model)
    except ElevenError as e:
        if voice == ELEVEN_BACKUP_VOICE or not _voice_refused(e):
            raise
        print(f"\nJarvis > (a ElevenLabs não deixou usar essa voz: {e}; uso a George)")
        for name in list(_eleven_voice_ids):
            _eleven_voice_ids[name] = ELEVEN_BACKUP_VOICE
        wanted = (os.environ.get("ELEVENLABS_VOICE", "") or os.environ.get("ELEVENLABS_VOICE_ID", "")).strip() \
            or ELEVEN_VOICE
        _eleven_voice_ids[wanted.lower()] = ELEVEN_BACKUP_VOICE
        return _eleven_request(text, path, ELEVEN_BACKUP_VOICE, model)


# Piper: voz feita no próprio PC, leve (roda bem no i3) e sem internet. Fica por último, de reserva,
# ou na frente de todas com "usa sempre a voz piper".
PIPER_DIR = Path(os.environ.get("JARVIS_PIPER", r"G:\Jarvis\modelos\piper"))
RHASSPY = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/"
# apelido -> (nome do arquivo, link do .onnx, link do .json). Razo: a mais natural (MIT, Lucasllfs no Hugging Face)
PIPER_VOICES = {
    "razo": ("pt-BR-razo-medium", "https://huggingface.co/Lucasllfs/Razo-piper-voice/resolve/main/pt-BR-razo-medium.onnx",
             "https://huggingface.co/Lucasllfs/Razo-piper-voice/resolve/main/config.json"),
    **{nick: (f"pt_BR-{nick}-{q}", f"{RHASSPY}{nick}/{q}/pt_BR-{nick}-{q}.onnx",
              f"{RHASSPY}{nick}/{q}/pt_BR-{nick}-{q}.onnx.json")
       for nick, q in (("faber", "medium"), ("cadu", "medium"), ("jeff", "medium"), ("edresson", "low"))},
}
PIPER_PACE = 1.3  # ritmo do Piper: 1 = o do modelo (rápido demais); maior = mais devagar e tranquilo
_piper = {}  # a voz carregada (1 a 2 s na primeira vez; depois fica na memória)


def piper_choice():
    """A voz do Piper: setx JARVIS_PIPER_VOZ faber (razo = padrão, faber, cadu, jeff ou edresson)."""
    wanted = os.environ.get("JARVIS_PIPER_VOZ", "").strip().lower()
    return PIPER_VOICES.get(wanted) or PIPER_VOICES["razo"]


def piper_name():
    return piper_choice()[0]


def piper_model():
    return PIPER_DIR / f"{piper_name()}.onnx"


def piper_installed():
    try:
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def has_piper():
    """Programa instalado (pip install piper-tts) e a voz baixada ("testa a voz piper" baixa)."""
    model = piper_model()
    return model.is_file() and Path(str(model) + ".json").is_file() and piper_installed()


def piper_pace():
    """Quanto mais alto, mais devagar ("fala mais devagar" sobe 0,1; "fala mais rápido" desce)."""
    try:
        value = float(load_settings().get("piper_ritmo") or PIPER_PACE)
    except (TypeError, ValueError):
        value = PIPER_PACE
    return max(0.8, min(2.0, value))


def change_pace(step):
    value = round(max(0.8, min(2.0, piper_pace() + step)), 2)
    save_settings(piper_ritmo=value)
    return value


def download_piper():
    """Baixa a voz do Piper (uns 60 MB, uma vez só) para a pasta PIPER_DIR (no G)."""
    name, onnx_url, json_url = piper_choice()
    PIPER_DIR.mkdir(parents=True, exist_ok=True)
    for final, url in ((PIPER_DIR / f"{name}.onnx.json", json_url), (PIPER_DIR / f"{name}.onnx", onnx_url)):
        if final.is_file() and final.stat().st_size > 0:
            continue
        part = final.with_name(final.name + ".baixando")
        with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        part.replace(final)
    return piper_model()


def _piper_sounds(sentences):
    """As vozes do Piper engolem o "lh" ("Bolha" saía "boa"): o som ʎ vira l + j, o resto fica igual."""
    return [[x for p in sounds for x in (("l", "j") if p == "ʎ" else (p,))] for sounds in sentences]


def _piper_wav(text, path):
    """Fala pelo Piper num WAV (o _play_mp3 reconhece e toca)."""
    name = piper_name()
    voice = _piper.get(name)
    if voice is None:
        import logging
        logging.getLogger("piper").setLevel(logging.ERROR)  # o aviso de fonema que falta não suja a tela
        from piper import PiperVoice
        voice = _piper[name] = PiperVoice.load(str(piper_model()))
        original = voice.phonemize
        voice.phonemize = lambda t: _piper_sounds(original(t))
    with wave.open(str(path), "wb") as w:
        if hasattr(voice, "synthesize_wav"):
            from piper import SynthesisConfig
            voice.synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=piper_pace()))
        else:  # piper-tts antigo (1.2)
            voice.synthesize(text, w, length_scale=piper_pace())


def main_voice():
    """"bing" (o padrão) = Bing na frente e o Piper só de reserva sem internet; "piper" = o Piper fala tudo."""
    wanted = os.environ.get("BOLHA_VOZ", "").strip().lower() or str(load_settings().get("voz_principal") or "bing")
    return "piper" if wanted == "piper" else "bing"


def set_main_voice(name):
    save_settings(voz_principal="piper" if name == "piper" else "bing")
    return True


def _gtts_mp3(text, path):
    """Voz do Google Tradutor (gTTS): grátis e sem chave, a última reserva."""
    from gtts import gTTS
    gTTS(text, lang="pt", tld="com.br").save(str(path))


def _has_gtts():
    try:
        import gtts  # noqa: F401
        return True
    except ImportError:
        return False


def voices_summary():
    """Linha mostrada ao ligar: que vozes ele vai usar, na ordem."""
    order = []
    try:
        import edge_tts  # noqa: F401
        order.append("Bing")
    except ImportError:
        pass
    wanted = (os.environ.get("ELEVENLABS_VOICE", "") or os.environ.get("ELEVENLABS_VOICE_ID", "")).strip() \
        or ELEVEN_VOICE
    if eleven_key():
        order.append(f"ElevenLabs ({wanted})")
    if _has_gtts():
        order.append("Google")
    if has_piper():
        if main_voice() == "piper":
            order.insert(0, "Piper (no PC)")
        else:
            order.append("Piper (sem internet)")
    line = "Vozes: " + (" -> ".join(order) or "nenhuma")
    key = eleven_key()
    if key and not key.startswith("sk_"):
        line += "  (ATENÇÃO: a ELEVENLABS_API_KEY não começa com sk_; deve ser o ID da chave, não a chave)"
    elif key and len(key) != 51:
        line += f"  (ATENÇÃO: a ELEVENLABS_API_KEY tem {len(key)} caracteres, a chave tem 51; copie de novo)"
    if not eleven_key():
        line += "  (ElevenLabs desligada: a ELEVENLABS_API_KEY não chegou neste PowerShell; " \
                "faça o setx e abra outra janela)"
    return line


def _a(name):
    return f"o {name}" if name == "Piper" else f"a {name}"


def _synth(text, path):
    """Bing (Edge, grátis) primeiro; reservas: ElevenLabs (se tiver chave) e Google (gTTS).
    Se o Bing recusar, fica um tempo só nas reservas e depois tenta o Bing de novo."""
    global _edge_off_until
    piper_ok = has_piper()
    if piper_ok and main_voice() == "piper":
        try:
            _piper_wav(text, path)
            return "Piper"
        except Exception as e:
            print(f"\nJarvis > (o Piper falhou: {_short_error(e)}; falo com o Bing)")
    backups = []
    if eleven_key():
        backups.append(("ElevenLabs", _eleven_mp3))
    if _has_gtts():
        backups.append(("Google", _gtts_mp3))
    if piper_ok and main_voice() != "piper":
        backups.append(("Piper", _piper_wav))  # sem internet: a voz feita no PC
    errors = []
    if not backups or time.time() >= _edge_off_until:
        try:
            _edge_mp3(text, path)
            _edge_off_until = 0.0
            return "Bing"
        except Exception as e:
            errors.append(f"voz do Bing {_short_error(e)}")
            if backups and not _edge_off_until:
                print(f"\nJarvis > (a voz do Bing {_short_error(e)}; falo com {_a(backups[0][0])} por enquanto)")
            _edge_off_until = time.time() + EDGE_RETRY
    for i, (name, make) in enumerate(backups):
        try:
            make(text, path)
            return name
        except Exception as e:
            errors.append(f"{name}: {_short_error(e)}")
            if i + 1 < len(backups) and _told.get(name) != str(e):  # avisa uma vez por erro novo
                _told[name] = str(e)
                print(f"\nJarvis > ({_a(name)} falhou: {_short_error(e)}; falo com {_a(backups[i + 1][0])})")
    if not backups:
        errors.append("para ter voz de reserva: python -m pip install gTTS, ou setx ELEVENLABS_API_KEY (veja VOZ no LEIA-ME)")
    raise RuntimeError("; ".join(errors))


def _cache_file(text):
    import hashlib
    key = hashlib.sha1(f"{VOICE}|{RATE}|{PITCH}|{text}".encode("utf-8")).hexdigest()[:20]
    return CACHE / f"{key}.mp3"


def synth_cached(text, path):
    """Frases curtas ficam guardadas: na segunda vez tocam na hora, sem esperar a internet (16)."""
    if main_voice() == "piper" and has_piper():  # o cache guarda a voz do Bing: com o Piper, nada dele toca
        _synth(text, path)
        return
    file = _cache_file(text)
    if file.is_file() and file.stat().st_size > 0:
        import shutil
        shutil.copyfile(file, path)
        return
    if _synth(text, path) == "Piper":
        return  # a do Piper não entra no cache: com a internet de volta, a frase sai de novo na voz do Bing
    if len(text) <= 120:
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copyfile(path, file)
        except OSError:
            pass


def prewarm(phrases):
    """Grava as frases prontas ("Verificando, senhor.") em segundo plano, para a primeira vez já ser na hora."""
    def run():
        for p in phrases:
            text = clean_for_speech(p)
            if text and not _cache_file(text).is_file():
                tmp = Path(tempfile.gettempdir()) / f"jarvis_pre_{int(time.time() * 1000)}.mp3"
                try:
                    synth_cached(text, tmp)
                except Exception:
                    return  # sem voz agora (sem internet?): tenta de novo na próxima vez que abrir
                finally:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
    threading.Thread(target=run, daemon=True).start()


def sentences(text):
    """A fala em frases (15): a primeira toca enquanto as outras ainda estão sendo geradas."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?;])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9\"(])", text) if p.strip()]
    out = []
    for p in parts:  # frase muito curta junta com a próxima (soa mais natural)
        if out and len(out[-1]) < 25:
            out[-1] += " " + p
        else:
            out.append(p)
    return out or [text]


def stop_speaking():
    """Corta a fala na hora ("Bolha, para", botão PARAR)."""
    _stop_talk.set()
    try:
        _mci("stop jarvisvoz")
    except Exception:
        pass
    return True


_main_calls = [0]  # quantas falas "de verdade" já foram pedidas (a frase pronta não toca depois de uma delas)


def say(text, on_state=None, filler=None):
    """filler = o número de falas de verdade quando a frase pronta foi pedida (None numa fala normal)."""
    text = clean_for_speech(text)
    if not text:
        return
    if filler is None:
        _main_calls[0] += 1
    with _say_lock:
        if filler is not None and _main_calls[0] != filler:
            return  # a resposta já chegou: o "Verificando, senhor." não toca mais
        _stop_talk.clear()
        parts = sentences(text)
        ready = queue.Queue()

        def produce():  # gera as próximas frases enquanto a primeira toca
            for i, part in enumerate(parts):
                if _stop_talk.is_set():
                    break
                # Um arquivo por frase: o anterior pode ainda estar preso pelo Windows.
                path = Path(tempfile.gettempdir()) / f"jarvis_fala_{int(time.time() * 1000)}_{i}.mp3"
                try:
                    synth_cached(part, path)
                    ready.put(path)
                except Exception as e:
                    ready.put(e)
                    return
            ready.put(None)

        threading.Thread(target=produce, daemon=True).start()
        speaking.set()
        played = 0
        try:
            while True:
                item = ready.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    if played == 0:
                        raise item
                    break
                try:
                    if not _stop_talk.is_set():
                        if on_state and played == 0:
                            on_state("falando")
                        _play(item)
                        played += 1
                finally:
                    try:
                        item.unlink()
                    except OSError:
                        pass
                if _stop_talk.is_set():
                    break
        finally:
            time.sleep(0.2)  # o eco da caixa de som some antes de voltar a ouvir
            speaking.clear()
            if on_state:
                on_state("parado")


def say_piper(text, on_state=None):
    """Fala esta frase pelo Piper, seja qual for a voz principal ("testa a voz piper")."""
    text = clean_for_speech(text)
    with _say_lock:
        _stop_talk.clear()
        path = Path(tempfile.gettempdir()) / f"jarvis_piper_{int(time.time() * 1000)}.wav"
        speaking.set()
        try:
            _piper_wav(text, path)
            if on_state:
                on_state("falando")
            _play(path)
        finally:
            try:
                path.unlink()
            except OSError:
                pass
            time.sleep(0.2)
            speaking.clear()
            if on_state:
                on_state("parado")


def say_async(text, on_state=None):
    """Fala sem esperar (a frase pronta enquanto a IA pensa)."""
    snap = _main_calls[0]
    threading.Thread(target=lambda: _quiet(say, text, None, snap), daemon=True).start()


def _quiet(fn, *args):
    try:
        fn(*args)
    except Exception:
        pass


# ------------------------- vocabulário pessoal (7, 8) -------------------------

def set_vocabulary(words):
    """Nomes de contatos, jogos, pastas e apelidos: vão no "prompt" do Whisper (ele escreve igual) e corrigem
    a transcrição ("abre o o mori" -> "abre o Omori")."""
    seen, out = set(), []
    for w in words:
        w = re.sub(r"\s+", " ", str(w or "")).strip()
        if 3 <= len(w) <= 40 and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    VOCAB[:] = out[:150]
    prompt = NAME + (". " + ", ".join(VOCAB) if VOCAB else "")
    N.STT_PROMPT = prompt[:600]
    return len(VOCAB)


COMMON_WORDS = set("""abre toca para pare volume musica video arquivo pasta senhor bolha jarvis youtube google sim nao
mais menos tela janela agora hoje amanha ontem""".split())


def fix_words(text, vocab=None):
    """Troca pedaços que soam como uma palavra do vocabulário pela palavra certa ("o mori" -> "Omori").
    Primeiro os iguais (sem espaço e acento), depois os bem parecidos; o que já foi trocado não mexe de novo."""
    vocab = VOCAB if vocab is None else vocab
    if not vocab or not text:
        return text
    keys = {_plain(v): v for v in vocab if len(_plain(v)) >= 4 and _plain(v) not in COMMON_WORDS}
    tokens = [[w, False] for w in str(text).split()]  # [palavra, já é do vocabulário]

    def run(fuzzy):
        i, out = 0, []
        while i < len(tokens):
            for size in (3, 2, 1):
                chunk = tokens[i:i + size]
                if len(chunk) < size or any(t[1] for t in chunk):
                    continue
                joined = "".join(_plain(t[0]) for t in chunk)
                if len(joined) < 4 or (size == 1 and joined in COMMON_WORDS):
                    continue
                best = keys.get(joined)
                if best is None and fuzzy and len(joined) >= 5 and size <= 2:
                    close = difflib.get_close_matches(joined, list(keys), n=1, cutoff=0.88)
                    best = keys[close[0]] if close else None
                if best is not None:
                    tail = re.match(r".*?([,.!?;:]*)$", chunk[-1][0]).group(1)
                    out.append([best + tail, True])
                    i += size
                    break
            else:
                out.append(tokens[i])
                i += 1
        tokens[:] = out

    run(False)
    run(True)
    return " ".join(t[0] for t in tokens)


# ------------------------- calibração do microfone (2) e barulho por hora (3) -------------------------

def load_settings():
    global MIN_LEVEL
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("limiar"), (int, float)):
        MIN_LEVEL = float(max(80.0, min(3000.0, data["limiar"])))
    return data if isinstance(data, dict) else {}


def save_settings(**changes):
    data = {}
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    data.update(changes)
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return data


def calibration_threshold(levels):
    """O limiar a partir de alguns segundos em que o senhor disse "Bolha" 3 vezes: entre o barulho do quarto e a
    sua voz. (limiar, barulho, voz)"""
    levels = sorted(float(x) for x in levels if x is not None)
    if len(levels) < 10:
        return None
    noise = levels[len(levels) // 5]  # o quarto mais calmo
    voice = levels[int(len(levels) * 0.95) - 1]  # os picos da fala
    if voice < noise * 2:  # não deu para ouvir a fala por cima do barulho
        return None
    threshold = max(80.0, min(noise * 2.5, noise + (voice - noise) * 0.3))
    return round(threshold), round(noise), round(voice)


def hour_noise(profile, hour):
    """O barulho que costuma ter nesta hora (aprendido ao longo dos dias), ou None."""
    value = (profile or {}).get(str(hour))
    return float(value) if isinstance(value, (int, float)) else None


def synth_mp3(text):
    """A fala em MP3, sem tocar no PC (vai para o celular), com as mesmas vozes e reservas do say()."""
    text = clean_for_speech(text)
    if not text:
        return b""
    path = Path(tempfile.gettempdir()) / f"jarvis_celular_{int(time.time() * 1000)}.mp3"
    try:
        _synth(text, path)
        return path.read_bytes()
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def beep():
    try:
        import winsound
        winsound.Beep(880, 120)
    except Exception:
        pass


def duck(level=DUCK_LEVEL):
    """Abaixa a música e o jogo enquanto você fala o pedido (10): cada programa que está tocando som, menos o
    próprio Bolha (o bipe continua alto). Devolve a função que volta o volume (ou None se não precisou)."""
    try:
        from pycaw.pycaw import AudioUtilities
        changed = []
        for sess in AudioUtilities.GetAllSessions():
            try:
                if not sess.Process or sess.Process.pid == os.getpid() or sess.State != 1:  # 1 = tocando agora
                    continue
                vol = sess.SimpleAudioVolume
                old = vol.GetMasterVolume()
                if old > level:
                    vol.SetMasterVolume(level, None)
                    changed.append((vol, old))
            except Exception:
                continue
        if changed:
            def restore_sessions():
                for vol, old in changed:
                    try:
                        vol.SetMasterVolume(old, None)
                    except Exception:
                        pass
            return restore_sessions
    except Exception:
        pass
    return _duck_master(level)


def _duck_master(level):
    """Reserva: abaixa o volume geral."""
    try:
        from pycaw.pycaw import AudioUtilities
        vol = AudioUtilities.GetSpeakers().EndpointVolume
        old = vol.GetMasterVolumeLevelScalar()
        if old <= level:
            return None
        vol.SetMasterVolumeLevelScalar(level, None)
    except Exception:
        return None

    def restore():
        try:
            vol.SetMasterVolumeLevelScalar(old, None)
        except Exception:
            pass

    return restore


# ------------------------- ouvir -------------------------
STOP = {"para", "pare", "parar", "chega", "silencio", "cala", "quieto", "stop", "paraa"}


def asks_stop(text):
    """ "Bolha, para" / "Bolha, chega": o nome e logo depois a palavra de parar (a própria fala dele não conta)."""
    words = [_plain(w) for w in str(text or "").split()]
    return any(_sounds_like_name(w) and i + 1 < len(words) and words[i + 1] in STOP for i, w in enumerate(words))

class Listener(threading.Thread):
    """Fica ouvindo o nome dele; depois grava o pedido e manda o texto para put(("voz", texto))."""

    def __init__(self, put, on_state=None, model_path=None):
        super().__init__(daemon=True)
        self.put = put
        self.on_state = on_state or (lambda s: None)
        self.model_path = model_path or find_model()
        self.answer_wanted = threading.Event()  # confirmação: ouve sem precisar dizer "Jarvis"
        self.ready = threading.Event()
        self.follow_wanted = threading.Event()
        self.calibrate_wanted = threading.Event()
        self.follow_quiet = False  # conversa contínua: escuta sem bipe
        self.on_interrupt = None  # "Bolha, para" enquanto ele fala
        self.error = None

    def ask_answer(self):
        self.answer_wanted.set()

    def follow_up(self, quiet=False):
        """Depois de uma pergunta dele: escuta uma vez sem o nome; se ninguém falar, volta a esperar o nome.
        quiet=True: conversa contínua (escuta 8 s sem bipe, depois de qualquer resposta)."""
        self.follow_quiet = quiet
        self.follow_wanted.set()

    def calibrate(self):
        """ "calibra o microfone": o senhor diz "Bolha" 3 vezes e ele acerta o volume mínimo sozinho (2)."""
        self.calibrate_wanted.set()

    def _calibrate(self, read_block):
        global MIN_LEVEL
        self.on_state("ouvindo")
        beep()
        levels = [rms(read_block()) for _ in range(int(8 / (BLOCK / SAMPLE_RATE)))]  # 8 segundos
        found = calibration_threshold(levels)
        self.on_state("parado")
        if not found:
            self.put(("alerta", "Não consegui ouvir sua voz acima do barulho, senhor. Chegue mais perto do "
                                "microfone ou aumente o volume dele no Windows e diga calibra o microfone de novo."))
            return
        threshold, noise, voice = found
        MIN_LEVEL = float(threshold)
        save_settings(limiar=threshold, ruido_calibrado=noise, voz=voice, calibrado=time.strftime("%Y-%m-%d %H:%M"))
        self.put(("alerta", f"Microfone calibrado, senhor: sua voz chega a {voice}, o quarto fica em {noise}; "
                            f"agora conto como fala a partir de {threshold}."))

    def _hear(self, read_block, noise, before=(), no_speech=NO_SPEECH, quiet=False):
        """Grava (com o som do PC baixinho) e transcreve. None = ninguém falou.
        quiet = se ninguém falar, não reclama (era só uma espera para você continuar a frase)."""
        global heard_seconds
        self.on_state("ouvindo")
        started = time.perf_counter()
        restore = duck()
        try:
            # com o som abaixado, o barulho aprendido com a música não vale mais: mede de novo
            pcm = record_command(read_block, noise, before, recalibrate=restore is not None, no_speech=no_speech)
        finally:
            if restore:
                restore()
        if not pcm and quiet:
            return None
        if not pcm:
            loudest, needed = last_levels
            print(f"\nJarvis > Não ouvi o pedido (som mais alto {loudest:.0f}, precisa de {needed:.0f})."
                  " Fale logo depois do bipe, perto do microfone, ou aumente o volume do microfone no Windows.")
            self.on_state("parado")
            return None
        self.on_state("pensando")
        try:
            text = N.transcribe(wav_bytes(pcm))
            heard_seconds = round(time.perf_counter() - started, 2)
            return text
        except Exception as e:
            print(f"\nJarvis > {e}")
            self.on_state("parado")
            return None

    def _finish(self, command, read_block, noise):
        """Frase pela metade ("Bolha, abre o..."): espera você completar antes de fazer qualquer coisa."""
        for _ in range(2):
            if not unfinished(command):
                break
            if DEBUG:
                print(f"[esperando você terminar] {command}")
            more = self._hear(read_block, noise, no_speech=GO_ON_WAIT, quiet=True)
            if not more or not more.strip():
                break
            command = f"{command.rstrip(' .…')} {strip_wake(more)}".strip()
        return command

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
        try:
            import comtypes
            comtypes.CoInitialize()  # o duck() mexe no volume por COM nesta thread
        except Exception:
            pass
        SetLogLevel(-1)
        # Sem gramática: o modelo escreve o que ouviu e is_wake() procura o nome nisso.
        rec = KaldiRecognizer(Model(str(self.model_path)), SAMPLE_RATE)
        noise, silent_blocks, warned = 300.0, 0, False
        recent = collections.deque(maxlen=PRE_BUFFER)
        # O microfone enche uma fila sozinho: enquanto o Whisper transcreve, nada do que você fala se perde.
        audio = queue.Queue(maxsize=600)

        def on_audio(indata, frames, t, status):
            try:
                audio.put_nowait(bytes(indata))
            except queue.Full:
                pass

        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK, channels=1, dtype="int16", callback=on_audio):
            self.ready.set()

            def read_block():
                try:
                    return audio.get(timeout=5)
                except queue.Empty:
                    raise RuntimeError("o microfone parou de mandar som (desconectado?)") from None

            profile = load_settings().get("ruido_por_hora", {}) or {}
            learned = hour_noise(profile, time.localtime().tm_hour)
            if learned:
                noise = learned  # começa com o barulho que costuma ter nesta hora (3)
            last_save = time.time()
            while True:
                if self.calibrate_wanted.is_set():
                    self.calibrate_wanted.clear()
                    self._calibrate(read_block)
                    continue
                if time.time() - last_save > 600:  # a cada 10 min guarda o barulho desta hora
                    last_save = time.time()
                    hour = str(time.localtime().tm_hour)
                    old = hour_noise(profile, hour)
                    profile[hour] = round(noise if old is None else old * 0.7 + noise * 0.3)
                    save_settings(ruido_por_hora=profile)
                if self.answer_wanted.is_set():
                    while speaking.is_set():
                        read_block()
                    beep()
                    text = self._hear(read_block, noise)
                    self.answer_wanted.clear()
                    self.put(("voz", strip_wake(text or "")))
                    continue
                if self.follow_wanted.is_set():
                    while speaking.is_set():
                        read_block()
                    self.follow_wanted.clear()
                    quiet_follow = self.follow_quiet
                    if not quiet_follow:
                        beep()
                    text = self._hear(read_block, noise, no_speech=CONVERSATION_WAIT if quiet_follow else FOLLOW_UP_WAIT,
                                      quiet=True)
                    if quiet_follow and text and (len(text.split()) < 2 or not text.strip(" .!?")):
                        text = ""  # na conversa contínua, uma palavra solta costuma ser barulho
                    if text and text.strip():
                        self.put(("voz", strip_wake(text)))
                    else:
                        self.on_state("parado")
                    continue
                block = read_block()
                if speaking.is_set():
                    recent.clear()
                    # enquanto ele fala, só escuta o "Bolha, para" (5)
                    if rec.AcceptWaveform(bytes(block)):
                        heard_now = json.loads(rec.Result()).get("text", "")
                    else:
                        heard_now = json.loads(rec.PartialResult()).get("partial", "")
                    if heard_now and asks_stop(heard_now):
                        rec.Reset()
                        stop_speaking()
                        if self.on_interrupt:
                            try:
                                self.on_interrupt()
                            except Exception:
                                pass
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
                # aprende o barulho do ambiente: desce rápido, sobe devagar (fala e picos quase não contam)
                noise += (level - noise) * (0.02 if level < noise else 0.005)
                done = rec.AcceptWaveform(bytes(block))
                heard = json.loads(rec.Result() if done else rec.PartialResult())
                said = heard.get("text") or heard.get("partial") or ""
                if DEBUG and done and said:
                    print(f"[vosk ouviu] {said}  (nível {level:.0f}, barulho {noise:.0f})")
                if not is_wake(said):
                    continue
                if DEBUG:
                    print(f"[vosk acordou com] {said}")
                rec.Reset()
                beep()
                text = self._hear(read_block, noise, list(recent))
                recent.clear()
                if text is None:
                    continue
                command = after_wake(text, lenient_first=True)
                if command is None:  # o Whisper não ouviu o nome: era conversa, TV ou vídeo
                    if DEBUG:
                        print(f"[ignorado, sem \"{NAME}\"] {text}")
                    self.on_state("parado")
                    continue
                if not command:  # só disse o nome: o pedido vem logo depois (a fila guardou o áudio)
                    command = strip_wake(self._hear(read_block, noise) or "")
                command = self._finish(command, read_block, noise)
                if command:
                    self.put(("voz", command))
                else:
                    self.on_state("parado")


def record_seconds(seconds):
    """Grava N segundos do microfone e devolve o WAV (para mandar áudio no WhatsApp)."""
    import sounddevice as sd
    seconds = max(1.0, min(120.0, float(seconds)))
    beep()
    data = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    sd.wait()
    beep()
    return wav_bytes(data.tobytes())
