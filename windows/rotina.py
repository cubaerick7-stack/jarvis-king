# -*- coding: utf-8 -*-
"""Rotina e casa: modos prontos (aula, estudo, trabalho, jogo, dormir, filme, visita) que fazem várias coisas de
uma vez e se desfazem com "sai do modo"; não perturbe (segura os avisos e conta depois); contatos VIP; modo
visita; Pomodoro com foco; listas de compras e de tarefas; água e postura; contas a pagar; chuva antes de sair;
música por humor; contagem regressiva.

O que precisa durar fica em G:\\Jarvis\\config (listas, contas, contagens, modos do senhor).
"""

import json
import os
import re
import threading
import time
import unicodedata
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

CONFIG = Path(r"G:\Jarvis\config")
LISTS = CONFIG / "listas.json"
BILLS = CONFIG / "contas.json"
COUNTDOWNS = CONFIG / "contagens.json"
USER_MODES = CONFIG / "modos.json"
DISTRACTIONS = ("youtube", "instagram", "tiktok", "facebook", "twitter", " / x", "netflix", "twitch", "reddit",
                "prime video", "9gag", "kwai")


def _say(text):
    print(f"Jarvis > {text}")


def norm(text):
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s/:-]", " ", text)).strip()


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


# ========================= MODOS (13, 77, 87, S1-S7) =========================

MODES = {
    "aula": {"descricao": "volume em 30, Teams aberto, não perturbe (WhatsApp em silêncio)",
             "acoes": [{"name": "set_volume", "args": {"percent": 30}},
                       {"name": "open_target", "args": {"target": "teams"}}],
             "nao_perturbe": True},
    "estudo": {"descricao": "Pomodoro de 25 minutos, lofi baixinho, bloqueia distrações e não perturbe",
               "acoes": [{"name": "set_volume", "args": {"percent": 20}},
                         {"name": "play_youtube", "args": {"query": "lofi hip hop para estudar"}},
                         {"name": "start_pomodoro", "args": {"minutes": 25}}],
               "nao_perturbe": True},
    "trabalho": {"descricao": "arruma as janelas do layout trabalho (abre o que faltar) e o e-mail",
                 "acoes": [{"name": "apply_layout", "args": {"name": "trabalho"}}]},
    "jogo": {"descricao": "libera memória, fecha o que pesa, não perturbe, Discord aberto e prioridade para o jogo",
             "acoes": [{"name": "clean_memory", "args": {}},
                       {"name": "open_target", "args": {"target": "discord"}}],
             "fecha": ["onedrive", "teams"], "nao_perturbe": True, "prioridade": True},
    "dormir": {"descricao": "boa noite com resumo e lembretes de amanhã, volume baixo e apaga a tela",
               "acoes": [{"name": "good_night", "args": {}}, {"name": "set_volume", "args": {"percent": 10}}],
               "nao_perturbe": True, "apaga_tela": True},
    "filme": {"descricao": "volume alto, não perturbe e o HUD apagado",
              "acoes": [{"name": "set_volume", "args": {"percent": 80}}],
              "nao_perturbe": True, "hud": False},
    "visita": {"descricao": "esconde notificações e cards pessoais (WhatsApp, memória, lembretes)",
               "acoes": [], "visita": True, "nao_perturbe": True},
}

state = {"modo": "", "volume_antes": None, "visita": False, "foco": False}
dnd = {"ate": None, "segurados": [], "motivo": ""}
FOREVER = datetime(2999, 1, 1)


def modes():
    out = {k: dict(v) for k, v in MODES.items()}
    user = _load(USER_MODES, {})
    if isinstance(user, dict):
        for k, v in user.items():
            if isinstance(v, dict):
                out[norm(k)] = {**out.get(norm(k), {}), **v}
    return out


def find_mode(name):
    key = norm(re.sub(r"^(?:o |a )?(?:modo|rotina)\s+", "", norm(name)))
    all_ = modes()
    if key in all_:
        return key
    for alias, real in (("estudar", "estudo"), ("estudos", "estudo"), ("trabalhar", "trabalho"), ("jogar", "jogo"),
                        ("gamer", "jogo"), ("games", "jogo"), ("dormir", "dormir"), ("sono", "dormir"),
                        ("cinema", "filme"), ("visitas", "visita"), ("aulas", "aula")):
        if key == alias:
            return real
    return None


def enter_mode(name, execute, get_volume=None, close_app=None, set_windows_dnd=None, on_screen=None):
    """Liga um modo: guarda como estava (volume) e faz tudo de uma vez."""
    key = find_mode(name)
    if key is None:
        return None
    mode = modes()[key]
    if state["modo"] and state["modo"] != key:
        exit_mode(execute, quiet=True, set_windows_dnd=set_windows_dnd, on_screen=on_screen)
    try:
        state["volume_antes"] = get_volume() if get_volume else None
    except Exception:
        state["volume_antes"] = None
    state["modo"] = key
    _say(f"Modo {key}: {mode.get('descricao', '')}.")
    if mode.get("nao_perturbe"):
        start_dnd(None, f"modo {key}", set_windows_dnd)
    if mode.get("visita"):
        state["visita"] = True
    if mode.get("hud") is False and on_screen:
        on_screen("hud", False)
    for name_ in mode.get("fecha", []):
        if close_app:
            try:
                close_app(name_)
            except Exception:
                pass
    ok = True
    for action in mode.get("acoes", []):
        if execute(action.get("name", ""), action.get("args", {}) or {}) is False:
            ok = False
    if mode.get("prioridade"):
        execute("game_priority", {})
    if mode.get("apaga_tela"):
        execute("screen_off", {})
    _say(f"Modo {key} ligado. Diga \"sai do modo\" para desfazer.")
    return ok


def exit_mode(execute, quiet=False, set_windows_dnd=None, on_screen=None, set_volume=None):
    """Desfaz o modo: volume de antes, avisos de volta (e conta o que segurou), Pomodoro parado."""
    key = state["modo"]
    if not key:
        if not quiet:
            _say("Não estou em nenhum modo, senhor.")
        return False
    held = stop_dnd(set_windows_dnd) if dnd["ate"] == FOREVER else []
    stop_pomodoro(quiet=True)
    state["visita"] = False
    if on_screen:
        on_screen("hud", True)
    if state["volume_antes"] is not None:
        execute("set_volume", {"percent": state["volume_antes"]})
    state.update(modo="", volume_antes=None)
    if not quiet:
        _say(f"Saí do modo {key}, senhor. Tudo como estava." + (held_summary(held) if held else ""))
    return True


# ========================= NÃO PERTURBE (76), VIP (75), VISITA (98) =========================

def start_dnd(until=None, why="", set_windows_dnd=None):
    """Segura os avisos até a hora pedida (None = até sair do modo / desligar)."""
    dnd.update(ate=until or FOREVER, motivo=why)
    if set_windows_dnd:
        try:
            set_windows_dnd(False)
        except Exception:
            pass
    return True


def dnd_until_text(text, now=None):
    """ "até as 18h" / "por 2 horas" / "por 30 minutos" -> datetime (ou None se não tiver hora)."""
    now = now or datetime.now()
    t = norm(text)
    m = re.search(r"\bpor (\d+)\s*(h|hora|horas|min|minuto|minutos)\b", t)
    if m:
        n = int(m.group(1))
        return now + (timedelta(hours=n) if m.group(2).startswith("h") else timedelta(minutes=n))
    m = re.search(r"\bate (?:as |a )?(\d{1,2})(?:\s*(?:h|:|horas?)\s*(\d{2})?)?\b", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if h > 23 or mi > 59:
            return None
        when = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        return when if when > now else when + timedelta(days=1)
    if "amanha" in t:
        return (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    return None


def stop_dnd(set_windows_dnd=None):
    held = list(dnd["segurados"])
    dnd.update(ate=None, segurados=[], motivo="")
    if set_windows_dnd:
        try:
            set_windows_dnd(True)
        except Exception:
            pass
    return held


def dnd_active(now=None):
    return dnd["ate"] is not None and (now or datetime.now()) < dnd["ate"]


def dnd_expired(now=None, set_windows_dnd=None):
    """O horário do não perturbe passou? (True, o que foi segurado) e desliga; senão (False, [])."""
    if dnd["ate"] is not None and dnd["ate"] != FOREVER and (now or datetime.now()) >= dnd["ate"]:
        return True, stop_dnd(set_windows_dnd)
    return False, []


def vips():
    import aprende
    return [norm(v) for v in aprende.pref("vip", []) or []]


def set_vip(name, on=True):
    import aprende
    current = aprende.pref("vip", []) or []
    key = norm(name)
    current = [v for v in current if norm(v) != key] + ([str(name).strip()] if on else [])
    aprende.set_pref("vip", current)
    _say(f"{str(name).strip()} {'agora é VIP: aviso na hora, até no não perturbe' if on else 'não é mais VIP'}.")
    return True


def is_vip(who):
    w = norm(who)
    return bool(w) and any(v and (v in w or w in v) for v in vips())


def should_hold(text, who=""):
    """Aviso que espera: não perturbe ligado (menos VIP) ou, havendo VIPs, mensagem de quem não é VIP."""
    if who and is_vip(who):
        return False
    if dnd_active():
        dnd["segurados"].append((datetime.now().strftime("%H:%M"), str(text)))
        return True
    return False


def held_summary(held):
    held = [h for h in held if h[1]]
    if not held:
        return ""
    return f" Enquanto isso, chegaram {len(held)} aviso{'s' if len(held) > 1 else ''}: " + \
        "; ".join(f"{t} {x}" for t, x in held[:6]) + "."


PERSONAL_CARDS = ("whatsapp", "memória", "memoria", "lembrete", "aviso", "o que sei de você", "histórico", "pessoa",
                  "lista", "contas", "e-mail", "email", "agenda", "instagram")


def hide_card(title):
    """No modo visita, os cards pessoais não aparecem."""
    return state["visita"] and any(p in norm(title) for p in map(norm, PERSONAL_CARDS))


# ========================= POMODORO (78) =========================

pomodoro = {"ativo": False, "fase": "", "fim": None, "ciclo": 0, "parar": threading.Event()}


def start_pomodoro(minutes, alert, pause=5, cycles=4, foreground_title=None, minimize=None):
    """Pomodoro com foco: avisa a pausa e a volta; no foco, minimiza YouTube, Instagram... e avisa."""
    minutes, pause, cycles = float(minutes or 25), float(pause or 5), int(cycles or 4)
    stop_pomodoro(quiet=True)
    flag = threading.Event()
    pomodoro.update(ativo=True, ciclo=1, parar=flag)
    state["foco"] = True

    def run():
        warned = 0.0
        for c in range(1, cycles + 1):
            pomodoro.update(fase="foco", ciclo=c, fim=datetime.now() + timedelta(minutes=minutes))
            while datetime.now() < pomodoro["fim"]:
                if flag.wait(5):
                    return
                if foreground_title:
                    try:
                        title = norm(foreground_title() or "")
                    except Exception:
                        title = ""
                    if title and any(d.strip() in title for d in DISTRACTIONS) and time.time() - warned > 60:
                        warned = time.time()
                        if minimize:
                            try:
                                minimize()
                            except Exception:
                                pass
                        alert("Foco, senhor. Tirei a distração da frente; ela volta na pausa.")
            if c == cycles:
                break
            pomodoro.update(fase="pausa", fim=datetime.now() + timedelta(minutes=pause))
            alert(f"Pausa de {pause:g} minutos, senhor. Levante, beba água.")
            if flag.wait(pause * 60):
                return
            alert(f"De volta ao foco, senhor. Ciclo {c + 1} de {cycles}.")
        pomodoro.update(ativo=False, fase="")
        state["foco"] = False
        alert("Pomodoro concluído, senhor. Bom trabalho.")

    threading.Thread(target=run, daemon=True).start()
    _say(f"Pomodoro: {minutes:g} minutos de foco, {pause:g} de pausa, {cycles} ciclos. Distrações vão para trás.")
    return True


def stop_pomodoro(quiet=False):
    was = pomodoro["ativo"]
    pomodoro["parar"].set()
    pomodoro.update(ativo=False, fase="")
    state["foco"] = False
    if not quiet:
        _say("Pomodoro parado." if was else "Não tinha Pomodoro rodando.")
    return was


def pomodoro_status():
    if not pomodoro["ativo"]:
        _say("Sem Pomodoro agora.")
        return False
    left = max(0, int((pomodoro["fim"] - datetime.now()).total_seconds() // 60))
    _say(f"{'Foco' if pomodoro['fase'] == 'foco' else 'Pausa'}, ciclo {pomodoro['ciclo']}: faltam {left} minutos.")
    return True


# ========================= LISTAS (79, S11, S19) =========================

SECTIONS = {
    "Hortifrúti": "alface tomate cebola alho batata cenoura banana maca laranja limao fruta verdura legume abacate "
                  "mamao uva morango pepino pimentao couve brocolis abobrinha melancia manga",
    "Açougue": "carne frango peixe linguica bife costela picanha patinho moida salsicha bacon presunto",
    "Laticínios": "leite queijo iogurte manteiga requeijao creme nata ovo ovos margarina",
    "Padaria": "pao paes bolo biscoito bolacha torrada rosca",
    "Mercearia": "arroz feijao macarrao oleo acucar sal cafe farinha molho milho ervilha atum sardinha aveia "
                 "tempero achocolatado cereal",
    "Bebidas": "agua refrigerante suco cerveja vinho energetico cha",
    "Limpeza": "detergente sabao amaciante desinfetante agua sanitaria esponja vassoura saco de lixo alcool",
    "Higiene": "sabonete shampoo xampu condicionador pasta de dente escova papel higienico desodorante absorvente "
               "fio dental",
}


def section_of(item):
    words = set(norm(item).split())
    for sec, keys in SECTIONS.items():
        if words & set(keys.split()) or norm(item) in keys:
            return sec
    return "Outros"


def list_name(name):
    n = norm(name)
    if not n or "compra" in n or "mercado" in n or "supermercado" in n:
        return "compras"
    if "tarefa" in n or "fazer" in n or "afazer" in n:
        return "tarefas"
    return re.sub(r"^(?:a |o )?(?:lista (?:de |do |da )?)", "", n) or "compras"


def split_items(text):
    return [i.strip(" .") for i in re.split(r"\s*(?:,|;|\be\b|\+)\s*", str(text)) if i.strip(" .")]


def add_items(name, text, priority=""):
    key = list_name(name)
    lists = _load(LISTS, {})
    items = lists.setdefault(key, [])
    added = []
    for it in split_items(text):
        if any(norm(x["item"]) == norm(it) and not x.get("feito") for x in items):
            continue
        entry = {"item": it, "feito": False, "quando": datetime.now().isoformat(timespec="minutes")}
        if key == "compras":
            entry["secao"] = section_of(it)
        if priority:
            entry["prioridade"] = norm(priority)
        items.append(entry)
        added.append(it)
    _save(LISTS, lists)
    if not added:
        _say(f"Isso já estava na lista de {key}.")
        return True
    _say(f"Anotei na lista de {key}: {', '.join(added)}.")
    return True


def check_item(name, text, done=True):
    """Risca (ou tira o risco) de um item: "risca o leite da lista"."""
    key = list_name(name)
    lists = _load(LISTS, {})
    items = lists.get(key, [])
    hits = 0
    for it in split_items(text):
        for x in items:
            if norm(it) in norm(x["item"]) and x.get("feito") != done:
                x["feito"] = done
                hits += 1
                break
    _save(LISTS, lists)
    if not hits:
        _say(f"Não achei isso na lista de {key}.")
        return False
    _say(f"{'Risquei' if done else 'Voltei'} {hits} item{'s' if hits > 1 else ''} da lista de {key}.")
    return True


def remove_items(name, text):
    key = list_name(name)
    lists = _load(LISTS, {})
    before = len(lists.get(key, []))
    wanted = [norm(i) for i in split_items(text)]
    lists[key] = [x for x in lists.get(key, []) if not any(w in norm(x["item"]) for w in wanted)]
    _save(LISTS, lists)
    removed = before - len(lists[key])
    _say(f"Tirei {removed} item{'s' if removed != 1 else ''} da lista de {key}." if removed else "Não achei isso na lista.")
    return removed > 0


def clear_list(name, confirm, only_done=False):
    key = list_name(name)
    lists = _load(LISTS, {})
    if not lists.get(key):
        _say(f"A lista de {key} já está vazia.")
        return True
    if not only_done and not confirm(f"Apago a lista de {key} inteira?"):
        _say("Ok, deixei a lista.")
        return False
    lists[key] = [x for x in lists[key] if not x.get("feito")] if only_done else []
    _save(LISTS, lists)
    _say(f"Lista de {key} {'sem os riscados' if only_done else 'apagada'}.")
    return True


PRIORITY = {"alta": 0, "urgente": 0, "media": 1, "": 1, "baixa": 2}


def list_text(name):
    key = list_name(name)
    items = _load(LISTS, {}).get(key, [])
    if not items:
        return key, ""
    lines = []
    if key == "compras":
        for sec in list(SECTIONS) + ["Outros"]:
            sec_items = [x for x in items if x.get("secao", section_of(x["item"])) == sec]
            if sec_items:
                lines.append(f"{sec}:")
                lines += [f"  {'✓' if x.get('feito') else '•'} {x['item']}" for x in sec_items]
    else:
        items = sorted(items, key=lambda x: (x.get("feito", False), PRIORITY.get(x.get("prioridade", ""), 1)))
        for i, x in enumerate(items, 1):
            pr = f" ({x['prioridade']})" if x.get("prioridade") else ""
            lines.append(f"{i}. {'✓ ' if x.get('feito') else ''}{x['item']}{pr}")
    return key, "\n".join(lines)


def show_list(name, card=None):
    key, text = list_text(name)
    if not text:
        _say(f"A lista de {key} está vazia.")
        return True
    pending = sum(1 for x in _load(LISTS, {}).get(key, []) if not x.get("feito"))
    if card:
        card(f"Lista de {key}", text)
    _say(f"Lista de {key}: {pending} item{'s' if pending != 1 else ''} para {'comprar' if key == 'compras' else 'fazer'}.")
    print(text)
    return True


# ========================= ÁGUA E POSTURA (80) =========================

wellness = {"ativo": False, "parar": threading.Event()}


def idle_seconds():
    """Há quanto tempo o senhor não mexe no mouse nem no teclado (0 fora do Windows)."""
    try:
        import ctypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
        return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000
    except Exception:
        return 0


def start_wellness(alert, every_minutes=60, kind="ambos"):
    stop_wellness(quiet=True)
    flag = threading.Event()
    wellness.update(ativo=True, parar=flag)
    msgs = {"agua": ["Senhor, hora de beber um copo d'água."],
            "postura": ["Senhor, confira a postura: costas retas e ombros relaxados."]}
    pool = msgs["agua"] + msgs["postura"] if norm(kind) in ("ambos", "") else msgs.get(norm(kind), msgs["agua"])

    def run():
        i = 0
        while not flag.wait(float(every_minutes) * 60):
            if idle_seconds() < 300:  # só com o PC em uso
                alert(pool[i % len(pool)])
                i += 1
    threading.Thread(target=run, daemon=True).start()
    _say(f"Lembrete de {'água e postura' if len(pool) > 1 else norm(kind)} a cada {every_minutes:g} minutos, "
         "só quando o senhor estiver no PC.")
    return True


def stop_wellness(quiet=False):
    wellness["parar"].set()
    was = wellness["ativo"]
    wellness["ativo"] = False
    if not quiet:
        _say("Parei os lembretes de água e postura." if was else "Não tinha lembrete de água ligado.")
    return was


# ========================= CONTAS A PAGAR (81, S12) =========================

def _money(text):
    """ "R$ 1.234,56" -> 1234.56; "89,90" -> 89.9; "150" -> 150.0."""
    t = str(text or "").replace("R$", "").strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else None


def next_due(day, today=None):
    today = today or date.today()
    import calendar
    y, m = today.year, today.month
    d = min(int(day), calendar.monthrange(y, m)[1])
    due = date(y, m, d)
    if due < today:
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        due = date(y, m, min(int(day), calendar.monthrange(y, m)[1]))
    return due


def add_bill(name, day, value="", add_reminder=None):
    """Conta todo mês no dia X: lembra 2 dias antes e no dia (lembrete mensal)."""
    try:
        day = int(re.search(r"\d{1,2}", str(day)).group(0))
    except (AttributeError, ValueError):
        _say("Em que dia vence a conta, senhor?")
        return False
    if not 1 <= day <= 31:
        _say("Esse dia não existe.")
        return False
    bills = _load(BILLS, [])
    bills = [b for b in bills if norm(b["nome"]) != norm(name)]
    amount = _money(value)
    bills.append({"nome": str(name).strip(), "dia": day, "valor": amount})
    _save(BILLS, bills)
    due = next_due(day)
    if add_reminder:
        label = f"pagar {name}" + (f" (R$ {amount:.2f})".replace(".", ",") if amount else "")
        add_reminder(f"{label}: vence dia {day}", (due - timedelta(days=2)).isoformat(), "09:00", repetir="mensal")
        add_reminder(f"{label}: vence hoje", due.isoformat(), "09:00", repetir="mensal")
    _say(f"Conta {name} anotada: vence todo dia {day}. Aviso 2 dias antes e no dia.")
    return True


def list_bills(today=None):
    bills = _load(BILLS, [])
    if not bills:
        _say("Não tenho contas anotadas. Diga, por exemplo, \"a conta de luz vence dia 10\".")
        return True
    today = today or date.today()
    rows = sorted(((next_due(b["dia"], today), b) for b in bills), key=lambda x: x[0])
    total = sum(b.get("valor") or 0 for _, b in rows)
    _say(f"Contas do mês ({len(rows)}" + (f", R$ {total:.2f}".replace(".", ",") if total else "") + "):")
    for due, b in rows:
        left = (due - today).days
        when = "hoje" if left == 0 else "amanhã" if left == 1 else f"em {left} dias"
        val = f" R$ {b['valor']:.2f}".replace(".", ",") if b.get("valor") else ""
        print(f"  - {b['nome']}{val}: dia {b['dia']} ({when})")
    return True


# ========================= CHUVA ANTES DE SAIR (82) =========================

def rain_forecast(city, hours=6, get_json=None):
    """(chance máxima de chuva nas próximas horas, hora dela, nome da cidade) pelo Open-Meteo, ou None."""
    if get_json is None:
        import ferramentas as F
        get_json = F._get_json
    if not city:
        return None
    found = get_json("https://geocoding-api.open-meteo.com/v1/search?count=1&language=pt&name="
                     + urllib.parse.quote(city)).get("results") or []
    if not found:
        return None
    place = found[0]
    data = get_json(f"https://api.open-meteo.com/v1/forecast?latitude={place['latitude']}&longitude={place['longitude']}"
                    "&hourly=precipitation_probability&forecast_days=2&timezone=auto")
    times = data.get("hourly", {}).get("time", [])
    probs = data.get("hourly", {}).get("precipitation_probability", [])
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    best = (0, "")
    for t, p in zip(times, probs):
        try:
            when = datetime.fromisoformat(t)
        except ValueError:
            continue
        if now <= when <= now + timedelta(hours=hours) and p is not None and p > best[0]:
            best = (int(p), when.strftime("%H:%M"))
    return best[0], best[1], place.get("name", city)


def rain_warning(city, hours=6, get_json=None):
    try:
        found = rain_forecast(city, hours, get_json)
    except Exception as e:
        _say(f"Não consegui ver a chuva agora ({e}).")
        return False
    if not found:
        _say("Para ver a chuva preciso da sua cidade: diga \"eu moro em ...\".")
        return False
    p, at, name = found
    if p >= 60:
        _say(f"Leve o guarda-chuva, senhor: {p}% de chance de chuva em {name} por volta das {at}.")
    elif p >= 30:
        _say(f"Talvez chova em {name} ({p}% por volta das {at}). Um guarda-chuva na mochila não faz mal.")
    else:
        _say(f"Sem chuva à vista em {name} nas próximas {hours} horas ({p}%).")
    return True


# ========================= MÚSICA POR HUMOR (83, S65) E CONTAGEM (85, S20) =========================

MOODS = {
    "animar": "músicas animadas para levantar o astral", "animado": "músicas animadas para levantar o astral",
    "feliz": "músicas felizes brasileiras", "focar": "lofi hip hop para concentrar", "foco": "lofi hip hop para concentrar",
    "estudar": "lofi hip hop para estudar", "relaxar": "música relaxante calma", "calma": "música relaxante calma",
    "triste": "músicas para ficar bem quando está triste", "dormir": "música calma para dormir",
    "treinar": "músicas para treinar academia", "academia": "músicas para treinar academia",
    "festa": "músicas de festa brasileiras", "romantico": "músicas românticas", "trabalhar": "música instrumental para trabalhar",
    "chuva": "músicas para dia de chuva", "nostalgia": "músicas anos 2000 nostalgia",
}


def mood_query(text, hour=None):
    t = norm(text)
    for k, q in MOODS.items():
        if re.search(rf"\b{k}\w*", t):
            return q
    hour = datetime.now().hour if hour is None else hour
    try:
        import aprende
        period = "manha" if hour < 12 else "tarde" if hour < 18 else "noite"
        learned = aprende.pref(f"musica_{period}")
        if learned:
            return learned
    except Exception:
        pass
    return "músicas animadas para começar o dia" if hour < 12 else "lofi hip hop para concentrar" if hour < 18 \
        else "música relaxante calma"


def add_countdown(name, day):
    try:
        d = date.fromisoformat(str(day).strip())
    except ValueError:
        _say(f"Não entendi a data {day}.")
        return False
    items = _load(COUNTDOWNS, {})
    items[norm(name)] = {"nome": str(name).strip(), "data": d.isoformat()}
    _save(COUNTDOWNS, items)
    left = (d - date.today()).days
    _say(f"Anotado: {name} em {d:%d/%m/%Y}, daqui a {left} dia{'s' if left != 1 else ''}.")
    return True


def days_until(name, reminders=(), today=None):
    """ "quantos dias para a prova?": olha as contagens e os lembretes."""
    today = today or date.today()
    key = norm(name)
    items = _load(COUNTDOWNS, {})
    hit = items.get(key) or next((v for k, v in items.items() if key and (key in k or k in key)), None)
    if hit is None:
        for r in reminders:
            if key and key in norm(r.get("texto", "")) and not r.get("avisado"):
                hit = {"nome": r["texto"], "data": r["data"]}
                break
    if hit is None:
        _say(f"Não sei a data de {name}. Diga, por exemplo, \"a prova é dia 20 de novembro\".")
        return False
    d = date.fromisoformat(hit["data"])
    left = (d - today).days
    if left < 0:
        _say(f"{hit['nome']} já passou ({d:%d/%m}).")
    elif left == 0:
        _say(f"{hit['nome']} é hoje, senhor!")
    else:
        weeks = f", umas {left // 7} semanas" if left >= 14 else ""
        _say(f"Faltam {left} dia{'s' if left > 1 else ''} para {hit['nome']} ({d:%d/%m}{weeks}).")
    return left


def list_countdowns(today=None):
    today = today or date.today()
    items = sorted(_load(COUNTDOWNS, {}).values(), key=lambda v: v["data"])
    items = [v for v in items if date.fromisoformat(v["data"]) >= today]
    if not items:
        _say("Não tenho contagens. Diga \"conta os dias para a viagem dia 20/12\".")
        return True
    _say("Contagens:")
    for v in items:
        print(f"  - {v['nome']}: {(date.fromisoformat(v['data']) - today).days} dias ({v['data'][8:10]}/{v['data'][5:7]})")
    return True
