"""As mãos do Bolha: a parte que dá para testar fora do Windows (tabelas, planos, desfazer, jogos...)."""
import os
import time
import zipfile
from pathlib import Path

import pytest

import maos


def test_winget_table():
    text = ("Nome                 ID                       Versão    Disponível Origem\n"
            "--------------------------------------------------------------------------\n"
            "VLC media player     VideoLAN.VLC             3.0.18    3.0.21     winget\n"
            "Mozilla Firefox (pt) Mozilla.Firefox.pt-BR    120.0     131.0      winget\n"
            "2 atualizações disponíveis.\n")
    rows = maos.parse_winget_table(text)
    assert [maos._col(r, "id") for r in rows] == ["VideoLAN.VLC", "Mozilla.Firefox.pt-BR"]
    assert maos._col(rows[0], "nome", "name") == "VLC media player"
    assert maos._col(rows[1], "dispon") == "131.0"


def test_instala_pede_confirmacao(monkeypatch):
    monkeypatch.setattr(maos, "winget_path", lambda: "winget")
    monkeypatch.setattr(maos, "winget_search", lambda n: [{"nome": "VLC media player", "id": "VideoLAN.VLC", "versao": "3"}])
    ran = []
    monkeypatch.setattr(maos, "_run", lambda args, **k: ran.append(args))
    assert maos.install_program("vlc", lambda q: False) is False
    assert ran == []  # sem "sim", nada roda


@pytest.mark.parametrize("pedido, nomes, esperado", [
    ("salvar", ["Arquivo", "Salvar (Ctrl+S)", "Desfazer"], 1),
    ("enviar", ["Cancelar", "Enviar"], 1),
    ("ok", ["Cancelar", "OK"], 1),
    ("xyz", ["Cancelar", "OK"], None),
])
def test_acha_o_botao_pelo_nome(pedido, nomes, esperado):
    assert maos.best_match(pedido, nomes) == esperado


def test_atalhos_do_word_em_portugues():
    assert maos.shortcut_for("salva", "winword") == "ctrl+b"
    assert maos.shortcut_for("negrito", "winword") == "ctrl+n"
    assert maos.shortcut_for("salva", "notepad") == "ctrl+s"
    assert maos.shortcut_for("nova aba", "chrome") == "ctrl+t"


def _files(folder, names):
    folder.mkdir(parents=True, exist_ok=True)
    for i, n in enumerate(names):
        p = folder / n
        p.write_text("x")
        os.utime(p, (time.time() - 1000 + i, time.time() - 1000 + i))


def test_organiza_por_tipo_e_desfaz(tmp_path):
    d = tmp_path / "Downloads"
    _files(d, ["foto.jpg", "contrato.pdf", "setup.exe", "musica.mp3", "x.abc"])
    assert maos.organize_folder(d, lambda q: True)
    assert (d / "Imagens" / "foto.jpg").exists() and (d / "Instaladores" / "setup.exe").exists()
    assert (d / "Outros" / "x.abc").exists()
    assert maos.undo_last()
    assert sorted(p.name for p in d.iterdir()) == ["contrato.pdf", "foto.jpg", "musica.mp3", "setup.exe", "x.abc"]


def test_organizar_sem_sim_nao_mexe(tmp_path):
    d = tmp_path / "D"
    _files(d, ["a.jpg"])
    assert maos.organize_folder(d, lambda q: False) is False
    assert (d / "a.jpg").exists()


def test_renomeia_em_lote_na_ordem_da_data_e_desfaz(tmp_path):
    d = tmp_path / "Fotos"
    _files(d, ["IMG_9.jpg", "IMG_1.jpg", "IMG_5.jpg"])
    assert maos.batch_rename(d, "praia", lambda q: True)
    assert sorted(p.name for p in d.iterdir()) == ["praia 01.jpg", "praia 02.jpg", "praia 03.jpg"]
    maos.undo_last()
    assert sorted(p.name for p in d.iterdir()) == ["IMG_1.jpg", "IMG_5.jpg", "IMG_9.jpg"]


def test_compacta_e_descompacta(tmp_path):
    d = tmp_path / "proj"
    _files(d, ["a.txt", "b.txt"])
    z = maos.compress(d)
    assert set(zipfile.ZipFile(z).namelist()) == {"proj/a.txt", "proj/b.txt"}
    out = maos.extract(z, str(tmp_path / "saida"))
    assert (Path(out) / "proj" / "a.txt").exists()


def test_nao_descompacta_zip_que_sai_da_pasta(tmp_path):
    z = tmp_path / "mau.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../fora.txt", "x")
    assert maos.extract(z) is False
    assert not (tmp_path / "fora.txt").exists()


def test_jogos_da_steam(tmp_path):
    lib = tmp_path / "Steam" / "steamapps"
    lib.mkdir(parents=True)
    (lib / "appmanifest_1150690.acf").write_text('"AppState"\n{\n\t"appid"\t\t"1150690"\n\t"name"\t\t"OMORI"\n}')
    games = maos.steam_games([tmp_path / "Steam"])
    assert games == {"omori": ("OMORI", "1150690")}


def test_programa_novo_abrindo_com_o_windows():
    assert maos.new_startup_programs({"OneDrive": "x"}) == []  # a primeira vez só guarda
    assert maos.new_startup_programs({"OneDrive": "x", "Spotify": "y"}) == ["Spotify"]
    assert maos.new_startup_programs({"OneDrive": "x", "Spotify": "y"}) == []


def test_por_que_ta_lento_oferece_fechar_o_culpado(monkeypatch, capsys):
    monkeypatch.setattr(maos, "heavy_processes", lambda: [("chrome", 65.0, 2100, [1]), ("explorer", 1.0, 90, [2])])
    import psutil
    asked, closed = [], []
    maos.why_slow(lambda q: asked.append(q) or True, close=lambda n: closed.append(n) or True)
    out = capsys.readouterr().out
    assert "O culpado parece ser chrome" in out and asked == ["Fecho o chrome?"] and closed == ["chrome"]


def test_historico_da_area_de_transferencia(monkeypatch):
    import ferramentas
    typed = []
    monkeypatch.setattr(ferramentas, "type_text", lambda t: typed.append(t) or True)
    maos.clip_history[:] = ["agora", "antes", "bem antes"]
    assert maos.clipboard_paste(2) and typed == ["antes"]
    assert maos.clipboard_paste(9) is False


def test_volume_por_programa(monkeypatch):
    class Vol:
        v = 0.5
        def GetMasterVolume(self): return self.v
        def SetMasterVolume(self, v, ctx): Vol.v = v
    class S:
        SimpleAudioVolume = Vol()
    monkeypatch.setattr(maos, "_sessions", lambda: [("discord", S()), ("chrome", S())])
    assert maos.app_volume("discord", delta=20) == 70
    assert maos.app_volume("spotify", percent=10) is False


def test_tipo_de_arquivo():
    assert maos.kind_of("a.PNG") == "Imagens" and maos.kind_of("b.docx") == "Documentos" and maos.kind_of("c") == "Outros"


# ------------------------- comandos de voz -------------------------
import importlib.util

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def jarvis(monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_ai", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.calls = []
    monkeypatch.setattr(mod, "tool", lambda _n, /, **a: mod.calls.append((_n, a)) or True)
    monkeypatch.setattr(mod, "act", lambda _n, fn, *a: mod.calls.append((_n, a)) or True)
    return mod


@pytest.mark.parametrize("frase, esperado", [
    ("clica em Salvar", ("click_ui", {"name": "Salvar"})),
    ("clica no botão Enviar", ("click_ui", {"name": "Enviar"})),
    ("lê essa janela", ("read_window", {})),
    ("coloca o chrome e o word lado a lado", ("side_by_side", {"first": "chrome", "second": "word"})),
    ("manda essa janela para a outra tela", ("to_second_screen", {"title": ""})),
    ("salva esse layout como trabalho", ("save_layout", {"name": "trabalho"})),
    ("layout trabalho", ("apply_layout", {"name": "trabalho"})),
    ("desliga o bluetooth", ("radio", {"kind": "bluetooth", "on": False})),
    ("liga o wifi", ("radio", {"kind": "wifi", "on": True})),
    ("ativa o modo escuro", ("dark_mode", {"on": True})),
    ("coloca o som no fone", ("audio_output", {"which": "fone"})),
    ("muda a resolução para 1366x768", ("set_resolution", {"width": 1366, "height": 768})),
    ("apaga a tela", ("screen_off", {})),
    ("instala o VLC", ("install_program", {"name": "vlc"})),
    ("atualiza tudo", ("update_programs", {"name": ""})),
    ("desinstala o vlc", ("uninstall_program", {"name": "vlc"})),
    ("limpa a memória", ("clean_memory", {})),
    ("libera ram", ("clean_memory", {})),
    ("limpa o pc", ("cleanup", {})),
    ("esvazia a lixeira", ("cleanup", {})),
    ("por que tá lento?", ("why_slow", {})),
    ("discord mais alto", ("app_volume", {"app": "discord", "delta": 20})),
    ("volume do spotify em 30", ("app_volume", {"app": "spotify", "percent": 30})),
    ("imprime o primeiro", ("print_file", {"path": "1"})),
    ("cola o que eu copiei antes", ("clipboard_paste", {"index": 2})),
    ("organiza os downloads", ("organize_folder", {"folder": "downloads", "by": "tipo"})),
    ("organiza a pasta downloads por data", ("organize_folder", {"folder": "downloads", "by": "data"})),
    ("desfaz o que você fez", ("undo_file", {})),
    ("salva", ("app_shortcut", {"action": "salva"})),
    ("desfaz", ("app_shortcut", {"action": "desfaz"})),
    ("nova aba", ("app_shortcut", {"action": "nova aba"})),
    ("converte o primeiro para mp3", ("convert_file", {"path": "1", "to": "mp3"})),
    ("observa o que eu faço", ("record_macro", {"name": ""})),
    ("para de gravar", ("stop_macro", {})),
    ("repete a macro planilha", ("play_macro", {"name": "planilha"})),
    ("grava os últimos 30 segundos", ("game_clip", {})),
    ("como tá a saúde do pc", ("health_report", {})),
    ("o que abre com o windows?", ("list_startup", {})),
])
def test_comandos_das_maos(jarvis, frase, esperado):
    assert jarvis.fast_local_router(frase)
    assert jarvis.calls[0] == esperado


@pytest.mark.parametrize("frase", ["organiza minha semana", "toca som de preto 2", "abre o chrome"])
def test_nao_rouba_outros_pedidos(jarvis, frase):
    jarvis.fast_local_router(frase)
    assert not any(c[0] in ("organize_folder", "app_volume", "click_ui") for c in jarvis.calls)
