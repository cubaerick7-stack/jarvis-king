# -*- coding: utf-8 -*-
"""Memória do Jarvis: perfil, coisas que você mandou guardar, lembretes, conversa e hábitos.

Tudo fica em G:\\Jarvis\\config\\memoria.json, no seu PC. Pergunte "o que você sabe sobre mim"
para ver e "esquece ..." para apagar.
"""

import json
import os
import re
import threading
import time
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

FILE = Path(r"G:\Jarvis\config\memoria.json")
ACTION_LOG = Path(r"G:\Jarvis\logs\acoes.log")
MAX_TALK = 6  # últimas trocas que a IA lembra
HABIT_DAYS = 3  # em quantos dias diferentes algo precisa se repetir para virar hábito

_lock = threading.RLock()  # o lembrete (outra thread) e o pedido não podem salvar um por cima do outro


def _empty():
    return {"perfil": {}, "fatos": [], "lembretes": [], "conversa": []}


def _norm(text):
    text = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


def load():
    """A memória inteira. Se o arquivo não puder ser lido, LEVANTA (nunca devolve vazio no lugar dele,
    senão o próximo save apagaria tudo)."""
    with _lock:
        for attempt in range(3):
            try:
                raw = FILE.read_bytes()
                break
            except FileNotFoundError:
                return _empty()
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(0.1)  # arquivo preso por um instante (antivírus, backup): tenta de novo
        try:
            data = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("não é um objeto")
        except ValueError:  # inclui texto salvo como ANSI no Bloco de Notas
            # JSON estragado (editado à mão?): guarda uma cópia em vez de apagar tudo no próximo save
            backup = FILE.with_name(f"memoria.estragada-{datetime.now():%Y%m%d-%H%M%S}.json")
            FILE.replace(backup)  # se nem isso der, levanta: melhor não salvar do que perder
            _say(f"O memoria.json estava estragado; guardei em {backup.name} e comecei outro.")
            return _empty()
        data = {**_empty(), **data}
        for key, kind in (("perfil", dict), ("fatos", list), ("lembretes", list), ("conversa", list)):
            if not isinstance(data[key], kind):
                data[key] = kind()
        return data


def save(data):
    with _lock:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        for _ in range(20):  # no Windows o replace falha se outro programa estiver lendo naquela hora
            try:
                os.replace(tmp, FILE)
                return
            except PermissionError:
                time.sleep(0.05)
        os.replace(tmp, FILE)


def _say(text):
    print(f"Jarvis > {text}")


# ------------------------- perfil e fatos -------------------------

def set_profile(key, value):
    key, value = _norm(key).replace(" ", "_"), str(value).strip()
    if not key or not value:
        return False
    with _lock:
        data = load()
        data["perfil"][key] = value
        save(data)
    _say(f"Anotado, senhor: {key.replace('_', ' ')} = {value}.")
    return True


def remember(fact):
    fact = str(fact).strip()
    if not fact:
        return False
    with _lock:
        data = load()
        if all(_norm(f["texto"]) != _norm(fact) for f in data["fatos"]):
            data["fatos"].append({"texto": fact, "quando": datetime.now().isoformat(timespec="minutes")})
            save(data)
    _say(f"Vou lembrar: {fact}.")
    return True


def forget(text):
    """Apaga fatos, lembretes e campos do perfil sobre o assunto ("esquece meu nome" apaga o nome)."""
    q = _norm(text).strip(" .!?")
    while True:  # "que o meu nome" -> "nome"
        shorter = re.sub(r"^(?:meu|minha|meus|minhas|o|a|os|as|que eu|que|sobre|do|da|de)\s+", "", q)
        if shorter == q:
            break
        q = shorter
    if not q:
        return False

    def has(big, small):  # palavra inteira: "Rio" não some com "esquece a prova do rio grande"... só com "rio"
        return bool(small) and re.search(rf"(?<!\w){re.escape(small)}(?!\w)", big) is not None

    def about(s):
        s = _norm(s).replace("_", " ")
        return has(s, q) or (len(s) >= 3 and has(q, s))

    def profile_about(k, v):  # a chave pode estar na frase ("esquece meu nome"); o valor só se for ele
        k, v = _norm(k).replace("_", " "), _norm(v)
        return has(q, k) or has(k, q) or has(v, q)

    with _lock:
        data = load()
        before = len(data["fatos"]) + len(data["lembretes"]) + len(data["perfil"])
        data["fatos"] = [f for f in data["fatos"] if not about(f.get("texto", ""))]
        data["lembretes"] = [r for r in data["lembretes"] if not about(r.get("texto", ""))]
        data["perfil"] = {k: v for k, v in data["perfil"].items() if not profile_about(k, v)}
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
    print(f"Jarvis > Sei {len(lines)} coisa{'s' if len(lines) > 1 else ''} sobre o senhor:")
    print("\n".join("  " + x for x in lines))
    return "\n".join(lines)


# ------------------------- lembretes -------------------------

REPEATS = {"diario": 1, "todo dia": 1, "dias uteis": "uteis", "semanal": 7, "toda semana": 7, "mensal": "mes",
           "todo mes": "mes", "anual": "ano", "todo ano": "ano"}


def next_date(d, repeat):
    """O próximo dia de um lembrete que se repete (diário, dias úteis, semanal, mensal, anual)."""
    step = REPEATS.get(_norm(repeat).replace("á", "a"), None)
    if step is None:
        return None
    if step == "uteis":
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d
    if step == "mes":
        y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        import calendar
        return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))
    if step == "ano":
        try:
            return d.replace(year=d.year + 1)
        except ValueError:  # 29/02
            return d.replace(year=d.year + 1, day=28)
    return d + timedelta(days=step)


def add_reminder(text, day, hour="", pedido=False, despertador=False, repetir=""):
    """day = AAAA-MM-DD; hour = HH:MM (sem hora, avisa às 9h ou ao abrir o Jarvis).
    pedido=True: na hora ele FAZ o pedido ("toca evidências"), em vez de só avisar.
    repetir = diario | dias uteis | semanal | mensal | anual: depois de avisar, marca o próximo."""
    hour_in = str(hour or "").strip().lower()
    if not str(day or "").strip() and hour_in:  # sem dia: a próxima vez que der essa hora (hoje ou amanhã)
        m = re.match(r"(\d{1,2})(?:\s*(?:h|:|horas?)\s*(\d{2})?)?", hour_in)
        now = datetime.now()
        if m and (int(m.group(1)), int(m.group(2) or 0)) <= (now.hour, now.minute):
            day = (now.date() + timedelta(days=1)).isoformat()
        else:
            day = now.date().isoformat()
    try:
        d = date.fromisoformat(str(day).strip())
    except ValueError:
        _say(f"Não entendi a data {day}.")
        return False
    hour = str(hour or "").strip().lower()
    if hour:  # aceita "7h", "19h30", "07:00:00", "8 horas" e "24:00" (meia-noite = 00:00 do dia seguinte)
        m = re.fullmatch(r"(\d{1,2})(?:\s*(?:h|:|horas?)\s*(\d{2})?)?(?::\d{2})?", hour)
        h, mi = (int(m.group(1)), int(m.group(2) or 0)) if m else (99, 0)
        if h == 24 and mi == 0:
            h, d = 0, d + timedelta(days=1)
        if h > 23 or mi > 59:
            _say(f"Não entendi a hora {hour}.")
            return False
        hour = f"{h:02d}:{mi:02d}"
    with _lock:
        data = load()
        item = {"texto": str(text).strip(), "data": d.isoformat(), "hora": hour, "avisado": False}
        if pedido:
            item["pedido"] = True
        if despertador:
            item["despertador"] = True
        if repetir and next_date(d, repetir) is not None:
            item["repetir"] = _norm(repetir)
        data["lembretes"].append(item)
        save(data)
    if despertador:
        _say(f"Despertador marcado para {d:%d/%m} às {hour}" + (f", com {text}." if text else "."))
    elif pedido:
        _say(f"Combinado, senhor: {d:%d/%m}{' às ' + hour if hour else ''} eu faço \"{text}\".")
    else:
        _say(f"Lembrete marcado para {d:%d/%m}{' às ' + hour if hour else ''}: {text}.")
    if item.get("repetir"):
        _say(f"E repito {item['repetir']}.")
    return True


def due_reminders(now=None):
    """Lembretes que já venceram e ainda não foram avisados (marca como avisados)."""
    return [r.get("texto", "lembrete") for r, _ in _due(now)]


LATE = 30 * 60  # pedido agendado com mais de 30 min de atraso (o Bolha estava fechado) não é feito: só avisa


def due_items(now=None):
    """Para a fila do Jarvis: ("lembrete", texto) para avisar ou ("agendado", pedido) para fazer agora."""
    now = now or datetime.now()
    out = []
    for r, when in _due(now):
        text = r.get("texto", "lembrete")
        if r.get("despertador"):
            if (now - when).total_seconds() > LATE:
                out.append(("lembrete", f"não toquei o despertador das {when:%H:%M} porque eu estava desligado"))
            else:
                out.append(("despertador", text or "padrão"))
        elif not r.get("pedido"):
            out.append(("lembrete", text))
        elif (now - when).total_seconds() > LATE:
            out.append(("lembrete", f'não fiz "{text}" às {when:%H:%M} de {when:%d/%m} porque eu estava desligado'))
        else:
            out.append(("agendado", text))
    return out


def _due(now=None):
    """[(lembrete, quando)] dos que venceram e não foram avisados (marca como avisados)."""
    now = now or datetime.now()
    with _lock:
        data = load()
        due = []
        for r in data["lembretes"]:
            if r.get("avisado"):
                continue
            try:
                when = datetime.fromisoformat(r["data"] + "T" + (r.get("hora") or "09:00").zfill(5))
            except (ValueError, KeyError, TypeError):  # um lembrete estragado não trava os outros
                when = now
            if when <= now:
                due.append((dict(r), when))
                nxt = next_date(when.date(), r["repetir"]) if r.get("repetir") else None
                while nxt is not None and datetime.combine(nxt, when.time()) <= now:  # o Bolha ficou dias fechado
                    nxt = next_date(nxt, r["repetir"])
                if nxt is not None:
                    r["data"] = nxt.isoformat()  # repete: fica marcado para a próxima vez
                else:
                    r["avisado"] = True
        if due:
            save(data)
    return due


def reminder_watcher(put, every=30):
    """Thread que entrega os lembretes vencidos na fila de pedidos do Jarvis."""
    import time

    def loop():
        while True:
            try:
                for item in due_items():
                    put(item)
            except Exception:
                pass
            time.sleep(every)

    threading.Thread(target=loop, daemon=True).start()


# ------------------------- conversa -------------------------

def add_talk(user, reply):
    with _lock:
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
    """Resumo da memória para ir junto de cada pedido (vazio se o arquivo não puder ser lido agora)."""
    try:
        data = load()
    except Exception:
        return ""
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


# ------------------------- hábitos viram rotinas (28) -------------------------
WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
_VERB = {"open_target": "abre {}", "play_youtube": "toca {}", "run_routine": "modo {}", "enter_mode": "modo {}",
         "open_url": "abre o site {}", "spotify_play": "toca {} no spotify"}


def habit_routines(now=None, days=30):
    """Hábitos fortes o bastante para virar rotina: [{pedido, hora, repetir, dia, texto}].
    Mesmo pedido em 3+ dias diferentes, sempre perto da mesma hora."""
    now = now or datetime.now()
    groups = defaultdict(list)
    for t, name, detail in _log_entries():
        name = name.replace("ia:", "")
        if name in _VERB and now - t <= timedelta(days=days):
            groups[(name, detail)].append(t)
    out = []
    for (name, detail), times in groups.items():
        by_day = {}
        for t in sorted(times):
            by_day.setdefault(t.date(), t)  # a primeira vez de cada dia
        if len(by_day) < HABIT_DAYS:
            continue
        minutes = sorted(t.hour * 60 + t.minute for t in by_day.values())
        median = minutes[len(minutes) // 2]
        if any(abs(m - median) > 60 for m in minutes):
            continue  # cada dia numa hora diferente: não é rotina
        weekdays = {d.weekday() for d in by_day}
        if len(weekdays) == 1:
            repeat, label = "semanal", f"toda {WEEKDAYS[next(iter(weekdays))]}"
        elif weekdays <= {0, 1, 2, 3, 4} and len(weekdays) >= 3:
            repeat, label = "dias uteis", "nos dias úteis"
        else:
            repeat, label = "diario", "todo dia"
        try:
            what = next(iter(json.loads(detail).values()))
        except Exception:
            what = detail
        hour = f"{median // 60:02d}:{median % 60:02d}"
        day = now.date()
        if repeat == "semanal":
            day += timedelta(days=(next(iter(weekdays)) - day.weekday()) % 7)
        if datetime.combine(day, datetime.min.time()).replace(hour=median // 60, minute=median % 60) <= now:
            day += timedelta(days=7 if repeat == "semanal" else 1)
        request = _VERB[name].format(what)
        out.append({"pedido": request, "hora": hour, "repetir": repeat, "dia": day.isoformat(),
                    "texto": f"Senhor, {label} por volta das {hour} o senhor pede \"{request}\". "
                             f"Quer que eu faça sozinho?"})
    return out
