# -*- coding: utf-8 -*-
"""Interface do Jarvis: painel vertical escuro com o reator, sempre por cima, no canto da tela.

Usa o pywebview, que desenha com o Edge (WebView2) que já vem no Windows.
Instalar uma vez:  python -m pip install pywebview
Arraste pelo título ou pelo reator para mudar de lugar. O × fecha o Jarvis.
"""

import json
from pathlib import Path

HTML = Path(__file__).resolve().parent / "interface" / "reator.html"
WIDTH, HEIGHT = 340, 640
BACKGROUND = "#02080b"
MARGIN = 16
TASKBAR = 48

_window = None


def available():
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        return False


def _corner():
    """Canto inferior direito da tela principal, acima da barra de tarefas (x, y, altura)."""
    try:
        import ctypes
        sw, sh = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
        height = min(HEIGHT, sh - TASKBAR - 2 * MARGIN)  # cabe em telas baixas (768 px)
        return sw - WIDTH - MARGIN, max(0, sh - height - TASKBAR - MARGIN), height
    except Exception:
        return None, None, HEIGHT


class Api:
    """Funções que a página chama (botões e caixa de pedido)."""

    def __init__(self, on_text):
        self._on_text = on_text

    def pedido(self, text):
        self._on_text(str(text))

    def fechar(self):
        self._on_text("sair")

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
        frameless=True, on_top=True, resizable=False, background_color=BACKGROUND)
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


def card(title, text):
    _js(f"cartao({json.dumps(title)}, {json.dumps(text)})")
