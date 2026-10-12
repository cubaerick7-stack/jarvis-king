# -*- coding: utf-8 -*-
"""Interface do Jarvis: o círculo do reator se mexendo (a "bolha"), sempre por cima, no canto da tela.
Quando você fala com ele, a bolha vira TELA CHEIA: o reator no meio e as janelas (música, arquivos,
confirmação, lembrete) abrindo por cima dele. Quando ele termina e fica parado, volta a ser bolha.

Usa o pywebview, que desenha com o Edge (WebView2) que já vem no Windows.
Instalar uma vez:  python -m pip install pywebview
Arraste o círculo para mudar de lugar. Passe o mouse em cima para ver o – (minimizar) e o × (fechar).
Dois cliques na bolha abrem a tela cheia; na tela cheia, Esc, – ou dois cliques no reator voltam para a bolha.
Outros jeitos (setx JARVIS_TELA ... e abra o PowerShell de novo):
  cheia   = tela cheia o tempo todo (o – minimiza)
  clique  = só a bolha; a tela cheia só abre com dois cliques
  painel  = o painel antigo (título, respostas escritas, cartões e caixa de pedido)
"""

import json
import os
import threading
from pathlib import Path

HTML = Path(__file__).resolve().parent / "interface" / "reator.html"
WIDTH, HEIGHT = 340, 640  # painel
BUBBLE = 230  # diâmetro do círculo
BACKGROUND = "#02080b"
MARGIN = 16

_window = None
_full = False  # a bolha está aberta em tela cheia agora
_full_lock = threading.Lock()


def mode():
    """ "bolha" (o padrão: abre em tela cheia quando você fala com ele), "cheia" (sempre),
    "clique" (só com dois cliques) ou "painel"."""
    value = os.environ.get("JARVIS_TELA", "").strip().lower()
    if value == "painel":
        return "painel"
    if value in ("cheia", "tela cheia", "sempre"):
        return "cheia"
    if value in ("clique", "bolha fixa", "so bolha", "só bolha"):
        return "clique"
    return "bolha"


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


def _round(window, circle=True):
    """Recorta a janela num círculo (Windows: SetWindowRgn). Fora do círculo não sobra nada:
    nem o quadrado escuro, nem clique roubado da janela de trás. circle=False tira o recorte (tela cheia)."""
    try:
        import ctypes
        from ctypes import wintypes
        u32, gdi = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")  # cópias próprias: os argtypes não vazam
        u32.FindWindowW.restype = wintypes.HWND
        u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        gdi.CreateEllipticRgn.restype = wintypes.HRGN
        gdi.CreateEllipticRgn.argtypes = [ctypes.c_int] * 4
        gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        try:
            hwnd = int(window.native.Handle.ToInt64())
        except Exception:
            hwnd = u32.FindWindowW(None, window.title)
        if hwnd and not circle:
            return bool(u32.SetWindowRgn(hwnd, None, True))
        rect = wintypes.RECT()
        if not hwnd or not u32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        w, h = rect.right - rect.left, rect.bottom - rect.top  # pixels de verdade (já com a escala da tela)
        rgn = gdi.CreateEllipticRgn(0, 0, w + 1, h + 1)
        if not rgn:
            return False
        if not u32.SetWindowRgn(hwnd, rgn, True):
            gdi.DeleteObject(rgn)  # o Windows só fica dono da região quando aceita
            return False
        return True
    except Exception:
        return False


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
        if _full and mode() in ("bolha", "clique"):
            set_full(False)  # a tela cheia que abriu sozinha volta para a bolha
        elif _window is not None:
            _window.minimize()

    def expandir(self):
        if mode() in ("bolha", "clique"):
            set_full(True)

    def recolher(self):
        if mode() in ("bolha", "clique"):
            set_full(False)


def set_full(on):
    """Bolha <-> tela cheia (a página troca o desenho sozinha pelo tamanho da janela)."""
    global _full
    window = _window
    if window is None:
        return False
    with _full_lock:
        if bool(on) == _full:
            return True
        try:
            if on:
                _round(window, circle=False)  # o recorte redondo cortaria a tela cheia
                window.restore()  # se estava minimizada
                window.toggle_fullscreen()
            else:
                window.toggle_fullscreen()  # volta ao tamanho e ao lugar de antes
                _round(window)
        except Exception:
            return False
        _full = bool(on)
        return True


def expand():
    """Ele vai mostrar algo (você falou com ele, um cartão, um lembrete): abre a tela cheia."""
    if mode() == "bolha":
        set_full(True)


def start(worker, on_text=lambda t: None, title="Jarvis"):
    """Abre a janela e roda worker() (o Jarvis) em outra thread. Volta quando a janela fecha."""
    global _window, _full
    import webview
    how = mode()
    bubble = how in ("bolha", "clique", "cheia")
    if bubble:
        x, y, _ = _corner(BUBBLE, BUBBLE)
        width = height = BUBBLE
    else:
        x, y, height = _corner()
        width = WIDTH
    always_full = how == "cheia"
    _full = always_full
    _window = webview.create_window(
        title, url=str(HTML), width=width, height=height, x=x, y=y, js_api=Api(on_text),
        frameless=True, easy_drag=False, resizable=False, background_color=BACKGROUND,
        fullscreen=always_full, on_top=not always_full)  # sempre em tela cheia por cima travaria o PC
    window = _window
    if bubble and not always_full:  # a página vira círculo sozinha quando a janela é quadrada e pequena (CSS)
        window.events.shown += lambda: _full or _round(window)
        window.events.loaded += lambda: _full or _round(window)  # de novo, se o "shown" veio cedo demais
    window.events.loaded += lambda: _js(f"mostraNome({json.dumps(title)})")  # nome em cima e na legenda
    webview.start(worker)
    _window = None
    _full = False


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
    """O pedido que chegou (falado ou digitado): abre a tela cheia e mostra na legenda "Você"."""
    expand()
    _js(f"mostraVoce({json.dumps(text)})")


def speech(text):
    _js(f"mostraFala({json.dumps(text)})")


def card(title, text, ms=7000):
    expand()
    _js(f"cartao({json.dumps(title)}, {json.dumps(text)}, {int(ms)})")
