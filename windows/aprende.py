# -*- coding: utf-8 -*-
"""O que o Bolha aprende com o senhor (sem treinar modelo nenhum: ele guarda e usa).

Tudo fica em G:\\Jarvis\\config\\aprendizado.json, visível e apagável:
- exemplos: pedidos que deram certo pela IA (vão como exemplo para a IA nos pedidos parecidos);
- correções: "errou, era o Chrome" -> da próxima vez o mesmo pedido já faz o certo, sem IA;
- apelidos: "o patrão" = Erick Cuba, "meu jogo" = Omori;
- pessoas: aniversário, quem é quem, do que cada um gosta;
- preferências: volume preferido por programa, música por hora do dia;
- aprendido: o diário do que ele aprendeu ("o que você aprendeu essa semana?").
"""

import difflib
import json
import os
import re
import shutil
import string
import threading
import time
import unicodedata
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

FILE = Path(r"G:\Jarvis\config\aprendizado.json")
CONFIG = Path(r"G:\Jarvis\config")
SKILLS_DIR = Path(r"G:\Jarvis\skills")
BACKUP_DIR = Path(r"G:\Jarvis\backups")
MAX_EXAMPLES = 300
SAME = 0.88  # tão parecido que é o mesmo pedido (correção vira atalho)
LIKE = 0.45  # parecido o bastante para servir de exemplo para a IA
# o argumento "principal" de cada ação, que a correção troca ("era o Chrome" troca o target)
MAIN_ARGS = ("target", "query", "name", "title", "city", "contact", "path", "page", "url", "text", "message")

_lock = threading.RLock()


def _say(text):
    print(f"Jarvis > {text}")


def norm(text):
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%]", " ", text)).strip()


def similarity(a, b):
    """0 a 1: quanto dois pedidos se parecem (letras e palavras)."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    wa, wb = set(a.split()), set(b.split())
    jac = len(wa & wb) / len(wa | wb) if wa | wb else 0.0
    return max(ratio, jac)


def _empty():
    return {"exemplos": [], "correcoes": [], "apelidos": {}, "pessoas": {}, "preferencias": {}, "aprendido": []}


def load():
    with _lock:
        try:
            raw = FILE.read_bytes()
        except FileNotFoundError:
            return _empty()
        try:
            data = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:  # estragado (editado à mão?): guarda uma cópia e começa outro
            FILE.replace(FILE.with_name(f"aprendizado.estragado-{datetime.now():%Y%m%d-%H%M%S}.json"))
            return _empty()
        out = _empty()
        for key, value in out.items():
            if isinstance(data.get(key), type(value)):
                out[key] = data[key]
        return out


def save(data):
    with _lock:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        for _ in range(20):
            try:
                os.replace(tmp, FILE)
                return
            except PermissionError:
                time.sleep(0.05)
        os.replace(tmp, FILE)


def _learned(data, text):
    data["aprendido"] = (data["aprendido"] + [{"quando": datetime.now().isoformat(timespec="minutes"),
                                               "texto": str(text)[:200]}])[-200:]


def _clean_actions(actions):
    out = []
    for a in actions or []:
        if isinstance(a, dict) and a.get("nome", a.get("name")):
            args = a.get("args") if isinstance(a.get("args"), dict) else {}
            out.append({"name": str(a.get("nome", a.get("name"))), "args": args})
    return out


# ------------------------- M3: acertos viram exemplos -------------------------

def learn_example(request, actions):
    """Pedido que a IA acertou: guarda como exemplo (nada de conversa, só pedidos com ação)."""
    actions = _clean_actions(actions)
    if not actions or not norm(request):
        return False
    with _lock:
        data = load()
        key = norm(request)
        for ex in data["exemplos"]:
            if norm(ex["pedido"]) == key:
                ex["acoes"], ex["usos"] = actions, int(ex.get("usos", 1)) + 1
                ex["quando"] = datetime.now().isoformat(timespec="minutes")
                break
        else:
            data["exemplos"].append({"pedido": str(request)[:200], "acoes": actions, "usos": 1, "nota": 0,
                                     "quando": datetime.now().isoformat(timespec="minutes")})
            data["exemplos"] = sorted(data["exemplos"], key=lambda e: (e.get("nota", 0), e.get("usos", 0)))[-MAX_EXAMPLES:]
        save(data)
    return True


def examples_for(request, n=3):
    """Os exemplos mais parecidos com o pedido: [(pedido, ações)] para a IA copiar o jeito certo."""
    try:
        data = load()
    except Exception:
        return []
    scored = []
    for ex in data["exemplos"] + [{**c, "nota": 2} for c in data["correcoes"]]:
        if ex.get("nota", 0) < 0:
            continue
        s = similarity(request, ex["pedido"])
        if s >= LIKE:
            scored.append((s + 0.05 * ex.get("nota", 0), ex))
    scored.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for _, ex in scored:
        if norm(ex["pedido"]) not in seen:
            seen.add(norm(ex["pedido"]))
            out.append((ex["pedido"], ex["acoes"]))
        if len(out) >= n:
            break
    return out


def examples_prompt(request):
    """Trecho que vai junto do pedido para a IA (vazio se não há exemplo parecido)."""
    found = examples_for(request)
    if not found:
        return ""
    lines = [f'Usuário: {p}\nJSON: {json.dumps({"actions": a, "reply": "Feito."}, ensure_ascii=False)}' for p, a in found]
    return ("Pedidos parecidos que deram certo antes (o senhor aprovou; faça igual se for o mesmo caso):\n"
            + "\n".join(lines))


def shortcut(request):
    """Ações já sabidas para este pedido: uma correção do senhor ou um exemplo que ele aprovou ("boa").
    None se não sabe (aí vai para o atalho ou a IA)."""
    try:
        data = load()
    except Exception:
        return None
    best, score = None, 0.0
    for c in data["correcoes"]:
        s = similarity(request, c["pedido"])
        if s >= SAME and s > score:
            best, score = c["acoes"], s
    if best is None:
        for ex in data["exemplos"]:
            if ex.get("nota", 0) >= 1 and norm(ex["pedido"]) == norm(request):
                return ex["acoes"]
    return best


# ------------------------- M2: "errou" e "boa" -------------------------

CORRECTION = re.compile(
    r"^(?:(?:nao|errou|errado|erro|ta errado|esta errado|voce errou|vc errou|nao foi isso|nao era isso|nao e isso)"
    r"[\s,.!]*)+(?:(?:era|e|eh|eu queria|queria|eu quis dizer|quis dizer|o certo e|o certo era)\s+)"
    r"(?:(?:o|a|os|as|no|na|pro|pra|para o|para a|um|uma)\s+)?(.+?)[\s.!?]*$")
WRONG = re.compile(r"^(?:errou|errado|ta errado|esta errado|voce errou|vc errou|nao era isso|nao foi isso|"
                   r"nao e isso|nao era esse|nao era essa|fez errado)(?:\s+(?:bolha|jarvis|senhor))?[\s.!?]*$")
GOOD = re.compile(r"^(?:boa|bom trabalho|muito bem|mandou bem|acertou|isso mesmo|perfeito|excelente|"
                  r"otimo|show de bola|boa bolha|boa jarvis)(?:\s+(?:bolha|jarvis|garoto|menino))?[\s.!?]*$")


def is_feedback(text):
    """'boa' / 'errou' / 'errou, era o Chrome': (True|False, correção ou "") ou None se não é nota."""
    t = norm(text)
    m = CORRECTION.match(t)
    if m:
        return False, _original_case(text, m.group(1).strip())
    if WRONG.match(t):
        return False, ""
    if GOOD.match(t):
        return True, ""
    return None


def corrected_actions(actions, right):
    """Troca o argumento principal da ação errada pelo certo: open_target(Edge) + "Chrome" -> open_target(Chrome)."""
    actions = _clean_actions(actions)
    for a in actions:
        for key in MAIN_ARGS:
            if isinstance(a["args"].get(key), str):
                a["args"] = {**a["args"], key: right}
                return actions
    return None


def correct(entry, right):
    """O senhor corrigiu o último pedido. Devolve as ações certas (para fazer agora) ou None."""
    if not entry or not entry.get("disse"):
        return None
    fixed = corrected_actions(entry.get("acoes"), right)
    if not fixed:
        return None
    with _lock:
        data = load()
        key = norm(entry["disse"])
        data["correcoes"] = [c for c in data["correcoes"] if norm(c["pedido"]) != key]
        data["correcoes"].append({"pedido": entry["disse"], "acoes": fixed,
                                  "quando": datetime.now().isoformat(timespec="minutes")})
        data["exemplos"] = [e for e in data["exemplos"] if norm(e["pedido"]) != key]
        _learned(data, f'"{entry["disse"]}" é {right}')
        save(data)
    return fixed


def rate(entry, ok):
    """ "boa": o último pedido vira exemplo aprovado. "errou": sai dos exemplos."""
    if not entry or not entry.get("disse"):
        return False
    key = norm(entry["disse"])
    with _lock:
        data = load()
        if ok:
            actions = [a for a in entry.get("acoes", []) if a.get("ok", True)]
            if actions:
                for ex in data["exemplos"]:
                    if norm(ex["pedido"]) == key:
                        ex["nota"] = int(ex.get("nota", 0)) + 1
                        break
                else:
                    data["exemplos"].append({"pedido": entry["disse"], "acoes": _clean_actions(actions), "usos": 1,
                                             "nota": 1, "quando": datetime.now().isoformat(timespec="minutes")})
                _learned(data, f'acertei "{entry["disse"]}"')
        else:
            data["exemplos"] = [e for e in data["exemplos"] if norm(e["pedido"]) != key]
            data["correcoes"] = [c for c in data["correcoes"] if norm(c["pedido"]) != key]
        save(data)
    return True


# ------------------------- apelidos -------------------------

ALIAS_PATTERNS = [
    re.compile(r"^(?:apelido|anota o apelido)\s*:?\s*(?P<a>.+?)\s+(?:e|eh|=)\s+(?:o |a )?(?P<v>.+)$"),
    re.compile(r"^(?P<a>.+?)\s+e (?:o )?apelido d[oae]s?\s+(?P<v>.+)$"),
    re.compile(r"^(?:quando eu (?:falar|disser|digo|falo)|se eu (?:falar|disser))\s+(?P<a>.+?),?\s+"
               r"(?:e|eh|quer dizer|significa|to falando d[oa]s?|estou falando d[oa]s?|e o|e a)\s+(?:o |a )?(?P<v>.+)$"),
    re.compile(r"^(?:pode chamar|vamos chamar|chama de agora em diante)\s+(?:o |a )?(?P<v>.+?)\s+de\s+(?P<a>.+)$"),
]


def parse_alias(text):
    """(apelido, valor) se a frase ensina um apelido, senão None. Usa o texto original para guardar o valor."""
    t = norm(text)
    if re.search(r"\b(?:faz|faca|abre|abra|toca|liga|coloca|manda|executa|roda)\b", t.split(",")[-1]) and \
            t.startswith(("quando eu", "se eu")):
        return None  # "quando eu disser X, abre Y" é uma habilidade, não um apelido
    for pat in ALIAS_PATTERNS:
        m = pat.match(t)
        if m:
            alias, value = m.group("a").strip(" ,.\"'"), m.group("v").strip(" ,.\"'")
            if alias and value and alias != value and len(alias) <= 40:
                return alias, _original_case(text, value)
    return None


def _original_case(text, value):
    """O valor como foi escrito ("erick cuba" -> "Erick Cuba"), se der para achar no texto original."""
    m = re.search(_accent_pattern(value), str(text), re.I)
    out = m.group(0) if m else value
    return out if any(c.isupper() for c in out) else string.capwords(out)


def set_alias(alias, value):
    alias, value = norm(alias), str(value).strip()
    if not alias or not value:
        return False
    with _lock:
        data = load()
        data["apelidos"][alias] = value
        _learned(data, f'"{alias}" = {value}')
        save(data)
    _say(f"Anotado, senhor: \"{alias}\" quer dizer {value}.")
    return True


def aliases():
    try:
        return load()["apelidos"]
    except Exception:
        return {}


_ACCENTS = {"a": "aàáâãä", "e": "eèéêë", "i": "iìíîï", "o": "oòóôõö", "u": "uùúûü", "c": "cç", "n": "nñ"}


def _accent_pattern(word):
    out = []
    for ch in norm(word):
        if ch in _ACCENTS:
            out.append(f"[{_ACCENTS[ch]}]")
        elif ch == " ":
            out.append(r"\s+")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def expand(text, table=None):
    """ "abre meu jogo" -> "abre Omori" (troca os apelidos pelo que eles querem dizer)."""
    table = aliases() if table is None else table
    for alias in sorted(table, key=len, reverse=True):
        pat = rf"(?<!\w)(?:(?:o|a|os|as)\s+)?{_accent_pattern(alias)}(?!\w)"
        text = re.sub(pat, lambda m: table[alias], text, flags=re.I)
    return text


# ------------------------- pessoas (30) -------------------------

def set_person(name, field, value):
    name, field, value = str(name).strip(), norm(field).replace(" ", "_") or "nota", str(value).strip()
    if not name or not value:
        return False
    with _lock:
        data = load()
        key = norm(name)
        person = data["pessoas"].setdefault(key, {"nome": string.capwords(name)})
        person[field] = value
        _learned(data, f"{person['nome']}: {field.replace('_', ' ')} = {value}")
        save(data)
    _say(f"Anotado sobre {string.capwords(name)}: {field.replace('_', ' ')} {value}.")
    return True


def person(name):
    data = load()
    key = norm(name)
    found = data["pessoas"].get(key) or next((p for k, p in data["pessoas"].items() if key and (key in k or k in key)), None)
    if not found:
        _say(f"Não sei nada sobre {name} ainda.")
        return False
    _say(f"O que sei sobre {found.get('nome', name)}:")
    for k, v in found.items():
        if k != "nome":
            print(f"  - {k.replace('_', ' ')}: {v}")
    return True


BIRTHDAY = re.compile(r"(\d{1,2})\s*(?:/|de)\s*(\d{1,2}|janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|"
                      r"outubro|novembro|dezembro)")
MONTHS = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro"]


def birthday_of(value):
    """ "3 de maio" / "03/05" -> (dia, mês) ou None."""
    m = BIRTHDAY.search(norm(value).replace(" / ", "/"))
    if not m:
        return None
    day, month = int(m.group(1)), m.group(2)
    month = MONTHS.index(month) + 1 if month in MONTHS else int(month)
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    return day, month


def birthdays_on(day=None):
    """Quem faz aniversário no dia (para o aviso e a skill aniversarios)."""
    day = day or date.today()
    out = []
    for p in load()["pessoas"].values():
        when = birthday_of(p.get("aniversario", ""))
        if when == (day.day, day.month):
            out.append(p.get("nome", ""))
    return out


# ------------------------- preferências (31) -------------------------

def set_pref(key, value):
    with _lock:
        data = load()
        data["preferencias"][str(key)] = value
        save(data)
    return True


def pref(key, default=None):
    try:
        return load()["preferencias"].get(str(key), default)
    except Exception:
        return default


def app_volume_pref(app, value=None):
    """Volume preferido por programa: grava (value) ou devolve o guardado."""
    app = norm(app)
    if not app:
        return None
    prefs = pref("volume_por_app", {}) or {}
    if value is None:
        return prefs.get(app)
    prefs[app] = int(value)
    set_pref("volume_por_app", prefs)
    return int(value)


# ------------------------- "o que você aprendeu essa semana?" (33) -------------------------

def learned_since(days=7):
    since = datetime.now() - timedelta(days=days)
    items = []
    for item in load()["aprendido"]:
        try:
            if datetime.fromisoformat(item["quando"]) >= since:
                items.append(item["texto"])
        except (ValueError, KeyError):
            continue
    if not items:
        _say("Nesta semana não aprendi nada novo, senhor. Diga \"errou, era...\" ou \"boa\" que eu aprendo.")
        return True
    _say(f"Nesta semana aprendi {len(items)} coisa{'s' if len(items) > 1 else ''}:")
    for t in items[-20:]:
        print(f"  - {t}")
    return True


# ------------------------- painel da memória (34) -------------------------

def panel_items(memory):
    """Tudo o que ele sabe, em itens com o texto que apaga cada um ("esquece ..."), para o painel da tela."""
    data = load()
    out = []
    for k, v in memory.get("perfil", {}).items():
        out.append({"tipo": "perfil", "texto": f"{k.replace('_', ' ')}: {v}", "apaga": f"esquece {k.replace('_', ' ')}"})
    for f in memory.get("fatos", []):
        out.append({"tipo": "lembro", "texto": f["texto"], "apaga": f"esquece {f['texto']}"})
    for r in memory.get("lembretes", []):
        if not r.get("avisado"):
            out.append({"tipo": "lembrete", "texto": f"{r['data']} {r.get('hora', '')} {r['texto']}".strip(),
                        "apaga": f"esquece {r['texto']}"})
    for a, v in data["apelidos"].items():
        out.append({"tipo": "apelido", "texto": f"{a} = {v}", "apaga": f"esquece o apelido {a}"})
    for p in data["pessoas"].values():
        extra = ", ".join(f"{k}: {v}" for k, v in p.items() if k != "nome")
        out.append({"tipo": "pessoa", "texto": f"{p.get('nome')}: {extra}", "apaga": f"esquece a pessoa {p.get('nome')}"})
    for c in data["correcoes"]:
        what = ", ".join(f"{a['name']} {' '.join(str(v) for v in a['args'].values())}" for a in c["acoes"])
        out.append({"tipo": "correção", "texto": f"\"{c['pedido']}\" -> {what}", "apaga": f"esquece a correção {c['pedido']}"})
    return out


def forget_learned(kind, what):
    """Apaga um apelido, uma pessoa ou uma correção pelo nome."""
    key = norm(what)
    with _lock:
        data = load()
        before = len(data["apelidos"]) + len(data["pessoas"]) + len(data["correcoes"])
        if kind in ("apelido", ""):
            data["apelidos"] = {a: v for a, v in data["apelidos"].items() if a != key}
        if kind in ("pessoa", ""):
            data["pessoas"] = {k: v for k, v in data["pessoas"].items() if k != key}
        if kind in ("correcao", ""):
            data["correcoes"] = [c for c in data["correcoes"] if norm(c["pedido"]) != key]
        removed = before - (len(data["apelidos"]) + len(data["pessoas"]) + len(data["correcoes"]))
        save(data)
    _say(f"Esqueci {what}." if removed else f"Não tinha {what} guardado.")
    return removed > 0


# ------------------------- backup da memória (35) -------------------------

def removable_drives():
    """Pendrives e cartões ligados ao PC (letra do disco)."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        mask = k32.GetLogicalDrives()
        return [f"{chr(65 + i)}:\\" for i in range(26)
                if mask >> i & 1 and k32.GetDriveTypeW(f"{chr(65 + i)}:\\") == 2]
    except Exception:
        return []


def backup(dest=""):
    """Copia a memória (G:\\Jarvis\\config e as skills) num .zip: no destino pedido, no pendrive ou em G:\\Jarvis\\backups."""
    dest = str(dest or "").strip()
    if norm(dest) in ("", "pendrive", "no pendrive", "pen drive", "usb"):
        drives = removable_drives()
        if norm(dest) and not drives:
            _say("Não achei pendrive ligado. Vou salvar em " + str(BACKUP_DIR) + ".")
        folder = Path(drives[0]) / "Bolha-backup" if drives and norm(dest) else BACKUP_DIR
    else:
        folder = Path(os.path.expandvars(dest)).expanduser()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"bolha-memoria-{datetime.now():%Y-%m-%d_%H-%M}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for base in (CONFIG, SKILLS_DIR):
                if base.is_dir():
                    for f in base.rglob("*"):
                        if f.is_file() and f.suffix.lower() in (".json", ".jsonl", ".md", ".txt") \
                                and not f.name.endswith(".tmp"):
                            z.write(f, Path(base.name) / f.relative_to(base))
    except OSError as e:
        _say(f"Não consegui fazer o backup: {e}.")
        return False
    _say(f"Backup da memória salvo em {target}.")
    return str(target)


def restore_hint():
    return f"Para voltar um backup, descompacte o .zip em {CONFIG.parent} (as pastas config e skills)."


def copy_tree_safe(src, dest):
    """Cópia simples de uma pasta inteira (usada no backup automático de pasta)."""
    src, dest = Path(src), Path(dest)
    if not src.is_dir():
        raise FileNotFoundError(str(src))
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for f in src.rglob("*"):
        if f.is_file():
            target = dest / f.relative_to(src)
            if target.exists() and target.stat().st_mtime >= f.stat().st_mtime and target.stat().st_size == f.stat().st_size:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            copied += 1
    return copied
