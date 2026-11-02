"""Editar fotos com o PhotoCraft (github.com/storytold/photocraft), sem abrir janela: photocraft-cli.

A IA escolhe os comandos (ids do registro do PhotoCraft) e esta parte só roda:
  photocraft-cli run <foto> --cmd <id> --params <json> ... --out <nova foto>
A foto original nunca é trocada: o resultado sai ao lado, com "-editada" no nome.
"""
import json
import os
import subprocess
from pathlib import Path

APPS = Path(os.environ.get("BOLHA_APPS", r"G:\Jarvis\apps"))
TIMEOUT = 180  # foto grande no i3: um filtro pesado pode levar um tempo

# os comandos mais usados, com os parâmetros certos (o resto a IA acha com photo_commands)
CHEAT_SHEET = (
    'image.imageSize {"width":px,"height":px} ou {"percent":50}; '
    'image.crop {"x":px,"y":px,"width":px,"height":px}; '
    'image.imageRotation.90cw {}; image.imageRotation.flipCanvasHorizontal {}; '
    'image.rotation.arbitrary {"angle":graus,"direction":"cw|ccw"}; '
    'image.autoTone {}; image.autoContrast {}; image.autoColor {}; image.mode.grayscale {}; '
    'image.adjustments.invert {}; '
    'image.adjustments.brightnessContrast {"brightness":-150..150,"contrast":-50..100}; '
    'image.adjustments.hueSaturation {"hue":-180..180,"saturation":-100..100,"lightness":-100..100}; '
    'image.adjustments.vibrance {"vibrance":-100..100,"saturation":-100..100}; '
    'image.adjustments.exposure {"exposure":-20..20}; '
    'filter.blur.gaussianBlur {"radius":0.1..1000}; filter.sharpen.smartSharpen {"amount":1..500}'
)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif", ".psd", ".pcraft", ".heic"}


def _say(text):
    print(f"Jarvis > {text}")


def find(name="photocraft-cli.exe"):
    """O programa do PhotoCraft: G:\\Jarvis\\apps\\photocraft (o senhor não usa o C) ou BOLHA_PHOTOCRAFT."""
    custom = os.environ.get("BOLHA_PHOTOCRAFT", "").strip()
    places = [Path(custom)] if custom else []
    places += [APPS / "photocraft", *sorted(APPS.glob("photocraft*"))]
    for place in places:
        exe = place / name if place.is_dir() else place.with_name(name)
        if exe.is_file():
            return exe
    return None


def _run(args, timeout=TIMEOUT):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _missing():
    _say("Não achei o PhotoCraft em G:\\Jarvis\\apps\\photocraft, senhor. Extraia o zip portátil lá.")
    return False


def commands(filter_text=""):
    """Os comandos que o PhotoCraft tem (com os parâmetros), para a IA escolher. Mostra no máximo 40."""
    cli = find()
    if cli is None:
        return _missing()
    args = [str(cli), "commands"]
    if filter_text:
        args += ["--filter", str(filter_text)]
    try:
        out = _run(args, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        _say(f"O PhotoCraft não respondeu: {e}")
        return False
    lines = [line for line in (out.stdout or "").splitlines() if line.strip()]
    if not lines:
        _say(f"Nenhum comando do PhotoCraft com \"{filter_text}\".")
        return False
    print("Jarvis > Comandos do PhotoCraft:")
    for line in lines[:40]:
        print(f"  {line[:300]}")
    if len(lines) > 40:
        print(f"  ... e mais {len(lines) - 40} (filtre melhor)")
    return True


def _steps(steps):
    """[["id", {params}], {"cmd": id, "params": {...}}, "id"] -> [(id, params)]."""
    out = []
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except ValueError:
            steps = [steps]
    for step in steps or []:
        if isinstance(step, str):
            out.append((step.strip(), {}))
        elif isinstance(step, (list, tuple)) and step:
            params = step[1] if len(step) > 1 and isinstance(step[1], dict) else {}
            out.append((str(step[0]).strip(), params))
        elif isinstance(step, dict):
            cmd = step.get("cmd") or step.get("id") or step.get("command") or step.get("name")
            if cmd:
                out.append((str(cmd).strip(), step.get("params") or step.get("args") or {}))
    return [(c, p) for c, p in out if c]


def output_for(photo, out=""):
    """Onde salvar: o que a IA pediu, ou ao lado da original com "-editada" (sem nunca apagar outra)."""
    photo = Path(photo)
    if out:
        target = Path(out)
        if not target.is_absolute():
            target = photo.with_name(target.name)
        if not target.suffix:
            target = target.with_suffix(photo.suffix if photo.suffix.lower() not in (".psd", ".pcraft") else ".png")
    else:
        ext = photo.suffix if photo.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff") else ".png"
        target = photo.with_name(f"{photo.stem}-editada{ext}")
    n = 2
    base = target
    while target.exists() or target.resolve() == photo.resolve():
        target = base.with_name(f"{base.stem}-{n}{base.suffix}")
        n += 1
    return target


def edit(photo, steps, out=""):
    """Roda os passos na foto e salva uma cópia editada. Volta o caminho do resultado (ou False)."""
    cli = find()
    if cli is None:
        return _missing()
    photo = Path(str(photo or "").strip('" '))
    if not photo.is_file():
        _say(f"Não achei a foto: {photo}")
        return False
    todo = _steps(steps)
    if not todo:
        _say("Não sei o que fazer na foto, senhor: faltaram os comandos.")
        return False
    target = output_for(photo, out)
    args = [str(cli), "run", str(photo)]
    for cmd, params in todo:
        args += ["--cmd", cmd, "--params", json.dumps(params, ensure_ascii=False)]
    args += ["--out", str(target)]
    try:
        result = _run(args)
    except subprocess.TimeoutExpired:
        _say("O PhotoCraft demorou demais e eu parei, senhor.")
        return False
    except OSError as e:
        _say(f"Não consegui rodar o PhotoCraft: {e}")
        return False
    if result.returncode != 0 or not target.exists():
        err = (result.stderr or result.stdout or "").strip().splitlines()
        _say(f"O PhotoCraft recusou: {err[-1][:240] if err else 'sem motivo'}")
        return False
    _say(f"Pronto: salvei {target.name} ao lado da original.")
    print(f"  {target}")
    return str(target)


def open_app(photo=""):
    """Abre o PhotoCraft (com a foto, se tiver)."""
    app = find("photocraft.exe")
    if app is None:
        return _missing()
    args = [str(app)]
    if photo and Path(photo).is_file():
        args.append(str(photo))
    try:
        subprocess.Popen(args, cwd=str(app.parent))
    except OSError as e:
        _say(f"Não consegui abrir o PhotoCraft: {e}")
        return False
    _say("Abrindo o PhotoCraft.")
    return True
