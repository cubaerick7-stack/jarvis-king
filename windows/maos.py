# -*- coding: utf-8 -*-
"""As mãos do Bolha: mexer em cada pedacinho do PC.

- Clicar em qualquer botão de qualquer programa pelo nome, ler o que está escrito numa janela e preencher campos
  (UI Automation do Windows, que a maioria dos programas informa). Se o programa não informa, usa o atalho de
  teclado conhecido e, por último, a visão (print + IA), que sempre pede confirmação antes de clicar.
- Janelas lado a lado, segunda tela e layouts salvos ("modo trabalho").
- Windows: Wi-Fi, Bluetooth, modo escuro, notificações, saída de som (fone/caixa), resolução, desligar a tela.
- Programas: instalar, atualizar e desinstalar pelo winget (sempre com "sim").
- Limpeza (temporários, lixeira, downloads velhos), limpador de memória (libera RAM sem fechar nada),
  "por que tá lento?", volume por programa, imprimir, histórico da área de transferência, atalhos por voz,
  organizar pasta, renomear em lote, compactar, converter, gravar e repetir macros, jogos da Steam/Epic,
  saúde do PC, programas novos que abrem com o Windows e desfazer a última ação de arquivo.

Tudo que apaga, instala, desinstala ou mexe em muitos arquivos pede "sim" antes (função confirm do Jarvis).
"""

import ctypes
import difflib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

CONFIG = Path(r"G:\Jarvis\config")
LAYOUTS = CONFIG / "layouts.json"
MACROS = CONFIG / "macros"
UNDO = CONFIG / "desfazer.json"
STARTUP_SNAPSHOT = CONFIG / "inicializacao.json"
TOOLS_DIR = Path(r"G:\Jarvis\tools")


def _say(text):
    print(f"Jarvis > {text}")


def norm(text):
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s.+-]", " ", text)).strip()


def _run(args, timeout=60, **kw):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kw)


def _ps(script, timeout=60):
    """Roda um PowerShell curto e devolve (código, saída)."""
    r = _run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
              "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script], timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return str(n)


def _user32():
    return ctypes.windll.user32


def _target_window():
    import ferramentas as F
    return F.user_target_window()


def _process_name(hwnd):
    try:
        import psutil
        pid = ctypes.c_ulong()
        _user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return psutil.Process(pid.value).name().lower().removesuffix(".exe")
    except Exception:
        return ""


# ========================= UI AUTOMATION (36, 37, 40, 12) =========================

_uia_cache = None
CLICKABLE = {50000: "botão", 50011: "menu", 50005: "link", 50019: "aba", 50007: "item", 50002: "caixa",
             50013: "opção", 50031: "botão", 50024: "item", 50003: "lista", 50010: "menu", 50020: "texto",
             50021: "barra", 50026: "grupo", 50025: "item"}
EDITABLE = {50004, 50003, 50030}  # Edit, ComboBox, Document
PATTERN_INVOKE, PATTERN_TOGGLE, PATTERN_SELECT, PATTERN_EXPAND = 10000, 10015, 10010, 10005
PATTERN_VALUE, PATTERN_TEXT = 10002, 10014
TREE_DESCENDANTS = 4
MAX_ELEMENTS = 1500


def uia():
    """(módulo, IUIAutomation) do Windows. Levanta RuntimeError fora do Windows."""
    global _uia_cache
    if _uia_cache is None:
        try:
            import comtypes
            import comtypes.client
            comtypes.CoInitialize()
            mod = comtypes.client.GetModule("UIAutomationCore.dll")
            auto = comtypes.client.CreateObject(mod.CUIAutomation, interface=mod.IUIAutomation)
        except Exception as e:
            raise RuntimeError(f"UI Automation indisponível ({e})") from e
        _uia_cache = (mod, auto)
    return _uia_cache


def _elements(hwnd, kinds=None, limit=MAX_ELEMENTS):
    """[(nome, tipo, elemento)] dos controles da janela (só os tipos pedidos)."""
    mod, auto = uia()
    root = auto.ElementFromHandle(hwnd)
    found = root.FindAll(TREE_DESCENDANTS, auto.CreateTrueCondition())
    out = []
    for i in range(min(found.Length, limit)):
        el = found.GetElement(i)
        try:
            ctype = el.CurrentControlType
            if kinds is not None and ctype not in kinds:
                continue
            if el.CurrentIsOffscreen and ctype not in (50011, 50010):
                continue
            name = (el.CurrentName or "").strip()
        except Exception:
            continue
        out.append((name, ctype, el))
    return out


def best_match(wanted, names, cutoff=0.72):
    """O índice do nome mais parecido com o pedido ("salvar" ~ "Salvar (Ctrl+S)"), ou None."""
    w = norm(wanted)
    best, score = None, 0.0
    for i, name in enumerate(names):
        n = norm(re.sub(r"\(.*?\)|\s+ctrl\+.*$|&", "", str(name), flags=re.I))
        if not n:
            continue
        if n == w:
            return i
        s = difflib.SequenceMatcher(None, w, n).ratio()
        if n.startswith(w + " ") or w.startswith(n + " ") or (len(w) >= 4 and w in n.split()):
            s = max(s, 0.85)
        if s > score:
            best, score = i, s
    return best if score >= cutoff else None


def _pattern(el, pattern_id, iface_name):
    mod, _ = uia()
    try:
        raw = el.GetCurrentPattern(pattern_id)
        if not raw:
            return None
        return raw.QueryInterface(getattr(mod, iface_name))
    except Exception:
        return None


def _press_element(el):
    """Aperta o controle do jeito que ele aceita: invocar, marcar, selecionar, expandir ou clique no meio."""
    for pid, iface, call in ((PATTERN_INVOKE, "IUIAutomationInvokePattern", "Invoke"),
                             (PATTERN_TOGGLE, "IUIAutomationTogglePattern", "Toggle"),
                             (PATTERN_SELECT, "IUIAutomationSelectionItemPattern", "Select"),
                             (PATTERN_EXPAND, "IUIAutomationExpandCollapsePattern", "Expand")):
        p = _pattern(el, pid, iface)
        if p is not None:
            try:
                getattr(p, call)()
                return True
            except Exception:
                continue
    try:
        r = el.CurrentBoundingRectangle
        import pyautogui
        pyautogui.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        return True
    except Exception:
        return False


# Atalhos de teclado conhecidos (49). Os do Word em português são outros (Ctrl+B salva, Ctrl+N é negrito).
SHORTCUTS = {
    "salvar": "ctrl+s", "salva": "ctrl+s", "salve": "ctrl+s", "desfazer": "ctrl+z", "desfaz": "ctrl+z",
    "refazer": "ctrl+y", "refaz": "ctrl+y", "nova aba": "ctrl+t", "fecha a aba": "ctrl+w", "fechar aba": "ctrl+w",
    "reabre a aba": "ctrl+shift+t", "reabrir aba": "ctrl+shift+t", "copiar": "ctrl+c", "copia": "ctrl+c",
    "colar": "ctrl+v", "cola": "ctrl+v", "recortar": "ctrl+x", "recorta": "ctrl+x", "selecionar tudo": "ctrl+a",
    "seleciona tudo": "ctrl+a", "imprimir": "ctrl+p", "imprime": "ctrl+p", "localizar": "ctrl+f",
    "procurar na pagina": "ctrl+f", "atualizar": "f5", "atualiza": "f5", "recarregar": "f5", "nova janela": "ctrl+n",
    "novo": "ctrl+n", "abrir": "ctrl+o", "aumentar zoom": "ctrl+plus", "diminuir zoom": "ctrl+minus",
    "zoom normal": "ctrl+0", "proxima aba": "ctrl+tab", "aba anterior": "ctrl+shift+tab", "tela cheia": "f11",
    "voltar pagina": "alt+left", "avancar pagina": "alt+right", "negrito": "ctrl+b", "italico": "ctrl+i",
    "sublinhado": "ctrl+u", "salvar como": "f12", "fechar": "alt+f4", "renomear": "f2",
    "nova pasta": "ctrl+shift+n", "historico": "ctrl+h", "downloads": "ctrl+j", "favoritar": "ctrl+d",
}
APP_SHORTCUTS = {
    "winword": {"salvar": "ctrl+b", "salva": "ctrl+b", "salve": "ctrl+b", "negrito": "ctrl+n", "sublinhado": "ctrl+s",
                "novo": "ctrl+o", "abrir": "ctrl+a", "selecionar tudo": "ctrl+t", "seleciona tudo": "ctrl+t",
                "localizar": "ctrl+l", "imprimir": "ctrl+p", "salvar como": "f12"},
    "excel": {"salvar": "ctrl+b", "salva": "ctrl+b", "negrito": "ctrl+n", "sublinhado": "ctrl+s", "novo": "ctrl+o",
              "abrir": "ctrl+a", "selecionar tudo": "ctrl+t", "seleciona tudo": "ctrl+t", "localizar": "ctrl+l"},
    "powerpnt": {"salvar": "ctrl+b", "salva": "ctrl+b", "negrito": "ctrl+n", "sublinhado": "ctrl+s", "novo": "ctrl+o",
                 "abrir": "ctrl+a"},
    "explorer": {"novo": "ctrl+n", "renomear": "f2", "nova pasta": "ctrl+shift+n"},
}


def shortcut_for(action, process=""):
    a = norm(action)
    return APP_SHORTCUTS.get(process, {}).get(a) or SHORTCUTS.get(a)


def press(keys):
    """Aperta um atalho na janela do senhor (nunca na do Bolha)."""
    import ferramentas as F
    return F.press_keys(keys)


def app_shortcut(action):
    """ "salva", "desfaz", "nova aba"... no programa da frente, com o atalho certo para ele."""
    hwnd = _target_window()
    keys = shortcut_for(action, _process_name(hwnd) if hwnd else "")
    if not keys:
        _say(f"Não conheço o atalho de \"{action}\".")
        return False
    return press(keys)


def click_ui(name, vision=None, confirm=None):
    """Clica no botão/menu/link chamado <name> no programa da frente.
    1) UI Automation; 2) atalho de teclado conhecido ("Salvar" = Ctrl+S); 3) visão (print + IA, com confirmação)."""
    name = str(name or "").strip()
    if not name:
        _say("Em que eu clico, senhor?")
        return False
    hwnd = _target_window()
    if not hwnd:
        _say("Não sei em que janela clicar: clique no programa e peça de novo.")
        return False
    try:
        items = _elements(hwnd, set(CLICKABLE))
        i = best_match(name, [n for n, _, _ in items])
        if i is not None:
            label, ctype, el = items[i]
            import ferramentas as F
            F.leave_jarvis_window()
            if _press_element(el):
                _say(f"Cliquei em {label} ({CLICKABLE.get(ctype, 'controle')}).")
                return True
    except RuntimeError as e:
        if os.name == "nt":
            _say(f"({e})")
    keys = shortcut_for(name, _process_name(hwnd))
    if keys:
        return press(keys)
    if vision is not None:
        return vision_click(name, vision, confirm)
    _say(f"Não achei \"{name}\" nessa janela.")
    return False


def read_window(max_chars=5000):
    """O que está escrito na janela da frente (títulos, textos, campos e o documento), para a IA entender."""
    hwnd = _target_window()
    if not hwnd:
        _say("Não sei qual janela ler.")
        return False
    import ferramentas as F
    title = F._title(hwnd)
    lines = []
    try:
        for name, ctype, el in _elements(hwnd):
            text = name
            if ctype in EDITABLE:
                p = _pattern(el, PATTERN_TEXT, "IUIAutomationTextPattern")
                if p is not None:
                    try:
                        text = p.DocumentRange.GetText(max_chars)
                    except Exception:
                        pass
                if not text:
                    v = _pattern(el, PATTERN_VALUE, "IUIAutomationValuePattern")
                    try:
                        text = v.CurrentValue if v is not None else ""
                    except Exception:
                        text = ""
            text = str(text or "").strip()
            if text and text not in lines:
                lines.append(text)
            if sum(len(x) for x in lines) > max_chars:
                break
    except RuntimeError as e:
        _say(f"Não consigo ler janelas aqui ({e}).")
        return False
    if not lines:
        _say(f"A janela {title} não informa o texto dela. Posso olhar pela tela: diga \"o que é isso na tela\".")
        return False
    _say(f"Na janela {title} está escrito:")
    text = "\n".join(lines)[:max_chars]
    print(text)
    return text


def list_controls(limit=40):
    """Os botões e menus da janela da frente (para o modo agente escolher onde clicar)."""
    hwnd = _target_window()
    if not hwnd:
        _say("Não sei qual janela olhar.")
        return False
    try:
        items = [(n, c) for n, c, _ in _elements(hwnd, set(CLICKABLE)) if n]
    except RuntimeError as e:
        _say(f"Não consigo ver os botões aqui ({e}).")
        return False
    seen, out = set(), []
    for n, c in items:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(f"{n} ({CLICKABLE.get(c, 'controle')})")
    _say(f"Botões e menus da janela ({len(out)}):")
    for line in out[:limit]:
        print(f"  - {line}")
    return out[:limit]


def fill_field(field, text):
    """Escreve num campo do programa da frente (40). field vazio = o campo com o cursor ou o primeiro campo."""
    hwnd = _target_window()
    if not hwnd:
        _say("Não sei em que janela escrever.")
        return False
    try:
        edits = _elements(hwnd, EDITABLE)
    except RuntimeError:
        edits = []
    target = None
    if edits:
        if str(field or "").strip():
            i = best_match(field, [n for n, _, _ in edits], cutoff=0.6)
            target = edits[i][2] if i is not None else None
        else:
            target = edits[0][2]
    if target is not None:
        v = _pattern(target, PATTERN_VALUE, "IUIAutomationValuePattern")
        if v is not None:
            try:
                v.SetValue(str(text))
                _say(f"Escrevi no campo {field or ''}.".replace("  ", " ").replace(" .", "."))
                return True
            except Exception:
                pass
        try:
            target.SetFocus()
        except Exception:
            pass
    import ferramentas as F
    return F.type_text(text)


# ------------------------- visão de reserva (38) -------------------------

VISION_PROMPT = ("Na imagem (print da tela, {w}x{h} pixels) ache o botão, link, ícone ou campo chamado \"{name}\". "
                 "Responda SÓ um JSON: {{\"achou\": true, \"x\": 0, \"y\": 0, \"descricao\": \"o que é\"}} com o CENTRO "
                 "dele em pixels da imagem, ou {{\"achou\": false}} se não estiver na tela.")


def vision_click(name, vision, confirm):
    """Print + IA acha o botão quando o programa não informa (jogos, apps estranhos). Sempre confirma antes."""
    try:
        import mss
        import mss.tools
        with (getattr(mss, "MSS", None) or mss.mss)() as sct:
            mon = sct.monitors[1]
            shot = sct.grab(mon)
            png = mss.tools.to_png(shot.rgb, shot.size)
    except Exception as e:
        _say(f"Não consegui olhar a tela: {e}.")
        return False
    try:
        raw = vision(VISION_PROMPT.format(w=shot.size[0], h=shot.size[1], name=name), png, "image/png")
        m = re.search(r"\{.*\}", str(raw), re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception as e:
        _say(f"A visão não respondeu: {e}.")
        return False
    if not data.get("achou"):
        _say(f"Não vi \"{name}\" na tela.")
        return False
    try:
        x, y = int(data["x"]) + mon["left"], int(data["y"]) + mon["top"]
    except (KeyError, TypeError, ValueError):
        _say("A visão respondeu sem a posição.")
        return False
    what = str(data.get("descricao") or name)[:80]
    if confirm is None or not confirm(f"Achei {what} pela tela. Clico ali?"):
        _say("Ok, não cliquei.")
        return False
    import pyautogui
    pyautogui.click(x, y)
    _say(f"Cliquei em {what}.")
    return True


# ========================= JANELAS E LAYOUTS (16, 41) =========================

def _work_area():
    """A área útil da tela principal (sem a barra de tarefas)."""
    import ferramentas as F
    for m in F.monitors():
        if m[4]:
            return m[:4]
    from ctypes import wintypes
    r = wintypes.RECT()
    _user32().SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
    return r.left, r.top, r.right, r.bottom


def _find_windows(title):
    """Janelas visíveis cujo título ou programa combina com o pedido."""
    import pygetwindow
    want = norm(title)
    out = []
    for w in pygetwindow.getAllWindows():
        if not w.title:
            continue
        hwnd = getattr(w, "_hWnd", None)
        hay = norm(w.title) + " " + (_process_name(hwnd) if hwnd else "")
        if want and want in hay:
            out.append(w)
    return out


def _place(hwnd, left, top, width, height):
    u32 = _user32()
    u32.ShowWindow(hwnd, 9)  # SW_RESTORE
    u32.MoveWindow(hwnd, int(left), int(top), int(width), int(height), True)


def side_by_side(first, second=""):
    """Duas janelas lado a lado na tela principal ("o Chrome e o Word lado a lado")."""
    left, top, right, bottom = _work_area()
    half = (right - left) // 2
    picked = []
    for name in (first, second):
        if name:
            found = _find_windows(name)
            if not found:
                _say(f"Não achei a janela {name}.")
                return False
            picked.append(found[0])
    if len(picked) == 1:  # só uma: a que ele pediu na esquerda e a anterior do senhor na direita
        other = _target_window()
        hwnd = getattr(picked[0], "_hWnd", None)
        if other and other != hwnd:
            import pygetwindow
            picked += [w for w in pygetwindow.getAllWindows() if getattr(w, "_hWnd", None) == other][:1]
    if not picked:
        _say("Quais janelas eu coloco lado a lado?")
        return False
    for i, w in enumerate(picked[:2]):
        _place(w._hWnd, left + i * half, top, half, bottom - top)
    _say("Pronto, lado a lado: " + " e ".join(w.title[:40] for w in picked[:2]) + ".")
    return True


def to_second_screen(title=""):
    import ferramentas as F
    hwnd = _find_windows(title)[0]._hWnd if title and _find_windows(title) else _target_window()
    if not hwnd:
        _say("Qual janela eu mando para a outra tela?")
        return False
    if not F.move_to_second(hwnd):
        _say("Só achei uma tela ligada.")
        return False
    _say("Mandei para a segunda tela.")
    return True


def window_state(action, title=""):
    hwnd = _find_windows(title)[0]._hWnd if title and _find_windows(title) else _target_window()
    if not hwnd:
        _say("Qual janela?")
        return False
    codes = {"maximizar": 3, "minimizar": 6, "restaurar": 9}
    code = codes.get(norm(action))
    if code is None:
        return False
    _user32().ShowWindow(hwnd, code)
    _say(f"Janela: {action}.")
    return True


def _visible_windows():
    """[(hwnd, título, programa, caminho do exe, retângulo, maximizada)] das janelas do senhor."""
    import ferramentas as F
    import pygetwindow
    import psutil
    out = []
    for w in pygetwindow.getAllWindows():
        hwnd = getattr(w, "_hWnd", None)
        if not hwnd or not w.title.strip() or F.is_jarvis_window(hwnd) or not _user32().IsWindowVisible(hwnd):
            continue
        if w.title in ("Program Manager", "Configurações", "Settings") or w.width < 120:
            continue
        try:
            pid = ctypes.c_ulong()
            _user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = psutil.Process(pid.value)
            exe, name = proc.exe(), proc.name().lower().removesuffix(".exe")
        except Exception:
            exe, name = "", ""
        out.append((hwnd, w.title, name, exe, (w.left, w.top, w.width, w.height), bool(_user32().IsZoomed(hwnd))))
    return out


def _load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def save_layout(name):
    """Guarda onde está cada janela agora ("salva esse layout como trabalho")."""
    name = norm(name) or "padrao"
    wins = [{"programa": p, "exe": exe, "titulo": t, "ret": list(r), "max": m} for _, t, p, exe, r, m in _visible_windows()]
    if not wins:
        _say("Não achei janelas para guardar.")
        return False
    layouts = _load_json(LAYOUTS, {})
    layouts[name] = wins
    _save_json(LAYOUTS, layouts)
    _say(f"Layout {name} guardado com {len(wins)} janelas. Diga \"layout {name}\" para voltar a ele.")
    return True


def apply_layout(name, wait=8.0):
    """Arruma as janelas como estavam no layout; abre o que estiver fechado."""
    layouts = _load_json(LAYOUTS, {})
    key = norm(name)
    saved = layouts.get(key) or next((v for k, v in layouts.items() if key and key in k), None)
    if not saved:
        _say(f"Não tenho o layout {name}. Arrume as janelas e diga \"salva esse layout como {name}\".")
        return False
    now = _visible_windows()
    started = []
    for item in saved:
        if not any(p == item["programa"] for _, _, p, _, _, _ in now) and item.get("exe") and Path(item["exe"]).exists():
            try:
                subprocess.Popen([item["exe"]])
                started.append(item["programa"])
            except OSError:
                pass
    if started:
        end = time.time() + wait
        while time.time() < end and not all(any(p == s for _, _, p, _, _, _ in _visible_windows()) for s in started):
            time.sleep(0.5)
        now = _visible_windows()
    used, placed = set(), 0
    for item in saved:
        match = next((w for w in now if w[0] not in used and w[2] == item["programa"]
                      and (norm(item["titulo"])[:15] in norm(w[1]) or True)), None)
        if match is None:
            continue
        used.add(match[0])
        x, y, w, h = item["ret"]
        _place(match[0], x, y, w, h)
        if item.get("max"):
            _user32().ShowWindow(match[0], 3)
        placed += 1
    _say(f"Layout {key or name}: arrumei {placed} janela{'s' if placed != 1 else ''}"
         + (f" e abri {', '.join(started)}" if started else "") + ".")
    return placed > 0 or bool(started)


# ========================= WINDOWS (42) =========================

RADIO_PS = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
Function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioAccessStatus,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
$r = $radios | ? { $_.Kind -eq '__KIND__' } | Select-Object -First 1
if (-not $r) { Write-Output 'SEM'; exit 2 }
[Windows.Devices.Radios.RadioState,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
Await ($r.SetStateAsync('__STATE__')) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
Write-Output $r.State
"""


def radio(kind, on):
    """Liga/desliga o Wi-Fi ou o Bluetooth (sem precisar de administrador)."""
    k = "WiFi" if norm(kind) in ("wifi", "wi-fi", "wi fi", "internet sem fio") else "Bluetooth"
    script = RADIO_PS.replace("__KIND__", k).replace("__STATE__", "On" if on else "Off")
    try:
        code, out = _ps(script, timeout=30)
    except Exception as e:
        _say(f"Não consegui mexer no {k}: {e}.")
        return False
    label = "Wi-Fi" if k == "WiFi" else "Bluetooth"
    if "SEM" in out:
        _say(f"Este PC não tem {label}.")
        return False
    if code != 0:
        _say(f"O Windows não deixou mudar o {label}. Abro as configurações?")
        return False
    _say(f"{label} {'ligado' if on else 'desligado'}.")
    return True


THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def dark_mode(on=True):
    """Modo escuro (ou claro) para o Windows e os apps."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "AppsUseLightTheme", 0, winreg.REG_DWORD, 0 if on else 1)
            winreg.SetValueEx(k, "SystemUsesLightTheme", 0, winreg.REG_DWORD, 0 if on else 1)
        _user32().SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet", 2, 1000, None)  # avisa os programas
    except Exception as e:
        _say(f"Não consegui mudar o tema: {e}.")
        return False
    _say(f"Modo {'escuro' if on else 'claro'} ligado.")
    return True


def windows_notifications(on):
    """Liga/desliga os avisos (banners) do Windows: o não perturbe do sistema."""
    try:
        import winreg
        path = r"Software\Microsoft\Windows\CurrentVersion\PushNotifications"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
            winreg.SetValueEx(k, "ToastEnabled", 0, winreg.REG_DWORD, 1 if on else 0)
    except Exception as e:
        _say(f"Não consegui mudar as notificações do Windows: {e}.")
        return False
    return True


def audio_devices():
    """[(nome, id)] das saídas de som ligadas."""
    from pycaw.pycaw import AudioUtilities
    out = []
    for d in AudioUtilities.GetAllDevices():
        try:
            state = str(getattr(d, "state", ""))
            if "Active" not in state and state not in ("1", "AudioDeviceState.Active"):
                continue
            if not str(d.id).startswith("{0.0.0."):  # 0.0.0 = saída; 0.0.1 = microfone
                continue
            out.append((d.FriendlyName, d.id))
        except Exception:
            continue
    return out


AUDIO_WORDS = {"fone": ["fone", "headset", "headphone", "earphone", "auricular", "airpods", "buds"],
               "caixa": ["alto-falante", "alto falante", "speaker", "caixa", "realtek", "monitor", "hdmi", "tv"]}


def _set_default_audio(device_id):
    import comtypes
    from comtypes import GUID, COMMETHOD, HRESULT
    from ctypes import c_int, c_wchar_p, c_void_p

    class IPolicyConfig(comtypes.IUnknown):
        _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
        _methods_ = [COMMETHOD([], HRESULT, f"Unused{i}", (["in"], c_void_p, "a")) for i in range(10)] + [
            COMMETHOD([], HRESULT, "SetDefaultEndpoint", (["in"], c_wchar_p, "id"), (["in"], c_int, "role"))]

    comtypes.CoInitialize()
    policy = comtypes.CoCreateInstance(GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}"), IPolicyConfig,
                                       comtypes.CLSCTX_ALL)
    for role in (0, 1, 2):  # console, multimídia, comunicação
        policy.SetDefaultEndpoint(device_id, role)


def audio_output(which):
    """Troca a saída de som: "fone", "caixa" ou o nome do aparelho."""
    try:
        devices = audio_devices()
    except Exception as e:
        _say(f"Não consegui ver as saídas de som: {e}.")
        return False
    if not devices:
        _say("Não achei saídas de som ligadas.")
        return False
    want = norm(which)
    words = AUDIO_WORDS.get(want, [want])
    pick = next((d for d in devices if any(w in norm(d[0]) for w in words)), None)
    if pick is None:
        i = best_match(want, [d[0] for d in devices], cutoff=0.5)
        pick = devices[i] if i is not None else None
    if pick is None:
        _say("Não achei essa saída. Tenho: " + "; ".join(d[0] for d in devices) + ".")
        return False
    try:
        _set_default_audio(pick[1])
    except Exception as e:
        _say(f"O Windows não deixou trocar a saída de som: {e}.")
        return False
    _say(f"Som saindo agora em: {pick[0]}.")
    return True


def set_resolution(width, height):
    """Muda a resolução da tela principal (só para uma que o monitor aceita)."""
    from ctypes import wintypes

    class DEVMODE(ctypes.Structure):
        _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                    ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD),
                    ("dmFields", wintypes.DWORD), ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
                    ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
                    ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                    ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short), ("dmFormName", wintypes.WCHAR * 32),
                    ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                    ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                    ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD),
                    ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD),
                    ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
                    ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD)]

    width, height = int(width), int(height)
    u32 = _user32()
    modes, i = set(), 0
    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(DEVMODE)
    while u32.EnumDisplaySettingsW(None, i, ctypes.byref(dm)):
        modes.add((dm.dmPelsWidth, dm.dmPelsHeight))
        i += 1
    if (width, height) not in modes:
        best = sorted(modes, key=lambda m: -m[0] * m[1])[:4]
        _say(f"A tela não aceita {width}x{height}. Aceita, por exemplo: " + ", ".join(f"{a}x{b}" for a, b in best) + ".")
        return False
    u32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm))  # ENUM_CURRENT_SETTINGS
    dm.dmPelsWidth, dm.dmPelsHeight = width, height
    dm.dmFields = 0x00080000 | 0x00100000  # DM_PELSWIDTH | DM_PELSHEIGHT
    if u32.ChangeDisplaySettingsW(ctypes.byref(dm), 0) != 0:
        _say("O Windows não aceitou a resolução.")
        return False
    _say(f"Resolução em {width}x{height}.")
    return True


def screen_off():
    """Apaga o monitor (volta mexendo no mouse)."""
    try:
        _user32().PostMessageW(0xFFFF, 0x0112, 0xF170, 2)  # HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, desliga
    except Exception as e:
        _say(f"Não consegui apagar a tela: {e}.")
        return False
    _say("Tela apagada. É só mexer no mouse para voltar.")
    return True


# ========================= PROGRAMAS PELO WINGET (18, 43, 44) =========================

def winget_path():
    return shutil.which("winget") or ""


def parse_winget_table(text):
    """A tabela do winget (Nome, ID, Versão...) em lista de dicionários, pelas posições do cabeçalho."""
    lines = [line.rstrip() for line in str(text).replace("\r", "\n").splitlines()]
    for i, line in enumerate(lines):
        if re.match(r"^-{5,}\s*$", line.strip()) and i > 0:
            header = lines[i - 1]
            cols = [(m.group(0), m.start()) for m in re.finditer(r"\S+", header)]
            cols = [(norm(name), start) for name, start in cols]
            out = []
            for row in lines[i + 1:]:
                if not row.strip() or re.match(r"^\d+ (?:upgrades?|atualiza)", row.strip(), re.I):
                    continue
                item = {}
                for j, (name, start) in enumerate(cols):
                    end = cols[j + 1][1] if j + 1 < len(cols) else None
                    item[name] = row[start:end].strip() if len(row) > start else ""
                out.append(item)
            return out
    return []


def _col(item, *names):
    for n in names:
        for k, v in item.items():
            if k.startswith(n):
                return v
    return ""


WINGET_FLAGS = ["--accept-source-agreements", "--disable-interactivity"]


def winget_search(name):
    r = _run([winget_path(), "search", str(name), *WINGET_FLAGS], timeout=90)
    return [{"nome": _col(i, "nome", "name"), "id": _col(i, "id"), "versao": _col(i, "vers")}
            for i in parse_winget_table(r.stdout) if _col(i, "id")]


def install_program(name, confirm):
    if not winget_path():
        _say("Não achei o winget neste Windows (ele vem com o Instalador de Aplicativos da Microsoft Store).")
        return False
    found = winget_search(name)
    if not found:
        _say(f"Não achei {name} no winget.")
        return False
    want = norm(name)
    pick = next((f for f in found if norm(f["nome"]) == want), found[0])
    if not confirm(f"Instalo {pick['nome']} ({pick['id']}), senhor?"):
        _say("Ok, não instalei.")
        return False
    _say(f"Instalando {pick['nome']}... pode levar uns minutos.")
    r = _run([winget_path(), "install", "--id", pick["id"], "-e", "--silent", "--accept-package-agreements",
              *WINGET_FLAGS], timeout=1800)
    if r.returncode != 0:
        _say(f"O winget não conseguiu instalar ({(r.stdout or r.stderr).strip().splitlines()[-1:] or ['erro']}).")
        return False
    _say(f"{pick['nome']} instalado.")
    return True


def upgradable():
    r = _run([winget_path(), "upgrade", *WINGET_FLAGS], timeout=120)
    return [{"nome": _col(i, "nome", "name"), "id": _col(i, "id"), "de": _col(i, "vers"), "para": _col(i, "dispon", "avail")}
            for i in parse_winget_table(r.stdout) if _col(i, "id")]


def update_programs(confirm, name=""):
    """Atualiza um programa ou todos os que têm atualização (sempre pergunta)."""
    if not winget_path():
        _say("Não achei o winget neste Windows.")
        return False
    items = upgradable()
    if name:
        items = [i for i in items if norm(name) in norm(i["nome"]) or norm(name) in norm(i["id"])]
    if not items:
        _say("Está tudo atualizado, senhor." if not name else f"Não há atualização para {name}.")
        return True
    for i in items[:12]:
        print(f"  - {i['nome']}: {i['de']} -> {i['para']}")
    if not confirm(f"Atualizo {len(items)} programa{'s' if len(items) > 1 else ''}?"):
        _say("Ok, não atualizei.")
        return False
    ok = 0
    for i in items:
        r = _run([winget_path(), "upgrade", "--id", i["id"], "-e", "--silent", "--accept-package-agreements",
                  *WINGET_FLAGS], timeout=1800)
        ok += r.returncode == 0
    _say(f"Atualizei {ok} de {len(items)}.")
    return ok > 0


def uninstall_program(name, confirm):
    if not winget_path():
        _say("Não achei o winget neste Windows.")
        return False
    r = _run([winget_path(), "list", "--name", str(name), *WINGET_FLAGS], timeout=90)
    found = [{"nome": _col(i, "nome", "name"), "id": _col(i, "id")} for i in parse_winget_table(r.stdout) if _col(i, "id")]
    if not found:
        _say(f"Não achei {name} instalado.")
        return False
    pick = found[0]
    if not confirm(f"Desinstalo {pick['nome']}? Isso apaga o programa."):
        _say("Ok, não desinstalei.")
        return False
    r = _run([winget_path(), "uninstall", "--id", pick["id"], "-e", "--silent", *WINGET_FLAGS], timeout=900)
    if r.returncode != 0:
        _say("O winget não conseguiu desinstalar.")
        return False
    _say(f"{pick['nome']} desinstalado.")
    return True


# ========================= LIMPEZA (45) E MEMÓRIA (11) =========================

def _folder_size(folder, older_than=None):
    total, files = 0, []
    limit = time.time() - older_than if older_than else None
    for root, _, names in os.walk(folder, onerror=lambda e: None):
        for n in names:
            p = Path(root) / n
            try:
                st = p.stat()
            except OSError:
                continue
            if limit and st.st_mtime > limit:
                continue
            total += st.st_size
            files.append(p)
    return total, files


def _recycle_size():
    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    try:
        ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        return info.i64Size, info.i64NumItems
    except Exception:
        return 0, 0


def cleanup(confirm, temp=True, recycle=True):
    """Apaga temporários (com mais de 1 dia) e esvazia a Lixeira. Mostra quanto vai liberar e pergunta antes."""
    temp_dirs = [Path(os.environ.get("TEMP", "")), Path(os.environ.get("LOCALAPPDATA", "")) / "Temp"]
    temp_dirs = list({str(p).lower(): p for p in temp_dirs if str(p) and p.is_dir()}.values())
    temp_size, temp_files = 0, []
    if temp:
        for d in temp_dirs:
            size, files = _folder_size(d, older_than=86400)
            temp_size += size
            temp_files += files
    bin_size, bin_items = _recycle_size() if recycle else (0, 0)
    total = temp_size + bin_size
    if total < 1024 * 1024:
        _say("Não tem quase nada para limpar, senhor.")
        return True
    if not confirm(f"Posso liberar {_size(total)}: temporários {_size(temp_size)} e Lixeira {_size(bin_size)} "
                   f"({bin_items} itens). Limpo?"):
        _say("Ok, não limpei.")
        return False
    freed = 0
    for f in temp_files:
        try:
            size = f.stat().st_size
            f.unlink()
            freed += size
        except OSError:
            continue  # arquivo em uso: fica
    if recycle and bin_items:
        try:
            if ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4) in (0, -2147418113):
                freed += bin_size
        except Exception:
            pass
    _say(f"Limpeza feita: liberei {_size(freed)}.")
    return True


def old_downloads(days=90, downloads=None):
    """Arquivos da pasta Downloads sem mexer há mais de N dias (só lista; apagar é com "sim")."""
    folder = Path(downloads or Path.home() / "Downloads")
    limit = time.time() - days * 86400
    items = []
    try:
        for p in folder.iterdir():
            try:
                st = p.stat()
                if st.st_mtime < limit:
                    items.append((p, st.st_size if p.is_file() else _folder_size(p)[0]))
            except OSError:
                continue
    except OSError:
        return []
    return sorted(items, key=lambda x: -x[1])


def clean_old_downloads(confirm, days=90, downloads=None):
    import ferramentas as F
    items = old_downloads(days, downloads)
    if not items:
        _say(f"Nada na pasta Downloads com mais de {days} dias.")
        return True
    total = sum(s for _, s in items)
    for p, s in items[:10]:
        print(f"  - {p.name} ({_size(s)})")
    if not confirm(f"Mando {len(items)} itens velhos dos Downloads ({_size(total)}) para a Lixeira?"):
        _say("Ok, deixei lá.")
        return False
    moved = sum(1 for p, _ in items if F.send_to_recycle_bin(p, lambda q: True))
    _say(f"Mandei {moved} itens para a Lixeira ({_size(total)}).")
    return True


def _working_sets():
    import psutil
    total = 0
    for p in psutil.process_iter(["memory_info"]):
        try:
            total += p.info["memory_info"].rss
        except Exception:
            continue
    return total


def clean_memory():
    """Limpador de memória (11): pede a todo programa para devolver a RAM que não está usando agora
    (EmptyWorkingSet). Não fecha nada; o que for preciso volta sozinho. Mostra antes e depois."""
    import psutil
    before_ram, before_ws = psutil.virtual_memory(), _working_sets()
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    done = 0
    for p in psutil.process_iter(["pid"]):
        h = k32.OpenProcess(0x0100 | 0x0400 | 0x0010, False, p.info["pid"])  # SET_QUOTA | QUERY_INFORMATION | VM_READ
        if not h:
            continue
        try:
            done += bool(psapi.EmptyWorkingSet(h))
        finally:
            k32.CloseHandle(h)
    time.sleep(1.0)
    after_ram, after_ws = psutil.virtual_memory(), _working_sets()
    freed = max(0, before_ws - after_ws)
    _say(f"Memória limpa: antes {before_ram.percent:.0f}% em uso ({_size(before_ram.total - before_ram.available)}), "
         f"agora {after_ram.percent:.0f}% ({_size(after_ram.total - after_ram.available)}). "
         f"Os {done} programas devolveram {_size(freed)} sem fechar nada.")
    return {"antes": before_ram.percent, "depois": after_ram.percent, "liberado_mb": freed // (1024 * 1024)}


# ========================= POR QUE TÁ LENTO? (17, 46) =========================

COMMON = {"chrome", "msedge", "firefox", "opera", "brave", "spotify", "discord", "teams", "ms-teams", "whatsapp",
          "steam", "epicgameslauncher", "winword", "excel", "powerpnt", "notepad", "code", "obs64", "vlc",
          "telegram", "zoom", "slack"}


def heavy_processes(sample=1.0):
    """[(nome, cpu%, memória em MB, pids)] somando os processos do mesmo programa, do mais pesado ao mais leve."""
    import psutil
    procs = list(psutil.process_iter(["name", "pid"]))
    for p in procs:
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    time.sleep(sample)
    cores = psutil.cpu_count() or 1
    groups = {}
    for p in procs:
        try:
            name = (p.info["name"] or "").lower().removesuffix(".exe")
            if not name or name in ("system idle process", "idle", "system"):
                continue
            g = groups.setdefault(name, [0.0, 0, []])
            g[0] += p.cpu_percent(None) / cores
            g[1] += p.memory_info().rss
            g[2].append(p.pid)
        except Exception:
            continue
    return sorted(((n, c, m // (1024 * 1024), pids) for n, (c, m, pids) in groups.items()),
                  key=lambda x: -(x[1] * 40 + x[2] / 50))


def why_slow(confirm, close=None):
    """Diz o culpado da lentidão (CPU, memória, disco) e oferece fechar."""
    import psutil
    import ferramentas as F
    procs = heavy_processes()
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.3)
    disk = shutil.disk_usage(Path.home().anchor or "/")
    mine = {"python", "pythonw", "py"}
    candidates = [p for p in procs if p[0] not in F.PROTECTED_PROCESSES and p[0] not in mine]
    _say(f"Processador em {cpu:.0f}%, memória em {mem.percent:.0f}%, disco com {_size(disk.free)} livres.")
    for n, c, m, _ in procs[:6]:
        print(f"  - {n}: CPU {c:.0f}%, {m} MB")
    if not candidates:
        _say("Não achei um culpado claro.")
        return True
    name, c, m, pids = candidates[0]
    reasons = []
    if c >= 20:
        reasons.append(f"usa {c:.0f}% do processador")
    if m >= 800:
        reasons.append(f"ocupa {_size(m * 1024 * 1024)} de memória")
    if disk.free < 5 * 1024 ** 3:
        _say("Atenção: o disco está quase cheio, isso deixa tudo lento. Diga \"limpa o PC\".")
    if not reasons and mem.percent < 85 and cpu < 70:
        _say("O PC não parece sobrecarregado agora.")
        return True
    if not reasons:
        reasons.append(f"é o que mais pesa ({m} MB)")
    _say(f"O culpado parece ser {name}: {' e '.join(reasons)}.")
    question = f"Fecho o {name}?" if name in COMMON else f"Fecho o {name}? Não é um programa comum, confira antes."
    if confirm(question):
        return (close or F.close_app)(name)
    _say("Ok, deixei aberto.")
    return True


# ========================= VOLUME POR PROGRAMA (52) =========================

def _sessions():
    from pycaw.pycaw import AudioUtilities
    out = []
    for s in AudioUtilities.GetAllSessions():
        try:
            if s.Process:
                out.append((s.Process.name().lower().removesuffix(".exe"), s))
        except Exception:
            continue
    return out


def app_volume(app, percent=None, delta=None):
    """Volume de um programa só ("Discord mais alto", "jogo em 30")."""
    try:
        sessions = _sessions()
    except Exception as e:
        _say(f"Não consegui ver o som dos programas: {e}.")
        return False
    want = norm(app).replace(" ", "")
    import ferramentas as F
    names = F.PROCESS_ALIASES.get(norm(app), [want])
    hits = [(n, s) for n, s in sessions if any(n.startswith(x) or x in n for x in names)]
    if not hits:
        playing = ", ".join(sorted({n for n, _ in sessions})) or "nenhum"
        _say(f"{app} não está tocando som agora. Tocando: {playing}.")
        return False
    for _, s in hits:
        vol = s.SimpleAudioVolume
        now = vol.GetMasterVolume() * 100
        new = percent if percent is not None else now + (delta or 0)
        vol.SetMasterVolume(max(0.0, min(100.0, float(new))) / 100, None)
    final = max(0, min(100, int(round(new))))
    _say(f"Volume do {hits[0][0]} em {final}%.")
    return final


# ========================= IMPRIMIR (47) =========================

def print_file(path):
    path = Path(path)
    if not path.is_file():
        _say(f"Não achei o arquivo {path}.")
        return False
    try:
        os.startfile(str(path), "print")
    except OSError as e:
        _say(f"Não consegui mandar para a impressora: {e}.")
        return False
    _say(f"Mandei {path.name} para a impressora padrão.")
    return True


# ========================= ÁREA DE TRANSFERÊNCIA (48) =========================

CLIP_MAX = 20
clip_history = []  # só na memória do programa (nunca em disco: pode ter senha copiada)


def watch_clipboard(every=1.0):
    def loop():
        try:
            import pyperclip
        except ImportError:
            return
        last = None
        while True:
            try:
                text = pyperclip.paste()
                if text and text != last and len(text) < 20000:
                    last = text
                    if text in clip_history:
                        clip_history.remove(text)
                    clip_history.insert(0, text)
                    del clip_history[CLIP_MAX:]
            except Exception:
                pass
            time.sleep(every)
    threading.Thread(target=loop, daemon=True).start()


def clipboard_list():
    if not clip_history:
        _say("Ainda não guardei nada do que o senhor copiou.")
        return True
    _say("O que o senhor copiou por último:")
    for i, t in enumerate(clip_history[:10], 1):
        print(f"{i}. {t.strip().splitlines()[0][:90] if t.strip() else '(espaços)'}")
    return True


def clipboard_paste(index=2):
    """ "cola o que eu copiei antes" = o 2º da lista; "cola o 3" = o 3º."""
    index = int(index or 2)
    if not 1 <= index <= len(clip_history):
        _say("Não tenho isso no histórico da área de transferência.")
        return False
    import ferramentas as F
    return F.type_text(clip_history[index - 1])


# ========================= ORGANIZAR, RENOMEAR, COMPACTAR (50) =========================

KINDS = {
    "Imagens": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".svg", ".tif", ".tiff"},
    "Documentos": {".pdf", ".doc", ".docx", ".txt", ".odt", ".rtf", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".md"},
    "Vídeos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"},
    "Músicas": {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".opus"},
    "Compactados": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Instaladores": {".exe", ".msi", ".msix", ".appx"},
}


def kind_of(path):
    ext = Path(path).suffix.lower()
    return next((k for k, exts in KINDS.items() if ext in exts), "Outros")


def plan_organize(folder, by="tipo"):
    """[(origem, destino)] para organizar a pasta por tipo ou por data (AAAA-MM). Não mexe em nada."""
    folder = Path(folder)
    moves = []
    for p in sorted(folder.iterdir()):
        if not p.is_file() or p.name.startswith(".") or p.suffix.lower() in (".tmp", ".crdownload", ".part"):
            continue
        if by == "data":
            sub = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m")
        else:
            sub = kind_of(p)
        target = folder / sub / p.name
        n = 1
        while target.exists():
            target = folder / sub / f"{p.stem} ({n}){p.suffix}"
            n += 1
        moves.append((p, target))
    return moves


def _record_undo(kind, moves):
    data = _load_json(UNDO, [])
    data.append({"quando": datetime.now().isoformat(timespec="seconds"), "tipo": kind,
                 "itens": [[str(a), str(b)] for a, b in moves]})
    _save_json(UNDO, data[-30:])


def record_move(src, dest, kind="mover"):
    """O Jarvis moveu/renomeou um arquivo: guarda para o "desfaz" (97)."""
    try:
        _record_undo(kind, [(src, dest)])
    except OSError:
        pass


def organize_folder(folder, confirm, by="tipo"):
    folder = Path(os.path.expandvars(str(folder))).expanduser()
    if not folder.is_dir():
        _say(f"Pasta não encontrada: {folder}")
        return False
    by = "data" if norm(by) in ("data", "mes", "por data", "datas") else "tipo"
    moves = plan_organize(folder, by)
    if not moves:
        _say("Não tem arquivo solto para organizar.")
        return True
    groups = {}
    for _, b in moves:
        groups[b.parent.name] = groups.get(b.parent.name, 0) + 1
    print("  " + ", ".join(f"{k}: {v}" for k, v in sorted(groups.items())))
    if not confirm(f"Organizo {len(moves)} arquivos de {folder.name} por {by} em subpastas?"):
        _say("Ok, deixei como está.")
        return False
    done = []
    for a, b in moves:
        try:
            b.parent.mkdir(exist_ok=True)
            shutil.move(str(a), str(b))
            done.append((a, b))
        except OSError:
            continue
    _record_undo("organizar", done)
    _say(f"Organizei {len(done)} arquivos em {len(groups)} pastas. Diga \"desfaz\" se não gostar.")
    return True


def plan_rename(folder, pattern, kind=""):
    """[(origem, destino)]: "foto" -> foto 001.jpg, foto 002.jpg... (na ordem da data). kind filtra (imagens...)."""
    folder = Path(folder)
    files = [p for p in folder.iterdir() if p.is_file()]
    if kind:
        files = [p for p in files if kind_of(p) == kind or p.suffix.lower().lstrip(".") == norm(kind)]
    files.sort(key=lambda p: p.stat().st_mtime)
    width = max(2, len(str(len(files))))
    moves = []
    for i, p in enumerate(files, 1):
        if norm(pattern) in ("data", "por data"):
            stem = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H-%M-%S")
        else:
            stem = f"{pattern.strip()} {i:0{width}d}"
        target = p.with_name(stem + p.suffix.lower())
        n = 1
        while target.exists() and target != p:
            target = p.with_name(f"{stem} ({n}){p.suffix.lower()}")
            n += 1
        if target != p:
            moves.append((p, target))
    return moves


def batch_rename(folder, pattern, confirm, kind=""):
    folder = Path(os.path.expandvars(str(folder))).expanduser()
    if not folder.is_dir():
        _say(f"Pasta não encontrada: {folder}")
        return False
    moves = plan_rename(folder, pattern or "arquivo", kind)
    if not moves:
        _say("Nada para renomear.")
        return True
    print(f"  ex.: {moves[0][0].name} -> {moves[0][1].name}")
    if not confirm(f"Renomeio {len(moves)} arquivos em {folder.name}?"):
        _say("Ok, não renomeei.")
        return False
    done = []
    for a, b in moves:
        try:
            a.rename(b)
            done.append((a, b))
        except OSError:
            continue
    _record_undo("renomear", done)
    _say(f"Renomeei {len(done)} arquivos. Diga \"desfaz\" se não gostar.")
    return True


def compress(path, dest=""):
    path = Path(os.path.expandvars(str(path))).expanduser()
    if not path.exists():
        _say(f"Não achei {path}.")
        return False
    target = Path(dest) if dest else path.with_suffix(".zip") if path.is_file() else path.parent / (path.name + ".zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        if path.is_file():
            z.write(path, path.name)
        else:
            for f in path.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(path.parent))
    _say(f"Compactei em {target.name} ({_size(target.stat().st_size)}).")
    return str(target)


def extract(path, dest=""):
    path = Path(os.path.expandvars(str(path))).expanduser()
    if not path.is_file() or path.suffix.lower() != ".zip":
        _say("Só descompacto arquivos .zip por enquanto.")
        return False
    target = Path(dest) if dest else path.with_suffix("")
    with zipfile.ZipFile(path) as z:
        for member in z.namelist():  # nada de "..\\" saindo da pasta
            if Path(member).is_absolute() or ".." in Path(member).parts:
                _say("Esse .zip tem caminhos estranhos; não descompactei por segurança.")
                return False
        z.extractall(target)
    _say(f"Descompactei em {target}.")
    return str(target)


# ========================= DESFAZER (97) =========================

def undo_last():
    """Desfaz a última ação de arquivo do Bolha (mover, renomear, organizar)."""
    data = _load_json(UNDO, [])
    if not data:
        _say("Não tenho nada de arquivo para desfazer.")
        return False
    last = data.pop()
    back = 0
    for src, dest in reversed(last["itens"]):
        try:
            if Path(dest).exists() and not Path(src).exists():
                Path(src).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(dest, src)
                back += 1
        except OSError:
            continue
    for _, dest in last["itens"]:  # tira as pastas que ficaram vazias
        try:
            Path(dest).parent.rmdir()
        except OSError:
            pass
    _save_json(UNDO, data)
    _say(f"Desfiz: {last['tipo']} ({back} arquivo{'s' if back != 1 else ''} de volta).")
    return back > 0


# ========================= CONVERTER (51) =========================

def find_ffmpeg():
    for p in (TOOLS_DIR / "ffmpeg.exe", TOOLS_DIR / "ffmpeg" / "bin" / "ffmpeg.exe"):
        if p.is_file():
            return str(p)
    return shutil.which("ffmpeg") or ""


def images_to_pdf(paths, dest):
    """Junta imagens num PDF (35, 51). Precisa do Pillow."""
    try:
        from PIL import Image
    except ImportError:
        _say("Para fazer PDF de imagens instale o Pillow: python -m pip install Pillow")
        return False
    paths = [Path(p) for p in paths if Path(p).is_file()]
    if not paths:
        _say("Não achei as imagens.")
        return False
    pages = [Image.open(p).convert("RGB") for p in paths]
    dest = Path(dest)
    pages[0].save(dest, save_all=True, append_images=pages[1:])
    _say(f"PDF com {len(pages)} página{'s' if len(pages) > 1 else ''} salvo em {dest}.")
    return str(dest)


def convert(path, to):
    """Converte um arquivo: imagem(ns) -> pdf, vídeo/áudio -> mp3, imagem -> jpg/png."""
    path = Path(os.path.expandvars(str(path))).expanduser()
    to = norm(to).lstrip(".")
    if path.is_dir() and to == "pdf":
        imgs = sorted((p for p in path.iterdir() if kind_of(p) == "Imagens"), key=lambda p: p.stat().st_mtime)
        return images_to_pdf(imgs, path / f"{path.name}.pdf")
    if not path.is_file():
        _say(f"Não achei {path}.")
        return False
    if to == "pdf" and kind_of(path) == "Imagens":
        return images_to_pdf([path], path.with_suffix(".pdf"))
    if to in ("jpg", "jpeg", "png", "webp") and kind_of(path) == "Imagens":
        try:
            from PIL import Image
        except ImportError:
            _say("Instale o Pillow: python -m pip install Pillow")
            return False
        out = path.with_suffix("." + to)
        Image.open(path).convert("RGB").save(out)
        _say(f"Convertido para {out.name}.")
        return str(out)
    if to in ("mp3", "wav", "m4a", "mp4", "gif"):
        ff = find_ffmpeg()
        if not ff:
            _say("Para converter vídeo e áudio preciso do ffmpeg. Diga \"instala o ffmpeg\".")
            return False
        out = path.with_suffix("." + to)
        if out == path:
            _say("O arquivo já está nesse formato.")
            return False
        args = [ff, "-y", "-i", str(path)] + (["-vn", "-q:a", "2"] if to == "mp3" else []) + [str(out)]
        r = _run(args, timeout=3600)
        if r.returncode != 0:
            _say("O ffmpeg não conseguiu converter.")
            return False
        _say(f"Convertido para {out.name} ({_size(out.stat().st_size)}).")
        return str(out)
    _say(f"Não sei converter {path.suffix} para {to}.")
    return False


def shrink_for_sending(path, max_mb=16):
    """Diminui um arquivo grande para mandar no zap: imagem fica menor, vídeo recomprime, o resto vira .zip."""
    path = Path(os.path.expandvars(str(path))).expanduser()
    if not path.exists():
        _say(f"Não achei {path}.")
        return False
    size = path.stat().st_size if path.is_file() else _folder_size(path)[0]
    if path.is_file() and size <= max_mb * 1024 * 1024 and kind_of(path) != "Imagens":
        _say(f"{path.name} já tem {_size(size)}: dá para mandar como está.")
        return str(path)
    if path.is_file() and kind_of(path) == "Imagens":
        try:
            from PIL import Image
            img = Image.open(path).convert("RGB")
            img.thumbnail((1920, 1920))
            out = path.with_name(path.stem + " (menor).jpg")
            img.save(out, quality=82)
            _say(f"Imagem diminuída: {_size(size)} -> {_size(out.stat().st_size)}.")
            return str(out)
        except ImportError:
            pass
    if path.is_file() and kind_of(path) == "Vídeos" and find_ffmpeg():
        out = path.with_name(path.stem + " (menor).mp4")
        r = _run([find_ffmpeg(), "-y", "-i", str(path), "-vf", "scale=-2:720", "-c:v", "libx264", "-crf", "28",
                  "-preset", "veryfast", "-c:a", "aac", "-b:a", "96k", str(out)], timeout=3600)
        if r.returncode == 0:
            _say(f"Vídeo diminuído: {_size(size)} -> {_size(out.stat().st_size)}.")
            return str(out)
    return compress(path)


# ========================= MACROS (29) =========================

recording = threading.Event()
VK_NAMES = {0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x1B: "esc", 0x20: "space", 0x21: "pageup",
            0x22: "pagedown", 0x23: "end", 0x24: "home", 0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
            0x2E: "delete", 0x10: "shift", 0x11: "ctrl", 0x12: "alt", 0x5B: "win", **{0x70 + i: f"f{i + 1}" for i in range(12)},
            **{c: chr(c).lower() for c in range(0x30, 0x3A)}, **{c: chr(c).lower() for c in range(0x41, 0x5B)}}
MOUSE = {0x01: "left", 0x02: "right", 0x04: "middle"}


def record_macro(name, seconds=300, every=0.03):
    """ "observa o que eu faço": grava cliques e teclas até o PARAR (ou "Bolha, para de gravar")."""
    name = norm(name).replace(" ", "-") or datetime.now().strftime("macro-%H%M")
    get_key, u32 = _user32().GetAsyncKeyState, _user32()
    from ctypes import wintypes
    pos = wintypes.POINT()
    events, down, t0 = [], set(), time.time()
    recording.set()
    _say(f"Gravando a macro {name}. Faça o que quer que eu aprenda e aperte PARAR (ou diga \"Bolha, para de gravar\").")

    def loop():
        while recording.is_set() and time.time() - t0 < seconds:
            now = time.time() - t0
            for vk in list(MOUSE) + list(VK_NAMES):
                pressed = bool(get_key(vk) & 0x8000)
                if pressed and vk not in down:
                    down.add(vk)
                    u32.GetCursorPos(ctypes.byref(pos))
                    events.append({"t": round(now, 3), "tipo": "clique" if vk in MOUSE else "tecla",
                                   "k": MOUSE.get(vk) or VK_NAMES[vk], "x": pos.x, "y": pos.y, "d": True})
                elif not pressed and vk in down:
                    down.discard(vk)
                    events.append({"t": round(now, 3), "tipo": "clique" if vk in MOUSE else "tecla",
                                   "k": MOUSE.get(vk) or VK_NAMES[vk], "d": False})
            time.sleep(every)
        recording.clear()
        _save_json(MACROS / f"{name}.json", {"nome": name, "eventos": events,
                                             "gravada": datetime.now().isoformat(timespec="minutes")})
        print(f"Jarvis > Macro {name} gravada ({len([e for e in events if e['d']])} ações). "
              f"Diga \"repete a macro {name}\".")

    threading.Thread(target=loop, daemon=True).start()
    return name


def stop_recording():
    if not recording.is_set():
        return False
    recording.clear()
    return True


def play_macro(name, speed=1.0, stop=None):
    """Repete a macro gravada (o PARAR também interrompe)."""
    data = _load_json(MACROS / f"{norm(name).replace(' ', '-')}.json", None)
    if not data:
        names = sorted(p.stem for p in MACROS.glob("*.json")) if MACROS.is_dir() else []
        _say(f"Não tenho a macro {name}." + (f" Tenho: {', '.join(names)}." if names else ""))
        return False
    import pyautogui
    last = 0.0
    for e in data["eventos"]:
        if stop is not None and stop.is_set():
            _say("Parei a macro.")
            return False
        time.sleep(max(0.0, (e["t"] - last) / max(0.1, speed)))
        last = e["t"]
        if e["tipo"] == "clique":
            if e["d"]:
                pyautogui.mouseDown(e["x"], e["y"], button=e["k"])
            else:
                pyautogui.mouseUp(button=e["k"])
        else:
            (pyautogui.keyDown if e["d"] else pyautogui.keyUp)(e["k"])
    _say(f"Macro {data['nome']} repetida.")
    return True


def list_macros():
    names = sorted(p.stem for p in MACROS.glob("*.json")) if MACROS.is_dir() else []
    _say("Macros: " + (", ".join(names) if names else "nenhuma ainda. Diga \"observa o que eu faço\"."))
    return names


# ========================= JOGOS (87, 88, 90) =========================

def _steam_roots():
    roots = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            roots.append(Path(winreg.QueryValueEx(k, "SteamPath")[0]))
    except Exception:
        pass
    return roots + [Path(r"C:\Program Files (x86)\Steam"), Path(r"G:\Steam"), Path(r"G:\SteamLibrary")]


def steam_games(roots=None):
    """{nome normalizado: (nome, appid)} dos jogos instalados na Steam."""
    roots = [Path(r) for r in roots] if roots is not None else _steam_roots()
    games, libraries = {}, set()
    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            libraries.add(root / "steamapps")
            for path in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
                libraries.add(Path(path.replace("\\\\", "\\")) / "steamapps")
        elif (root / "steamapps").is_dir():
            libraries.add(root / "steamapps")
    for lib in libraries:
        for acf in lib.glob("appmanifest_*.acf"):
            text = acf.read_text(encoding="utf-8", errors="ignore")
            name = re.search(r'"name"\s+"([^"]+)"', text)
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            if name and appid:
                games[norm(name.group(1))] = (name.group(1), appid.group(1))
    return games


def epic_games():
    file = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Epic" / "UnrealEngineLauncher" / "LauncherInstalled.dat"
    games = {}
    data = _load_json(file, {})
    for item in data.get("InstallationList", []) if isinstance(data, dict) else []:
        app = item.get("AppName")
        if app:
            label = Path(item.get("InstallLocation", app)).name or app
            games[norm(label)] = (label, app)
    return games


def find_game(name):
    """(nome, link para abrir, loja) do jogo instalado na Steam ou na Epic, ou None."""
    want = norm(name)
    for store, games, url in (("Steam", steam_games(), "steam://rungameid/{}"),
                              ("Epic", epic_games(), "com.epicgames.launcher://apps/{}?action=launch&silent=true")):
        if not games:
            continue
        keys = list(games)
        i = best_match(want, keys, cutoff=0.75)
        if i is None:
            i = next((j for j, k in enumerate(keys) if len(want) >= 4 and want in k), None)
        if i is not None:
            label, gid = games[keys[i]]
            return label, url.format(gid), store
    return None


def open_game(name, quiet=False):
    """Abre jogo da Steam ou da Epic pelo nome."""
    found = find_game(name)
    if not found:
        if not quiet:
            _say(f"Não achei {name} na Steam nem na Epic.")
        return False
    label, url, store = found
    try:
        os.startfile(url)
    except OSError as e:
        _say(f"Não consegui abrir {label}: {e}.")
        return False
    _say(f"Abrindo {label} pela {store}.")
    return True


def game_clip():
    """Grava os últimos 30 segundos (Xbox Game Bar: Win+Alt+G)."""
    import pyautogui
    pyautogui.hotkey("win", "alt", "g")
    _say("Pedi para o Xbox Game Bar salvar os últimos segundos (precisa da gravação em segundo plano ligada).")
    return True


def game_bar():
    import pyautogui
    pyautogui.hotkey("win", "g")
    _say("Abri o Xbox Game Bar (o painel Desempenho mostra o FPS).")
    return True


def game_priority(name=""):
    """Prioridade alta para o jogo (o processo da janela da frente ou pelo nome)."""
    import psutil
    target = None
    if name:
        want = norm(name).replace(" ", "")
        target = next((p for p in psutil.process_iter(["name"]) if want in (p.info["name"] or "").lower()), None)
    else:
        hwnd = _target_window()
        if hwnd:
            pid = ctypes.c_ulong()
            _user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            target = psutil.Process(pid.value)
    if target is None:
        _say("Não achei o jogo para dar prioridade.")
        return False
    try:
        target.nice(getattr(psutil, "HIGH_PRIORITY_CLASS", 128))
    except Exception as e:
        _say(f"Não consegui dar prioridade: {e}.")
        return False
    _say(f"Prioridade alta para {target.name()}.")
    return True


def temperature():
    """Temperatura do processador, se o Windows informar (muitos notebooks só informam como administrador)."""
    code, out = _ps("Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
                    "| Select-Object -ExpandProperty CurrentTemperature", timeout=20)
    temps = [int(x) / 10 - 273.15 for x in re.findall(r"\d{4}", out)]
    return round(max(temps)) if code == 0 and temps else None


# ========================= SAÚDE DO PC (93, 60) =========================

def disks():
    """[(disco, livre, total)] dos discos fixos."""
    import psutil
    out = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            u = shutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        out.append((part.mountpoint, u.free, u.total))
    return out


def low_disks(limit_pct=10, limit_gb=5):
    return [(d, f, t) for d, f, t in disks() if f < t * limit_pct / 100 or f < limit_gb * 1024 ** 3]


def health_report(windows_updates=True):
    """Relatório de saúde: discos, memória, temperatura, atualizações pendentes, o que abre com o Windows."""
    import psutil
    mem = psutil.virtual_memory()
    lines = []
    for d, f, t in disks():
        lines.append(f"Disco {d[:2]}: {_size(f)} livres de {_size(t)}" + (" (QUASE CHEIO)" if f < t * 0.1 else ""))
    lines.append(f"Memória: {mem.percent:.0f}% em uso ({_size(mem.available)} livres)")
    temp = temperature()
    if temp:
        lines.append(f"Temperatura: {temp} °C" + (" (QUENTE)" if temp >= 85 else ""))
    try:
        boot = datetime.fromtimestamp(psutil.boot_time())
        lines.append(f"Ligado há {(datetime.now() - boot).days} dia(s)")
    except Exception:
        pass
    if winget_path():
        try:
            n = len(upgradable())
            lines.append(f"Programas com atualização: {n}" + (" (diga \"atualiza tudo\")" if n else ""))
        except Exception:
            pass
    if windows_updates:
        code, out = _ps("(New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher()"
                        ".Search('IsInstalled=0 and IsHidden=0').Updates.Count", timeout=90)
        m = re.search(r"^\s*(\d+)\s*$", out, re.M)
        if code == 0 and m:
            lines.append(f"Atualizações do Windows pendentes: {m.group(1)}")
    lines.append(f"Programas que abrem com o Windows: {len(startup_programs())}")
    _say("Saúde do PC:")
    for line in lines:
        print(f"  - {line}")
    return "\n".join(lines)


# ========================= O QUE ABRE COM O WINDOWS (94) =========================

RUN_KEYS = [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
            ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run"),
            ("HKLM", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run")]


def startup_programs():
    """{nome: comando} do que abre com o Windows (registro e pasta Inicializar)."""
    out = {}
    try:
        import winreg
        for hive, path in RUN_KEYS:
            root = winreg.HKEY_CURRENT_USER if hive == "HKCU" else winreg.HKEY_LOCAL_MACHINE
            try:
                with winreg.OpenKey(root, path) as k:
                    i = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(k, i)
                        except OSError:
                            break
                        out[name] = str(value)
                        i += 1
            except OSError:
                continue
    except ImportError:
        pass
    for folder in (Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup",
                   Path(os.environ.get("PROGRAMDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\StartUp"):
        if str(folder) and folder.is_dir():
            for p in folder.iterdir():
                if p.suffix.lower() in (".lnk", ".exe", ".bat", ".url"):
                    out[p.stem] = str(p)
    return out


def new_startup_programs(current=None):
    """Programas que passaram a abrir com o Windows desde a última olhada (a primeira vez só guarda)."""
    current = startup_programs() if current is None else current
    seen = _load_json(STARTUP_SNAPSHOT, None)
    _save_json(STARTUP_SNAPSHOT, current)
    if seen is None:
        return []
    return [n for n in current if n not in seen]


def list_startup():
    items = startup_programs()
    _say(f"{len(items)} programas abrem com o Windows:")
    for n in sorted(items):
        print(f"  - {n}")
    return True


# ========================= NOTIFICAÇÕES DO WINDOWS VIRAM CARD (100) =========================

def watch_notifications(put, every=4.0):
    """Lê as notificações do Windows e manda cada nova como aviso do Bolha. Precisa dos pacotes winrt
    (veja NOTIFICAÇÕES no LEIA-ME) e da permissão "acesso às notificações" que o Windows pergunta uma vez."""
    try:
        import asyncio
        from winrt.windows.ui.notifications import KnownNotificationBindings, NotificationKinds
        from winrt.windows.ui.notifications.management import UserNotificationListener
    except Exception:
        return False

    def run():
        listener = UserNotificationListener.current
        try:
            status = asyncio.run(_await(listener.request_access_async()))
            if int(status) != 1:  # 1 = Allowed
                return
        except Exception:
            return
        seen = set()
        first = True
        while True:
            try:
                items = asyncio.run(_await(listener.get_notifications_async(NotificationKinds.TOAST)))
                for n in items:
                    if n.id in seen:
                        continue
                    seen.add(n.id)
                    if first:
                        continue  # as que já estavam lá quando ele abriu não são novas
                    try:
                        app = n.app_info.display_info.display_name
                    except Exception:
                        app = "um programa"
                    texts = []
                    try:
                        binding = n.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
                        texts = [t.text for t in binding.get_text_elements()]
                    except Exception:
                        pass
                    if app.lower() not in ("bolha", "python", "jarvis"):
                        put(("aviso", f"Notificação do {app}: " + " — ".join(t for t in texts if t)[:160]))
                first = False
            except Exception:
                pass
            time.sleep(every)

    threading.Thread(target=run, daemon=True).start()
    return True


async def _await(op):
    return await op


# ========================= DOWNLOAD TERMINOU (103) =========================

PARTIAL = (".crdownload", ".part", ".tmp", ".download", ".opdownload")


def watch_downloads(folder, put, every=5.0):
    """Avisa quando um download termina (o arquivo novo aparece sem o .crdownload)."""
    folder = Path(folder)

    def snapshot():
        try:
            return {p.name for p in folder.iterdir() if p.is_file() and not p.name.lower().endswith(PARTIAL)}
        except OSError:
            return set()

    def run():
        known = snapshot()
        while True:
            time.sleep(every)
            now = snapshot()
            for name in sorted(now - known):
                try:
                    size = (folder / name).stat().st_size
                except OSError:
                    continue
                if size > 0 and not name.startswith("~"):
                    put(("aviso", f"Download concluído, senhor: {name} ({_size(size)})."))
            known = now

    threading.Thread(target=run, daemon=True).start()
    return True
