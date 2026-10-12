"""Testes do roteador rápido. Rodam em qualquer sistema: as ações reais
do Windows são trocadas por funções que só registram a chamada."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = [
    "set_volume", "get_volume", "mute_audio", "change_volume", "search_files",
    "open_search_result", "show_search_result", "open_target", "search_web",
    "media_control", "window_control", "system_info", "take_screenshot",
]


@pytest.fixture
def jarvis(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_ai", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ACTION_LOG = tmp_path / "acoes.log"
    mod.calls = []
    for name in ACTIONS:
        monkeypatch.setattr(mod, name, lambda *a, _n=name: mod.calls.append((_n, a)))
    mod.last_results = ["a.pdf", "b.pdf", "c.pdf"]
    return mod


def route(jarvis, text):
    jarvis.calls.clear()
    handled = jarvis.fast_local_router(text)
    return jarvis.calls if handled else "IA"


@pytest.mark.parametrize("text, expected", [
    # TESTES.txt
    ("mn muta o volume", [("mute_audio", (True,))]),
    ("desmuta", [("mute_audio", (False,))]),
    ("coloca o volume em 50", [("set_volume", (50,))]),
    ("deixa o volume na metade", [("set_volume", (50,))]),
    ("qual o volume", [("get_volume", ())]),
    ("procura um pdf", [("search_files", ("pdf",))]),
    ("procura o arquivo FO 1102", [("search_files", ("fo 1102",))]),
    ("abre o primeiro", [("open_search_result", (1,))]),
    ("mostra o primeiro na pasta", [("show_search_result", (1,))]),
    ("abre a calculadora", [("open_target", ("calculadora",))]),
    ("abre youtube", [("open_target", ("youtube",))]),
    # bugs corrigidos
    ("desmuta o volume", [("mute_audio", (False,))]),
    ("aumenta o volume em 10", [("change_volume", (10,))]),
    ("abaixa o som 5", [("change_volume", (-5,))]),
    ("aumenta o volume", [("change_volume", (10,))]),
    ("procura no youtube lofi", [("search_web", ("lofi", "youtube"))]),
    ("busca na internet previsão do tempo", [("search_web", ("previsão do tempo", "google"))]),
    ("pesquisa receita de bolo", [("search_web", ("receita de bolo", "google"))]),
    ("mostra o segundo na pasta", [("show_search_result", (2,))]),
    ("abre o terceiro", [("open_search_result", (3,))]),
    ("abre o 2", [("open_search_result", (2,))]),
    ("pausa a música", [("media_control", ("play_pause",))]),
    ("próxima música", [("media_control", ("next",))]),
    ("tira um print", [("take_screenshot", ())]),
])
def test_router(jarvis, text, expected):
    assert route(jarvis, text) == expected


def test_unknown_goes_to_ai(jarvis):
    assert route(jarvis, "organiza minha semana") == "IA"


def test_actions_are_logged(jarvis):
    route(jarvis, "coloca o volume em 30")
    assert "set_volume\t30" in jarvis.ACTION_LOG.read_text(encoding="utf-8")


def test_file_search_ignores_accents(jarvis, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_real", ROOT / "windows" / "jarvis_ai.py")
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    (tmp_path / "Relatório Final.pdf").write_text("x")
    (tmp_path / "outro.txt").write_text("x")
    monkeypatch.setattr(real, "SEARCH_ROOTS", [tmp_path])
    found = real.search_files("relatorio")
    assert [Path(p).name for p in found] == ["Relatório Final.pdf"]


@pytest.mark.parametrize("text, expected", [
    ("2", [("open_search_result", (2,))]),
    ("o segundo", [("open_search_result", (2,))]),
    ("executa o 3", [("open_search_result", (3,))]),
    ("executa o omori.exe", [("open_target", ("omori.exe",))]),
    ("roda o omori", [("open_target", ("omori",))]),
])
def test_router_programs(jarvis, text, expected):
    assert route(jarvis, text) == expected


def load_real():
    spec = importlib.util.spec_from_file_location("jarvis_real", ROOT / "windows" / "jarvis_ai.py")
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    return real


def make_omori(tmp_path):
    game = tmp_path / "Nova pasta" / "OMORIES"
    (game / "www" / "fonts").mkdir(parents=True)
    (game / "www" / "fonts" / "OMORI_GAME.ttf").write_text("x")
    (game / "OMORIgame.exe").write_text("x")
    (game / "OMORI.exe").write_text("x")
    (tmp_path / "Nova pasta" / "A").mkdir()
    (tmp_path / "Nova pasta" / "A" / "OMORI.lnk").write_text("x")
    return game


def test_find_program_prefers_shortcut_then_exe(tmp_path, monkeypatch):
    real = load_real()
    make_omori(tmp_path)
    monkeypatch.setattr(real, "PROGRAM_ROOTS", [tmp_path])
    assert real.find_program("omori.exe").name == "OMORI.lnk"
    assert real.find_program("omorie").name == "OMORI.lnk"  # erro de digitação
    assert real.find_program("jogo que nao existe") is None


def test_search_ranks_exact_name_and_programs_first(tmp_path, monkeypatch):
    real = load_real()
    make_omori(tmp_path)
    monkeypatch.setattr(real, "SEARCH_ROOTS", [tmp_path])
    names = [Path(p).name for p in real.search_files("omori")]
    assert names[:2] == ["OMORI.lnk", "OMORI.exe"]
    assert names[-1] == "OMORI_GAME.ttf"


@pytest.mark.parametrize("text", ["2 execute", "executa o 2", "abre 2", "2"])
def test_number_with_verb(jarvis, text):
    assert route(jarvis, text) == [("open_search_result", (2,))]


def test_broken_shortcut_falls_back_to_exe(tmp_path, monkeypatch):
    real = load_real()
    make_omori(tmp_path)
    monkeypatch.setattr(real, "PROGRAM_ROOTS", [tmp_path])
    opened = []

    def fake_startfile(path, cwd=None):
        if path.endswith(".lnk"):
            raise OSError(1223, "A operação foi cancelada pelo usuário")
        opened.append((Path(path).name, Path(cwd).name))

    monkeypatch.setattr(real.os, "startfile", fake_startfile, raising=False)
    assert real.open_target("omori") is True
    assert opened == [("OMORI.exe", "OMORIES")]  # abre a partir da pasta do jogo


@pytest.mark.parametrize("query, first", [("omoir", "OMORI.lnk"), ("omorie", "OMORIES"), ("omories", "OMORIES")])
def test_search_typos_and_folders(tmp_path, monkeypatch, query, first):
    real = load_real()
    make_omori(tmp_path)
    monkeypatch.setattr(real, "SEARCH_ROOTS", [tmp_path])
    found = real.search_files(query)
    assert found and Path(found[0]).name == first


def test_ai_does_not_claim_success_when_action_fails(jarvis, monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_LOCAL", "1")  # simula a IA pelo Qwen
    class Msg:
        content = '{"actions":[{"name":"open_target","args":{"target":"omori"}}],"reply":"Abri o omori"}'

    class Resp:
        message = Msg()

    monkeypatch.setattr(jarvis, "chat", lambda **kw: Resp())
    monkeypatch.setattr(jarvis, "open_target", lambda target: False)
    jarvis.ask_ai_router("omori")
    out = capsys.readouterr().out
    assert "Abri o omori" not in out and "Não deu certo: open_target" in out


@pytest.mark.parametrize("text, expected", [
    ("o que você sabe fazer", [("show_help", ())]),
    ("ajuda", [("show_help", ())]),
    ("que horas são", [("tell_time", ())]),
    ("abre a pasta downloads", [("open_folder", ("downloads",))]),
    ("abre minha pasta de documentos", [("open_folder", ("documentos",))]),
])
def test_router_help_time_folders(jarvis, monkeypatch, text, expected):
    for name in ["show_help", "tell_time", "open_folder"]:
        monkeypatch.setattr(jarvis, name, lambda *a, _n=name: jarvis.calls.append((_n, a)))
    assert route(jarvis, text) == expected


def test_catalog_drives_prompt_and_help(capsys):
    real = load_real()
    for tool in real.TOOLS:
        assert tool["name"] in real.AI_PROMPT
        assert tool["group"] in real.TOOL_GROUPS
    real.show_help()
    out = capsys.readouterr().out
    assert "abre o omori" in out and "tira um print" in out


def test_ai_runs_catalog_tools(jarvis, monkeypatch):
    monkeypatch.setenv("JARVIS_LOCAL", "1")  # simula a IA pelo Qwen
    class Msg:
        content = ('{"actions":[{"name":"set_volume","args":{"percent":25}},'
                   '{"name":"open_target","args":{"target":"notepad"}}],"reply":"ok"}')

    class Resp:
        message = Msg()

    monkeypatch.setattr(jarvis, "chat", lambda **kw: Resp())
    jarvis.calls.clear()
    jarvis.ask_ai_router("modo estudo")
    assert jarvis.calls == [("set_volume", (25,)), ("open_target", ("notepad",))]


def test_find_program_walks_games_drive_everything_does_not_index(tmp_path, monkeypatch):
    real = load_real()
    games = tmp_path / "G"
    make_omori(games)
    empty = tmp_path / "menu"
    empty.mkdir()
    monkeypatch.setattr(real, "PROGRAM_ROOTS", [empty])
    monkeypatch.setattr(real, "EXTRA_PROGRAM_ROOTS", [games])
    monkeypatch.setattr(real.F, "everything_search", lambda q, n=400, ext=None: [])
    monkeypatch.setattr(real.F, "indexes_drive", lambda d: False)  # G: em exFAT: o "nada" não vale
    assert real.find_program("omori").name == "OMORI.lnk"
    monkeypatch.setattr(real.F, "indexes_drive", lambda d: True)  # G: indexado: confia no Everything
    assert real.find_program("omori") is None


def test_store_app_opens_without_typing(monkeypatch):
    real = load_real()
    monkeypatch.setattr(real, "find_programs", lambda name: [])
    monkeypatch.setattr(real.F, "store_app", lambda name: ("Câmera", "Microsoft.WindowsCamera_8wekyb3d8bbwe!App"))
    opened = []
    monkeypatch.setattr(real.os, "startfile", lambda path, *a, **k: opened.append(path), raising=False)
    monkeypatch.setattr(real, "need_pyautogui", lambda: (_ for _ in ()).throw(AssertionError("digitou")))
    assert real.open_target("câmera") is True
    assert opened == ["shell:AppsFolder\\Microsoft.WindowsCamera_8wekyb3d8bbwe!App"]


@pytest.mark.parametrize("text", ["me lembra às 7h de tomar remédio", "me lembra amanhã às 15h da reunião",
                                  "alarme às 6 horas"])
def test_reminder_at_a_time_goes_to_ai_not_timer(text):
    real = load_real()
    used = []
    real.tool = lambda name, **a: used.append(name) or True
    assert real.fast_local_router(text) is False and used == []  # a IA marca o lembrete com data e hora


def test_timer_in_minutes_keeps_the_message():
    real = load_real()
    used = []
    real.tool = lambda name, **a: used.append((name, a)) or True
    assert real.fast_local_router("coloca um alarme em 20 minutos pra tirar o bolo") is True
    assert used == [("start_timer", {"minutes": 20, "message": "tirar o bolo"})]


def test_name_prefix_is_removed_but_keeps_the_rest():
    real = load_real()
    assert real.NAME == "Bolha"
    assert real.clean_prefix("Bolha, digita Olá Mundo") == "digita Olá Mundo"
    assert real.clean_prefix("jarvis abre o chrome") == "abre o chrome"  # o nome antigo, digitado, ainda vale
    assert real.clean_prefix("mn muta o volume") == "muta o volume"
    assert real.clean_prefix("Manoel ligou?") == "Manoel ligou?"  # "mano" só sozinho


def test_assistant_introduces_itself_with_the_name(capsys):
    real = load_real()
    assert real.fast_local_router("bolha, quem é você?") is True
    assert "Meu nome é Bolha" in capsys.readouterr().out
    assert "Seu nome é Bolha" in real.AI_PROMPT and "oi bolha, tudo bem?" in real.AI_PROMPT


@pytest.mark.parametrize("text", ["calma", "Calma, mano.", "peraí", "Bolha, espera aí", "deixa eu pensar",
                                  "Calma, mano Eu tipo, não tenho um negócio, mano Eu não falei o que quero ainda "
                                  "Não pesquisa quando eu mandar algo do tipo",
                                  "ainda não te falei", "isso não era um pedido"])
def test_thinking_aloud_does_nothing(jarvis, text, capsys):
    assert route(jarvis, text) == []
    assert "senhor" in capsys.readouterr().out


@pytest.mark.parametrize("text", ["ainda não falei com a Ana, manda pra ela que eu chego às 8",
                                  "calma que eu já volto, toca lofi", "pesquisa receita de bolo"])
def test_real_requests_are_not_mistaken_for_thinking_aloud(jarvis, text):
    assert route(jarvis, text) != []  # vai para a ação ou para a IA, nunca para o "pode falar"


def test_ai_is_told_not_to_search_half_sentences(jarvis):
    assert "NUNCA pesquise só porque não entendeu" in jarvis.AI_PROMPT


@pytest.mark.parametrize("text", ["toca evidências no spotify", "abre o spotify e toca evidências",
                                  "Toque Spotify e evidências", "abre o spotify e pesquisa evidencias"])
def test_spotify_music_stays_in_spotify(jarvis, monkeypatch, text):
    asked = []
    monkeypatch.setattr(jarvis.F, "spotify_play", lambda q: asked.append(q) or True)
    assert jarvis.fast_local_router(text) is True
    assert asked == ["evidencias"]


@pytest.mark.parametrize("text", ["abre o chatgpt", "abre o whatsapp web"])
def test_sites_open_in_jarvis_browser(text, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("jx", ROOT / "windows" / "jarvis_ai.py")
    j = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(j)
    opened = []
    monkeypatch.setattr(j, "open_url", lambda u: opened.append(u) or True)
    assert j.open_target(text.split(" ", 1)[1]) is True
    assert opened and opened[0].startswith("https://")


def test_instagram_opens_in_users_own_browser(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("jx2", ROOT / "windows" / "jarvis_ai.py")
    j = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(j)
    opened, own = [], []
    monkeypatch.setattr(j, "open_url", lambda u: opened.append(u) or True)
    monkeypatch.setattr(j.webbrowser, "open", lambda u: own.append(u) or True)
    assert j.open_target("instagram") is True
    assert own == ["https://www.instagram.com"] and opened == []
