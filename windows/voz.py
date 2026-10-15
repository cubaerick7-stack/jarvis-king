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
    threshold = max(350.0, noise * 2.5)
    before = [bytes(b) for b in before]
    spoke_before = sum(rms(b) >= threshold for b in before) >= 3
    chunks, spoke, quiet, elapsed, loudest = list(before), False, 0.0, 0.0, 0.0
    step = BLOCK / SAMPLE_RATE
    first = []
    while elapsed < MAX_COMMAND:
        block = read_block()
        chunks.append(bytes(block))
        elapsed += step
        level = rms(block)
        if len(first) <= ECHO_BLOCKS:
            first.append(level)
            if recalibrate and len(first) == ECHO_BLOCKS + 1:  # o menor bloco nunca fica abaixo do barulho real
                threshold = max(350.0, min(noise, min(first)) * 2.5)
        if len(first) > ECHO_BLOCKS and level >= threshold:
            spoke, quiet = True, 0.0
        else:
            quiet += step
        if len(first) > ECHO_BLOCKS:
            loudest = max(loudest, level)
        last_levels = (loudest, threshold)
        if spoke and quiet >= END_SILENCE:
            break
        if not spoke and elapsed >= (2.0 if spoke_before else no_speech):
            return b"".join(chunks) if spoke_before else b""
    return b"".join(chunks)


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
    if lenient_first and plain and _near_name(plain[0]):  # só se o nome exato não apareceu
        return " ".join(words[1:]).strip(" ,.!?;:-")
    return None


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
        return bool(eleven_key()) or _has_gtts()  # sem o edge-tts, ainda dá para falar pelas reservas


def _mci(command):
    import ctypes
    winmm = ctypes.windll.winmm
    code = winmm.mciSendStringW(command, None, 0, None)
    if code:
        buf = ctypes.create_unicode_buffer(256)
        winmm.mciGetErrorStringW(code, buf, 256)
        raise RuntimeError(f"o Windows não tocou o áudio ({buf.value or code})")


def _play_mp3(path):
    """Toca o MP3 pelo próprio Windows (MCI), sem instalar player."""
    alias = "jarvisvoz"
    try:
        _mci(f"close {alias}")  # se uma fala anterior ficou aberta
    except RuntimeError:
        pass
    _mci(f'open "{path}" type mpegvideo alias {alias}')
    try:
        _mci(f"play {alias} wait")
    finally:
        try:
            _mci(f"close {alias}")
        except RuntimeError:
            pass


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


def _synth(text, path):
    """Bing (Edge, grátis) primeiro; reservas: ElevenLabs (se tiver chave) e Google (gTTS).
    Se o Bing recusar, fica um tempo só nas reservas e depois tenta o Bing de novo."""
    global _edge_off_until
    backups = []
    if eleven_key():
        backups.append(("ElevenLabs", _eleven_mp3))
    if _has_gtts():
        backups.append(("Google", _gtts_mp3))
    errors = []
    if not backups or time.time() >= _edge_off_until:
        try:
            _edge_mp3(text, path)
            _edge_off_until = 0.0
            return
        except Exception as e:
            errors.append(f"voz do Bing {_short_error(e)}")
            if backups and not _edge_off_until:
                print(f"\nJarvis > (a voz do Bing {_short_error(e)}; falo com a {backups[0][0]} por enquanto)")
            _edge_off_until = time.time() + EDGE_RETRY
    for i, (name, make) in enumerate(backups):
        try:
            make(text, path)
            return
        except Exception as e:
            errors.append(f"{name}: {_short_error(e)}")
            if i + 1 < len(backups) and _told.get(name) != str(e):  # avisa uma vez por erro novo
                _told[name] = str(e)
                print(f"\nJarvis > (a {name} falhou: {_short_error(e)}; falo com a {backups[i + 1][0]})")
    if not backups:
        errors.append("para ter voz de reserva: python -m pip install gTTS, ou setx ELEVENLABS_API_KEY (veja VOZ no LEIA-ME)")
    raise RuntimeError("; ".join(errors))


def say(text, on_state=None):
    text = clean_for_speech(text)
    if not text:
        return
    # Um arquivo por fala: o anterior pode ainda estar preso pelo Windows.
    path = Path(tempfile.gettempdir()) / f"jarvis_fala_{int(time.time() * 1000)}.mp3"
    _synth(text, path)
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
        try:
            path.unlink()
        except OSError:
            pass


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
    """Abaixa o som do PC enquanto você fala o pedido. Devolve a função que volta o volume
    (ou None se não precisou ou não deu para mexer)."""
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
        self.error = None

    def ask_answer(self):
        self.answer_wanted.set()

    def follow_up(self):
        """Depois de uma pergunta dele: escuta uma vez sem o nome; se ninguém falar, volta a esperar o nome."""
        self.follow_wanted.set()

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

            while True:
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
                    beep()
                    text = self._hear(read_block, noise, no_speech=FOLLOW_UP_WAIT, quiet=True)
                    if text and text.strip():
                        self.put(("voz", strip_wake(text)))
                    else:
                        self.on_state("parado")
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
