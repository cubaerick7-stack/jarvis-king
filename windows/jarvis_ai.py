#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import ctypes
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
SCREENSHOT_DIR = Path(r"G:\Jarvis\screenshots")
ACTION_LOG = Path(r"G:\Jarvis\logs\acoes.log")
SEARCH_ROOTS = [
    Path(r"G:\\"),
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Documents",
]
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

    need_pyautogui()
    pyautogui.press("win")
    time.sleep(0.4)
    pyautogui.write(original, interval=0.025)
    time.sleep(0.7)
    pyautogui.press("enter")
    print(f"Jarvis > Tentando abrir {original}.")
    return True


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

    found, seen = [], set()
    print(f"Jarvis > Procurando: {query_original}")

    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                try:
                    if not path.is_file():
                        continue
                    matched = path.suffix.lower() == extension if extension else query_low in normalize(path.name)
                    if matched:
                        p = str(path)
                        if p not in seen:
                            seen.add(p)
                            found.append(p)
                        if len(found) >= MAX_RESULTS:
                            break
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            pass
        if len(found) >= MAX_RESULTS:
            break

    last_results = found

    if not found:
        print("Jarvis > Não encontrei nenhum arquivo.")
        return []

    print("Jarvis > Encontrei:")
    for i, p in enumerate(found, 1):
        print(f"  {i}. {p}")
    return found


def open_search_result(index):
    index = int(index)
    if not (1 <= index <= len(last_results)):
        print("Jarvis > Esse resultado não existe.")
        return False
    path = Path(last_results[index - 1])
    if not path.exists():
        print("Jarvis > O arquivo não existe mais.")
        return False
    os.startfile(str(path))
    print(f"Jarvis > Abrindo: {path}")
    return True


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

    # "abre o terceiro", "abre o 2", "abre ele"
    if last_results and (
        re.match(rf"^(?:abre|abra|abrir)\s+(?:o|a)\s+{ORDINAL}\b", clean)
        or any(x in clean for x in ["abre ele", "abre o arquivo", "abre esse"])
    ):
        n = ordinal_to_number(clean)
        if n is None:
            print("Jarvis > Qual resultado?")
        else:
            act("open_search_result", open_search_result, n)
        return True

    # abrir apps/sites
    m = re.match(r"^(?:abre|abra|abrir|inicia|inicie)\s+(?:o\s+|a\s+)?(.+?)(?:\s+pra mim|\s+para mim)?$", text, flags=re.I)
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

AI_PROMPT = r"""
Você é o roteador do JARVIS no Windows.
Responda SOMENTE JSON válido, sem explicações.

Formato:
{"actions":[{"name":"acao","args":{}}],"reply":"frase curta"}

Ações:
set_volume {"percent":0-100}
mute_audio {"mute":true/false}
open_target {"target":"nome"}
search_files {"query":"nome"}
open_search_result {"index":1}
show_search_result {"index":1}
list_folder {"path":"caminho"}
search_web {"query":"texto","site":"google ou youtube"}
media_control {"action":"play, pause, next, previous ou stop"}
window_control {"action":"minimizar, maximizar, fechar, trocar, desktop ou menu"}
take_screenshot {}
system_info {}

Regras:
- metade do volume = 50
- pode retornar várias actions
- não invente ações
"""


def execute_ai_action(name, args):
    table = {
        "set_volume": lambda: set_volume(args.get("percent", 50)),
        "mute_audio": lambda: mute_audio(args.get("mute", True)),
        "open_target": lambda: open_target(args.get("target", "")),
        "search_files": lambda: search_files(args.get("query", "")),
        "open_search_result": lambda: open_search_result(args.get("index", 1)),
        "show_search_result": lambda: show_search_result(args.get("index", 1)),
        "list_folder": lambda: list_folder(args.get("path", "")),
        "search_web": lambda: search_web(args.get("query", ""), args.get("site", "google")),
        "media_control": lambda: media_control(args.get("action", "")),
        "window_control": lambda: window_control(args.get("action", "")),
        "take_screenshot": take_screenshot,
        "system_info": system_info,
    }
    fn = table.get(name)
    if not fn:
        print(f"Jarvis > Ação desconhecida: {name}")
        return False
    log_action(f"ia:{name}", json.dumps(args, ensure_ascii=False))
    try:
        return fn()
    except Exception as e:
        print(f"Jarvis > Erro em {name}: {e}")
        return False


def ask_ai_router(user_text):
    if chat is None:
        print("Jarvis > Instale ollama: python -m pip install ollama")
        return False

    try:
        response = chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": AI_PROMPT},
                {"role": "user", "content": user_text},
            ],
            format="json",
            think=False,
            stream=False,
            options={"temperature": 0, "num_ctx": 2048, "num_predict": 180},
        )
        raw = (response.message.content or "").strip()
        data = json.loads(raw)

        for action in data.get("actions", []):
            execute_ai_action(action.get("name", ""), action.get("args", {}) or {})

        reply = str(data.get("reply", "")).strip()
        if reply:
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
