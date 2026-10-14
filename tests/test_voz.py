import array
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))
import nuvem as N  # noqa: E402
import voz as V  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture
def nome_jarvis():
    """Testes do jeito antigo, com JARVIS_NOME=Jarvis."""
    V.set_name("Jarvis")


def block(level):
    return array.array("h", [level] * V.BLOCK).tobytes()


def test_wake_word_variants(nome_jarvis):
    assert V.is_wake("jarbas")
    assert V.is_wake("ei jarvis toca lofi")
    assert not V.is_wake("jardim")
    assert not V.is_wake("")


def test_record_stops_after_you_stop_talking():
    audio = iter([block(0)] * 3 + [block(3000)] * 10 + [block(0)] * 50)
    pcm = V.record_command(lambda: next(audio))
    seconds = len(pcm) / 2 / V.SAMPLE_RATE
    expected = 0.3 + 1.0 + V.END_SILENCE  # antes + falando + o silêncio que encerra
    assert expected - 0.15 <= seconds <= expected + 0.15


def test_a_pause_to_think_does_not_cut_the_sentence():
    # fala 1 s, pensa 1,2 s e continua: a gravação pega as duas partes
    audio = iter([block(3000)] * 10 + [block(0)] * 12 + [block(3000)] * 10 + [block(0)] * 50)
    pcm = V.record_command(lambda: next(audio))
    assert len(pcm) / 2 / V.SAMPLE_RATE >= 3.2


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
    monkeypatch.setattr(N, "_groq_transcribe", lambda wav, key, *_: (_ for _ in ()).throw(OSError("caiu")))
    monkeypatch.setattr(N, "_gemini_transcribe", lambda wav, key, *_: " toca lofi ")
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
    j.voice_out = True
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


def test_model_found_inside_extra_folder(tmp_path):
    inner = tmp_path / "vosk-pt" / "vosk-model-small-pt-0.3"
    (inner / "am").mkdir(parents=True)
    (inner / "am" / "final.mdl").write_bytes(b"x")
    assert V.find_model(tmp_path / "vosk-pt") == inner
    assert V.find_model(tmp_path / "vazio") is None


def test_wake_word_spelled_in_many_ways(nome_jarvis):
    for heard in ("jarvis", "jarbas toca lofi", "já vis", "javis", "jervis abre o chrome"):
        assert V.is_wake(heard), heard
    for heard in ("jardim", "chaves", "jardins", "o jarro"):
        assert not V.is_wake(heard), heard


def test_command_said_in_one_breath_uses_audio_before_wake():
    before = [block(3000)] * 15  # "Jarvis, toca lofi" já falado
    pcm = V.record_command(lambda: block(0), before=before)
    assert len(pcm) / 2 / V.SAMPLE_RATE >= 1.5  # manda o áudio de antes, sem esperar 5 s


def test_strip_wake_word(nome_jarvis):
    assert V.strip_wake("Jarvis, toca lofi.") == "toca lofi"
    assert V.strip_wake("Já vis toca lofi") == "toca lofi"
    assert V.strip_wake("Jarvis.") == ""
    assert V.strip_wake("toca jarvis") == "toca jarvis"


def test_old_flat_model_layout_is_found(tmp_path):
    flat = tmp_path / "vosk-pt"
    flat.mkdir()
    (flat / "final.mdl").write_bytes(b"x")
    assert V.find_model(flat) == flat
    nested = tmp_path / "outra" / "vosk-model-small-pt-0.3"
    nested.mkdir(parents=True)
    (nested / "final.mdl").write_bytes(b"x")
    assert V.find_model(tmp_path / "outra") == nested


def test_typed_request_is_spoken_too(monkeypatch):
    j = load_jarvis()
    said = []
    j.voice_out = True
    monkeypatch.setattr(j.V, "say", lambda text, on_state: said.append(text))
    monkeypatch.setattr(j, "think", lambda *a, **k: json.dumps({"actions": [], "reply": "Pois não, senhor."}))
    j.respond("me conta uma coisa")
    assert said == ["Pois não, senhor."]
    j.voice_out = False
    j.respond("me conta outra")
    assert said == ["Pois não, senhor."]


def test_after_wake_only_obeys_when_jarvis_was_said(nome_jarvis):
    assert V.after_wake("Jarvis, toca lofi.") == "toca lofi"
    assert V.after_wake("Jarvis.") == ""  # só chamou: espera o pedido
    assert V.after_wake("Já vis, toca lofi") == "toca lofi"
    assert V.after_wake("eu já vi esse filme") is None  # conversa ou TV: não obedece


def test_beep_echo_is_not_taken_as_speech():
    audio = iter([block(5000)] * V.ECHO_BLOCKS + [block(0)] * 100)  # o bipe volta pelo microfone
    assert V.record_command(lambda: next(audio)) == b""


def test_recalibrates_after_music_is_lowered():
    # com a música alta o barulho medido era 2000; depois de abaixar o som, a voz (1200) precisa contar
    audio = iter([block(200)] * (V.ECHO_BLOCKS + 1) + [block(1200)] * 10 + [block(200)] * 50)
    assert V.record_command(lambda: next(audio), noise=2000, recalibrate=True) != b""
    audio = iter([block(200)] * (V.ECHO_BLOCKS + 1) + [block(1200)] * 10 + [block(200)] * 50)
    assert V.record_command(lambda: next(audio), noise=2000) == b""  # sem recalibrar, a voz se perdia


def test_default_name_is_bolha_and_only_exact():
    assert V.NAME == "Bolha" and N.STT_PROMPT == "Bolha"
    for heard in ("bolha", "bolha toca lofi", "ei bolha", "bolhas"):
        assert V.is_wake(heard), heard
    for heard in ("olha só", "bola", "jarvis", "folha", "molha a planta", ""):
        assert not V.is_wake(heard), heard  # palavras do dia a dia não acordam


def test_bolha_after_wake_and_strip():
    assert V.after_wake("Bolha, toca lofi.") == "toca lofi"
    assert V.after_wake("Bolha.") == ""
    assert V.after_wake("Olha, toca lofi") is None  # "olha" não é o nome
    assert V.after_wake("Jarvis, toca lofi") is None  # o nome agora é Bolha
    assert V.strip_wake("Bolha, abre o chrome") == "abre o chrome"


def test_name_can_be_changed_back():
    V.set_name("Jarvis")
    assert V.is_wake("jarbas toca lofi") and V.after_wake("Jarvis, oi") == "oi" and N.STT_PROMPT == "Jarvis"
    V.set_name("   ")  # vazio: volta ao padrão
    assert V.NAME == "Bolha"


def test_reator_is_fullscreen_when_window_is_big():
    html = (ROOT / "windows" / "interface" / "reator.html").read_text(encoding="utf-8")
    assert "@media (min-width: 600px)" in html and "const CHEIA = '(min-width: 600px)'" in html
    assert "window.mostraNome" in html and "aspect-ratio: 4/5" not in html  # a versão círculo saiu


def test_ui_is_fullscreen_unless_panel(monkeypatch):
    import ui as U
    assert U.mode() == "cheia"
    monkeypatch.setenv("JARVIS_TELA", "Painel")
    assert U.mode() == "painel"
    monkeypatch.setenv("JARVIS_TELA", "bolha")  # a bolha saiu: vira tela cheia
    assert U.mode() == "cheia"
    assert U.front() is False and U.behind() is False  # sem janela não quebra


def test_request_brings_jarvis_forward_and_opening_sends_him_behind(monkeypatch):
    j = load_jarvis()
    moves = []
    monkeypatch.setattr(j.U, "front", lambda: moves.append("frente"))
    monkeypatch.setattr(j.U, "behind", lambda: moves.append("atras"))
    monkeypatch.setattr(j.F, "second_monitor", lambda: None)
    monkeypatch.setattr(j, "open_target", lambda *a: print("Jarvis > Abrindo calculadora.") or True)
    j.respond("abre a calculadora")
    assert moves == ["frente", "atras"]  # sem segunda tela, o que ele abriu fica por cima dele


def test_with_second_monitor_the_new_window_goes_there(monkeypatch):
    j = load_jarvis()
    expected, moves = [], []
    monkeypatch.setattr(j.U, "front", lambda: moves.append("frente"))
    monkeypatch.setattr(j.U, "behind", lambda: moves.append("atras"))
    monkeypatch.setattr(j.F, "second_monitor", lambda: (1920, 0, 3840, 1040))
    monkeypatch.setattr(j.F, "expect_window", lambda: expected.append(True))
    monkeypatch.setattr(j, "open_target", lambda *a: True)
    j.respond("abre a calculadora")
    assert expected == [True] and moves == ["frente"]  # ele continua na frente na tela principal


def test_new_window_moves_only_after_jarvis_opened_something(monkeypatch):
    import ferramentas as F
    moved = []
    monkeypatch.setattr(F, "_expect_until", 0.0)
    monkeypatch.setattr(F, "is_jarvis_window", lambda h: False)
    monkeypatch.setattr(F, "_on_primary", lambda h: True)
    monkeypatch.setattr(F, "move_to_second", lambda h: moved.append(h) or True)
    monkeypatch.setattr(F, "foreground_window", lambda: 10)
    assert F._maybe_move(20) is False  # você abriu sozinho: fica onde está
    F.expect_window()
    assert F._maybe_move(10) is False  # a janela que já estava na frente não conta
    assert F._maybe_move(20) is True and moved == [20]
    assert F._maybe_move(30) is False  # só a primeira janela nova


def test_weather_and_pc_become_popups(monkeypatch):
    j = load_jarvis()
    cards = []
    monkeypatch.setattr(j.U, "card", lambda t, x, ms=7000: cards.append((t, x)))
    monkeypatch.setattr(j.F, "weather", lambda city="": print(
        "Jarvis > Recife: Sol, +28°C (sensação +31°C), umidade 70%, vento 15km/h") or True)
    monkeypatch.setattr(j, "think", lambda *a, **k: json.dumps(
        {"actions": [{"name": "weather", "args": {}}], "reply": "Está 28 graus, senhor."}))
    j.respond("me fala como vai estar lá fora")
    assert cards and cards[0][0] == "Clima" and cards[0][1].startswith("Recife: Sol, +28°C")
    assert "Está 28 graus" not in cards[0][1]


def test_sent_whatsapp_becomes_a_popup(monkeypatch):
    j = load_jarvis()
    cards = []
    monkeypatch.setattr(j.U, "card", lambda t, x, ms=7000: cards.append((t, x)))
    assert j._sent("Enviado para Ana: chego às 8") == "Enviado para Ana: chego às 8"
    assert j._sent(False) is False
    assert cards == [("WhatsApp", "Enviado para Ana: chego às 8")]


def test_fullscreen_page_has_windows_and_hooks():
    html = (ROOT / "windows" / "interface" / "reator.html").read_text(encoding="utf-8")
    assert "@media (min-width: 600px)" in html and "const CHEIA = '(min-width: 600px)'" in html
    for hook in ("window.mostraVoce", "border-radius: var(--raio)", "const CLIMA", "const MANDO"):
        assert hook in html
    assert "innerHTML" not in html  # texto de arquivo/IA nunca vira HTML


def test_whisper_near_miss_counts_only_as_first_word_after_vosk_heard_the_name():
    assert V.after_wake("Bola, toca lofi", lenient_first=True) == "toca lofi"
    assert V.after_wake("Olha, toca lofi", lenient_first=True) == "toca lofi"
    assert V.after_wake("eu olha toca lofi", lenient_first=True) is None  # no meio da frase, só o nome exato
    assert V.after_wake("Bola, toca lofi") is None


@pytest.mark.parametrize("text", ["a bolha imobiliária vai estourar", "tem que sair da bolha", "plástico bolha é ótimo",
                                  "a gente vive numa bolha.", "essa bolha da inteligência artificial"])
def test_the_noun_on_tv_does_not_wake_it(text):
    assert not V.is_wake(text.lower())
    assert V.after_wake(text, lenient_first=True) is None


@pytest.mark.parametrize("text, command", [("Bolha, toca lofi", "toca lofi"), ("Ei Bolha, toca lofi", "toca lofi"),
                                           ("Tá. Bolha, abre o Chrome", "abre o Chrome"), ("Oi bolha", "")])
def test_calling_the_name_still_works(text, command):
    assert V.is_wake(text.lower())
    assert V.after_wake(text, lenient_first=True) == command


def test_exact_name_wins_over_a_similar_first_word():
    assert V.after_wake("Olha que coisa. Bolha, toca lofi.", lenient_first=True) == "toca lofi"
    assert V.after_wake("Olha. Bolha.", lenient_first=True) == ""
    assert V.after_wake("Olha, toca lofi", lenient_first=True) == "toca lofi"  # sem o nome exato, a 1ª parecida vale


@pytest.mark.parametrize("text, cut", [
    ("pesquisa sobre tipo", True), ("abre o", True), ("Eu queria que você...", True), ("toca uma música e", True),
    ("é hum", True), ("toca lofi", False), ("abre o Chrome.", False), ("por que?", False), ("toca lofi mano", False),
    ("", False),
])
def test_unfinished_sentence(text, cut):
    assert V.unfinished(text) is cut


def test_waits_for_you_to_finish_before_acting(monkeypatch):
    lis = V.Listener(put=lambda x: None, model_path="x")
    heard = iter(["Chrome e", "o Spotify"])
    waits = []

    def fake_hear(read_block, noise, before=(), no_speech=V.NO_SPEECH, quiet=False):
        waits.append((no_speech, quiet))
        return next(heard, None)

    monkeypatch.setattr(lis, "_hear", fake_hear)
    assert lis._finish("abre o...", None, 300.0) == "abre o Chrome e o Spotify"
    assert waits == [(V.GO_ON_WAIT, True)] * 2
    waits.clear()
    assert lis._finish("toca lofi", None, 300.0) == "toca lofi" and waits == []
    monkeypatch.setattr(lis, "_hear", lambda *a, **k: None)
    assert lis._finish("pesquisa sobre tipo", None, 300.0) == "pesquisa sobre tipo"  # você não continuou: segue


def test_continuation_wait_is_quiet_when_nobody_talks(monkeypatch, capsys):
    lis = V.Listener(put=lambda x: None, model_path="x")
    monkeypatch.setattr(V, "duck", lambda *a, **k: None)
    monkeypatch.setattr(V, "record_command", lambda *a, **k: b"")
    assert lis._hear(lambda: block(0), 300.0, no_speech=V.GO_ON_WAIT, quiet=True) is None
    assert "Não ouvi" not in capsys.readouterr().out


def test_question_listens_for_answer_without_name(monkeypatch):
    j = load_jarvis()

    class L:
        n = 0

        def follow_up(self):
            L.n += 1

    monkeypatch.setattr(j, "listener", L())
    monkeypatch.setattr(j, "handle", lambda t: print("Jarvis > Qual cidade, senhor?"))
    j.respond("como tá o tempo")
    assert L.n == 1
    monkeypatch.setattr(j, "handle", lambda t: print("Jarvis > Pronto, senhor."))
    j.respond("abre a calculadora")
    assert L.n == 1


WEATHER = "Boqueirão, Curitiba: Chuva fraca, +17°C (sensação +18°C), umidade 91%, vento 9km/h"


def test_weather_is_told_back_like_a_conversation(monkeypatch):
    j = load_jarvis()
    said, captions = [], []
    monkeypatch.setattr(j, "voice_out", True)
    monkeypatch.setattr(j, "speak", lambda t: said.append(t))
    monkeypatch.setattr(j.U, "speech", lambda t: captions.append(t))
    monkeypatch.setattr(j.F, "weather", lambda city="": print(f"Jarvis > {WEATHER}") or True)
    monkeypatch.setattr(j, "think", lambda *a, **k: "Verifiquei, senhor. Em Curitiba chove fraco, 17 graus.")
    j.respond("previsão do tempo")
    assert said == ["Verifiquei, senhor. Em Curitiba chove fraco, 17 graus."] and captions == said


def test_weather_without_ai_still_sounds_natural(monkeypatch):
    j = load_jarvis()
    said = []
    monkeypatch.setattr(j, "voice_out", True)
    monkeypatch.setattr(j, "speak", lambda t: said.append(t))
    monkeypatch.setattr(j.F, "weather", lambda city="": print(f"Jarvis > {WEATHER}") or True)

    def no_ai(*a, **k):
        raise RuntimeError("sem IA")

    monkeypatch.setattr(j, "think", no_ai)
    j.respond("previsão do tempo")
    assert said == ["Verifiquei, senhor. Em Curitiba está chuva fraca, com 17 graus e sensação de 18."
                    " A umidade está em 91 por cento."]


def _fake_edge(monkeypatch, fail):
    import types
    calls = []

    class Communicate:
        def __init__(self, text, *a, **k):
            self.text = text

        async def save(self, path):
            calls.append(self.text)
            if fail:
                raise RuntimeError("403, message='Invalid response status', url='wss://speech.platform.bing.com/x'")
            Path(path).write_bytes(b"mp3")

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=Communicate))
    monkeypatch.setattr(V, "_edge_off_until", 0.0)
    monkeypatch.setattr(V, "_play_mp3", lambda path: None)
    monkeypatch.setattr(V, "_has_gtts", lambda: False)
    return calls


def test_bing_refused_falls_back_to_elevenlabs(monkeypatch, tmp_path):
    edge = _fake_edge(monkeypatch, fail=True)
    eleven = []
    monkeypatch.setenv("ELEVENLABS_API_KEY", "teste")
    monkeypatch.setattr(V, "_eleven_mp3", lambda text, path: eleven.append(text) or Path(path).write_bytes(b"mp3"))
    V.say("Olá, senhor.")
    V.say("Tudo certo.")  # não tenta o Bing de novo logo em seguida
    assert edge == ["Olá, senhor."] and eleven == ["Olá, senhor.", "Tudo certo."]
    monkeypatch.setattr(V, "_edge_off_until", 1.0)  # passou o tempo: tenta o Bing de novo
    V.say("De novo.")
    assert edge == ["Olá, senhor.", "De novo."]


def test_bing_working_does_not_spend_elevenlabs_credits(monkeypatch):
    edge = _fake_edge(monkeypatch, fail=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "teste")
    monkeypatch.setattr(V, "_eleven_mp3", lambda *a: pytest.fail("gastou crédito à toa"))
    V.say("Olá, senhor.")
    assert edge == ["Olá, senhor."]


def test_without_elevenlabs_key_says_how_to_get_backup_voice(monkeypatch):
    _fake_edge(monkeypatch, fail=True)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as e:
        V.say("Olá, senhor.")
    assert "403" in str(e.value) and "ELEVENLABS_API_KEY" in str(e.value) and "wss://" not in str(e.value)


def test_google_voice_is_last_backup(monkeypatch):
    _fake_edge(monkeypatch, fail=True)
    used = []
    monkeypatch.setenv("ELEVENLABS_API_KEY", "teste")

    def no_credits(text, path):
        raise RuntimeError("acabaram os créditos da ElevenLabs deste mês")

    monkeypatch.setattr(V, "_eleven_mp3", no_credits)
    monkeypatch.setattr(V, "_has_gtts", lambda: True)
    monkeypatch.setattr(V, "_gtts_mp3", lambda text, path: used.append(text))
    V.say("Olá, senhor.")
    assert used == ["Olá, senhor."]


def test_elevenlabs_request_uses_portuguese_and_key_header(monkeypatch, tmp_path):
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"mp3"

    def fake_open(req, timeout=0):
        sent["url"], sent["key"], sent["body"] = req.full_url, req.get_header("Xi-api-key"), json.loads(req.data)
        return Resp()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "k123")
    monkeypatch.delenv("ELEVENLABS_MODEL", raising=False)
    monkeypatch.setenv("ELEVENLABS_VOICE", "zNEsdgTUa3ndwKry8Xcq")
    monkeypatch.setattr(V.urllib.request, "urlopen", fake_open)
    V._eleven_mp3("Olá", tmp_path / "a.mp3")
    assert sent["key"] == "k123" and sent["url"].endswith("/zNEsdgTUa3ndwKry8Xcq?output_format=mp3_44100_64")
    assert sent["body"] == {"text": "Olá", "model_id": "eleven_flash_v2_5", "language_code": "pt",
                             "voice_settings": {"stability": 0.58, "similarity_boost": 0.75,
                                                "style": 0.0, "speed": 0.98, "use_speaker_boost": True}}
    assert (tmp_path / "a.mp3").read_bytes() == b"mp3"


def test_elevenlabs_voice_found_by_name(monkeypatch):
    asked = []

    def fake_get(url):
        asked.append(url)
        return {"voices": [{"name": "Elvis Presley Fake", "voice_id": "B" * 20},
                           {"name": "Elvis", "voice_id": "A" * 20}]}

    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.delenv("ELEVENLABS_VOICE", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    monkeypatch.setattr(V, "_eleven_voice_ids", {})
    monkeypatch.setattr(V, "_eleven_get", fake_get)
    assert V.eleven_voice() == "A" * 20  # o nome exato ganha
    assert V.eleven_voice() == "A" * 20 and len(asked) == 1  # guarda: não pergunta toda fala
    monkeypatch.setattr(V, "_eleven_voice_ids", {})
    monkeypatch.setattr(V, "_eleven_get", lambda url: {"voices": []})
    assert V.eleven_voice() == V.ELEVEN_BACKUP_VOICE  # não achou: usa a George


def test_library_voice_refused_uses_george(monkeypatch, capsys):
    tried = []

    def fake_request(text, path, voice, model):
        tried.append(voice)
        if voice != V.ELEVEN_BACKUP_VOICE:
            raise V.ElevenError("HTTP 402 Free users cannot use library voices via the API", 402,
                                "Free users cannot use library voices via the API")

    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE", "A" * 20)
    monkeypatch.setattr(V, "_eleven_request", fake_request)
    monkeypatch.setattr(V, "_eleven_voice_ids", {})
    V._eleven_mp3("Olá", "x.mp3")
    V._eleven_mp3("De novo", "x.mp3")  # não insiste na voz recusada
    assert tried == ["A" * 20, V.ELEVEN_BACKUP_VOICE, V.ELEVEN_BACKUP_VOICE]
    assert capsys.readouterr().out.count("uso a George") == 1


def test_failed_backup_voice_says_why(monkeypatch, capsys):
    _fake_edge(monkeypatch, fail=True)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setattr(V, "_told", {})

    def broken(text, path):
        raise V.ElevenError("a chave foi recusada (invalid api key)")

    monkeypatch.setattr(V, "_eleven_mp3", broken)
    monkeypatch.setattr(V, "_has_gtts", lambda: True)
    monkeypatch.setattr(V, "_gtts_mp3", lambda text, path: None)
    V.say("Olá")
    V.say("De novo")
    out = capsys.readouterr().out
    assert out.count("a ElevenLabs falhou: a chave foi recusada") == 1 and "falo com a Google" in out


def test_startup_line_tells_which_voices(monkeypatch):
    monkeypatch.setattr(V, "_has_gtts", lambda: True)
    monkeypatch.delenv("ELEVENLABS_VOICE", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    assert "ElevenLabs (Elvis) -> Google" in V.voices_summary()
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    assert "ELEVENLABS_API_KEY não chegou" in V.voices_summary()


def test_key_id_instead_of_key_is_explained(monkeypatch):
    monkeypatch.setattr(V, "_has_gtts", lambda: False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "abc123")
    assert "não começa com sk_" in V.voices_summary()
    err = V.ElevenError("HTTP 400", 400, "API key ID used as API key - only valid API keys can be used.")
    assert not V._voice_refused(err)  # não adianta trocar para a George


def test_key_with_extra_text_pasted_is_cleaned(monkeypatch):
    key = "sk_" + "a1" * 24
    monkeypatch.setenv("ELEVENLABS_API_KEY", f'"{key}" ')
    assert V.eleven_key() == key
    monkeypatch.setenv("ELEVENLABS_API_KEY", "ELEVENLABS_API_KEY=" + key)
    assert V.eleven_key() == key
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_" + "b" * 64)  # comprida demais: não dá para adivinhar
    monkeypatch.setattr(V, "_has_gtts", lambda: False)
    assert "tem 67 caracteres" in V.voices_summary()


def test_youtube_player_error_moves_videos_to_default_browser(monkeypatch):
    j = load_jarvis()
    calls = []
    monkeypatch.setattr(j, "_youtube_outside", False)
    monkeypatch.delenv("JARVIS_YOUTUBE", raising=False)
    monkeypatch.setattr(j.B, "available", lambda: True)
    monkeypatch.setattr(j.B, "play_youtube", lambda q: calls.append(("jarvis", q)) or j.B.PLAYER_ERROR)
    monkeypatch.setattr(j.F, "play_youtube", lambda q: calls.append(("padrao", q)) or True)
    monkeypatch.setattr(j.B, "on_youtube", lambda: True)
    monkeypatch.setattr(j.B, "youtube_control", lambda *a: calls.append(("teclas jarvis",)) or True)
    monkeypatch.setattr(j.F, "youtube_control", lambda a: calls.append(("teclas padrao", a)) or True)
    j.play_youtube("p do pecado")
    j.play_youtube("evidencias")  # o próximo já vai direto para o navegador padrão
    j.youtube_control("pausar")  # e as teclas vão para lá, não para a aba quebrada
    assert calls == [("jarvis", "p do pecado"), ("padrao", "p do pecado"), ("padrao", "evidencias"),
                     ("teclas padrao", "pausar")]


def test_player_check_sees_youtube_error():
    import navegador as B

    class Loc:
        def __init__(self, visible):
            self.first = self
            self.visible = visible

        def is_visible(self):
            return self.visible

    class Page:
        def __init__(self, error, playing):
            self.error, self.playing = error, playing

        def locator(self, sel):
            return Loc(self.error)

        def evaluate(self, js):
            return self.playing

    assert B._player_ok(Page(error=True, playing=False), seconds=1) is False
    assert B._player_ok(Page(error=False, playing=True), seconds=1) is True


@pytest.mark.parametrize("text", ["Atenção, senhor. A bateria está fraca.",
                                  "Confirma que posso apagar o arquivo?", "Não consegui abrir o programa."])
def test_elevenlabs_alerts_use_serious_delivery(text):
    settings = V.eleven_delivery(text, "eleven_flash_v2_5")
    assert settings["stability"] == 0.72 and settings["speed"] == 0.94
    assert settings["style"] == 0.0


def test_elevenlabs_tone_can_be_fixed(monkeypatch):
    monkeypatch.setenv("BOLHA_TOM", "neutro")
    assert V.eleven_delivery("Confirma que posso apagar?", "eleven_flash_v2_5")["stability"] == 0.58
    monkeypatch.setenv("BOLHA_TOM", "serio")
    assert V.eleven_delivery("Tudo pronto, senhor.", "eleven_flash_v2_5")["stability"] == 0.72


def test_elevenlabs_model_specific_settings():
    v3 = V.eleven_delivery("Confirma que posso apagar?", "eleven_v3")
    assert v3["stability"] == 1.0 and "use_speaker_boost" not in v3
    v4 = V.eleven_delivery("Tudo pronto.", "eleven_v4")
    assert set(v4) == {"stability", "similarity_boost"}
