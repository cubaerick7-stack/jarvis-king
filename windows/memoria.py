# -*- coding: utf-8 -*-
"""Memória do Jarvis: perfil, coisas que você mandou guardar, lembretes, conversa e hábitos.

Tudo fica em G:\\Jarvis\\config\\memoria.json, no seu PC. Pergunte "o que você sabe sobre mim"
para ver e "esquece ..." para apagar.
"""

import json
import re
import threading
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

FILE = Path(r"G:\Jarvis\config\memoria.json")
ACTION_LOG = Path(r"G:\Jarvis\logs\acoes.log")
MAX_TALK = 6  # últimas trocas que a IA lembra
HABIT_DAYS = 3  # em quantos dias diferentes algo precisa se repetir para virar hábito

_lock = threading.Lock()


def _empty():
    return {"perfil": {}, "fatos": [], "lembretes": [], "conversa": []}


def _norm(text):
    text = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


def load():
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
        return {**_empty(), **data}
    except Exception:
        return _empty()


def save(data):
    with _lock:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(FILE)


def _say(text):
    print(f"Jarvis > {text}")


# ------------------------- perfil e fatos -------------------------

def set_profile(key, value):
    key, value = _norm(key).replace(" ", "_"), str(value).strip()
    if not key or not value:
        return False
    data = load()
    data["perfil"][key] = value
    save(data)
    _say(f"Anotado, senhor: {key.replace('_', ' ')} = {value}.")
    return True


def remember(fact):
    fact = str(fact).strip()
    if not fact:
        return False
    data = load()
    if all(_norm(f["texto"]) != _norm(fact) for f in data["fatos"]):
        data["fatos"].append({"texto": fact, "quando": datetime.now().isoformat(timespec="minutes")})
        save(data)
    _say(f"Vou lembrar: {fact}.")
    return True


def forget(text):
    """Apaga fatos, lembretes e campos do perfil que contenham o texto."""
    q = _norm(text)
    if not q:
        return False
    data = load()
    before = len(data["fatos"]) + len(data["lembretes"]) + len(data["perfil"])
    data["fatos"] = [f for f in data["fatos"] if q not in _norm(f["texto"])]
    data["lembretes"] = [r for r in data["lembretes"] if q not in _norm(r["texto"])]
    data["perfil"] = {k: v for k, v in data["perfil"].items() if q not in _norm(k) and q not in _norm(v)}
    removed = before - (len(data["fatos"]) + len(data["lembretes"]) + len(data["perfil"]))
    save(data)
    _say(f"Esqueci {removed} coisa(s) sobre {text}." if removed else f"Não tinha nada guardado sobre {text}.")
    return removed > 0


def what_i_know():
    data = load()
    lines = [f"- {k.replace('_', ' ')}: {v}" for k, v in data["perfil"].items()]
    lines += [f"- {f['texto']}" for f in data["fatos"]]
    lines += [f"- lembrete {r['data']} {r.get('hora') or ''}: {r['texto']}".replace("  ", " ")
              for r in data["lembretes"] if not r.get("avisado")]
    if not lines:
        _say("Ainda não sei nada sobre o senhor. Diga, por exemplo, \"meu nome é João\".")
        return True
    print("Jarvis > O que eu sei sobre o senhor:")
    print("\n".join("  " + x for x in lines))
    return "\n".join(lines)


# ------------------------- lembretes -------------------------

def add_reminder(text, day, hour=""):
    """day = AAAA-MM-DD; hour = HH:MM (sem hora, avisa às 9h ou ao abrir o Jarvis)."""
    try:
        d = date.fromisoformat(str(day).strip())
    except ValueError:
        _say(f"Não entendi a data {day}.")
        return False
    hour = str(hour or "").strip()
    if hour and not re.fullmatch(r"\d{1,2}:\d{2}", hour):
        _say(f"Não entendi a hora {hour}.")
        return False
    data = load()
    data["lembretes"].append({"texto": str(text).strip(), "data": d.isoformat(), "hora": hour, "avisado": False})
    save(data)
    _say(f"Lembrete marcado para {d:%d/%m}{' às ' + hour if hour else ''}: {text}.")
    return True


def due_reminders(now=None):
    """Lembretes que já venceram e ainda não foram avisados (marca como avisados)."""
    now = now or datetime.now()
    data = load()
    due = []
    for r in data["lembretes"]:
        if r.get("avisado"):
            continue
        when = datetime.fromisoformat(r["data"] + "T" + (r.get("hora") or "09:00").zfill(5))
        if when <= now:
            r["avisado"] = True
            due.append(r["texto"])
    if due:
        save(data)
    return due


def reminder_watcher(put, every=30):
    """Thread que entrega os lembretes vencidos na fila de pedidos do Jarvis."""
    import time

    def loop():
        while True:
            try:
                for text in due_reminders():
                    put(("lembrete", text))
            except Exception:
                pass
            time.sleep(every)

    threading.Thread(target=loop, daemon=True).start()


# ------------------------- conversa -------------------------

def add_talk(user, reply):
    data = load()
    data["conversa"] = (data["conversa"] + [{"voce": str(user)[:300], "jarvis": str(reply)[:300]}])[-MAX_TALK:]
    save(data)


# ------------------------- histórico e hábitos -------------------------

def _log_entries():
    try:
        lines = ACTION_LOG.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out = []
    for line in lines:
        parts = line.split("\t")
        if len(parts) >= 2:
            try:
                out.append((datetime.fromisoformat(parts[0]), parts[1], parts[2] if len(parts) > 2 else ""))
            except ValueError:
                continue
    return out


def history(day="hoje"):
    d = _norm(day)
    target = date.today() - timedelta(days=1) if d == "ontem" else date.today()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        target = date.fromisoformat(d)
    items = [f"{t:%H:%M} {name.replace('ia:', '')} {detail}".strip()
             for t, name, detail in _log_entries() if t.date() == target]
    if not items:
        _say(f"Não tenho nada registrado em {target:%d/%m}.")
        return True
    print(f"Jarvis > O que o senhor pediu em {target:%d/%m}:")
    for line in items[-30:]:
        print("  " + line)
    return "\n".join(items[-30:])


def habits(now=None, days=30):
    """O que o senhor costuma pedir perto desta hora (repetido em vários dias)."""
    now = now or datetime.now()
    seen = defaultdict(set)
    for t, name, detail in _log_entries():
        if now - t > timedelta(days=days) or t.date() == now.date():
            continue
        if abs(t.hour - now.hour) <= 1 and name.replace("ia:", "") in {"play_youtube", "open_target", "run_routine", "open_url"}:
            seen[(name.replace("ia:", ""), detail)].add(t.date())
    return [k for k, ds in sorted(seen.items(), key=lambda kv: -len(kv[1])) if len(ds) >= HABIT_DAYS]


def habit_hint(now=None):
    found = habits(now)
    if not found:
        return ""
    name, detail = found[0]
    try:
        args = json.loads(detail)
        what = next(iter(args.values()))
    except Exception:
        what = detail
    verbs = {"play_youtube": "ouvir", "open_target": "abrir", "run_routine": "ativar o modo", "open_url": "abrir"}
    return f"Senhor, a essa hora o senhor costuma {verbs.get(name, 'usar')} {what}. Quer que eu faça?"


# ------------------------- para a IA -------------------------

def context():
    """Resumo da memória para ir junto de cada pedido."""
    data = load()
    parts = []
    if data["perfil"]:
        parts.append("Perfil do usuário: " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in data["perfil"].items()))
    if data["fatos"]:
        parts.append("Coisas que ele pediu para lembrar:\n" + "\n".join(f"- {f['texto']}" for f in data["fatos"][-20:]))
    pending = [r for r in data["lembretes"] if not r.get("avisado")]
    if pending:
        parts.append("Lembretes marcados:\n" + "\n".join(f"- {r['data']} {r.get('hora') or ''} {r['texto']}" for r in pending[:10]))
    if data["conversa"]:
        parts.append("Conversa recente:\n" + "\n".join(f"Usuário: {c['voce']}\nJarvis: {c['jarvis']}" for c in data["conversa"]))
    return "\n".join(parts)
