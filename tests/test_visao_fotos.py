"""Visão do PC (área de trabalho, discos, o que pode apagar) e fotos pelo PhotoCraft (02/11/2026)."""
import importlib.util
import json
import os
import time
from pathlib import Path

import pytest

import fotos as FO
import visao as VP

ROOT = Path(__file__).resolve().parents[1]


# ------------------------- visão do PC -------------------------

def test_o_que_e_do_sistema_ou_do_senhor():
    assert VP.verdict(r"C:\Windows\System32") == "nunca"
    assert VP.verdict(r"C:\Program Files\Steam") == "nunca"
    assert VP.verdict(r"C:\Users\joao\Documents\faculdade") == "pessoal"
    assert VP.verdict(r"G:\Jarvis\jarvis-king") == "pessoal"
    assert VP.verdict(r"C:\Users\joao\AppData\Local\Temp") == ""


def test_tamanho_da_pasta_para_no_prazo(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.bin").write_bytes(b"1" * 2000)
    (tmp_path / "y.bin").write_bytes(b"1" * 500)
    assert VP.folder_size(tmp_path, time.monotonic() + 5) == (2500, 2, True)
    assert VP.folder_size(tmp_path, time.monotonic() - 1)[2] is False


def test_area_de_trabalho_e_instalador_solto(tmp_path, monkeypatch):
    (tmp_path / "Jogos").mkdir()
    (tmp_path / "setup.exe").write_bytes(b"0" * 10)
    (tmp_path / "Discord.url").write_text("[InternetShortcut]")
    monkeypatch.setattr(VP, "desktops", lambda: [tmp_path])
    items = {name: (kind, note) for name, kind, _, note in VP.desktop_items()}
    assert items["Jogos"] == ("pasta", "")
    assert items["setup.exe"] == ("arquivo", "instalador solto")
    assert items["Discord"][0] == "link"


def test_instalador_velho_vira_sugestao_de_apagar(tmp_path, monkeypatch):
    big = tmp_path / "OllamaSetup.exe"
    with open(big, "wb") as f:
        f.truncate(60 * 1024 * 1024)
    old = time.time() - 60 * 86400
    os.utime(big, (old, old))
    (tmp_path / "foto.jpg").write_bytes(b"1")
    monkeypatch.setattr(VP, "_shell_folder", lambda *a: tmp_path)
    found = VP.cleanable(time.monotonic() + 5)
    assert any("OllamaSetup.exe" in label and level == "voce decide" for label, _, _, level in found)
    assert not any("foto.jpg" in label for label, _, _, _ in found)


def test_resumo_para_a_ia(tmp_path, monkeypatch):
    monkeypatch.setattr(VP, "desktops", lambda: [tmp_path])
    monkeypatch.setattr(VP, "drives", lambda: [("C", 100 * 2**30, 95 * 2**30, 5 * 2**30), ("G", 1000 * 2**30, 10 * 2**30, 990 * 2**30)])
    text = VP.overview(deep=False)
    assert "C: 5,0 GB livres" in text and "QUASE CHEIO" in text
    assert "NUNCA APAGAR" in text
    VP._short.update(t=0.0, text="")
    assert VP.short_context().startswith("PC: discos C:")


# ------------------------- fotos (PhotoCraft) -------------------------

def test_passos_em_varios_formatos():
    assert FO._steps([["image.mode.grayscale", {}], {"cmd": "filter.blur.gaussianBlur", "params": {"radius": 3}},
                      "image.autoTone"]) == [("image.mode.grayscale", {}), ("filter.blur.gaussianBlur", {"radius": 3}),
                                             ("image.autoTone", {})]
    assert FO._steps('[["image.imageSize", {"percent": 50}]]') == [("image.imageSize", {"percent": 50})]


def test_nunca_troca_a_foto_original(tmp_path):
    photo = tmp_path / "praia.jpg"
    photo.write_bytes(b"x")
    assert FO.output_for(photo).name == "praia-editada.jpg"
    (tmp_path / "praia-editada.jpg").write_bytes(b"x")
    assert FO.output_for(photo).name == "praia-editada-2.jpg"
    assert FO.output_for(photo, "praia.jpg").name == "praia-2.jpg"


def test_editar_chama_o_photocraft_cli(tmp_path, monkeypatch):
    photo = tmp_path / "eu.png"
    photo.write_bytes(b"x")
    cli = tmp_path / "photocraft-cli.exe"
    monkeypatch.setattr(FO, "find", lambda name="photocraft-cli.exe": cli)
    seen = {}

    class Done:
        returncode, stdout, stderr = 0, "{}", ""

    def run(args, timeout=0):
        seen["args"] = args
        Path(args[args.index("--out") + 1]).write_bytes(b"ok")
        return Done()
    monkeypatch.setattr(FO, "_run", run)
    out = FO.edit(photo, [["image.mode.grayscale", {}], ["image.adjustments.brightnessContrast", {"brightness": 30}]])
    assert out.endswith("eu-editada.png")
    args = seen["args"]
    assert args[:3] == [str(cli), "run", str(photo)]
    assert args[3:7] == ["--cmd", "image.mode.grayscale", "--params", "{}"]
    assert json.loads(args[args.index("image.adjustments.brightnessContrast") + 2]) == {"brightness": 30}
    assert photo.read_bytes() == b"x"


def test_sem_photocraft_avisa_onde_por(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(FO, "APPS", tmp_path)
    monkeypatch.delenv("BOLHA_PHOTOCRAFT", raising=False)
    assert FO.edit(tmp_path / "x.jpg", ["image.autoTone"]) is False
    assert "G:\\Jarvis\\apps\\photocraft" in capsys.readouterr().out


# ------------------------- apagar vários com uma pergunta -------------------------

@pytest.fixture
def jarvis(monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_ai", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_apagar_varios_pergunta_uma_vez(jarvis, monkeypatch, tmp_path):
    a, b = tmp_path / "a.exe", tmp_path / "b.zip"
    a.write_bytes(b"1" * 10)
    b.write_bytes(b"1" * 10)
    asked, sent = [], []
    monkeypatch.setattr(jarvis, "confirm_danger", lambda q: asked.append(q) or True)
    monkeypatch.setattr(jarvis.F, "send_to_recycle_bin", lambda p, c: sent.append(Path(p).name) or True)
    assert jarvis.delete_paths([str(a), str(b)]) is True
    assert len(asked) == 1 and "a.exe" in asked[0] and "b.zip" in asked[0]
    assert sent == ["a.exe", "b.zip"]


def test_apagar_nunca_mexe_no_sistema(jarvis, monkeypatch):
    monkeypatch.setattr(jarvis, "confirm_danger", lambda q: pytest.fail("não pergunta: nada para apagar"))
    monkeypatch.setattr(jarvis.VP, "verdict", lambda p: "nunca")
    monkeypatch.setattr(Path, "exists", lambda self: True)
    assert jarvis.delete_paths([r"C:\Windows"]) is False


def test_ferramentas_novas_no_catalogo(jarvis):
    names = {t["name"] for t in jarvis.TOOLS}
    assert {"pc_overview", "delete_paths", "photo_edit", "photo_commands", "photo_open"} <= names
    picked = [t["name"] for t in jarvis.select_tools("deixa essa foto preto e branco")]
    assert "photo_edit" in picked
