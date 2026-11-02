"""Visão do PC: o que tem na área de trabalho, nos discos e o que pode ou não ser apagado.

A IA recebe isto como texto e tira as próprias conclusões ("o C está quase cheio, o que mais pesa são os
instaladores velhos"). Aqui nada é apagado: apagar continua com delete_item / delete_paths, que perguntam antes.
"""
import os
import string
import time
from pathlib import Path, PureWindowsPath

CACHE_SECONDS = 60  # o resumo curto que vai em todo pedido é refeito no máximo uma vez por minuto
SCAN_SECONDS = 25  # teto para medir pastas (o i3 com HD não pode travar a Bolha)
INSTALLER_EXTS = {".exe", ".msi", ".zip", ".rar", ".7z", ".iso"}
OLD_DAYS = 30

# nunca apagar: o Windows quebra ou programas param de abrir
NEVER = ["windows", "program files", "program files (x86)", "programdata", "$recycle.bin", "system volume information",
         "recovery", "boot", "pagefile.sys", "hiberfil.sys", "swapfile.sys"]
# nunca sugerir: são do senhor (fotos, documentos, projetos) mesmo quando pesam
PERSONAL = ["documents", "documentos", "pictures", "imagens", "desktop", "área de trabalho", "videos", "vídeos",
            "music", "músicas", "jarvis-king", "config", ".git", "saved games"]

_short = {"t": 0.0, "text": ""}


def _size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return str(n)


def _shell_folder(name, fallback):
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        value, _ = winreg.QueryValueEx(key, name)
        return Path(os.path.expandvars(value))
    except Exception:
        return Path.home() / fallback


def desktops():
    """A área de trabalho do senhor e a pública (atalhos que aparecem para todos)."""
    found = [_shell_folder("Desktop", "Desktop"), Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"]
    return [d for d in dict.fromkeys(found) if d.is_dir()]


def _shortcut_target(path):
    """Para onde um .lnk aponta ("" se não deu para ler)."""
    try:
        from win32com.client import Dispatch
        return Dispatch("WScript.Shell").CreateShortCut(str(path)).Targetpath or ""
    except Exception:
        return ""


def desktop_items():
    """[(nome, tipo, tamanho, observação)] do que está na área de trabalho."""
    items = []
    for folder in desktops():
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for e in entries:
            if e.name.lower() == "desktop.ini":
                continue
            path = Path(e.path)
            ext = path.suffix.lower()
            note = ""
            if e.is_dir():
                kind = "pasta"
                size = 0
            elif ext == ".lnk":
                kind = "atalho"
                size = 0
                target = _shortcut_target(path)
                if target and not Path(target).exists():
                    note = "QUEBRADO (o programa não existe mais)"
            elif ext == ".url":
                kind, size = "link", 0
            else:
                kind = "arquivo"
                try:
                    size = e.stat().st_size
                except OSError:
                    size = 0
                if ext in INSTALLER_EXTS:
                    note = "instalador solto"
            items.append((path.stem if kind in ("atalho", "link") else e.name, kind, size, note))
    return sorted(items, key=lambda i: (i[1] != "pasta", i[0].lower()))


def drives():
    """[(letra, total, usado, livre)] dos discos que existem."""
    out = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if not os.path.exists(root):
            continue
        try:
            import shutil
            total, used, free = shutil.disk_usage(root)
        except OSError:
            continue
        if total:
            out.append((letter, total, used, free))
    return out


def folder_size(path, deadline, older_than_days=0):
    """Tamanho de uma pasta (e quantos arquivos), parando no prazo. Volta (bytes, arquivos, completo?)."""
    total, count = 0, 0
    limit = time.time() - older_than_days * 86400 if older_than_days else None
    stack = [str(path)]
    while stack:
        if time.monotonic() > deadline:
            return total, count, False
        try:
            entries = os.scandir(stack.pop())
        except OSError:
            continue
        with entries:
            for e in entries:
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if limit and st.st_mtime > limit:
                    continue
                total += st.st_size
                count += 1
    return total, count, True


def biggest_folders(root, deadline, n=8):
    """As pastas mais pesadas logo abaixo de root: [(caminho, bytes, completo?)]."""
    try:
        subs = [Path(e.path) for e in os.scandir(root) if e.is_dir(follow_symlinks=False)]
    except OSError:
        return []
    out = []
    for sub in subs:
        if sub.name.lower() in ("$recycle.bin", "system volume information"):
            continue
        size, _, done = folder_size(sub, deadline)
        out.append((sub, size, done))
        if time.monotonic() > deadline:
            break
    return sorted(out, key=lambda x: -x[1])[:n]


def verdict(path):
    """'nunca' (sistema), 'pessoal' (do senhor: só ele decide) ou '' (pode avaliar)."""
    parts = [p.lower() for p in PureWindowsPath(str(path)).parts[1:]]
    if parts and parts[0] in NEVER:
        return "nunca"
    if any(p in PERSONAL for p in parts):
        return "pessoal"
    return ""


def cleanable(deadline, extra_roots=()):
    """O que dá para apagar sem perder nada do senhor: [(o que é, caminho ou "", bytes, nível)].
    nível: 'seguro' (temporário/cache, o Windows recria) ou 'voce decide' (instalador velho, download antigo)."""
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    out = []
    safe = [
        ("Temporários do Windows (seus)", Path(os.environ.get("TEMP", local / "Temp"))),
        ("Temporários do Windows (sistema)", Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Temp"),
        ("Cache do Edge", local / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache"),
        ("Cache do Chrome", local / "Google" / "Chrome" / "User Data" / "Default" / "Cache"),
        ("Relatórios de erro do Windows", local / "CrashDumps"),
        ("Cache do pip", local / "pip" / "Cache"),
        ("Temporários da Bolha", Path(r"G:\Jarvis\tmp")),
    ]
    for label, path in safe:
        if path.is_dir():
            size, _, _ = folder_size(path, deadline)
            if size > 5 * 1024 * 1024:
                out.append((label, str(path), size, "seguro"))
    try:
        import maos
        bin_size, bin_items = maos._recycle_size()
        if bin_size:
            out.append((f"Lixeira ({bin_items} itens)", "", bin_size, "seguro"))
    except Exception:
        pass
    old = time.time() - OLD_DAYS * 86400
    roots = [_shell_folder("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads"), Path(r"G:\Jarvis"), *extra_roots]
    for root in dict.fromkeys(roots):
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        for e in entries:
            try:
                if not e.is_file() or Path(e.name).suffix.lower() not in INSTALLER_EXTS:
                    continue
                st = e.stat()
            except OSError:
                continue
            if st.st_size > 50 * 1024 * 1024 and (st.st_mtime < old or str(root).lower().startswith("g:\\jarvis")):
                out.append((f"Instalador/compactado já usado: {e.name}", e.path, st.st_size, "voce decide"))
    return sorted(out, key=lambda x: -x[2])


def overview(deep=True, seconds=SCAN_SECONDS):
    """O texto completo para a IA: área de trabalho, discos, o que pesa e o que pode ou não ser apagado."""
    deadline = time.monotonic() + seconds
    lines = ["ÁREA DE TRABALHO:"]
    items = desktop_items()
    if not items:
        lines.append("  (vazia)")
    for name, kind, size, note in items[:60]:
        extra = f", {_size(size)}" if size > 1024 * 1024 else ""
        lines.append(f"  - {name} ({kind}{extra}){' - ' + note if note else ''}")
    if len(items) > 60:
        lines.append(f"  ... e mais {len(items) - 60}")
    lines.append("\nDISCOS:")
    disks = drives()
    for letter, total, used, free in disks:
        pct = used * 100 / total
        warn = " - QUASE CHEIO" if pct >= 90 else ""
        lines.append(f"  - {letter}: {_size(free)} livres de {_size(total)} ({pct:.0f}% usado){warn}")
    if deep:
        lines.append("\nO QUE MAIS PESA (pastas):")
        home = Path.home()
        for root in [home, *[Path(f"{d[0]}:\\") for d in disks]]:
            if time.monotonic() > deadline:
                lines.append("  (parei de medir para não travar; peça de novo para continuar)")
                break
            big = biggest_folders(root, deadline, n=6)
            if not big:
                continue
            lines.append(f"  {root}")
            for path, size, done in big:
                tag = verdict(path)
                tag = {"nunca": " [SISTEMA: não apagar]", "pessoal": " [SEU: só o senhor decide]"}.get(tag, "")
                lines.append(f"    - {path.name}: {'mais de ' if not done else ''}{_size(size)}{tag}")
        lines.append("\nPODE APAGAR:")
        clean = cleanable(deadline)
        if not clean:
            lines.append("  (nada que valha a pena)")
        for label, path, size, level in clean[:20]:
            lines.append(f"  - [{level.upper()}] {label}: {_size(size)}{' em ' + path if path and path not in label else ''}")
    lines.append("\nNUNCA APAGAR: Windows, Arquivos de Programas, ProgramData, AppData\\Roaming (configurações), "
                 "e os documentos, fotos e projetos do senhor sem ele ver.")
    return "\n".join(lines)


def short_context():
    """Uma linha para todo pedido: os discos e o que está na área de trabalho (rápido, com cache de 1 min)."""
    if time.time() - _short["t"] < CACHE_SECONDS and _short["text"]:
        return _short["text"]
    try:
        disks = ", ".join(f"{l}: {_size(f)} livres ({u * 100 / t:.0f}% usado)" for l, t, u, f in drives())
        names = [f"{n}{' (quebrado)' if 'QUEBRADO' in note else ''}" for n, _, _, note in desktop_items()]
        desk = ", ".join(names[:40]) + (f" e mais {len(names) - 40}" if len(names) > 40 else "")
        text = f"PC: discos {disks or '?'}. Área de trabalho: {desk or 'vazia'}."
    except Exception:
        text = ""
    _short.update(t=time.time(), text=text)
    return text
