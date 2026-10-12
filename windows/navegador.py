# -*- coding: utf-8 -*-
"""Navegador do Jarvis: um Edge controlado pelo Playwright.

Ele usa o Edge que já vem no Windows (não baixa navegador nenhum) com um perfil próprio
em G:\\Jarvis\\navegador, então logins (WhatsApp Web, YouTube...) ficam salvos.
Uma aba para cada coisa: a do YouTube (música continua tocando enquanto você pesquisa),
a de pesquisa/sites e a do WhatsApp (não recarrega a cada mensagem).

Instalar uma vez:  python -m pip install playwright
"""

import os
import re
import time
import unicodedata
import urllib.parse
from pathlib import Path

PROFILE = Path(os.environ.get("JARVIS_NAVEGADOR", r"G:\Jarvis\navegador"))
CHANNEL = os.environ.get("JARVIS_NAVEGADOR_CANAL", "msedge")
MAX_TEXT = 6000  # quanto texto de uma página vai para a IA ler
TIMEOUT = 10000  # ms

_pw = None
_ctx = None
_page = None  # a aba usada por último: web_read, web_click, web_fill e web_key agem nela
_tabs = {}  # "midia" (YouTube) | "web" (pesquisa e sites) | "zap" (WhatsApp) -> aba
last_links = []  # [(título, url)] da última pesquisa, para "abre o 2"


def _say(text):
    print(f"Jarvis > {text}")


def available():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def _second_monitor():
    try:
        import ferramentas
        return ferramentas.second_monitor()
    except Exception:
        return None


def _launch():
    global _pw, _ctx
    from playwright.sync_api import sync_playwright
    if _pw is None:
        _pw = sync_playwright().start()
    PROFILE.mkdir(parents=True, exist_ok=True)
    args = ["--start-maximized", "--autoplay-policy=no-user-gesture-required"]
    second = _second_monitor()
    if second:  # o Jarvis fica em tela cheia na principal: o navegador abre na segunda tela
        args.append(f"--window-position={second[0]},{second[1]}")
    try:
        _ctx = _pw.chromium.launch_persistent_context(
            str(PROFILE), channel=CHANNEL, headless=False, no_viewport=True, args=args)
    except Exception as e:
        if any(x in str(e) for x in ("existing browser session", "has been closed", "ProcessSingleton")):
            raise RuntimeError(f"o perfil {PROFILE} já está aberto em outro Edge (outro Jarvis rodando?)") from e
        raise
    return _ctx


def _alive(p):
    """A aba ainda existe? Na API do Playwright o "fechou" só chega durante uma chamada,
    então faz uma ida e volta rápida antes de confiar no is_closed()."""
    if p is None:
        return False
    try:
        p.wait_for_timeout(1)
        return not p.is_closed()
    except Exception:
        return False


def _new_tab():
    global _ctx
    if _ctx is not None:
        try:
            used = [t for t in _tabs.values() if t is not None]
            free = [t for t in _ctx.pages if t not in used and _alive(t)]
            return free[0] if free else _ctx.new_page()
        except Exception:  # o navegador inteiro foi fechado
            try:
                _ctx.close()
            except Exception:
                pass
            _ctx = None
            _tabs.clear()
    ctx = _launch()
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def page(kind="web"):
    """A aba do Jarvis para "midia", "web" ou "zap". Se você fechou a aba ou o navegador, abre de novo."""
    global _page
    p = _tabs.get(kind)
    if not _alive(p):
        p = _new_tab()
        _tabs[kind] = p
    _page = p
    return p


def current():
    """A aba usada por último (para ler, clicar e escrever no que acabou de abrir)."""
    return _page if _alive(_page) else page("web")


def is_open():
    return any(_alive(t) for t in [_page, *_tabs.values()])


def close_tab():
    """Fecha a aba do YouTube do Jarvis (ou a última usada)."""
    p = _tabs.get("midia") if _alive(_tabs.get("midia")) else _page
    if not _alive(p):
        _say("Não tem aba do Jarvis aberta.")
        return False
    p.close()
    _say("Fechei a aba.")
    return True


def _clean(text):
    text = re.sub(r"[ \t\r\f\v]+", " ", text or "")
    return re.sub(r"\n\s*\n+", "\n", text).strip()


# ------------------------- navegar e ler -------------------------

def open_url(url):
    url = str(url).strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    kind = "midia" if "youtube.com/watch" in url else "web"
    p = page(kind)
    try:
        p.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        if "closed" not in str(e):
            raise
        _tabs.pop(kind, None)  # você fechou o navegador no meio: abre de novo e tenta mais uma vez
        p = page(kind)
        p.goto(url, wait_until="domcontentloaded", timeout=30000)
    p.bring_to_front()
    _say(f"Abri {p.title() or url}.")
    return f"Página aberta: {p.title()} ({p.url})"


def search(query):
    """Pesquisa no Google e devolve os resultados numerados (título e endereço)."""
    global last_links
    p = page("web")
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
    if not links:  # Google pediu "não sou um robô" ou mudou a página: tenta o DuckDuckGo
        try:
            p.goto("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(str(query)),
                   wait_until="domcontentloaded", timeout=30000)
            for a in p.locator("a.result__a").all()[:8]:
                title = _clean(a.inner_text())
                href = a.get_attribute("href") or ""
                m = re.search(r"uddg=([^&]+)", href)
                href = urllib.parse.unquote(m.group(1)) if m else href
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
    p = current()
    try:
        text = _clean(p.inner_text("body", timeout=TIMEOUT))
    except Exception:
        text = ""
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + " [...]"
    return f"Página: {p.title()} ({p.url})\n{text}"


def click(target):
    """Clica num link/botão pelo texto, ou abre o resultado N da última pesquisa."""
    global _page
    target = str(target).strip()
    if target.isdigit() and last_links:
        n = int(target)
        if 1 <= n <= len(last_links):
            return open_url(last_links[n - 1][1])
    p = current()
    try:
        before = set(p.context.pages)
    except Exception:
        before = None
    for loc in (p.get_by_role("link", name=target), p.get_by_role("button", name=target), p.get_by_text(target)):
        try:
            loc.first.click(timeout=4000)
        except Exception:
            continue
        try:
            p.wait_for_timeout(800)  # dá tempo de uma aba nova aparecer (link com target=_blank)
            opened = [t for t in p.context.pages if t not in before and not t.is_closed()] if before is not None else []
            if opened:
                p = _page = opened[-1]
            p.wait_for_load_state("domcontentloaded", timeout=TIMEOUT)
        except Exception:
            pass
        _say(f"Cliquei em {target}.")
        return f"Cliquei em {target}. Agora em: {p.title()} ({p.url})"
    _say(f"Não achei '{target}' na página.")
    return False


def fill(field, text, enter=False):
    """Escreve num campo (pelo nome, placeholder ou rótulo); sem nome, no primeiro campo visível."""
    p = current()
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
    current().keyboard.press(str(key))
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


# O YouTube vem trocando o formato das listas; qualquer um destes é o link de um vídeo da busca.
YT_FIRST_VIDEO = ("ytd-video-renderer a#video-title, ytd-search yt-lockup-view-model a[href^='/watch?v='], "
                  "ytd-search a#video-title[href*='/watch?v=']")


def on_youtube():
    p = _tabs.get("midia")
    try:
        return _alive(p) and "youtube.com" in p.url
    except Exception:
        return False


def play_youtube(query):
    """Busca no YouTube na aba de mídia do Jarvis e clica no primeiro vídeo (pula anúncios e shorts)."""
    p = page("midia")
    p.goto("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(str(query)),
           wait_until="domcontentloaded", timeout=30000)
    p.bring_to_front()
    first = p.locator(YT_FIRST_VIDEO).first
    try:
        first.wait_for(timeout=25000)  # na primeira vez, num PC simples, o YouTube demora a montar a lista
        title = first.get_attribute("title") or first.get_attribute("aria-label") or str(query)
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
    p = page("midia")
    p.bring_to_front()
    p.keyboard.press(key)
    _say(f"YouTube: {action}.")
    return True


# ------------------------- WhatsApp -------------------------

WHATSAPP = "https://web.whatsapp.com/"
WA_SEARCH = ['div[contenteditable="true"][data-tab="3"]', '[aria-label*="Pesquisar"][contenteditable="true"]',
             '[aria-label*="Search"][contenteditable="true"]']
WA_COMPOSE = ['#main footer div[contenteditable="true"]', 'footer div[contenteditable="true"]',
              'div[contenteditable="true"][data-tab="10"]']
WA_TITLE = ['#main header span[dir="auto"]', '#main header [title]', '#main header']


def _words(text):
    text = unicodedata.normalize("NFKD", str(text).lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", text)


def same_person(asked, title):
    """ "Ana" bate com "Ana Paula" e "mãe" com "Mãe ❤️", mas "Ana" não bate com "Mariana"."""
    a, t = _words(asked), _words(title)

    def covered(xs, ys):
        return bool(xs) and all(any(y == x or (len(x) >= 3 and y.startswith(x)) for y in ys) for x in xs)

    return covered(a, t) or covered(t, a)


def _chat_title(p):
    for sel in WA_TITLE:
        try:
            loc = p.locator(sel).first
            if loc.is_visible():
                title = loc.get_attribute("title") or _clean(loc.inner_text(timeout=1500)).split("\n")[0]
                if title and title.strip():
                    return title.strip()
        except Exception:
            continue
    return ""


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
    """Manda mensagem pelo WhatsApp Web. Sempre confirma antes de enviar, com o nome da conversa que abriu."""
    contact, message = str(contact).strip(), str(message).strip()
    if not contact or not message:
        _say("Preciso do nome do contato e da mensagem.")
        return False
    p = page("zap")
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
    p.keyboard.press("Escape")  # fecha a conversa anterior: a caixa de texto dela não pode ser usada
    time.sleep(0.5)
    search_box.click()
    p.keyboard.press("Control+A")
    p.keyboard.type(contact)
    time.sleep(1.5)
    p.keyboard.press("Enter")
    compose = _first_visible(p, WA_COMPOSE, 8)
    if compose is None:
        _say(f"Não achei a conversa com {contact}.")
        return False
    title, end = "", time.time() + 5
    while time.time() < end:  # o cabeçalho pode demorar um pouco para trocar de conversa
        title = _chat_title(p)
        if not title or same_person(contact, title):
            break
        time.sleep(0.5)
    if title and not same_person(contact, title):
        _say(f"Abriu a conversa de {title}, não a de {contact}. Não enviei.")
        return False
    if not confirm(f'Mando "{message}" para {title or contact}?'):
        _say("Cancelado, não enviei.")
        return False
    compose.click()
    p.keyboard.type(message)
    p.keyboard.press("Enter")
    _say(f"Mensagem enviada para {title or contact}.")
    return f"Enviado para {title or contact}: {message}"
