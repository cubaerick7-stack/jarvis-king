# -*- coding: utf-8 -*-
"""Interface do Jarvis: TELA CHEIA na tela principal, com o reator no meio. O que você pede aparece em
janelas de vidro por cima dele (música, arquivos, confirmação, lembrete), e o que ele abre (programa,
pasta, navegador) vai para a segunda tela; sem segunda tela, abre por cima dele.

Usa o pywebview, que desenha com o Edge (WebView2) que já vem no Windows.
Instalar uma vez:  python -m pip install pywebview
O – minimiza e o × fecha. Quando você fala com ele, ele volta para a frente.
O painel antigo (título, respostas escritas, cartões e caixa de pedido):  setx JARVIS_TELA painel
"""

import json
import os
import threading
from pathlib import Path

HTML = Path(__file__).resolve().parent / "interface" / "reator.html"
WIDTH, HEIGHT = 340, 640  # painel
BACKGROUND = "#02080b"
MARGIN = 16

_window = None


def mode():
    """ "cheia" (o padrão) ou "painel"."""
    return "painel" if os.environ.get("JARVIS_TELA", "").strip().lower() == "painel" else "cheia"


def available():
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        return False


def _corner(width=WIDTH, want_height=HEIGHT):
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
        height = int(min(want_height, bottom - top - 2 * MARGIN))  # cabe em telas baixas (768 px)
        return int(right - width - MARGIN), int(max(top, bottom - height - MARGIN)), height
    except Exception:
        return None, None, want_height


def _hwnd(window):
    try:
        return int(window.native.Handle.ToInt64())
    except Exception:
        try:
            import ctypes
            return ctypes.windll.user32.FindWindowW(None, window.title)
        except Exception:
            return 0


def _place(where):
    """where="frente": por cima das outras (sem roubar o teclado); "atras": embaixo de todas,
    para o que ele acabou de abrir aparecer por cima dele."""
    if _window is None or mode() != "cheia":
        return False
    try:
        import ctypes
        u32 = ctypes.WinDLL("user32")
        hwnd = _hwnd(_window)
        if not hwnd:
            return False
        flags = 0x0013  # NOSIZE | NOMOVE | NOACTIVATE
        if where == "frente":
            if u32.IsIconic(hwnd):
                u32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE: estava minimizado
            u32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags)  # HWND_TOPMOST e logo depois NOTOPMOST:
            return bool(u32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags))  # sobe sem ficar preso por cima
        return bool(u32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, flags))  # HWND_BOTTOM
    except Exception:
        return False


def front():
    return _place("frente")


def behind():
    return _place("atras")


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


def start(worker, on_text=lambda t: None, title="Jarvis"):
    """Abre a janela e roda worker() (o Jarvis) em outra thread. Volta quando a janela fecha."""
    global _window
    import webview
    full = mode() == "cheia"
    if full:  # começa no canto (0, 0), que é sempre da tela principal, e vira tela cheia ali
        x, y, width, height = 0, 0, WIDTH, HEIGHT
    else:
        x, y, height = _corner()
        width = WIDTH
    _window = webview.create_window(
        title, url=str(HTML), width=width, height=height, x=x, y=y, js_api=Api(on_text),
        frameless=True, easy_drag=False, resizable=False, background_color=BACKGROUND,
        fullscreen=full, on_top=not full)  # em tela cheia, por cima de tudo travaria o PC
    window = _window
    window.events.loaded += lambda: _js(f"mostraNome({json.dumps(title)})")  # nome em cima e na legenda
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


def heard(text):
    """O pedido que chegou (falado ou digitado): o Jarvis vem para a frente com ele na legenda "Você"."""
    front()
    _js(f"mostraVoce({json.dumps(text)})")


def speech(text):
    _js(f"mostraFala({json.dumps(text)})")


def card(title, text, ms=7000):
    _js(f"cartao({json.dumps(title)}, {json.dumps(text)}, {int(ms)})")
