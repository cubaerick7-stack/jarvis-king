# -*- coding: utf-8 -*-
"""Interface do Jarvis: painel vertical escuro com o reator, sempre por cima, no canto da tela.

Usa o pywebview, que desenha com o Edge (WebView2) que já vem no Windows.
Instalar uma vez:  python -m pip install pywebview
Arraste pelo título ou pelo reator para mudar de lugar. O × fecha o Jarvis.
"""

import json
import threading
from pathlib import Path

HTML = Path(__file__).resolve().parent / "interface" / "reator.html"
WIDTH, HEIGHT = 340, 640
BACKGROUND = "#02080b"
MARGIN = 16

_window = None


def available():
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        return False


def _corner():
    """Canto inferior direito da área de trabalho (sem a barra de tarefas): (x, y, altura).
    Em pixels "lógicos", que é o que o pywebview espera: com a tela em 125% ou 150%
    a conta em pixels de verdade jogava a janela para fora da tela."""
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        area = wintypes.RECT()
        u32.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0)  # SPI_GETWORKAREA
        try:
            scale = u32.GetDpiForSystem() / 96  # 96 = 100%; o pyautogui deixa o processo "DPI-aware"
        except AttributeError:
            scale = 1.0
        left, top, right, bottom = (v / scale for v in (area.left, area.top, area.right, area.bottom))
        height = int(min(HEIGHT, bottom - top - 2 * MARGIN))  # cabe em telas baixas (768 px)
        return int(right - WIDTH - MARGIN), int(max(top, bottom - height - MARGIN)), height
    except Exception:
        return None, None, HEIGHT


class Api:
    """Funções que a página chama (botões e caixa de pedido)."""

    def __init__(self, on_text):
        self._on_text = on_text

    def pedido(self, text):
        self._on_text(str(text))

    def fechar(self):
        # fecha na hora, mesmo com o Jarvis ocupado ou esperando um "sim" (o main() encerra o resto)
        threading.Thread(target=close, daemon=True).start()

    def minimizar(self):
        if _window is not None:
            _window.minimize()


def start(worker, on_text=lambda t: None):
    """Abre a janela e roda worker() (o Jarvis) em outra thread. Volta quando a janela fecha."""
    global _window
    import webview
    x, y, height = _corner()
    _window = webview.create_window(
        "J.A.R.V.I.S.", url=str(HTML), width=WIDTH, height=height, x=x, y=y, js_api=Api(on_text),
        frameless=True, easy_drag=False, on_top=True, resizable=False, background_color=BACKGROUND)
    webview.start(worker)
    _window = None


def close():
    if _window is not None:
        try:
            _window.destroy()
        except Exception:
            pass


def _js(code):
    if _window is None:
        return
    try:
        _window.evaluate_js(code)
    except Exception:
        pass  # janela ainda carregando ou já fechada


def state(name):
    _js(f"setEstado({json.dumps(name)})")


def speech(text):
    _js(f"mostraFala({json.dumps(text)})")


def card(title, text, ms=7000):
    _js(f"cartao({json.dumps(title)}, {json.dumps(text)}, {int(ms)})")
