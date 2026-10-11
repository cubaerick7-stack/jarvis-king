# -*- coding: utf-8 -*-
"""Interface do Jarvis: o reator numa janela transparente, sempre por cima, no canto da tela.

Usa o pywebview, que desenha com o Edge (WebView2) que já vem no Windows.
Instalar uma vez:  python -m pip install pywebview
Arraste a janela com o mouse para mudar de lugar. Fechar a janela fecha o Jarvis.
"""

import json
from pathlib import Path

HTML = Path(__file__).resolve().parent / "interface" / "reator.html"
WIDTH, HEIGHT = 340, 560
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
    """Canto inferior direito da tela principal, acima da barra de tarefas."""
    try:
        import ctypes
        sw, sh = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
        return sw - WIDTH - MARGIN, sh - HEIGHT - TASKBAR - MARGIN
    except Exception:
        return None, None


def start(worker):
    """Abre a janela e roda worker() (o Jarvis) em outra thread. Volta quando a janela fecha."""
    global _window
    import webview
    x, y = _corner()
    _window = webview.create_window(
        "J.A.R.V.I.S.", url=str(HTML), width=WIDTH, height=HEIGHT, x=x, y=y,
        frameless=True, on_top=True, transparent=True, easy_drag=True, resizable=False)
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
