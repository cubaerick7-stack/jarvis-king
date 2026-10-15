# -*- coding: utf-8 -*-
"""Habilidades (skills): receitas prontas em texto que o Bolha segue usando as ferramentas que já existem.

Cada habilidade é uma pasta com um SKILL.md:
    windows\\skills\\<nome>\\SKILL.md     as que vêm com o Bolha
    G:\\Jarvis\\skills\\<nome>\\SKILL.md   as do senhor (criadas por voz ou importadas); valem mais que as de fábrica

Formato do SKILL.md:
    ---
    nome: modo-aula
    descricao: uma linha dizendo o que ela faz
    gatilhos: modo aula; vou ter aula        (frases que disparam direto, sem IA; opcional)
    ---
    A receita em texto, que a IA lê e segue.

    ```acoes
    [{"name": "set_volume", "args": {"percent": 30}}]
    ```
    (opcional: ações que rodam direto, sem IA)

    ```pedidos
    abre o Teams
    silencia o WhatsApp
    ```
    (opcional: pedidos falados, um por linha, feitos em ordem)

A IA vê só o nome e a linha de cada uma (as que combinam com o pedido); quando precisa, carrega a receita.
Ações perigosas continuam pedindo "sim". Habilidade importada da internet entra só com o texto: as ações
e os pedidos dela só rodam depois que o senhor aprovar ("aprova a habilidade X").
"""

import json
import re
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

BUILTIN = Path(__file__).resolve().parent / "skills"
USER = Path(r"G:\Jarvis\skills")
MAX_IMPORT = 60_000  # bytes de uma habilidade importada
SCRIPT_BLOCK = re.compile(r"```(?:python|py|powershell|ps1|bash|sh|cmd|bat|batch|js|javascript|vbs)\b.*?```", re.S | re.I)


def _say(text):
    print(f"Jarvis > {text}")


def norm(text):
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", text)).strip()


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", norm(text)).strip("-")[:50] or "habilidade"


class Skill(dict):
    @property
    def name(self):
        return self["nome"]


def parse(text, folder=None):
    """O SKILL.md em dicionário: nome, descricao, gatilhos, receita, acoes, pedidos, aprovada."""
    text = str(text or "").replace("\r\n", "\n")
    meta, body = {}, text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[norm(k).replace(" ", "_")] = v.strip()
        body = m.group(2)
    actions = []
    for block in re.findall(r"```acoes\s*\n(.*?)```", body, re.S):
        try:
            data = json.loads(block)
            actions += [a for a in data if isinstance(a, dict) and a.get("name")] if isinstance(data, list) else []
        except ValueError:
            pass
    requests = []
    for block in re.findall(r"```pedidos\s*\n(.*?)```", body, re.S):
        requests += [line.strip() for line in block.splitlines() if line.strip() and not line.strip().startswith("#")]
    recipe = re.sub(r"```(?:acoes|pedidos)\s*\n.*?```", "", body, flags=re.S).strip()
    name = meta.get("nome") or (folder.name if folder else "") or "habilidade"
    triggers = [t.strip() for t in re.split(r"[;|]", meta.get("gatilhos", "")) if t.strip()]
    # ia: a receita ainda precisa da IA depois das ações (sem ações, sempre precisa)
    needs_ai = norm(meta.get("ia", "")) == "sim" or not (actions or requests)
    return Skill(nome=slug(name), descricao=meta.get("descricao", "").strip(), gatilhos=triggers, receita=recipe,
                 acoes=actions, pedidos=requests, aprovada=norm(meta.get("aprovada", "sim")) != "nao",
                 origem=meta.get("origem", ""), pasta=str(folder or ""), ia=needs_ai and bool(recipe))


def load_all():
    """Todas as habilidades (as do senhor por cima das de fábrica com o mesmo nome)."""
    found = {}
    for base in (BUILTIN, USER):
        try:
            folders = sorted(p for p in base.iterdir() if p.is_dir())
        except OSError:
            continue
        for folder in folders:
            file = folder / "SKILL.md"
            try:
                skill = parse(file.read_text(encoding="utf-8-sig"), folder)
            except OSError:
                continue
            found[skill.name] = skill
    return found


def get(name):
    skills = load_all()
    key = slug(name)
    if key in skills:
        return skills[key]
    close = [s for k, s in skills.items() if key and (key in k or k in key)]
    return close[0] if len(close) == 1 else None


def match_trigger(text, skills=None):
    """A habilidade cujo gatilho é exatamente o pedido ("modo aula", "bolha, modo aula!"). None se nenhuma."""
    key = norm(text)
    if not key:
        return None
    for skill in (skills or load_all()).values():
        for trigger in skill["gatilhos"]:
            if norm(trigger) == key:
                return skill
    return None


def relevant(text, n=8, skills=None):
    """As habilidades que mais combinam com o pedido (pelas palavras), para a IA ver só elas."""
    words = {w for w in norm(text).split() if len(w) > 2}
    if not words:
        return []
    scored = []
    for s in (skills or load_all()).values():
        hay = set(norm(" ".join([s.name.replace("-", " "), s["descricao"], *s["gatilhos"]])).split())
        hits = len(words & hay) + sum(1 for w in words for h in hay if len(w) > 4 and h.startswith(w[:5]) and w != h) * 0.5
        if hits:
            scored.append((hits, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:n]]


def prompt_for(text):
    """Linhas para a IA: nome e descrição das habilidades que combinam com o pedido."""
    found = relevant(text)
    if not found:
        return ""
    return ("Habilidades que podem servir (use use_skill com o nome para carregar a receita):\n"
            + "\n".join(f"- {s.name}: {s['descricao']}" for s in found))


def list_skills():
    skills = load_all()
    if not skills:
        _say("Não tenho habilidades ainda.")
        return True
    _say(f"Tenho {len(skills)} habilidades (diga o nome ou peça do seu jeito):")
    for s in skills.values():
        mark = "" if s["aprovada"] else " (esperando aprovação)"
        print(f"  - {s.name}: {s['descricao']}{mark}")
    return [s.name for s in skills.values()]


# ------------------------- usar -------------------------

def use(name, run_actions, run_request):
    """Carrega a habilidade. Com ações/pedidos prontos, faz direto; a receita volta para a IA seguir.
    run_actions(lista) -> (falhas, vistos); run_request(texto) faz um pedido falado."""
    skill = get(name)
    if skill is None:
        _say(f"Não conheço a habilidade {name}.")
        return False
    if (skill["acoes"] or skill["pedidos"]) and not skill["aprovada"]:
        _say(f"A habilidade {skill.name} veio da internet e ainda não foi aprovada. "
             f"Diga \"aprova a habilidade {skill.name}\" depois de ler a receita.")
        print(skill["receita"][:1500])
        return False
    ok = True
    if skill["acoes"]:
        failed, _ = run_actions(skill["acoes"])
        ok = not failed
    for request in skill["pedidos"]:
        if run_request(request) is False:
            ok = False
    if skill["ia"]:
        _say(f"Habilidade {skill.name}, receita para seguir:")
        print(skill["receita"][:4000])  # a IA lê a receita e segue (modo ciclo)
    elif not (skill["acoes"] or skill["pedidos"]):
        _say(f"Habilidade {skill.name} feita.")
    return ok


# ------------------------- criar por voz e importar -------------------------

TEACH = re.compile(
    r"^(?:aprende|aprenda|aprender|grava|cria|crie)(?:\s+(?:uma|a|essa|nova))?(?:\s+(?:habilidade|skill|comando|atalho))?"
    r"(?:\s*[:,-])?\s*(?:quando|se)\s+eu\s+(?:disser|falar|digo|falo|pedir)\s+(.+?)"
    r"(?:\s*,\s*(?:voce |vc )?(?:(?:faz|faca|faça|fazer|entao|então)\s+)?|\s+(?:voce |vc )?(?:faz|faca|faça|fazer|entao|então)\s+"
    r"|\s*:\s*)(.+)$", re.I)


def parse_teach(text):
    """ "aprende: quando eu disser modo aula, faça abrir o Teams e silenciar o WhatsApp" -> (gatilho, o que fazer)."""
    t = str(text).strip()
    t = re.sub(r"^\s*(?:bolha|jarvis)[,\s]+", "", t, flags=re.I)
    m = TEACH.match(unicodedata.normalize("NFC", t))
    if not m:
        return None
    trigger = m.group(1).strip(" \"'“”,.")
    todo = m.group(2).strip(" \"'“”.")
    return (trigger, todo) if trigger and todo else None


VERBS = ("abre abra abrir fecha feche fechar toca toque tocar coloca coloque colocar poe põe pôr bota botar "
         "aumenta aumente aumentar abaixa abaixe abaixar baixa baixe baixar diminui diminua diminuir silencia silencie "
         "silenciar muta mute mutar desmuta liga ligue ligar desliga desligue desligar manda mande mandar envia envie "
         "enviar pesquisa pesquise pesquisar procura procure procurar busca busque buscar mostra mostre mostrar "
         "minimiza minimizar maximiza maximizar bloqueia bloquear inicia iniciar começa comeca começar comecar ativa "
         "ative ativar desativa desativar pausa pause pausar pula pule pular tira tire tirar faz faça faca fazer cria "
         "crie criar escreve escreva escrever digita digite digitar lê le leia ler resume resuma resumir deixa deixe "
         "deixar volta volte voltar muda mude mudar troca troque trocar apaga apague apagar limpa limpe limpar arruma "
         "arrume arrumar organiza organize organizar instala instale instalar atualiza atualize atualizar lembra "
         "lembre lembrar marca marque marcar me roda rode rodar executa execute executar joga jogar entra entrar "
         "vai ir salva salve salvar grava grave gravar inicie começe").split()
SPLIT = re.compile(r"\s*(?:[,;]\s*(?:e\s+)?(?:depois\s+)?|\s(?:e depois|e entao|e então|depois|e)\s+)"
                   r"(?=(?:" + "|".join(sorted(map(re.escape, set(VERBS)), key=len, reverse=True)) + r")\b)", re.I)


def split_requests(todo):
    """ "abrir o Teams e silenciar o WhatsApp" -> ["abre o Teams", "silencia o WhatsApp"].
    Só corta antes de um verbo: "toca rock e samba" continua um pedido só."""
    parts = [p.strip(" ,.") for p in SPLIT.split(str(todo)) if p and p.strip(" ,.")]
    out = []
    for p in parts:
        words = p.split()
        if words:
            words[0] = INFINITIVE.get(norm(words[0]), words[0])
        out.append(" ".join(words))
    return out or [todo]


# "abrir o Teams" vira "abre o Teams": o roteador entende o imperativo
INFINITIVE = {"abrir": "abre", "fechar": "fecha", "tocar": "toca", "colocar": "coloca", "silenciar": "silencia",
              "mutar": "muta", "baixar": "abaixa", "abaixar": "abaixa", "aumentar": "aumenta", "mandar": "manda",
              "pesquisar": "pesquisa", "procurar": "procura", "ligar": "liga", "desligar": "desliga", "deixar": "deixa",
              "por": "põe", "pôr": "põe", "ativar": "ativa", "desativar": "desativa", "mostrar": "mostra",
              "minimizar": "minimiza", "bloquear": "bloqueia", "iniciar": "inicia", "começar": "começa"}


def create(trigger, todo, description=""):
    """Cria a habilidade do senhor em G:\\Jarvis\\skills\\<nome>\\SKILL.md."""
    name = slug(trigger)
    folder = USER / name
    requests = split_requests(todo)
    text = (f"---\nnome: {name}\ndescricao: {description or 'quando o senhor disser ' + trigger + ': ' + todo}\n"
            f"gatilhos: {trigger}\ncriada: {datetime.now():%Y-%m-%d %H:%M}\n---\n"
            f"Quando o senhor disser \"{trigger}\", faça: {todo}.\n\n```pedidos\n" + "\n".join(requests) + "\n```\n")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(text, encoding="utf-8")
    except OSError as e:
        _say(f"Não consegui salvar a habilidade: {e}.")
        return False
    _say(f"Aprendi, senhor. Quando o senhor disser \"{trigger}\", eu faço: {'; '.join(requests)}.")
    return name


def import_skill(url, fetch=None):
    """Importa uma habilidade da internet (só o texto). Scripts nunca entram; ações esperam aprovação."""
    url = str(url or "").strip()
    if not re.match(r"^https://", url):
        _say("Só importo habilidade de um link https.")
        return False
    if "github.com/" in url and "/blob/" in url:  # a página do GitHub vira o arquivo cru
        url = url.replace("github.com/", "raw.githubusercontent.com/").replace("/blob/", "/")
    try:
        if fetch:
            raw = fetch(url)
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "Bolha/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read(MAX_IMPORT + 1)
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    except Exception as e:
        _say(f"Não consegui baixar a habilidade: {e}.")
        return False
    if len(text) > MAX_IMPORT:
        _say("Essa habilidade é grande demais para ser só uma receita; não importei.")
        return False
    scripts = len(SCRIPT_BLOCK.findall(text))
    text = SCRIPT_BLOCK.sub("(script removido: só entra depois do senhor aprovar e ler)", text)
    skill = parse(text)
    name = skill.name if skill.name != "habilidade" else slug(Path(url).parent.name or "importada")
    folder = USER / name
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text.replace("\r\n", "\n"), re.S)
    meta, body = (m.group(1), m.group(2)) if m else ("", text)
    meta = "\n".join(line for line in meta.splitlines() if not re.match(r"^\s*(aprovada|origem|nome)\s*:", line, re.I))
    content = (f"---\nnome: {name}\n{meta}\norigem: {url}\naprovada: nao\n---\n{body}").replace("\n\n---", "\n---")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(content, encoding="utf-8")
    except OSError as e:
        _say(f"Não consegui salvar a habilidade: {e}.")
        return False
    _say(f"Importei a habilidade {name} (só o texto)"
         + (f"; tirei {scripts} script(s)" if scripts else "")
         + f". Leia em {folder} e diga \"aprova a habilidade {name}\" para ela poder agir.")
    return name


def approve(name, confirm):
    skill = get(name)
    if skill is None or not skill["pasta"]:
        _say(f"Não achei a habilidade {name}.")
        return False
    file = Path(skill["pasta"]) / "SKILL.md"
    if skill["aprovada"]:
        _say(f"A habilidade {skill.name} já está aprovada.")
        return True
    if not confirm(f"Aprovo a habilidade {skill.name}? Ela vai poder agir sozinha."):
        _say("Ok, continua só como texto.")
        return False
    text = file.read_text(encoding="utf-8")
    file.write_text(re.sub(r"(?m)^aprovada:\s*nao\s*$", "aprovada: sim", text, count=1), encoding="utf-8")
    _say(f"Habilidade {skill.name} aprovada.")
    return True


def remove(name, confirm):
    """Apaga uma habilidade do senhor (as de fábrica não somem)."""
    skill = get(name)
    if skill is None or not str(skill["pasta"]).lower().startswith(str(USER).lower()):
        _say(f"Não achei a habilidade {name} entre as suas.")
        return False
    if not confirm(f"Apago a habilidade {skill.name}?"):
        _say("Ok, não apaguei.")
        return False
    import shutil
    shutil.rmtree(skill["pasta"], ignore_errors=True)
    _say(f"Apaguei a habilidade {skill.name}.")
    return True
