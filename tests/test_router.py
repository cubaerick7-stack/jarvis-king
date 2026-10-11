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
