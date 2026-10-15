# -*- coding: utf-8 -*-
"""Arquivos e documentos: buscar DENTRO dos arquivos, perguntar sobre um documento, ditar, ler PDF em voz alta
em partes ("continua", "volta", "para"), planilhas (abrir, somar coluna, criar), fotos por data,
backup de pasta e o último arquivo baixado.

Sem programas extras: PDF pelo pypdf, Word e Excel lendo o .docx/.xlsx (que são .zip com XML por dentro).
"""

import json
import os
import re
import time
import unicodedata
import zipfile
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

CONFIG = Path(r"G:\Jarvis\config")
INDEX = CONFIG / "indice-textos.json"
TEXT_EXTS = {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".odt", ".rtf", ".json", ".log"}
MAX_FILE = 25 * 1024 * 1024
PART = 900  # tamanho de cada parte lida em voz alta (umas 6 frases)
MONTHS = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro"]


def _say(text):
    print(f"Jarvis > {text}")


def norm(text):
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def read_text(path, limit=300_000):
    """Texto de qualquer documento que o Bolha entende (PDF, Word, Excel, texto)."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".xlsx":
        return "\n".join("\t".join(str(c) for c in row) for row in read_sheet(path))[:limit]
    if ext == ".odt":
        with zipfile.ZipFile(path) as z:
            xml = z.read("content.xml").decode("utf-8", "ignore")
        return re.sub(r"<[^>]+>", " ", xml.replace("</text:p>", "\n"))[:limit]
    import ferramentas as F
    return F.read_text(path, limit)


# ========================= BUSCA DENTRO DOS ARQUIVOS (53) =========================

def _load_index():
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_index(index):
    try:
        INDEX.parent.mkdir(parents=True, exist_ok=True)
        tmp = INDEX.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, INDEX)
    except OSError:
        pass


def search_content(query, roots, seconds=25.0, limit=20):
    """Arquivos cujo TEXTO tem as palavras pedidas ("o contrato que fala de multa"). Guarda um índice do texto
    (G:\\Jarvis\\config\\indice-textos.json) para a próxima busca ser rápida. [(caminho, trecho)]"""
    words = [w for w in norm(query).split() if len(w) > 2]
    if not words:
        return []
    index, changed = _load_index(), False
    found, deadline = [], time.time() + seconds
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for folder, dirs, files in os.walk(root, onerror=lambda e: None):
            dirs[:] = [d for d in dirs if not d.startswith((".", "$")) and d.lower() not in ("node_modules", "appdata")]
            for name in files:
                path = Path(folder) / name
                if path.suffix.lower() not in TEXT_EXTS or path.parent == INDEX.parent:
                    continue  # a pasta de configuração do Bolha (o próprio índice) fica de fora
                try:
                    st = path.stat()
                except OSError:
                    continue
                if st.st_size > MAX_FILE:
                    continue
                key, stamp = str(path), f"{st.st_mtime:.0f}:{st.st_size}"
                item = index.get(key)
                if not item or item.get("m") != stamp:
                    if time.time() > deadline:
                        continue  # sem tempo para ler arquivo novo: usa só o que já está no índice
                    try:
                        text = norm(read_text(path, 100_000))
                    except Exception:
                        text = ""
                    item = index[key] = {"m": stamp, "t": text}
                    changed = True
                text = item["t"]
                if text and all(w in text for w in words):
                    i = text.find(words[0])
                    found.append((key, text[max(0, i - 60): i + 140].replace("\n", " ")))
    for key in [k for k in index if not Path(k).exists()][:500]:
        index.pop(key, None)
        changed = True
    if changed:
        _save_index(index)
    found.sort(key=lambda f: -Path(f[0]).stat().st_mtime if Path(f[0]).exists() else 0)
    return found[:limit]


def show_content_results(query, found):
    if not found:
        _say(f"Não achei nenhum documento falando de \"{query}\".")
        return []
    _say(f"Achei {len(found)} documento{'s' if len(found) > 1 else ''} falando de \"{query}\":")
    for i, (path, snippet) in enumerate(found, 1):
        print(f"{i}. {path}")
        print(f"     ...{snippet.strip()}...")
    return [p for p, _ in found]


# ========================= PERGUNTAS SOBRE UM DOCUMENTO (54) =========================

DOC_PROMPT = ("Você é o Bolha, mordomo do João. Responda a pergunta usando SÓ o documento abaixo, em português do "
              "Brasil, em até 4 frases curtas. Cite números, datas e prazos exatamente como estão. Se o documento não "
              "disser, responda que o documento não informa isso.")


def ask_document(path, question, think):
    path = Path(path)
    if not path.is_file():
        _say(f"Não achei o documento {path}.")
        return False
    try:
        text = read_text(path, 60_000)
    except Exception as e:
        _say(f"Não consegui ler {path.name}: {e}.")
        return False
    if not text.strip():
        _say(f"{path.name} não tem texto que eu consiga ler (pode ser imagem escaneada).")
        return False
    try:
        answer = think(DOC_PROMPT, f"Documento ({path.name}):\n{text}\n\nPergunta: {question}", json_mode=False,
                       temperature=0.1)
    except Exception as e:
        _say(f"Não consegui perguntar à IA: {e}.")
        return False
    _say(re.sub(r"[*_#`]", "", str(answer)).strip())
    return True


# ========================= LER EM VOZ ALTA EM PARTES (10, 56) =========================

reader = {"arquivo": "", "partes": [], "i": 0}


def split_parts(text, size=PART):
    """Partes de ~size letras terminando em fim de frase."""
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", str(text))).strip()
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = max(text.rfind(". ", start, end), text.rfind("\n", start, end), text.rfind("? ", start, end),
                      text.rfind("! ", start, end))
            if cut > start + size // 3:
                end = cut + 1
        parts.append(text[start:end].strip())
        start = end
    return [p for p in parts if p]


def read_aloud(path):
    """Começa a ler um PDF/Word/texto em voz alta, uma parte por vez."""
    path = Path(path)
    if not path.is_file():
        _say(f"Não achei o arquivo {path}.")
        return False
    try:
        text = read_text(path)
    except Exception as e:
        _say(f"Não consegui ler {path.name}: {e}.")
        return False
    parts = split_parts(text)
    if not parts:
        _say(f"{path.name} não tem texto que eu consiga ler.")
        return False
    reader.update(arquivo=str(path), partes=parts, i=0)
    return _read_part(intro=f"Lendo {path.stem}, parte 1 de {len(parts)}. ")


def _read_part(intro=""):
    i, parts = reader["i"], reader["partes"]
    more = " Diga continua para seguir." if i + 1 < len(parts) else " Fim do documento."
    print(f"Jarvis > {intro}{parts[i]}{more}")
    return True


def reading_control(action):
    """ "continua", "volta", "repete", "parte 5", "para"."""
    if not reader["partes"]:
        _say("Não estou lendo nada agora. Diga \"lê em voz alta\" e o arquivo.")
        return False
    a = norm(action)
    if a in ("para", "parar", "pare", "chega"):
        n = reader["i"] + 1
        _say(f"Parei na parte {n} de {len(reader['partes'])}. Diga continua quando quiser.")
        return True
    m = re.search(r"\d+", a)
    if m:
        reader["i"] = max(0, min(len(reader["partes"]) - 1, int(m.group(0)) - 1))
    elif a.startswith("volta"):
        reader["i"] = max(0, reader["i"] - 1)
    elif a.startswith("repet"):
        pass
    else:
        if reader["i"] + 1 >= len(reader["partes"]):
            _say("Já terminei de ler esse documento, senhor.")
            return True
        reader["i"] += 1
    return _read_part(intro=f"Parte {reader['i'] + 1} de {len(reader['partes'])}. ")


# ========================= DITADO (55) =========================

dictation = {"ativo": False, "arquivo": "", "frases": []}


def start_dictation(name, folder):
    name = re.sub(r'[<>:"/\\|?*]', "", str(name or "").strip()) or f"Ditado {datetime.now():%d-%m-%Y %H-%M}"
    kind = ".txt" if name.lower().endswith(".txt") else ".docx"
    path = Path(folder) / (re.sub(r"\.(txt|docx)$", "", name, flags=re.I) + kind)
    dictation.update(ativo=True, arquivo=str(path), frases=[])
    _say(f"Pode ditar, senhor. Vou escrevendo em {path.name}. Diga \"apaga a última frase\" para corrigir e "
         f"\"fim do ditado\" para salvar.")
    return True


def dictate(text):
    """Cada fala vira um parágrafo. "ponto final", "vírgula", "nova linha" viram pontuação."""
    t = str(text).strip()
    low = norm(t)
    if low in ("fim do ditado", "termina o ditado", "para de ditar", "salva o ditado", "acabou o ditado"):
        return stop_dictation()
    if low in ("apaga a ultima frase", "apaga a ultima", "desfaz a ultima frase"):
        if dictation["frases"]:
            dictation["frases"].pop()
            _say("Apaguei a última frase.")
        return True
    for word, sym in ((r"\s*\bponto de interroga[cç][aã]o\b", "?"), (r"\s*\bponto de exclama[cç][aã]o\b", "!"),
                      (r"\s*\bponto final\b", "."), (r"\s*\bv[ií]rgula\b", ","), (r"\s*\bdois pontos\b", ":"),
                      (r"\s*\bnova linha\b|\s*\bpar[aá]grafo\b", "\n")):
        t = re.sub(word, sym, t, flags=re.I)
    t = t.strip()
    if t:
        t = t[0].upper() + t[1:]
        dictation["frases"].append(t)
        _save_dictation()
    _say("Anotado.")
    return True


def _save_dictation():
    path = Path(dictation["arquivo"])
    path.parent.mkdir(parents=True, exist_ok=True)
    paragraphs = [p for p in "\n".join(dictation["frases"]).split("\n")]
    if path.suffix.lower() == ".txt":
        path.write_text("\n".join(paragraphs) + "\n", encoding="utf-8")
    else:
        write_docx(path, paragraphs)


def stop_dictation():
    if not dictation["ativo"]:
        _say("Não estava ditando.")
        return False
    dictation["ativo"] = False
    if not dictation["frases"]:
        _say("Ditado cancelado: não tinha nada escrito.")
        return True
    _save_dictation()
    _say(f"Ditado salvo em {dictation['arquivo']} ({len(dictation['frases'])} frases).")
    return dictation["arquivo"]


def write_docx(path, paragraphs):
    """Um .docx simples (abre no Word e no LibreOffice) sem precisar de biblioteca."""
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{escape(p)}</w:t></w:r></w:p>' for p in paragraphs)
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.'
        'openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxml'
        'formats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override Part'
        'Name="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.'
        'main+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.'
        'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.'
        'org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://'
        f'schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>',
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return str(path)


# ========================= PLANILHAS (57) =========================

def _col_index(ref):
    """ "C" -> 2, "AA" -> 26."""
    n = 0
    for ch in ref.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_sheet(path, sheet=1):
    """Linhas da planilha (.xlsx ou .csv) como listas de valores (números viram float)."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        import csv
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(raw[:2000], delimiters=",;\t") if raw.strip() else csv.excel
        return [[_number(c) for c in row] for row in csv.reader(raw.splitlines(), dialect)]
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        name = f"xl/worksheets/sheet{sheet}.xml"
        if name not in z.namelist():
            name = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet"))[0]
        root = ET.fromstring(z.read(name))
    rows = []
    for row in root.iter(f"{{{ns['m']}}}row"):
        values = {}
        for c in row.findall("m:c", ns):
            ref = re.match(r"([A-Z]+)", c.get("r", "A"))
            col = _col_index(ref.group(1)) if ref else len(values)
            v = c.find("m:v", ns)
            t = c.get("t")
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{ns['m']}}}t"))
            else:
                val = _number(v.text) if v is not None else ""
            values[col] = val
        if values:
            rows.append([values.get(i, "") for i in range(max(values) + 1)])
    return rows


def _number(text):
    s = str(text or "").strip()
    t = s.replace("R$", "").replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|-?\d+,\d+", t):
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t) if t else ""
    except ValueError:
        return s


def sum_column(path, column):
    """Soma uma coluna pela letra ("C") ou pelo nome no cabeçalho ("valor")."""
    path = Path(path)
    if not path.is_file():
        _say(f"Não achei a planilha {path}.")
        return False
    try:
        rows = read_sheet(path)
    except Exception as e:
        _say(f"Não consegui ler a planilha: {e}.")
        return False
    if not rows:
        _say("A planilha está vazia.")
        return False
    col, header = None, [norm(c) for c in rows[0]]
    want = norm(column)
    if want in header:
        col = header.index(want)
    elif any(want and want in h for h in header):
        col = next(i for i, h in enumerate(header) if want in h)
    elif re.fullmatch(r"[a-z]{1,2}", want):
        col = _col_index(want)
    if col is None:
        _say(f"Não achei a coluna {column}. Colunas: {', '.join(str(c) for c in rows[0])}.")
        return False
    nums = [r[col] for r in rows if col < len(r) and isinstance(r[col], float)]
    total = sum(nums)
    shown = f"{total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    _say(f"A soma da coluna {rows[0][col] if col < len(rows[0]) and rows[0][col] else column} é {shown} "
         f"({len(nums)} valores).")
    return total


def create_sheet(path, headers, rows=()):
    """Cria uma planilha .xlsx simples."""
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    all_rows = [list(headers)] + [list(r) for r in rows]

    def cell(ref, v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return f'<c r="{ref}"><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'

    def letter(i):
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s

    data = "".join(f'<row r="{n}">' + "".join(cell(f"{letter(i)}{n}", v) for i, v in enumerate(r)) + "</row>"
                   for n, r in enumerate(all_rows, 1))
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.'
        'openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.'
        'openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override '
        'PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main'
        '+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.'
        f'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{main}" '
        f'xmlns:r="{rel}"><sheets><sheet name="Planilha1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="'
        f'http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{main}">'
        f"<sheetData>{data}</sheetData></worksheet>",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    _say(f"Planilha criada: {path.name} ({len(all_rows) - 1} linhas).")
    return str(path)


def show_sheet(path, limit=12):
    path = Path(path)
    try:
        rows = read_sheet(path)
    except Exception as e:
        _say(f"Não consegui ler a planilha: {e}.")
        return False
    _say(f"{path.name}: {len(rows)} linhas.")
    for r in rows[:limit]:
        print("  " + " | ".join(str(int(c) if isinstance(c, float) and c.is_integer() else c) for c in r))
    return True


# ========================= FOTOS POR DATA (58) =========================

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}


def photo_date(path):
    """A data da foto: a do EXIF (quando a câmera tirou), senão a do arquivo."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            exif = img.getexif()
            raw = exif.get(36867) or exif.get(306)  # DateTimeOriginal, DateTime
            if not raw:
                raw = exif.get_ifd(0x8769).get(36867)
            if raw:
                return datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S").date()
    except Exception:
        pass
    try:
        return date.fromtimestamp(Path(path).stat().st_mtime)
    except OSError:
        return None


def parse_month(text, today=None):
    """ "julho" -> (ano, 7); "julho de 2024" -> (2024, 7); "mês passado" -> o anterior."""
    today = today or date.today()
    t = norm(text)
    if "mes passado" in t:
        return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    if "este mes" in t or "esse mes" in t or "deste mes" in t:
        return today.year, today.month
    year = re.search(r"\b(20\d\d|19\d\d)\b", t)
    for i, m in enumerate(MONTHS, 1):
        if re.search(rf"\b{m}\b", t):
            y = int(year.group(1)) if year else (today.year if i <= today.month else today.year - 1)
            return y, i
    if year:
        return int(year.group(1)), None
    return None


def photos_from(when, roots):
    """Fotos de um mês ("fotos de julho") ou ano, das pastas de imagens."""
    period = parse_month(when)
    if not period:
        _say(f"Não entendi o mês \"{when}\".")
        return []
    year, month = period
    found = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.suffix.lower() in PHOTO_EXTS:
                d = photo_date(p)
                if d and d.year == year and (month is None or d.month == month):
                    found.append(p)
    found.sort(key=lambda p: photo_date(p) or date.min)
    label = f"{MONTHS[month - 1]} de {year}" if month else str(year)
    if not found:
        _say(f"Não achei fotos de {label}.")
        return []
    _say(f"Achei {len(found)} foto{'s' if len(found) > 1 else ''} de {label}:")
    for i, p in enumerate(found[:20], 1):
        print(f"{i}. {p}")
    return [str(p) for p in found]


# ========================= ÚLTIMO BAIXADO (66) E BACKUP (59) =========================

def last_download(folder):
    folder = Path(folder)
    try:
        files = [p for p in folder.iterdir() if p.is_file()
                 and p.suffix.lower() not in (".crdownload", ".part", ".tmp", ".ini") and not p.name.startswith("~")]
    except OSError:
        return None
    return max(files, key=lambda p: p.stat().st_mtime, default=None)


def backup_folder(src, dest):
    """Copia o que mudou de uma pasta para outra (backup)."""
    import aprende
    src, dest = Path(os.path.expandvars(str(src))).expanduser(), Path(os.path.expandvars(str(dest))).expanduser()
    if not src.is_dir():
        _say(f"Não achei a pasta {src}.")
        return False
    target = dest / src.name if dest.name.lower() != src.name.lower() else dest
    try:
        n = aprende.copy_tree_safe(src, target)
    except OSError as e:
        _say(f"O backup falhou: {e}.")
        return False
    _say(f"Backup de {src.name} feito em {target}: {n} arquivo{'s' if n != 1 else ''} novo{'s' if n != 1 else ''} ou mudado{'s' if n != 1 else ''}.")
    return True
