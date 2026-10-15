# -*- coding: utf-8 -*-
"""Diário de cada pedido (o motor que faz o Bolha melhorar).

Cada pedido vira uma linha em G:\\Jarvis\\config\\diario.jsonl: o que o senhor disse, por onde ele entendeu
(atalho, aprendido, habilidade ou IA), o que fez, se deu certo, quanto demorou em cada parte
(ouvir, pensar, fazer, falar) e o erro, se houve.

Com isso:
- "o que deu errado hoje?" lista os pedidos que falharam;
- "por que você fez isso?" explica o último pedido;
- todo domingo sai o G:\\Jarvis\\config\\relatorio.md (as 10 falhas mais comuns e o que está lento),
  que o senhor manda para o Claude e o Codex;
- "gera o relatório de erro" monta um arquivo pronto para mandar (sem chaves nem senhas).
"""

import json
import os
import platform
import re
import sys
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

FILE = Path(r"G:\Jarvis\config\diario.jsonl")
REPORT = Path(r"G:\Jarvis\config\relatorio.md")
ERROR_REPORT = Path(r"G:\Jarvis\config\relatorio-erro.md")
PHASES = ("ouvir", "pensar", "fazer", "falar")
SLOW = 4.0  # segundos: pedido mais lento que isso entra na lista de lentos
MAX_LINES = 20000  # o diário não cresce para sempre: guarda os últimos pedidos

_lock = threading.RLock()
current = None  # o pedido em andamento (o laço do Jarvis atende um por vez)
last = None  # o último pedido terminado (para "por que você fez isso?" e "errou")


def _norm(text):
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def _say(text):
    print(f"Jarvis > {text}")


# ------------------------- o pedido em andamento -------------------------

class Entry(dict):
    """Um pedido: dicionário simples (vira JSON) com ajudantes para cronometrar."""

    def __init__(self, text, origin=""):
        super().__init__(quando=datetime.now().isoformat(timespec="seconds"), origem=origin or "",
                         disse=str(text or "")[:300], rota="", acoes=[], fala="", ok=True, erro="",
                         tempos={p: 0.0 for p in PHASES})
        self.running = set()  # fases sendo cronometradas agora

    def add_time(self, phase, seconds):
        if phase in self["tempos"]:
            self["tempos"][phase] = round(self["tempos"][phase] + max(0.0, float(seconds)), 2)

    @property
    def total(self):
        return round(sum(self["tempos"].values()), 2)


def start(text, origin="", heard_seconds=0.0):
    """Começa a registrar um pedido. heard_seconds = quanto levou para ouvir (gravar + transcrever)."""
    global current
    current = Entry(text, origin)
    if heard_seconds:
        current.add_time("ouvir", heard_seconds)
    return current


@contextmanager
def timing(phase):
    """with diario.timing("pensar"): ... soma o tempo no pedido em andamento (se houver)."""
    entry = current
    nested = entry is not None and phase in entry.running  # rotina dentro de ferramenta: não conta duas vezes
    if entry is not None:
        entry.running.add(phase)
    t0 = time.perf_counter()
    try:
        yield
    finally:
        if entry is not None and not nested:
            entry.running.discard(phase)
            entry.add_time(phase, time.perf_counter() - t0)


def route(name):
    """Por onde o pedido foi entendido: atalho, aprendido, habilidade, ia, conversa..."""
    if current is not None and not current["rota"]:
        current["rota"] = name


def action(name, args=None, ok=True):
    if current is None:
        return
    try:
        args = json.loads(json.dumps(args or {}, ensure_ascii=False, default=str))
    except Exception:
        args = {}
    current["acoes"].append({"nome": str(name), "args": args, "ok": ok is not False})
    if ok is False:
        current["ok"] = False


def error(text):
    if current is not None:
        current["ok"] = False
        current["erro"] = str(text)[:400]


def finish(said=""):
    """Fecha o pedido: grava no diário e devolve a linha do cronômetro (para o console)."""
    global current, last
    entry = current
    if entry is None:
        return ""
    current = None
    entry["fala"] = str(said or "")[:300]
    if not entry["rota"]:
        entry["rota"] = "atalho" if entry["acoes"] else "conversa"
    if re.match(r"^(?:Desculpe, senhor, não consegui|Não consegui falar com a IA|Não deu certo)", entry["fala"]):
        entry["ok"] = False
    entry["total"] = entry.total
    _append(entry)
    if entry["rota"] not in ("nota", "meta"):  # "errou"/"boa" e "por que fez isso?" falam do pedido anterior
        last = entry
    return stopwatch_line(entry)


def stopwatch_line(entry):
    """ "(tempo 3,4 s: ouvir 1,2 · pensar 0,8 · fazer 0,3 · falar 1,1)" """
    t = entry.get("tempos", {})
    parts = [f"{p} {t.get(p, 0):.1f}".replace(".", ",") for p in PHASES if t.get(p)]
    total = f"{entry.get('total', sum(t.values())):.1f}".replace(".", ",")
    return f"(tempo {total} s" + (": " + " · ".join(parts) if parts else "") + ")"


def mark_last(ok, note=""):
    """O senhor disse "errou" ou "boa" sobre o último pedido: grava a nota no diário."""
    if last is None:
        return False
    item = {"quando": datetime.now().isoformat(timespec="seconds"), "nota": "boa" if ok else "errou",
            "sobre": last.get("disse", ""), "detalhe": str(note or "")[:200]}
    _append(item)
    if not ok:
        last["ok"] = False
    return True


# ------------------------- arquivo -------------------------

def _append(item):
    try:
        with _lock:
            FILE.parent.mkdir(parents=True, exist_ok=True)
            with FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            _trim()
    except Exception:
        pass  # o diário nunca derruba o Bolha


_writes = 0


def _trim():
    global _writes
    _writes += 1
    if _writes % 500:
        return
    lines = FILE.read_text(encoding="utf-8").splitlines()
    if len(lines) > MAX_LINES:
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text("\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8")
        os.replace(tmp, FILE)


def entries(since=None, until=None):
    """Os pedidos gravados (sem as notas), do mais antigo para o mais novo."""
    out = []
    try:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return out
    for line in lines:
        try:
            item = json.loads(line)
            when = datetime.fromisoformat(item["quando"])
        except (ValueError, KeyError, TypeError):
            continue
        if since and when < since or until and when >= until:
            continue
        item["_quando"] = when
        out.append(item)
    return out


def requests(since=None, until=None):
    return [e for e in entries(since, until) if "disse" in e]


def notes(since=None, until=None):
    return [e for e in entries(since, until) if "nota" in e]


def _day_range(day="hoje"):
    d = _norm(day)
    target = date.today()
    if d == "ontem":
        target -= timedelta(days=1)
    elif re.fullmatch(r"\d{4} \d{2} \d{2}", d):
        target = date.fromisoformat(d.replace(" ", "-"))
    start_ = datetime.combine(target, datetime.min.time())
    return target, start_, start_ + timedelta(days=1)


def _failed(e):
    return e.get("ok") is False


# ------------------------- perguntas do senhor -------------------------

def what_went_wrong(day="hoje"):
    """ "o que deu errado hoje?": os pedidos que falharam (ou que o senhor disse que errei)."""
    target, a, b = _day_range(day)
    wrong = [e for e in requests(a, b) if _failed(e)]
    told = {(_norm(n.get("sobre"))) for n in notes(a, b) if n.get("nota") == "errou"}
    wrong += [e for e in requests(a, b) if not _failed(e) and _norm(e.get("disse")) in told]
    wrong.sort(key=lambda e: e["_quando"])
    if not wrong:
        _say(f"Nada deu errado em {target:%d/%m}, senhor." if requests(a, b)
             else f"Não tenho pedidos registrados em {target:%d/%m}.")
        return True
    _say(f"{len(wrong)} pedido{'s' if len(wrong) > 1 else ''} deu errado em {target:%d/%m}:")
    for e in wrong[-15:]:
        why = e.get("erro") or next((f"{a['nome']} falhou" for a in e.get("acoes", []) if not a.get("ok")), "") \
            or ("o senhor disse que errei" if _norm(e.get("disse")) in told else e.get("fala", ""))
        print(f"  {e['_quando']:%H:%M} \"{e.get('disse', '')}\": {why[:120]}")
    return True


def explain_last():
    """ "por que você fez isso?": o que ele entendeu, por onde e o que fez no último pedido."""
    e = last or next(iter(reversed(requests())), None)
    if not e:
        _say("Ainda não fiz nada para explicar, senhor.")
        return True
    how = {"atalho": "um comando que eu conheço de cor", "aprendido": "o que o senhor me ensinou",
           "habilidade": "uma habilidade que o senhor criou", "ia": "a IA, que escolheu as ações",
           "conversa": "uma conversa, sem ação"}.get(e.get("rota"), e.get("rota") or "a IA")
    acts = e.get("acoes") or []
    did = "; ".join(f"{a['nome']} {_args_text(a.get('args'))}".strip() + ("" if a.get("ok") else " (falhou)")
                    for a in acts) or "nenhuma ação"
    _say(f"O senhor pediu \"{e.get('disse', '')}\". Entendi por {how} e fiz: {did}. "
         + ("Deu certo." if e.get("ok", True) else f"Não deu certo{': ' + e['erro'] if e.get('erro') else ''}.")
         + " Se errei, diga \"errou, era ...\" que eu aprendo.")
    return True


def _args_text(args):
    if not isinstance(args, dict) or not args:
        return ""
    return "(" + ", ".join(f"{v}" for v in args.values() if str(v).strip())[:80] + ")"


def stopwatch_today():
    """O cronômetro do dia: média de cada parte e o pedido mais lento."""
    target, a, b = _day_range("hoje")
    items = requests(a, b)
    if not items:
        _say("Ainda não tenho pedidos cronometrados hoje.")
        return True
    avg = {p: sum(e.get("tempos", {}).get(p, 0) for e in items) / len(items) for p in PHASES}
    slow = max(items, key=lambda e: e.get("total", 0))
    _say(f"Hoje, em média: " + ", ".join(f"{p} {v:.1f} s".replace(".", ",") for p, v in avg.items())
         + f". O mais lento foi \"{slow.get('disse', '')}\" ({slow.get('total', 0):.1f} s).".replace(".", ",", 1))
    return True


# ------------------------- relatório da semana (M4) -------------------------

def build_report(end=None, days=7):
    """O texto do relatório: as 10 falhas mais comuns e o que está lento."""
    end = end or datetime.now()
    start_ = end - timedelta(days=days)
    items = requests(start_, end)
    wrong_notes = [n for n in notes(start_, end) if n.get("nota") == "errou"]
    good_notes = [n for n in notes(start_, end) if n.get("nota") == "boa"]
    lines = [f"# Relatório da semana do Bolha ({start_:%d/%m} a {end:%d/%m/%Y})", "",
             "Mande este arquivo para o Claude ou o Codex: é a lista de trabalho deles.", ""]
    total = len(items)
    failed = [e for e in items if _failed(e)]
    lines += ["## Resumo", f"- Pedidos: {total}",
              f"- Deram errado: {len(failed)}" + (f" ({len(failed) * 100 // total}%)" if total else ""),
              f"- \"Errou\" do senhor: {len(wrong_notes)}; \"boa\": {len(good_notes)}"]
    routes = Counter(e.get("rota") or "?" for e in items)
    if routes:
        lines.append("- Por onde entendeu: " + ", ".join(f"{k} {v}" for k, v in routes.most_common()))
    lines.append("")

    groups = defaultdict(list)
    for e in failed:
        groups[_norm(e.get("disse"))].append(e)
    for n in wrong_notes:
        groups[_norm(n.get("sobre"))].append({"disse": n.get("sobre"), "erro": "o senhor disse que errei: "
                                              + str(n.get("detalhe") or "")})
    lines.append("## As 10 falhas mais comuns")
    if not groups:
        lines.append("- Nenhuma falha nesta semana.")
    for i, (_, es) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1]))[:10], 1):
        e = es[-1]
        why = e.get("erro") or next((f"{a['nome']} falhou" for a in e.get("acoes", []) if not a.get("ok")), "") \
            or e.get("fala", "")
        lines.append(f"{i}. \"{e.get('disse', '')}\" ({len(es)}x): {str(why)[:160]}")
    lines.append("")

    lines.append("## O que está lento (média por parte)")
    if items:
        for p in PHASES:
            vals = [e.get("tempos", {}).get(p, 0) for e in items if e.get("tempos", {}).get(p, 0)]
            if vals:
                lines.append(f"- {p}: {sum(vals) / len(vals):.1f} s em média, pior {max(vals):.1f} s ({len(vals)} pedidos)")
        slow = sorted((e for e in items if e.get("total", 0) >= SLOW), key=lambda e: -e.get("total", 0))[:10]
        if slow:
            lines += ["", "### Os pedidos mais lentos"]
            for e in slow:
                lines.append(f"- \"{e.get('disse', '')}\": {e.get('total', 0):.1f} s {stopwatch_line(e)}")
    else:
        lines.append("- Sem pedidos nesta semana.")
    lines.append("")

    asked = Counter(_norm(e.get("disse")) for e in items if e.get("disse"))
    if asked:
        lines.append("## O que o senhor mais pediu")
        for text, n in asked.most_common(10):
            lines.append(f"- {text} ({n}x)")
        lines.append("")
    return "\n".join(lines)


def write_report(end=None):
    text = build_report(end)
    try:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(text, encoding="utf-8")
    except OSError as e:
        _say(f"Não consegui salvar o relatório: {e}.")
        return False
    _say(f"Relatório da semana salvo em {REPORT}.")
    return str(REPORT)


def report_due(now=None):
    """Domingo e o relatório ainda não foi feito hoje."""
    now = now or datetime.now()
    if now.weekday() != 6:
        return False
    try:
        return datetime.fromtimestamp(REPORT.stat().st_mtime).date() != now.date()
    except OSError:
        return True


def weekly_watcher(every=1800):
    """Thread: todo domingo gera o relatório sozinho."""
    def loop():
        while True:
            try:
                if report_due():
                    write_report()
            except Exception:
                pass
            time.sleep(every)
    threading.Thread(target=loop, daemon=True).start()


# ------------------------- relatório de erro (107) -------------------------

SECRET = re.compile(r"(sk_[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{20,}|"
                    r"(?:key|token|senha|password|secret)[\"'=: ]+[^\s\"',]{6,})", re.I)


def scrub(text):
    """Tira chaves e senhas de um texto antes de ele sair do PC."""
    text = SECRET.sub("[escondido]", str(text))
    for var in ("GEMINI_API_KEY", "GROQ_API_KEY", "ELEVENLABS_API_KEY", "WAHA_API_KEY", "INSTAGRAM_TOKEN",
                "BOLHA_SENHA", "BOLHA_NGROK", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN", "HA_TOKEN"):
        value = os.environ.get(var, "").strip()
        if len(value) >= 4:
            text = text.replace(value, "[escondido]")
    return text


def error_report(log_file=None):
    """Arquivo pronto para mandar ao Claude ou ao Codex: os erros recentes, sem chaves nem senhas."""
    since = datetime.now() - timedelta(days=3)
    wrong = [e for e in requests(since) if _failed(e)][-30:]
    lines = ["# Relatório de erro do Bolha", "",
             f"- Gerado em {datetime.now():%d/%m/%Y %H:%M}",
             f"- Windows: {platform.platform()} · Python {sys.version.split()[0]}", "",
             "## Pedidos que falharam (últimos 3 dias)"]
    if not wrong:
        lines.append("- Nenhum.")
    for e in wrong:
        lines.append(f"- {e['_quando']:%d/%m %H:%M} \"{e.get('disse', '')}\" ({e.get('rota', '')}): "
                     f"{e.get('erro') or e.get('fala', '')}")
        for a in e.get("acoes", []):
            lines.append(f"    - {a['nome']} {json.dumps(a.get('args', {}), ensure_ascii=False)} "
                         f"-> {'ok' if a.get('ok') else 'FALHOU'}")
    if log_file:
        try:
            tail = Path(log_file).read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
            lines += ["", "## Últimas ações (acoes.log)", "```", *tail, "```"]
        except OSError:
            pass
    text = scrub("\n".join(lines) + "\n")
    try:
        ERROR_REPORT.parent.mkdir(parents=True, exist_ok=True)
        ERROR_REPORT.write_text(text, encoding="utf-8")
    except OSError as e:
        _say(f"Não consegui salvar o relatório de erro: {e}.")
        return False
    _say(f"Relatório de erro pronto em {ERROR_REPORT}, sem chaves nem senhas. É só mandar para o Claude ou o Codex.")
    return str(ERROR_REPORT)


def summary_of(day="hoje"):
    """Para o "boa noite": quantos pedidos, quantos deram certo e os assuntos principais do dia."""
    _, a, b = _day_range(day)
    items = requests(a, b)
    if not items:
        return ""
    ok = sum(1 for e in items if not _failed(e))
    top = [t for t, _ in Counter(_norm(e.get("disse")) for e in items).most_common(3)]
    return f"Hoje o senhor me fez {len(items)} pedidos, {ok} deram certo. Os mais pedidos: {', '.join(top)}."
