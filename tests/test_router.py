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
    class Msg:
        content = '{"actions":[{"name":"open_target","args":{"target":"omori"}}],"reply":"Abri o omori"}'

    class Resp:
        message = Msg()

    monkeypatch.setattr(jarvis, "chat", lambda **kw: Resp())
    monkeypatch.setattr(jarvis, "open_target", lambda target: False)
    jarvis.ask_ai_router("omori")
    out = capsys.readouterr().out
    assert "Abri o omori" not in out and "Não deu certo: open_target" in out
