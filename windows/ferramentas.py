# -*- coding: utf-8 -*-
"""Ferramentas extras do Jarvis: sistema, energia, rede, clima, arquivos, texto e rotinas.

Cada função imprime o resultado para o usuário e devolve True/valor quando deu certo
ou False quando falhou. O catálogo (TOOLS em jarvis_ai.py) liga cada uma a um nome.
"""

import ast
import ctypes
import json
import operator
import os
import re
import shutil
import socket
import subprocess
import threading
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROUTINES_FILE = Path(r"G:\Jarvis\config\rotinas.json")
DEFAULT_ROUTINES = {
    "estudo": [
        {"name": "set_volume", "args": {"percent": 25}},
        {"name": "open_target", "args": {"target": "notepad"}},
        {"name": "start_timer", "args": {"minutes": 25, "message": "Pausa do estudo!"}},
    ],
    "relaxar": [
        {"name": "set_volume", "args": {"percent": 40}},
        {"name": "search_web", "args": {"query": "lofi hip hop", "site": "youtube"}},
    ],
    "foco": [
        {"name": "mute_audio", "args": {"mute": True}},
        {"name": "window_control", "args": {"action": "desktop"}},
    ],
}

# Processos que o Jarvis nunca fecha
PROTECTED_PROCESSES = {
    "python", "pythonw", "py", "explorer", "csrss", "winlogon", "svchost", "system", "lsass",
    "services", "smss", "wininit", "dwm", "conhost", "powershell", "pwsh", "cmd",
    "windowsterminal", "ollama", "ollama app",
}
# Pastas onde o Jarvis não mexe em arquivos
PROTECTED_DIRS = [r"c:\windows", r"c:\program files", r"c:\program files (x86)", r"c:\programdata"]

SETTINGS_PAGES = {
    "bluetooth": "ms-settings:bluetooth",
    "wifi": "ms-settings:network-wifi",
    "rede": "ms-settings:network",
    "internet": "ms-settings:network",
    "tela": "ms-settings:display",
    "video": "ms-settings:display",
    "som": "ms-settings:sound",
    "audio": "ms-settings:sound",
    "atualizacao": "ms-settings:windowsupdate",
    "windows update": "ms-settings:windowsupdate",
    "apps": "ms-settings:appsfeatures",
    "aplicativos": "ms-settings:appsfeatures",
    "energia": "ms-settings:powersleep",
    "bateria": "ms-settings:batterysaver",
    "armazenamento": "ms-settings:storagesense",
    "notificacoes": "ms-settings:notifications",
    "papel de parede": "ms-settings:personalization-background",
    "personalizacao": "ms-settings:personalization",
    "mouse": "ms-settings:mousetouchpad",
    "teclado": "ms-settings:typing",
    "impressoras": "ms-settings:printers",
    "data e hora": "ms-settings:dateandtime",
    "idioma": "ms-settings:regionlanguage",
    "privacidade": "ms-settings:privacy",
    "microfone": "ms-settings:privacy-microphone",
    "camera": "ms-settings:privacy-webcam",
}


def _norm(text):
    text = unicodedata.normalize("NFD", str(text).strip().lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _say(msg):
    print(f"Jarvis > {msg}")


def _run(args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


# ========================= SISTEMA =========================

def battery_status():
    import psutil
    bat = psutil.sensors_battery()
    if bat is None:
        _say("Não achei bateria (PC na tomada direto?).")
        return False
    state = "carregando" if bat.power_plugged else "na bateria"
    extra = ""
    if not bat.power_plugged and bat.secsleft not in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED):
        extra = f", dura uns {bat.secsleft // 3600}h{(bat.secsleft % 3600) // 60:02d}"
    _say(f"Bateria em {bat.percent:.0f}%, {state}{extra}.")
    return True


def list_processes(limit=10):
    import psutil
    procs = []
    for p in psutil.process_iter(["name", "memory_info", "cpu_percent"]):
        try:
            procs.append((p.info["memory_info"].rss, p.info["name"]))
        except Exception:
            continue
    procs.sort(reverse=True)
    _say(f"Programas usando mais memória:")
    for rss, name in procs[: int(limit)]:
        print(f"  {name}: {rss / (1024 ** 2):.0f} MB")
    return True


def close_app(name):
    import psutil
    wanted = _norm(re.sub(r"\.exe$", "", str(name), flags=re.I))
    if not wanted:
        return False
    if wanted in PROTECTED_PROCESSES:
        _say(f"Não fecho {name}: é parte do sistema ou do próprio Jarvis.")
        return False
    closed = set()
    for p in psutil.process_iter(["name"]):
        pname = _norm(re.sub(r"\.exe$", "", p.info["name"] or "", flags=re.I))
        if not pname or pname in PROTECTED_PROCESSES:
            continue
        if pname == wanted or (len(wanted) >= 4 and wanted in pname):
            try:
                p.terminate()
                closed.add(p.info["name"])
            except Exception:
                continue
    if not closed:
        _say(f"Não achei {name} aberto.")
        return False
    _say(f"Fechei: {', '.join(sorted(closed))}.")
    return True


def open_settings(page=""):
    key = _norm(page)
    uri = SETTINGS_PAGES.get(key)
    if uri is None:
        uri = next((v for k, v in SETTINGS_PAGES.items() if k in key), "ms-settings:")
    os.startfile(uri)
    _say("Configurações abertas.")
    return True


def set_brightness(percent):
    percent = max(0, min(100, int(percent)))
    cmd = f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{percent})"
    r = _run(["powershell", "-NoProfile", "-Command", cmd])
    if r.returncode != 0:
        _say("Não consegui mudar o brilho (monitor externo não aceita por aqui).")
        return False
    _say(f"Brilho em {percent}%.")
    return True


def power_action(action, minutes=1):
    action = _norm(action)
    seconds = max(0, int(float(minutes) * 60))
    if action in ("bloquear", "lock"):
        ctypes.windll.user32.LockWorkStation()
        _say("PC bloqueado.")
    elif action in ("suspender", "dormir", "sleep"):
        _run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        _say("Suspendendo.")
    elif action in ("desligar", "shutdown"):
        _run(["shutdown", "/s", "/t", str(seconds)])
        _say(f"O PC desliga em {seconds // 60} min. Diga 'cancela o desligamento' para parar.")
    elif action in ("reiniciar", "restart"):
        _run(["shutdown", "/r", "/t", str(seconds)])
        _say(f"O PC reinicia em {seconds // 60} min. Diga 'cancela o desligamento' para parar.")
    elif action in ("cancelar", "abort"):
        _run(["shutdown", "/a"])
        _say("Desligamento cancelado.")
    else:
        _say(f"Não conheço a ação de energia '{action}'.")
        return False
    return True


def network_info():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        ip = "sem rede"
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2).close()
        online = "com internet"
    except OSError:
        online = "SEM internet"
    wifi = ""
    try:
        out = _run(["netsh", "wlan", "show", "interfaces"]).stdout
        m = re.search(r"^\s*SSID\s*:\s*(.+)$", out, flags=re.M)
        if m:
            wifi = f", Wi-Fi '{m.group(1).strip()}'"
    except Exception:
        pass
    _say(f"IP local {ip}{wifi}, {online}.")
    return True


# ========================= INFORMAÇÃO =========================

def weather(city=""):
    city = str(city).strip()
    fmt = urllib.parse.quote("%l: %C, %t (sensação %f), umidade %h, vento %w", safe="%")
    url = f"https://wttr.in/{urllib.parse.quote(city)}?format={fmt}&lang=pt&m"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=8) as r:
            text = r.read().decode("utf-8").strip()
    except Exception as e:
        _say(f"Não consegui ver o clima agora ({e}).")
        return False
    _say(text)
    return True


_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        if isinstance(node.op, ast.Pow) and abs(_eval(node.right)) > 100:
            raise ValueError("expoente grande demais")
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("conta inválida")


def calculate(expression):
    expr = _norm(expression)
    m = re.match(r"^(\d+(?:[.,]\d+)?)\s*(?:%|por cento)\s*de\s*(\d+(?:[.,]\d+)?)$", expr)
    if m:
        expr = f"{m.group(1)}/100*{m.group(2)}"
    for word, sym in [("dividido por", "/"), ("vezes", "*"), ("mais", "+"), ("menos", "-"),
                      ("elevado a", "**"), ("x", "*"), ("÷", "/"), ("^", "**")]:
        expr = expr.replace(word, sym)
    expr = re.sub(r"(\d),(\d)", r"\1.\2", expr)
    try:
        value = _eval(ast.parse(expr, mode="eval"))
    except Exception:
        _say(f"Não entendi a conta: {expression}")
        return False
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, float):
        value = round(value, 6)
    _say(f"{expression} = {str(value).replace('.', ',')}")
    return value


_timers = []


def _alert(message):
    print(f"\n⏰ Jarvis > {message}\nVocê > ", end="", flush=True)
    try:
        import winsound
        for _ in range(3):
            winsound.Beep(880, 300)
    except Exception:
        pass
    try:
        ctypes.windll.user32.MessageBoxW(0, message, "Jarvis", 0x40 | 0x40000)
    except Exception:
        pass


def start_timer(minutes, message="Tempo esgotado!"):
    minutes = float(minutes)
    if minutes <= 0:
        return False
    t = threading.Timer(minutes * 60, _alert, args=(str(message) or "Tempo esgotado!",))
    t.daemon = True
    t.start()
    _timers.append(t)
    shown = int(minutes) if minutes.is_integer() else minutes
    _say(f"Ok, aviso em {shown} min: {message}")
    return True


def cancel_timers():
    n = sum(1 for t in _timers if t.is_alive())
    for t in _timers:
        t.cancel()
    _timers.clear()
    _say(f"Cancelei {n} timer(s).")
    return True


# ========================= ARQUIVOS =========================

def _protected(path):
    p = str(Path(path).resolve()).lower()
    return any(p == d or p.startswith(d + "\\") for d in PROTECTED_DIRS)


def read_text(path, limit=200_000):
    """Texto de TXT/código/CSV/JSON/MD, PDF (pypdf) ou DOCX."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
            if sum(len(x) for x in parts) > limit:
                break
        return "\n".join(parts)[:limit]
    if ext == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)[:limit]
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read(limit)


def read_file(path, show_chars=1500):
    path = Path(path)
    if not path.is_file():
        _say(f"Arquivo não encontrado: {path}")
        return False
    try:
        text = read_text(path)
    except Exception as e:
        _say(f"Não consegui ler {path.name}: {e}")
        return False
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        _say(f"{path.name} não tem texto que eu consiga ler (pode ser imagem escaneada).")
        return False
    _say(f"{path.name} ({len(text)} caracteres):")
    print(text[:show_chars] + ("\n[...]" if len(text) > show_chars else ""))
    return text


def file_info(path):
    from datetime import datetime
    path = Path(path)
    if not path.exists():
        _say(f"Não existe: {path}")
        return False
    st = path.stat()
    size = st.st_size
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            break
        size /= 1024
    kind = "pasta" if path.is_dir() else (path.suffix or "arquivo")
    _say(f"{path.name}: {kind}, {size:.1f} {unit}, modificado em "
         f"{datetime.fromtimestamp(st.st_mtime):%d/%m/%Y %H:%M}.")
    return True


def create_folder(path):
    path = Path(os.path.expandvars(str(path))).expanduser()
    if _protected(path):
        _say("Não crio nada em pastas do sistema.")
        return False
    path.mkdir(parents=True, exist_ok=True)
    _say(f"Pasta criada: {path}")
    return True


def copy_item(src, dest):
    src, dest = Path(src), Path(os.path.expandvars(str(dest))).expanduser()
    if not src.exists():
        _say(f"Não existe: {src}")
        return False
    if _protected(dest):
        _say("Não copio para pastas do sistema.")
        return False
    target = dest / src.name if dest.is_dir() else dest
    if src.is_dir():
        shutil.copytree(src, target)
    else:
        shutil.copy2(src, target)
    _say(f"Copiado para {target}")
    return str(target)


def move_item(src, dest):
    src, dest = Path(src), Path(os.path.expandvars(str(dest))).expanduser()
    if not src.exists():
        _say(f"Não existe: {src}")
        return False
    if _protected(src) or _protected(dest):
        _say("Não mexo em pastas do sistema.")
        return False
    target = dest / src.name if dest.is_dir() else dest
    if target.exists():
        _say(f"Já existe {target}; não vou sobrescrever.")
        return False
    shutil.move(str(src), str(target))
    _say(f"Movido para {target}")
    return str(target)


def rename_item(src, new_name):
    src = Path(src)
    if not src.exists():
        _say(f"Não existe: {src}")
        return False
    new_name = str(new_name).strip()
    if not Path(new_name).suffix and src.suffix:
        new_name += src.suffix
    target = src.with_name(new_name)
    if target.exists():
        _say(f"Já existe {target.name}; não vou sobrescrever.")
        return False
    if _protected(src):
        _say("Não mexo em pastas do sistema.")
        return False
    src.rename(target)
    _say(f"Renomeado para {target.name}")
    return str(target)


def send_to_recycle_bin(path, confirm):
    """Excluir é nível 3 no plano: sempre pergunta e vai para a Lixeira (dá para desfazer)."""
    path = Path(path)
    if not path.exists():
        _say(f"Não existe: {path}")
        return False
    if _protected(path):
        _say("Não excluo nada de pastas do sistema.")
        return False
    if not confirm(f"Mandar '{path}' para a Lixeira?"):
        _say("Ok, não excluí.")
        return False

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p),
                    ("pTo", ctypes.c_wchar_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]

    FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_SILENT = 3, 0x40, 0x10, 0x4
    op = SHFILEOPSTRUCTW(None, FO_DELETE, str(path) + "\0", None,
                         FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT, 0, None, None)
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) != 0:
        _say("Não consegui mandar para a Lixeira.")
        return False
    _say(f"{path.name} foi para a Lixeira.")
    return True


# ------------------------- EVERYTHING (busca no PC inteiro) -------------------------
# O Everything (voidtools.com) mantém um índice de todos os discos; o es.exe pergunta a ele.
ES_CANDIDATES = [
    Path(r"G:\Jarvis\tools\es.exe"),
    Path(r"C:\Program Files\Everything\es.exe"),
    Path(r"C:\Program Files (x86)\Everything\es.exe"),
]
# Pastas do sistema ficam de fora: o Jarvis não deve mexer nelas.
EVERYTHING_EXCLUDE = [
    "C:\\Windows\\", "C:\\Program Files\\", "C:\\Program Files (x86)\\", "C:\\ProgramData\\",
    "\\AppData\\", "\\$Recycle.Bin\\", "\\System Volume Information\\",
]


def find_es():
    custom = os.environ.get("JARVIS_ES", "").strip()
    if custom and Path(custom).exists():
        return custom
    for path in ES_CANDIDATES:
        if path.exists():
            return str(path)
    return shutil.which("es")


def _decode(raw):
    for enc in ("utf-8", "mbcs", "cp1252"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def everything_search(query, limit=400, extension=None):
    """Caminhos achados pelo Everything, ou None se ele não estiver instalado/aberto."""
    exe = find_es()
    if not exe:
        return None
    terms = [f"ext:{extension.lstrip('.')}"] if extension else str(query).split()
    terms += [f'!"{p}"' for p in EVERYTHING_EXCLUDE]
    try:
        r = subprocess.run([exe, "-n", str(limit), *terms], capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:  # Everything fechado: o es.exe não consegue perguntar
        return None
    return [line.strip() for line in _decode(r.stdout).splitlines() if line.strip()]


# ========================= TEXTO E TECLADO =========================

def type_text(text):
    """Digita no programa da frente (via área de transferência, para acentos funcionarem)."""
    import pyautogui
    import pyperclip
    old = None
    try:
        old = pyperclip.paste()
    except Exception:
        pass
    pyperclip.copy(str(text))
    pyautogui.hotkey("ctrl", "v")
    if old is not None:
        threading.Timer(1.0, pyperclip.copy, args=(old,)).start()
    _say("Digitado.")
    return True


ALLOWED_KEYS = {
    "ctrl", "alt", "shift", "win", "enter", "esc", "tab", "space", "backspace", "delete", "home", "end",
    "pageup", "pagedown", "up", "down", "left", "right", "printscreen",
    *[f"f{i}" for i in range(1, 13)], *"abcdefghijklmnopqrstuvwxyz0123456789",
}


def press_keys(keys):
    import pyautogui
    parts = [k.strip().lower() for k in re.split(r"[+ ]+", str(keys)) if k.strip()]
    parts = ["ctrl" if k == "control" else "esc" if k == "escape" else k for k in parts]
    if not parts or any(k not in ALLOWED_KEYS for k in parts):
        _say(f"Não sei apertar '{keys}'.")
        return False
    pyautogui.hotkey(*parts)
    _say(f"Apertei {'+'.join(parts)}.")
    return True


def read_clipboard():
    import pyperclip
    text = pyperclip.paste() or ""
    _say("Área de transferência:" if text else "A área de transferência está vazia.")
    if text:
        print(text[:1500])
    return text


def focus_window(title):
    import pygetwindow
    wanted = _norm(title)
    for w in pygetwindow.getAllWindows():
        if w.title and wanted in _norm(w.title):
            try:
                if w.isMinimized:
                    w.restore()
                w.activate()
            except Exception:
                pass
            _say(f"Janela: {w.title}")
            return True
    _say(f"Não achei janela com '{title}'.")
    return False


def list_windows():
    import pygetwindow
    titles = [w.title for w in pygetwindow.getAllWindows() if w.title.strip()]
    _say("Janelas abertas:")
    for t in titles[:25]:
        print(f"  - {t}")
    return titles


# ========================= ROTINAS =========================

def load_routines():
    routines = dict(DEFAULT_ROUTINES)
    try:
        if ROUTINES_FILE.exists():
            routines.update({_norm(k): v for k, v in json.loads(ROUTINES_FILE.read_text(encoding="utf-8")).items()})
    except Exception as e:
        _say(f"Erro lendo {ROUTINES_FILE}: {e}")
    return routines


def list_routines():
    routines = load_routines()
    _say("Rotinas (diga 'modo <nome>'):")
    for name, steps in routines.items():
        print(f"  - {name}: " + ", ".join(s["name"] for s in steps))
    print(f"  Crie as suas em {ROUTINES_FILE}")
    return list(routines)


def run_routine(name, execute):
    routines = load_routines()
    key = _norm(name)
    steps = routines.get(key)
    if steps is None:
        _say(f"Não conheço a rotina '{name}'.")
        list_routines()
        return False
    _say(f"Rotina {key}:")
    ok = True
    for step in steps:
        if execute(step.get("name", ""), step.get("args", {}) or {}) is False:
            ok = False
    return ok


# ========================= YOUTUBE =========================
# Toca o primeiro vídeo direto (sem a página de resultados) e reaproveita a mesma aba
# do YouTube nos próximos pedidos, em vez de abrir uma aba nova a cada música.

YOUTUBE_KEYS = {
    "pausar": "k", "pause": "k", "play": "k", "continuar": "k",
    "proximo": "shift+n", "next": "shift+n",
    "anterior": "shift+p", "previous": "shift+p",
    "tela cheia": "f", "fullscreen": "f",
    "avancar": "l", "voltar": "j",
    "mudo": "m", "mute": "m",
    "legenda": "c",
    "mais rapido": "shift+.", "mais devagar": "shift+,",
}


def youtube_first_video(query):
    """URL do primeiro vídeo da busca do YouTube, ou None (sem chave de API)."""
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(str(query))
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept-Language": "pt-BR,pt;q=0.9"})
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception:
        return None
    m = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})"', html) or re.search(r'"videoId":"([\w-]{11})"', html)
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else None


def _youtube_window():
    try:
        import pygetwindow
        for w in pygetwindow.getAllWindows():
            if "youtube" in (w.title or "").lower():
                return w
    except Exception:
        pass
    return None


def _focus(w):
    try:
        if w.isMinimized:
            w.restore()
        w.activate()
    except Exception:
        pass


def _navigate_same_tab(window, url):
    import time
    import pyautogui
    import pyperclip
    _focus(window)
    time.sleep(0.4)
    pyautogui.hotkey("ctrl", "l")
    pyperclip.copy(url)
    pyautogui.hotkey("ctrl", "v")
    pyautogui.press("enter")


def play_youtube(query, open_url=None):
    """Toca o primeiro vídeo. Se o YouTube já está aberto, troca o vídeo na mesma aba."""
    import webbrowser
    open_url = open_url or webbrowser.open
    url = youtube_first_video(query)
    if not url:
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(str(query))
        _say(f"Não achei o vídeo direto; abrindo a busca de {query}.")
    window = _youtube_window()
    if window is not None:
        try:
            _navigate_same_tab(window, url)
            _say(f"Tocando {query} (na mesma aba do YouTube).")
            return True
        except Exception:
            pass
    open_url(url)
    _say(f"Tocando {query} no YouTube.")
    return True


def youtube_control(action):
    """Controla o vídeo aberto: pausar, próximo, tela cheia, avançar, voltar, mudo, legenda..."""
    import pyautogui
    key = YOUTUBE_KEYS.get(_norm(action))
    if key is None:
        _say(f"Não sei fazer '{action}' no YouTube.")
        return False
    window = _youtube_window()
    if window is None:
        _say("Não tem YouTube aberto.")
        return False
    _focus(window)
    import time
    time.sleep(0.3)
    pyautogui.hotkey(*key.split("+"))
    _say(f"YouTube: {action}.")
    return True
