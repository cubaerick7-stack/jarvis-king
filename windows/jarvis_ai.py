#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import contextlib
import ctypes
import difflib
import io
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ferramentas as F  # noqa: E402
import navegador as B  # noqa: E402
import voz as V  # noqa: E402
import nuvem as N  # noqa: E402

try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    from ollama import chat
except ImportError:
    chat = None

MODEL = "qwen3:1.7b"
# Mesmas opções em todas as chamadas: mudar num_ctx faz o Ollama recarregar o modelo.
AI_OPTIONS = {"temperature": 0, "num_ctx": 4096, "num_predict": 400}
KEEP_ALIVE = "30m"  # mantém o modelo na RAM entre pedidos
MAX_RESULTS = 20
MAX_SCAN = 400  # quantos achados juntar antes de ordenar
SCREENSHOT_DIR = Path(r"G:\Jarvis\screenshots")
ACTION_LOG = Path(r"G:\Jarvis\logs\acoes.log")
SEARCH_ROOTS = [
    Path(r"G:\\"),
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Documents",
]
PROGRAM_ROOTS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path.home() / "Desktop",
    Path(r"G:\\"),
]
PROGRAM_EXTS = (".lnk", ".exe", ".url")
last_results = []


def normalize(text):
    text = str(text).strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text)


def clean_prefix(text):
    return re.sub(r"^\s*(jarvis|mn|mano)[\s,:-]*", "", text, flags=re.I).strip()


def log_action(name, detail=""):
    """Registra cada ação executada (horário, ação, detalhe). Nunca interrompe o Jarvis."""
    try:
        ACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ACTION_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}\t{name}\t{detail}\n")
    except Exception:
        pass


def need_pyautogui():
    if pyautogui is None:
        raise RuntimeError("Instale pyautogui: python -m pip install pyautogui")


def ordinal_to_number(text):
    clean = normalize(text)
    words = {
        "primeiro": 1, "primeira": 1,
        "segundo": 2, "segunda": 2,
        "terceiro": 3, "terceira": 3,
        "quarto": 4, "quarta": 4,
        "quinto": 5, "quinta": 5,
        "sexto": 6, "sexta": 6,
        "setimo": 7, "setima": 7,
        "oitavo": 8, "oitava": 8,
        "nono": 9, "nona": 9,
        "decimo": 10, "decima": 10,
    }
    m = re.search(r"\b(\d+)\b", clean)
    if m:
        return int(m.group(1))
    for word, number in words.items():
        if re.search(rf"\b{word}\b", clean):
            return number
    if len(last_results) == 1:
        return 1
    return None


# ========================= VOLUME =========================

def _device():
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetSpeakers()


def set_volume(percent):
    percent = max(0, min(100, int(percent)))
    try:
        device = _device()
        try:
            device.volume_percent = percent
        except Exception:
            device.EndpointVolume.SetMasterVolumeLevelScalar(percent / 100.0, None)
        print(f"Jarvis > Volume em {percent}%.")
        return True
    except Exception as e:
        print(f"Jarvis > Erro no volume: {e}")
        return False


def get_volume():
    try:
        device = _device()
        try:
            value = int(round(float(device.volume_percent)))
        except Exception:
            value = int(round(device.EndpointVolume.GetMasterVolumeLevelScalar() * 100))
        print(f"Jarvis > O volume está em {value}%.")
        return value
    except Exception as e:
        print(f"Jarvis > Erro ao ler volume: {e}")
        return None


def mute_audio(mute=True):
    try:
        device = _device()
        device.EndpointVolume.SetMute(1 if mute else 0, None)
        print("Jarvis > Som mutado." if mute else "Jarvis > Som ativado.")
        return True
    except Exception as e:
        print(f"Jarvis > Erro no mudo: {e}")
        return False


def change_volume(delta):
    value = get_volume()
    if value is not None:
        set_volume(value + delta)


# ========================= APPS/SITES =========================

SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "drive": "https://drive.google.com",
    "whatsapp": "https://web.whatsapp.com",
}


def open_target(target):
    original = str(target).strip()
    low = normalize(original)

    aliases = {
        "google chrome": "chrome",
        "explorador de arquivos": "explorer",
        "explorador": "explorer",
        "gerenciador de tarefas": "taskmgr",
        "configuracoes": "settings",
        "bloco de notas": "notepad",
        "bloco de nota": "notepad",
        "notas": "notepad",
        "notepad": "notepad",
        "calculadora": "calc",
    }
    low = aliases.get(low, low)

    if low in FOLDERS:
        return open_folder(low)

    if low in SITES:
        webbrowser.open(SITES[low])
        print(f"Jarvis > Abrindo {low}.")
        return True

    if low == "chrome":
        p = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if os.path.exists(p):
            subprocess.Popen([p])
            print("Jarvis > Abrindo Chrome.")
            return True

    if low == "explorer":
        subprocess.Popen(["explorer.exe"])
        print("Jarvis > Explorador aberto.")
        return True

    if low == "taskmgr":
        subprocess.Popen(["taskmgr.exe"])
        print("Jarvis > Gerenciador de Tarefas aberto.")
        return True

    if low == "settings":
        os.startfile("ms-settings:")
        print("Jarvis > Configurações abertas.")
        return True

    if low == "notepad":
        subprocess.Popen(["notepad.exe"])
        print("Jarvis > Bloco de Notas aberto.")
        return True

    if low == "calc":
        subprocess.Popen(["calc.exe"])
        print("Jarvis > Calculadora aberta.")
        return True

    for program in find_programs(original):
        if launch(program):
            return True

    if len(low.split()) > 4:
        print(f"Jarvis > Não achei um programa chamado \"{original}\".")
        return False

    need_pyautogui()
    pyautogui.press("win")
    time.sleep(0.4)
    pyautogui.write(original, interval=0.025)
    time.sleep(0.7)
    pyautogui.press("enter")
    print(f"Jarvis > Tentando abrir {original}.")
    return True


def launch(path):
    """Abre arquivo/programa a partir da pasta dele (jogos costumam precisar disso).
    Atalho quebrado ou janela cancelada devolve False em vez de travar."""
    path = Path(path)
    try:
        os.startfile(str(path), cwd=str(path.parent))
    except TypeError:
        os.startfile(str(path))
    except OSError as e:
        print(f"Jarvis > Não consegui abrir {path.name} ({e.strerror or e}). Tentando outro...")
        return False
    print(f"Jarvis > Abrindo: {path}")
    return True


def find_program(name):
    found = find_programs(name)
    return found[0] if found else None


def find_programs(name):
    """Atalhos (.lnk/.url) e .exe com nome igual ou bem parecido com o pedido, do melhor pro pior:
    nome exato antes de parecido, atalho antes de .exe, caminho curto antes de longo."""
    wanted = normalize(re.sub(r"\.(exe|lnk|url)$", "", str(name).strip(), flags=re.I))
    if not wanted:
        return []
    matches = []
    for root in PROGRAM_ROOTS:
        if not str(root) or not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                try:
                    if path.suffix.lower() not in PROGRAM_EXTS or not path.is_file():
                        continue
                except OSError:
                    continue
                stem = normalize(path.stem)
                if stem == wanted:
                    closeness = 0
                elif difflib.SequenceMatcher(None, stem, wanted).ratio() >= 0.8:
                    closeness = 1
                else:
                    continue
                matches.append(((closeness, PROGRAM_EXTS.index(path.suffix.lower()), len(str(path))), path))
        except (PermissionError, OSError):
            continue
    return [p for _, p in sorted(matches, key=lambda m: m[0])[:5]]


def search_web(query, site="google"):
    if normalize(site) == "youtube":
        url = "https://www.youtube.com/results?search_query=" + quote_plus(str(query))
    else:
        if B.available():  # na aba do Jarvis, e a IA consegue ler os resultados
            return B.search(query)
        url = "https://www.google.com/search?q=" + quote_plus(str(query))
    if B.available():
        return B.open_url(url)
    webbrowser.open(url)
    print(f"Jarvis > Pesquisa aberta: {query}")
    return True


# ========================= ARQUIVOS =========================

def search_files(query):
    global last_results
    query_original = str(query).strip()
    query_low = normalize(query_original)
    extension = None
    if query_low in {"pdf", "docx", "txt", "jpg", "jpeg", "png", "mp3", "mp4"}:
        extension = "." + query_low

    found, seen, close = [], set(), []
    print(f"Jarvis > Procurando: {query_original}")

    indexed = F.everything_search(query_original, MAX_SCAN, extension)
    if indexed:  # Everything: o PC inteiro em milissegundos
        found = indexed
    roots = [] if indexed else SEARCH_ROOTS  # sem Everything (ou sem achado), varre as pastas de sempre

    for root in roots:
        if not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                try:
                    if extension:
                        matched = path.suffix.lower() == extension and path.is_file()
                    else:
                        name = normalize(path.name)
                        matched = query_low in name
                        if not matched and len(close) < 50 and is_close(query_low, normalize(path.stem)):
                            close.append(str(path))
                    if matched:
                        p = str(path)
                        if p not in seen:
                            seen.add(p)
                            found.append(p)
                        if len(found) >= MAX_SCAN:
                            break
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            pass
        if len(found) >= MAX_SCAN:
            break

    if not found and close:
        print("Jarvis > Não achei esse nome exato; mostrando os parecidos.")
        found = close
    found = rank_results(found, query_low)[:MAX_RESULTS]
    last_results = found

    if not found:
        print("Jarvis > Não encontrei nenhum arquivo.")
        return []

    print("Jarvis > Encontrei:")
    for i, p in enumerate(found, 1):
        print(f"  {i}. {p}")
    return found


def is_close(query, stem):
    """'omorie' ~ 'omori', 'omories' ~ 'omori'."""
    if len(query) < 4 or not stem:
        return False
    m = difflib.SequenceMatcher(None, query, stem)
    return m.real_quick_ratio() >= 0.8 and m.ratio() >= 0.8


def rank_results(paths, query):
    """Nome igual ao pedido primeiro, depois atalhos/programas, depois documentos, depois o resto;
    dentro de cada grupo, os mais perto da raiz."""
    kinds = {".lnk": 0, ".exe": 0, ".url": 0, ".pdf": 1, ".docx": 1, ".doc": 1, ".txt": 1, ".xlsx": 1}

    def key(p):
        path = Path(p)
        return (
            0 if normalize(path.stem) == query else 1,
            1 if path.is_dir() else kinds.get(path.suffix.lower(), 2),
            len(path.parts),
            p.lower(),
        )

    return sorted(paths, key=key)


def open_search_result(index):
    index = int(index)
    if not (1 <= index <= len(last_results)):
        print("Jarvis > Esse resultado não existe.")
        return False
    path = Path(last_results[index - 1])
    if not path.exists():
        print("Jarvis > O arquivo não existe mais.")
        return False
    return launch(path)


def show_search_result(index):
    index = int(index)
    if not (1 <= index <= len(last_results)):
        print("Jarvis > Esse resultado não existe.")
        return False
    path = Path(last_results[index - 1])
    subprocess.Popen(["explorer.exe", "/select,", str(path)])
    print(f"Jarvis > Mostrando no Explorer: {path}")
    return True


def list_folder(path):
    folder = Path(os.path.expandvars(str(path))).expanduser()
    if not folder.exists() or not folder.is_dir():
        print(f"Jarvis > Pasta não encontrada: {folder}")
        return []
    try:
        items = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        print("Jarvis > Sem permissão para essa pasta.")
        return []
    print(f"Jarvis > Conteúdo de {folder}:")
    for item in items[:100]:
        kind = "PASTA" if item.is_dir() else "ARQUIVO"
        print(f"  [{kind}] {item.name}")
    return [str(x) for x in items[:100]]


# ========================= SISTEMA =========================

def system_info():
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    mem = MEMORYSTATUSEX()
    mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
    print(f"Jarvis > RAM total: {mem.ullTotalPhys / (1024**3):.1f} GB")
    print(f"Jarvis > RAM disponível: {mem.ullAvailPhys / (1024**3):.1f} GB")
    print(f"Jarvis > CPU: {platform.processor() or platform.machine()}")
    for drive in ("C:\\", "G:\\"):
        if Path(drive).exists():
            usage = shutil.disk_usage(drive)
            print(f"Jarvis > Disco {drive[0]}: {usage.free/(1024**3):.1f} GB livres de {usage.total/(1024**3):.1f} GB")


def media_control(action):
    action = normalize(action)
    keys = {
        "play": 0xB3, "pause": 0xB3, "play_pause": 0xB3,
        "next": 0xB0, "proxima": 0xB0,
        "previous": 0xB1, "anterior": 0xB1,
        "stop": 0xB2, "parar": 0xB2,
    }
    key = keys.get(action)
    if key is None:
        return False
    ctypes.windll.user32.keybd_event(key, 0, 0, 0)
    ctypes.windll.user32.keybd_event(key, 0, 2, 0)
    print(f"Jarvis > Mídia: {action}.")
    return True


def is_own_console_in_front():
    try:
        k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
        own = k32.GetConsoleWindow()
        return bool(own) and own == u32.GetForegroundWindow()
    except Exception:
        return False


def window_control(action):
    need_pyautogui()
    action = normalize(action)
    if action == "minimizar":
        pyautogui.hotkey("win", "down")
    elif action == "maximizar":
        pyautogui.hotkey("win", "up")
    elif action == "fechar":
        if is_own_console_in_front():
            print("Jarvis > A janela da frente é o próprio Jarvis; não vou fechá-la.")
            return False
        pyautogui.hotkey("alt", "f4")
    elif action == "trocar":
        pyautogui.hotkey("alt", "tab")
    elif action == "desktop":
        pyautogui.hotkey("win", "d")
    elif action == "menu":
        pyautogui.press("win")
    else:
        return False
    print(f"Jarvis > Ação de janela: {action}.")
    return True


def take_screenshot():
    try:
        import mss
        import mss.tools
    except ImportError:
        print("Jarvis > Instale MSS: python -m pip install mss")
        return False
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    file = SCREENSHOT_DIR / f"print_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.png"
    try:
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[0])
            mss.tools.to_png(shot.rgb, shot.size, output=str(file))
        print(f"Jarvis > Print salvo em: {file}")
        return True
    except Exception as e:
        print(f"Jarvis > Erro no print: {e}")
        return False


# ========================= ROTEADOR LOCAL =========================

ORDINAL = r"(primeir[oa]|segund[oa]|terceir[oa]|quart[oa]|quint[oa]|sext[oa]|setim[oa]|oitav[oa]|non[oa]|decim[oa]|\d+)"


def tool(tool_name, /, **args):
    """Roda uma ferramenta do catálogo pelo nome (usado pelo roteador rápido)."""
    log_action(tool_name, json.dumps(args, ensure_ascii=False))
    return TOOLS_BY_NAME[tool_name]["run"](args)


def act(name, fn, *args):
    log_action(name, " ".join(str(a) for a in args))
    return fn(*args)


COMPOUND = re.compile(
    r"\s(?:e|depois|e depois|e entao|entao|e tambem)\s+(?:me\s+|pra mim\s+)?"
    r"(?:abre|abra|explica|explique|fala|fale|diz|diga|conta|conte|digita|digite|escreve|escreva|"
    r"pesquisa|pesquise|procura|procure|toca|coloca|poe|aumenta|abaixa|fecha|feche|mostra|"
    r"le|leia|resume|resuma|cria|crie|liga|desliga|muta|tira|faz|faca|manda|copia|move|apaga)\b"
)


def number_ref(text):
    """'primeiro' -> '1', 'o 2' -> '2', resto fica como está."""
    text = text.strip()
    if re.fullmatch(rf"(?:o |a )?{ORDINAL}", text):
        return str(ordinal_to_number(text))
    return text


def fast_local_router(user_text):
    text = clean_prefix(user_text)
    clean = normalize(text)

    if small_talk(normalize(user_text)) or small_talk(clean):
        return True

    # pedido com duas partes ("abre o bloco de notas e me explica X") vai inteiro para a IA,
    # que divide em várias ações; o roteador rápido só entende um comando por vez
    if COMPOUND.search(clean):
        return False

    # volume relativo ("aumenta o volume em 10") vem antes do volume exato
    up = re.search(r"\b(aumenta|sobe|aumente|suba)\b.*\b(volume|som)\b", clean)
    down = re.search(r"\b(abaixa|diminui|reduz|abaixe|diminua|reduza)\b.*\b(volume|som)\b", clean)
    if up or down:
        m = re.search(r"\b(\d{1,3})\b", clean)
        step = int(m.group(1)) if m else 10
        act("change_volume", change_volume, step if up else -step)
        return True

    # volume exato / metade
    if "metade" in clean and ("volume" in clean or "som" in clean or "deixa" in clean):
        act("set_volume", set_volume, 50)
        return True

    m = re.search(r"(?:volume|som).{0,20}?\b(\d{1,3})\s*%?", clean)
    if m:
        act("set_volume", set_volume, int(m.group(1)))
        return True

    if any(x in clean for x in ["qual o volume", "quanto ta o volume", "quanto esta o volume", "volume atual"]):
        act("get_volume", get_volume)
        return True

    if re.search(r"\b(desmuta|tira do mudo|ativa o som|liga o som)\b", clean):
        act("mute_audio", mute_audio, False)
        return True

    if any(x in clean for x in ["muta o volume", "muta o som", "mute o volume", "mute o som", "sem som", "silencia o som", "desliga o som"]):
        act("mute_audio", mute_audio, True)
        return True

    # pesquisa web (antes da busca de arquivos, que também começa com "procura"/"busca")
    m = re.match(r"^(?:pesquisa|pesquise|procura|procure|busca|busque)\s+no\s+youtube\s+(.+)$", text, flags=re.I)
    if m:
        act("search_web", search_web, m.group(1), "youtube")
        return True

    m = re.match(r"^(?:procura|procure|busca|busque|pesquisa|pesquise)\s+(?:na internet|no google)\s+(.+)$", text, flags=re.I)
    if m:
        act("search_web", search_web, m.group(1), "google")
        return True

    m = re.match(r"^(?:pesquisa|pesquise)\s+(.+)$", text, flags=re.I)
    if m:
        act("search_web", search_web, m.group(1), "google")
        return True

    # arquivos
    for pattern in [
        r"^(?:procura|procure|busca|busque|encontra|encontre)\s+(?:um\s+|uma\s+|o\s+|a\s+)?(?:arquivo\s+)?(.+)$",
        r"^(?:ache|acha)\s+(?:um\s+|uma\s+|o\s+|a\s+)?(?:arquivo\s+)?(.+)$",
    ]:
        m = re.match(pattern, clean)
        if m:
            query = re.sub(r"\s+(pra mim|para mim)$", "", m.group(1).strip()).strip()
            query = re.sub(r"^(um|uma)\s+", "", query).strip()
            act("search_files", search_files, query)
            return True

    # resultados da última busca: "mostra o segundo na pasta", "onde ele está"
    if last_results and (
        re.search(rf"\bmostra\b.*\b{ORDINAL}\b", clean)
        or any(x in clean for x in ["mostra na pasta", "mostra ele na pasta", "onde ele esta", "onde esta o arquivo"])
    ):
        n = ordinal_to_number(clean)
        if n is None:
            print("Jarvis > Qual resultado?")
        else:
            act("show_search_result", show_search_result, n)
        return True

    # só "2" ou "o segundo" depois de uma busca
    RUN = r"(?:abre|abra|abrir|executa|execute|executar|roda|rode|rodar)"
    if last_results and re.fullmatch(rf"(?:{RUN} )?(?:o |a )?{ORDINAL}(?: {RUN})?", clean):
        act("open_search_result", open_search_result, ordinal_to_number(clean))
        return True

    # "abre o terceiro", "abre o 2", "abre ele"
    if last_results and (
        re.match(rf"^(?:abre|abra|abrir|executa|execute|roda|rode)\s+(?:o|a)\s+{ORDINAL}\b", clean)
        or any(x in clean for x in ["abre ele", "abre o arquivo", "abre esse"])
    ):
        n = ordinal_to_number(clean)
        if n is None:
            print("Jarvis > Qual resultado?")
        else:
            act("open_search_result", open_search_result, n)
        return True

    # ajuda, hora, pastas
    if re.fullmatch(r"(ajuda|help|comandos|lista de comandos)\??", clean) or re.search(
        r"\bo que (voce|vc|tu) (sabe|consegue|pode) fazer\b|\bo que (voce|vc) faz\b", clean
    ):
        act("show_help", show_help)
        return True
    if re.search(r"\b(que horas sao|que hora e|horas agora|que dia e hoje)\b", clean):
        act("tell_time", tell_time)
        return True
    m = re.match(r"^(?:abre|abra|abrir|mostra)\s+(?:a\s+)?(?:pasta|minha pasta|meus|minhas)\s+(?:de\s+|do\s+|da\s+)?(.+)$", clean)
    if m:
        act("open_folder", open_folder, m.group(1).strip())
        return True

    # ---- YouTube: tocar direto e controlar o vídeo aberto
    for pattern, action in [
        (r"\btela cheia\b", "tela cheia"),
        (r"\b(avanca|adianta)\s+(?:o\s+)?(?:video|10 segundos)\b|\bpula 10 segundos\b", "avancar"),
        (r"\b(volta|retrocede)\s+(?:o\s+)?(?:video|10 segundos)\b", "voltar"),
        (r"\b(proximo video|pula esse video|pula o video|outro video)\b", "proximo"),
        (r"\b(liga|ativa|coloca)\s+(?:a\s+)?legenda\b", "legenda"),
    ]:
        if re.search(pattern, clean):
            tool("youtube_control", action=action)
            return True

    m = re.match(r"^(?:toca|toque|tocar|bota|coloca|poe|abre|abra|quero ouvir|quero ver)\s+(?:a\s+|o\s+|uma\s+|um\s+)?"
                 r"(?:musica|video|clipe|cancao)\s+(?:d[aoe]s?\s+)?(.+?)(?:\s+no youtube)?$", clean)
    if m:
        tool("play_youtube", query=m.group(1).strip())
        return True
    m = re.match(r"^(?:toca|toque|tocar)\s+(.+?)(?:\s+no youtube)?$", clean)
    if m:
        tool("play_youtube", query=m.group(1).strip())
        return True
    # ---- ferramentas extras
    m = re.match(r"^(?:abre|abra|abrir|mostra|vai em|vai nas)\s+(?:as\s+)?configurac\w*(?:\s+(?:de|do|da|das|dos)\s+(.+))?$", clean)
    if m:
        tool("open_settings", page=m.group(1) or "")
        return True
    if re.search(r"\bbateria\b", clean):
        tool("battery_status")
        return True
    m = re.search(r"\bbrilho\b.*?\b(\d{1,3})\b", clean)
    if m:
        tool("set_brightness", percent=int(m.group(1)))
        return True
    if re.search(r"\b(cancela|cancelar|cancele)\s+(o\s+)?(desligamento|reinicio)\b|\bnao desliga\b", clean):
        tool("power_action", action="cancelar")
        return True
    m = re.search(r"\b(desliga|desligar|desligue|reinicia|reiniciar|reinicie)\s+(?:o\s+)?(?:pc|computador|notebook)\b"
                  r"(?:.*?\b(\d+)\s*(min|minuto|minutos|h|hora|horas)\b)?", clean)
    if m:
        minutes = int(m.group(2)) * (60 if m.group(3) and m.group(3).startswith("h") else 1) if m.group(2) else 1
        tool("power_action", action="desligar" if m.group(1).startswith("deslig") else "reiniciar", minutes=minutes)
        return True
    if re.search(r"\b(bloqueia|bloquear|bloqueie|trava|travar)\s+(?:o\s+|a\s+)?(pc|computador|notebook|tela)\b", clean):
        tool("power_action", action="bloquear")
        return True
    if re.search(r"\b(suspende|suspender|hiberna|hibernar)\b", clean):
        tool("power_action", action="suspender")
        return True
    m = re.match(r"^(?:fecha|feche|fechar|encerra|encerre|mata)\s+(?:o\s+|a\s+)?(.+?)(?:\s+pra mim)?$", clean)
    if m:
        target = m.group(1).strip()
        if target in {"janela", "essa janela", "esta janela", "isso", "isto"}:
            act("window_control", window_control, "fechar")
        else:
            tool("close_app", name=target)
        return True
    if re.search(r"\b(cancela|cancelar|para|parar)\s+(?:o\s+|os\s+)?(timer|timers|alarme|alarmes|lembrete|lembretes)\b", clean):
        tool("cancel_timers")
        return True
    m = re.search(r"\b(?:me lembra|me lembre|me avisa|me avise|lembra|timer|alarme|cronometro)\b.*?\b(\d+)\s*"
                  r"(seg|segundo|segundos|min|minuto|minutos|h|hora|horas)\b(?:\s+(?:de|pra|para|que)\s+(.+))?", clean)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        minutes = n / 60 if unit.startswith("seg") else n * 60 if unit.startswith("h") else n
        tool("start_timer", minutes=minutes, message=(m.group(3) or "Tempo esgotado!").strip())
        return True
    m = re.search(r"\b(?:clima|previsao do tempo|como (?:esta|ta) o tempo|temperatura|vai chover)\b(?:.*?\b(?:em|de|no|na)\s+(.+?))?\??$", clean)
    if m:
        tool("weather", city=(m.group(1) or "").strip())
        return True
    m = re.match(r"^(?:calcula|calcule|quanto e|quanto da|quanto que e|conta)\s+(.+?)\??$", clean)
    if m and re.search(r"\d", m.group(1)):
        tool("calculate", expression=m.group(1))
        return True
    m = re.match(r"^(?:resume|resuma|resumir|faz um resumo d[oea]|faca um resumo d[oea])\s+(?:o\s+|a\s+)?(?:arquivo\s+)?(.+)$", clean)
    if m:
        tool("summarize_file", path=number_ref(m.group(1)))
        return True
    m = re.match(r"^(?:le|leia|ler)\s+(?:o\s+|a\s+)?(?:arquivo\s+)?(.+)$", clean)
    if m:
        tool("read_file", path=number_ref(m.group(1)))
        return True
    m = re.match(r"^(?:apaga|apague|exclui|exclua|deleta|delete|joga na lixeira|manda pra lixeira)\s+(?:o\s+|a\s+)?(?:arquivo\s+)?(.+)$", clean)
    if m:
        tool("delete_item", path=number_ref(m.group(1)))
        return True
    m = re.match(r"^(?:digita|digite|escreve|escreva)\s+(.+)$", text, flags=re.I)
    if m:
        tool("type_text", text=m.group(1))
        return True
    m = re.match(r"^(?:modo|rotina|ativa o modo|ativar modo|ativa a rotina)\s+(.+)$", clean)
    if m:
        tool("run_routine", name=m.group(1).strip())
        return True
    if re.search(r"\b(quais|lista as|mostra as) rotinas\b", clean):
        tool("list_routines")
        return True
    if re.search(r"\b(meu ip|tem internet|to com internet|tou com internet|estou com internet|wifi conectado|como ta a internet)\b", clean):
        tool("network_info")
        return True
    if re.search(r"\b(o que (?:ta|esta) pesando|(?:pc|computador) (?:ta|esta) lento|processos)\b", clean):
        tool("list_processes")
        return True
    if re.search(r"\b(quais|lista as|mostra as) janelas\b", clean):
        tool("list_windows")
        return True
    if re.search(r"\bo que (eu )?copiei\b|\barea de transferencia\b", clean):
        tool("read_clipboard")
        return True
    m = re.match(r"^(?:vai para o|vai pro|vai para a|vai pra|muda para o|muda pro|foca no|foca na)\s+(.+)$", clean)
    if m:
        tool("focus_window", title=m.group(1).strip())
        return True

    # abrir apps/sites
    m = re.match(r"^(?:abre|abra|abrir|inicia|inicie|executa|execute|roda|rode|joga|jogar)\s+(?:o\s+|a\s+)?(.+?)(?:\s+pra mim|\s+para mim)?$", text, flags=re.I)
    if m:
        act("open_target", open_target, m.group(1).strip(" ."))
        return True

    # mídia
    if re.match(r"^(play|pause|pausa|pausar|continua|continuar|despausa|toca)\b", clean):
        act("media_control", media_control, "play_pause")
        return True
    if any(x in clean for x in ["proxima musica", "proxima faixa", "pula a musica", "pula essa"]):
        act("media_control", media_control, "next")
        return True
    if any(x in clean for x in ["musica anterior", "faixa anterior", "volta a musica"]):
        act("media_control", media_control, "previous")
        return True

    # janelas e sistema
    if "minimiza" in clean:
        act("window_control", window_control, "minimizar")
        return True
    if "maximiza" in clean:
        act("window_control", window_control, "maximizar")
        return True
    if any(x in clean for x in ["mostra o desktop", "area de trabalho"]):
        act("window_control", window_control, "desktop")
        return True
    if any(x in clean for x in ["troca de janela", "outra janela"]):
        act("window_control", window_control, "trocar")
        return True
    if any(x in clean for x in ["quanta ram", "quanto de ram", "espaco no disco", "informacoes do pc"]):
        act("system_info", system_info)
        return True
    if any(x in clean for x in ["tira um print", "tira print", "captura a tela", "faz um print"]):
        act("take_screenshot", take_screenshot)
        return True

    return False


# ========================= IA COMO FALLBACK JSON =========================

# ========================= CATÁLOGO DE FERRAMENTAS =========================
# Fonte única do que o Jarvis sabe fazer: gera o prompt do Qwen, a tela de ajuda
# e a execução das ações. Ferramenta nova = uma entrada nova aqui.

FOLDERS = {
    "downloads": Path.home() / "Downloads",
    "documentos": Path.home() / "Documents",
    "desktop": Path.home() / "Desktop",
    "area de trabalho": Path.home() / "Desktop",
    "imagens": Path.home() / "Pictures",
    "fotos": Path.home() / "Pictures",
    "musicas": Path.home() / "Music",
    "videos": Path.home() / "Videos",
    "prints": SCREENSHOT_DIR,
    "jarvis": Path(r"G:\Jarvis"),
}


def open_folder(name):
    key = normalize(name)
    folder = FOLDERS.get(key) or Path(os.path.expandvars(str(name))).expanduser()
    if not folder.is_dir():
        print(f"Jarvis > Pasta não encontrada: {name}")
        return False
    os.startfile(str(folder))
    print(f"Jarvis > Pasta aberta: {folder}")
    return True


def open_url(url):
    url = str(url).strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    if B.available():
        return B.open_url(url)
    webbrowser.open(url)
    print(f"Jarvis > Abrindo {url}")
    return True


def play_youtube(query):
    """Com o Playwright, clica no vídeo de verdade na aba do Jarvis; sem ele, o jeito antigo."""
    if B.available():
        try:
            return B.play_youtube(query)
        except Exception as e:
            print(f"Jarvis > Navegador do Jarvis falhou ({e}); abrindo do jeito antigo.")
    return F.play_youtube(query)


def youtube_control(action):
    if B.on_youtube():
        return B.youtube_control(action, normalize)
    return F.youtube_control(action)


def tell_time():
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    now = datetime.now()
    print(f"Jarvis > Agora são {now:%H:%M} de {dias[now.weekday()]}, {now:%d/%m/%Y}.")
    return True


def resolve_path(ref):
    """'2' ou 2 = resultado 2 da última busca; 'ele'/'esse' = o primeiro; senão é caminho."""
    text = str(ref).strip()
    if re.fullmatch(r"\d{1,2}", text) and last_results:
        i = int(text)
        if 1 <= i <= len(last_results):
            return Path(last_results[i - 1])
    if normalize(text) in {"", "ele", "ela", "esse", "essa", "isso", "o arquivo"} and last_results:
        return Path(last_results[0])
    n = ordinal_to_number(text) if last_results and re.fullmatch(rf"(?:o |a )?{ORDINAL}", normalize(text)) else None
    if n and 1 <= n <= len(last_results):
        return Path(last_results[n - 1])
    return Path(os.path.expandvars(text)).expanduser()


YES = {"s", "sim", "pode", "confirmo", "y", "yes", "isso", "manda", "envia", "pode mandar", "sim senhor", "claro"}
commands = queue.Queue()  # (origem, texto) vindos do teclado e da voz; um só lugar executa tudo
queue_mode = False  # ligado no main(); nos testes a confirmação usa input() direto
listener = None  # voz.Listener quando a voz está ligada


def confirm(question):
    if not queue_mode:
        try:
            answer = input(f"Jarvis > {question} (s/n) ")
        except (EOFError, KeyboardInterrupt):
            return False
        return normalize(answer).strip(" .!") in YES
    print(f"Jarvis > {question} (s/n)")
    if listener is not None:
        speak(question)
        listener.ask_answer()
    try:
        _, answer = commands.get(timeout=60)
    except queue.Empty:
        return False
    return normalize(answer).strip(" .!") in YES


def summarize_file(ref):
    path = resolve_path(ref)
    text = F.read_file(path, show_chars=0) if path.is_file() else False
    if not text:
        if not path.is_file():
            print(f"Jarvis > Arquivo não encontrado: {path}")
        return False
    print("Jarvis > Resumindo...")
    limit = 60000 if N.available() else 6000  # o Gemini aguenta textos bem maiores
    try:
        summary = think("Resuma o texto em português do Brasil, em até 6 tópicos curtos.", text[:limit],
                        json_mode=False, num_predict=400, temperature=0.2)
    except Exception as e:
        print(f"Jarvis > Não consegui resumir: {e}")
        return False
    print(summary.strip())
    return True


def show_help():
    print("Jarvis > Eu sei fazer isto (fale do seu jeito, são só exemplos):")
    for group in TOOL_GROUPS:
        tools = [t for t in TOOLS if t["group"] == group]
        print(f"\n  {group.upper()}")
        for t in tools:
            print(f"    - {t['desc']}: \"{t['examples'][0]}\"")
    print("\n  Frases que eu não reconheço vão para a IA (Gemini ou Groq), que escolhe as ações acima.")
    return True


TOOL_GROUPS = ["som", "programas e sites", "arquivos e pastas", "ler e resumir", "mídia", "navegador", "janelas e teclado",
               "sistema", "energia", "informação", "rotinas"]

TOOLS = [
    {"name": "set_volume", "args": '{"percent":0-100}', "group": "som",
     "desc": "deixar o volume num valor", "examples": ["coloca o volume em 30", "deixa na metade"],
     "run": lambda a: set_volume(a.get("percent", 50))},
    {"name": "change_volume", "args": '{"delta":-100..100}', "group": "som",
     "desc": "aumentar ou abaixar o volume", "examples": ["aumenta o volume em 10", "abaixa um pouco o som"],
     "run": lambda a: change_volume(int(a.get("delta", 10)))},
    {"name": "get_volume", "args": "{}", "group": "som",
     "desc": "dizer o volume atual", "examples": ["qual o volume"],
     "run": lambda a: get_volume()},
    {"name": "mute_audio", "args": '{"mute":true/false}', "group": "som",
     "desc": "mutar ou desmutar", "examples": ["muta o som", "desmuta"],
     "run": lambda a: mute_audio(a.get("mute", True))},
    {"name": "open_target", "args": '{"target":"nome"}', "group": "programas e sites",
     "desc": "abrir programa, jogo ou site", "examples": ["abre o omori", "abre o chrome", "abre youtube"],
     "run": lambda a: open_target(a.get("target", ""))},
    {"name": "open_url", "args": '{"url":"endereço"}', "group": "programas e sites",
     "desc": "abrir um endereço de site", "examples": ["abre o site g1.globo.com"],
     "run": lambda a: open_url(a.get("url", ""))},
    {"name": "play_youtube", "args": '{"query":"música ou vídeo"}', "group": "mídia",
     "desc": "tocar música/vídeo no YouTube direto (reusa a mesma aba)", "examples": ["toca a música evidências"],
     "run": lambda a: play_youtube(a.get("query", ""))},
    {"name": "youtube_control", "args": '{"action":"pausar|proximo|anterior|tela cheia|avancar|voltar|mudo|legenda"}',
     "group": "mídia", "desc": "controlar o vídeo do YouTube aberto", "examples": ["coloca em tela cheia", "avança o vídeo"],
     "run": lambda a: youtube_control(a.get("action", ""))},
    {"name": "search_web", "args": '{"query":"texto","site":"google|youtube"}', "group": "programas e sites",
     "desc": "pesquisar no Google ou ver resultados do YouTube", "examples": ["pesquisa receita de bolo", "procura no youtube lofi"],
     "run": lambda a: search_web(a.get("query", ""), a.get("site", "google"))},
    {"name": "search_files", "args": '{"query":"nome ou extensão"}', "group": "arquivos e pastas",
     "desc": "procurar arquivo ou pasta em todos os discos do PC", "examples": ["procura o arquivo omori", "procura um pdf"],
     "run": lambda a: search_files(a.get("query", ""))},
    {"name": "open_search_result", "args": '{"index":1}', "group": "arquivos e pastas",
     "desc": "abrir um resultado da última busca", "examples": ["abre o segundo", "2"],
     "run": lambda a: open_search_result(a.get("index", 1))},
    {"name": "show_search_result", "args": '{"index":1}', "group": "arquivos e pastas",
     "desc": "mostrar um resultado no Explorer", "examples": ["mostra o primeiro na pasta"],
     "run": lambda a: show_search_result(a.get("index", 1))},
    {"name": "open_folder", "args": '{"name":"downloads|documentos|desktop|imagens|musicas|videos|prints|jarvis|caminho"}',
     "group": "arquivos e pastas",
     "desc": "abrir uma pasta", "examples": ["abre a pasta downloads"],
     "run": lambda a: open_folder(a.get("name", ""))},
    {"name": "list_folder", "args": '{"path":"caminho"}', "group": "arquivos e pastas",
     "desc": "listar o que tem numa pasta", "examples": ["o que tem em G:\\Jarvis"],
     "run": lambda a: list_folder(a.get("path", ""))},
    {"name": "media_control", "args": '{"action":"play|pause|next|previous|stop"}', "group": "mídia",
     "desc": "tocar, pausar, pular música", "examples": ["pausa a música", "próxima música"],
     "run": lambda a: media_control(a.get("action", ""))},
    {"name": "window_control", "args": '{"action":"minimizar|maximizar|fechar|trocar|desktop|menu"}', "group": "janelas e teclado",
     "desc": "minimizar, maximizar, fechar ou trocar janela", "examples": ["minimiza", "fecha essa janela"],
     "run": lambda a: window_control(a.get("action", ""))},
    {"name": "take_screenshot", "args": "{}", "group": "sistema",
     "desc": "tirar print da tela", "examples": ["tira um print"],
     "run": lambda a: take_screenshot()},
    {"name": "system_info", "args": "{}", "group": "sistema",
     "desc": "mostrar RAM, CPU e espaço em disco", "examples": ["quanta ram tenho"],
     "run": lambda a: system_info()},
    {"name": "tell_time", "args": "{}", "group": "sistema",
     "desc": "dizer hora e data", "examples": ["que horas são"],
     "run": lambda a: tell_time()},
    # ---- sistema
    {"name": "battery_status", "args": "{}", "group": "sistema",
     "desc": "dizer a bateria", "examples": ["quanto de bateria tem"],
     "run": lambda a: F.battery_status()},
    {"name": "list_processes", "args": "{}", "group": "sistema",
     "desc": "mostrar o que está pesando no PC", "examples": ["o que tá pesando o pc"],
     "run": lambda a: F.list_processes()},
    {"name": "close_app", "args": '{"name":"programa"}', "group": "programas e sites",
     "desc": "fechar um programa", "examples": ["fecha o chrome"],
     "run": lambda a: F.close_app(a.get("name", ""))},
    {"name": "open_settings", "args": '{"page":"bluetooth|wifi|tela|som|atualizacao|apps|energia|bateria|..."}',
     "group": "sistema", "desc": "abrir uma tela das Configurações", "examples": ["abre as configurações de bluetooth"],
     "run": lambda a: F.open_settings(a.get("page", ""))},
    {"name": "set_brightness", "args": '{"percent":0-100}', "group": "sistema",
     "desc": "mudar o brilho da tela", "examples": ["brilho em 70"],
     "run": lambda a: F.set_brightness(a.get("percent", 50))},
    {"name": "network_info", "args": "{}", "group": "sistema",
     "desc": "ver IP, Wi-Fi e se tem internet", "examples": ["tô com internet?"],
     "run": lambda a: F.network_info()},
    # ---- energia
    {"name": "power_action", "args": '{"action":"bloquear|suspender|desligar|reiniciar|cancelar","minutes":1}',
     "group": "energia", "desc": "bloquear, suspender, desligar ou reiniciar (com tempo)",
     "examples": ["desliga o pc em 30 minutos", "bloqueia o pc", "cancela o desligamento"],
     "run": lambda a: F.power_action(a.get("action", ""), a.get("minutes", 1))},
    # ---- informação
    {"name": "weather", "args": '{"city":"cidade"}', "group": "informação",
     "desc": "ver o clima de agora", "examples": ["clima em São Paulo"],
     "run": lambda a: F.weather(a.get("city", ""))},
    {"name": "calculate", "args": '{"expression":"conta"}', "group": "informação",
     "desc": "fazer contas", "examples": ["quanto é 15% de 320", "calcula 12 vezes 7"],
     "run": lambda a: F.calculate(a.get("expression", ""))},
    {"name": "start_timer", "args": '{"minutes":5,"message":"texto"}', "group": "informação",
     "desc": "timer e lembrete", "examples": ["me lembra em 10 minutos de tirar o bolo"],
     "run": lambda a: F.start_timer(a.get("minutes", 5), a.get("message", "Tempo esgotado!"))},
    {"name": "cancel_timers", "args": "{}", "group": "informação",
     "desc": "cancelar os timers", "examples": ["cancela os timers"],
     "run": lambda a: F.cancel_timers()},
    # ---- arquivos
    {"name": "read_file", "args": '{"path":"caminho ou número do resultado"}', "group": "ler e resumir",
     "desc": "ler TXT, PDF ou DOCX", "examples": ["lê o primeiro", "lê o arquivo 2"],
     "run": lambda a: F.read_file(resolve_path(a.get("path", "1")))},
    {"name": "summarize_file", "args": '{"path":"caminho ou número do resultado"}', "group": "ler e resumir",
     "desc": "resumir um documento com a IA", "examples": ["resume o primeiro"],
     "run": lambda a: summarize_file(a.get("path", "1"))},
    {"name": "file_info", "args": '{"path":"caminho ou número"}', "group": "arquivos e pastas",
     "desc": "tamanho e data de um arquivo", "examples": ["qual o tamanho do primeiro"],
     "run": lambda a: F.file_info(resolve_path(a.get("path", "1")))},
    {"name": "create_folder", "args": '{"path":"caminho"}', "group": "arquivos e pastas",
     "desc": "criar pasta", "examples": ["cria a pasta G:\\Jarvis\\projetos"],
     "run": lambda a: F.create_folder(a.get("path", ""))},
    {"name": "copy_item", "args": '{"src":"caminho ou número","dest":"pasta"}', "group": "arquivos e pastas",
     "desc": "copiar arquivo ou pasta", "examples": ["copia o primeiro para G:\\backup"],
     "run": lambda a: F.copy_item(resolve_path(a.get("src", "1")), a.get("dest", ""))},
    {"name": "move_item", "args": '{"src":"caminho ou número","dest":"pasta"}', "group": "arquivos e pastas",
     "desc": "mover arquivo ou pasta", "examples": ["move o segundo para documentos"],
     "run": lambda a: F.move_item(resolve_path(a.get("src", "1")), FOLDERS.get(normalize(a.get("dest", "")), a.get("dest", "")))},
    {"name": "rename_item", "args": '{"src":"caminho ou número","new_name":"novo nome"}', "group": "arquivos e pastas",
     "desc": "renomear", "examples": ["renomeia o primeiro para contrato final"],
     "run": lambda a: F.rename_item(resolve_path(a.get("src", "1")), a.get("new_name", ""))},
    {"name": "delete_item", "args": '{"path":"caminho ou número"}', "group": "arquivos e pastas",
     "desc": "mandar para a Lixeira (sempre pergunta antes)", "examples": ["apaga o terceiro"],
     "run": lambda a: F.send_to_recycle_bin(resolve_path(a.get("path", "")), confirm)},
    # ---- teclado e janelas
    {"name": "type_text", "args": '{"text":"texto"}', "group": "janelas e teclado",
     "desc": "digitar um texto no programa da frente", "examples": ["digita bom dia a todos"],
     "run": lambda a: F.type_text(a.get("text", ""))},
    {"name": "press_keys", "args": '{"keys":"ctrl+c"}', "group": "janelas e teclado",
     "desc": "apertar teclas e atalhos", "examples": ["aperta ctrl+s"],
     "run": lambda a: F.press_keys(a.get("keys", ""))},
    {"name": "read_clipboard", "args": "{}", "group": "janelas e teclado",
     "desc": "mostrar o que está copiado", "examples": ["o que eu copiei"],
     "run": lambda a: F.read_clipboard()},
    {"name": "focus_window", "args": '{"title":"parte do título"}', "group": "janelas e teclado",
     "desc": "trazer uma janela para a frente", "examples": ["vai para o chrome"],
     "run": lambda a: F.focus_window(a.get("title", ""))},
    {"name": "list_windows", "args": "{}", "group": "janelas e teclado",
     "desc": "listar janelas abertas", "examples": ["quais janelas estão abertas"],
     "run": lambda a: F.list_windows()},
    # ---- navegador do Jarvis (a IA vê o resultado e decide o próximo passo)
    {"name": "web_search", "args": '{"query":"texto"}', "group": "navegador",
     "desc": "pesquisar no Google e LER os resultados (para escolher, comparar, responder)",
     "examples": ["pesquisa a melhor receita de bolo de cenoura"],
     "run": lambda a: B.search(a.get("query", ""))},
    {"name": "web_read", "args": "{}", "group": "navegador",
     "desc": "ler o texto da página aberta no navegador do Jarvis", "examples": ["lê essa página"],
     "run": lambda a: B.read_page()},
    {"name": "web_click", "args": '{"target":"texto do link/botão ou número do resultado"}', "group": "navegador",
     "desc": "clicar num link/botão ou abrir o resultado N da pesquisa", "examples": ["abre o segundo resultado"],
     "run": lambda a: B.click(a.get("target", ""))},
    {"name": "web_fill", "args": '{"field":"nome do campo (ou vazio)","text":"texto","enter":true}', "group": "navegador",
     "desc": "escrever num campo da página", "examples": ["escreve meu email no campo de login"],
     "run": lambda a: B.fill(a.get("field", ""), a.get("text", ""), bool(a.get("enter")))},
    {"name": "web_key", "args": '{"key":"Enter|Escape|PageDown|..."}', "group": "navegador",
     "desc": "apertar uma tecla na página", "examples": ["desce a página"],
     "run": lambda a: B.press(a.get("key", "Enter"))},
    {"name": "whatsapp_send", "args": '{"contact":"nome","message":"texto"}', "group": "navegador",
     "desc": "mandar mensagem no WhatsApp Web (pede confirmação)", "examples": ["manda oi pra mãe no zap"],
     "run": lambda a: B.whatsapp_send(a.get("contact", ""), a.get("message", ""), confirm)},
    # ---- rotinas
    {"name": "run_routine", "args": '{"name":"estudo|relaxar|foco|..."}', "group": "rotinas",
     "desc": "rodar uma rotina com vários passos", "examples": ["modo estudo"],
     "run": lambda a: F.run_routine(a.get("name", ""), execute_ai_action)},
    {"name": "list_routines", "args": "{}", "group": "rotinas",
     "desc": "listar as rotinas", "examples": ["quais rotinas tem"],
     "run": lambda a: F.list_routines()},
    {"name": "show_help", "args": "{}", "group": "sistema",
     "desc": "mostrar tudo o que eu sei fazer", "examples": ["o que você sabe fazer"],
     "run": lambda a: show_help()},
]
TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}

AI_EXAMPLES = [
    ("põe o som no talo", '{"actions":[{"name":"set_volume","args":{"percent":100}}],"reply":"Volume no máximo."}'),
    ("tá muito alto", '{"actions":[{"name":"change_volume","args":{"delta":-20}}],"reply":"Abaixei."}'),
    ("quero jogar omori", '{"actions":[{"name":"open_target","args":{"target":"omori"}}],"reply":"Abrindo o Omori."}'),
    ("bota uma música lofi pra mim", '{"actions":[{"name":"play_youtube","args":{"query":"lofi"}}],"reply":"Tocando lofi."}'),
    ("coloca o volume em 70 e abre a música evidências no youtube", '{"actions":[{"name":"set_volume","args":{"percent":70}},{"name":"play_youtube","args":{"query":"evidências"}}],"reply":"Volume 70 e tocando Evidências."}'),
    ("pula esse vídeo", '{"actions":[{"name":"youtube_control","args":{"action":"proximo"}}],"reply":"Próximo."}'),
    ("cadê aquele pdf do FO 1102", '{"actions":[{"name":"search_files","args":{"query":"FO 1102"}}],"reply":"Procurando."}'),
    ("me mostra meus downloads", '{"actions":[{"name":"open_folder","args":{"name":"downloads"}}],"reply":"Abrindo Downloads."}'),
    ("modo estudo", '{"actions":[{"name":"run_routine","args":{"name":"estudo"}}],"reply":"Modo estudo ativado."}'),
    ("abre o bloco de notas e escreve lista de compras", '{"actions":[{"name":"open_target","args":{"target":"notepad"}},{"name":"type_text","args":{"text":"lista de compras"}}],"reply":"Feito."}'),
    ("vai chover hoje em recife?", '{"actions":[{"name":"weather","args":{"city":"Recife"}}],"reply":"Olha o clima em Recife."}'),
    ("o pc tá lento", '{"actions":[{"name":"list_processes","args":{}},{"name":"system_info","args":{}}],"reply":"Esses são os programas que mais pesam."}'),
    ("joga esse arquivo na lixeira", '{"actions":[{"name":"delete_item","args":{"path":"1"}}],"reply":"Vou pedir confirmação."}'),
    ("faz um resumo do segundo", '{"actions":[{"name":"summarize_file","args":{"path":"2"}}],"reply":"Resumindo."}'),
    ("abre o bloco de notas e me explica quem foi Tiradentes", '{"actions":[{"name":"open_target","args":{"target":"notepad"}},{"name":"type_text","args":{"text":"Tiradentes (Joaquim José da Silva Xavier) foi um dos líderes da Inconfidência Mineira, movimento contra o domínio português em 1789. Foi enforcado em 1792 e hoje é considerado herói nacional."}}],"reply":"Escrevi no Bloco de Notas."}'),
    ("escolhe a melhor receita de bolo de cenoura", '{"actions":[{"name":"web_search","args":{"query":"melhor receita bolo de cenoura"}}],"reply":"Pesquisando receitas.","continue":true}'),
    ("(depois de ver os resultados) 1. Bolo de cenoura fofinho - tudogostoso... 2. ...", '{"actions":[{"name":"web_click","args":{"target":"1"}},{"name":"web_read","args":{}}],"reply":"Vou ler a mais bem avaliada.","continue":true}'),
    ("manda pra Ana que eu chego às 8", '{"actions":[{"name":"whatsapp_send","args":{"contact":"Ana","message":"Chego às 8"}}],"reply":"Pronto."}'),
    ("me explica o que é fotossíntese", '{"actions":[],"reply":"É o processo em que as plantas usam luz, água e gás carbônico para produzir açúcar e liberar oxigênio."}'),
    ("oi jarvis, tudo bem?", '{"actions":[],"reply":"Tudo certo! Diga o que precisa."}'),
    ("faz um bolo pra mim", '{"actions":[],"reply":"Isso eu não consigo fazer. Diga \\"o que você sabe fazer\\" para ver a lista."}'),
]


def build_ai_prompt():
    tools = "\n".join(f"{t['name']} {t['args']} - {t['desc']}" for t in TOOLS)
    examples = "\n".join(f"Usuário: {u}\nJSON: {j}" for u, j in AI_EXAMPLES)
    return f"""Você é o JARVIS, assistente do Windows do usuário. Fala português do Brasil como um mordomo
calmo, educado e um pouco espirituoso, chamando o usuário de "senhor". Curto e direto: suas respostas são faladas em voz alta.
Responda SOMENTE JSON válido, sem explicações, neste formato:
{{"actions":[{{"name":"acao","args":{{}}}}],"reply":"frase curta","continue":false}}

Ferramentas disponíveis (use só estas, com estes nomes):
{tools}

Regras:
- abrir, executar, rodar ou jogar um programa/jogo = open_target com o nome do programa
- um número sozinho ("2") depois de uma busca = open_search_result com esse índice
- "ele", "esse", "o primeiro" se referem aos resultados da última busca
- system_info só quando pedirem RAM, CPU ou disco
- pode usar várias ações em sequência
- conversa ou pergunta de conhecimento: actions vazio e a resposta (curta, até 3 frases) em reply
- se pedir para abrir um programa E escrever/explicar algo, abra e use type_text com o texto
- tocar/ouvir/abrir uma música ou vídeo = play_youtube (toca direto); search_web youtube só se pedir para ver a lista
- pausar, pular, tela cheia, avançar no vídeo aberto = youtube_control
- MODO CICLO: se precisar VER o resultado antes de decidir (pesquisar na web, ler página, procurar arquivo,
  escolher entre opções), faça essa ação e coloque "continue":true. Você recebe o resultado e decide o
  próximo passo. Quando terminar, "continue":false e a resposta final em reply (até 5 frases)
- pesquisar para escolher/comparar/responder = web_search, depois web_click no melhor e web_read
- mandar mensagem no WhatsApp = whatsapp_send (ele mesmo pede confirmação)
- se nenhuma ferramenta serve, diga isso em reply; nunca finja que fez

Exemplos:
{examples}
"""


AI_PROMPT = build_ai_prompt()


def execute_ai_action(name, args):
    tool = TOOLS_BY_NAME.get(name)
    if not tool:
        print(f"Jarvis > Ação desconhecida: {name}")
        return False
    log_action(f"ia:{name}", json.dumps(args, ensure_ascii=False))
    try:
        return tool["run"](args)
    except Exception as e:
        print(f"Jarvis > Erro em {name}: {e}")
        return False


def active_window_title():
    try:
        u32 = ctypes.windll.user32
        hwnd = u32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


def ai_context():
    parts = [f"Agora: {datetime.now():%d/%m/%Y %H:%M}"]
    title = active_window_title()
    if title:
        parts.append(f"Janela ativa: {title}")
    if last_results:
        lines = "\n".join(f"{i}. {Path(p).name}" for i, p in enumerate(last_results[:10], 1))
        parts.append(f"Resultados da última busca:\n{lines}")
    return "\n".join(parts) + "\n\nPedido: "


OPENS_WINDOW = {"open_target", "open_url", "open_folder", "open_search_result", "focus_window", "open_settings"}


def ask_local(system, user, json_mode=True, num_predict=None, temperature=None):
    if chat is None:
        raise RuntimeError("Ollama não instalado (python -m pip install ollama)")
    options = dict(AI_OPTIONS)
    if num_predict:
        options["num_predict"] = num_predict
    if temperature is not None:
        options["temperature"] = temperature
    response = chat(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        format="json" if json_mode else "",
        think=False,
        stream=False,
        keep_alive=KEEP_ALIVE,
        options=options,
    )
    return (response.message.content or "").strip()


def ask_cloud(system, user, json_mode=True, num_predict=None, temperature=None):
    return N.generate(system, user, json_mode=json_mode, temperature=temperature or 0.0,
                      max_tokens=max(2048, num_predict or 0))


def ask_groq(system, user, json_mode=True, num_predict=None, temperature=None):
    return N.groq_generate(system, user, json_mode=json_mode, temperature=temperature or 0.0,
                           max_tokens=max(2048, num_predict or 0))


def local_enabled():
    """O Jarvis é só online; o Qwen local só entra com  setx JARVIS_LOCAL 1."""
    return os.environ.get("JARVIS_LOCAL", "").strip() == "1"


def ai_backends():
    """Ordem de quem pensa: Gemini, depois Groq (e o Qwen só se JARVIS_LOCAL=1)."""
    order = []
    if N.available():
        order.append(("Gemini", ask_cloud))
    if N.groq_available():
        order.append(("Groq", ask_groq))
    if local_enabled():
        order.append(("Qwen", ask_local))
    return order


def think(system, user, **kw):
    """Pergunta para a primeira IA disponível; se falhar, tenta a próxima."""
    errors = []
    for name, fn in ai_backends():
        try:
            text = fn(system, user, **kw)
            if text:
                if errors:
                    print(f"Jarvis > ({'; '.join(errors)}; respondi com o {name})")
                return text
        except Exception as e:
            errors.append(f"{name} falhou: {e}")
    raise RuntimeError("; ".join(errors) or "nenhuma IA configurada (setx GEMINI_API_KEY ou GROQ_API_KEY)")


def parse_json(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    return json.loads(raw)


MAX_STEPS = 6  # teto do modo ciclo, para não gastar o limite grátis da nuvem
MAX_SEEN = 2500  # quanto do resultado de cada ação volta para a IA


class _Tee(io.StringIO):
    """Mostra na tela e guarda o que a ferramenta escreveu, para a IA ver o resultado."""

    def __init__(self, screen):
        super().__init__()
        self.screen = screen

    def write(self, text):
        self.screen.write(text)
        return super().write(text)


def run_actions(actions):
    """Executa as ações; devolve as que falharam e o que cada uma mostrou."""
    failed, seen = [], []
    for i, action in enumerate(actions):
        name = action.get("name", "")
        args = action.get("args", {}) or {}
        tee = _Tee(sys.stdout)
        with contextlib.redirect_stdout(tee):
            result = execute_ai_action(name, args)
        if result is False:
            failed.append(name)
        elif name in OPENS_WINDOW and i + 1 < len(actions):
            time.sleep(1.5)  # espera a janela abrir antes de digitar/clicar nela
        shown = tee.getvalue().strip()
        if isinstance(result, str) and result not in shown:
            shown = (shown + "\n" + result).strip()
        status = "FALHOU" if result is False else "ok"
        seen.append(f"- {name} {json.dumps(args, ensure_ascii=False)} -> {status}\n{shown[:MAX_SEEN]}")
    return failed, seen


def ask_ai_router(user_text):
    """Modo ciclo: a IA age, vê o resultado e decide o próximo passo, até terminar."""
    history = []
    for step in range(MAX_STEPS):
        prompt = ai_context() + user_text
        if history:
            prompt += ("\n\nO que você já fez neste pedido e o resultado de cada ação:\n"
                       + "\n".join(history) + "\n\nDecida o próximo passo ou termine.")
        try:
            data = parse_json(think(AI_PROMPT, prompt))
        except Exception as e:
            print(f"Jarvis > Não consegui falar com a IA: {e}")
            return False

        actions = data.get("actions", []) or []
        failed, seen = run_actions(actions)
        history += seen
        reply = str(data.get("reply", "")).strip()
        if data.get("continue") and actions and step + 1 < MAX_STEPS:
            if reply:
                print(f"Jarvis > {reply}")
            continue
        if failed and not data.get("continue"):
            print(f"Jarvis > Não deu certo: {', '.join(failed)}.")
        elif reply:
            print(f"Jarvis > {reply}")
        return True
    return True


def warm_up_ai():
    """Carrega o Qwen e já processa o prompt do catálogo em segundo plano.
    O Ollama guarda esse começo em cache, então os pedidos seguintes só processam a frase nova.
    Com a nuvem na frente, o Qwen fica quieto (sem gastar CPU) até ser preciso."""
    backends = ai_backends()
    if chat is None or not backends or backends[0][0] != "Qwen":
        return
    try:
        chat(
            model=MODEL,
            messages=[{"role": "system", "content": AI_PROMPT}, {"role": "user", "content": "oi"}],
            format="json",
            think=False,
            stream=False,
            keep_alive=KEEP_ALIVE,
            options={**AI_OPTIONS, "num_predict": 1},
        )
    except Exception:
        pass


SMALL_TALK = [
    (r"^(oi|ola|opa|eai|e ai|fala|salve|bom dia|boa tarde|boa noite|hey)( jarvis)?[!. ]*$", "Oi! Diga o que precisa."),
    (r"^(oi |ola |e ai |fala )?(jarvis,? )?(tudo bem|tudo certo|como (voce|vc) esta|beleza)( jarvis)?\??$", "Tudo certo por aqui! Em que posso ajudar?"),
    (r"^(obrigad[oa]|valeu|vlw|brigad[oa]|show|top|massa|perfeito)( jarvis)?[!. ]*$", "Tamo junto!"),
    (r"^(jarvis,? )?(quem e voce|quem e vc|qual (e )?(o )?seu nome)\??$", "Sou o Jarvis, seu assistente do Windows. Diga \"o que você sabe fazer\"."),
]


def small_talk(clean):
    for pattern, answer in SMALL_TALK:
        if re.search(pattern, clean):
            print(f"Jarvis > {answer}")
            return True
    return False


def set_state(state):
    """parado | ouvindo | pensando | falando. A interface do reator se liga aqui."""


def speak(text):
    if listener is None:
        return
    try:
        V.say(text, set_state)
    except Exception as e:
        print(f"Jarvis > (não consegui falar: {e})")


def handle(text):
    if fast_local_router(text):
        return
    ask_ai_router(text)


def handle_spoken(text):
    """Executa o pedido falado e responde em voz com a última fala do Jarvis."""
    set_state("pensando")
    tee = _Tee(sys.stdout)
    with contextlib.redirect_stdout(tee):
        handle(text)
    said = [line[len("Jarvis > "):] for line in tee.getvalue().splitlines() if line.startswith("Jarvis > ")]
    said = [x for x in said if not x.startswith("(")]
    if said:
        speak(said[-1])
    else:
        set_state("parado")


def keyboard_reader():
    while True:
        try:
            text = input()
        except (EOFError, KeyboardInterrupt):
            commands.put(("teclado", "sair"))
            return
        commands.put(("teclado", text))


def start_voice():
    global listener
    lacks = V.missing()
    if lacks:
        print("Voz desligada. Falta: " + ", ".join(lacks) + " (veja o LEIA-ME).")
        return
    listener = V.Listener(commands.put, set_state)
    listener.start()
    print('Voz ligada: diga "Jarvis" e faça o pedido depois do bipe.')


def main():
    global queue_mode
    print("")
    print("==============================================")
    print("              J.A.R.V.I.S.")
    print("     comandos rápidos + IA: " + (" -> ".join(n for n, _ in ai_backends()) or "nenhuma (configure a chave)"))
    print("==============================================")
    print("")
    print("Digite o pedido e Enter. 'sair' fecha.")
    threading.Thread(target=warm_up_ai, daemon=True).start()
    if "--sem-voz" not in sys.argv:
        start_voice()
    print("")
    queue_mode = True
    threading.Thread(target=keyboard_reader, daemon=True).start()

    while True:
        try:
            origin, user_text = commands.get(timeout=0.5)  # com timeout o Ctrl+C funciona no Windows
        except queue.Empty:
            continue
        user_text = (user_text or "").strip()
        if not user_text:
            continue
        if origin == "voz":
            print(f"Você (voz) > {user_text}")
        if normalize(user_text) in {"sair", "exit", "quit"}:
            print("Jarvis > Até mais.")
            break
        try:
            if origin == "voz":
                handle_spoken(user_text)
            else:
                handle(user_text)
        except Exception as e:
            print(f"Jarvis > Erro: {e}")
            set_state("parado")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nJarvis encerrado.")
