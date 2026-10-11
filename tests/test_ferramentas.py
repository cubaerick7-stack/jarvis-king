"""Testes das ferramentas extras e das rotas novas do roteador rápido."""
import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))
import ferramentas as F  # noqa: E402


@pytest.fixture
def jarvis(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_ai", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ACTION_LOG = tmp_path / "acoes.log"
    mod.calls = []
    monkeypatch.setattr(mod, "tool", lambda tool_name, /, **a: mod.calls.append((tool_name, a)))
    monkeypatch.setattr(mod, "window_control", lambda *a: mod.calls.append(("window_control", a)))
    mod.last_results = ["a.pdf", "b.pdf", "c.pdf"]
    return mod


def route(jarvis, text):
    jarvis.calls.clear()
    return jarvis.calls if jarvis.fast_local_router(text) else "IA"


@pytest.mark.parametrize("text, expected", [
    ("quanto de bateria tem", [("battery_status", {})]),
    ("abre as configurações de bluetooth", [("open_settings", {"page": "bluetooth"})]),
    ("abre as configurações", [("open_settings", {"page": ""})]),
    ("brilho em 70", [("set_brightness", {"percent": 70})]),
    ("desliga o pc em 30 minutos", [("power_action", {"action": "desligar", "minutes": 30})]),
    ("reinicia o computador", [("power_action", {"action": "reiniciar", "minutes": 1})]),
    ("desliga o pc em 2 horas", [("power_action", {"action": "desligar", "minutes": 120})]),
    ("cancela o desligamento", [("power_action", {"action": "cancelar"})]),
    ("bloqueia o pc", [("power_action", {"action": "bloquear"})]),
    ("fecha o chrome", [("close_app", {"name": "chrome"})]),
    ("fecha essa janela", [("window_control", ("fechar",))]),
    ("me lembra em 10 minutos de tirar o bolo", [("start_timer", {"minutes": 10, "message": "tirar o bolo"})]),
    ("timer de 30 segundos", [("start_timer", {"minutes": 0.5, "message": "Tempo esgotado!"})]),
    ("cancela os timers", [("cancel_timers", {})]),
    ("clima em São Paulo", [("weather", {"city": "sao paulo"})]),
    ("como tá o tempo", [("weather", {"city": ""})]),
    ("quanto é 15% de 320", [("calculate", {"expression": "15% de 320"})]),
    ("calcula 12 vezes 7", [("calculate", {"expression": "12 vezes 7"})]),
    ("lê o primeiro", [("read_file", {"path": "1"})]),
    ("resume o segundo", [("summarize_file", {"path": "2"})]),
    ("apaga o terceiro", [("delete_item", {"path": "3"})]),
    ("digita Olá, tudo bem?", [("type_text", {"text": "Olá, tudo bem?"})]),
    ("modo estudo", [("run_routine", {"name": "estudo"})]),
    ("quais rotinas tem", [("list_routines", {})]),
    ("tô com internet?", [("network_info", {})]),
    ("o pc tá lento", [("list_processes", {})]),
    ("quais janelas estão abertas", [("list_windows", {})]),
    ("o que eu copiei", [("read_clipboard", {})]),
    ("vai para o chrome", [("focus_window", {"title": "chrome"})]),
])
def test_new_routes(jarvis, text, expected):
    assert route(jarvis, text) == expected


def test_desliga_o_som_mutes_not_unmutes(jarvis, monkeypatch):
    monkeypatch.setattr(jarvis, "mute_audio", lambda m: jarvis.calls.append(("mute_audio", (m,))))
    assert route(jarvis, "desliga o som") == [("mute_audio", (True,))]


@pytest.mark.parametrize("expr, value", [
    ("2+2", 4), ("12 vezes 7", 84), ("10 dividido por 4", 2.5), ("15% de 320", 48),
    ("2 elevado a 10", 1024), ("3,5 mais 1,5", 5), ("(2+3)*4", 20),
])
def test_calculate(expr, value):
    assert F.calculate(expr) == value


@pytest.mark.parametrize("expr", ["__import__('os')", "9**9**9", "abc"])
def test_calculate_rejects_unsafe(expr):
    assert F.calculate(expr) is False


def test_every_tool_is_documented_and_callable():
    spec = importlib.util.spec_from_file_location("j2", ROOT / "windows" / "jarvis_ai.py")
    j = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(j)
    names = [t["name"] for t in j.TOOLS]
    assert len(names) == len(set(names)) and len(names) >= 40
    for t in j.TOOLS:
        assert t["group"] in j.TOOL_GROUPS and t["examples"] and callable(t["run"])
        assert t["name"] in j.AI_PROMPT


def test_file_ops(tmp_path):
    src = tmp_path / "nota.txt"
    src.write_text("olá jarvis", encoding="utf-8")
    dest = tmp_path / "backup"
    assert F.create_folder(dest)
    copied = Path(F.copy_item(src, dest))
    assert copied.read_text(encoding="utf-8") == "olá jarvis"
    renamed = Path(F.rename_item(copied, "nota final"))
    assert renamed.name == "nota final.txt"
    assert F.move_item(src, renamed) is False  # não sobrescreve
    moved = Path(F.move_item(src, tmp_path / "backup" / "outra.txt"))
    assert moved.exists() and not src.exists()


def test_read_txt_and_docx(tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("linha 1\nlinha 2", encoding="utf-8")
    assert F.read_file(txt) == "linha 1\nlinha 2"
    docx = tmp_path / "b.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:p><w:t>Contrato</w:t></w:p><w:p><w:t>Final</w:t></w:p></w:document>")
    assert F.read_file(docx) == "Contrato\nFinal"


def test_delete_asks_first(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("x")
    assert F.send_to_recycle_bin(f, confirm=lambda q: False) is False
    assert f.exists()


def test_close_app_refuses_protected():
    assert F.close_app("explorer") is False
    assert F.close_app("python.exe") is False


def test_routines(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "ROUTINES_FILE", tmp_path / "rotinas.json")
    (tmp_path / "rotinas.json").write_text('{"Jogo": [{"name": "set_volume", "args": {"percent": 70}}]}', encoding="utf-8")
    ran = []
    assert F.run_routine("jogo", lambda n, a: ran.append((n, a)))
    assert ran == [("set_volume", {"percent": 70})]
    assert "estudo" in F.list_routines()
    assert F.run_routine("inexistente", lambda n, a: None) is False


def test_resolve_path_uses_last_results(jarvis):
    assert jarvis.resolve_path("2") == Path("b.pdf")
    assert jarvis.resolve_path("ele") == Path("a.pdf")
    assert jarvis.resolve_path("o terceiro") == Path("c.pdf")


def test_tool_accepts_arg_called_name(monkeypatch):
    spec = importlib.util.spec_from_file_location("j3", ROOT / "windows" / "jarvis_ai.py")
    j = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(j)
    got = []
    monkeypatch.setattr(F, "close_app", lambda name: got.append(name) or True)
    monkeypatch.setattr(j, "log_action", lambda *a: None)
    assert j.tool("close_app", name="chrome") is True and got == ["chrome"]


@pytest.mark.parametrize("text", ["oi", "Oi Jarvis!", "bom dia", "valeu", "tudo bem?", "quem é você"])
def test_small_talk_skips_ai(jarvis, text):
    assert jarvis.fast_local_router(text) is True and jarvis.calls == []


def test_ai_calls_share_options_and_keep_alive(jarvis, monkeypatch):
    seen = []

    class Resp:
        class message:
            content = '{"actions":[],"reply":"ok"}'

    monkeypatch.setattr(jarvis, "chat", lambda **kw: seen.append(kw) or Resp())
    jarvis.warm_up_ai()
    jarvis.ask_ai_router("organiza minha semana")
    assert seen[0]["messages"][0] == seen[1]["messages"][0]  # mesmo prompt => cache do Ollama
    assert all(k["keep_alive"] == jarvis.KEEP_ALIVE for k in seen)
    assert seen[0]["options"]["num_ctx"] == seen[1]["options"]["num_ctx"]


@pytest.mark.parametrize("text", [
    "ABRE O BLOCO DE NOTA E ME EXPLIQUE BREVEMENTE QM FOI MARECHAL DEODORO DA FONSECA",
    "abre o chrome e pesquisa clima",
    "muta o som e depois abre o youtube",
])
def test_compound_goes_to_ai(jarvis, text):
    assert route(jarvis, text) == "IA"


@pytest.mark.parametrize("text", ["procura o arquivo pedra e papel", "abre o bloco de notas"])
def test_simple_with_e_still_fast(jarvis, monkeypatch, text):
    monkeypatch.setattr(jarvis, "search_files", lambda q: jarvis.calls.append(("search_files", q)))
    monkeypatch.setattr(jarvis, "open_target", lambda t: jarvis.calls.append(("open_target", t)))
    assert route(jarvis, text) != "IA"


def test_long_unknown_target_is_not_typed_in_start_menu(monkeypatch):
    spec = importlib.util.spec_from_file_location("j4", ROOT / "windows" / "jarvis_ai.py")
    j = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(j)
    monkeypatch.setattr(j, "find_programs", lambda name: [])
    monkeypatch.setattr(j, "pyautogui", None)  # se tentasse digitar, quebraria
    assert j.open_target("bloco de nota e me explique quem foi deodoro") is False


def test_ai_waits_for_window_before_typing(jarvis, monkeypatch):
    order = []

    class Resp:
        class message:
            content = ('{"actions":[{"name":"open_target","args":{"target":"notepad"}},'
                       '{"name":"type_text","args":{"text":"oi"}}],"reply":"ok"}')

    monkeypatch.setattr(jarvis, "chat", lambda **kw: Resp())
    monkeypatch.setattr(jarvis, "open_target", lambda t: order.append("open") or True)
    monkeypatch.setattr(F, "type_text", lambda t: order.append("type") or True)
    monkeypatch.setattr(jarvis.time, "sleep", lambda s: order.append(f"sleep{s}"))
    jarvis.ask_ai_router("abre o bloco de notas e escreve oi")
    assert order == ["open", "sleep1.5", "type"]
