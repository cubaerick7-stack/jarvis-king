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


def test_reator_becomes_a_circle_when_window_is_square():
    html = (ROOT / "windows" / "interface" / "reator.html").read_text(encoding="utf-8")
    rule = "(min-aspect-ratio: 4/5) and (max-aspect-ratio: 5/4)"
    assert f"@media {rule}" in html and f"const BOLHA = '{rule}'" in html  # CSS e desenho com a mesma regra
    assert "window.mostraNome" in html


def test_ui_mode_and_round_are_safe(monkeypatch):
    import ui as U
    assert U.mode() == "bolha"
    monkeypatch.setenv("JARVIS_TELA", "Painel")
    assert U.mode() == "painel"
    for value, want in (("cheia", "cheia"), ("Tela cheia", "cheia"), ("clique", "clique"), ("qualquer", "bolha")):
        monkeypatch.setenv("JARVIS_TELA", value)
        assert U.mode() == want
    assert U._round(object()) is False  # fora do Windows (ou sem janela) não quebra
    assert U._round(object(), circle=False) is False


class FakeWindow:
    title = "Bolha"

    def __init__(self):
        self.calls = []

    def restore(self):
        self.calls.append("restore")

    def toggle_fullscreen(self):
        self.calls.append("toggle")

    def minimize(self):
        self.calls.append("minimize")

    def evaluate_js(self, code):
        self.calls.append(code.split("(")[0])


@pytest.fixture
def janela(monkeypatch):
    import ui as U
    w = FakeWindow()
    monkeypatch.setattr(U, "_window", w)
    monkeypatch.setattr(U, "_full", False)
    rounds = []
    monkeypatch.setattr(U, "_round", lambda window, circle=True: rounds.append(circle) or True)
    w.rounds = rounds
    return U, w


def test_bubble_opens_fullscreen_when_you_talk_and_closes_after(janela):
    U, w = janela
    U.heard("toca lofi")
    U.card("Tocando agora", "lofi")  # já está em tela cheia: não alterna de novo
    assert w.calls == ["restore", "toggle", "mostraVoce", "cartao"]
    assert w.rounds == [False]  # tirou o recorte redondo antes de crescer
    U.Api(lambda t: None).recolher()
    assert w.calls[-1] == "toggle" and w.rounds == [False, True] and U._full is False


def test_minimize_in_fullscreen_goes_back_to_the_bubble(janela):
    U, w = janela
    api = U.Api(lambda t: None)
    api.expandir()
    api.minimizar()
    assert w.calls == ["restore", "toggle", "toggle"]
    api.minimizar()  # já é bolha: aí minimiza de verdade
    assert w.calls[-1] == "minimize"


def test_click_mode_only_opens_with_a_double_click(janela, monkeypatch):
    U, w = janela
    monkeypatch.setenv("JARVIS_TELA", "clique")
    U.heard("toca lofi")
    assert "toggle" not in w.calls
    U.Api(lambda t: None).expandir()
    assert w.calls.count("toggle") == 1


def test_always_fullscreen_never_shrinks(janela, monkeypatch):
    U, w = janela
    monkeypatch.setenv("JARVIS_TELA", "cheia")
    monkeypatch.setattr(U, "_full", True)
    api = U.Api(lambda t: None)
    api.recolher()
    api.minimizar()
    assert w.calls == ["minimize"]


def test_fullscreen_page_has_windows_and_hooks():
    html = (ROOT / "windows" / "interface" / "reator.html").read_text(encoding="utf-8")
    assert "@media (min-width: 600px)" in html and "const CHEIA = '(min-width: 600px)'" in html
    for hook in ("window.mostraVoce", "api().recolher()", "api().expandir()", "border-radius: var(--raio)"):
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
