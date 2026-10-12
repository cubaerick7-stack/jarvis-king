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
import tempfile
import threading
import time
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
    "msedgewebview2",  # desenha a janela do Jarvis (e a de outros programas)
}
# Nome falado -> processo ("fecha o bloco de notas" = notepad.exe)
PROCESS_ALIASES = {
    "bloco de notas": ["notepad"], "notas": ["notepad"], "calculadora": ["calculatorapp", "calculator", "calc"],
    "gerenciador de tarefas": ["taskmgr"], "edge": ["msedge"], "microsoft edge": ["msedge"],
    "google chrome": ["chrome"], "word": ["winword"], "powerpoint": ["powerpnt"], "excel": ["excel"],
    "explorador de arquivos": ["explorer"],  # protegido: responde que não fecha (é a barra de tarefas)
    "paint": ["mspaint"], "spotify": ["spotify"], "teams": ["ms-teams", "teams"],
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
    _say("Programas usando mais memória:")
    for rss, name in procs[: int(limit)]:
        print(f"  {name}: {rss / (1024 ** 2):.0f} MB")
    return True


def close_app(name):
    """Fecha como o X da janela (o programa pergunta se quer salvar); só força o que não tem janela."""
    import psutil
    wanted = _norm(re.sub(r"\.exe$", "", str(name), flags=re.I))
    if not wanted:
        return False
    names = PROCESS_ALIASES.get(wanted, [wanted.replace(" ", "")])
    if wanted in PROTECTED_PROCESSES or any(n in PROTECTED_PROCESSES for n in names):
        _say(f"Não fecho {name}: é parte do sistema ou do próprio Jarvis.")
        return False
    try:  # o Edge do próprio Jarvis (YouTube, WhatsApp) é filho dele: "fecha o edge" não mexe nele
        mine = {c.pid for c in psutil.Process().children(recursive=True)} | {os.getpid()}
    except Exception:
        mine = {os.getpid()}
    found, closed, windowless, denied = set(), set(), [], set()
    for p in psutil.process_iter(["name", "pid"]):
        pname = _norm(re.sub(r"\.exe$", "", p.info["name"] or "", flags=re.I))
        if not pname or pname in PROTECTED_PROCESSES or p.info["pid"] in mine:
            continue
        if pname in names or any(len(n) >= 4 and pname.startswith(n) for n in names):
            found.add(p.info["name"])
            try:
                r = _run(["taskkill", "/PID", str(p.info["pid"])])  # sem /F: pede para fechar
                if r.returncode == 0:
                    closed.add(p.info["name"])
                else:
                    windowless.append(p)
            except Exception:
                windowless.append(p)
    if windowless:
        time.sleep(1.5)  # os processos de fundo costumam sair junto com a janela principal
        for p in windowless:
            try:
                if p.is_running():
                    p.terminate()
                closed.add(p.info["name"])
            except psutil.NoSuchProcess:
                closed.add(p.info["name"])
            except psutil.AccessDenied:
                denied.add(p.info["name"])
            except Exception:
                continue
    if not found:
        _say(f"Não achei {name} aberto.")
        return False
    if denied - closed:  # ex.: o Gerenciador de Tarefas roda como administrador
        _say(f"Não consegui fechar {', '.join(sorted(denied - closed))}: roda como administrador.")
    if not closed:
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
on_alarm = None  # o Jarvis liga isto para o timer virar aviso falado no reator


def _alert(message):
    try:
        import winsound
        for _ in range(3):
            winsound.Beep(880, 300)
    except Exception:
        pass
    if on_alarm is not None:
        on_alarm(message)
        return
    print(f"\n⏰ Jarvis > {message}\nVocê > ", end="", flush=True)
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


EVERYTHING_CANDIDATES = [
    Path(r"G:\Jarvis\tools\Everything\Everything.exe"),
    Path(r"C:\Program Files\Everything\Everything.exe"),
    Path(r"C:\Program Files (x86)\Everything\Everything.exe"),
]
_everything_started = False


def start_everything():
    """Abre o Everything escondido (perto do relógio) se ele estiver fechado. Só tenta uma vez."""
    global _everything_started
    if _everything_started:
        return False
    _everything_started = True
    for exe in EVERYTHING_CANDIDATES:
        if exe.exists():
            try:
                subprocess.Popen([str(exe), "-startup"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return True
            except OSError:
                return False
    return False


def find_es():
    custom = os.environ.get("JARVIS_ES", "").strip()
    if custom and Path(custom).exists():
        return custom
    for path in ES_CANDIDATES:
        if path.exists():
            return str(path)
    return shutil.which("es")


def _decode(raw):
    for enc in ("utf-8", f"cp{_oem_cp()}", "mbcs", "cp1252"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def _oem_cp():
    try:
        return ctypes.windll.kernel32.GetOEMCP()  # 850 no Windows em português
    except Exception:
        return 850


def _excluded(path):
    low = path.lower()
    return any(x.lower() in low for x in EVERYTHING_EXCLUDE)


def _es_command(exe, terms, limit, out, wait_ms=0):
    """Linha de comando do es.exe como TEXTO. O es.exe lê as aspas do jeito dele (barra invertida não
    escapa nada), então a lista do subprocess, que vira \\", estragava as exclusões e zerava a busca."""
    parts = [f'"{exe}"', "-n", str(int(limit))]
    if wait_ms:
        parts += ["-timeout", str(int(wait_ms))]  # espera o Everything terminar de carregar o índice
    parts += ["-export-txt", f'"{out}"']  # o arquivo sai em UTF-8 (o console sairia na página 850)
    parts += terms + [f'!"{p}"' for p in EVERYTHING_EXCLUDE]
    return " ".join(parts)


def everything_search(query, limit=400, extension=None):
    """Caminhos achados pelo Everything, ou None se ele não estiver instalado/aberto."""
    exe = find_es()
    if not exe:
        return None
    if extension:
        terms = [f"ext:{extension.lstrip('.')}"]
    else:  # cada palavra entre aspas: "-foo" não vira opção do es.exe e |, !, <, > ficam literais
        terms = [t if re.match(r"^[a-z]+:", t, re.I) else f'"{t}"'
                 for t in str(query).replace('"', " ").split() if t]
    out = Path(tempfile.gettempdir()) / f"jarvis_es_{os.getpid()}_{threading.get_ident()}.txt"

    def ask(wait_ms=0):
        try:
            return subprocess.run(_es_command(exe, terms, limit * 2, out, wait_ms), capture_output=True, timeout=25,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            return None

    try:
        r = ask()
        if r is not None and r.returncode != 0 and start_everything():
            r = ask(wait_ms=20000)  # o -timeout espera a janela do Everything abrir e o índice carregar
        if r is None or r.returncode != 0:  # Everything fechado: o es.exe não consegue perguntar
            return None
        try:
            text = out.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            text = _decode(r.stdout or b"")
    finally:
        try:
            out.unlink()
        except OSError:
            pass
    paths = [line.strip() for line in text.splitlines() if line.strip()]
    return [p for p in paths if not _excluded(p)][:limit]  # sistema fica de fora mesmo se o filtro falhar


_drives = {}


def indexes_drive(drive):
    """O Everything indexa este disco? Por padrão ele só indexa discos NTFS fixos: num pendrive ou
    disco exFAT o "não achei" dele não vale. Pergunta uma vez por disco (None = sem Everything)."""
    key = str(drive)[:2].upper()
    if key not in _drives:
        found = everything_search(key + "\\", 1)
        if found is None:
            return None
        _drives[key] = bool(found)
    return _drives[key]


def warm_up_everything():
    """Abre o Everything ao ligar o Jarvis, para o índice estar pronto na primeira busca."""
    exe = find_es()
    if not exe:
        return
    try:
        r = subprocess.run(f'"{exe}" -n 1 jarvis', capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            start_everything()
    except (OSError, subprocess.TimeoutExpired):
        pass


# ------------------------- apps da Microsoft Store -------------------------
_store_apps = None
_store_lock = threading.Lock()


def store_apps():
    """Nome -> AppID dos apps do Menu Iniciar (inclui os da Store, que não têm .lnk). Lido uma vez."""
    global _store_apps
    with _store_lock:
        if _store_apps is not None:
            return _store_apps
        _store_apps = {}
        if os.name != "nt":
            return _store_apps
        cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
               "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                               capture_output=True, timeout=20,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            items = json.loads(r.stdout.decode("utf-8-sig", "replace") or "[]")
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return _store_apps
        for item in items if isinstance(items, list) else [items]:
            if isinstance(item, dict) and item.get("Name") and item.get("AppID"):
                _store_apps.setdefault(_norm(item["Name"]), (item["Name"], item["AppID"]))
        return _store_apps


def store_app(name):
    """(nome, AppID) do app com esse nome (ou bem parecido), ou None."""
    import difflib
    wanted = _norm(name)
    apps = store_apps()
    if not wanted or not apps:
        return None
    if wanted in apps:
        return apps[wanted]
    close = difflib.get_close_matches(wanted, list(apps), n=1, cutoff=0.85)
    return apps[close[0]] if close else None


# ========================= JANELAS DO PRÓPRIO JARVIS =========================
# Pedido digitado no reator ou no console deixa a janela do Jarvis na frente. Antes de digitar,
# apertar teclas ou fechar/minimizar, o Jarvis volta para a última janela do usuário.

_last_user_window = None


def foreground_window():
    try:
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


def is_jarvis_window(hwnd):
    """Reator, console do Jarvis ou Windows Terminal (onde o Jarvis costuma rodar)."""
    if not hwnd:
        return False
    try:
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        pid = ctypes.c_ulong()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return True
        console = k32.GetConsoleWindow()
        if console and hwnd in (console, u32.GetAncestor(console, 3)):  # 3 = GA_ROOTOWNER
            return True
        cls = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(hwnd, cls, 64)
        return cls.value == "CASCADIA_HOSTING_WINDOW_CLASS"
    except Exception:
        return False


# ========================= SEGUNDA TELA =========================
# O Jarvis fica em tela cheia na tela principal. O que ele abre (programa, pasta, navegador) vai para
# a segunda tela, se existir; senão abre por cima dele na mesma tela.

_expect_until = 0.0  # até quando a próxima janela nova é algo que o Jarvis abriu
_expect_from = None  # a janela da frente quando ele abriu


def monitors():
    """As telas: [(esquerda, cima, direita, baixo, é_a_principal)], área sem a barra de tarefas, em pixels."""
    try:
        from ctypes import wintypes
        u32 = ctypes.WinDLL("user32")

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        found = []
        PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                  ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

        def each(hmon, hdc, rect, data):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if u32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                w = info.rcWork
                found.append((w.left, w.top, w.right, w.bottom, bool(info.dwFlags & 1)))
            return True

        u32.EnumDisplayMonitors(None, None, PROC(each), 0)
        return found
    except Exception:
        return []


def second_monitor():
    """A área da segunda tela, ou None se só tem uma."""
    others = [m[:4] for m in monitors() if not m[4]]
    return others[0] if others else None


def _on_primary(hwnd):
    try:
        u32 = ctypes.windll.user32
        u32.MonitorFromWindow.restype = ctypes.c_void_p
        u32.MonitorFromPoint.restype = ctypes.c_void_p
        main = u32.MonitorFromPoint(ctypes.c_longlong(0), 1)  # o ponto (0,0) é sempre da tela principal
        return u32.MonitorFromWindow(ctypes.c_void_p(hwnd), 2) == main
    except Exception:
        return False


def move_to_second(hwnd):
    """Leva a janela para a segunda tela, maximizada. False se não tem segunda tela."""
    area = second_monitor()
    if not area or not hwnd:
        return False
    try:
        u32 = ctypes.windll.user32
        left, top, right, bottom = area
        u32.ShowWindow(hwnd, 9)  # SW_RESTORE: maximizada ela não sai do lugar
        u32.SetWindowPos(hwnd, None, left, top, right - left, bottom - top, 0x0014)  # NOZORDER | NOACTIVATE
        u32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        return True
    except Exception:
        return False


def expect_window(seconds=10.0):
    """O Jarvis acabou de abrir algo: a próxima janela nova que aparecer na tela principal vai para a segunda."""
    global _expect_until, _expect_from
    _expect_from = foreground_window()
    _expect_until = time.time() + seconds


def _maybe_move(hwnd):
    global _expect_until
    if time.time() > _expect_until or not hwnd or hwnd == _expect_from or is_jarvis_window(hwnd):
        return False
    _expect_until = 0.0
    return _on_primary(hwnd) and move_to_second(hwnd)


def track_focus(every=0.3):
    """Lembra qual foi a última janela do usuário (que não é do Jarvis) e manda para a segunda tela
    a janela que o Jarvis acabou de abrir."""
    if foreground_window() is None:
        return

    def loop():
        global _last_user_window
        while True:
            hwnd = foreground_window()
            if hwnd and not is_jarvis_window(hwnd):
                _last_user_window = hwnd
                _maybe_move(hwnd)
            time.sleep(every)

    threading.Thread(target=loop, daemon=True).start()


def _title(hwnd):
    try:
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


def user_window_title():
    """Título da janela em que o usuário estava (não a do Jarvis)."""
    hwnd = foreground_window()
    if hwnd and not is_jarvis_window(hwnd):
        return _title(hwnd)
    return _title(_last_user_window) if _last_user_window else ""


def leave_jarvis_window():
    """Se a janela da frente é do Jarvis, volta para a do usuário. False se não conseguiu."""
    hwnd = foreground_window()
    if hwnd is None or not is_jarvis_window(hwnd):
        return True
    target = _last_user_window
    try:
        u32 = ctypes.windll.user32
        if not target or not u32.IsWindow(target):
            return False
        if u32.IsIconic(target):
            u32.ShowWindow(target, 9)  # SW_RESTORE
        u32.keybd_event(0x12, 0, 0, 0)  # um toque no Alt libera o SetForegroundWindow
        u32.keybd_event(0x12, 0, 2, 0)
        u32.SetForegroundWindow(target)
    except Exception:
        return False
    time.sleep(0.3)
    return not is_jarvis_window(foreground_window())


def wait_new_window(before, timeout=8.0, least=1.0):
    """Depois de abrir um programa, espera a janela dele vir para a frente (no i3 pode levar uns segundos)."""
    if before is None:  # sem como olhar as janelas: espera um tempo fixo
        time.sleep(1.5)
        return False
    start = time.time()
    while time.time() - start < timeout:
        hwnd = foreground_window()
        if time.time() - start >= least and hwnd and hwnd != before and not is_jarvis_window(hwnd):
            time.sleep(0.4)  # a janela apareceu; espera ela aceitar teclado
            return True
        time.sleep(0.2)
    return False


# ========================= TEXTO E TECLADO =========================

def type_text(text):
    """Digita no programa da frente (via área de transferência, para acentos funcionarem)."""
    import pyautogui
    import pyperclip
    if not leave_jarvis_window():
        _say("Clique na janela onde devo digitar e peça de novo.")
        return False
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
    if not leave_jarvis_window():
        _say("Clique na janela onde devo apertar as teclas e peça de novo.")
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
