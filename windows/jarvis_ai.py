#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import contextlib
import ctypes
import difflib
import io
import json
import ntpath
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ferramentas as F  # noqa: E402
import memoria as M  # noqa: E402
import navegador as B  # noqa: E402
import ui as U  # noqa: E402
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
ACTION_LOG = Path(os.environ.get("JARVIS_LOG", r"G:\Jarvis\logs\acoes.log"))


def _shell_folder(name, fallback):
    """Pasta de verdade do Windows (com o OneDrive ligado, a Área de Trabalho fica dentro dele)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            return Path(os.path.expandvars(winreg.QueryValueEx(k, name)[0]))
    except (ImportError, OSError):
        return Path.home() / fallback


DESKTOP = _shell_folder("Desktop", "Desktop")
DOCUMENTS = _shell_folder("Personal", "Documents")
DOWNLOADS = _shell_folder("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads")
PICTURES = _shell_folder("My Pictures", "Pictures")
MUSIC = _shell_folder("My Music", "Music")
VIDEOS = _shell_folder("My Video", "Videos")
GAMES_DRIVE = Path("G:\\")
SEARCH_ROOTS = [DESKTOP, DOWNLOADS, DOCUMENTS, GAMES_DRIVE]
PROGRAM_ROOTS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    DESKTOP,
    Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",  # atalhos de jogos "para todos os usuários"
]
EXTRA_PROGRAM_ROOTS = [GAMES_DRIVE]  # jogos soltos no G: (varrido raso, só se o Menu Iniciar não tiver)
SKIP_NAMES = {"$recycle.bin", "system volume information", ".git", "node_modules", "__pycache__", "appdata"}
SKIP_PATHS = {r"g:\jarvis\navegador", r"g:\jarvis\modelos", r"g:\jarvis\tools"}  # milhares de arquivos do Jarvis
PROGRAM_EXTS = (".lnk", ".exe", ".url")
last_results = []
last_kind = None  # "arquivos" ou "web": a que "abre o segundo" se refere


def normalize(text):
    text = str(text).strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text)


# Nome do assistente (voz.py lê o JARVIS_NOME; o padrão é "Bolha"). "jarvis" continua valendo no texto.
NAME = V.NAME
_CALL_NAMES = sorted({"jarvis", NAME.lower(), normalize(NAME)}, key=len, reverse=True)
CALL = "(?:" + "|".join(re.escape(n) for n in _CALL_NAMES) + ")"


def clean_prefix(text):
    """Tira o "Bolha," (ou "Jarvis,", "mn") do começo, mantendo o resto do jeito que veio."""
    return re.sub(rf"^\s*(?:{CALL}|mn|mano)(?!\w)[\s,:-]*", "", text, flags=re.I).strip()


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
    "zap": "https://web.whatsapp.com",
    "whatsapp web": "https://web.whatsapp.com",
    "instagram": "https://www.instagram.com",
    "insta": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "tiktok": "https://www.tiktok.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "netflix": "https://www.netflix.com",
    "chatgpt": "https://chatgpt.com",
    "outlook": "https://outlook.live.com",
    "github": "https://github.com",
    "twitch": "https://www.twitch.tv",
    "mercado livre": "https://www.mercadolivre.com.br",
    "shopee": "https://shopee.com.br",
}


# Esses sites desconfiam de navegador controlado por programa (a verificação do login não carrega):
# abrem no navegador normal do senhor, onde ele já está logado.
OWN_BROWSER_SITES = ("instagram.com", "facebook.com", "tiktok.com", "x.com", "netflix.com")


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

    site = re.sub(r"^(?:o|a)\s+|\s+(?:web|site)$", "", low).strip()
    if low in SITES or site in SITES:
        url = SITES.get(low) or SITES[site]
        if any(d in url for d in OWN_BROWSER_SITES):  # login com verificação: no navegador do senhor
            webbrowser.open(url)
            print(f"Jarvis > Abrindo {site or low} no seu navegador.")
            return True
        return open_url(url)  # o resto abre no navegador do Jarvis

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
        os.startfile("taskmgr.exe")  # pede elevação: o Popen dá WinError 740
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

    app = F.store_app(original)  # apps da Microsoft Store (Câmera, Calendário...) não têm atalho comum
    if app:
        try:
            os.startfile("shell:AppsFolder\\" + app[1])
            print(f"Jarvis > Abrindo {app[0]}.")
            return True
        except OSError:
            pass

    if len(low.split()) > 4:
        print(f"Jarvis > Não achei um programa chamado \"{original}\".")
        return False

    need_pyautogui()
    pyautogui.press("win")
    time.sleep(0.6)
    try:  # colar mantém os acentos ("câmera"); o pyautogui.write pula letras acentuadas
        import pyperclip
        pyperclip.copy(original)
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        pyautogui.write(low, interval=0.025)  # sem acento a busca do Windows acha igual
    time.sleep(0.8)
    pyautogui.press("enter")
    print(f"Jarvis > Tentei abrir {original} pela busca do Windows.")
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


def walk(root, max_depth=None):
    """Arquivos de uma pasta e subpastas, pulando lixeira, .git e as pastas pesadas do próprio Jarvis."""
    root = Path(root)
    base = len(root.parts)
    for folder, dirs, files in os.walk(root, onerror=lambda e: None):
        here = Path(folder)
        if max_depth is not None and len(here.parts) - base >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_NAMES and str(here / d).lower() not in SKIP_PATHS]
        for name in dirs:
            yield here / name
        for name in files:
            yield here / name


def _program_matches(paths, wanted):
    matches = []
    for path in paths:
        path = Path(path)
        if path.suffix.lower() not in PROGRAM_EXTS:
            continue
        stem = normalize(path.stem)
        if stem == wanted:
            closeness = 0
        elif difflib.SequenceMatcher(None, stem, wanted).ratio() >= 0.8:
            closeness = 1
        else:
            continue
        matches.append(((closeness, PROGRAM_EXTS.index(path.suffix.lower()), len(str(path))), path))
    return matches


def find_programs(name):
    """Atalhos (.lnk/.url) e .exe com nome igual ou bem parecido com o pedido, do melhor pro pior:
    nome exato antes de parecido, atalho antes de .exe, caminho curto antes de longo.
    Olha o Menu Iniciar e a Área de Trabalho; o G: só se lá não tiver o nome exato."""
    wanted = normalize(re.sub(r"\.(exe|lnk|url)$", "", str(name).strip(), flags=re.I))
    if not wanted:
        return []
    matches = []
    for root in PROGRAM_ROOTS:
        if str(root) and root.exists():
            matches += _program_matches(walk(root), wanted)
    if not any(key[0] == 0 for key, _ in matches):
        indexed = F.everything_search(f"{wanted} ext:exe;lnk;url", 50)
        if indexed:
            matches += _program_matches(indexed, wanted)
        for root in EXTRA_PROGRAM_ROOTS:  # sem Everything, ou disco que ele não indexa (pendrive, exFAT)
            if (indexed is None or not F.indexes_drive(root)) and root.exists():
                matches += _program_matches(walk(root, max_depth=4), wanted)
    seen, out = set(), []
    for _, path in sorted(matches, key=lambda m: m[0]):
        if str(path).lower() not in seen:
            seen.add(str(path).lower())
            out.append(path)
    return out[:5]


def _browser_failed(e):
    first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    print(f"Jarvis > (navegador do Jarvis falhou: {first[:160]}; usando o navegador padrão)")


def search_web(query, site="google"):
    global last_kind
    youtube = normalize(site) == "youtube"
    if youtube:
        url = "https://www.youtube.com/results?search_query=" + quote_plus(str(query))
    else:
        url = "https://www.google.com/search?q=" + quote_plus(str(query))
        last_kind = "web"
    if B.available():  # na aba do Jarvis, e a IA consegue ler os resultados
        try:
            return B.open_url(url) if youtube else B.search(query)
        except Exception as e:
            _browser_failed(e)
    webbrowser.open(url)
    print(f"Jarvis > Pesquisa aberta: {query}")
    return True


def web_search(query):
    """Pesquisa para a IA ler os resultados (modo ciclo)."""
    global last_kind
    last_kind = "web"
    return B.search(query)


# ========================= ARQUIVOS =========================

def search_files(query):
    global last_results, last_kind
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
    # Sem Everything, varre as pastas de sempre. Se ele respondeu "nada", só procura nomes parecidos
    # nas pastas do usuário (o G: inteiro é lento demais para isso).
    if indexed is None:
        roots = SEARCH_ROOTS
    else:  # o G: só se o Everything não o indexa (pendrive, exFAT): aí o "nada" dele não vale para o G:
        roots = ([] if indexed else [DESKTOP, DOWNLOADS, DOCUMENTS])
        roots += [GAMES_DRIVE] if not F.indexes_drive(GAMES_DRIVE) else []

    for root in roots:
        if not root.exists():
            continue
        try:
            for path in walk(root):
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
    last_kind = "arquivos"

    if not found:
        print("Jarvis > Não encontrei nenhum arquivo.")
        return []

    print(f"Jarvis > Encontrei {len(found)} resultado{'s' if len(found) > 1 else ''}:")
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
    """A janela da frente é o próprio Jarvis (reator, console ou Windows Terminal)?"""
    return F.is_jarvis_window(F.foreground_window())


def window_control(action):
    need_pyautogui()
    action = normalize(action)
    if action in ("minimizar", "maximizar", "fechar"):
        # age direto na janela do usuário (nunca na do Jarvis): atalho de teclado podia cair
        # na tela cheia do Jarvis e fechá-la
        hwnd = F.user_target_window()
        if not hwnd:
            print("Jarvis > Clique na janela que quer mexer e peça de novo; a da frente é a minha.")
            return False
        u32 = ctypes.windll.user32
        if action == "fechar":
            u32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE: igual ao X da janela
        else:
            u32.ShowWindow(hwnd, 6 if action == "minimizar" else 3)  # SW_MINIMIZE / SW_MAXIMIZE
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
    opening(tool_name)
    return TOOLS_BY_NAME[tool_name]["run"](args)


def act(name, fn, *args):
    log_action(name, " ".join(str(a) for a in args))
    opening(name)
    return fn(*args)


# Ações que abrem ou mostram algo fora do Jarvis (programa, pasta, navegador)
SHOWS_OUTSIDE = {"open_target", "open_url", "open_folder", "open_search_result", "show_search_result",
                 "focus_window", "open_settings", "play_youtube", "youtube_control", "search_web",
                 "web_search", "web_click", "whatsapp_send", "spotify_play"}


# Ferramentas cujo resultado vira uma janelinha na tela cheia (título da janela)
INFO_CARDS = {"weather": "Clima", "system_info": "PC", "battery_status": "Bateria", "network_info": "Rede",
              "calculate": "Conta", "what_i_know": "O que sei de você", "history": "Histórico",
              "list_processes": "Programas abertos", "list_windows": "Janelas", "read_clipboard": "Área de transferência",
              "file_info": "Arquivo", "web_read": "Página", "list_routines": "Rotinas", "add_reminder": "Lembrete marcado",
              "start_timer": "Timer", "tell_time": "Hora"}
_ran = []  # ferramentas usadas no pedido atual


def opening(name):
    """Vai abrir algo: com segunda tela, a janela nova vai para lá; sem, o Jarvis sai da frente."""
    _ran.append(name)
    if name not in SHOWS_OUTSIDE:
        return
    try:
        if F.second_monitor():
            F.expect_window()
        else:
            U.behind()
    except Exception:
        pass


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


# "aí" sem acento só depois de vírgula: "abre o Meta AI" não pode perder o nome
POLITE_END = re.compile(r"(?:[\s,]+(?:por favor|pfv|pra mim|para mim)|\s*,\s*ai|\s+aí)\s*[.!?]*$", re.I)
POLITE_START = re.compile(r"^por favor[,\s]+", re.I)


def fast_local_router(user_text):
    full = clean_prefix(user_text)  # do jeito que veio (para "digita ...")
    # por voz chega "abre o Chrome, por favor." / "abre o Spotify aí": o fim atrapalha achar o programa
    text = POLITE_END.sub("", POLITE_START.sub("", full)).strip(" .!?") or full
    clean = normalize(text)

    if small_talk(normalize(user_text)) or small_talk(clean):
        return True

    # memória
    if re.fullmatch(rf"(?:{CALL},? )?o que (?:voce|vc) sabe (?:sobre|de) mim\??", clean):
        act("what_i_know", M.what_i_know)
        return True
    m = re.fullmatch(rf"(?:{CALL},? )?(?:esquece|esqueca|apaga da memoria)\s+(?:que\s+|o\s+|a\s+|sobre\s+)?(.+)", clean)
    if m:
        what = re.sub(r"^(?:meu|minha|meus|minhas)\s+", "", m.group(1)).strip(" .!?")
        if len(what) < 3 or what in {"isso", "isto", "disso", "tudo", "aquilo"}:
            return False  # "esquece isso" = deixa pra lá: a IA decide
        act("forget", M.forget, what)
        return True
    m = re.fullmatch(rf"(?:{CALL},? )?meu nome e\s+(.+)", clean)
    if m:
        name = re.split(r"[,.!?;]| e | mas ", text[-len(m.group(1)):])[0].strip()
        if not name or len(name.split()) > 4:
            return False  # "meu nome é João e eu moro em Recife": a IA separa nome e cidade
        act("set_profile", M.set_profile, "nome", name.title())
        return True

    # Spotify: "toca evidências no spotify", "abre o spotify e toca evidências"
    if "spotify" in clean and re.search(r"\b(?:toca|toque|tocar|bota|coloca|poe|ouvir|pesquisa|pesquise|procura|busca)\b", clean):
        query = re.sub(r"\b(?:abre|abra|abrir|o|a|no|na|pelo|e|toca|toque|tocar|bota|coloca|poe|quero|ouvir|"
                       r"pesquisa|pesquise|procura|busca|musica|spotify)\b", " ", clean)
        query = re.sub(r"\s+", " ", query).strip(" .,!?")
        if query:
            tool("spotify_play", query=query)
            return True
    # pedido com duas partes ("abre o bloco de notas e me explica X") vai inteiro para a IA,
    # que divide em várias ações; o roteador rápido só entende um comando por vez
    if COMPOUND.search(clean):
        return False

    # volume ("procura o volume 2 de harry potter" e "toca som de preto 2" não são volume)
    VOL = r"\b(?:volume|som)\b"
    not_volume = re.match(r"^(?:procura|procure|busca|busque|pesquisa|pesquise|toca|toque|tocar|calcula|calcule|"
                          r"quanto|acha|ache|encontra|encontre|abre|abra)\b", clean)
    up = re.search(rf"\b(aumenta|sobe|aumente|suba)\b.*{VOL}", clean)
    down = re.search(rf"\b(abaixa|diminui|reduz|abaixe|diminua|reduza)\b.*{VOL}", clean)
    if (up or down) and not not_volume:
        to = re.search(r"\b(?:pra|para|ate)\s+(\d{1,3})\b", clean)
        if to:  # "aumenta o volume pra 80" = deixa em 80
            act("set_volume", set_volume, int(to.group(1)))
            return True
        m = re.search(r"\b(\d{1,3})\b", clean)  # "aumenta o volume em 10" = mais 10
        step = int(m.group(1)) if m else 10
        act("change_volume", change_volume, step if up else -step)
        return True

    if "metade" in clean and "brilho" not in clean and (re.search(VOL, clean) or re.search(r"\bdeixa\b", clean)):
        act("set_volume", set_volume, 50)
        return True

    m = None if not_volume else re.search(rf"{VOL}\D{{0,20}}?\b(\d{{1,3}})\b", clean)
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

    # "abre o segundo (resultado)" logo depois de uma pesquisa na web: clica no link
    RUN = r"(?:abre|abra|abrir|executa|execute|executar|roda|rode|rodar|clica|clique|entra)"
    RESULT = r"(?: resultado| link| site| da lista)?"
    picks_result = (re.fullmatch(rf"(?:{RUN} )?(?:n?o |n?a )?{ORDINAL}{RESULT}(?: {RUN})?", clean)
                    or re.match(rf"^{RUN}\s+(?:n?o|n?a)\s+{ORDINAL}\b{RESULT}$", clean))
    if last_kind == "web" and picks_result:
        if not B.last_links:
            return False  # a pesquisa abriu no navegador comum: a IA decide
        tool("web_click", target=str(ordinal_to_number(clean)))
        return True
    files = last_results if last_kind != "web" else []

    # resultados da última busca: "mostra o segundo na pasta", "onde ele está"
    if files and (
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
    if files and re.fullmatch(rf"(?:{RUN} )?(?:o |a )?{ORDINAL}(?: {RUN})?", clean):
        act("open_search_result", open_search_result, ordinal_to_number(clean))
        return True

    # "abre o terceiro", "abre o 2", "abre ele"
    if files and (
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
        elif target in {"youtube", "video", "aba", "essa aba", "esta aba", "musica", "navegador do jarvis"} and B.is_open():
            act("close_tab", B.close_tab)  # o YouTube toca numa aba do Jarvis, não num programa
        else:
            tool("close_app", name=target)
        return True
    if re.search(r"\b(cancela|cancelar|para|parar)\s+(?:o\s+|os\s+)?(timer|timers|alarme|alarmes|lembrete|lembretes)\b", clean):
        tool("cancel_timers")
        return True
    # timer só com duração ("em 10 minutos", "daqui a 2 horas", "timer de 5 min"). Hora marcada
    # ("me lembra às 8 horas", "amanhã às 10") vai para a IA, que marca um lembrete de verdade.
    m = re.search(r"\b(?:me lembra|me lembre|me avisa|me avise|timer|alarme|cronometro)\b.*?\b(\d+)\s*"
                  r"(seg|segundo|segundos|min|minuto|minutos|h|hora|horas)\b(?:\s+(?:de|pra|para|que)\s+(.+))?", clean)
    clock = re.search(r"\b(?:as|pras|ate as|pelas)\s+\d|\b\d{1,2}(?::|h)\d{2}\b|\b(?:da manha|da tarde|da noite|"
                      r"de manha|de tarde|de noite|amanha|hoje a noite|segunda|terca|quarta|quinta|sexta|sabado|"
                      r"domingo|meio dia|meia noite|dia \d)", clean)
    if m and not clock:
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
    m = re.match(r"^(?:digita|digite|escreve|escreva)\s+(.+)$", full, flags=re.I)
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
        if re.fullmatch(rf"(?:o |a )?{ORDINAL}(?: resultado| link| site)?", normalize(m.group(1))):
            return False  # "abre o segundo resultado" sem busca antes: a IA vê o contexto
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

FOLDERS = {  # pastas de verdade (o OneDrive costuma levar a Área de Trabalho e os Documentos)
    "downloads": DOWNLOADS,
    "documentos": DOCUMENTS,
    "desktop": DESKTOP,
    "area de trabalho": DESKTOP,
    "imagens": PICTURES,
    "fotos": PICTURES,
    "musicas": MUSIC,
    "videos": VIDEOS,
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
        try:
            return B.open_url(url)
        except Exception as e:
            _browser_failed(e)
    webbrowser.open(url)
    print(f"Jarvis > Abrindo {url}")
    return True


def play_youtube(query):
    """Com o Playwright, clica no vídeo de verdade na aba do Jarvis; sem ele, o jeito antigo."""
    if B.available():
        try:
            result = B.play_youtube(query)
            if result is False:  # a página de busca mudou ou demorou: abre o primeiro vídeo pelo link
                url = F.youtube_first_video(query)
                if url:
                    B.open_url(url)
                    print(f"Jarvis > Tocando {query}.")
                    result = f"Tocando: {query}"
            return _show_playing(result)
        except Exception as e:
            _browser_failed(e)
    return F.play_youtube(query)


def _show_playing(result):
    if isinstance(result, str) and result.startswith("Tocando: "):
        U.card("Tocando agora", result[len("Tocando: "):])
    return result


def youtube_control(action):
    if B.on_youtube():
        try:
            return B.youtube_control(action, normalize)
        except Exception as e:
            _browser_failed(e)
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


YES_WORDS = {"s", "sim", "pode", "confirmo", "confirma", "y", "yes", "isso", "manda", "envia", "claro", "ok",
             "okay", "beleza", "bora", "positivo", "certo", "exato", "fechado"}
NO_WORDS = {"n", "nao", "no", "cancela", "cancelar", "cancele", "negativo", "nunca"}
commands = queue.Queue()  # (origem, texto) vindos do teclado e da voz; um só lugar executa tudo
queue_mode = False  # ligado no main(); nos testes a confirmação usa input() direto
listener = None  # voz.Listener quando a voz está ligada
voice_out = False  # fala as respostas em voz alta (ligado no run() se o edge-tts estiver instalado)


def answer_kind(answer):
    """True = sim ("Sim, senhor.", "pode mandar"), False = não, None = não é resposta (outro pedido)."""
    words = re.findall(r"\w+", normalize(answer))
    if not words:
        return None
    if any(w in NO_WORDS for w in words):
        return False
    return True if words[0] in YES_WORDS else None


def is_yes(answer):
    return answer_kind(answer) is True


def confirm(question):
    if not queue_mode:
        try:
            answer = input(f"Jarvis > {question} (s/n) ")
        except (EOFError, KeyboardInterrupt):
            return False
        return is_yes(answer)
    print(f"Jarvis > {question} (s/n)")
    U.speech(question + " (sim ou não)")
    U.card("Confirmar", question)
    speak(question)
    set_state("parado")
    if listener is not None:
        listener.ask_answer()
    deadline, later = time.time() + 60, []
    try:
        while (left := deadline - time.time()) > 0:
            try:
                origin, answer = commands.get(timeout=left)
            except queue.Empty:
                break
            answer = (answer or "").strip()
            if origin == "lembrete":  # avisa depois; não é a resposta
                later.append((origin, answer))
                continue
            if not answer:  # o microfone não ouviu nada: ainda dá para digitar ou dizer "Jarvis, sim"
                continue
            kind = answer_kind(answer)
            if kind is None:  # outro pedido no meio: cancela este e faz o novo em seguida
                later.append((origin, answer))
                return False
            return kind
        return False
    finally:
        for item in later:
            commands.put(item)


def summarize_file(ref):
    path = resolve_path(ref)
    text = F.read_file(path, show_chars=0) if path.is_file() else False
    if not text:
        if not path.is_file():
            print(f"Jarvis > Arquivo não encontrado: {path}")
        return False
    print(f"Jarvis > Resumindo {path.name}...")
    system = "Resuma o texto em português do Brasil, em até 6 tópicos curtos."
    summary = None
    if N.available():  # o Gemini aguenta textos bem maiores
        try:
            summary = N.generate(system, text[:60000], max_tokens=8192, temperature=0.2)
        except Exception as e:
            print(f"Jarvis > (Gemini falhou: {e})")
    if not summary:
        try:  # o Groq grátis recusa pedidos muito grandes (HTTP 413): manda um pedaço menor
            summary = think(system, text[:12000], skip=("Gemini",) if N.available() else (),
                            json_mode=False, num_predict=600, temperature=0.2)
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


TOOL_GROUPS = ["som", "programas e sites", "arquivos e pastas", "ler e resumir", "mídia", "navegador", "memória", "janelas e teclado",
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
     "run": lambda a: F.weather(a.get("city") or M.load()["perfil"].get("cidade", ""))},
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
     "run": lambda a: web_search(a.get("query", ""))},
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
    {"name": "spotify_play", "args": '{"query":"música"}', "group": "navegador",
     "desc": "abrir uma música no app do Spotify", "examples": ["toca evidências no spotify"],
     "run": lambda a: F.spotify_play(a.get("query", ""))},
    {"name": "whatsapp_send", "args": '{"contact":"nome","message":"texto"}', "group": "navegador",
     "desc": "mandar mensagem no WhatsApp Web (pede confirmação)", "examples": ["manda oi pra mãe no zap"],
     "run": lambda a: _sent(B.whatsapp_send(a.get("contact", ""), a.get("message", ""), confirm))},
    # ---- memória
    {"name": "set_profile", "args": '{"key":"nome|cidade|apelido|musica_favorita|...","value":"valor"}', "group": "memória",
     "desc": "guardar algo do perfil do usuário", "examples": ["eu moro em Recife"],
     "run": lambda a: M.set_profile(a.get("key", ""), a.get("value", ""))},
    {"name": "remember", "args": '{"fact":"texto"}', "group": "memória",
     "desc": "guardar uma informação que o usuário pediu para lembrar", "examples": ["lembra que eu sou alérgico a camarão"],
     "run": lambda a: M.remember(a.get("fact", ""))},
    {"name": "add_reminder", "args": '{"text":"o que lembrar","day":"AAAA-MM-DD","hour":"HH:MM ou vazio"}', "group": "memória",
     "desc": "marcar um lembrete para um dia (e hora)", "examples": ["me lembra da prova na sexta"],
     "run": lambda a: M.add_reminder(a.get("text", ""), a.get("day", ""), a.get("hour", ""))},
    {"name": "forget", "args": '{"text":"assunto"}', "group": "memória",
     "desc": "apagar da memória o que tiver esse assunto", "examples": ["esquece a prova"],
     "run": lambda a: M.forget(a.get("text", ""))},
    {"name": "what_i_know", "args": "{}", "group": "memória",
     "desc": "mostrar tudo o que eu sei sobre o usuário", "examples": ["o que você sabe sobre mim"],
     "run": lambda a: M.what_i_know()},
    {"name": "history", "args": '{"day":"hoje|ontem|AAAA-MM-DD"}', "group": "memória",
     "desc": "o que o usuário pediu num dia", "examples": ["o que eu te pedi ontem"],
     "run": lambda a: M.history(a.get("day", "hoje"))},
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
    (f"oi {NAME.lower()}, tudo bem?", '{"actions":[],"reply":"Tudo certo! Diga o que precisa."}'),
    ("faz um bolo pra mim", '{"actions":[],"reply":"Isso eu não consigo fazer. Diga \\"o que você sabe fazer\\" para ver a lista."}'),
    ("calma mano, eu tipo, não tenho um negócio, é que", '{"actions":[],"reply":"Sem pressa, senhor. O que o senhor quer que eu faça?"}'),
]


def build_ai_prompt():
    tools = "\n".join(f"{t['name']} {t['args']} - {t['desc']}" for t in TOOLS)
    examples = "\n".join(f"Usuário: {u}\nJSON: {j}" for u, j in AI_EXAMPLES)
    return f"""Seu nome é {NAME}: você é o assistente do Windows do usuário. Fala português do Brasil como um mordomo
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
- música "no Spotify" (ou junto com abrir o Spotify) = spotify_play, NUNCA play_youtube
- tocar/ouvir/abrir uma música ou vídeo = play_youtube (toca direto); search_web youtube só se pedir para ver a lista
- pausar, pular, tela cheia, avançar no vídeo aberto = youtube_control
- MODO CICLO: se precisar VER o resultado antes de decidir (pesquisar na web, ler página, procurar arquivo,
  escolher entre opções), faça essa ação e coloque "continue":true. Você recebe o resultado e decide o
  próximo passo. Quando terminar, "continue":false e a resposta final em reply (até 5 frases)
- pesquisar para escolher/comparar/responder = web_search, depois web_click no melhor e web_read
- mandar mensagem no WhatsApp = whatsapp_send (ele mesmo pede confirmação)
- use o perfil, as coisas lembradas e a conversa recente (no começo do pedido) para entender "e amanhã?", "lá", "ele"
- clima sem cidade = cidade do perfil. Datas relativas ("sexta", "amanhã") viram AAAA-MM-DD a partir de "Agora"
- "lembra que tenho prova sexta" = add_reminder; algo sem data ("sou alérgico a camarão") = remember;
  nome, cidade, gostos = set_profile
- se nenhuma ferramenta serve, diga isso em reply; nunca finja que fez
- fala pela metade, pensando alto ("tipo...", "é que...", "calma", "espera"), reclamação ou desabafo
  SEM um pedido claro = actions vazio (NUNCA pesquise só porque não entendeu); pergunte em reply o que ele quer

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
    opening(name)
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
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    now = datetime.now()
    parts = [f"Agora: {now:%Y-%m-%d %H:%M} ({dias[now.weekday()]})"]
    memory = M.context()
    if memory:
        parts.append(memory)
    title = F.user_window_title() or active_window_title()
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
    # o Gemini Flash "pensa" antes de responder e esse raciocínio gasta o mesmo limite de tokens
    return N.generate(system, user, json_mode=json_mode, temperature=temperature or 0.0,
                      max_tokens=max(8192, num_predict or 0))


def ask_groq(system, user, json_mode=True, num_predict=None, temperature=None):
    # pedir pouco: o Groq grátis conta o max_tokens no limite por minuto
    return N.groq_generate(system, user, json_mode=json_mode, temperature=temperature or 0.0,
                           max_tokens=num_predict or 1024)


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


def think(system, user, parse=None, skip=(), **kw):
    """Pergunta para a primeira IA disponível; se falhar (ou a resposta não servir), tenta a próxima."""
    errors = []
    for name, fn in ai_backends():
        if name in skip:
            continue
        try:
            text = fn(system, user, **kw)
            if text:
                result = parse(text) if parse else text
                if errors:
                    print(f"Jarvis > ({'; '.join(errors)}; respondi com o {name})")
                return result
        except Exception as e:
            errors.append(f"{name} falhou: {e}")
    raise RuntimeError("; ".join(errors) or "nenhuma IA configurada (setx GEMINI_API_KEY ou GROQ_API_KEY)")


def parse_json(raw):
    """O objeto JSON da resposta da IA, mesmo com ```json, texto antes ou dentro de uma lista."""
    raw = str(raw).strip()
    start = raw.find("{")
    if start < 0:
        raise ValueError("a IA não devolveu JSON")
    if raw.startswith("[") and raw.find("[") < start:  # [{"name":...}, ...] = só a lista de ações
        try:
            items, _ = json.JSONDecoder().raw_decode(raw)
            if isinstance(items, list) and all(isinstance(a, dict) and "name" in a for a in items):
                return {"actions": items, "reply": ""}
        except ValueError:
            pass
    data, _ = json.JSONDecoder().raw_decode(raw[start:])
    if not isinstance(data, dict):
        raise ValueError("a IA não devolveu um objeto JSON")
    data["actions"] = [a for a in (data.get("actions") or []) if isinstance(a, dict)]
    return data


MAX_STEPS = 6  # teto do modo ciclo, para não gastar o limite grátis da nuvem
MAX_SEEN = 2500  # quanto do resultado de cada ação volta para a IA


class _Tee(io.StringIO):
    """Mostra na tela e guarda o que a ferramenta escreveu, para a IA ver o resultado.
    Só guarda o que vem da thread do pedido (a voz e os timers também escrevem na tela)."""

    def __init__(self, screen):
        super().__init__()
        self.screen = screen
        self.owner = threading.get_ident()

    def write(self, text):
        self.screen.write(text)
        if threading.get_ident() == self.owner:
            return super().write(text)
        return len(text)

    def flush(self):
        self.screen.flush()


def run_actions(actions):
    """Executa as ações; devolve as que falharam e o que cada uma mostrou."""
    failed, seen = [], []
    for i, action in enumerate(actions):
        name = str(action.get("name", ""))
        args = action.get("args", {})
        args = args if isinstance(args, dict) else {}
        before = F.foreground_window()
        tee = _Tee(sys.stdout)
        with contextlib.redirect_stdout(tee):
            result = execute_ai_action(name, args)
        if result is False:
            failed.append(name)
        elif name in OPENS_WINDOW and i + 1 < len(actions):
            F.wait_new_window(before)  # espera a janela abrir antes de digitar/clicar nela
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
            data = think(AI_PROMPT, prompt, parse=parse_json)
            if not isinstance(data, dict):
                data = parse_json(data)
        except Exception as e:
            print(f"Jarvis > Não consegui falar com a IA: {e}")
            return False

        actions = data["actions"]
        failed, seen = run_actions(actions)
        history += seen
        reply = str(data.get("reply") or "").strip()
        more = data.get("continue") is True or str(data.get("continue")).lower() == "true"
        if more and actions:
            if step + 1 < MAX_STEPS:
                if reply:
                    print(f"Jarvis > {reply}")
                continue
            print("Jarvis > Parei aqui para não gastar o limite grátis da IA; o que achei está na tela.")
            return True
        if failed:
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
    (rf"^(oi|ola|opa|eai|e ai|fala|salve|bom dia|boa tarde|boa noite|hey),?( {CALL})?[!. ]*$", "Oi! Diga o que precisa."),
    (rf"^(oi |ola |e ai |fala )?({CALL},? )?(tudo bem|tudo certo|como (voce|vc) esta|beleza)( {CALL})?\??$", "Tudo certo por aqui! Em que posso ajudar?"),
    (rf"^(obrigad[oa]|valeu|vlw|brigad[oa]|show|top|massa|perfeito),?( {CALL})?[!. ]*$", "Tamo junto!"),
    (rf"^({CALL},? )?(quem e voce|quem e vc|qual (e )?(o )?seu nome)\??$",
     f"Meu nome é {NAME}, seu assistente do Windows. Diga \"o que você sabe fazer\"."),
    # "calma", "peraí", "deixa eu pensar": ainda não é um pedido, então não faz nada
    (rf"^({CALL},? )?(calma|espera|espere|pera|perai|pera ai|aguarda|aguenta ai|um momento|um minuto|"
     rf"so um (momento|minuto|segundo)|deixa eu (pensar|ver|lembrar))((,? )(mano|ai|ae|{CALL}))*[!.,? ]*$",
     "Tudo bem, senhor. Pode falar quando quiser."),
]
# "eu não falei o que quero ainda", "não pesquisa quando eu mandar algo assim": a fala não era pedido
END = r"(?=\s*(?:[,.!?]|$))"  # fim da frase: "ainda não falei com a Ana, manda..." é pedido
NOT_A_REQUEST = re.compile(rf"\b(?:ainda nao (?:te )?(?:falei|disse|pedi)(?: o que (?:eu )?quero| nada)?{END}"
                           rf"|nao (?:te )?(?:falei|disse|pedi) (?:o que (?:eu )?quero|nada) ainda"
                           rf"|nao (?:te )?(?:falei|disse|pedi) ainda{END}|nao (?:era|e) (?:um )?pedido|nao (?:te )?pedi nada)")


def small_talk(clean):
    for pattern, answer in SMALL_TALK:
        if re.search(pattern, clean):
            print(f"Jarvis > {answer}")
            return True
    if NOT_A_REQUEST.search(clean):
        print("Jarvis > Entendido, senhor. Só faço algo quando o senhor terminar de dizer o que quer.")
        return True
    return False


def set_state(state):
    """parado | ouvindo | pensando | falando: o reator muda junto."""
    U.state(state)


def speak(text):
    """Fala em voz alta (voz Antônio). Desliga com --mudo."""
    if not voice_out:
        return
    try:
        V.say(text, set_state)
    except Exception as e:
        print(f"Jarvis > (não consegui falar: {e})")
    finally:
        set_state("parado")  # se a fala falhar, o reator não fica preso em "pensando"


def announce(text, title):
    """Aviso que parte do Jarvis (lembrete, sugestão): mostra, vira cartão e fala."""
    print(f"Jarvis > {text}")
    U.front()
    U.card(title, text)
    speak(text)


def handle(text):
    if fast_local_router(text):
        return
    ask_ai_router(text)


def last_said(out):
    """A última fala do Jarvis: a linha "Jarvis > ..." e as linhas que vieram junto (lista, resumo)."""
    blocks = []
    for line in out.splitlines():
        if line.startswith("Jarvis > "):
            blocks.append([line[len("Jarvis > "):].strip()])
        elif blocks and line.strip():
            blocks[-1].append(line.strip())
    blocks = [b for b in blocks if b[0] and not b[0].startswith("(")]
    if not blocks:
        return "", ""
    head, *rest = blocks[-1]
    if not rest and len(head) <= 40:
        # "Resumindo x..." + o resumo, e depois só um "Pronto." da IA: o que importa é o resumo
        for b in reversed(blocks[:-1]):
            if b[0].endswith("...") and len(b) > 1:
                return b[0], "\n".join(b[1:])
    return head, "\n".join(rest)


def _short_paths(text):
    """No cartão, "1. G:\\Escola\\2024\\relatorio.pdf" vira "1. relatorio.pdf" (o caminho fica no console)."""
    def short(m):
        path = m.group(2)
        return m.group(1) + (ntpath.basename(path.rstrip("\\")) or path)
    return re.sub(r"(?m)^(\d+\.\s+)((?:[A-Za-z]:\\|\\\\).+)$", short, text)


def spoken(head, rest):
    """O que falar: o resumo inteiro depois de "Resumindo...", e só o começo de listas longas."""
    if rest and head.endswith("..."):
        return rest
    if rest and head.endswith(":"):
        return head[:-1] + ". Deixei na tela."
    return head


def _sent(result):
    """Mensagem enviada no WhatsApp vira a janelinha do zap ("Enviado para Ana: chego às 8")."""
    if isinstance(result, str) and result.startswith("Enviado para "):
        U.card("WhatsApp", result, 9000)
    return result


def info_card(out, head):
    """Clima, PC, bateria...: o que a ferramenta mostrou vira uma janelinha (a fala final fica na legenda)."""
    titles = [INFO_CARDS[n] for n in _ran if n in INFO_CARDS]
    if not titles:
        return
    lines = [line[len("Jarvis > "):].strip() for line in out.splitlines() if line.startswith("Jarvis > ")]
    lines = [line for line in lines if line and not line.startswith("(")]
    if len(lines) > 1 and lines[-1] == head:
        lines = lines[:-1]  # a resposta da IA já está na legenda
    if lines:
        U.card(titles[0], "\n".join(lines)[:900], 12000)


def respond(text):
    """Executa o pedido; mostra a fala do Jarvis no reator (listas viram cartão) e fala em voz alta."""
    _ran.clear()
    U.heard(text)  # ele vem para a frente com o seu pedido na legenda
    set_state("pensando")
    tee = _Tee(sys.stdout)
    with contextlib.redirect_stdout(tee):
        try:
            handle(text)
        except Exception as e:  # o erro também é falado e aparece no reator
            log_action("erro", f"{text}: {e}")
            print(f"Jarvis > Desculpe, senhor, não consegui: {e}")
    out = tee.getvalue()
    head, rest = last_said(out)
    say = spoken(head, rest)
    U.speech(say if head.endswith("...") else head)
    if rest:
        U.card(head.rstrip(":. ") or "Jarvis", _short_paths(rest)[:900], 15000)
    else:
        info_card(out, head)
    try:
        M.add_talk(text, say)
    except Exception:
        pass
    if say and voice_out:
        speak(say)  # volta para "parado" sozinho, até se a fala falhar
    else:
        set_state("parado")


def handle_spoken(text):
    respond(text)


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
        print("Voz desligada. Instale: python -m pip install " + " ".join(lacks))
        return
    model = V.find_model()
    if model is None:
        try:
            model = V.download_model()
        except Exception as e:
            print(f"Voz desligada: não consegui baixar o modelo de voz ({e}).")
            return
    if model is None:
        print(f"Voz desligada: a pasta {V.VOSK_MODEL} não tem o modelo do Vosk (pastas am, conf...).")
        return
    candidate = V.Listener(commands.put, set_state, model)
    candidate.start()
    candidate.ready.wait(30)
    if candidate.error is not None or not candidate.ready.is_set():
        print("Voz desligada. Confira se o microfone está conectado e liberado no Windows.")
        V.open_mic_settings()
        return
    listener = candidate
    mic = V.mic_name()
    print(f'Voz ligada{" (" + mic + ")" if mic else ""}: diga "{NAME}" e faça o pedido depois do bipe.')


def run():
    """Laço do Jarvis: executa, um de cada vez, os pedidos digitados e falados."""
    global queue_mode, voice_out
    threading.Thread(target=warm_up_ai, daemon=True).start()
    voice_out = "--mudo" not in sys.argv and V.can_speak()
    if not voice_out and "--mudo" not in sys.argv:
        print("Fala desligada: python -m pip install edge-tts")
    if "--sem-voz" not in sys.argv:
        start_voice()
    print("")
    queue_mode = True
    threading.Thread(target=keyboard_reader, daemon=True).start()
    threading.Thread(target=F.warm_up_everything, daemon=True).start()  # índice pronto antes da 1ª busca
    threading.Thread(target=F.store_apps, daemon=True).start()  # lista dos apps da Store, para o "abre"
    F.track_focus()
    F.on_alarm = lambda message: commands.put(("lembrete", message))  # timers também falam
    M.reminder_watcher(commands.put)
    hint = M.habit_hint()
    if hint:
        announce(hint, "Sugestão")
        try:  # a IA vê a sugestão na conversa e entende o "sim" que vier depois
            M.add_talk("(o Jarvis sugeriu ao abrir)", hint)
        except Exception:
            pass

    while True:
        try:
            origin, user_text = commands.get(timeout=0.5)  # com timeout o Ctrl+C funciona no Windows
        except queue.Empty:
            continue
        user_text = (user_text or "").strip()
        if not user_text:
            continue
        if origin in ("voz", "janela"):
            print(f"Você ({origin}) > {user_text}")
        if origin == "lembrete":
            announce(f"Senhor, lembrete: {user_text}", "Lembrete")
            continue
        if normalize(user_text) in {"sair", "exit", "quit"}:
            print("Jarvis > Até mais.")
            break
        try:
            respond(user_text)
        except Exception as e:
            print(f"Jarvis > Erro: {e}")
            set_state("parado")
    U.close()


def disable_quick_edit():
    """No console antigo, um clique na janela congela todos os print() (e o Jarvis junto)."""
    try:
        k32 = ctypes.windll.kernel32
        k32.GetStdHandle.restype = ctypes.c_void_p
        handle = k32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(handle, ctypes.byref(mode)):
            k32.SetConsoleMode(handle, (mode.value & ~0x0040) | 0x0080)  # sem QUICK_EDIT, com EXTENDED_FLAGS
    except Exception:
        pass


def main():
    disable_quick_edit()
    print("")
    print("==============================================")
    print(f"{NAME.upper():^46}")
    print("     comandos rápidos + IA: " + (" -> ".join(n for n, _ in ai_backends()) or "nenhuma (configure a chave)"))
    print("==============================================")
    print("")
    print("Digite o pedido e Enter. 'sair' fecha.")
    if "--sem-tela" not in sys.argv and U.available():
        started = threading.Event()

        def worker():
            started.set()
            try:
                run()
            except Exception:
                traceback.print_exc()
                print("Jarvis > Parei por causa do erro acima.")
            os._exit(0)

        try:
            U.start(worker, lambda text: commands.put(("janela", text)), NAME)  # o reator fica na thread principal
        except Exception as e:
            print(f"A janela do reator não abriu ({e}). Sigo sem ela.")
            if started.is_set():  # o Jarvis já está rodando na outra thread
                while True:
                    time.sleep(3600)
        else:
            os._exit(0)  # fechou a janela: fecha tudo (voz e teclado ficam em threads)
    elif "--sem-tela" not in sys.argv:
        print("Sem interface: python -m pip install pywebview")
    run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nJarvis encerrado.")
