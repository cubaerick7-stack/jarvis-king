"""Testes que só rodam no Windows (no CI do GitHub): mexem de verdade no Bloco de Notas pela UI Automation."""
import os
import subprocess
import time

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="só no Windows")


@pytest.fixture
def bloco():
    import pygetwindow
    proc = subprocess.Popen(["notepad.exe"])
    hwnd = None
    for _ in range(50):
        wins = [w for w in pygetwindow.getAllWindows() if "Bloco de Notas" in w.title or "Notepad" in w.title]
        if wins:
            hwnd = wins[0]._hWnd
            break
        time.sleep(0.2)
    if hwnd is None:
        proc.kill()
        pytest.skip("o Bloco de Notas não abriu janela aqui")
    yield hwnd
    subprocess.run(["taskkill", "/F", "/IM", "notepad.exe"], capture_output=True)


def test_le_e_escreve_no_bloco_de_notas_pela_ui_automation(bloco):
    import maos
    edits = maos._elements(bloco, maos.EDITABLE)
    assert edits, "o Bloco de Notas não mostrou o campo de texto"
    value = maos._pattern(edits[0][2], maos.PATTERN_VALUE, "IUIAutomationValuePattern")
    if value is None:  # o Bloco de Notas novo (Windows 11) usa o TextPattern
        pytest.skip("este Bloco de Notas não aceita ValuePattern")
    value.SetValue("Olá do Bolha")
    assert value.CurrentValue == "Olá do Bolha"


def test_acha_menus_do_bloco_de_notas(bloco):
    import maos
    names = [n for n, _, _ in maos._elements(bloco, set(maos.CLICKABLE)) if n]
    assert names, "nenhum botão/menu encontrado"
    assert maos.best_match("arquivo", names) is not None or maos.best_match("file", names) is not None


def test_discos_e_inicializacao():
    import maos
    assert maos.disks()
    assert isinstance(maos.startup_programs(), dict)
