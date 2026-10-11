# -*- coding: utf-8 -*-
"""Navegador do Jarvis: um Edge controlado pelo Playwright.

Ele usa o Edge que já vem no Windows (não baixa navegador nenhum) com um perfil próprio
em G:\\Jarvis\\navegador, então logins (WhatsApp Web, YouTube...) ficam salvos.
Uma aba só é reaproveitada em todos os pedidos, para não abrir coisa à toa.

Instalar uma vez:  python -m pip install playwright
"""

import os
import re
import time
import urllib.parse
from pathlib import Path

PROFILE = Path(os.environ.get("JARVIS_NAVEGADOR", r"G:\Jarvis\navegador"))
CHANNEL = os.environ.get("JARVIS_NAVEGADOR_CANAL", "msedge")
MAX_TEXT = 6000  # quanto texto de uma página vai para a IA ler
TIMEOUT = 10000  # ms

_pw = None
_ctx = None
_page = None
last_links = []  # [(título, url)] da última pesquisa, para "abre o 2"


def _say(text):
    print(f"Jarvis > {text}")


def available():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def _launch():
    global _pw, _ctx, _page
    from playwright.sync_api import sync_playwright
    if _pw is None:
        _pw = sync_playwright().start()
    PROFILE.mkdir(parents=True, exist_ok=True)
    _ctx = _pw.chromium.launch_persistent_context(
        str(PROFILE), channel=CHANNEL, headless=False, no_viewport=True, args=["--start-maximized"])
    _page = _ctx.pages[0] if _ctx.pages else _ctx.new_page()
    return _page


def page():
    """A aba do Jarvis. Se você fechou a aba ou o navegador, abre de novo."""
    global _page
    if _page is not None:
        try:
            if not _page.is_closed():
                return _page
            alive = [p for p in _ctx.pages if not p.is_closed()]
            _page = alive[-1] if alive else _ctx.new_page()
            return _page
        except Exception:
            pass  # o navegador inteiro foi fechado
    return _launch()


def is_open():
    try:
        return _page is not None and not _page.is_closed()
    except Exception:
        return False


def _clean(text):
    text = re.sub(r"[ \t\r\f\v]+", " ", text or "")
    return re.sub(r"\n\s*\n+", "\n", text).strip()


# ------------------------- navegar e ler -------------------------

def open_url(url):
    url = str(url).strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    p = page()
    p.goto(url, wait_until="domcontentloaded", timeout=30000)
    p.bring_to_front()
    _say(f"Abri {p.title() or url}.")
    return f"Página aberta: {p.title()} ({p.url})"


def search(query):
    """Pesquisa no Google e devolve os resultados numerados (título e endereço)."""
    global last_links
    p = page()
    p.goto("https://www.google.com/search?hl=pt-BR&q=" + urllib.parse.quote_plus(str(query)),
           wait_until="domcontentloaded", timeout=30000)
    p.bring_to_front()
    links = []
    try:
        p.wait_for_selector("a:has(h3)", timeout=TIMEOUT)
        for a in p.locator("a:has(h3)").all()[:8]:
            title = _clean(a.locator("h3").first.inner_text())
            href = a.get_attribute("href") or ""
            if title and href.startswith("http"):
                links.append((title, href))
    except Exception:
        pass
    last_links = links
    if not links:
        _say(f"Pesquisei {query}, mas não consegui ler os resultados.")
        return "Sem resultados legíveis. Use web_read para ver a página."
    lines = "\n".join(f"{i}. {t} - {u}" for i, (t, u) in enumerate(links, 1))
    _say(f"Pesquisei {query}.")
    return "Resultados:\n" + lines


def read_page():
    """Título, endereço e o texto da aba (cortado para caber na IA)."""
    p = page()
    try:
        text = _clean(p.inner_text("body", timeout=TIMEOUT))
    except Exception:
        text = ""
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + " [...]"
    return f"Página: {p.title()} ({p.url})\n{text}"


def click(target):
    """Clica num link/botão pelo texto, ou abre o resultado N da última pesquisa."""
    target = str(target).strip()
    if target.isdigit() and last_links:
        n = int(target)
        if 1 <= n <= len(last_links):
            return open_url(last_links[n - 1][1])
    p = page()
    for loc in (p.get_by_role("link", name=target), p.get_by_role("button", name=target), p.get_by_text(target)):
        try:
            loc.first.click(timeout=4000)
            p.wait_for_load_state("domcontentloaded", timeout=TIMEOUT)
            _say(f"Cliquei em {target}.")
            return f"Cliquei em {target}. Agora em: {p.title()} ({p.url})"
        except Exception:
            continue
    _say(f"Não achei '{target}' na página.")
    return False


def fill(field, text, enter=False):
    """Escreve num campo (pelo nome, placeholder ou rótulo); sem nome, no primeiro campo visível."""
    p = page()
    field = str(field or "").strip()
    if field:
        options = [p.get_by_placeholder(field), p.get_by_label(field), p.get_by_role("textbox", name=field)]
    else:
        options = [p.locator("input:visible, textarea:visible, [contenteditable=true]:visible")]
    for loc in options:
        try:
            box = loc.first
            box.click(timeout=4000)
            box.fill(str(text), timeout=4000)
            if enter:
                p.keyboard.press("Enter")
            return f"Escrevi em {field or 'campo'}: {text}"
        except Exception:
            continue
    _say(f"Não achei o campo {field or 'de texto'}.")
    return False


def press(key):
    page().keyboard.press(str(key))
    return f"Apertei {key}"


# ------------------------- YouTube -------------------------

YOUTUBE_KEYS = {
    "pausar": "k", "pause": "k", "play": "k", "continuar": "k",
    "proximo": "Shift+N", "next": "Shift+N",
    "anterior": "Shift+P", "previous": "Shift+P",
    "tela cheia": "f", "fullscreen": "f",
    "avancar": "l", "voltar": "j",
    "mudo": "m", "mute": "m",
    "legenda": "c",
    "mais rapido": ">", "mais devagar": "<",
}


def on_youtube():
    try:
        return is_open() and "youtube.com" in _page.url
    except Exception:
        return False


def play_youtube(query):
    """Busca no YouTube na aba do Jarvis e clica no primeiro vídeo (pula anúncios e shorts)."""
    p = page()
    p.goto("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(str(query)),
           wait_until="domcontentloaded", timeout=30000)
    p.bring_to_front()
    first = p.locator("ytd-video-renderer a#video-title").first
    try:
        first.wait_for(timeout=TIMEOUT)
        title = first.get_attribute("title") or str(query)
        first.click()
    except Exception:
        _say(f"Abri a busca de {query}, mas não consegui clicar no vídeo.")
        return False
    _say(f"Tocando {title}.")
    return f"Tocando: {title}"


def youtube_control(action, norm=lambda s: s):
    key = YOUTUBE_KEYS.get(norm(action))
    if key is None:
        _say(f"Não sei fazer '{action}' no YouTube.")
        return False
    p = page()
    p.bring_to_front()
    p.keyboard.press(key)
    _say(f"YouTube: {action}.")
    return True


# ------------------------- WhatsApp -------------------------

WHATSAPP = "https://web.whatsapp.com/"
WA_SEARCH = ['div[contenteditable="true"][data-tab="3"]', '[aria-label*="Pesquisar"][contenteditable="true"]',
             '[aria-label*="Search"][contenteditable="true"]']
WA_COMPOSE = ['footer div[contenteditable="true"]', 'div[contenteditable="true"][data-tab="10"]']


def _first_visible(p, selectors, timeout):
    end = time.time() + timeout
    while time.time() < end:
        for sel in selectors:
            loc = p.locator(sel).first
            try:
                if loc.is_visible():
                    return loc
            except Exception:
                pass
        time.sleep(0.5)
    return None


def whatsapp_send(contact, message, confirm):
    """Manda mensagem pelo WhatsApp Web. Sempre confirma antes de enviar."""
    p = page()
    if "web.whatsapp.com" not in p.url:
        p.goto(WHATSAPP, wait_until="domcontentloaded", timeout=30000)
    p.bring_to_front()
    search_box = _first_visible(p, WA_SEARCH, 15)
    if search_box is None:
        _say("Leia o QR code do WhatsApp com o celular (só na primeira vez). Espero 60 segundos.")
        search_box = _first_visible(p, WA_SEARCH, 60)
        if search_box is None:
            _say("O WhatsApp Web não carregou.")
            return False
    search_box.click()
    p.keyboard.press("Control+A")
    p.keyboard.type(str(contact))
    time.sleep(1.5)
    p.keyboard.press("Enter")
    compose = _first_visible(p, WA_COMPOSE, 8)
    if compose is None:
        _say(f"Não achei a conversa com {contact}.")
        return False
    if not confirm(f'Mando "{message}" para {contact}?'):
        _say("Cancelado, não enviei.")
        return False
    compose.click()
    p.keyboard.type(str(message))
    p.keyboard.press("Enter")
    _say(f"Mensagem enviada para {contact}.")
    return f"Enviado para {contact}: {message}"
