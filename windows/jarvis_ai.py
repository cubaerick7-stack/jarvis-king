#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import ctypes
import difflib
import json
import os
import platform
import re
import shutil
import subprocess
import time
import unicodedata
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    from ollama import chat
except ImportError:
    chat = None

MODEL = "qwen3:1.7b"
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
        url = "https://www.google.com/search?q=" + quote_plus(str(query))
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

    for root in SEARCH_ROOTS:
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


def act(name, fn, *args):
    log_action(name, " ".join(str(a) for a in args))
    return fn(*args)


def fast_local_router(user_text):
    text = clean_prefix(user_text)
    clean = normalize(text)

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

    if any(x in clean for x in ["desmuta", "tira do mudo", "ativa o som", "liga o som"]):
        act("mute_audio", mute_audio, False)
        return True

    if any(x in clean for x in ["muta o volume", "muta o som", "mute o volume", "mute o som", "sem som", "silencia o som"]):
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
    webbrowser.open(url)
    print(f"Jarvis > Abrindo {url}")
    return True


def tell_time():
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    now = datetime.now()
    print(f"Jarvis > Agora são {now:%H:%M} de {dias[now.weekday()]}, {now:%d/%m/%Y}.")
    return True


def show_help():
    print("Jarvis > Eu sei fazer isto (fale do seu jeito, são só exemplos):")
    for group in TOOL_GROUPS:
        tools = [t for t in TOOLS if t["group"] == group]
        print(f"\n  {group.upper()}")
        for t in tools:
            print(f"    - {t['desc']}: \"{t['examples'][0]}\"")
    print("\n  Frases que eu não reconheço vão para a IA local (Qwen), que escolhe as ações acima.")
    return True


TOOL_GROUPS = ["som", "programas e sites", "arquivos e pastas", "mídia", "janelas", "sistema"]

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
    {"name": "search_web", "args": '{"query":"texto","site":"google|youtube"}', "group": "programas e sites",
     "desc": "pesquisar no Google ou YouTube", "examples": ["pesquisa receita de bolo", "procura no youtube lofi"],
     "run": lambda a: search_web(a.get("query", ""), a.get("site", "google"))},
    {"name": "search_files", "args": '{"query":"nome ou extensão"}', "group": "arquivos e pastas",
     "desc": "procurar arquivo ou pasta no PC", "examples": ["procura o arquivo omori", "procura um pdf"],
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
    {"name": "window_control", "args": '{"action":"minimizar|maximizar|fechar|trocar|desktop|menu"}', "group": "janelas",
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
    {"name": "show_help", "args": "{}", "group": "sistema",
     "desc": "mostrar tudo o que eu sei fazer", "examples": ["o que você sabe fazer"],
     "run": lambda a: show_help()},
]
TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}

AI_EXAMPLES = [
    ("põe o som no talo", '{"actions":[{"name":"set_volume","args":{"percent":100}}],"reply":"Volume no máximo."}'),
    ("tá muito alto", '{"actions":[{"name":"change_volume","args":{"delta":-20}}],"reply":"Abaixei."}'),
    ("quero jogar omori", '{"actions":[{"name":"open_target","args":{"target":"omori"}}],"reply":"Abrindo o Omori."}'),
    ("bota uma música lofi pra mim", '{"actions":[{"name":"search_web","args":{"query":"lofi","site":"youtube"}}],"reply":"Procurando lofi no YouTube."}'),
    ("cadê aquele pdf do FO 1102", '{"actions":[{"name":"search_files","args":{"query":"FO 1102"}}],"reply":"Procurando."}'),
    ("me mostra meus downloads", '{"actions":[{"name":"open_folder","args":{"name":"downloads"}}],"reply":"Abrindo Downloads."}'),
    ("modo estudo", '{"actions":[{"name":"set_volume","args":{"percent":25}},{"name":"open_target","args":{"target":"notepad"}}],"reply":"Modo estudo: volume 25 e bloco de notas."}'),
    ("oi jarvis, tudo bem?", '{"actions":[],"reply":"Tudo certo! Diga o que precisa."}'),
    ("faz um bolo pra mim", '{"actions":[],"reply":"Isso eu não consigo fazer. Diga \\"o que você sabe fazer\\" para ver a lista."}'),
]


def build_ai_prompt():
    tools = "\n".join(f"{t['name']} {t['args']} - {t['desc']}" for t in TOOLS)
    examples = "\n".join(f"Usuário: {u}\nJSON: {j}" for u, j in AI_EXAMPLES)
    return f"""Você é o JARVIS, assistente do Windows do usuário. Fala português do Brasil, curto e direto.
Responda SOMENTE JSON válido, sem explicações, neste formato:
{{"actions":[{{"name":"acao","args":{{}}}}],"reply":"frase curta"}}

Ferramentas disponíveis (use só estas, com estes nomes):
{tools}

Regras:
- abrir, executar, rodar ou jogar um programa/jogo = open_target com o nome do programa
- um número sozinho ("2") depois de uma busca = open_search_result com esse índice
- "ele", "esse", "o primeiro" se referem aos resultados da última busca
- system_info só quando pedirem RAM, CPU ou disco
- pode usar várias ações em sequência
- conversa ou pergunta sem ação: actions vazio e a resposta em reply
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


def ask_ai_router(user_text):
    if chat is None:
        print("Jarvis > Instale ollama: python -m pip install ollama")
        return False

    try:
        response = chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": AI_PROMPT},
                {"role": "user", "content": ai_context() + user_text},
            ],
            format="json",
            think=False,
            stream=False,
            options={"temperature": 0, "num_ctx": 3072, "num_predict": 200},
        )
        raw = (response.message.content or "").strip()
        data = json.loads(raw)

        failed = []
        for action in data.get("actions", []):
            name = action.get("name", "")
            if execute_ai_action(name, action.get("args", {}) or {}) is False:
                failed.append(name)

        reply = str(data.get("reply", "")).strip()
        if failed:
            print(f"Jarvis > Não deu certo: {', '.join(failed)}.")
        elif reply:
            print(f"Jarvis > {reply}")

        return True

    except Exception as e:
        print(f"Jarvis > Erro ao falar com Ollama: {e}")
        return False


def main():
    print("")
    print("==============================================")
    print("              JARVIS LITE V2")
    print("     comandos rápidos + Qwen3:1.7b fallback")
    print("==============================================")
    print("")
    print("Os comandos comuns agora rodam SEM IA.")
    print("Digite 'sair' para fechar.")
    print("")

    while True:
        try:
            user_text = input("Você > ").strip()
        except KeyboardInterrupt:
            print("\nJarvis encerrado.")
            break

        if not user_text:
            continue

        if normalize(user_text) in {"sair", "exit", "quit"}:
            print("Jarvis > Até mais.")
            break

        try:
            if fast_local_router(user_text):
                continue
            ask_ai_router(user_text)
        except Exception as e:
            print(f"Jarvis > Erro: {e}")


if __name__ == "__main__":
    main()
