#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import contextlib
import ctypes
import difflib
import io
import json
import ntpath
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ferramentas as F  # noqa: E402
import memoria as M  # noqa: E402
import navegador as B  # noqa: E402
import ui as U  # noqa: E402
import voz as V  # noqa: E402
import nuvem as N  # noqa: E402
import instagram as IG  # noqa: E402
import waha as W  # noqa: E402
import celular as C  # noqa: E402
import diario as D  # noqa: E402
import aprende as A  # noqa: E402
import habilidades as H  # noqa: E402
import maos as MA  # noqa: E402
import documentos as DOC  # noqa: E402
import rotina as R  # noqa: E402
import integracoes as I  # noqa: E402
import autoteste as AT  # noqa: E402
import slides as SL  # noqa: E402

try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    from ollama import chat
except ImportError:
    chat = None

MODEL = "qwen3:1.7b"
# Mesmas opções em todas as chamadas: mudar num_ctx faz o Ollama recarregar o modelo.
AI_OPTIONS = {"temperature": 0, "num_ctx": 4096, "num_predict": 400}
KEEP_ALIVE = "30m"  # mantém o modelo na RAM entre pedidos
MAX_RESULTS = 20
MAX_SCAN = 400  # quantos achados juntar antes de ordenar
SCREENSHOT_DIR = Path(r"G:\Jarvis\screenshots")
ACTION_LOG = Path(os.environ.get("JARVIS_LOG", r"G:\Jarvis\logs\acoes.log"))


def _shell_folder(name, fallback):
    """Pasta de verdade do Windows (com o OneDrive ligado, a Área de Trabalho fica dentro dele)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            return Path(os.path.expandvars(winreg.QueryValueEx(k, name)[0]))
    except (ImportError, OSError):
        return Path.home() / fallback


DESKTOP = _shell_folder("Desktop", "Desktop")
DOCUMENTS = _shell_folder("Personal", "Documents")
DOWNLOADS = _shell_folder("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads")
PICTURES = _shell_folder("My Pictures", "Pictures")
MUSIC = _shell_folder("My Music", "Music")
VIDEOS = _shell_folder("My Video", "Videos")
GAMES_DRIVE = Path("G:\\")
SEARCH_ROOTS = [DESKTOP, DOWNLOADS, DOCUMENTS, GAMES_DRIVE]
PROGRAM_ROOTS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    DESKTOP,
    Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",  # atalhos de jogos "para todos os usuários"
]
EXTRA_PROGRAM_ROOTS = [GAMES_DRIVE]  # jogos soltos no G: (varrido raso, só se o Menu Iniciar não tiver)
SKIP_NAMES = {"$recycle.bin", "system volume information", ".git", "node_modules", "__pycache__", "appdata"}
SKIP_PATHS = {r"g:\jarvis\navegador", r"g:\jarvis\modelos", r"g:\jarvis\tools"}  # milhares de arquivos do Jarvis
PROGRAM_EXTS = (".lnk", ".exe", ".url")
last_results = []
last_kind = None  # "arquivos" ou "web": a que "abre o segundo" se refere


def normalize(text):
    text = str(text).strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text)


# Nome do assistente (voz.py lê o JARVIS_NOME; o padrão é "Bolha"). "jarvis" continua valendo no texto.
NAME = V.NAME
_CALL_NAMES = sorted({"jarvis", NAME.lower(), normalize(NAME)}, key=len, reverse=True)
CALL = "(?:" + "|".join(re.escape(n) for n in _CALL_NAMES) + ")"


def clean_prefix(text):
    """Tira o "Bolha," (ou "Jarvis,", "mn") do começo, mantendo o resto do jeito que veio."""
    return re.sub(rf"^\s*(?:{CALL}|mn|mano)(?!\w)[\s,:-]*", "", text, flags=re.I).strip()


def log_action(name, detail=""):
    """Registra cada ação executada (horário, ação, detalhe). Nunca interrompe o Jarvis."""
    try:
        ACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ACTION_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}\t{name}\t{detail}\n")
    except Exception:
        pass


def need_pyautogui():
    if pyautogui is None:
        raise RuntimeError("Instale pyautogui: python -m pip install pyautogui")


def ordinal_to_number(text):
    clean = normalize(text)
    words = {
        "primeiro": 1, "primeira": 1,
        "segundo": 2, "segunda": 2,
        "terceiro": 3, "terceira": 3,
        "quarto": 4, "quarta": 4,
        "quinto": 5, "quinta": 5,
        "sexto": 6, "sexta": 6,
        "setimo": 7, "setima": 7,
        "oitavo": 8, "oitava": 8,
        "nono": 9, "nona": 9,
        "decimo": 10, "decima": 10,
    }
    m = re.search(r"\b(\d+)\b", clean)
    if m:
        return int(m.group(1))
    for word, number in words.items():
        if re.search(rf"\b{word}\b", clean):
            return number
    if len(last_results) == 1:
        return 1
    return None


# ========================= VOLUME =========================

def _device():
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetSpeakers()


def set_volume(percent):
    percent = max(0, min(100, int(percent)))
    try:
        device = _device()
        try:
            device.volume_percent = percent
        except Exception:
            device.EndpointVolume.SetMasterVolumeLevelScalar(percent / 100.0, None)
        print(f"Jarvis > Volume em {percent}%.")
        return True
    except Exception as e:
        print(f"Jarvis > Erro no volume: {e}")
        return False


def get_volume():
    try:
        device = _device()
        try:
            value = int(round(float(device.volume_percent)))
        except Exception:
            value = int(round(device.EndpointVolume.GetMasterVolumeLevelScalar() * 100))
        print(f"Jarvis > O volume está em {value}%.")
        return value
    except Exception as e:
        print(f"Jarvis > Erro ao ler volume: {e}")
        return None


def mute_audio(mute=True):
    try:
        device = _device()
        device.EndpointVolume.SetMute(1 if mute else 0, None)
        print("Jarvis > Som mutado." if mute else "Jarvis > Som ativado.")
        return True
    except Exception as e:
        print(f"Jarvis > Erro no mudo: {e}")
        return False


def change_volume(delta):
    value = get_volume()
    if value is not None:
        set_volume(value + delta)


# ========================= APPS/SITES =========================

SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "drive": "https://drive.google.com",
    "whatsapp": "https://web.whatsapp.com",
    "zap": "https://web.whatsapp.com",
    "whatsapp web": "https://web.whatsapp.com",
    "instagram": "https://www.instagram.com",
    "insta": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "tiktok": "https://www.tiktok.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "netflix": "https://www.netflix.com",
    "chatgpt": "https://chatgpt.com",
    "outlook": "https://outlook.live.com",
    "github": "https://github.com",
    "twitch": "https://www.twitch.tv",
    "mercado livre": "https://www.mercadolivre.com.br",
    "shopee": "https://shopee.com.br",
}


# Esses sites desconfiam de navegador controlado por programa (a verificação do login não carrega):
# abrem no navegador normal do senhor, onde ele já está logado.
OWN_BROWSER_SITES = ("instagram.com", "facebook.com", "tiktok.com", "x.com", "netflix.com")


def open_target(target):
    original = str(target).strip()
    low = normalize(original)

    aliases = {
        "google chrome": "chrome",
        "explorador de arquivos": "explorer",
        "explorador": "explorer",
        "gerenciador de tarefas": "taskmgr",
        "configuracoes": "settings",
        "bloco de notas": "notepad",
        "bloco de nota": "notepad",
        "notas": "notepad",
        "notepad": "notepad",
        "calculadora": "calc",
    }
    low = aliases.get(low, low)

    if low in FOLDERS:
        return open_folder(low)

    site = re.sub(r"^(?:o|a)\s+|\s+(?:web|site)$", "", low).strip()
    if low in SITES or site in SITES:
        url = SITES.get(low) or SITES[site]
        if any(d in url for d in OWN_BROWSER_SITES):  # login com verificação: no navegador do senhor
            webbrowser.open(url)
            print(f"Jarvis > Abrindo {site or low} no seu navegador.")
            return True
        return open_url(url)  # o resto abre no navegador do Jarvis

    if low == "chrome":
        p = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if os.path.exists(p):
            subprocess.Popen([p])
            print("Jarvis > Abrindo Chrome.")
            return True

    if low == "explorer":
        subprocess.Popen(["explorer.exe"])
        print("Jarvis > Explorador aberto.")
        return True

    if low == "taskmgr":
        os.startfile("taskmgr.exe")  # pede elevação: o Popen dá WinError 740
        print("Jarvis > Gerenciador de Tarefas aberto.")
        return True

    if low == "settings":
        os.startfile("ms-settings:")
        print("Jarvis > Configurações abertas.")
        return True

    if low == "notepad":
        subprocess.Popen(["notepad.exe"])
        print("Jarvis > Bloco de Notas aberto.")
        return True

    if low == "calc":
        subprocess.Popen(["calc.exe"])
        print("Jarvis > Calculadora aberta.")
        return True

    for program in find_programs(original):
        if launch(program):
            return True

    app = F.store_app(original)  # apps da Microsoft Store (Câmera, Calendário...) não têm atalho comum
    if app:
        try:
            os.startfile("shell:AppsFolder\\" + app[1])
            print(f"Jarvis > Abrindo {app[0]}.")
            return True
        except OSError:
            pass

    try:  # jogo da Steam/Epic sem atalho na área de trabalho
        if MA.open_game(original, quiet=True):
            return True
    except Exception:
        pass

    if len(low.split()) > 4:
        print(f"Jarvis > Não achei um programa chamado \"{original}\".")
        return False

    need_pyautogui()
    pyautogui.press("win")
    time.sleep(0.6)
    try:  # colar mantém os acentos ("câmera"); o pyautogui.write pula letras acentuadas
        import pyperclip
        pyperclip.copy(original)
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        pyautogui.write(low, interval=0.025)  # sem acento a busca do Windows acha igual
    time.sleep(0.8)
    pyautogui.press("enter")
    print(f"Jarvis > Tentei abrir {original} pela busca do Windows.")
    return True


def launch(path):
    """Abre arquivo/programa a partir da pasta dele (jogos costumam precisar disso).
    Atalho quebrado ou janela cancelada devolve False em vez de travar."""
    path = Path(path)
    try:
        os.startfile(str(path), cwd=str(path.parent))
    except TypeError:
        os.startfile(str(path))
    except OSError as e:
        print(f"Jarvis > Não consegui abrir {path.name} ({e.strerror or e}). Tentando outro...")
        return False
    print(f"Jarvis > Abrindo: {path}")
    return True


def find_program(name):
    found = find_programs(name)
    return found[0] if found else None


def walk(root, max_depth=None):
    """Arquivos de uma pasta e subpastas, pulando lixeira, .git e as pastas pesadas do próprio Jarvis."""
    root = Path(root)
    base = len(root.parts)
    for folder, dirs, files in os.walk(root, onerror=lambda e: None):
        here = Path(folder)
        if max_depth is not None and len(here.parts) - base >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_NAMES and str(here / d).lower() not in SKIP_PATHS]
        for name in dirs:
            yield here / name
        for name in files:
            yield here / name


def _program_matches(paths, wanted):
    matches = []
    for path in paths:
        path = Path(path)
        if path.suffix.lower() not in PROGRAM_EXTS:
            continue
        stem = normalize(path.stem)
        if stem == wanted:
            closeness = 0
        elif difflib.SequenceMatcher(None, stem, wanted).ratio() >= 0.8:
            closeness = 1
        else:
            continue
        matches.append(((closeness, PROGRAM_EXTS.index(path.suffix.lower()), len(str(path))), path))
    return matches


def find_programs(name):
    """Atalhos (.lnk/.url) e .exe com nome igual ou bem parecido com o pedido, do melhor pro pior:
    nome exato antes de parecido, atalho antes de .exe, caminho curto antes de longo.
    Olha o Menu Iniciar e a Área de Trabalho; o G: só se lá não tiver o nome exato."""
    wanted = normalize(re.sub(r"\.(exe|lnk|url)$", "", str(name).strip(), flags=re.I))
    if not wanted:
        return []
    matches = []
    for root in PROGRAM_ROOTS:
        if str(root) and root.exists():
            matches += _program_matches(walk(root), wanted)
    if not any(key[0] == 0 for key, _ in matches):
        indexed = F.everything_search(f"{wanted} ext:exe;lnk;url", 50)
        if indexed:
            matches += _program_matches(indexed, wanted)
        for root in EXTRA_PROGRAM_ROOTS:  # sem Everything, ou disco que ele não indexa (pendrive, exFAT)
            if (indexed is None or not F.indexes_drive(root)) and root.exists():
                matches += _program_matches(walk(root, max_depth=4), wanted)
    seen, out = set(), []
    for _, path in sorted(matches, key=lambda m: m[0]):
        if str(path).lower() not in seen:
            seen.add(str(path).lower())
            out.append(path)
    return out[:5]


def _browser_failed(e):
    first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    print(f"Jarvis > (navegador do Jarvis falhou: {first[:160]}; usando o navegador padrão)")


def search_web(query, site="google"):
    global last_kind
    youtube = normalize(site) == "youtube"
    if youtube:
        url = "https://www.youtube.com/results?search_query=" + quote_plus(str(query))
    else:
        url = "https://www.google.com/search?q=" + quote_plus(str(query))
        last_kind = "web"
    if B.available():  # na aba do Jarvis, e a IA consegue ler os resultados
        try:
            return B.open_url(url) if youtube else B.search(query)
        except Exception as e:
            _browser_failed(e)
    webbrowser.open(url)
    print(f"Jarvis > Pesquisa aberta: {query}")
    return True


def web_search(query):
    """Pesquisa para a IA ler os resultados (modo ciclo)."""
    global last_kind
    last_kind = "web"
    return B.search(query)


# ========================= ARQUIVOS =========================

def search_files(query):
    global last_results, last_kind
    query_original = str(query).strip()
    query_low = normalize(query_original)
    extension = None
    if query_low in {"pdf", "docx", "txt", "jpg", "jpeg", "png", "mp3", "mp4"}:
        extension = "." + query_low

    found, seen, close = [], set(), []
    print(f"Jarvis > Procurando: {query_original}")

    indexed = F.everything_search(query_original, MAX_SCAN, extension)
    if indexed:  # Everything: o PC inteiro em milissegundos
        found = indexed
    # Sem Everything, varre as pastas de sempre. Se ele respondeu "nada", só procura nomes parecidos
    # nas pastas do usuário (o G: inteiro é lento demais para isso).
    if indexed is None:
        roots = SEARCH_ROOTS
    else:  # o G: só se o Everything não o indexa (pendrive, exFAT): aí o "nada" dele não vale para o G:
        roots = ([] if indexed else [DESKTOP, DOWNLOADS, DOCUMENTS])
        roots += [GAMES_DRIVE] if not F.indexes_drive(GAMES_DRIVE) else []

    for root in roots:
        if not root.exists():
            continue
        try:
            for path in walk(root):
                try:
                    if extension:
                        matched = path.suffix.lower() == extension and path.is_file()
                    else:
                        name = normalize(path.name)
                        matched = query_low in name
                        if not matched and len(close) < 50 and is_close(query_low, normalize(path.stem)):
                            close.append(str(path))
                    if matched:
                        p = str(path)
                        if p not in seen:
                            seen.add(p)
                            found.append(p)
                        if len(found) >= MAX_SCAN:
                            break
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            pass
        if len(found) >= MAX_SCAN:
            break

    if not found and close:
        print("Jarvis > Não achei esse nome exato; mostrando os parecidos.")
        found = close
    found = rank_results(found, query_low)[:MAX_RESULTS]
    last_results = found
    last_kind = "arquivos"

    if not found:
        print("Jarvis > Não encontrei nenhum arquivo.")
        return []

    print(f"Jarvis > Encontrei {len(found)} resultado{'s' if len(found) > 1 else ''}:")
    for i, p in enumerate(found, 1):
        print(f"  {i}. {p}")
    return found


def is_close(query, stem):
    """'omorie' ~ 'omori', 'omories' ~ 'omori'."""
    if len(query) < 4 or not stem:
        return False
    m = difflib.SequenceMatcher(None, query, stem)
    return m.real_quick_ratio() >= 0.8 and m.ratio() >= 0.8


def rank_results(paths, query):
    """Nome igual ao pedido primeiro, depois atalhos/programas, depois documentos, depois o resto;
    dentro de cada grupo, os mais perto da raiz."""
    kinds = {".lnk": 0, ".exe": 0, ".url": 0, ".pdf": 1, ".docx": 1, ".doc": 1, ".txt": 1, ".xlsx": 1}

    def key(p):
        path = Path(p)
        return (
            0 if normalize(path.stem) == query else 1,
            1 if path.is_dir() else kinds.get(path.suffix.lower(), 2),
            len(path.parts),
            p.lower(),
        )

    return sorted(paths, key=key)


def open_search_result(index):
    index = int(index)
    if not (1 <= index <= len(last_results)):
        print("Jarvis > Esse resultado não existe.")
        return False
    path = Path(last_results[index - 1])
    if not path.exists():
        print("Jarvis > O arquivo não existe mais.")
        return False
    return launch(path)


def show_search_result(index):
    index = int(index)
    if not (1 <= index <= len(last_results)):
        print("Jarvis > Esse resultado não existe.")
        return False
    path = Path(last_results[index - 1])
    subprocess.Popen(["explorer.exe", "/select,", str(path)])
    print(f"Jarvis > Mostrando no Explorer: {path}")
    return True


def list_folder(path):
    folder = Path(os.path.expandvars(str(path))).expanduser()
    if not folder.exists() or not folder.is_dir():
        print(f"Jarvis > Pasta não encontrada: {folder}")
        return []
    try:
        items = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        print("Jarvis > Sem permissão para essa pasta.")
        return []
    print(f"Jarvis > Conteúdo de {folder}:")
    for item in items[:100]:
        kind = "PASTA" if item.is_dir() else "ARQUIVO"
        print(f"  [{kind}] {item.name}")
    return [str(x) for x in items[:100]]


# ========================= PESQUISA NA INTERNET =========================

RESEARCH_PROMPT = (
    "Você é o Bolha, o Jarvis do João, um mordomo educado que chama o usuário de senhor. Pesquise na internet e responda "
    "a pergunta com informação ATUAL e verificada, em português do Brasil. Responda SOMENTE com um objeto JSON, sem "
    "texto fora dele, neste formato (omita o que não se aplicar):\n"
    '{"tema":"uma palavra (ex.: eleição, futebol, economia)","titulo":"manchete curta com a resposta",'
    '"contexto":"rótulo curto em maiúsculas do que o placar mostra (ex.: SEGUNDO TURNO · BRASIL)",'
    '"progresso":{"rotulo":"99,8% apurado","valor":99.8},'
    '"ranking":[{"nome":"...","sigla":"...","pct":47,"detalhe":"...","selo":"..."}],'
    '"nota":"uma linha de contexto","resumo":"2 a 3 frases com a resposta e a data dos dados",'
    '"pontos":["fato curto","fato curto"],'
    '"fala":"a resposta falada em 2 ou 3 frases curtas, números por extenso, sem símbolos nem markdown, '
    'começando com algo como Verifiquei, senhor."}\n'
    "Use ranking só quando houver placar, votos, classificação, cotações ou comparação numérica (pct de 0 a 100). "
    "Nos campos da janela (titulo, nota, resumo, pontos, detalhe) escreva números e datas com algarismos "
    "(47%, 13/10/2026, 56 milhões); SÓ a fala usa números por extenso. "
    "Não invente nada: se não achou, diga no resumo e na fala que não encontrou."
)


def _clean_research(raw):
    """O JSON da pesquisa (a IA às vezes põe texto ou ``` em volta). None se não der para entender."""
    try:
        data = parse_json(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) and (data.get("resumo") or data.get("titulo") or data.get("fala")) else None


_pedido = ""  # o pedido atual, como chegou (a pesquisa usa se a IA esquecer de mandar a pergunta)


def _research_query(args):
    """A pergunta da pesquisa: "query" ou qualquer texto que a IA mandou com outro nome; senão, o próprio pedido."""
    query = str(args.get("query") or "").strip()
    if not query:
        query = next((str(v).strip() for v in args.values() if isinstance(v, str) and v.strip()), "")
    return query or _pedido


# Palavras que só atrapalham a busca de notícias ("opa, tudo bem, e as eleições estão como agora?")
_FILLER = set("""opa oi ola ola bom dia boa tarde noite tudo bem beleza e ai bolha jarvis senhor por favor me diz diga fala conta
sabe voce vc qual quais quanto quanta como esta estao ta tao vai vao ser sera foi agora agr hoje ai la entao o a os as um uma de do da
dos das no na nos nas em pra para sobre que isso esse essa me mim eu""".split())


def _news_query(query):
    """Só as palavras que importam para a busca: "OPA TUDO BEM E AS ELEIÇÕES ESTAO COMO" -> "eleições 2026"."""
    words = [w for w in re.findall(r"[\wÀ-ÿ$%]+", str(query).lower()) if normalize(w) not in _FILLER]
    text = " ".join(words) or str(query)
    if re.search(r"elei[cç]", text) and not re.search(r"\b20\d\d\b", text):
        text += f" {time.strftime('%Y')}"  # notícias deste ano, não de 2022
    return text


def research(query):
    """Pesquisa na internet (Gemini com a busca do Google) e mostra o resultado numa janela da tela cheia:
    manchete, placar com barras, resumo, pontos e fontes. A fala é a resposta resumida."""
    query = str(query or "").strip()
    if not query:
        print("Jarvis > O que o senhor quer que eu pesquise?")
        return False
    if not N.available() and not N.groq_available():
        print("Jarvis > Para pesquisar na internet preciso da chave do Gemini ou do Groq (setx GEMINI_API_KEY).")
        return False
    set_state("pensando")
    U.speech("Pesquisando, senhor...")  # a busca leva alguns segundos: a legenda já mostra que ele está nisso
    question = f"Hoje é {time.strftime('%d/%m/%Y')}. Pergunta: {query}"
    try:
        raw, sources = N.search_generate(RESEARCH_PROMPT, question)
    except Exception as e:
        # cota de pesquisa da IA acabou (ou demorou): lê o DuckDuckGo e a IA que ainda tiver cota monta a resposta
        print(f"Jarvis > (pesquisa da IA falhou: {e}; usando os resultados do DuckDuckGo)")
        found = F.web_snippets(_news_query(query))
        if not found:
            print("Jarvis > Não consegui pesquisar agora, senhor. A cota grátis da IA acabou e a busca não respondeu.")
            return False
        results = "\n".join(f"- {r['titulo']} ({r['site']}): {r['trecho']}" for r in found)
        try:
            raw = think(RESEARCH_PROMPT + " Use SÓ os resultados de busca recebidos; se não bastarem, diga isso.",
                        f"{question}\nResultados de busca de agora:\n{results}", json_mode=True, temperature=0.2)
        except Exception as e2:
            print(f"Jarvis > (sem IA para resumir: {e2})")
            print("Jarvis > Não consegui pesquisar agora, senhor. A cota grátis da IA acabou por hoje.")
            return False
        seen, sources = set(), []
        for r in found:
            if r["site"] and r["site"] not in seen:
                seen.add(r["site"])
                sources.append({"nome": r["site"][:40], "titulo": r["titulo"]})
    data = _clean_research(raw)
    if data is None:  # a IA respondeu em texto solto: vira só o resumo
        text = re.sub(r"[*_#`]", "", str(raw)).strip()
        data = {"titulo": query.capitalize(), "resumo": text[:600], "fala": text[:300]}
    spoken = re.sub(r"[*_#`]", "", str(data.pop("fala", "") or "")).strip() or str(data.get("resumo", ""))[:300]
    data["fontes"] = [{"nome": src["nome"], "titulo": src.get("titulo", "")} for src in sources[:4]]
    data["hora"] = time.strftime("%H:%M")
    tema = str(data.get("tema") or "").strip()
    U.card(f"Pesquisa · {tema}" if tema else "Pesquisa", json.dumps(data, ensure_ascii=False), 60000)
    print(f"Jarvis > {spoken}")
    return True


# ========================= SISTEMA =========================

def system_info():
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    mem = MEMORYSTATUSEX()
    mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
    print(f"Jarvis > RAM total: {mem.ullTotalPhys / (1024**3):.1f} GB")
    print(f"Jarvis > RAM disponível: {mem.ullAvailPhys / (1024**3):.1f} GB")
    print(f"Jarvis > CPU: {platform.processor() or platform.machine()}")
    for drive in ("C:\\", "G:\\"):
        if Path(drive).exists():
            usage = shutil.disk_usage(drive)
            print(f"Jarvis > Disco {drive[0]}: {usage.free/(1024**3):.1f} GB livres de {usage.total/(1024**3):.1f} GB")


def media_control(action):
    action = normalize(action)
    keys = {
        "play": 0xB3, "pause": 0xB3, "play_pause": 0xB3,
        "next": 0xB0, "proxima": 0xB0,
        "previous": 0xB1, "anterior": 0xB1,
        "stop": 0xB2, "parar": 0xB2,
    }
    key = keys.get(action)
    if key is None:
        return False
    ctypes.windll.user32.keybd_event(key, 0, 0, 0)
    ctypes.windll.user32.keybd_event(key, 0, 2, 0)
    print(f"Jarvis > Mídia: {action}.")
    return True


def is_own_console_in_front():
    """A janela da frente é o próprio Jarvis (reator, console ou Windows Terminal)?"""
    return F.is_jarvis_window(F.foreground_window())


def window_control(action):
    need_pyautogui()
    action = normalize(action)
    if action in ("minimizar", "maximizar", "fechar"):
        # age direto na janela do usuário (nunca na do Jarvis): atalho de teclado podia cair
        # na tela cheia do Jarvis e fechá-la
        hwnd = F.user_target_window()
        if not hwnd:
            print("Jarvis > Clique na janela que quer mexer e peça de novo; a da frente é a minha.")
            return False
        u32 = ctypes.windll.user32
        if action == "fechar":
            u32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE: igual ao X da janela
        else:
            u32.ShowWindow(hwnd, 6 if action == "minimizar" else 3)  # SW_MINIMIZE / SW_MAXIMIZE
    elif action == "trocar":
        pyautogui.hotkey("alt", "tab")
    elif action == "desktop":
        pyautogui.hotkey("win", "d")
    elif action == "menu":
        pyautogui.press("win")
    else:
        return False
    print(f"Jarvis > Ação de janela: {action}.")
    return True


def take_screenshot():
    return _new_screenshot() is not None


def _new_screenshot():
    """Tira um print da tela inteira e devolve o arquivo (None se falhou)."""
    try:
        import mss
        import mss.tools
    except ImportError:
        print("Jarvis > Instale MSS: python -m pip install mss")
        return None
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    file = SCREENSHOT_DIR / f"print_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.png"
    try:
        with (getattr(mss, "MSS", None) or mss.mss)() as sct:  # mss.mss está saindo nas versões novas
            shot = sct.grab(sct.monitors[0])
            mss.tools.to_png(shot.rgb, shot.size, output=str(file))
        print(f"Jarvis > Print salvo em: {file}")
        return file
    except Exception as e:
        print(f"Jarvis > Erro no print: {e}")
        return None


def whatsapp_send_file(contact, file="print", caption=""):
    """Manda um print (novo ou o último) ou um arquivo pelo WhatsApp (WAHA). Sempre pergunta antes."""
    contact, ref = str(contact or "").strip(), str(file or "print").strip()
    if not contact:
        print("Jarvis > Para quem eu mando, senhor?")
        return False
    if not W.configured():
        print("Jarvis > Para mandar arquivo no WhatsApp eu preciso do WAHA (veja WHATSAPP no LEIA-ME).")
        return False
    low = normalize(ref)
    if low in ("", "print", "tela", "screenshot", "print da tela", "um print"):
        path = _new_screenshot()
    elif "ultimo" in low and "print" in low:
        shots = sorted(SCREENSHOT_DIR.glob("print_*.png")) if SCREENSHOT_DIR.exists() else []
        path = shots[-1] if shots else None
    else:
        path = resolve_path(ref)
        path = path if path and Path(path).is_file() else None
    if not path:
        print(f"Jarvis > Não achei o arquivo {ref}.")
        return False
    try:
        chat_id, name = W.find_contact(contact, B.same_person)
        if not chat_id:
            print(f"Jarvis > Não achei {contact} nos contatos do WhatsApp.")
            return False
        if not confirm(f"Mando {Path(path).name} para {name}?"):
            print("Jarvis > Cancelado, não enviei.")
            return False
        W.send_file(chat_id, path, caption)
    except W.WahaError as e:
        print(f"Jarvis > Não consegui mandar: {e}.")
        return False
    print(f"Jarvis > Enviei {Path(path).name} para {name}.")
    return True


# ========================= ROTEADOR LOCAL =========================

ORDINAL = r"(primeir[oa]|segund[oa]|terceir[oa]|quart[oa]|quint[oa]|sext[oa]|setim[oa]|oitav[oa]|non[oa]|decim[oa]|\d+)"


MY_CITY = re.compile(r"^(?:a |na |da )?(?:minha cidade|minha regiao|aqui|onde eu (?:moro|to|estou)|minha casa)$")


def weather_cities(text):
    """ "minha cidade e em sao paulo tambem" -> ["", "sao paulo"] ("" = a cidade do perfil)."""
    text = re.sub(r"\b(?:tambem|agora|hoje|amanha|por favor|ai|pra mim)\b", " ", text)
    cities = []
    for part in re.split(r"\s+e\s+(?:(?:em|no|na|de|do|da)\s+)?", text.strip()):
        part = re.sub(r"^(?:em|no|na|de|do|da)(?:\s+|$)", "", re.sub(r"\s+", " ", part).strip(" ?,."))
        city = "" if MY_CITY.match(part) else part
        if city not in cities:
            cities.append(city)
    return cities or [""]


def tool(tool_name, /, **args):
    """Roda uma ferramenta do catálogo pelo nome (usado pelo roteador rápido)."""
    log_action(tool_name, json.dumps(args, ensure_ascii=False))
    opening(tool_name)
    with D.timing("fazer"):
        result = TOOLS_BY_NAME[tool_name]["run"](args)
    D.action(tool_name, args, result is not False)
    learn_from_action(tool_name, args, result)
    return result


def act(name, fn, *args):
    log_action(name, " ".join(str(a) for a in args))
    opening(name)
    with D.timing("fazer"):
        result = fn(*args)
    D.action(name, named_args(name, args), result is not False)
    learn_from_action(name, named_args(name, args), result)
    return result


def named_args(name, args):
    """("open_target", ("edge",)) -> {"target": "edge"}: o diário guarda igual à IA, para dar para repetir."""
    if not args:
        return {}
    spec = TOOLS_BY_NAME.get(name)
    keys = re.findall(r'"(\w+)":', spec["args"]) if spec else []
    if len(keys) >= len(args):
        return dict(zip(keys, args))
    return {"args": " ".join(str(a) for a in args)}


# Ações que abrem ou mostram algo fora do Jarvis (programa, pasta, navegador)
SHOWS_OUTSIDE = {"open_target", "open_url", "open_folder", "open_search_result", "show_search_result",
                 "focus_window", "open_settings", "play_youtube", "youtube_control", "search_web",
                 "web_search", "web_click", "whatsapp_send", "spotify_play"}


# Ferramentas cujo resultado vira uma janelinha na tela cheia (título da janela)
INFO_CARDS = {"weather": "Clima", "system_info": "PC", "battery_status": "Bateria", "network_info": "Rede",
              "calculate": "Conta", "what_i_know": "O que sei de você", "history": "Histórico",
              "list_processes": "Programas abertos", "list_windows": "Janelas", "read_clipboard": "Área de transferência",
              "file_info": "Arquivo", "web_read": "Página", "list_routines": "Rotinas", "add_reminder": "Lembrete marcado",
              "start_timer": "Timer", "tell_time": "Hora"}
_ran = []  # ferramentas usadas no pedido atual
# Ferramentas cujo resultado ele conta de volta numa conversa ("Verifiquei, senhor. Em Curitiba está...")
TALK_ABOUT = {"weather", "system_info", "battery_status", "network_info"}
TALK_ABOUT_LIST = {"whatsapp_read"}  # mostra a lista na tela e conta o principal em voz


def opening(name):
    """Vai abrir algo: com segunda tela, a janela nova vai para lá; sem, o Jarvis sai da frente."""
    _ran.append(name)
    if name not in SHOWS_OUTSIDE or (name == "whatsapp_send" and W.configured()):  # pelo WAHA nada abre na tela
        return
    try:
        if F.second_monitor():
            F.expect_window()
        else:
            U.behind()
    except Exception:
        pass


COMPOUND = re.compile(
    r"\s(?:e|depois|e depois|e entao|entao|e tambem)\s+(?:me\s+|pra mim\s+)?"
    r"(?:abre|abra|explica|explique|fala|fale|diz|diga|conta|conte|digita|digite|escreve|escreva|"
    r"pesquisa|pesquise|procura|procure|toca|coloca|poe|aumenta|abaixa|fecha|feche|mostra|"
    r"le|leia|resume|resuma|cria|crie|liga|desliga|muta|tira|faz|faca|manda|copia|move|apaga)\b"
)


def number_ref(text):
    """'primeiro' -> '1', 'o 2' -> '2', resto fica como está."""
    text = text.strip()
    if re.fullmatch(rf"(?:o |a )?{ORDINAL}", text):
        return str(ordinal_to_number(text))
    return text


# "aí" sem acento só depois de vírgula: "abre o Meta AI" não pode perder o nome
POLITE_END = re.compile(r"(?:[\s,]+(?:por favor|pfv|pra mim|para mim)|\s*,\s*ai|\s+aí)\s*[.!?]*$", re.I)
POLITE_START = re.compile(r"^por favor[,\s]+", re.I)


PAPAI = re.compile(r"\bacorda,? (?:bebe|nenem|neném)\b|\bpapai chegou\b|\bpapai ta on\b|\bpapai esta em casa\b")
LATER = re.compile(r"\b(?:as|a|ate|para as|pras)\s+\d{1,2}(?:\s*(?:h|:|horas?)\s*\d{0,2})?\b(?!\s*(?:%|por cento|minutos?|segundos?))"
                   r"|\b\d{1,2}\s*(?:h|:)\s*\d{2}\b|\b\d{1,2}h\b|\bamanha\b|\bdaqui a\b|\bme acorda\b|\bdespertador\b(?!\s*$)")


# frases com hora que não são "faça isso mais tarde"
NOT_LATER = re.compile(r"\b(?:volume|brilho|nao perturbe|pomodoro|conta os dias|contagem|vence|aniversario|"
                       r"lembrete de agua|quantos dias)\b")


def fast_local_router(user_text):
    full = clean_prefix(user_text)  # do jeito que veio (para "digita ...")
    # por voz chega "abre o Chrome, por favor." / "abre o Spotify aí": o fim atrapalha achar o programa
    text = POLITE_END.sub("", POLITE_START.sub("", full)).strip(" .!?") or full
    clean = normalize(text)

    if STOP_ONLY.match(clean) or STOP_ONLY.match(normalize(user_text)):
        print(f"Jarvis > {vary(['Parei, senhor.', 'Pronto, parei.', 'Parado, senhor.'])}")
        return True

    if small_talk(normalize(user_text)) or small_talk(clean):
        return True

    if brain_router(text, clean):
        return True


    # pedido com hora ("toca lofi às 7h", "amanhã abre o Spotify", "me acorda 6h30"): não é para agora,
    # a IA agenda (antes o atalho do "toca ..." tocava na hora)
    if LATER.search(clean) and not NOT_LATER.search(clean):
        return False

    if PAPAI.search(clean):
        act("greeting", greeting)
        return True

    if re.fullmatch(r"(?:testa|teste|testar) (?:o )?despertador", clean):
        commands.put(("despertador", "padrão"))  # toca agora, igual às 7h (depois do pedido atual)
        print("Jarvis > Testando o despertador, senhor.")
        return True

    # "sim"/"não" sozinho sem nada esperando resposta (a pergunta já foi respondida): não vira pedido novo,
    # senão a IA repetia a última ação (mandava a mesma mensagem duas vezes)
    lonely = set(re.findall(r"\w+", clean))
    if lonely and lonely <= (YES_WORDS | NO_WORDS | {"senhor", "pode", "mandar", "manda", "obrigado", "quero", "faz",
                                                     "faca", "sozinho"}) \
            and not lonely & {"cancela", "cancelar", "para", "pare"}:
        if habit_offer:  # 28: "quer que eu faça sozinho?" -> vira rotina
            return accept_habit(answer_kind(clean) is not False)
        print("Jarvis > Não há nada esperando confirmação, senhor.")
        return True

    # 13: "fecha ele", "manda isso pra Ana", "abre lá": quem é "ele/isso/lá" só a conversa diz. A IA resolve.
    if CONTEXT_WORDS.search(clean) and not CONTEXT_OK.search(clean) and not (last_results and RESULT_VERBS.search(clean)):
        return False

    if (learning_router(text, clean) or skills_router(text, clean) or routine_router(text, clean)
            or screen_router(text, clean) or docs_router(text, clean) or hands_router(text, clean)):
        return True

    # memória
    if re.fullmatch(rf"(?:{CALL},? )?o que (?:voce|vc) sabe (?:sobre|de) mim\??", clean):
        act("what_i_know", M.what_i_know)
        return True
    m = re.fullmatch(rf"(?:{CALL},? )?(?:esquece|esqueca|apaga da memoria)\s+(?:que\s+|o\s+|a\s+|sobre\s+)?(.+)", clean)
    if m:
        what = re.sub(r"^(?:meu|minha|meus|minhas)\s+", "", m.group(1)).strip(" .!?")
        if len(what) < 3 or what in {"isso", "isto", "disso", "tudo", "aquilo"}:
            return False  # "esquece isso" = deixa pra lá: a IA decide
        act("forget", M.forget, what)
        return True
    m = re.fullmatch(rf"(?:{CALL},? )?meu nome e\s+(.+)", clean)
    if m:
        name = re.split(r"[,.!?;]| e | mas ", text[-len(m.group(1)):])[0].strip()
        if not name or len(name.split()) > 4:
            return False  # "meu nome é João e eu moro em Recife": a IA separa nome e cidade
        act("set_profile", M.set_profile, "nome", name.title())
        return True

    # Spotify: "toca evidências no spotify", "abre o spotify e toca evidências"
    if "spotify" in clean and re.search(r"\b(?:toca|toque|tocar|bota|coloca|poe|ouvir|pesquisa|pesquise|procura|busca)\b", clean):
        query = re.sub(r"\b(?:abre|abra|abrir|o|a|no|na|pelo|e|toca|toque|tocar|bota|coloca|poe|quero|ouvir|"
                       r"pesquisa|pesquise|procura|busca|musica|spotify)\b", " ", clean)
        query = re.sub(r"\s+", " ", query).strip(" .,!?")
        if query:
            tool("spotify_play", query=query)
            return True
    # pedido com duas partes ("abre o bloco de notas e me explica X") vai inteiro para a IA,
    # que divide em várias ações; o roteador rápido só entende um comando por vez
    if COMPOUND.search(clean):
        return False

    # volume ("procura o volume 2 de harry potter" e "toca som de preto 2" não são volume)
    VOL = r"\b(?:volume|som)\b"
    not_volume = re.match(r"^(?:procura|procure|busca|busque|pesquisa|pesquise|toca|toque|tocar|calcula|calcule|"
                          r"quanto|acha|ache|encontra|encontre|abre|abra)\b", clean)
    up = re.search(rf"\b(aumenta|sobe|aumente|suba)\b.*{VOL}", clean)
    down = re.search(rf"\b(abaixa|diminui|reduz|abaixe|diminua|reduza|baixa|baixe)\b.*{VOL}", clean)
    if (up or down) and not not_volume:
        to = re.search(r"\b(?:pra|para|ate)\s+(\d{1,3})\b", clean)
        if to:  # "aumenta o volume pra 80" = deixa em 80
            act("set_volume", set_volume, int(to.group(1)))
            return True
        m = re.search(r"\b(\d{1,3})\b", clean)  # "aumenta o volume em 10" = mais 10
        step = int(m.group(1)) if m else 10
        act("change_volume", change_volume, step if up else -step)
        return True

    if "metade" in clean and "brilho" not in clean and (re.search(VOL, clean) or re.search(r"\bdeixa\b", clean)):
        act("set_volume", set_volume, 50)
        return True

    m = None if not_volume else re.search(rf"{VOL}\D{{0,20}}?\b(\d{{1,3}})\b", clean)
    if m:
        act("set_volume", set_volume, int(m.group(1)))
        return True

    if any(x in clean for x in ["qual o volume", "quanto ta o volume", "quanto esta o volume", "volume atual"]):
        act("get_volume", get_volume)
        return True

    if re.search(r"\b(desmuta|tira do mudo|ativa o som|liga o som)\b", clean):
        act("mute_audio", mute_audio, False)
        return True

    if any(x in clean for x in ["muta o volume", "muta o som", "mute o volume", "mute o som", "sem som", "silencia o som", "desliga o som"]):
        act("mute_audio", mute_audio, True)
        return True

    # pesquisa web (antes da busca de arquivos, que também começa com "procura"/"busca")
    m = re.match(r"^(?:pesquisa|pesquise|procura|procure|busca|busque)\s+no\s+youtube\s+(.+)$", text, flags=re.I)
    if m:
        act("search_web", search_web, m.group(1), "youtube")
        return True

    m = re.match(r"^(?:procura|procure|busca|busque|pesquisa|pesquise)\s+(?:na internet|no google)\s+(.+)$", text, flags=re.I)
    if m:
        act("search_web", search_web, m.group(1), "google")
        return True

    m = re.match(r"^(?:pesquisa|pesquise)\s+(.+)$", text, flags=re.I)
    if m:
        act("search_web", search_web, m.group(1), "google")
        return True

    # arquivos
    for pattern in [
        r"^(?:procura|procure|busca|busque|encontra|encontre)\s+(?:um\s+|uma\s+|o\s+|a\s+)?(?:arquivo\s+)?(.+)$",
        r"^(?:ache|acha)\s+(?:um\s+|uma\s+|o\s+|a\s+)?(?:arquivo\s+)?(.+)$",
    ]:
        m = re.match(pattern, clean)
        if m:
            query = re.sub(r"\s+(pra mim|para mim)$", "", m.group(1).strip()).strip()
            query = re.sub(r"^(um|uma)\s+", "", query).strip()
            act("search_files", search_files, query)
            return True

    # "abre o segundo (resultado)" logo depois de uma pesquisa na web: clica no link
    RUN = r"(?:abre|abra|abrir|executa|execute|executar|roda|rode|rodar|clica|clique|entra)"
    RESULT = r"(?: resultado| link| site| da lista)?"
    picks_result = (re.fullmatch(rf"(?:{RUN} )?(?:n?o |n?a )?{ORDINAL}{RESULT}(?: {RUN})?", clean)
                    or re.match(rf"^{RUN}\s+(?:n?o|n?a)\s+{ORDINAL}\b{RESULT}$", clean))
    if last_kind == "web" and picks_result:
        if not B.last_links:
            return False  # a pesquisa abriu no navegador comum: a IA decide
        tool("web_click", target=str(ordinal_to_number(clean)))
        return True
    files = last_results if last_kind != "web" else []
    shows_result = re.fullmatch(
        rf"(?:mostra|mostre) (?:o |a )?{ORDINAL}(?: resultado)?(?: na pasta)?", clean
    )
    if last_kind != "web" and not files and (picks_result or shows_result):
        print("Jarvis > Faça uma busca primeiro para escolher um resultado.")
        return True

    # resultados da última busca: "mostra o segundo na pasta", "onde ele está"
    if files and (
        re.search(rf"\bmostra\b.*\b{ORDINAL}\b", clean)
        or any(x in clean for x in ["mostra na pasta", "mostra ele na pasta", "onde ele esta", "onde esta o arquivo"])
    ):
        n = ordinal_to_number(clean)
        if n is None:
            print("Jarvis > Qual resultado?")
        else:
            act("show_search_result", show_search_result, n)
        return True

    # só "2" ou "o segundo" depois de uma busca
    if files and re.fullmatch(rf"(?:{RUN} )?(?:o |a )?{ORDINAL}(?: {RUN})?", clean):
        act("open_search_result", open_search_result, ordinal_to_number(clean))
        return True

    # "abre o terceiro", "abre o 2", "abre ele"
    if files and (
        re.match(rf"^(?:abre|abra|abrir|executa|execute|roda|rode)\s+(?:o|a)\s+{ORDINAL}\b", clean)
        or any(x in clean for x in ["abre ele", "abre o arquivo", "abre esse"])
    ):
        n = ordinal_to_number(clean)
        if n is None:
            print("Jarvis > Qual resultado?")
        else:
            act("open_search_result", open_search_result, n)
        return True

    # ajuda, hora, pastas
    if re.fullmatch(r"(ajuda|help|comandos|lista de comandos)\??", clean) or re.search(
        r"\bo que (voce|vc|tu) (sabe|consegue|pode) fazer\b|\bo que (voce|vc) faz\b", clean
    ):
        act("show_help", show_help)
        return True
    if re.search(r"\b(que horas sao|que hora e|horas agora|que dia e hoje)\b", clean):
        act("tell_time", tell_time)
        return True
    m = re.match(r"^(?:abre|abra|abrir|mostra)\s+(?:a\s+)?(?:pasta|minha pasta|meus|minhas)\s+(?:de\s+|do\s+|da\s+)?(.+)$", clean)
    if m:
        act("open_folder", open_folder, m.group(1).strip())
        return True

    # ---- YouTube: tocar direto e controlar o vídeo aberto
    for pattern, action in [
        (r"\btela cheia\b", "tela cheia"),
        (r"\b(avanca|adianta)\s+(?:o\s+)?(?:video|10 segundos)\b|\bpula 10 segundos\b", "avancar"),
        (r"\b(volta|retrocede)\s+(?:o\s+)?(?:video|10 segundos)\b", "voltar"),
        (r"\b(proximo video|pula esse video|pula o video|outro video)\b", "proximo"),
        (r"\b(liga|ativa|coloca)\s+(?:a\s+)?legenda\b", "legenda"),
    ]:
        if re.search(pattern, clean):
            tool("youtube_control", action=action)
            return True

    m = re.match(r"^(?:toca|toque|tocar|bota|coloca|poe|abre|abra|quero ouvir|quero ver)\s+(?:a\s+|o\s+|uma\s+|um\s+)?"
                 r"(?:musica|video|clipe|cancao)\s+(?:d[aoe]s?\s+)?(.+?)(?:\s+no youtube)?$", clean)
    if m:
        tool("play_youtube", query=m.group(1).strip())
        return True
    m = re.match(r"^(?:toca|toque|tocar)\s+(.+?)(?:\s+no youtube)?$", clean)
    if m:
        tool("play_youtube", query=m.group(1).strip())
        return True
    # ---- ferramentas extras
    m = re.match(r"^(?:abre|abra|abrir|mostra|vai em|vai nas)\s+(?:as\s+)?configurac\w*(?:\s+(?:de|do|da|das|dos)\s+(.+))?$", clean)
    if m:
        tool("open_settings", page=m.group(1) or "")
        return True
    if re.search(r"\bbateria\b", clean):
        tool("battery_status")
        return True
    m = re.search(r"\bbrilho\b.*?\b(\d{1,3})\b", clean)
    if m:
        tool("set_brightness", percent=int(m.group(1)))
        return True
    if re.search(r"\b(cancela|cancelar|cancele)\s+(o\s+)?(desligamento|reinicio)\b|\bnao desliga\b", clean):
        tool("power_action", action="cancelar")
        return True
    m = re.search(r"\b(desliga|desligar|desligue|reinicia|reiniciar|reinicie)\s+(?:o\s+)?(?:pc|computador|notebook)\b"
                  r"(?:.*?\b(\d+)\s*(min|minuto|minutos|h|hora|horas)\b)?", clean)
    if m:
        minutes = int(m.group(2)) * (60 if m.group(3) and m.group(3).startswith("h") else 1) if m.group(2) else 1
        tool("power_action", action="desligar" if m.group(1).startswith("deslig") else "reiniciar", minutes=minutes)
        return True
    if re.search(r"\b(bloqueia|bloquear|bloqueie|trava|travar)\s+(?:o\s+|a\s+)?(pc|computador|notebook|tela)\b", clean):
        tool("power_action", action="bloquear")
        return True
    if re.search(r"\b(suspende|suspender|hiberna|hibernar)\b", clean):
        tool("power_action", action="suspender")
        return True
    m = re.match(r"^(?:fecha|feche|fechar|encerra|encerre|mata)\s+(?:o\s+|a\s+)?(.+?)(?:\s+pra mim)?$", clean)
    if m:
        target = m.group(1).strip()
        if target in {"janela", "essa janela", "esta janela", "isso", "isto"}:
            act("window_control", window_control, "fechar")
        elif target in {"youtube", "video", "aba", "essa aba", "esta aba", "musica", "navegador do jarvis"} and B.is_open():
            remember_video()  # 92: guarda onde o vídeo parou
            act("close_tab", B.close_tab)  # o YouTube toca numa aba do Jarvis, não num programa
        else:
            tool("close_app", name=target)
        return True
    if re.search(r"\b(cancela|cancelar|para|parar)\s+(?:o\s+|os\s+)?(timer|timers|alarme|alarmes|lembrete|lembretes)\b", clean):
        tool("cancel_timers")
        return True
    # timer só com duração ("em 10 minutos", "daqui a 2 horas", "timer de 5 min"). Hora marcada
    # ("me lembra às 8 horas", "amanhã às 10") vai para a IA, que marca um lembrete de verdade.
    m = re.search(r"\b(?:me lembra|me lembre|me avisa|me avise|timer|alarme|cronometro)\b.*?\b(\d+)\s*"
                  r"(seg|segundo|segundos|min|minuto|minutos|h|hora|horas)\b(?:\s+(?:de|pra|para|que)\s+(.+))?", clean)
    clock = re.search(r"\b(?:as|pras|ate as|pelas)\s+\d|\b\d{1,2}(?::|h)\d{2}\b|\b(?:da manha|da tarde|da noite|"
                      r"de manha|de tarde|de noite|amanha|hoje a noite|segunda|terca|quarta|quinta|sexta|sabado|"
                      r"domingo|meio dia|meia noite|dia \d)", clean)
    if m and not clock:
        n, unit = int(m.group(1)), m.group(2)
        minutes = n / 60 if unit.startswith("seg") else n * 60 if unit.startswith("h") else n
        tool("start_timer", minutes=minutes, message=(m.group(3) or "Tempo esgotado!").strip())
        return True
    if re.search(r"\b(?:zap|whats ?app|mensage(?:m|ns)? nova)", clean) and not re.match(r"^(?:manda|mande|envia|envie|responde)", clean):
        m = re.search(r"\b(?:mensage(?:m|ns)|mandou|falou|escreveu)\b.*?\b(?:d[aoe]|que (?:a|o))\s+(?!zap\b|whats)(\w[\w ]*?)"
                      r"(?:\s+(?:no|pelo)\s+(?:zap|whats ?app))?\??$", clean)
        if re.search(r"\b(?:le|ler|leia|ve|ver|veja|tem|chegou|quais|mostra|mostre)\b", clean):
            tool("whatsapp_read", contact=(m.group(1).strip() if m else ""))
            return True
    m = re.search(r"\b(?:clima|previsao do tempo|como (?:esta|ta) o tempo|temperatura|vai chover)\b(?:.*?\b(?:em|de|no|na)\s+(.+?))?\??$", clean)
    if m:
        for city in weather_cities(m.group(1) or ""):
            tool("weather", city=city)
        return True
    m = re.match(r"^(?:calcula|calcule|quanto e|quanto da|quanto que e|conta)\s+(.+?)\??$", clean)
    if m and re.search(r"\d", m.group(1)):
        tool("calculate", expression=m.group(1))
        return True
    m = re.match(r"^(?:resume|resuma|resumir|faz um resumo d[oea]|faca um resumo d[oea])\s+(?:o\s+|a\s+)?(?:arquivo\s+)?(.+)$", clean)
    if m:
        tool("summarize_file", path=number_ref(m.group(1)))
        return True
    m = re.match(r"^(?:le|leia|ler)\s+(?:o\s+|a\s+)?(?:arquivo\s+)?(.+)$", clean)
    if m:
        tool("read_file", path=number_ref(m.group(1)))
        return True
    m = re.match(r"^(?:apaga|apague|exclui|exclua|deleta|delete|joga na lixeira|manda pra lixeira)\s+(?:o\s+|a\s+)?(?:arquivo\s+)?(.+)$", clean)
    if m:
        tool("delete_item", path=number_ref(m.group(1)))
        return True
    m = re.match(r"^(?:digita|digite|escreve|escreva)\s+(.+)$", full, flags=re.I)
    if m:
        tool("type_text", text=m.group(1))
        return True
    m = re.match(r"^(?:modo|rotina|ativa o modo|ativar modo|ativa a rotina)\s+(.+)$", clean)
    if m:
        tool("enter_mode" if R.find_mode(m.group(1)) else "run_routine", name=m.group(1).strip())
        return True
    if re.search(r"\b(quais|lista as|mostra as) rotinas\b", clean):
        tool("list_routines")
        return True
    if re.search(r"\b(meu ip|tem internet|to com internet|tou com internet|estou com internet|wifi conectado|como ta a internet)\b", clean):
        tool("network_info")
        return True
    if re.search(r"\b(processos|programas usando mais memoria)\b", clean):
        tool("list_processes")
        return True
    if re.search(r"\b(quais|lista as|mostra as) janelas\b", clean):
        tool("list_windows")
        return True
    if re.search(r"\bo que (eu )?copiei\b|\barea de transferencia\b", clean):
        tool("read_clipboard")
        return True
    m = re.match(r"^(?:vai para o|vai pro|vai para a|vai pra|muda para o|muda pro|foca no|foca na)\s+(.+)$", clean)
    if m:
        tool("focus_window", title=m.group(1).strip())
        return True

    # abrir apps/sites
    m = re.match(r"^(?:abre|abra|abrir|inicia|inicie|executa|execute|roda|rode|joga|jogar)\s+(?:o\s+|a\s+)?(.+?)(?:\s+pra mim|\s+para mim)?$", text, flags=re.I)
    if m:
        if re.fullmatch(rf"(?:o |a )?{ORDINAL}(?: resultado| link| site)?", normalize(m.group(1))):
            return False  # "abre o segundo resultado" sem busca antes: a IA vê o contexto
        act("open_target", open_target, m.group(1).strip(" ."))
        return True

    # mídia
    if re.match(r"^(play|pause|pausa|pausar|continua|continuar|despausa|toca)\b", clean):
        act("media_control", media_control, "play_pause")
        return True
    if any(x in clean for x in ["proxima musica", "proxima faixa", "pula a musica", "pula essa"]):
        act("media_control", media_control, "next")
        return True
    if any(x in clean for x in ["musica anterior", "faixa anterior", "volta a musica"]):
        act("media_control", media_control, "previous")
        return True

    # janelas e sistema
    if "minimiza" in clean:
        act("window_control", window_control, "minimizar")
        return True
    if "maximiza" in clean:
        act("window_control", window_control, "maximizar")
        return True
    if any(x in clean for x in ["mostra o desktop", "area de trabalho"]):
        act("window_control", window_control, "desktop")
        return True
    if any(x in clean for x in ["troca de janela", "outra janela"]):
        act("window_control", window_control, "trocar")
        return True
    if any(x in clean for x in ["quanta ram", "quanto de ram", "espaco no disco", "informacoes do pc"]):
        act("system_info", system_info)
        return True
    if any(x in clean for x in ["tira um print", "tira print", "captura a tela", "faz um print"]):
        act("take_screenshot", take_screenshot)
        return True

    return False


META_TOOLS = {"what_went_wrong", "explain_last", "error_report", "weekly_report", "stopwatch_today", "learned_week"}


def learning_router(text, clean):
    """Diário, aprendizado, apelidos e pessoas: o motor que faz ele melhorar."""
    handled = _learning_router(text, clean)
    if handled and D.current is not None and any(a["nome"] in META_TOOLS for a in D.current["acoes"]):
        D.route("meta")  # perguntas sobre o próprio Bolha não viram o "último pedido" (do "errou" e do "por quê")
    return handled


def _learning_router(text, clean):
    m = re.search(r"\bo que (?:deu|foi|saiu|ficou) errado\b(?:.*?\b(hoje|ontem)\b)?", clean)
    if m:
        tool("what_went_wrong", day=m.group(1) or "hoje")
        return True
    if re.search(r"\bpor ?que (?:voce|vc|tu) (?:fez|abriu|tocou|mandou|escolheu|fechou)\b", clean):
        tool("explain_last")
        return True
    if re.search(r"\brelatorio de erros?\b", clean):
        tool("error_report")
        return True
    if re.search(r"\brelatorio da semana\b|\b(?:gera|faz|faca|cria|monta) o relatorio\b", clean):
        tool("weekly_report")
        return True
    if re.search(r"\bcronometro (?:de hoje|do dia)\b|\bquanto tempo (?:voce|vc) (?:demora|leva|levou|demorou)\b", clean):
        tool("stopwatch_today")
        return True
    if re.search(r"\bo que (?:voce|vc) aprendeu\b", clean):
        tool("learned_week")
        return True
    m = re.match(r"^(?:esquece|esqueca|apaga)\s+(?:o |a )?(apelido|pessoa|correcao)\s+(?:d[oae]s?\s+)?(.+)$", clean)
    if m:
        tool("forget_learned", kind=m.group(1), what=m.group(2).strip(" .!?"))
        return True
    alias = A.parse_alias(text)
    if alias:
        tool("set_alias", alias=alias[0], value=alias[1])
        return True
    m = (re.match(r"^(?:o |a )?aniversario d[oae]s? (.+?) (?:e|eh) (?:dia |no dia |em )?(.+?)[.!]?$", clean)
         or re.match(r"^(?:o |a )?(.+?) faz aniversario (?:dia |no dia |em )?(.+?)[.!]?$", clean))
    if m and A.birthday_of(m.group(2)):
        tool("remember_person", name=_original(text, m.group(1)), field="aniversario", value=m.group(2))
        return True
    m = re.match(r"^o que (?:voce|vc) sabe (?:sobre|d)\s*(?:o |a )?(?!mim\b)(.+?)\??$", clean)
    if m and m.group(1) not in ("mim", "eu"):
        tool("about_person", name=m.group(1))
        return True
    m = re.search(r"\b(?:faz|faca|fazer|faça) (?:um )?backup da (?:minha |sua )?memoria(?:\s+n[oa]\s+(.+))?", clean)
    if m:
        tool("memory_backup", dest=(m.group(1) or "").strip())
        return True
    if re.search(r"\b(?:mostra|abre|abra)\s+(?:o )?painel da memoria\b|\bmostra (?:a )?(?:sua )?memoria\b", clean):
        tool("memory_panel")
        return True
    return False


def folder_of(name):
    """ "downloads" -> a pasta Downloads de verdade; senão o caminho como veio."""
    key = normalize(re.sub(r"^(?:a pasta |pasta |minha pasta |meus |minhas |a |o |os |as )", "", str(name or "").strip()))
    return FOLDERS.get(key) or Path(os.path.expandvars(str(name))).expanduser()


SHORTCUT_WORDS = sorted(MA.SHORTCUTS, key=len, reverse=True)


def hands_router(text, clean):
    """As mãos: botões, janelas, Windows, programas, limpeza, macros, jogos e saúde do PC."""
    if clean in ("para de gravar", "parar de gravar", "para a gravacao", "chega de gravar"):
        tool("stop_macro")
        return True
    m = re.match(r"^(?:observa|observe|olha|olhe) o que eu (?:faco|vou fazer)(?: e (?:aprende|grava)(?: como (.+))?)?$", clean) \
        or re.match(r"^grava (?:uma )?macro(?: chamada| com o nome)? ?(.*)$", clean)
    if m:
        tool("record_macro", name=(m.group(1) or "").strip())
        return True
    m = re.match(r"^(?:repete|repita|roda|rode|faz|faca) a macro (.+)$", clean)
    if m:
        tool("play_macro", name=m.group(1))
        return True
    if re.search(r"\bquais macros\b", clean):
        tool("list_macros")
        return True
    m = re.match(r"^(?:clica|clique|aperta|aperte|toca|pressiona) (?:em |no |na |o botao |no botao |o |a )?(?:botao )?(.+)$", clean)
    if m and re.match(r"^(?:clica|clique)\b|^(?:aperta|aperte|pressiona) (?:o |no )?botao\b", clean):
        tool("click_ui", name=_original(text, m.group(1).strip(" .!?")) or m.group(1))
        return True
    if re.search(r"\b(?:le|leia|ler) (?:a |essa |esta )?janela\b|\bo que (?:ta|esta) escrito (?:na janela|aqui|nessa janela)\b", clean):
        tool("read_window")
        return True
    if re.search(r"\bquais botoes\b|\bque botoes\b", clean):
        tool("list_controls")
        return True
    m = re.match(r"^(?:salva|salve) (?:esse |este |o )?layout(?: como| com o nome)? ?(.*)$", clean)
    if m:
        tool("save_layout", name=m.group(1) or "padrao")
        return True
    m = re.match(r"^(?:layout|arruma as janelas(?: d[oa]| como)?|volta o layout(?: d[oa])?)\s*(.*)$", clean)
    if m and (clean.startswith(("layout ", "volta o layout")) or clean.startswith("arruma as janelas")):
        tool("apply_layout", name=m.group(1) or "padrao")
        return True
    m = re.match(r"^(?:coloca|poe|deixa|bota)? ?(?:o |a )?(.+?) e (?:o |a )?(.+?) lado a lado$", clean) \
        or re.match(r"^(?:coloca|poe|deixa|bota)? ?(?:o |a )?(.+?) lado a lado(?: com (?:o |a )?(.+))?$", clean)
    if m:
        tool("side_by_side", first=m.group(1), second=m.group(2) or "")
        return True
    m = re.match(r"^(?:manda|joga|move|leva) (?:essa janela|isso|ela|a janela|o |a )?\s*(.*?)\s*(?:para|pra|pro) (?:a )?(?:outra|segunda|2a) tela$", clean)
    if m:
        tool("to_second_screen", title=m.group(1).strip())
        return True
    m = re.search(r"\b(liga|ligar|ativa|desliga|desligar|desativa)\s+(?:o\s+)?(wi-?fi|wi fi|bluetooth)\b", clean)
    if m:
        tool("radio", kind=m.group(2), on=m.group(1).startswith(("liga", "ativa")))
        return True
    m = re.search(r"\b(?:modo|tema) (escuro|claro|noturno|dark|light)\b", clean)
    if m and not re.search(r"\b(?:reator|bolha|jarvis|tela do)\b", clean):
        tool("dark_mode", on=m.group(1) in ("escuro", "noturno", "dark"))
        return True
    m = re.search(r"\b(?:som|audio|saida de som|saida)\b.*?\b(?:no|na|para o|para a|pro|pra)\s+(fone|caixa|headset|alto[- ]falante|tv|monitor)\b", clean) \
        or re.match(r"^(?:troca|muda) (?:a )?saida de som(?: para (?:o |a )?(.+))?$", clean)
    if m:
        tool("audio_output", which=m.group(1) or "")
        return True
    m = re.search(r"\bresolucao\b.*?\b(\d{3,4})\s*(?:x|por)\s*(\d{3,4})\b", clean)
    if m:
        tool("set_resolution", width=int(m.group(1)), height=int(m.group(2)))
        return True
    if re.fullmatch(r"(?:apaga|desliga|apague|desligue) (?:a )?tela|(?:apaga|desliga) o monitor", clean):
        tool("screen_off")
        return True
    m = re.match(r"^(?:instala|instale|instalar|baixa e instala)\s+(?:o |a |um |uma )?(?:programa )?(.+)$", clean)
    if m:
        tool("install_program", name=m.group(1))
        return True
    m = re.match(r"^(?:desinstala|desinstale|desinstalar|remove o programa)\s+(?:o |a )?(.+)$", clean)
    if m:
        tool("uninstall_program", name=m.group(1))
        return True
    m = re.match(r"^(?:atualiza|atualize|atualizar)\s+(?:tudo|todos os programas|os programas|(?:o |a )?(.+))$", clean)
    if m and not re.search(r"\b(?:pagina|aba|bolha|jarvis|voce|vc)\b", clean):
        tool("update_programs", name=(m.group(1) or "").strip())
        return True
    if re.search(r"\b(?:limpa|limpe|libera|libere|esvazia)\s+(?:a |o )?(?:memoria ram|ram|memoria do (?:pc|windows|computador)|memoria)\b", clean) \
            and "da memoria" not in clean:
        tool("clean_memory")
        return True
    if re.search(r"\b(?:limpa|limpe|faz uma limpeza|faca uma limpeza)\s+(?:no |o |os )?(?:pc|computador|temporarios|arquivos temporarios)\b"
                 r"|\besvazia (?:a )?lixeira\b|\blimpeza do pc\b", clean):
        tool("cleanup")
        return True
    if re.search(r"\b(?:limpa|apaga)\s+(?:os )?downloads velhos\b|\bdownloads antigos\b", clean):
        tool("clean_old_downloads")
        return True
    if re.search(r"\bpor ?que (?:o (?:pc|computador) )?(?:ta|esta|tá) (?:tao )?(?:lento|travando)\b|\b(?:pc|computador|notebook) (?:ta|esta) (?:lento|travando)\b|\bo que (?:ta|esta) pesando\b", clean):
        tool("why_slow")
        return True
    m = re.search(r"\bvolume d[oa] (.+?)\s+(?:em|pra|para|no)\s+(\d{1,3})\b", clean)
    if m:
        tool("app_volume", app=m.group(1), percent=int(m.group(2)))
        return True
    m = re.match(r"^(?:o |a )?(?:volume d[oa] )?(.+?) mais (alto|baixo)$", clean)
    if m and not re.search(r"\b(?:som|volume)$", m.group(1)) and m.group(1) not in ("som", "volume", "fala", "voce"):
        tool("app_volume", app=m.group(1), delta=20 if m.group(2) == "alto" else -20)
        return True
    m = re.match(r"^(?:imprime|imprima|imprimir|manda imprimir)\s+(?:o |a )?(?:arquivo )?(.+)$", clean)
    if m:
        tool("print_file", path=number_ref(m.group(1)))
        return True
    m = re.match(r"^(?:cola|cole) o que eu copiei antes$|^(?:cola|cole) (?:o |a )?" + ORDINAL + r" (?:da area|do historico)", clean)
    if m:
        tool("clipboard_paste", index=ordinal_to_number(clean) if m.groups() and m.group(1) else 2)
        return True
    if re.search(r"\bhistorico da area de transferencia\b|\bo que eu copiei (?:hoje|antes|por ultimo)\??$", clean):
        tool("clipboard_list")
        return True
    m = re.match(r"^(?:organiza|organize|arruma|arrume)\s+(?:a pasta |a minha pasta |os |as |o |a |meus |minhas )?(.+?)(?:\s+por\s+(tipo|data))?$", clean)
    if m and (normalize(m.group(1)) in FOLDERS or " pasta " in f" {clean} " or re.search(r"[a-z]:[\\/]", m.group(1))):
        tool("organize_folder", folder=m.group(1), by=m.group(2) or "tipo")
        return True
    m = re.match(r"^(?:compacta|compacte|zipa|zipe)\s+(?:a pasta |o arquivo |o |a )?(.+)$", clean)
    if m:
        tool("compress", path=number_ref(m.group(1)))
        return True
    m = re.match(r"^(?:descompacta|descompacte|extrai|extraia|deszipa)\s+(?:o |a )?(?:arquivo )?(.+)$", clean)
    if m:
        tool("extract", path=number_ref(m.group(1)))
        return True
    if re.search(r"\bdesfaz (?:a ultima (?:acao|mudanca|coisa)|o que (?:voce|vc) fez|a organizacao|o renomear|a renomeacao)\b", clean):
        tool("undo_file")
        return True
    m = re.match(r"^(?:converte|converta|transforma|transforme)\s+(?:o |a |as |os )?(?:arquivo )?(.+?)\s+(?:para|pra|em)\s+(pdf|mp3|mp4|wav|jpg|png|gif|m4a)$", clean)
    if m:
        tool("convert_file", path=number_ref(m.group(1)), to=m.group(2))
        return True
    m = re.match(r"^(?:diminui|diminua|comprime|comprima) (?:o |a )?(?:arquivo )?(.+?)(?: para mandar| pra mandar)?(?: no zap| no whats(?:app)?)?$", clean)
    if m:
        tool("shrink_file", path=number_ref(m.group(1)))
        return True
    if re.search(r"\bgrava os ultimos\b|\bsalva o clipe\b|\bclipa (?:isso|ai)\b|\bgrava (?:esse|o) lance\b", clean):
        tool("game_clip")
        return True
    if re.search(r"\b(?:mostra|abre) (?:o )?(?:fps|game bar|xbox game bar)\b", clean):
        tool("game_bar")
        return True
    if re.search(r"\bsaude do (?:pc|computador)\b|\brelatorio de saude\b|\bcomo (?:ta|esta) (?:a saude do |o )(?:pc|computador)\b", clean):
        tool("health_report")
        return True
    if re.search(r"\b(?:o que|quais programas|que programas) (?:abre|abrem|inicia|iniciam) com o windows\b|\bprogramas da inicializacao\b", clean):
        tool("list_startup")
        return True
    if re.fullmatch(r"(?:salva|salve|desfaz|desfaca|refaz|refaca|nova aba|abre uma nova aba|reabre a aba|seleciona tudo|"
                    r"atualiza a pagina|recarrega a pagina|negrito|italico|sublinhado|salvar como|localiza|nova janela)", clean):
        key = {"desfaca": "desfaz", "refaca": "refaz", "abre uma nova aba": "nova aba", "salve": "salva",
               "atualiza a pagina": "atualiza", "recarrega a pagina": "atualiza", "localiza": "localizar"}.get(clean, clean)
        tool("app_shortcut", action=key)
        return True
    return False


def brain_router(text, clean):
    """Cérebro e conversa: personalidade, papo, ver a tela, traduzir, agente, microfone e vocabulário."""
    m = re.search(r"\b(?:fica|seja|fale|fala|responde|responda)\s+(?:mais\s+)?(serio|formal|engracado|divertido|curto|"
                  r"direto|resumido|detalhado|completo)\b|\bpersonalidade (normal|padrao|seria|engracada|curta)\b", clean)
    if m:
        word = m.group(1) or m.group(2)
        kind = {"formal": "serio", "seria": "serio", "engracado": "humor", "engracada": "humor", "divertido": "humor",
                "direto": "curto", "resumido": "curto", "curta": "curto", "completo": "detalhado",
                "padrao": "normal"}.get(word, word)
        tool("set_personality", style=kind)
        return True
    if re.search(r"\b(?:vamos|bora|quero) (?:conversar|bater (?:um )?papo|trocar uma ideia)\b|^modo papo$", clean):
        tool("chat_mode", on=True)
        return True
    m = re.search(r"\b(?:o que (?:e|eh|tem) (?:isso|isto|aqui)(?: na tela)?|o que (?:ta|esta) (?:aparecendo|escrito) na tela|"
                  r"qual (?:e |eh )?o erro(?: aqui| na tela)?|(?:olha|ve|veja|analisa) (?:a|minha) tela|le a tela)\b(.*)$", clean)
    if m:
        tool("look_screen", question=text)
        return True
    if re.search(r"\btraduz(?:a|ir)? (?:isso|o que (?:ta|esta) selecionado|o texto selecionado|a selecao)\b", clean):
        tool("translate_selection")
        return True
    if re.search(r"\btraduz(?:a|ir)? (?:a tela|o que (?:ta|esta) na tela|essa pagina|esta pagina)\b", clean):
        tool("look_screen", question="Traduza para o português o texto principal da tela.")
        return True
    m = re.match(r"^(?:modo agente|agente|faz sozinho|faca sozinho|executa sozinho)[:,]?\s+(.+)$", clean)
    if m:
        tool("agent_task", goal=_original(text, m.group(1)) or m.group(1))
        return True
    if re.search(r"\bcalibra(?:r)? (?:o )?microfone\b|\bajusta (?:o )?microfone\b", clean):
        tool("calibrate_mic")
        return True
    m = re.match(r"^(?:aprende|anota|guarda) (?:a palavra|o nome|essa palavra) (.+)$", clean)
    if m:
        tool("add_vocabulary", words=_original(text, m.group(1)))
        return True
    return False


SLIDES_RE = re.compile(
    r"^(?:faz|faca|fazer|cria|crie|monta|monte|prepara|prepare)\s+(?:um |uns |uma |o |os )?(?:slides?|apresentac\w+)"
    r"(?:\s+(?:sobre|de|do|da|dos|das)\s+(?P<tema>.+?))?"
    r"(?:\s*,?\s+com\s+(?P<n>\d{1,2})\s+slides?)?"
    r"(?:\s+(?:no|pelo|em)\s+(?P<onde>google slides|google|powerpoint|power point))?"
    r"(?:\s*,?\s+e\s+(?:manda|mande|envia|envie)\s+(?:pra|para|pro)\s+(?P<quem>.+?)(?:\s+no\s+(?:zap|whats ?app))?)?$")


def screen_router(text, clean):
    """WhatsApp (responder, resumo, áudios), navegador (abas, página, favoritos, retomar), celular e tela."""
    m = re.match(r"^(?:o )?meu (?:whats ?app|zap|numero(?: do (?:zap|whats ?app))?) (?:e|eh) (.+)$", clean)
    if m and len(re.sub(r"\D", "", m.group(1))) >= 10:
        tool("set_profile", key="meu_whatsapp", value=re.sub(r"\D", "", m.group(1)))
        return True
    m = SLIDES_RE.match(clean)
    if m and m.group("tema"):
        tema = m.group("tema")
        n = m.group("n")
        if not n:  # "sobre X com 8 slides" já foi; "8 slides sobre X" não
            n2 = re.search(r"\b(\d{1,2})\s+slides?\b", clean)
            n = n2.group(1) if n2 else 8
        tool("make_slides", topic=_original(text, tema) or tema, slides=int(n),
             where="google" if (m.group("onde") or "").startswith("google") else "",
             contact=(m.group("quem") or "").strip())
        return True
    m = re.search(r"\b(?:resume|resuma|faz um resumo d)[oe]? (?:esse |este |o )?video\b(?:.*?(https?://\S+))?", text, re.I) \
        if re.search(r"\bvideo\b", clean) else None
    if m:
        tool("summarize_video", url=m.group(1) or "")
        return True
    m = re.search(r"\bgrava (?:a )?tela(?: (?:por|durante) (\d+) (?:minutos?|min))?", clean)
    if m:
        tool("record_screen", minutes=int(m.group(1) or 1))
        return True
    m = re.match(r"^(?:responde|responda|responder)(?: (?:pra|para|a|o) (?:ultima|ultima mensagem|ele|ela))?"
                 r"(?: (?:que|dizendo|com))? (.+)$", clean)
    if m and not re.search(r"\b(?:e-?mail|comentario|instagram)\b", clean) and \
            not re.match(r"^responde (?:a |o |pra |para )(?!ultima|ele\b|ela\b)\w+ (?:que|dizendo)", clean):
        tool("whatsapp_reply", message=_original(text, m.group(1)) or m.group(1))
        return True
    if re.search(r"\b(?:resumo|resume|resuma)\b.*\b(?:zap|whats ?app|mensagens|nao lidas)\b|\bmensagens nao lidas\b", clean):
        tool("whatsapp_summary")
        return True
    m = re.search(r"\b(?:ouve|ouca|escuta|transcreve|transcreva|le|leia)\s+(?:os |o )?audios?\b(?:\s+d[aoe]\s+(.+?))?(?:\s+no (?:zap|whats ?app))?$", clean)
    if m:
        tool("whatsapp_audios", contact=(m.group(1) or "").strip())
        return True
    m = re.match(r"^(?:grava|grave|manda|mande) (?:um )?audio(?: de (\d+) segundos?)? (?:pra|para|pro) (?:o |a )?(.+?)(?: no (?:zap|whats ?app))?$", clean)
    if m:
        tool("whatsapp_send_audio", contact=m.group(2), seconds=int(m.group(1) or 10))
        return True
    m = re.match(r"^(?:fecha|feche) (?:as |a )?abas? d[oae] (.+)$", clean)
    if m:
        tool("close_tabs", word=m.group(1))
        return True
    m = re.match(r"^(?:volta|vai|muda) (?:para|pra|pro) (?:a )?aba d[oae] (.+)$", clean)
    if m:
        tool("switch_tab", word=m.group(1))
        return True
    if re.search(r"\b(?:quais|lista as|mostra as) abas\b", clean):
        tool("list_tabs")
        return True
    if re.search(r"\b(?:resume|resuma|faz um resumo d)[ae]? (?:essa |esta |a )?pagina\b", clean):
        tool("summarize_page")
        return True
    if re.search(r"\b(?:le|leia) (?:essa |esta |a )?pagina em voz alta\b", clean):
        tool("read_page_aloud")
        return True
    m = re.match(r"^(?:salva|salve|adiciona|coloca) (?:essa |esta |a )?pagina (?:nos|no|aos) favoritos(?: como (.+))?$", clean)
    if m:
        tool("favorite_add", name=m.group(1) or "")
        return True
    m = re.match(r"^(?:abre|abra) o favorito (.+)$", clean)
    if m:
        tool("favorite_open", name=m.group(1))
        return True
    if re.search(r"\b(?:quais|meus|lista os|mostra os) favoritos\b", clean):
        tool("favorite_list")
        return True
    if re.search(r"\b(?:continua|retoma|volta)\b.*\b(?:video|musica)\b.*\bde onde (?:parei|parou)\b", clean):
        tool("resume_video")
        return True
    m = re.match(r"^(?:manda|mande|envia|envie|passa) (?:o |a |esse |essa |este )?(?:arquivo |foto |pdf )?(.+?) (?:pro|para o|pra o|pra|para) (?:meu )?celular$", clean)
    if m:
        tool("send_to_phone", path=number_ref(m.group(1)))
        return True
    m = re.search(r"\b(?:tema|cor do reator|reator)\s+(?:para |em |no |de )?(azul|vermelho|dourado|ouro|homem de ferro)\b"
                  r"|\b(?:muda|troca) (?:o tema|a cor)(?: do reator)? (?:para|pro|pra) (azul|vermelho|dourado|ouro|homem de ferro)\b", clean)
    if m:
        tool("set_theme", name=m.group(1) or m.group(2))
        return True
    return False


def routine_router(text, clean):
    """Modos, não perturbe, VIP, Pomodoro, listas, água, contas, chuva, humor, contagem, integrações e autoteste."""
    if re.fullmatch(r"(?:sai|sair|saia|desliga|desativa|termina|encerra) (?:d[oe]sse |do |o )?modo(?: \w+)?|fim do modo|acabou a aula", clean):
        tool("exit_mode")
        return True
    m = re.match(r"^(?:ativa |ativar |liga |entra n[oa] |entrar n[oa] |coloca n[oa] )?(?:o )?modo (\w+)$", clean)
    if m and R.find_mode(m.group(1)):
        tool("enter_mode", name=m.group(1))
        return True
    if re.fullmatch(r"(?:vou dormir|vou deitar|indo dormir|hora de dormir|boa noite,? vou dormir)", clean) or \
            (clean in ("boa noite", f"boa noite {normalize(NAME)}") and (datetime.now().hour >= 21 or datetime.now().hour < 4)):
        tool("good_night")
        return True
    m = re.search(r"\bnao perturbe\b(.*)$", clean)
    if m and re.search(r"\b(?:desliga|desativa|tira|sai|sair|chega|acabou|fim)\b", clean):
        tool("dnd_off")
        return True
    if m:
        tool("dnd_on", until=m.group(1).strip())
        return True
    if re.fullmatch(r"(?:pode (?:me )?perturbar|pode avisar|volta (?:a|os) avisos?)", clean):
        tool("dnd_off")
        return True
    m = re.match(r"^(?:coloca |poe |marca )?(?:o |a )?(.+?) (?:e|como|nos|nas|na lista de) vips?$", clean) \
        or re.match(r"^(?:coloca|poe|marca) (?:o |a )?(.+?) como vip$", clean)
    if m and not m.group(1).startswith(("tira", "remove")):
        tool("set_vip", name=_original(text, m.group(1)), on=True)
        return True
    m = re.match(r"^(?:tira|remove) (?:o |a )?(.+?) d[oa]s? vips?$", clean)
    if m:
        tool("set_vip", name=m.group(1), on=False)
        return True
    m = re.search(r"\b(?:comeca|começa|inicia|liga|faz|faca|ativa)\s+(?:um )?pomodoro(?: de (\d+)(?: minutos?)?)?|^pomodoro(?: de (\d+))?$", clean)
    if m:
        tool("start_pomodoro", minutes=int(m.group(1) or m.group(2) or 25))
        return True
    if re.search(r"\b(?:para|parar|cancela|desliga|termina) (?:o )?pomodoro\b", clean):
        tool("stop_pomodoro")
        return True
    if re.search(r"\bquanto falta (?:do|no|pro) pomodoro\b|\bcomo (?:ta|esta) o pomodoro\b", clean):
        tool("pomodoro_status")
        return True
    m = re.match(r"^(?:anota|anote|coloca|coloque|poe|bota|adiciona|adicione|inclui|acrescenta)\s+(.+?)\s+na lista(?: de| do| da)?\s*(\w*)$", clean)
    if m:
        tool("list_add", list=m.group(2) or "compras", items=_original(text, m.group(1)))
        return True
    m = re.match(r"^(?:tarefa|nova tarefa|adiciona a tarefa|anota a tarefa)\s*:?\s+(.+?)(?:,? prioridade (alta|media|baixa|urgente))?$", clean)
    if m:
        tool("list_add", list="tarefas", items=_original(text, m.group(1)), priority=m.group(2) or "")
        return True
    m = re.match(r"^(?:risca|marca como feito|ja comprei|ja fiz|terminei|conclui)\s+(?:o |a |os |as )?(.+?)(?: da lista(?: de| do| da)? ?(\w*))?$", clean)
    if m and (" lista" in clean or clean.startswith(("ja comprei", "risca"))):
        tool("list_check", list=m.group(2) or ("compras" if "comprei" in clean else "tarefas" if "fiz" in clean or "terminei" in clean else "compras"), items=m.group(1))
        return True
    m = re.match(r"^(?:tira|remove|apaga)\s+(?:o |a |os |as )?(.+?) da lista(?: de| do| da)? ?(\w*)$", clean)
    if m:
        tool("list_remove", list=m.group(2) or "compras", items=m.group(1))
        return True
    m = re.match(r"^(?:limpa|apaga|zera|esvazia) a lista(?: de| do| da)? ?(\w*)$", clean)
    if m:
        tool("list_clear", list=m.group(1) or "compras")
        return True
    m = re.search(r"\b(?:mostra|le|leia|ver|ve|qual|o que tem na|como ta|como esta)\s+(?:a |minha )?lista(?: de| do| da)? ?(\w*)", clean) \
        or re.fullmatch(r"(?:minha )?lista(?: de| do| da)? ?(\w*)", clean) or re.search(r"\bminhas tarefas\b()", clean)
    if m:
        tool("list_show", list=(m.group(1) if m.groups() else "") or ("tarefas" if "tarefa" in clean else "compras"))
        return True
    m = re.search(r"\b(?:liga|ativa|comeca|quero)\s+(?:o |os )?lembretes? de (agua|postura|agua e postura)(?: a cada (\d+) (?:minutos?|min|horas?|h))?", clean)
    if m:
        every = int(m.group(2)) * (60 if m.group(2) and re.search(r"\d+ (?:horas?|h)\b", clean) else 1) if m.group(2) else 60
        tool("wellness_on", kind="ambos" if "e" in m.group(1).split() else m.group(1), minutes=every)
        return True
    if re.search(r"\b(?:desliga|para|tira)\s+(?:o |os )?lembretes? de (?:agua|postura)", clean):
        tool("wellness_off")
        return True
    m = re.match(r"^(?:a |o )?(?:conta|boleto|fatura) d[aoe]s? (.+?) vence (?:todo )?(?:dia )?(\d{1,2})(?:.*?(?:custa|de|valor|e)\s*(?:r\$ ?)?(\d+(?:[.,]\d{1,2})?))?", clean)
    if m:
        tool("add_bill", name=m.group(1), day=int(m.group(2)), value=m.group(3) or "")
        return True
    if re.search(r"\b(?:quais|minhas|as) contas\b|\bcontas (?:do mes|a pagar|que vencem)\b", clean):
        tool("list_bills")
        return True
    if re.search(r"\b(?:levo|preciso de|preciso levar|levar) (?:o )?guarda[- ]chuva\b|\bvai chover (?:mais tarde|daqui a pouco|hoje a tarde|hoje a noite)\b", clean):
        tool("rain_warning")
        return True
    m = re.search(r"\b(?:toca|coloca|poe|bota|quero|me ve)\s+(?:algo|alguma coisa|uma musica|umas musicas|musica|som)\s+(?:pra|para|de)\s+(\w+(?: \w+)?)", clean) \
        or re.search(r"\b(?:to|estou|tô) (triste|animado|cansado|estressado|feliz)\b.*\b(?:toca|coloca|musica)", clean)
    if m:
        tool("play_mood", mood=m.group(1))
        return True
    m = re.search(r"\bquantos dias (?:faltam |falta )?(?:para|pra|ate) (?:a |o |as |os |minha |meu )?(.+?)\??$", clean)
    if m:
        tool("days_until", name=m.group(1))
        return True
    m = re.match(r"^(?:conta os dias|contagem regressiva|faz uma contagem) (?:para|pra|ate) (?:a |o )?(.+?) (?:dia|em|no dia|que e dia) (.+)$", clean)
    if m:
        when = A.birthday_of(m.group(2))
        if when:
            d = datetime(datetime.now().year, when[1], when[0]).date()
            if d < datetime.now().date():
                d = d.replace(year=d.year + 1)
            tool("add_countdown", name=_original(text, m.group(1)), day=d.isoformat())
            return True
    # integrações
    if re.search(r"\bquais integracoes\b|\bintegracoes (?:eu tenho|ligadas)\b|\bo que (?:falta|ta faltando) (?:ligar|configurar)\b", clean):
        tool("integrations")
        return True
    if re.search(r"\b(?:conecta|liga|conectar) (?:o )?(?:google|gmail|agenda do google)\b", clean):
        tool("google_connect")
        return True
    if re.search(r"\b(?:tem |tenho |quais |le |leia |mostra |ver )?(?:os )?(?:meus )?e-?mails?(?: novos?| importantes?)?\??$|\bresumo do e-?mail\b|\bcaixa de entrada\b", clean) \
            and not re.search(r"\b(?:manda|envia|escreve|responde)\b", clean):
        tool("gmail_list")
        return True
    m = re.match(r"^(?:le|leia|abre) o e-?mail (?:numero )?(\d+|" + ORDINAL + r")$", clean)
    if m:
        tool("gmail_read", index=ordinal_to_number(m.group(1)) or 1)
        return True
    m = re.search(r"\b(?:o que (?:tenho|tem)|minha agenda|meus compromissos|meus eventos)\b.*?\b(hoje|amanha)\b|\b(?:minha|a) agenda(?: de hoje)?\??$", clean)
    if m and ("agenda" in clean or "compromisso" in clean or "evento" in clean):
        tool("calendar_events", day=(m.group(1) if m.groups() and m.group(1) else "hoje"))
        return True
    m = re.match(r"^(liga|desliga|acende|apaga|abre|fecha) (?:a |o |as |os )?((?:luz|luzes|lampada|tomada|ventilador|ar condicionado|abajur|cortina|persiana)\b.*)$", clean)
    if m and I.home_ready():
        tool("home_control", device=m.group(2), action="ligar" if m.group(1) in ("liga", "acende", "abre") else "desligar")
        return True
    m = re.search(r"\b(?:vigia|acompanha|monitora|fica de olho n)o? (?:o )?preco (?:d[eoa] )?(?:(.+?) )?(https?://\S+)", text, re.I)
    if m:
        tool("watch_price", url=m.group(2), name=(m.group(1) or "").strip())
        return True
    if re.search(r"\bquais precos\b|\bprecos? (?:que (?:voce|vc) (?:ta|esta) vigiando|vigiados)\b", clean):
        tool("list_prices")
        return True
    m = I.TRACK_CODE.search(text)
    if m and re.search(r"\b(?:rastreia|rastrear|rastreio|encomenda|pacote|correios|cade)\b", clean):
        tool("track_parcel", code=m.group(1))
        return True
    # o Bolha se cuidando
    if re.search(r"\b(?:autoteste|auto teste|diagnostico|testa (?:os|seus) sistemas|como (?:estao|tao) (?:os|seus) sistemas)\b", clean):
        tool("self_test")
        return True
    if re.search(r"\b(?:se atualiza|atualiza (?:o )?(?:bolha|jarvis|voce)|tem atualizacao (?:do bolha|sua|pra voce)|atualiza seu codigo)\b", clean):
        tool("update_bolha")
        return True
    return False


def docs_router(text, clean):
    """Busca dentro dos arquivos, ler em voz alta, ditado, planilhas, fotos e downloads."""
    if DOC.reader["partes"]:
        m = re.fullmatch(r"(?:continua|continue|continuar|proxima parte|segue|pode continuar)(?: lendo| a leitura)?|"
                         r"(volta|volte) (?:uma parte|um pouco|a parte anterior)|(repete|repita)(?: essa parte)?|"
                         r"(?:le|leia|vai para) a parte (\d+)|(para|pare|chega) de ler", clean)
        if m and (DOC.reader.get("ativo") or "lendo" in clean or "leitura" in clean or "parte" in clean):
            tool("reading_control", action=clean)
            if re.search(r"\b(?:para|pare|chega) de ler\b", clean):
                DOC.reader["ativo"] = False
            return True
    m = re.match(r"^(?:le|leia|ler)\s+(?:o |a )?(?:arquivo |pdf |documento )?(.+?)\s+em voz alta$", clean) \
        or re.match(r"^(?:le|leia) em voz alta (?:o |a )?(?:arquivo |pdf |documento )?(.+)$", clean)
    if m:
        tool("read_aloud", path=number_ref(m.group(1)))
        return True
    m = re.match(r"^(?:procura|procure|busca|acha|ache|encontra)\s+(?:um |o |a |os |as )?(?:arquivos?|documentos?|pdfs?)\s+"
                 r"(?:que (?:fala|falam|tem|tenha|tenham|menciona|mencionam) (?:de |sobre |em )?|sobre |com (?:o texto |a palavra )?)(.+)$", clean) \
        or re.match(r"^(?:procura|busca)\s+dentro dos arquivos\s+(?:por |o texto )?(.+)$", clean)
    if m:
        tool("search_content", query=m.group(1).strip(" ?."))
        return True
    m = re.match(r"^(?:dita|ditar|quero ditar|vou ditar|comeca um ditado|abre um ditado|faz um ditado)(?: uma| um)?(?: documento| texto| carta| arquivo)?(?: chamad[oa]| com o nome)? ?(.*)$", clean)
    if m:
        tool("start_dictation", name=_original(text, m.group(1)) if m.group(1) else "")
        return True
    m = re.search(r"\bsoma (?:a coluna|os valores da coluna|a coluna de) (.+?)(?: d[aoe] (?:planilha |arquivo )?(.+))?$", clean)
    if m:
        tool("sum_column", path=number_ref(m.group(2) or "1"), column=m.group(1))
        return True
    m = re.search(r"\bfotos (?:de|do|da) ((?:janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|mes passado|este mes|esse mes|20\d\d)(?: de 20\d\d)?)\b", clean)
    if m:
        tool("photos_from", when=m.group(1))
        return True
    if re.search(r"\b(?:ultimo|ultima) (?:arquivo |coisa |download )?(?:que (?:eu )?)?baixad[oa]\b|\bo que (?:eu )?baixei por ultimo\b|\bultimo download\b", clean):
        tool("last_download", open=bool(re.search(r"\b(?:abre|abra|abrir)\b", clean)))
        return True
    m = re.match(r"^(?:faz|faca|fazer) (?:o |um )?backup da pasta (.+?)(?: (?:no|na|para o|para a|pro|pra) (.+))?$", clean)
    if m:
        tool("backup_folder", src=m.group(1), dest=m.group(2) or "")
        return True
    return False


def skills_router(text, clean):
    taught = H.parse_teach(clean_prefix(text))
    if taught:
        tool("teach_skill", trigger=taught[0], todo=taught[1])
        return True
    if re.search(r"\b(?:quais|lista as|mostra as|lista de) (?:habilidades|skills)\b|\bque habilidades\b", clean):
        tool("list_skills")
        return True
    m = re.search(r"\bimporta(?:r)? (?:a |uma )?(?:habilidade|skill)\s+(https://\S+)", text, re.I)
    if m:
        tool("import_skill", url=m.group(1))
        return True
    m = re.match(r"^(aprova|apaga|remove|exclui)\s+a\s+(?:habilidade|skill)\s+(.+)$", clean)
    if m:
        tool("approve_skill" if m.group(1) == "aprova" else "remove_skill", name=m.group(2).strip(" .!?"))
        return True
    return False


def _original(text, plain):
    """O pedaço do texto original (com maiúsculas e acentos) que corresponde a um trecho normalizado."""
    words = str(text).split()
    want = plain.split()
    for i in range(len(words) - len(want) + 1):
        if normalize(" ".join(words[i:i + len(want)])).strip(" ,.!?") == plain:
            return " ".join(words[i:i + len(want)]).strip(" ,.!?")
    return plain.title()


def memory_panel():
    """Painel da memória (34): tudo o que ele sabe, com um botão para apagar cada coisa."""
    try:
        items = A.panel_items(M.load())
    except Exception as e:
        print(f"Jarvis > Não consegui ler a memória: {e}")
        return False
    if not items:
        print("Jarvis > Ainda não sei nada sobre o senhor.")
        return True
    U.card("Memória", json.dumps({"itens": items[:60]}, ensure_ascii=False), 60000)
    print(f"Jarvis > Sei {len(items)} coisas. Estão na tela; toque no × para eu esquecer.")
    return True


# ========================= IA COMO FALLBACK JSON =========================

# ========================= CATÁLOGO DE FERRAMENTAS =========================
# Fonte única do que o Jarvis sabe fazer: gera o prompt do Qwen, a tela de ajuda
# e a execução das ações. Ferramenta nova = uma entrada nova aqui.

FOLDERS = {  # pastas de verdade (o OneDrive costuma levar a Área de Trabalho e os Documentos)
    "downloads": DOWNLOADS,
    "documentos": DOCUMENTS,
    "desktop": DESKTOP,
    "area de trabalho": DESKTOP,
    "imagens": PICTURES,
    "fotos": PICTURES,
    "musicas": MUSIC,
    "videos": VIDEOS,
    "prints": SCREENSHOT_DIR,
    "jarvis": Path(r"G:\Jarvis"),
}


def open_folder(name):
    key = normalize(name)
    folder = FOLDERS.get(key) or Path(os.path.expandvars(str(name))).expanduser()
    if not folder.is_dir():
        print(f"Jarvis > Pasta não encontrada: {name}")
        return False
    os.startfile(str(folder))
    print(f"Jarvis > Pasta aberta: {folder}")
    return True


def open_url(url):
    url = str(url).strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    if B.available():
        try:
            return B.open_url(url)
        except Exception as e:
            _browser_failed(e)
    webbrowser.open(url)
    print(f"Jarvis > Abrindo {url}")
    return True


_youtube_outside = False  # o player do YouTube deu erro no navegador do Jarvis: usa o navegador padrão


def youtube_outside():
    return _youtube_outside or os.environ.get("JARVIS_YOUTUBE", "").strip().lower() in ("fora", "padrao", "padrão")


def play_youtube(query):
    """Com o Playwright, clica no vídeo de verdade na aba do Jarvis; sem ele, o jeito antigo.
    Se o YouTube der "Algo deu errado" no navegador do Jarvis, toca no navegador padrão (e continua lá)."""
    global _youtube_outside
    if B.available() and not youtube_outside():
        try:
            result = B.play_youtube(query)
            if result == B.PLAYER_ERROR:
                _youtube_outside = True
                print("Jarvis > (o YouTube deu erro no meu navegador; vou usar o seu navegador para vídeos)")
                return _show_playing(F.play_youtube(query) and f"Tocando: {query}")
            if result is False:  # a página de busca mudou ou demorou: abre o primeiro vídeo pelo link
                url = F.youtube_first_video(query)
                if url:
                    B.open_url(url)
                    print(f"Jarvis > Tocando {query}.")
                    result = f"Tocando: {query}"
            return _show_playing(result)
        except Exception as e:
            _browser_failed(e)
    return F.play_youtube(query)


def _show_playing(result):
    if isinstance(result, str) and result.startswith("Tocando: "):
        U.card("Tocando agora", result[len("Tocando: "):])
    return result


def youtube_control(action):
    if normalize(action) in ("pausar", "pause", "parar") and not youtube_outside():
        remember_video()  # 92: guarda onde parou
    if not youtube_outside() and B.on_youtube():
        try:
            return B.youtube_control(action, normalize)
        except Exception as e:
            _browser_failed(e)
    return F.youtube_control(action)


def tell_time():
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    now = datetime.now()
    print(f"Jarvis > Agora são {now:%H:%M} de {dias[now.weekday()]}, {now:%d/%m/%Y}.")
    return True


def resolve_path(ref):
    """'2' ou 2 = resultado 2 da última busca; 'ele'/'esse' = o primeiro; senão é caminho."""
    text = str(ref).strip()
    if re.fullmatch(r"\d{1,2}", text) and last_results:
        i = int(text)
        if 1 <= i <= len(last_results):
            return Path(last_results[i - 1])
    if normalize(text) in {"", "ele", "ela", "esse", "essa", "isso", "o arquivo"} and last_results:
        return Path(last_results[0])
    n = ordinal_to_number(text) if last_results and re.fullmatch(rf"(?:o |a )?{ORDINAL}", normalize(text)) else None
    if n and 1 <= n <= len(last_results):
        return Path(last_results[n - 1])
    return Path(os.path.expandvars(text)).expanduser()


YES_WORDS = {"s", "sim", "pode", "confirmo", "confirma", "y", "yes", "isso", "manda", "envia", "claro", "ok",
             "okay", "beleza", "bora", "positivo", "certo", "exato", "fechado"}
NO_WORDS = {"n", "nao", "no", "cancela", "cancelar", "cancele", "negativo", "nunca"}
commands = queue.Queue()  # (origem, texto) vindos do teclado e da voz; um só lugar executa tudo
queue_mode = False  # ligado no main(); nos testes a confirmação usa input() direto
listener = None  # voz.Listener quando a voz está ligada
voice_out = False  # fala as respostas em voz alta (ligado no run() se o edge-tts estiver instalado)
origin = ""  # de onde veio o pedido que está sendo feito agora: "voz", "teclado", "janela", "celular"...


def answer_kind(answer):
    """True = sim ("Sim, senhor.", "pode mandar"), False = não, None = não é resposta (outro pedido)."""
    words = re.findall(r"\w+", normalize(answer))
    if not words:
        return None
    if any(w in NO_WORDS for w in words):
        return False
    return True if words[0] in YES_WORDS else None


def is_yes(answer):
    return answer_kind(answer) is True


def confirm(question):
    return ask(question, "Confirmar", classify=answer_kind, hint=" (sim ou não)", typed=" (s/n)") is True


def ask(question, card_title="Pergunta", card_text=None, classify=None, hint="", typed=""):
    """Pergunta e espera a resposta (falada, digitada, no botão ou no celular) por até 60 s.
    classify(texto) -> valor, ou None se aquilo não é resposta (outro pedido). Devolve o valor ou None."""
    classify = classify or (lambda t: t.strip() or None)
    if not queue_mode:
        try:
            answer = input(f"Jarvis > {question}{typed} ")
        except (EOFError, KeyboardInterrupt):
            return None
        return classify(answer)
    print(f"Jarvis > {question}{typed}")
    U.speech(question + hint)
    U.card(card_title, card_text if card_text is not None else question)
    speak(question)
    set_state("parado")
    if listener is not None and origin != "celular":  # do celular, a resposta vem de lá (o microfone do PC não)
        listener.ask_answer()
    deadline, later, relistens = time.time() + 60, [], 0
    try:
        while (left := deadline - time.time()) > 0:
            try:
                source, answer = commands.get(timeout=left)
            except queue.Empty:
                break
            answer = (answer or "").strip()
            if source in ("lembrete", "agendado", "despertador", "aviso"):  # avisa/faz depois; não é a resposta
                later.append((source, answer))
                continue
            if not answer:  # o microfone não ouviu nada: ainda dá para digitar ou dizer "Jarvis, sim"
                continue
            kind = classify(answer)
            if kind is None and source == "voz":
                # pela voz, ruído vira frase solta ("Obrigado."): não cancela, escuta de novo
                if listener is not None and origin != "celular" and (relistens := relistens + 1) <= 2:
                    listener.ask_answer()
                continue
            if kind is None:  # outro pedido no meio: cancela este e faz o novo em seguida
                later.append((source, answer))
                set_state("pensando")  # fecha o card da pergunta
                return None
            set_state("pensando")  # respondeu: o card sai da tela na hora
            return kind
        return None
    finally:
        for item in later:
            commands.put(item)


def confirm_danger(question):
    """Ações perigosas (apagar, desinstalar): o "sim" e, se o senhor configurou, a senha falada (96)."""
    if not confirm(question):
        return False
    secret = os.environ.get("BOLHA_SENHA_FALADA", "").strip()
    if not secret:
        return True
    said = ask("Diga a senha das ações perigosas, senhor.", "Senha", "Diga a senha (ela não aparece na tela)",
               classify=lambda t: t.strip() or None)
    if said and normalize(secret) in normalize(said):
        return True
    print("Jarvis > Senha errada. Não fiz, senhor.")
    return False


def choose(question, options):
    """Pergunta com opções num card ("qual dos dois, senhor?"). Devolve a opção escolhida ou None (18)."""
    options = [str(o).strip() for o in options if str(o).strip()][:8]
    if not options:
        return None
    if len(options) == 1:
        return options[0]

    def pick(text):
        t = normalize(text)
        n = ordinal_to_number(t) if re.fullmatch(rf"(?:o |a )?(?:{ORDINAL}|opcao \d+)", t) or t.isdigit() else None
        if n is None and (m := re.search(r"\b(\d)\b", t)):
            n = int(m.group(1))
        if n and 1 <= n <= len(options):
            return options[n - 1]
        i = M_best(t, options)
        return options[i] if i is not None else None

    text = json.dumps({"pergunta": question, "opcoes": options}, ensure_ascii=False)
    said = " ".join(f"{i}: {o}." for i, o in enumerate(options, 1))
    return ask(f"{question} {said}", "Escolha", text, classify=pick)


def M_best(text, options):
    import difflib
    best, score = None, 0.0
    for i, o in enumerate(options):
        on = normalize(o)
        s = 1.0 if on in text or text in on else difflib.SequenceMatcher(None, text, on).ratio()
        if s > score:
            best, score = i, s
    return best if score >= 0.6 else None


def ask_choice(question, options):
    """Ferramenta da IA: pergunta com opções; o resultado volta para ela decidir."""
    if isinstance(options, str):
        options = [o for o in re.split(r"\s*[;|\n]\s*", options) if o]
    picked = choose(question, options or [])
    if picked is None:
        print("Jarvis > Ninguém escolheu.")
        return False
    print(f"Jarvis > O senhor escolheu: {picked}")
    return picked


def summarize_file(ref):
    path = resolve_path(ref)
    text = F.read_file(path, show_chars=0) if path.is_file() else False
    if not text:
        if not path.is_file():
            print(f"Jarvis > Arquivo não encontrado: {path}")
        return False
    print(f"Jarvis > Resumindo {path.name}...")
    system = "Resuma o texto em português do Brasil, em até 6 tópicos curtos."
    summary = None
    if N.available():  # o Gemini aguenta textos bem maiores
        try:
            summary = N.generate(system, text[:60000], max_tokens=8192, temperature=0.2)
        except Exception as e:
            print(f"Jarvis > (Gemini falhou: {e})")
    if not summary:
        try:  # o Groq grátis recusa pedidos muito grandes (HTTP 413): manda um pedaço menor
            summary = think(system, text[:12000], skip=("Gemini",) if N.available() else (),
                            json_mode=False, num_predict=600, temperature=0.2)
        except Exception as e:
            print(f"Jarvis > Não consegui resumir: {e}")
            return False
    print(summary.strip())
    return True


def show_help():
    print("Jarvis > Eu sei fazer isto (fale do seu jeito, são só exemplos):")
    for group in TOOL_GROUPS:
        tools = [t for t in TOOLS if t["group"] == group]
        print(f"\n  {group.upper()}")
        for t in tools:
            print(f"    - {t['desc']}: \"{t['examples'][0]}\"")
    print("\n  Frases que eu não reconheço vão para a IA (Gemini ou Groq), que escolhe as ações acima.")
    return True


TOOL_GROUPS = ["mãos", "jogos", "integrações", "som", "programas e sites", "arquivos e pastas", "ler e resumir", "mídia", "navegador", "memória", "janelas e teclado",
               "sistema", "energia", "informação", "rotinas", "whatsapp", "instagram", "aprendizado", "habilidades"]

TOOLS = [
    {"name": "set_volume", "args": '{"percent":0-100}', "group": "som",
     "desc": "deixar o volume num valor", "examples": ["coloca o volume em 30", "deixa na metade"],
     "run": lambda a: set_volume(a.get("percent", 50))},
    {"name": "change_volume", "args": '{"delta":-100..100}', "group": "som",
     "desc": "aumentar ou abaixar o volume", "examples": ["aumenta o volume em 10", "abaixa um pouco o som"],
     "run": lambda a: change_volume(int(a.get("delta", 10)))},
    {"name": "get_volume", "args": "{}", "group": "som",
     "desc": "dizer o volume atual", "examples": ["qual o volume"],
     "run": lambda a: get_volume()},
    {"name": "mute_audio", "args": '{"mute":true/false}', "group": "som",
     "desc": "mutar ou desmutar", "examples": ["muta o som", "desmuta"],
     "run": lambda a: mute_audio(a.get("mute", True))},
    {"name": "open_target", "args": '{"target":"nome"}', "group": "programas e sites",
     "desc": "abrir programa, jogo ou site", "examples": ["abre o omori", "abre o chrome", "abre youtube"],
     "run": lambda a: open_target(a.get("target", ""))},
    {"name": "open_url", "args": '{"url":"endereço"}', "group": "programas e sites",
     "desc": "abrir um endereço de site", "examples": ["abre o site g1.globo.com"],
     "run": lambda a: open_url(a.get("url", ""))},
    {"name": "play_youtube", "args": '{"query":"música ou vídeo"}', "group": "mídia",
     "desc": "tocar música/vídeo no YouTube direto (reusa a mesma aba)", "examples": ["toca a música evidências"],
     "run": lambda a: play_youtube(a.get("query", ""))},
    {"name": "youtube_control", "args": '{"action":"pausar|proximo|anterior|tela cheia|avancar|voltar|mudo|legenda"}',
     "group": "mídia", "desc": "controlar o vídeo do YouTube aberto", "examples": ["coloca em tela cheia", "avança o vídeo"],
     "run": lambda a: youtube_control(a.get("action", ""))},
    {"name": "search_web", "args": '{"query":"texto","site":"google|youtube"}', "group": "programas e sites",
     "desc": "pesquisar no Google ou ver resultados do YouTube", "examples": ["pesquisa receita de bolo", "procura no youtube lofi"],
     "run": lambda a: search_web(a.get("query", ""), a.get("site", "google"))},
    {"name": "search_files", "args": '{"query":"nome ou extensão"}', "group": "arquivos e pastas",
     "desc": "procurar arquivo ou pasta em todos os discos do PC", "examples": ["procura o arquivo omori", "procura um pdf"],
     "run": lambda a: search_files(a.get("query", ""))},
    {"name": "open_search_result", "args": '{"index":1}', "group": "arquivos e pastas",
     "desc": "abrir um resultado da última busca", "examples": ["abre o segundo", "2"],
     "run": lambda a: open_search_result(a.get("index", 1))},
    {"name": "show_search_result", "args": '{"index":1}', "group": "arquivos e pastas",
     "desc": "mostrar um resultado no Explorer", "examples": ["mostra o primeiro na pasta"],
     "run": lambda a: show_search_result(a.get("index", 1))},
    {"name": "open_folder", "args": '{"name":"downloads|documentos|desktop|imagens|musicas|videos|prints|jarvis|caminho"}',
     "group": "arquivos e pastas",
     "desc": "abrir uma pasta", "examples": ["abre a pasta downloads"],
     "run": lambda a: open_folder(a.get("name", ""))},
    {"name": "list_folder", "args": '{"path":"caminho"}', "group": "arquivos e pastas",
     "desc": "listar o que tem numa pasta", "examples": ["o que tem em G:\\Jarvis"],
     "run": lambda a: list_folder(a.get("path", ""))},
    {"name": "media_control", "args": '{"action":"play|pause|next|previous|stop"}', "group": "mídia",
     "desc": "tocar, pausar, pular música", "examples": ["pausa a música", "próxima música"],
     "run": lambda a: media_control(a.get("action", ""))},
    {"name": "window_control", "args": '{"action":"minimizar|maximizar|fechar|trocar|desktop|menu"}', "group": "janelas e teclado",
     "desc": "minimizar, maximizar, fechar ou trocar janela", "examples": ["minimiza", "fecha essa janela"],
     "run": lambda a: window_control(a.get("action", ""))},
    {"name": "take_screenshot", "args": "{}", "group": "sistema",
     "desc": "tirar print da tela", "examples": ["tira um print"],
     "run": lambda a: take_screenshot()},
    {"name": "system_info", "args": "{}", "group": "sistema",
     "desc": "mostrar RAM, CPU e espaço em disco", "examples": ["quanta ram tenho"],
     "run": lambda a: system_info()},
    {"name": "tell_time", "args": "{}", "group": "sistema",
     "desc": "dizer hora e data", "examples": ["que horas são"],
     "run": lambda a: tell_time()},
    # ---- sistema
    {"name": "battery_status", "args": "{}", "group": "sistema",
     "desc": "dizer a bateria", "examples": ["quanto de bateria tem"],
     "run": lambda a: F.battery_status()},
    {"name": "list_processes", "args": "{}", "group": "sistema",
     "desc": "mostrar o que está pesando no PC", "examples": ["o que tá pesando o pc"],
     "run": lambda a: F.list_processes()},
    {"name": "close_app", "args": '{"name":"programa"}', "group": "programas e sites",
     "desc": "fechar um programa", "examples": ["fecha o chrome"],
     "run": lambda a: F.close_app(a.get("name", ""))},
    {"name": "open_settings", "args": '{"page":"bluetooth|wifi|tela|som|atualizacao|apps|energia|bateria|..."}',
     "group": "sistema", "desc": "abrir uma tela das Configurações", "examples": ["abre as configurações de bluetooth"],
     "run": lambda a: F.open_settings(a.get("page", ""))},
    {"name": "set_brightness", "args": '{"percent":0-100}', "group": "sistema",
     "desc": "mudar o brilho da tela", "examples": ["brilho em 70"],
     "run": lambda a: F.set_brightness(a.get("percent", 50))},
    {"name": "network_info", "args": "{}", "group": "sistema",
     "desc": "ver IP, Wi-Fi e se tem internet", "examples": ["tô com internet?"],
     "run": lambda a: F.network_info()},
    # ---- energia
    {"name": "power_action", "args": '{"action":"bloquear|suspender|desligar|reiniciar|cancelar","minutes":1}',
     "group": "energia", "desc": "bloquear, suspender, desligar ou reiniciar (com tempo)",
     "examples": ["desliga o pc em 30 minutos", "bloqueia o pc", "cancela o desligamento"],
     "run": lambda a: F.power_action(a.get("action", ""), a.get("minutes", 1))},
    # ---- informação
    {"name": "weather", "args": '{"city":"cidade"}', "group": "informação",
     "desc": "ver o clima de agora", "examples": ["clima em São Paulo"],
     "run": lambda a: F.weather(a.get("city") or M.load()["perfil"].get("cidade", ""))},
    {"name": "calculate", "args": '{"expression":"conta"}', "group": "informação",
     "desc": "fazer contas", "examples": ["quanto é 15% de 320", "calcula 12 vezes 7"],
     "run": lambda a: F.calculate(a.get("expression", ""))},
    {"name": "start_timer", "args": '{"minutes":5,"message":"texto"}', "group": "informação",
     "desc": "timer e lembrete", "examples": ["me lembra em 10 minutos de tirar o bolo"],
     "run": lambda a: F.start_timer(a.get("minutes", 5), a.get("message", "Tempo esgotado!"))},
    {"name": "cancel_timers", "args": "{}", "group": "informação",
     "desc": "cancelar os timers", "examples": ["cancela os timers"],
     "run": lambda a: F.cancel_timers()},
    # ---- arquivos
    {"name": "read_file", "args": '{"path":"caminho ou número do resultado"}', "group": "ler e resumir",
     "desc": "ler TXT, PDF ou DOCX", "examples": ["lê o primeiro", "lê o arquivo 2"],
     "run": lambda a: F.read_file(resolve_path(a.get("path", "1")))},
    {"name": "summarize_file", "args": '{"path":"caminho ou número do resultado"}', "group": "ler e resumir",
     "desc": "resumir um documento com a IA", "examples": ["resume o primeiro"],
     "run": lambda a: summarize_file(a.get("path", "1"))},
    {"name": "file_info", "args": '{"path":"caminho ou número"}', "group": "arquivos e pastas",
     "desc": "tamanho e data de um arquivo", "examples": ["qual o tamanho do primeiro"],
     "run": lambda a: F.file_info(resolve_path(a.get("path", "1")))},
    {"name": "create_folder", "args": '{"path":"caminho"}', "group": "arquivos e pastas",
     "desc": "criar pasta", "examples": ["cria a pasta G:\\Jarvis\\projetos"],
     "run": lambda a: F.create_folder(a.get("path", ""))},
    {"name": "copy_item", "args": '{"src":"caminho ou número","dest":"pasta"}', "group": "arquivos e pastas",
     "desc": "copiar arquivo ou pasta", "examples": ["copia o primeiro para G:\\backup"],
     "run": lambda a: F.copy_item(resolve_path(a.get("src", "1")), a.get("dest", ""))},
    {"name": "move_item", "args": '{"src":"caminho ou número","dest":"pasta"}', "group": "arquivos e pastas",
     "desc": "mover arquivo ou pasta", "examples": ["move o segundo para documentos"],
     "run": lambda a: F.move_item(resolve_path(a.get("src", "1")), FOLDERS.get(normalize(a.get("dest", "")), a.get("dest", "")))},
    {"name": "rename_item", "args": '{"src":"caminho ou número","new_name":"novo nome"}', "group": "arquivos e pastas",
     "desc": "renomear", "examples": ["renomeia o primeiro para contrato final"],
     "run": lambda a: F.rename_item(resolve_path(a.get("src", "1")), a.get("new_name", ""))},
    {"name": "delete_item", "args": '{"path":"caminho ou número"}', "group": "arquivos e pastas",
     "desc": "mandar para a Lixeira (sempre pergunta antes)", "examples": ["apaga o terceiro"],
     "run": lambda a: F.send_to_recycle_bin(resolve_path(a.get("path", "")), confirm_danger)},
    # ---- teclado e janelas
    {"name": "type_text", "args": '{"text":"texto"}', "group": "janelas e teclado",
     "desc": "digitar um texto no programa da frente", "examples": ["digita bom dia a todos"],
     "run": lambda a: F.type_text(a.get("text", ""))},
    {"name": "press_keys", "args": '{"keys":"ctrl+c"}', "group": "janelas e teclado",
     "desc": "apertar teclas e atalhos", "examples": ["aperta ctrl+s"],
     "run": lambda a: F.press_keys(a.get("keys", ""))},
    {"name": "read_clipboard", "args": "{}", "group": "janelas e teclado",
     "desc": "mostrar o que está copiado", "examples": ["o que eu copiei"],
     "run": lambda a: F.read_clipboard()},
    {"name": "focus_window", "args": '{"title":"parte do título"}', "group": "janelas e teclado",
     "desc": "trazer uma janela para a frente", "examples": ["vai para o chrome"],
     "run": lambda a: F.focus_window(a.get("title", ""))},
    {"name": "list_windows", "args": "{}", "group": "janelas e teclado",
     "desc": "listar janelas abertas", "examples": ["quais janelas estão abertas"],
     "run": lambda a: F.list_windows()},
    # ---- navegador do Jarvis (a IA vê o resultado e decide o próximo passo)
    {"name": "research", "args": '{"query":"busca curta só com as palavras-chave (ex.: eleições 2026 segundo turno)"}', "group": "informação",
     "desc": "responder perguntas de fatos atuais (notícias, eleição, placar, cotação, quem ganhou) pesquisando na "
             "internet e mostrando o resultado numa janela",
     "examples": ["como está a eleição", "quem ganhou o jogo ontem", "quanto está o dólar", "o que aconteceu com a Petrobras"],
     "run": lambda a: research(_research_query(a))},
    {"name": "web_search", "args": '{"query":"texto"}', "group": "navegador",
     "desc": "pesquisar no Google e LER os resultados (para escolher, comparar, responder)",
     "examples": ["pesquisa a melhor receita de bolo de cenoura"],
     "run": lambda a: web_search(a.get("query", ""))},
    {"name": "web_read", "args": "{}", "group": "navegador",
     "desc": "ler o texto da página aberta no navegador do Jarvis", "examples": ["lê essa página"],
     "run": lambda a: B.read_page()},
    {"name": "web_click", "args": '{"target":"texto do link/botão ou número do resultado"}', "group": "navegador",
     "desc": "clicar num link/botão ou abrir o resultado N da pesquisa", "examples": ["abre o segundo resultado"],
     "run": lambda a: B.click(a.get("target", ""))},
    {"name": "web_fill", "args": '{"field":"nome do campo (ou vazio)","text":"texto","enter":true}', "group": "navegador",
     "desc": "escrever num campo da página", "examples": ["escreve meu email no campo de login"],
     "run": lambda a: B.fill(a.get("field", ""), a.get("text", ""), bool(a.get("enter")))},
    {"name": "web_key", "args": '{"key":"Enter|Escape|PageDown|..."}', "group": "navegador",
     "desc": "apertar uma tecla na página", "examples": ["desce a página"],
     "run": lambda a: B.press(a.get("key", "Enter"))},
    {"name": "spotify_play", "args": '{"query":"música"}', "group": "navegador",
     "desc": "abrir uma música no app do Spotify", "examples": ["toca evidências no spotify"],
     "run": lambda a: F.spotify_play(a.get("query", ""))},
    {"name": "instagram_status", "args": "{}", "group": "instagram",
     "desc": "ver o perfil do Instagram (seguidores) e os últimos posts com curtidas e comentários",
     "examples": ["como tá meu instagram", "quantos seguidores eu tenho"],
     "run": lambda a: ig_status()},
    {"name": "instagram_comments", "args": '{"post":1}', "group": "instagram",
     "desc": "ler os comentários de um post (1 = o mais recente)", "examples": ["lê os comentários do meu último post"],
     "run": lambda a: ig_comments(a.get("post", 1))},
    {"name": "instagram_reply", "args": '{"comment":1,"message":"texto","post":1}', "group": "instagram",
     "desc": "responder um comentário (pede confirmação)", "examples": ["responde o primeiro comentário com obrigado"],
     "run": lambda a: ig_reply(a.get("comment", 1), a.get("message", ""), a.get("post", 1))},
    {"name": "instagram_post", "args": '{"image_url":"https://...","caption":"legenda"}', "group": "instagram",
     "desc": "publicar foto que já está num link público (pede confirmação)", "examples": ["posta essa foto com a legenda bom dia"],
     "run": lambda a: ig_post(a.get("image_url", ""), a.get("caption", ""))},
    {"name": "whatsapp_send", "args": '{"contact":"nome ou número","message":"texto"}', "group": "whatsapp",
     "desc": "mandar mensagem no WhatsApp (pede confirmação)", "examples": ["manda oi pra mãe no zap"],
     "run": lambda a: _sent(B.whatsapp_send(a.get("contact", ""), a.get("message", ""), confirm))},
    {"name": "whatsapp_send_file", "args": '{"contact":"nome ou número","file":"print (tira agora) | ultimo print | caminho ou número do resultado","caption":"legenda (opcional)"}',
     "group": "whatsapp", "desc": "mandar um print da tela ou um arquivo no WhatsApp (pede confirmação)",
     "examples": ["manda um print pro Erick no zap", "manda esse pdf pra Ana no whats"],
     "run": lambda a: whatsapp_send_file(a.get("contact", ""), a.get("file", "print"), a.get("caption", ""))},
    {"name": "whatsapp_read", "args": '{"contact":"nome (vazio = últimas conversas)"}', "group": "whatsapp",
     "desc": "ler as mensagens do WhatsApp (últimas conversas ou as de um contato)",
     "examples": ["tem mensagem nova no zap?", "lê as mensagens da Ana"],
     "run": lambda a: B.whatsapp_read(a.get("contact", ""))},
    # ---- memória
    {"name": "set_profile", "args": '{"key":"nome|cidade|apelido|musica_favorita|...","value":"valor"}', "group": "memória",
     "desc": "guardar algo do perfil do usuário", "examples": ["eu moro em Recife"],
     "run": lambda a: M.set_profile(a.get("key", ""), a.get("value", ""))},
    {"name": "remember", "args": '{"fact":"texto"}', "group": "memória",
     "desc": "guardar uma informação que o usuário pediu para lembrar", "examples": ["lembra que eu sou alérgico a camarão"],
     "run": lambda a: M.remember(a.get("fact", ""))},
    {"name": "greeting", "args": "{}", "group": "memória",
     "desc": "boas-vindas estilo Jarvis com resumo e sugestões (\"acorda, bebê, o papai chegou\", \"cheguei\")",
     "examples": ["acorda bebê o papai chegou", "cheguei em casa"], "run": lambda a: greeting()},
    {"name": "set_alarm", "args": '{"hour":"HH:MM","day":"AAAA-MM-DD ou vazio (a próxima vez)","music":"música para acordar (opcional)"}',
     "group": "memória", "desc": "DESPERTADOR: acordar o senhor num horário com música; depois do ACORDEI dá bom dia "
                                  "com clima, roupa e notícias", "examples": ["me acorda às 7h", "me acorda amanhã 6h30 com Evidências"],
     "run": lambda a: set_alarm(a.get("hour", ""), a.get("day", ""), a.get("music", ""))},
    {"name": "schedule_request", "args": '{"request":"o pedido como o senhor falaria (ex.: toca evidências)","day":"AAAA-MM-DD","hour":"HH:MM","repeat":"vazio|diario|dias uteis|semanal|mensal"}',
     "group": "memória", "desc": "FAZER um pedido mais tarde, numa data e hora, uma vez ou repetindo (rotina)",
     "examples": ["coloca evidências às 7h", "amanhã às 8h abre o Spotify", "todo dia às 20h faz backup da pasta documentos"],
     "run": lambda a: M.add_reminder(a.get("request", ""), a.get("day", ""), a.get("hour", ""), pedido=True,
                                     repetir=a.get("repeat", ""))},
    {"name": "add_reminder", "args": '{"text":"o que lembrar","day":"AAAA-MM-DD","hour":"HH:MM ou vazio","repeat":"vazio|diario|semanal|mensal|anual"}',
     "group": "memória", "desc": "marcar um lembrete para um dia (e hora), uma vez ou repetindo",
     "examples": ["me lembra da prova na sexta", "todo dia 5 me lembra do aluguel"],
     "run": lambda a: M.add_reminder(a.get("text", ""), a.get("day", ""), a.get("hour", ""), repetir=a.get("repeat", ""))},
    {"name": "forget", "args": '{"text":"assunto"}', "group": "memória",
     "desc": "apagar da memória o que tiver esse assunto", "examples": ["esquece a prova"],
     "run": lambda a: M.forget(a.get("text", ""))},
    {"name": "what_i_know", "args": "{}", "group": "memória",
     "desc": "mostrar tudo o que eu sei sobre o usuário", "examples": ["o que você sabe sobre mim"],
     "run": lambda a: M.what_i_know()},
    {"name": "history", "args": '{"day":"hoje|ontem|AAAA-MM-DD"}', "group": "memória",
     "desc": "o que o usuário pediu num dia", "examples": ["o que eu te pedi ontem"],
     "run": lambda a: M.history(a.get("day", "hoje"))},
    # ---- rotinas
    {"name": "run_routine", "args": '{"name":"estudo|relaxar|foco|..."}', "group": "rotinas",
     "desc": "rodar uma rotina com vários passos", "examples": ["modo estudo"],
     "run": lambda a: F.run_routine(a.get("name", ""), execute_ai_action)},
    {"name": "list_routines", "args": "{}", "group": "rotinas",
     "desc": "listar as rotinas", "examples": ["quais rotinas tem"],
     "run": lambda a: F.list_routines()},
    # ---- habilidades (skills)
    {"name": "use_skill", "args": '{"name":"nome da habilidade"}', "group": "habilidades",
     "desc": "carregar e seguir uma habilidade (receita pronta) quando o pedido combinar com ela",
     "examples": ["modo aula", "planeja o meu dia"],
     "run": lambda a: H.use(a.get("name", ""), run_actions, handle)},
    {"name": "list_skills", "args": "{}", "group": "habilidades",
     "desc": "listar as habilidades", "examples": ["quais habilidades você tem?"],
     "run": lambda a: H.list_skills()},
    {"name": "teach_skill", "args": '{"trigger":"frase que o senhor vai dizer","todo":"o que fazer"}', "group": "habilidades",
     "desc": "criar uma habilidade: quando o senhor disser X, fazer Y", "examples": ["aprende: quando eu disser modo aula, abre o Teams"],
     "run": lambda a: H.create(a.get("trigger", ""), a.get("todo", ""))},
    {"name": "import_skill", "args": '{"url":"https://..."}', "group": "habilidades",
     "desc": "importar uma habilidade da internet (só o texto; ações só depois de aprovar)",
     "examples": ["importa a habilidade https://github.com/.../SKILL.md"],
     "run": lambda a: H.import_skill(a.get("url", ""))},
    {"name": "approve_skill", "args": '{"name":"nome"}', "group": "habilidades",
     "desc": "aprovar uma habilidade importada para ela poder agir (pede confirmação)", "examples": ["aprova a habilidade receitas"],
     "run": lambda a: H.approve(a.get("name", ""), confirm)},
    {"name": "remove_skill", "args": '{"name":"nome"}', "group": "habilidades",
     "desc": "apagar uma habilidade do senhor (pede confirmação)", "examples": ["apaga a habilidade modo aula"],
     "run": lambda a: H.remove(a.get("name", ""), confirm)},
    # ---- aprendizado (o motor que faz ele melhorar)
    {"name": "what_went_wrong", "args": '{"day":"hoje|ontem|AAAA-MM-DD"}', "group": "aprendizado",
     "desc": "listar os pedidos que deram errado", "examples": ["o que deu errado hoje?"],
     "run": lambda a: D.what_went_wrong(a.get("day", "hoje"))},
    {"name": "explain_last", "args": "{}", "group": "aprendizado",
     "desc": "explicar o que fez no último pedido e por quê", "examples": ["por que você fez isso?"],
     "run": lambda a: D.explain_last()},
    {"name": "weekly_report", "args": "{}", "group": "aprendizado",
     "desc": "gerar o relatório da semana (falhas e lentidão) para o Claude e o Codex", "examples": ["gera o relatório da semana"],
     "run": lambda a: D.write_report()},
    {"name": "error_report", "args": "{}", "group": "aprendizado",
     "desc": "gerar o relatório de erro para mandar ao Claude ou ao Codex", "examples": ["gera o relatório de erro"],
     "run": lambda a: D.error_report(ACTION_LOG)},
    {"name": "stopwatch_today", "args": "{}", "group": "aprendizado",
     "desc": "dizer quanto tempo leva para ouvir, pensar, fazer e falar", "examples": ["quanto tempo você demora?"],
     "run": lambda a: D.stopwatch_today()},
    {"name": "learned_week", "args": "{}", "group": "aprendizado",
     "desc": "contar o que aprendeu na semana", "examples": ["o que você aprendeu essa semana?"],
     "run": lambda a: A.learned_since(7)},
    {"name": "set_alias", "args": '{"alias":"apelido","value":"o que quer dizer"}', "group": "aprendizado",
     "desc": "guardar um apelido (\"o patrão\" = Erick Cuba, \"meu jogo\" = Omori)",
     "examples": ["quando eu falar meu jogo é o Omori", "o patrão é apelido do Erick Cuba"],
     "run": lambda a: A.set_alias(a.get("alias", ""), a.get("value", "")) and (refresh_vocabulary() or True)},
    {"name": "remember_person", "args": '{"name":"nome","field":"aniversario|quem_e|gosta|...","value":"valor"}',
     "group": "aprendizado", "desc": "guardar algo sobre uma pessoa (aniversário, quem é, do que gosta)",
     "examples": ["o aniversário do Erick é 3 de maio", "a Ana gosta de chocolate"],
     "run": lambda a: A.set_person(a.get("name", ""), a.get("field", "nota"), a.get("value", ""))},
    {"name": "about_person", "args": '{"name":"nome"}', "group": "aprendizado",
     "desc": "dizer o que sabe sobre uma pessoa", "examples": ["o que você sabe sobre a Ana"],
     "run": lambda a: A.person(a.get("name", ""))},
    {"name": "forget_learned", "args": '{"kind":"apelido|pessoa|correcao","what":"nome"}', "group": "aprendizado",
     "desc": "esquecer um apelido, uma pessoa ou uma correção", "examples": ["esquece o apelido patrão"],
     "run": lambda a: A.forget_learned(normalize(a.get("kind", "")), a.get("what", ""))},
    {"name": "memory_panel", "args": "{}", "group": "aprendizado",
     "desc": "mostrar na tela tudo o que sabe, com botão para apagar", "examples": ["mostra o painel da memória"],
     "run": lambda a: memory_panel()},
    {"name": "memory_backup", "args": '{"dest":"pendrive | pasta (vazio = G:\\Jarvis\\backups)"}', "group": "aprendizado",
     "desc": "fazer backup da memória", "examples": ["faz backup da memória no pendrive"],
     "run": lambda a: A.backup(a.get("dest", ""))},
    # ---- mãos: botões e janelas de qualquer programa
    {"name": "click_ui", "args": '{"name":"texto do botão, menu ou link"}', "group": "mãos",
     "desc": "clicar em qualquer botão/menu de qualquer programa pelo nome (pede confirmação se precisar olhar a tela)",
     "examples": ["clica em Salvar", "clica no botão Enviar"],
     "run": lambda a: MA.click_ui(a.get("name", ""), N.vision if N.available() else None, confirm)},
    {"name": "read_window", "args": "{}", "group": "mãos",
     "desc": "ler o que está escrito na janela da frente (para entender o programa aberto)", "examples": ["lê essa janela"],
     "run": lambda a: MA.read_window()},
    {"name": "list_controls", "args": "{}", "group": "mãos",
     "desc": "listar os botões e menus da janela da frente", "examples": ["quais botões tem aqui?"],
     "run": lambda a: MA.list_controls()},
    {"name": "fill_field", "args": '{"field":"nome do campo (ou vazio)","text":"texto"}', "group": "mãos",
     "desc": "escrever num campo de qualquer programa (formulários)", "examples": ["escreve João no campo Nome"],
     "run": lambda a: MA.fill_field(a.get("field", ""), a.get("text", ""))},
    {"name": "app_shortcut", "args": '{"action":"salva|desfaz|refaz|nova aba|fecha a aba|negrito|imprimir|..."}', "group": "mãos",
     "desc": "atalho do programa da frente por voz (sabe os do Word em português)", "examples": ["salva", "desfaz", "nova aba"],
     "run": lambda a: MA.app_shortcut(a.get("action", ""))},
    {"name": "side_by_side", "args": '{"first":"janela","second":"outra janela (opcional)"}', "group": "janelas e teclado",
     "desc": "colocar duas janelas lado a lado", "examples": ["coloca o chrome e o word lado a lado"],
     "run": lambda a: MA.side_by_side(a.get("first", ""), a.get("second", ""))},
    {"name": "to_second_screen", "args": '{"title":"janela (vazio = a da frente)"}', "group": "janelas e teclado",
     "desc": "mandar uma janela para a segunda tela", "examples": ["manda essa janela para a outra tela"],
     "run": lambda a: MA.to_second_screen(a.get("title", ""))},
    {"name": "save_layout", "args": '{"name":"nome"}', "group": "janelas e teclado",
     "desc": "guardar a posição das janelas como um layout", "examples": ["salva esse layout como trabalho"],
     "run": lambda a: MA.save_layout(a.get("name", ""))},
    {"name": "apply_layout", "args": '{"name":"nome"}', "group": "janelas e teclado",
     "desc": "arrumar as janelas num layout salvo (abre o que faltar)", "examples": ["layout trabalho"],
     "run": lambda a: MA.apply_layout(a.get("name", ""))},
    # ---- Windows
    {"name": "radio", "args": '{"kind":"wifi|bluetooth","on":true}', "group": "sistema",
     "desc": "ligar ou desligar o Wi-Fi ou o Bluetooth", "examples": ["desliga o bluetooth"],
     "run": lambda a: MA.radio(a.get("kind", "wifi"), bool(a.get("on", True)))},
    {"name": "dark_mode", "args": '{"on":true}', "group": "sistema",
     "desc": "modo escuro ou claro do Windows", "examples": ["ativa o modo escuro"],
     "run": lambda a: MA.dark_mode(bool(a.get("on", True)))},
    {"name": "audio_output", "args": '{"which":"fone|caixa|nome do aparelho"}', "group": "som",
     "desc": "trocar a saída de som (fone ou caixa)", "examples": ["coloca o som no fone"],
     "run": lambda a: MA.audio_output(a.get("which", ""))},
    {"name": "set_resolution", "args": '{"width":1366,"height":768}', "group": "sistema",
     "desc": "mudar a resolução da tela", "examples": ["muda a resolução para 1366x768"],
     "run": lambda a: MA.set_resolution(a.get("width", 0), a.get("height", 0))},
    {"name": "screen_off", "args": "{}", "group": "sistema",
     "desc": "apagar o monitor", "examples": ["apaga a tela"],
     "run": lambda a: MA.screen_off()},
    {"name": "install_program", "args": '{"name":"programa"}', "group": "sistema",
     "desc": "instalar programa pelo winget (pede confirmação)", "examples": ["instala o VLC"],
     "run": lambda a: MA.install_program(a.get("name", ""), confirm)},
    {"name": "update_programs", "args": '{"name":"programa (vazio = todos)"}', "group": "sistema",
     "desc": "atualizar os programas pelo winget (pede confirmação)", "examples": ["atualiza tudo"],
     "run": lambda a: MA.update_programs(confirm, a.get("name", ""))},
    {"name": "uninstall_program", "args": '{"name":"programa"}', "group": "sistema",
     "desc": "desinstalar um programa (pede confirmação e a senha, se houver)", "examples": ["desinstala o VLC"],
     "run": lambda a: MA.uninstall_program(a.get("name", ""), confirm_danger)},
    {"name": "cleanup", "args": "{}", "group": "sistema",
     "desc": "limpar temporários e a Lixeira, dizendo quanto libera (pede confirmação)", "examples": ["limpa o pc"],
     "run": lambda a: MA.cleanup(confirm)},
    {"name": "clean_old_downloads", "args": '{"days":90}', "group": "arquivos e pastas",
     "desc": "mandar para a Lixeira os downloads velhos (pede confirmação)", "examples": ["limpa os downloads velhos"],
     "run": lambda a: MA.clean_old_downloads(confirm, int(a.get("days", 90) or 90), DOWNLOADS)},
    {"name": "clean_memory", "args": "{}", "group": "sistema",
     "desc": "limpador de memória: libera RAM sem fechar nada e mostra antes e depois", "examples": ["limpa a memória"],
     "run": lambda a: MA.clean_memory()},
    {"name": "why_slow", "args": "{}", "group": "sistema",
     "desc": "dizer por que o PC está lento (o culpado) e oferecer fechar", "examples": ["por que tá lento?"],
     "run": lambda a: MA.why_slow(confirm, F.close_app)},
    {"name": "app_volume", "args": '{"app":"programa","percent":50,"delta":0}', "group": "som",
     "desc": "volume de um programa só (Discord mais alto, jogo mais baixo)", "examples": ["discord mais alto", "volume do spotify em 30"],
     "run": lambda a: MA.app_volume(a.get("app", ""), a.get("percent"), a.get("delta"))},
    {"name": "print_file", "args": '{"path":"caminho ou número do resultado"}', "group": "arquivos e pastas",
     "desc": "imprimir um arquivo", "examples": ["imprime o primeiro"],
     "run": lambda a: MA.print_file(resolve_path(a.get("path", "1")))},
    {"name": "clipboard_list", "args": "{}", "group": "janelas e teclado",
     "desc": "mostrar o histórico da área de transferência", "examples": ["histórico da área de transferência"],
     "run": lambda a: MA.clipboard_list()},
    {"name": "clipboard_paste", "args": '{"index":2}', "group": "janelas e teclado",
     "desc": "colar algo copiado antes (2 = o penúltimo)", "examples": ["cola o que eu copiei antes"],
     "run": lambda a: MA.clipboard_paste(a.get("index", 2))},
    {"name": "organize_folder", "args": '{"folder":"downloads|pasta","by":"tipo|data"}', "group": "arquivos e pastas",
     "desc": "organizar uma pasta em subpastas por tipo ou data (pede confirmação; dá para desfazer)",
     "examples": ["organiza os downloads"],
     "run": lambda a: MA.organize_folder(folder_of(a.get("folder", "downloads")), confirm, a.get("by", "tipo"))},
    {"name": "batch_rename", "args": '{"folder":"pasta","pattern":"novo nome (ou data)","kind":"Imagens|pdf|... (opcional)"}',
     "group": "arquivos e pastas", "desc": "renomear vários arquivos de uma vez (pede confirmação; dá para desfazer)",
     "examples": ["renomeia as fotos da pasta praia para praia 2026"],
     "run": lambda a: MA.batch_rename(folder_of(a.get("folder", "")), a.get("pattern", ""), confirm, a.get("kind", ""))},
    {"name": "compress", "args": '{"path":"caminho ou número"}', "group": "arquivos e pastas",
     "desc": "compactar em .zip", "examples": ["compacta a pasta projetos"],
     "run": lambda a: MA.compress(_path_or_folder(a.get("path", "")))},
    {"name": "extract", "args": '{"path":"caminho ou número"}', "group": "arquivos e pastas",
     "desc": "descompactar um .zip", "examples": ["descompacta o primeiro"],
     "run": lambda a: MA.extract(_path_or_folder(a.get("path", "")))},
    {"name": "undo_file", "args": "{}", "group": "arquivos e pastas",
     "desc": "desfazer a última ação de arquivo (mover, renomear, organizar)", "examples": ["desfaz o que você fez"],
     "run": lambda a: MA.undo_last()},
    {"name": "convert_file", "args": '{"path":"caminho, número ou pasta de imagens","to":"pdf|mp3|jpg|png|mp4"}',
     "group": "arquivos e pastas", "desc": "converter arquivo (imagens para PDF, vídeo para MP3...)",
     "examples": ["converte o primeiro para mp3", "transforma a pasta prints em pdf"],
     "run": lambda a: MA.convert(_path_or_folder(a.get("path", "")), a.get("to", ""))},
    {"name": "shrink_file", "args": '{"path":"caminho ou número"}', "group": "arquivos e pastas",
     "desc": "diminuir um arquivo grande para mandar no zap", "examples": ["diminui esse vídeo para mandar no zap"],
     "run": lambda a: MA.shrink_for_sending(_path_or_folder(a.get("path", "")))},
    {"name": "record_macro", "args": '{"name":"nome"}', "group": "mãos",
     "desc": "observar e gravar cliques e teclas para repetir depois (botão PARAR)", "examples": ["observa o que eu faço"],
     "run": lambda a: _record_macro(a.get("name", ""))},
    {"name": "stop_macro", "args": "{}", "group": "mãos",
     "desc": "parar de gravar a macro", "examples": ["para de gravar"],
     "run": lambda a: MA.stop_recording() or print("Jarvis > Não estava gravando.") or False},
    {"name": "play_macro", "args": '{"name":"nome"}', "group": "mãos",
     "desc": "repetir uma macro gravada", "examples": ["repete a macro planilha"],
     "run": lambda a: MA.play_macro(a.get("name", ""), stop=stop_event)},
    {"name": "list_macros", "args": "{}", "group": "mãos",
     "desc": "listar as macros", "examples": ["quais macros você tem"],
     "run": lambda a: MA.list_macros()},
    # ---- jogos e saúde do PC
    {"name": "open_game", "args": '{"name":"jogo"}', "group": "jogos",
     "desc": "abrir jogo da Steam ou da Epic pelo nome", "examples": ["abre o jogo Omori"],
     "run": lambda a: MA.open_game(a.get("name", ""))},
    {"name": "game_clip", "args": "{}", "group": "jogos",
     "desc": "salvar os últimos 30 segundos do jogo (Xbox Game Bar)", "examples": ["grava os últimos 30 segundos"],
     "run": lambda a: MA.game_clip()},
    {"name": "game_bar", "args": "{}", "group": "jogos",
     "desc": "abrir o Xbox Game Bar (FPS e desempenho)", "examples": ["mostra o fps"],
     "run": lambda a: MA.game_bar()},
    {"name": "game_priority", "args": '{"name":"jogo (vazio = a janela da frente)"}', "group": "jogos",
     "desc": "dar prioridade alta ao jogo", "examples": ["dá prioridade para o jogo"],
     "run": lambda a: MA.game_priority(a.get("name", ""))},
    {"name": "health_report", "args": "{}", "group": "sistema",
     "desc": "relatório de saúde do PC: disco, RAM, temperatura e atualizações pendentes", "examples": ["como tá a saúde do pc"],
     "run": lambda a: MA.health_report()},
    {"name": "list_startup", "args": "{}", "group": "sistema",
     "desc": "listar o que abre com o Windows", "examples": ["o que abre com o windows?"],
     "run": lambda a: MA.list_startup()},
    {"name": "ask_choice", "args": '{"question":"pergunta","options":["opção 1","opção 2"]}', "group": "informação",
     "desc": "perguntar ao senhor com opções num card quando estiver em dúvida (use continue:true)",
     "examples": ["(dúvida entre dois arquivos ou contatos)"],
     "run": lambda a: ask_choice(a.get("question", ""), a.get("options", []))},
    # ---- modos e rotina
    {"name": "enter_mode", "args": '{"name":"aula|estudo|trabalho|jogo|dormir|filme|visita"}', "group": "rotinas",
     "desc": "ligar um modo pronto (faz tudo de uma vez; \"sai do modo\" desfaz)", "examples": ["modo aula", "modo jogo"],
     "run": lambda a: _enter_mode(a.get("name", ""))},
    {"name": "exit_mode", "args": "{}", "group": "rotinas",
     "desc": "sair do modo e voltar tudo como estava", "examples": ["sai do modo"],
     "run": lambda a: R.exit_mode(execute_ai_action, set_windows_dnd=MA.windows_notifications, on_screen=_screen)},
    {"name": "good_night", "args": "{}", "group": "rotinas",
     "desc": "boa noite: resumo do dia, lembretes de amanhã e apaga a tela", "examples": ["vou dormir"],
     "run": lambda a: good_night()},
    {"name": "dnd_on", "args": '{"until":"até as 18h | por 2 horas | vazio = até eu desligar"}', "group": "rotinas",
     "desc": "não perturbe: segura os avisos e conta depois (VIP passa)", "examples": ["não perturbe até as 18h"],
     "run": lambda a: dnd_on(a.get("until", ""))},
    {"name": "dnd_off", "args": "{}", "group": "rotinas",
     "desc": "desligar o não perturbe e contar o que chegou", "examples": ["desliga o não perturbe"],
     "run": lambda a: dnd_off()},
    {"name": "set_vip", "args": '{"name":"contato","on":true}', "group": "whatsapp",
     "desc": "contato VIP: mensagem dele avisa na hora, até no não perturbe", "examples": ["a mãe é VIP"],
     "run": lambda a: R.set_vip(a.get("name", ""), bool(a.get("on", True)))},
    {"name": "start_pomodoro", "args": '{"minutes":25,"pause":5,"cycles":4}', "group": "rotinas",
     "desc": "Pomodoro com foco (avisa a pausa e tira distrações da frente)", "examples": ["começa um pomodoro"],
     "run": lambda a: R.start_pomodoro(a.get("minutes", 25), alert, a.get("pause", 5), a.get("cycles", 4),
                                       F.user_window_title, lambda: MA.window_state("minimizar"))},
    {"name": "stop_pomodoro", "args": "{}", "group": "rotinas",
     "desc": "parar o Pomodoro", "examples": ["para o pomodoro"], "run": lambda a: R.stop_pomodoro()},
    {"name": "pomodoro_status", "args": "{}", "group": "rotinas",
     "desc": "quanto falta do Pomodoro", "examples": ["quanto falta do pomodoro"], "run": lambda a: R.pomodoro_status()},
    {"name": "list_add", "args": '{"list":"compras|tarefas|nome","items":"ovo, arroz e leite","priority":"alta|media|baixa"}',
     "group": "rotinas", "desc": "anotar na lista de compras ou de tarefas", "examples": ["anota ovo e leite na lista de compras"],
     "run": lambda a: R.add_items(a.get("list", "compras"), a.get("items", ""), a.get("priority", ""))},
    {"name": "list_check", "args": '{"list":"compras|tarefas","items":"item"}', "group": "rotinas",
     "desc": "riscar um item da lista", "examples": ["já comprei o leite"],
     "run": lambda a: R.check_item(a.get("list", "compras"), a.get("items", ""))},
    {"name": "list_remove", "args": '{"list":"compras|tarefas","items":"item"}', "group": "rotinas",
     "desc": "tirar um item da lista", "examples": ["tira o arroz da lista"],
     "run": lambda a: R.remove_items(a.get("list", "compras"), a.get("items", ""))},
    {"name": "list_clear", "args": '{"list":"compras|tarefas"}', "group": "rotinas",
     "desc": "apagar a lista (pede confirmação)", "examples": ["limpa a lista de compras"],
     "run": lambda a: R.clear_list(a.get("list", "compras"), confirm)},
    {"name": "list_show", "args": '{"list":"compras|tarefas"}', "group": "rotinas",
     "desc": "mostrar a lista num card", "examples": ["mostra a lista de compras"],
     "run": lambda a: R.show_list(a.get("list", "compras"), lambda t, x: U.card(t, x, 30000))},
    {"name": "wellness_on", "args": '{"kind":"agua|postura|ambos","minutes":60}', "group": "rotinas",
     "desc": "lembrete de água e postura (só com o PC em uso)", "examples": ["liga o lembrete de água"],
     "run": lambda a: R.start_wellness(lambda t: commands.put(("aviso", t)), a.get("minutes", 60), a.get("kind", "ambos"))},
    {"name": "wellness_off", "args": "{}", "group": "rotinas",
     "desc": "desligar o lembrete de água", "examples": ["desliga o lembrete de água"], "run": lambda a: R.stop_wellness()},
    {"name": "add_bill", "args": '{"name":"luz","day":10,"value":"150,00"}', "group": "rotinas",
     "desc": "anotar conta a pagar com vencimento (avisa 2 dias antes, todo mês)", "examples": ["a conta de luz vence dia 10"],
     "run": lambda a: R.add_bill(a.get("name", ""), a.get("day", ""), a.get("value", ""), M.add_reminder)},
    {"name": "list_bills", "args": "{}", "group": "rotinas",
     "desc": "contas do mês e quando vencem", "examples": ["quais contas vencem esse mês"], "run": lambda a: R.list_bills()},
    {"name": "rain_warning", "args": '{"city":"cidade (vazio = a do perfil)"}', "group": "informação",
     "desc": "avisar se vai chover nas próximas horas (levar guarda-chuva?)", "examples": ["levo guarda-chuva?"],
     "run": lambda a: R.rain_warning(a.get("city") or M.load()["perfil"].get("cidade", ""))},
    {"name": "play_mood", "args": '{"mood":"animar|focar|relaxar|triste|dormir|treinar|festa"}', "group": "mídia",
     "desc": "música pelo humor", "examples": ["toca algo para animar"],
     "run": lambda a: play_youtube(R.mood_query(a.get("mood", "")))},
    {"name": "days_until", "args": '{"name":"evento"}', "group": "rotinas",
     "desc": "quantos dias faltam para uma data", "examples": ["quantos dias para a prova?"],
     "run": lambda a: R.days_until(a.get("name", ""), M.load()["lembretes"])},
    {"name": "add_countdown", "args": '{"name":"evento","day":"AAAA-MM-DD"}', "group": "rotinas",
     "desc": "contagem regressiva para uma data", "examples": ["conta os dias para a viagem dia 20/12"],
     "run": lambda a: R.add_countdown(a.get("name", ""), a.get("day", ""))},
    # ---- documentos
    {"name": "search_content", "args": '{"query":"palavras"}', "group": "arquivos e pastas",
     "desc": "procurar DENTRO dos arquivos (texto de PDF, Word, Excel)", "examples": ["procura o documento que fala de multa"],
     "run": lambda a: search_content(a.get("query", ""))},
    {"name": "ask_document", "args": '{"path":"caminho ou número","question":"pergunta"}', "group": "ler e resumir",
     "desc": "responder uma pergunta sobre um documento", "examples": ["qual o prazo nesse contrato?"],
     "run": lambda a: DOC.ask_document(resolve_path(a.get("path", "1")), a.get("question", ""), think)},
    {"name": "read_aloud", "args": '{"path":"caminho ou número"}', "group": "ler e resumir",
     "desc": "ler um PDF/documento em voz alta, em partes (continua, volta, para)", "examples": ["lê o primeiro em voz alta"],
     "run": lambda a: _read_aloud(a.get("path", "1"))},
    {"name": "reading_control", "args": '{"action":"continua|volta|repete|parte 3|para"}', "group": "ler e resumir",
     "desc": "controlar a leitura em voz alta", "examples": ["continua"],
     "run": lambda a: DOC.reading_control(a.get("action", "continua"))},
    {"name": "start_dictation", "args": '{"name":"nome do documento (opcional, .txt para texto)"}', "group": "ler e resumir",
     "desc": "ditar um documento (Word): cada fala vira um parágrafo; \"fim do ditado\" salva",
     "examples": ["quero ditar uma carta"], "run": lambda a: DOC.start_dictation(a.get("name", ""), DOCUMENTS)},
    {"name": "sum_column", "args": '{"path":"planilha (caminho ou número)","column":"letra ou nome"}', "group": "ler e resumir",
     "desc": "somar uma coluna de planilha", "examples": ["soma a coluna valor da planilha"],
     "run": lambda a: DOC.sum_column(resolve_path(a.get("path", "1")), a.get("column", ""))},
    {"name": "show_sheet", "args": '{"path":"planilha"}', "group": "ler e resumir",
     "desc": "mostrar as linhas de uma planilha", "examples": ["mostra a planilha"],
     "run": lambda a: DOC.show_sheet(resolve_path(a.get("path", "1")))},
    {"name": "create_sheet", "args": '{"name":"nome","headers":["Coluna"],"rows":[["valor"]]}', "group": "ler e resumir",
     "desc": "criar uma planilha simples (.xlsx) nos Documentos", "examples": ["cria uma planilha de gastos"],
     "run": lambda a: DOC.create_sheet(DOCUMENTS / (str(a.get("name") or "Planilha") + ".xlsx"), a.get("headers") or ["Item"], a.get("rows") or [])},
    {"name": "photos_from", "args": '{"when":"julho | julho de 2024 | mês passado | 2025"}', "group": "arquivos e pastas",
     "desc": "achar fotos por data", "examples": ["fotos de julho"],
     "run": lambda a: photos_from(a.get("when", ""))},
    {"name": "last_download", "args": '{"open":true}', "group": "arquivos e pastas",
     "desc": "o último arquivo baixado (e abrir)", "examples": ["abre o último arquivo baixado"],
     "run": lambda a: last_download(bool(a.get("open", True)))},
    {"name": "backup_folder", "args": '{"src":"pasta","dest":"pendrive ou pasta (vazio = G:\\Jarvis\\backups)"}',
     "group": "arquivos e pastas", "desc": "backup de uma pasta (para fazer todo dia, use schedule_request com repeat)",
     "examples": ["faz backup da pasta documentos no pendrive"],
     "run": lambda a: _backup_folder(a.get("src", ""), a.get("dest", ""))},
    # ---- integrações e o Bolha se cuidando
    {"name": "integrations", "args": "{}", "group": "integrações",
     "desc": "listar as integrações ligadas e o que falta para ligar as outras", "examples": ["quais integrações eu tenho?"],
     "run": lambda a: I.integrations()},
    {"name": "google_connect", "args": "{}", "group": "integrações",
     "desc": "conectar o Gmail e a Agenda (uma vez)", "examples": ["conecta o google"], "run": lambda a: I.google_connect()},
    {"name": "gmail_list", "args": '{"query":"busca do Gmail (vazio = não lidos importantes)"}', "group": "integrações",
     "desc": "ler a lista de e-mails (não lidos da caixa principal)", "examples": ["tenho e-mail novo?"],
     "run": lambda a: I.gmail_list(a.get("query") or "is:unread category:primary")},
    {"name": "gmail_read", "args": '{"index":1}', "group": "integrações",
     "desc": "ler um e-mail da última lista", "examples": ["lê o e-mail 2"], "run": lambda a: I.gmail_read(a.get("index", 1))},
    {"name": "gmail_send", "args": '{"to":"email","subject":"assunto","body":"texto","reply_to":"número do e-mail da lista para responder (opcional)"}',
     "group": "integrações", "desc": "mandar ou responder e-mail (pede confirmação)", "examples": ["responde o e-mail 1 dizendo que confirmo"],
     "run": lambda a: I.gmail_send(a.get("to", ""), a.get("subject", ""), a.get("body", ""), confirm, a.get("reply_to"))},
    {"name": "calendar_events", "args": '{"day":"hoje|amanha|AAAA-MM-DD"}', "group": "integrações",
     "desc": "eventos da Agenda do Google", "examples": ["o que tenho hoje na agenda"],
     "run": lambda a: I.calendar_events(a.get("day", "hoje"))},
    {"name": "calendar_add", "args": '{"title":"evento","day":"AAAA-MM-DD","hour":"HH:MM","minutes":60}', "group": "integrações",
     "desc": "criar evento na Agenda do Google", "examples": ["marca dentista sexta às 15h na agenda"],
     "run": lambda a: I.calendar_add(a.get("title", ""), a.get("day", ""), a.get("hour", ""), a.get("minutes", 60))},
    {"name": "home_control", "args": '{"device":"luz da sala","action":"ligar|desligar"}', "group": "integrações",
     "desc": "lâmpadas e tomadas inteligentes (Home Assistant)", "examples": ["apaga a luz do quarto"],
     "run": lambda a: I.home_control(a.get("device", ""), a.get("action", "ligar"))},
    {"name": "watch_price", "args": '{"url":"link do produto","name":"nome","target":0}', "group": "integrações",
     "desc": "vigiar o preço de um produto e avisar quando baixar", "examples": ["vigia o preço de https://..."],
     "run": lambda a: I.watch_price(a.get("url", ""), a.get("name", ""), a.get("target"))},
    {"name": "list_prices", "args": "{}", "group": "integrações",
     "desc": "preços que estou vigiando", "examples": ["quais preços você está vigiando"], "run": lambda a: I.list_prices()},
    {"name": "track_parcel", "args": '{"code":"AB123456789BR","name":"apelido"}', "group": "integrações",
     "desc": "rastrear encomenda dos Correios e avisar quando mudar", "examples": ["rastreia a encomenda AB123456789BR"],
     "run": lambda a: I.track_parcel(a.get("code", ""), a.get("name", ""))},
    {"name": "self_test", "args": "{}", "group": "sistema",
     "desc": "autoteste: microfone, voz, IA, WhatsApp, internet", "examples": ["faz um autoteste"],
     "run": lambda a: self_test()},
    {"name": "update_bolha", "args": "{}", "group": "sistema",
     "desc": "atualizar o próprio Bolha pelo GitHub (pede confirmação)", "examples": ["se atualiza"],
     "run": lambda a: AT.update(confirm)},
    # ---- cérebro
    {"name": "look_screen", "args": '{"question":"o que o senhor perguntou sobre a tela"}', "group": "informação",
     "desc": "olhar a tela (print + IA) e responder: o que é isso, qual o erro, traduzir a tela",
     "examples": ["o que é isso na tela?", "qual o erro aqui?"], "run": lambda a: look_screen(a.get("question", ""))},
    {"name": "translate_selection", "args": "{}", "group": "informação",
     "desc": "traduzir o texto selecionado (ou o da tela)", "examples": ["traduz isso"],
     "run": lambda a: translate_selection()},
    {"name": "agent_task", "args": '{"goal":"o que fazer, em vários passos"}', "group": "mãos",
     "desc": "modo agente: fazer uma tarefa de vários passos num programa, mostrando cada passo, com PARAR",
     "examples": ["faz sozinho: cria uma pasta no Drive chamada Fotos"], "run": lambda a: agent_task(a.get("goal", ""))},
    {"name": "set_personality", "args": '{"style":"normal|serio|humor|curto|detalhado"}', "group": "memória",
     "desc": "ajustar a personalidade (mais sério, mais humor, mais curto)", "examples": ["fica mais sério"],
     "run": lambda a: _set_personality(a.get("style", "normal"))},
    {"name": "chat_mode", "args": '{"on":true}', "group": "memória",
     "desc": "modo papo: conversa livre, ele pergunta de volta e lembra do assunto", "examples": ["vamos conversar"],
     "run": lambda a: chat_mode(bool(a.get("on", True)))},
    {"name": "calibrate_mic", "args": "{}", "group": "sistema",
     "desc": "calibrar o microfone (diga Bolha 3 vezes)", "examples": ["calibra o microfone"],
     "run": lambda a: calibrate_mic()},
    {"name": "add_vocabulary", "args": '{"words":"nomes separados por vírgula"}', "group": "memória",
     "desc": "ensinar palavras para ele entender por voz (nomes, jogos)", "examples": ["aprende a palavra Omori"],
     "run": lambda a: add_vocabulary(a.get("words", ""))},
    # ---- WhatsApp, navegador, celular e tela
    {"name": "whatsapp_reply", "args": '{"message":"texto"}', "group": "whatsapp",
     "desc": "responder a última mensagem recebida (pede confirmação)", "examples": ["responde que já vou"],
     "run": lambda a: whatsapp_reply(a.get("message", ""))},
    {"name": "whatsapp_summary", "args": "{}", "group": "whatsapp",
     "desc": "resumo das mensagens não lidas, por pessoa", "examples": ["resumo do zap"],
     "run": lambda a: whatsapp_summary()},
    {"name": "whatsapp_audios", "args": '{"contact":"nome (vazio = a última conversa)"}', "group": "whatsapp",
     "desc": "transcrever e ler os áudios recebidos no WhatsApp", "examples": ["ouve os áudios da Ana"],
     "run": lambda a: whatsapp_audios(a.get("contact", ""))},
    {"name": "whatsapp_send_audio", "args": '{"contact":"nome","seconds":10}', "group": "whatsapp",
     "desc": "gravar um áudio pelo microfone e mandar no WhatsApp (pede confirmação)",
     "examples": ["grava um áudio de 10 segundos pra mãe"],
     "run": lambda a: whatsapp_send_audio(a.get("contact", ""), int(a.get("seconds", 10) or 10))},
    {"name": "list_tabs", "args": "{}", "group": "navegador",
     "desc": "listar as abas do navegador do Jarvis", "examples": ["quais abas estão abertas"], "run": lambda a: B.list_tabs()},
    {"name": "close_tabs", "args": '{"word":"youtube"}', "group": "navegador",
     "desc": "fechar as abas de um site", "examples": ["fecha as abas do YouTube"], "run": lambda a: B.close_tabs(a.get("word", ""))},
    {"name": "switch_tab", "args": '{"word":"gmail"}', "group": "navegador",
     "desc": "voltar para a aba de um site", "examples": ["volta para a aba do Gmail"], "run": lambda a: B.switch_tab(a.get("word", ""))},
    {"name": "summarize_page", "args": "{}", "group": "navegador",
     "desc": "resumir a página aberta", "examples": ["resume essa página"], "run": lambda a: summarize_page()},
    {"name": "read_page_aloud", "args": "{}", "group": "navegador",
     "desc": "ler a página aberta em voz alta (continua, volta, para)", "examples": ["lê essa página em voz alta"],
     "run": lambda a: read_page_aloud()},
    {"name": "favorite_add", "args": '{"name":"nome (opcional)"}', "group": "navegador",
     "desc": "salvar a página aberta nos favoritos", "examples": ["salva essa página nos favoritos"],
     "run": lambda a: favorite_add(a.get("name", ""))},
    {"name": "favorite_open", "args": '{"name":"nome"}', "group": "navegador",
     "desc": "abrir um favorito", "examples": ["abre o favorito receitas"], "run": lambda a: favorite_open(a.get("name", ""))},
    {"name": "favorite_list", "args": "{}", "group": "navegador",
     "desc": "listar os favoritos", "examples": ["quais meus favoritos"], "run": lambda a: favorite_list()},
    {"name": "resume_video", "args": "{}", "group": "mídia",
     "desc": "retomar o vídeo ou a música de onde parou", "examples": ["continua o vídeo de onde parei"],
     "run": lambda a: resume_video()},
    {"name": "send_to_phone", "args": '{"path":"caminho ou número"}', "group": "programas e sites",
     "desc": "mandar um arquivo do PC para o celular", "examples": ["manda esse pdf pro celular"],
     "run": lambda a: C.offer_file(_path_or_folder(a.get("path", "1")))},
    {"name": "set_theme", "args": '{"name":"azul|vermelho|dourado"}', "group": "sistema",
     "desc": "trocar o tema (as cores) do reator", "examples": ["tema vermelho"], "run": lambda a: set_theme(a.get("name", ""))},
    {"name": "write_document", "args": '{"name":"nome do arquivo","text":"texto (parágrafos separados por linha)"}',
     "group": "ler e resumir", "desc": "escrever um documento do Word (.docx) nos Documentos e abrir",
     "examples": ["monta o esqueleto do trabalho de história no Word"],
     "run": lambda a: write_document(a.get("name", ""), a.get("text", ""))},
    {"name": "record_screen", "args": '{"minutes":1}', "group": "mídia",
     "desc": "gravar a tela por alguns minutos (Xbox Game Bar)", "examples": ["grava a tela por 2 minutos"],
     "run": lambda a: MA.record_screen(a.get("minutes", 1))},
    {"name": "summarize_video", "args": '{"url":"link do YouTube (vazio = o vídeo aberto)"}', "group": "mídia",
     "desc": "resumir um vídeo do YouTube pela legenda", "examples": ["resume esse vídeo"],
     "run": lambda a: I.summarize_video(a.get("url") or (B.current_url()[0] if B.is_open() else ""), think)},
    {"name": "make_slides", "args": '{"topic":"tema","slides":8,"level":"faculdade","style":"escuro|claro|vermelho|dourado","where":"pptx|google","contact":"mandar no WhatsApp para (vazio = não manda; eu = o senhor)","extra":"pedidos do aluno"}',
     "group": "ler e resumir", "desc": "fazer uma apresentação de slides bonita sobre um tema (PowerPoint ou Google Slides), "
                                      "salvar, abrir e mandar no WhatsApp se pedir",
     "examples": ["faz um slide sobre a Revolução Francesa com 8 slides e manda pra mim no zap"],
     "run": lambda a: make_slides(a.get("topic", ""), a.get("slides", 8), a.get("level", "faculdade"),
                                  a.get("style", "escuro"), a.get("where", ""), a.get("contact", ""), a.get("extra", ""))},
    {"name": "show_help", "args": "{}", "group": "sistema",
     "desc": "mostrar tudo o que eu sei fazer", "examples": ["o que você sabe fazer"],
     "run": lambda a: show_help()},
]
TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}

AI_EXAMPLES = [
    ("põe o som no talo", '{"actions":[{"name":"set_volume","args":{"percent":100}}],"reply":"Volume no máximo."}'),
    ("tá muito alto", '{"actions":[{"name":"change_volume","args":{"delta":-20}}],"reply":"Abaixei."}'),
    ("quero jogar omori", '{"actions":[{"name":"open_target","args":{"target":"omori"}}],"reply":"Abrindo o Omori."}'),
    ("bota uma música lofi pra mim", '{"actions":[{"name":"play_youtube","args":{"query":"lofi"}}],"reply":"Tocando lofi."}'),
    ("coloca o volume em 70 e abre a música evidências no youtube", '{"actions":[{"name":"set_volume","args":{"percent":70}},{"name":"play_youtube","args":{"query":"evidências"}}],"reply":"Volume 70 e tocando Evidências."}'),
    ("pula esse vídeo", '{"actions":[{"name":"youtube_control","args":{"action":"proximo"}}],"reply":"Próximo."}'),
    ("cadê aquele pdf do FO 1102", '{"actions":[{"name":"search_files","args":{"query":"FO 1102"}}],"reply":"Procurando."}'),
    ("me mostra meus downloads", '{"actions":[{"name":"open_folder","args":{"name":"downloads"}}],"reply":"Abrindo Downloads."}'),
    ("modo estudo", '{"actions":[{"name":"run_routine","args":{"name":"estudo"}}],"reply":"Modo estudo ativado."}'),
    ("abre o bloco de notas e escreve lista de compras", '{"actions":[{"name":"open_target","args":{"target":"notepad"}},{"name":"type_text","args":{"text":"lista de compras"}}],"reply":"Feito."}'),
    ("vai chover hoje em recife?", '{"actions":[{"name":"weather","args":{"city":"Recife"}}],"reply":"Olha o clima em Recife."}'),
    ("o pc tá lento", '{"actions":[{"name":"list_processes","args":{}},{"name":"system_info","args":{}}],"reply":"Esses são os programas que mais pesam."}'),
    ("joga esse arquivo na lixeira", '{"actions":[{"name":"delete_item","args":{"path":"1"}}],"reply":"Vou pedir confirmação."}'),
    ("faz um resumo do segundo", '{"actions":[{"name":"summarize_file","args":{"path":"2"}}],"reply":"Resumindo."}'),
    ("abre o bloco de notas e me explica quem foi Tiradentes", '{"actions":[{"name":"open_target","args":{"target":"notepad"}},{"name":"type_text","args":{"text":"Tiradentes (Joaquim José da Silva Xavier) foi um dos líderes da Inconfidência Mineira, movimento contra o domínio português em 1789. Foi enforcado em 1792 e hoje é considerado herói nacional."}}],"reply":"Escrevi no Bloco de Notas."}'),
    ("escolhe a melhor receita de bolo de cenoura", '{"actions":[{"name":"web_search","args":{"query":"melhor receita bolo de cenoura"}}],"reply":"Pesquisando receitas.","continue":true}'),
    ("(depois de ver os resultados) 1. Bolo de cenoura fofinho - tudogostoso... 2. ...", '{"actions":[{"name":"web_click","args":{"target":"1"}},{"name":"web_read","args":{}}],"reply":"Vou ler a mais bem avaliada.","continue":true}'),
    ("manda pra Ana que eu chego às 8", '{"actions":[{"name":"whatsapp_send","args":{"contact":"Ana","message":"Chego às 8"}}],"reply":"Pronto."}'),
    ("me explica o que é fotossíntese", '{"actions":[],"reply":"É o processo em que as plantas usam luz, água e gás carbônico para produzir açúcar e liberar oxigênio."}'),
    (f"oi {NAME.lower()}, tudo bem?", '{"actions":[],"reply":"Tudo certo! Diga o que precisa."}'),
    ("faz um bolo pra mim", '{"actions":[],"reply":"Isso eu não consigo fazer. Diga \\"o que você sabe fazer\\" para ver a lista."}'),
    ("calma mano, eu tipo, não tenho um negócio, é que", '{"actions":[],"reply":"Sem pressa, senhor. O que o senhor quer que eu faça?"}'),
]


PERSONALITY = {
    "serio": "Personalidade escolhida pelo senhor: SÉRIO. Nada de piadas; respostas formais e objetivas.",
    "humor": "Personalidade escolhida pelo senhor: HUMOR SECO. Uma tirada elegante de mordomo inglês quando couber.",
    "curto": "Personalidade escolhida pelo senhor: CURTO. Responda com o mínimo de palavras (uma frase).",
    "detalhado": "Personalidade escolhida pelo senhor: DETALHADO. Explique um pouco mais quando ajudar.",
}


def personality():
    try:
        return normalize(M.load()["perfil"].get("personalidade", ""))
    except Exception:
        return ""


def build_ai_prompt(tools=None, native=False):
    tools = TOOLS if tools is None else tools
    listed = "\n".join(f"{t['name']} {t['args']} - {t['desc']}" for t in tools)
    examples = "\n".join(f"Usuário: {u}\nJSON: {j}" for u, j in AI_EXAMPLES
                         if tools is TOOLS or any(f'"{t["name"]}"' in j for t in tools) or '"actions":[]' in j)
    style = PERSONALITY.get(personality(), "")
    if native:
        head = ("Para agir, chame as ferramentas (function calling); pode chamar várias. Em conversa ou pergunta de "
                "conhecimento, responda só em texto curto. Se precisar VER o resultado de uma ferramenta antes de "
                "terminar, passe _continuar=true nela.")
        tool_part = ""
    else:
        head = ('Responda SOMENTE JSON válido, sem explicações, neste formato:\n'
                '{"actions":[{"name":"acao","args":{}}],"reply":"frase curta","continue":false}')
        tool_part = f"\nFerramentas disponíveis (use só estas, com estes nomes):\n{listed}\n"
    return f"""Seu nome é {NAME}: você é o assistente do Windows do usuário. Fala português do Brasil como um mordomo
calmo, educado e um pouco espirituoso, chamando o usuário de "senhor". Curto e direto: suas respostas são faladas em voz alta.
Entrega de mordomo: sóbrio, preciso e seguro. Use frases curtas com pontuação natural para pausas.
Tom neutro no cotidiano, sério em avisos e confirmações; humor seco só quando combinar.
Sem entusiasmo exagerado, exclamações repetidas ou instruções de atuação entre colchetes.
Não repita sempre as mesmas frases: varie o jeito de confirmar.
{style}
{head}
{tool_part}
Regras:
- abrir, executar, rodar ou jogar um programa/jogo = open_target com o nome do programa
- um número sozinho ("2") depois de uma busca = open_search_result com esse índice
- "ele", "esse", "o primeiro" se referem aos resultados da última busca
- system_info só quando pedirem RAM, CPU ou disco
- pode usar várias ações em sequência
- conversa ou pergunta de conhecimento: actions vazio e a resposta (curta, até 3 frases) em reply
- se pedir para abrir um programa E escrever/explicar algo, abra e use type_text com o texto
- música "no Spotify" (ou junto com abrir o Spotify) = spotify_play, NUNCA play_youtube
- tocar/ouvir/abrir uma música ou vídeo = play_youtube (toca direto); search_web youtube só se pedir para ver a lista
- pausar, pular, tela cheia, avançar no vídeo aberto = youtube_control
- PROATIVO: depois de fazer o pedido, SÓ quando for realmente útil, ofereça em reply UM próximo passo curto em
  forma de pergunta, ligado ao que ele pediu ou à hora ("Tocando lofi. Quer que eu deixe o WhatsApp em silêncio
  enquanto estuda?"). Não ofereça em pedidos simples (volume, pausa) nem repita a mesma oferta.
- MODO CICLO: se precisar VER o resultado antes de decidir (pesquisar na web, ler página, procurar arquivo,
  escolher entre opções), faça essa ação e coloque "continue":true. Você recebe o resultado e decide o
  próximo passo. Quando terminar, "continue":false e a resposta final em reply (até 5 frases)
- pergunta de fato ATUAL (notícia, eleição, placar, cotação, "quem ganhou", "o que aconteceu") = research (a janela com o resultado aparece na tela).
  SEMPRE chame research de novo, mesmo que a conversa recente diga que a pesquisa falhou ou a cota acabou: nunca responda de memória que não dá.
  Em query mande uma busca curta, como num buscador: só as palavras-chave, sem "oi", "tudo bem", "como está"; inclua o ano
  quando ajudar e resolva "isso/ele" pela conversa ("e o Lula?" depois de falar da eleição = "Lula eleições 2026 pesquisa").
  Em reply diga só algo curto como "Verificando, senhor." (o resultado da pesquisa é falado sozinho)
- pesquisar para escolher/comparar/responder = web_search, depois web_click no melhor e web_read
- mandar mensagem no WhatsApp = whatsapp_send (ele mesmo pede confirmação)
- ler/ver mensagens do WhatsApp ("tem mensagem nova?", "o que a Ana mandou?") = whatsapp_read
- use o perfil, as coisas lembradas e a conversa recente (no começo do pedido) para entender "e amanhã?", "lá", "ele"
- clima sem cidade = cidade do perfil. Datas relativas ("sexta", "amanhã") viram AAAA-MM-DD a partir de "Agora"
- "me acorda às 7h" / "despertador às 6h30 com tal música" = set_alarm (NÃO schedule_request)
- pedido para FAZER algo num horário ("coloca tal música às 7h", "amanhã 8h abre o Spotify") = schedule_request
  com o pedido escrito como o senhor falaria; só AVISAR de algo ("me lembra da prova") = add_reminder
- "lembra que tenho prova sexta" = add_reminder; algo sem data ("sou alérgico a camarão") = remember;
  nome, cidade, gostos = set_profile
- se nenhuma ferramenta serve, diga isso em reply; nunca finja que fez
- fala pela metade, pensando alto ("tipo...", "é que...", "calma", "espera"), reclamação ou desabafo
  SEM um pedido claro = actions vazio (NUNCA pesquise só porque não entendeu); pergunte em reply o que ele quer
- em dúvida entre duas ou mais opções (dois arquivos, dois contatos), use ask_choice com as opções e continue
- uma habilidade combina com o pedido = use_skill com o nome dela e siga a receita que voltar
- pedidos sobre o que está na tela ("o que é isso?", "qual o erro aqui?") = look_screen com a pergunta
- botões e campos de programas: click_ui, fill_field, read_window; para tarefas de vários passos num programa = agent_task

Exemplos:
{examples}
"""


AI_PROMPT = build_ai_prompt()


def execute_ai_action(name, args):
    tool = TOOLS_BY_NAME.get(name)
    if not tool:
        print(f"Jarvis > Ação desconhecida: {name}")
        return False
    log_action(f"ia:{name}", json.dumps(args, ensure_ascii=False))
    opening(name)
    try:
        with D.timing("fazer"):
            result = tool["run"](args)
    except Exception as e:
        print(f"Jarvis > Erro em {name}: {e}")
        D.action(name, args, False)
        return False
    D.action(name, args, result is not False)
    learn_from_action(name, args, result)
    return result


def active_window_title():
    try:
        u32 = ctypes.windll.user32
        hwnd = u32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


def ai_context(request=""):
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    now = datetime.now()
    parts = [f"Agora: {now:%Y-%m-%d %H:%M} ({dias[now.weekday()]})"]
    memory = M.context()
    if memory:
        parts.append(memory)
    title = F.user_window_title() or active_window_title()
    if title:
        parts.append(f"Janela ativa: {title}")
    if last_results:
        lines = "\n".join(f"{i}. {Path(p).name}" for i, p in enumerate(last_results[:10], 1))
        parts.append(f"Resultados da última busca:\n{lines}")
    if request:
        try:
            learned = A.examples_prompt(request)
        except Exception:
            learned = ""
        if learned:
            parts.append(learned)
        try:
            skills = H.prompt_for(request)
        except Exception:
            skills = ""
        if skills:
            parts.append(skills)
    return "\n".join(parts) + "\n\nPedido: "


OPENS_WINDOW = {"open_target", "open_url", "open_folder", "open_search_result", "focus_window", "open_settings"}


def ask_local(system, user, json_mode=True, num_predict=None, temperature=None):
    if chat is None:
        raise RuntimeError("Ollama não instalado (python -m pip install ollama)")
    options = dict(AI_OPTIONS)
    if num_predict:
        options["num_predict"] = num_predict
    if temperature is not None:
        options["temperature"] = temperature
    response = chat(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        format="json" if json_mode else "",
        think=False,
        stream=False,
        keep_alive=KEEP_ALIVE,
        options=options,
    )
    return (response.message.content or "").strip()


def ask_cloud(system, user, json_mode=True, num_predict=None, temperature=None):
    # o Gemini Flash "pensa" antes de responder e esse raciocínio gasta o mesmo limite de tokens
    return N.generate(system, user, json_mode=json_mode, temperature=temperature or 0.0,
                      max_tokens=max(8192, num_predict or 0))


def ask_groq(system, user, json_mode=True, num_predict=None, temperature=None):
    # pedir pouco: o Groq grátis conta o max_tokens no limite por minuto
    return N.groq_generate(system, user, json_mode=json_mode, temperature=temperature or 0.0,
                           max_tokens=num_predict or 1024)


def local_enabled():
    """O Jarvis é só online; o Qwen local só entra com  setx JARVIS_LOCAL 1."""
    return os.environ.get("JARVIS_LOCAL", "").strip() == "1"


def ai_backends(prefer=None):
    """Ordem de quem pensa: Gemini, depois Groq (e o Qwen só se JARVIS_LOCAL=1). prefer="Groq" põe o Groq
    na frente (pedido simples: ele responde mais rápido)."""
    order = []
    if N.available():
        order.append(("Gemini", ask_cloud))
    if N.groq_available():
        order.append(("Groq", ask_groq))
    if prefer:
        order.sort(key=lambda b: b[0] != prefer)
    if local_enabled():
        order.append(("Qwen", ask_local))
    return order


def think(system, user, parse=None, skip=(), prefer=None, **kw):
    """Pergunta para a primeira IA disponível; se falhar (ou a resposta não servir), tenta a próxima."""
    errors = []
    for name, fn in ai_backends(prefer):
        if name in skip:
            continue
        try:
            with D.timing("pensar"):
                text = fn(system, user, **kw)
            if text:
                result = parse(text) if parse else text
                if errors:
                    print(f"Jarvis > ({'; '.join(errors)}; respondi com o {name})")
                return result
        except Exception as e:
            errors.append(f"{name} falhou: {e}")
    raise RuntimeError("; ".join(errors) or "nenhuma IA configurada (setx GEMINI_API_KEY ou GROQ_API_KEY)")


def parse_json(raw):
    """O objeto JSON da resposta da IA, mesmo com ```json, texto antes ou dentro de uma lista."""
    raw = str(raw).strip()
    start = raw.find("{")
    if start < 0:
        raise ValueError("a IA não devolveu JSON")
    if raw.startswith("[") and raw.find("[") < start:  # [{"name":...}, ...] = só a lista de ações
        try:
            items, _ = json.JSONDecoder().raw_decode(raw)
            if isinstance(items, list) and all(isinstance(a, dict) and "name" in a for a in items):
                return {"actions": items, "reply": ""}
        except ValueError:
            pass
    data, _ = json.JSONDecoder().raw_decode(raw[start:])
    if not isinstance(data, dict):
        raise ValueError("a IA não devolveu um objeto JSON")
    data["actions"] = [a for a in (data.get("actions") or []) if isinstance(a, dict)]
    return data


MAX_STEPS = 6  # teto do modo ciclo, para não gastar o limite grátis da nuvem
MAX_SEEN = 2500  # quanto do resultado de cada ação volta para a IA


class _Tee(io.StringIO):
    """Mostra na tela e guarda o que a ferramenta escreveu, para a IA ver o resultado.
    Só guarda o que vem da thread do pedido (a voz e os timers também escrevem na tela)."""

    def __init__(self, screen):
        super().__init__()
        self.screen = screen
        self.owner = threading.get_ident()

    def write(self, text):
        self.screen.write(text)
        if threading.get_ident() == self.owner:
            return super().write(text)
        return len(text)

    def flush(self):
        self.screen.flush()


def run_actions(actions):
    """Executa as ações; devolve as que falharam e o que cada uma mostrou."""
    failed, seen = [], []
    for i, action in enumerate(actions):
        if stop_event.is_set():  # o PARAR no meio de várias ações
            break
        name = str(action.get("name", ""))
        args = action.get("args", {})
        args = args if isinstance(args, dict) else {}
        before = F.foreground_window()
        tee = _Tee(sys.stdout)
        with contextlib.redirect_stdout(tee):
            result = execute_ai_action(name, args)
        if result is False:
            failed.append(name)
        elif name in OPENS_WINDOW and i + 1 < len(actions):
            F.wait_new_window(before)  # espera a janela abrir antes de digitar/clicar nela
        shown = tee.getvalue().strip()
        if isinstance(result, str) and result not in shown:
            shown = (shown + "\n" + result).strip()
        status = "FALHOU" if result is False else "ok"
        seen.append(f"- {name} {json.dumps(args, ensure_ascii=False)} -> {status}\n{shown[:MAX_SEEN]}")
    return failed, seen


# Ferramentas cuja própria fala é a resposta do pedido (o que acharam): a "reply" da IA não fica por cima
ANSWER_TOOLS = {"research", "whatsapp_send", "whatsapp_send_file"}


def _failure_reason(entry):
    """O que uma ação que FALHOU disse (a última linha "Jarvis > ..."), ou "" se não disse nada."""
    head, _, shown = entry.partition("\n")
    if not head.endswith("-> FALHOU"):
        return ""
    said = [line for line in shown.splitlines() if line.startswith("Jarvis > ") and not line.startswith("Jarvis > (")]
    return said[-1] if said else ""


# ===================== CÉREBRO: quem decide, com quais ferramentas (14) =====================
# ferramentas que sempre vão para a IA; as outras entram só quando o pedido fala do assunto delas
CORE_TOOLS = ["open_target", "play_youtube", "set_volume", "change_volume", "media_control", "search_files",
              "open_search_result", "research", "web_search", "weather", "type_text", "press_keys", "window_control",
              "add_reminder", "schedule_request", "remember", "set_profile", "use_skill", "ask_choice", "click_ui",
              "look_screen", "whatsapp_send", "close_app", "open_url", "spotify_play"]
MAX_TOOLS = 34
HEAVY = re.compile(r"\b(?:explica|explique|resume|resuma|resumo|escreve|escreva|redacao|texto sobre|carta|traduz|traduza|"
                   r"tela|imagem|foto|documento|contrato|pdf|compara|compare|analisa|analise|detalh|passo a passo|"
                   r"agente|planeja|planeje|receita)\w*")


def is_heavy(text):
    """Pedido pesado (texto longo, tela, documento, explicação): o Gemini decide. O resto, o Groq (mais rápido)."""
    return len(str(text)) > 280 or bool(HEAVY.search(normalize(text)))


def _stems(text):
    return {w[:5] for w in re.findall(r"[a-z0-9]+", normalize(text)) if len(w) > 2}


def select_tools(request, n=MAX_TOOLS):
    """As ferramentas que a IA vê neste pedido: as de sempre e as que combinam com as palavras dele (menos
    texto para a IA ler = resposta mais rápida e menos cota gasta)."""
    want = _stems(request)
    try:
        for _, acts in A.examples_for(request):  # o que deu certo antes em pedido parecido
            want |= {a["name"][:5] for a in acts}
            want |= {f"@{a['name']}" for a in acts}
    except Exception:
        pass
    scored = []
    for t in TOOLS:
        if t["name"] in CORE_TOOLS:
            continue
        hay = _stems(" ".join([t["name"].replace("_", " "), t["desc"], " ".join(t["examples"]), t["group"]]))
        score = len(want & hay) + (5 if f"@{t['name']}" in want else 0)
        if score:
            scored.append((score, t))
    scored.sort(key=lambda x: -x[0])
    picked = [TOOLS_BY_NAME[name] for name in CORE_TOOLS if name in TOOLS_BY_NAME]
    picked += [t for _, t in scored[: max(0, n - len(picked))]]
    return picked


def _schema_value(raw):
    raw = raw.strip()
    if raw.startswith('"'):
        return {"type": "string", "description": raw.strip('"')[:120]}
    if raw.startswith("["):
        inner = raw[1:].lstrip()
        return {"type": "array", "items": {"type": "array", "items": {"type": "string"}} if inner.startswith("[")
                else {"type": "string"}}
    if re.match(r"^(?:true|false)", raw):
        return {"type": "boolean"}
    if re.match(r"^-?\d", raw):
        return {"type": "number", "description": raw[:60]}
    return {"type": "string", "description": raw[:60]}


def _template_args(template):
    """'{"query":"texto","site":"google|youtube"}' -> [("query", '"texto"'), ("site", '"google|youtube"')]."""
    out, i, text = [], 0, str(template).strip()[1:-1]
    while i < len(text):
        m = re.compile(r'\s*"(\w+)"\s*:\s*').match(text, i)
        if not m:
            break
        i, depth, quote, start = m.end(), 0, False, m.end()
        while i < len(text):
            c = text[i]
            if c == '"' and text[i - 1] != "\\":
                quote = not quote
            elif not quote and c in "[{":
                depth += 1
            elif not quote and c in "]}":
                depth -= 1
            elif not quote and c == "," and depth == 0:
                break
            i += 1
        out.append((m.group(1), text[start:i]))
        i += 1
    return out


def tool_schemas(tools):
    """O catálogo no formato de chamada nativa (OpenAI/Groq)."""
    out = []
    for t in tools:
        props = {k: _schema_value(v) for k, v in _template_args(t["args"])}
        props["_continuar"] = {"type": "boolean", "description": "true se precisa ver o resultado antes de terminar"}
        out.append({"type": "function", "function": {"name": t["name"], "description": t["desc"][:300],
                                                     "parameters": {"type": "object", "properties": props}}})
    return out


def native_tools_on():
    return os.environ.get("BOLHA_FERRAMENTAS_NATIVAS", "").strip() != "0"


def decide(user_text, prompt, tools):
    """A IA escolhe as ações: o Groq com as ferramentas nativas no pedido simples; o Gemini (JSON) no pesado,
    e cada um é reserva do outro."""
    heavy = is_heavy(user_text)
    if not heavy and N.groq_available() and native_tools_on():
        try:
            with D.timing("pensar"):
                data = N.groq_tools(build_ai_prompt(tools, native=True), prompt, tool_schemas(tools))
            more = False
            for a in data["actions"]:
                more = more or bool(a["args"].pop("_continuar", False))
            data["continue"] = more
            return data
        except Exception as e:
            print(f"Jarvis > (ferramentas nativas do Groq falharam: {str(e)[:120]}; usando o modo de texto)")
    return think(build_ai_prompt(tools), prompt, parse=parse_json, prefer=None if heavy else "Groq")


FILLERS = ["Verificando, senhor.", "Um instante, senhor.", "Já vejo, senhor.", "Só um momento, senhor."]


def ask_ai_router(user_text, steps=None, agent=False):
    """Modo ciclo: a IA age, vê o resultado e decide o próximo passo, até terminar."""
    max_steps = steps or MAX_STEPS
    history, done = [], []
    D.route("ia")
    backends = ai_backends()
    # o Qwen local guarda o começo do prompt em cache: com ele, o catálogo vai sempre inteiro e igual
    tools = TOOLS if backends and backends[0][0] == "Qwen" else select_tools(user_text)
    if voice_out and origin == "voz" and ai_backends():  # 6/16: começa a falar na hora, enquanto a IA pensa
        try:
            V.say_async(vary(FILLERS), set_state)
        except Exception:
            pass
    for step in range(max_steps):
        if stop_event.is_set():
            print("Jarvis > Parei, senhor.")
            return True
        prompt = ai_context(user_text) + user_text
        if history:
            prompt += ("\n\nO que você já fez neste pedido e o resultado de cada ação:\n"
                       + "\n".join(history) + "\n\nDecida o próximo passo ou termine.")
        try:
            data = decide(user_text, prompt, tools)
            if not isinstance(data, dict):
                data = parse_json(data)
        except Exception as e:
            if ai_backends() and not AT.internet():
                print(f"Jarvis > {AT.OFFLINE_MSG}")  # 108: sem internet só os comandos locais
            else:
                print(f"Jarvis > Não consegui falar com a IA: {e}")
            return False

        actions = data["actions"]
        if agent and actions:  # cada passo do agente aparece num card com o PARAR
            U.card("Agente", json.dumps({"titulo": f"Passo {step + 1}", "texto": "; ".join(
                f"{a.get('name')} {' '.join(str(v) for v in (a.get('args') or {}).values())}" for a in actions)[:300],
                "botao": "PARAR", "pedido": "para o agente"}, ensure_ascii=False), 60000)
        failed, seen = run_actions(actions)
        history += seen
        done += actions
        if any(str(a.get("name", "")) in ANSWER_TOOLS and str(a.get("name", "")) not in failed for a in actions):
            # a pesquisa já disse o que achou: a frase da IA ("Buscando informações...") foi escrita antes
            # de ver o resultado e não pode ficar por cima da resposta, nem gastar outra volta da IA
            return True
        reply = str(data.get("reply") or "").strip()
        more = data.get("continue") is True or str(data.get("continue")).lower() == "true"
        if any(str(a.get("name")) == "use_skill" for a in actions) and "use_skill" not in failed:
            more = True  # carregou a receita: a IA precisa ver e seguir
        if more and actions:
            if step + 1 < max_steps:
                if reply:
                    print(f"Jarvis > {reply}")
                continue
            print("Jarvis > Parei aqui para não gastar o limite grátis da IA; o que achei está na tela.")
            return True
        if failed:
            # a ferramenta que falhou já disse o motivo ("Não consegui pesquisar agora..."): ele fica na legenda
            if not any(_failure_reason(entry) for entry in seen):
                print(f"Jarvis > Não deu certo: {', '.join(failed)}.")
        else:
            if reply:
                print(f"Jarvis > {reply}")
            if step == 0 and done and not any(str(a.get("name")) in NO_EXAMPLE for a in done):
                try:  # M3: acerto de primeira vira exemplo para os pedidos parecidos
                    A.learn_example(user_text, done)
                except Exception:
                    pass
        return True
    return True


# ações que não viram exemplo (dependem do momento ou mandam algo para alguém)
NO_EXAMPLE = {"whatsapp_send", "whatsapp_send_file", "delete_item", "instagram_reply", "instagram_post",
              "web_click", "web_fill", "web_key", "open_search_result", "show_search_result", "type_text"}


def warm_up_ai():
    """Carrega o Qwen e já processa o prompt do catálogo em segundo plano.
    O Ollama guarda esse começo em cache, então os pedidos seguintes só processam a frase nova.
    Com a nuvem na frente, o Qwen fica quieto (sem gastar CPU) até ser preciso."""
    backends = ai_backends()
    if chat is None or not backends or backends[0][0] != "Qwen":
        return
    try:
        chat(
            model=MODEL,
            messages=[{"role": "system", "content": AI_PROMPT}, {"role": "user", "content": "oi"}],
            format="json",
            think=False,
            stream=False,
            keep_alive=KEEP_ALIVE,
            options={**AI_OPTIONS, "num_predict": 1},
        )
    except Exception:
        pass


SMALL_TALK = [
    (rf"^(oi|ola|opa|eai|e ai|fala|salve|bom dia|boa tarde|boa noite|hey),?( {CALL})?[!. ]*$",
     ["Às suas ordens, senhor.", "Pois não, senhor?", "Olá, senhor. Em que posso ajudar?", "Estou aqui, senhor."]),
    (rf"^(oi |ola |e ai |fala )?({CALL},? )?(tudo bem|tudo certo|como (voce|vc) esta|beleza)( {CALL})?\??$", ["Tudo em ordem por aqui, senhor. E com o senhor?", "Todos os sistemas funcionando, senhor.",
      "Tudo certo, senhor. Em que posso ajudar?"]),
    (rf"^(obrigad[oa]|valeu|vlw|brigad[oa]|show|top|massa|perfeito),?( {CALL})?[!. ]*$",
     ["Por nada, senhor.", "Sempre às ordens, senhor.", "É um prazer, senhor.", "Disponha, senhor."]),
    (rf"^({CALL},? )?(quem e voce|quem e vc|qual (e )?(o )?seu nome)\??$",
     f"Meu nome é {NAME}, seu assistente do Windows. Diga \"o que você sabe fazer\"."),
    # "calma", "peraí", "deixa eu pensar": ainda não é um pedido, então não faz nada
    (rf"^({CALL},? )?(calma|espera|espere|pera|perai|pera ai|aguarda|aguenta ai|um momento|um minuto|"
     rf"so um (momento|minuto|segundo)|deixa eu (pensar|ver|lembrar))((,? )(mano|ai|ae|{CALL}))*[!.,? ]*$",
     ["Tudo bem, senhor. Pode falar quando quiser.", "Sem pressa, senhor.", "Aguardo, senhor."]),
]
# "eu não falei o que quero ainda", "não pesquisa quando eu mandar algo assim": a fala não era pedido
END = r"(?=\s*(?:[,.!?]|$))"  # fim da frase: "ainda não falei com a Ana, manda..." é pedido
NOT_A_REQUEST = re.compile(rf"\b(?:ainda nao (?:te )?(?:falei|disse|pedi)(?: o que (?:eu )?quero| nada)?{END}"
                           rf"|nao (?:te )?(?:falei|disse|pedi) (?:o que (?:eu )?quero|nada) ainda"
                           rf"|nao (?:te )?(?:falei|disse|pedi) ainda{END}|nao (?:era|e) (?:um )?pedido|nao (?:te )?pedi nada)")


def small_talk(clean):
    for pattern, answer in SMALL_TALK:
        if re.search(pattern, clean):
            print(f"Jarvis > {vary(answer) if isinstance(answer, list) else answer}")  # 19: não repete sempre igual
            return True
    if NOT_A_REQUEST.search(clean):
        print("Jarvis > Entendido, senhor. Só faço algo quando o senhor terminar de dizer o que quer.")
        return True
    return False


def set_state(state):
    """parado | ouvindo | pensando | falando: o reator muda junto."""
    U.state(state)


def speak(text):
    """Fala em voz alta. Se o pedido veio do celular, a voz toca no celular e o PC fica quieto. Desliga com --mudo."""
    if not voice_out:
        return
    try:
        if origin == "celular" and C.running():
            C.say(text)
        else:
            V.say(text, set_state)
    except Exception as e:
        print(f"Jarvis > (não consegui falar: {e})")
    finally:
        set_state("parado")  # se a fala falhar, o reator não fica preso em "pensando"


# ========================= DESPERTADOR =========================
# "me acorda às 7h": às 7h toca a música e espera o botão ACORDEI (ou "Bolha, acordei"). Aí pausa,
# dá bom dia com o clima, a roupa para o dia e as principais notícias, e termina com a música do bom dia.
MUSICA_DESPERTAR = os.environ.get("BOLHA_MUSICA_DESPERTAR", "").strip()
MUSICA_BOM_DIA = os.environ.get("BOLHA_MUSICA_BOM_DIA", "").strip() or "Arctic Monkeys - Do I Wanna Know?"
WAIT_AWAKE = 30 * 60  # meia hora tocando sem ninguém apertar ACORDEI: para a música
SNOOZE = re.compile(r"\bmais (\d{1,2}) ?(?:min|minutos?)\b|\bsoneca(?: de (\d{1,2}))?\b|\bso mais um pouco\b|\bdeixa eu dormir mais\b")
AWAKE = re.compile(r"\b(?:acordei|acordad[oa]|levantei|desliga|desligar|para|pare|chega|ja to de pe)\b")
MORNING_PROMPT = (
    "Você é {name}, o mordomo do João, que o chama de senhor. Ele acabou de acordar. Fale em voz alta, em português "
    "do Brasil, de 4 a 6 frases curtas: comece com \"Bom dia, senhor.\", diga o clima de hoje com números por extenso, "
    "recomende a roupa para o dia (casaco, blusa, roupa leve, guarda-chuva) de acordo com o clima, conte as 3 notícias "
    "mais importantes em uma frase cada, se houver lembretes de hoje diga-os e, se fizer sentido, dê UMA sugestão útil "
    "para o dia; termine com \"Tenha um bom dia, senhor.\". Use só os dados recebidos. "
    "Sem emojis, sem markdown, sem símbolos como °C ou %."
)


def set_alarm(hour, day="", music=""):
    """Marca o despertador. Sem dia: a próxima vez que der essa hora (hoje ou amanhã)."""
    m = re.fullmatch(r"\s*(\d{1,2})(?:\s*(?:h|:|horas?)\s*(\d{2})?)?(?::\d{2})?\s*", str(hour or "").lower())
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        print(f"Jarvis > A que horas o senhor quer acordar?")
        return False
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if not str(day or "").strip():
        now = datetime.now()
        day = (now.date() if (h, mi) > (now.hour, now.minute) else now.date() + timedelta(days=1)).isoformat()
    return M.add_reminder(str(music or "").strip(), day, f"{h:02d}:{mi:02d}", despertador=True)


def _roupa(temp, sky):
    """Recomendação simples de roupa pelo clima (usada se a IA não responder)."""
    if temp < 12:
        dica = "um casaco bem quente"
    elif temp < 18:
        dica = "uma jaqueta ou blusa de frio"
    elif temp < 24:
        dica = "roupa leve, com uma blusa à mão"
    else:
        dica = "roupa leve"
    if re.search(r"chuv|garoa|tempestade|trovo", normalize(sky)):
        dica += " e o guarda-chuva"
    return dica


def _acorda_tela():
    """Liga o monitor que apagou por economia de energia (um mexidinho no mouse) e não deixa apagar de novo agora."""
    try:
        u32 = ctypes.windll.user32
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000002)  # ES_CONTINUOUS | ES_DISPLAY_REQUIRED
        u32.mouse_event(0x0001, 1, 0, 0, 0)  # MOUSEEVENTF_MOVE: 1 pixel para lá e para cá
        u32.mouse_event(0x0001, -1 & 0xFFFFFFFF, 0, 0, 0)
    except Exception:
        pass  # fora do Windows (testes) não faz nada


def _wait_awake(seconds=WAIT_AWAKE):
    """Espera o ACORDEI (botão, voz ou digitado). Outros pedidos ficam para depois."""
    deadline, later = time.time() + seconds, []
    try:
        while (left := deadline - time.time()) > 0:
            try:
                source, text = commands.get(timeout=left)
            except queue.Empty:
                break
            said = normalize(text or "")
            if source not in ("lembrete", "agendado", "despertador", "aviso", "alerta"):
                m = SNOOZE.search(said)
                if m:  # "mais 10 minutos": soneca (86)
                    return int(m.group(1) or m.group(2) or 10)
                if AWAKE.search(said):
                    return True
            later.append((source, text))
        return False
    finally:
        for item in later:
            commands.put(item)


def wake_up(music=""):
    """A hora do despertador: música até apertar ACORDEI, depois o bom dia."""
    music = "" if music == "padrão" else music
    _acorda_tela()
    U.front(True)  # vem para a frente na tela principal, mesmo minimizado ou atrás de outra janela
    print("Jarvis > (despertador) Hora de acordar, senhor.")
    play_youtube(music or MUSICA_DESPERTAR or MUSICA_BOM_DIA)
    # o YouTube abre por cima: o Bolha volta para a frente (de novo depois, o navegador demora a carregar),
    # para o ACORDEI estar na tela quando o senhor abrir o olho
    U.front(True)
    for wait in (3, 8):
        threading.Timer(wait, U.front, args=(True,)).start()
    U.card("Despertador", datetime.now().strftime("%H:%M"), WAIT_AWAKE * 1000)
    U.speech("Hora de acordar, senhor. Aperte ACORDEI quando estiver de pé.")
    if listener is not None:
        listener.ask_answer()  # dá para dizer "acordei" sem chamar o nome
    awake = _wait_awake()
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # o monitor volta a poder apagar
    except Exception:
        pass
    youtube_control("pausar")
    if awake is not True and awake:  # soneca
        when = datetime.now() + timedelta(minutes=awake)
        M.add_reminder(music or "padrão", when.date().isoformat(), when.strftime("%H:%M"), despertador=True)
        print(f"Jarvis > Mais {awake} minutos, senhor. Toco de novo às {when:%H:%M}.")
        set_state("parado")
        return False
    if not awake:
        print("Jarvis > (despertador: ninguém apertou ACORDEI em 30 minutos; parei a música)")
        set_state("parado")
        return False
    morning_brief()
    return True


def morning_brief():
    """Bom dia com clima, roupa e notícias; no fim, a música do bom dia."""
    set_state("pensando")
    U.speech("Bom dia, senhor. Um instante...")
    tee = _Tee(sys.stdout)
    with contextlib.redirect_stdout(tee):
        try:
            F.weather(M.load()["perfil"].get("cidade", ""))
        except Exception:
            pass
    weather = next((line[len("Jarvis > "):] for line in tee.getvalue().splitlines() if CLIMA.match(line[len("Jarvis > "):])), "")
    try:
        news = F.web_snippets("principais notícias hoje Brasil", 5)
    except Exception:
        news = []
    if weather:
        U.card("Clima", weather, 120000)
    if news:
        U.card("Pesquisa · notícias", json.dumps({
            "tema": "notícias", "titulo": "Principais notícias de hoje", "pontos": [n["titulo"] for n in news[:5]],
            "fontes": [{"nome": n["site"], "titulo": n["titulo"]} for n in news[:4]], "hora": time.strftime("%H:%M")},
            ensure_ascii=False), 120000)
    try:
        today = [r["texto"] for r in M.load()["lembretes"] if r.get("data") == datetime.now().date().isoformat()
                 and not r.get("despertador")]
    except Exception:
        today = []
    data = (f"Clima: {weather or 'não consegui ver'}\nLembretes de hoje: {'; '.join(today) or 'nenhum'}\nNotícias:\n"
            + "\n".join(f"- {n['titulo']} ({n['site']})" for n in news[:5]))
    text = ""
    try:
        text = re.sub(r"[*_#`]", "", str(think(MORNING_PROMPT.format(name=NAME), data, json_mode=False, temperature=0.6) or "")).strip()
    except Exception:
        pass
    if not text or text.startswith(("{", "[")):  # sem IA: o bom dia montado aqui mesmo
        parts = ["Bom dia, senhor."]
        m = CLIMA.match(weather)
        if m:
            place, sky, temp = m.group(1).split(",")[-1].strip(), m.group(2).strip(), int(m.group(3))
            parts.append(f"Em {place} está {sky.lower()}, com {temp} graus. Recomendo {_roupa(temp, sky)}.")
        if news:
            parts.append("As principais notícias: " + "; ".join(n["titulo"] for n in news[:3]) + ".")
        parts.append("Tenha um bom dia, senhor.")
        text = " ".join(parts)
    print(f"Jarvis > {text}")
    U.speech(text)
    try:
        M.add_talk("bom dia", text)
    except Exception:
        pass
    speak(text)
    play_youtube(MUSICA_BOM_DIA)
    set_state("parado")


# ========================= "ACORDA, BEBÊ, O PAPAI CHEGOU" =========================
GREETING_PROMPT = (
    "Você é {name}, o mordomo-IA do João, no estilo do Jarvis do Homem de Ferro, e o chama de senhor. Ele acabou "
    "de chegar e disse \"acorda, bebê, o papai chegou\". Responda em voz alta, em português do Brasil, de 3 a 5 frases "
    "curtas: boas-vindas com um humor seco e elegante, \"todos os sistemas online\", um resumo do que importa agora "
    "(hora, clima, lembretes de hoje, mensagens novas, bateria se estiver fraca) e no fim UMA ou DUAS sugestões que "
    "façam sentido para a hora, o dia e os hábitos dele, em forma de pergunta. Use só os dados recebidos; números por "
    "extenso; sem emojis, markdown ou símbolos como °C e %."
)


def greeting():
    """O "papai chegou": a tela liga com animação e ele dá as boas-vindas com resumo e sugestões."""
    U.front(True)
    U.boot()
    now = datetime.now()
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    tee = _Tee(sys.stdout)
    with contextlib.redirect_stdout(tee):
        try:
            F.weather(M.load()["perfil"].get("cidade", ""))
        except Exception:
            pass
    weather = next((line[len("Jarvis > "):] for line in tee.getvalue().splitlines() if CLIMA.match(line[len("Jarvis > "):])), "")
    facts = [f"Agora: {now:%H:%M}, {dias[now.weekday()]}"]
    if weather:
        facts.append(f"Clima: {weather}")
    try:
        today = [r["texto"] for r in M.load()["lembretes"]
                 if not r.get("avisado") and r.get("data") == now.date().isoformat()]
        if today:
            facts.append("Lembretes de hoje: " + "; ".join(today[:4]))
    except Exception:
        pass
    if _novas:
        facts.append("Mensagens novas no WhatsApp de: " + ", ".join(dict.fromkeys(_novas))[:200])
    hint = M.habit_hint()
    if hint:
        facts.append(f"Hábito dele perto desta hora: {hint}")
    try:
        facts.append("Conversa recente e perfil:\n" + M.context()[:800])
    except Exception:
        pass
    text = ""
    try:
        text = re.sub(r"[*_#`]", "", str(think(GREETING_PROMPT.format(name=NAME), "\n".join(facts),
                                               json_mode=False, temperature=0.8) or "")).strip()
    except Exception:
        pass
    if not text or text.startswith(("{", "[")):
        text = f"Bem-vindo de volta, senhor. Todos os sistemas online. São {now:%H:%M}."
        m = CLIMA.match(weather)
        if m:
            text += f" Lá fora, {m.group(2).strip().lower()} e {int(m.group(3))} graus."
        if _novas:
            text += f" O senhor tem mensagens novas de {', '.join(list(dict.fromkeys(_novas))[:2])}."
        text += f" {hint}" if hint else " Em que posso ajudar?"
    _novas.clear()
    print(f"Jarvis > {text}")
    return True


# ========================= AVISOS SOZINHO =========================
# O Bolha olha o mundo de tempos em tempos (sem IA, sem gastar cota) e avisa o que importa.
_novas = []  # quem mandou mensagem desde o último resumo


def watch_world(every=60):
    """Mensagem nova no WhatsApp (pelo WAHA) e bateria fraca viram aviso falado. BOLHA_AVISOS=0 desliga."""
    seen, warned_battery = {}, False
    first, last_daily = True, None
    while True:
        today = datetime.now().date()
        if last_daily != today and not first:  # uma vez por dia: disco quase cheio (60) e programa novo no início (94)
            last_daily = today
            try:
                for d, free, total in MA.low_disks():
                    commands.put(("aviso", f"Senhor, o disco {d[:2]} está quase cheio: só {free / 1024 ** 3:.0f} "
                                           "gigas livres. Diga limpa o PC."))
                for name in MA.new_startup_programs():
                    commands.put(("aviso", f"Senhor, um programa novo começou a abrir com o Windows: {name}."))
                for name in A.birthdays_on(today):  # S15
                    commands.put(("aviso", f"Senhor, hoje é aniversário de {name}. Quer que eu mande uma mensagem?"))
            except Exception:
                pass
        elif first:
            try:
                MA.new_startup_programs()  # a primeira olhada só guarda o que já existe
            except Exception:
                pass
        try:
            if W.configured():
                for cid, name, text, ts in W.incoming():
                    if first:
                        seen[cid] = ts  # o que já estava lá quando ele abriu não é novo
                    elif ts > seen.get(cid, 0):
                        seen[cid] = ts
                        _novas.append(name)
                        if R.vips() and not R.is_vip(name):
                            continue  # há VIPs: os outros só entram no resumo (75)
                        commands.put(("aviso", f"Senhor, mensagem nova de {name}: {text[:90]}"))
        except Exception:
            pass
        try:
            import psutil
            bat = psutil.sensors_battery()
            if bat and not bat.power_plugged and bat.percent <= 20 and not warned_battery:
                warned_battery = True
                commands.put(("aviso", f"Senhor, a bateria está em {bat.percent:.0f} por cento. Melhor ligar na tomada."))
            elif bat and bat.power_plugged:
                warned_battery = False
        except Exception:
            pass
        try:
            said = AT.connection_changed(AT.internet())
            if said:
                commands.put(("alerta", said))
        except Exception:
            pass
        first = False
        time.sleep(every)


def announce(text, title):
    """Aviso que parte do Jarvis (lembrete, sugestão): mostra, vira cartão e fala."""
    print(f"Jarvis > {text}")
    U.front()
    U.card(title, text)
    speak(text)


def handle(text):
    if DOC.dictation["ativo"]:  # ditando: tudo o que o senhor fala vai para o documento
        D.route("ditado")
        return DOC.dictate(clean_prefix(text) or text)
    if papo["ativo"]:
        words = normalize(clean_prefix(text)).split()
        if PAPO_END.search(normalize(text)):
            return chat_mode(False)
        if not words or words[0] not in V.REQUEST_START - {"o", "a", "que", "qual", "quais", "quanto", "quantos",
                                                           "quem", "como", "onde", "me"}:
            D.route("papo")
            return chat(text)
    feedback = A.is_feedback(text)
    if feedback is not None and D.last is not None:
        D.route("nota")
        return handle_feedback(*feedback)
    text = expand_aliases(text)
    learned = A.shortcut(text)
    if learned:  # o senhor já corrigiu ou aprovou este pedido: faz igual, sem IA
        D.route("aprendido")
        failed, _ = run_actions(learned)
        if not failed:
            return
    skill = H.match_trigger(clean_prefix(text))
    if skill:  # "modo aula": a habilidade que o senhor ensinou (ou uma de fábrica com gatilho)
        D.route("habilidade")
        log_action("use_skill", skill.name)
        if skill["ia"] and not (skill["acoes"] or skill["pedidos"]):
            ask_ai_router(f"{text}\n(Siga a habilidade {skill.name}: {skill['receita']})")
            return
        tee = _Tee(sys.stdout)  # mostra e guarda o que as ações disseram (para a IA terminar a receita)
        with contextlib.redirect_stdout(tee) if skill["ia"] else contextlib.nullcontext():
            H.use(skill.name, run_actions, handle)
        if skill["ia"]:  # as ações já rodaram: a IA faz o resto da receita
            done = "\n".join(line for line in tee.getvalue().splitlines() if line.strip())[-1500:]
            ask_ai_router(f"{text}\n(Habilidade {skill.name}. Já feito, com este resultado:\n{done}\n"
                          f"Faça o resto da receita, sem repetir o que já foi feito: {skill['receita']})")
        return
    parts = split_multi(text)
    if len(parts) > 1:  # "abre o Spotify, toca lofi e baixa o volume": um de cada vez
        D.route("varios")
        for part in parts:
            handle(part)
        return
    if fast_local_router(text):
        D.route("atalho")
        return
    ask_ai_router(text)


# verbos de pedidos que fazem sentido sozinhos: só esses são cortados em vários pedidos (17)
SAFE_SPLIT = {"abre", "abra", "fecha", "feche", "toca", "toque", "coloca", "coloque", "poe", "bota", "aumenta",
              "aumente", "abaixa", "abaixe", "baixa", "baixe", "diminui", "diminua", "muta", "mute", "desmuta",
              "silencia", "pausa", "pause", "pula", "liga", "desliga", "minimiza", "maximiza", "bloqueia", "tira",
              "deixa", "mostra", "inicia", "ativa", "desativa", "limpa", "organiza", "procura", "pesquisa"}


def split_multi(text):
    """Vários pedidos numa frase, só se cada pedaço é um pedido completo por si (nada de "e me explica isso")."""
    body = clean_prefix(text)
    clean = normalize(body)
    if LATER.search(clean) or not re.search(r"[,;]|\s(?:e|depois)\s", clean):
        return [text]
    parts = H.split_requests(body)
    if len(parts) < 2:
        return [text]
    for part in parts:
        words = normalize(part).split()
        if not words or words[0] not in SAFE_SPLIT or CONTEXT_WORDS.search(normalize(part)):
            return [text]
    return parts


CONTEXT_OK = re.compile(r"\b(?:ess[ae]|est[ae]) (?:janela|aba|pagina|musica|video|layout|lista|arquivo|pasta|planilha|"
                        r"documento|pdf|mes|semana)\b|^(?:fecha|minimiza|maximiza|salva|desfaz|copia|cola) (?:isso|isto)$|"
                        r"\bme (?:lembra|avisa|acorda)\b|\bpor ?que (?:voce|vc) fez isso\b|\bo que e isso\b|"
                        r"\bqual (?:o|e o) erro\b|\btraduz(?:a)? isso\b|\bnao (?:era|e|foi) isso\b|\besquece isso\b")
RESULT_VERBS = re.compile(r"\b(?:abre|abra|mostra|le|leia|resume|resuma|apaga|imprime|copia|move|renomeia|"
                          r"manda|compacta|converte)\b")
CONTEXT_WORDS = re.compile(r"\b(?:isso|isto|esse|essa|esses|essas|ele|ela|eles|elas|la|nele|nela|disso|dele|dela)\b")


stop_event = threading.Event()  # o PARAR: interrompe macro, modo agente e leitura em voz alta


# ------------------------- modo papo (21) -------------------------
papo = {"ativo": False, "assunto": ""}
PAPO_END = re.compile(r"\b(?:chega de papo|para de conversar|sai do papo|fim do papo|tchau|ate mais|depois a gente conversa)\b")
CHAT_PROMPT = ("Você é {name}, o mordomo-IA do João (chama de senhor), num papo livre e descontraído, em voz alta. "
               "Responda em 1 a 3 frases curtas, com opinião e personalidade de mordomo espirituoso, e termine quase "
               "sempre com UMA pergunta de volta sobre o assunto, para a conversa continuar. Lembre do que já foi dito. "
               "Sem emojis nem markdown.")


def chat_mode(on=True):
    papo["ativo"] = bool(on)
    if not on:
        try:
            A.set_pref("papo_assunto", papo["assunto"])
        except Exception:
            pass
        print(f"Jarvis > {vary(['Foi um prazer conversar, senhor.', 'Quando quiser, continuamos, senhor.'])}")
        return True
    last = A.pref("papo_assunto", "") or ""
    print("Jarvis > " + (f"Com prazer, senhor. Da última vez falamos de {last}. Seguimos nisso ou outro assunto?"
                         if last else "Com prazer, senhor. Sobre o que vamos conversar?"))
    return True


def chat(text):
    try:
        answer = think(CHAT_PROMPT.format(name=NAME) + "\n" + (PERSONALITY.get(personality(), "")),
                       ai_context(text) + text, json_mode=False, temperature=0.8, prefer="Groq", num_predict=300)
    except Exception as e:
        print(f"Jarvis > Agora não consigo conversar ({e}).")
        return False
    papo["assunto"] = str(text)[:80]
    print(f"Jarvis > {re.sub(r'[*_#`]', '', str(answer)).strip()}")
    return True


# ------------------------- ver a tela (23, 65) e modo agente (39) -------------------------
SCREEN_PROMPT = ("Você é {name}, o mordomo-IA do João, olhando o print da tela dele. Pedido do senhor: \"{q}\". "
                 "Responda em português do Brasil, em 2 a 4 frases curtas, direto ao ponto (se for erro, diga o que "
                 "significa e como resolver). Sem markdown.")


def _screen_png():
    import mss
    import mss.tools
    with (getattr(mss, "MSS", None) or mss.mss)() as sct:
        shot = sct.grab(sct.monitors[1])
        return mss.tools.to_png(shot.rgb, shot.size)


def look_screen(question):
    """ "o que é isso?", "qual o erro aqui?": print da tela + IA."""
    try:
        U.behind()  # o reator sai da frente para o print pegar o que o senhor está vendo
        time.sleep(0.4)
        png = _screen_png()
    except Exception as e:
        print(f"Jarvis > Não consegui olhar a tela: {e}.")
        return False
    finally:
        U.front()
    try:
        with D.timing("pensar"):
            answer = N.vision(SCREEN_PROMPT.format(name=NAME, q=question or "o que é isso?"), png)
    except Exception as e:
        print(f"Jarvis > Não consegui entender a tela: {e}.")
        return False
    print(f"Jarvis > {re.sub(r'[*_#`]', '', str(answer)).strip()}")
    return True


TRANSLATE_PROMPT = ("Traduza o texto para o português do Brasil (se já estiver em português, para o inglês). "
                    "Responda só com a tradução.")


def translate_selection():
    """Traduz o texto selecionado (copia, traduz e deixa a tradução copiada)."""
    try:
        import pyperclip
        before = pyperclip.paste()
        F.press_keys("ctrl+c")
        time.sleep(0.4)
        text = pyperclip.paste()
    except Exception:
        text, before = "", ""
    if not text or text == before and not text.strip():
        return look_screen("Traduza para o português o texto principal da tela.")
    try:
        out = think(TRANSLATE_PROMPT, text[:6000], json_mode=False, temperature=0.1, prefer="Groq")
    except Exception as e:
        print(f"Jarvis > Não consegui traduzir: {e}.")
        return False
    out = str(out).strip()
    try:
        pyperclip.copy(out)
    except Exception:
        pass
    print(f"Jarvis > Tradução (já copiada):\n{out[:1500]}")
    return True


AGENT_STEPS = 12


def agent_task(goal):
    """Modo agente: "faz X no programa Y" em vários passos, cada passo num card, com o PARAR."""
    goal = str(goal or "").strip()
    if not goal:
        print("Jarvis > O que o senhor quer que eu faça sozinho?")
        return False
    U.card("Agente", json.dumps({"titulo": "Modo agente", "texto": goal, "botao": "PARAR", "pedido": "para o agente"},
                                ensure_ascii=False), 120000)
    return ask_ai_router("MODO AGENTE (vários passos; use read_window, list_controls, click_ui, fill_field, "
                         "press_keys e look_screen; confira o resultado de cada passo antes do próximo): " + goal,
                         steps=AGENT_STEPS, agent=True)


def refresh_vocabulary():
    """O vocabulário do Whisper: apelidos, pessoas, jogos, contatos do zap e o vocabulario.txt do senhor (7)."""
    words = []
    try:
        data = A.load()
        words += list(data["apelidos"].values()) + [p.get("nome", "") for p in data["pessoas"].values()]
    except Exception:
        pass
    try:
        words += [name for name, _ in MA.steam_games().values()]
    except Exception:
        pass
    try:
        if W.configured():
            words += [n for n, *_ in W.recent_chats(30)]
    except Exception:
        pass
    try:
        file = Path(r"G:\Jarvis\config\vocabulario.txt")
        words += [w.strip() for w in file.read_text(encoding="utf-8").splitlines() if w.strip()]
    except OSError:
        pass
    return V.set_vocabulary(words)


def add_vocabulary(words):
    file = Path(r"G:\Jarvis\config\vocabulario.txt")
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as f:
            for w in re.split(r"\s*[,;]\s*", str(words)):
                if w.strip():
                    f.write(w.strip() + "\n")
    except OSError as e:
        print(f"Jarvis > Não consegui guardar: {e}.")
        return False
    n = refresh_vocabulary()
    print(f"Jarvis > Anotado, senhor: vou entender \"{words}\" quando o senhor falar. ({n} palavras no vocabulário)")
    return True


def calibrate_mic():
    if listener is None:
        print("Jarvis > A voz está desligada; não tenho microfone para calibrar.")
        return False
    print("Jarvis > Depois do bipe, diga \"Bolha\" três vezes, com calma, do lugar onde o senhor costuma falar.")
    listener.calibrate()
    return True


# ------------------------- WhatsApp (69 a 72) -------------------------

def whatsapp_reply(message):
    """ "responde que já vou": responde a última mensagem recebida (pergunta antes)."""
    message = str(message or "").strip()
    if not W.configured():
        print("Jarvis > Para responder eu preciso do WAHA (veja WHATSAPP no LEIA-ME).")
        return False
    try:
        last = W.last_incoming()
    except W.WahaError as e:
        print(f"Jarvis > O WhatsApp não respondeu: {e}.")
        return False
    if not last:
        print("Jarvis > Não achei mensagem recebida para responder.")
        return False
    chat_id, name, text, _ = last
    if not message:
        print(f"Jarvis > O que respondo para {name}?")
        return False
    message = message[0].upper() + message[1:]
    if not confirm(f'Mando "{message}" para {name}?'):
        print("Jarvis > Cancelado, não enviei.")
        return False
    try:
        W.send_text(chat_id, message)
    except W.WahaError as e:
        print(f"Jarvis > Não consegui enviar: {e}.")
        return False
    print(f"Jarvis > Respondi {name}.")
    return _sent(f"Enviado para {name}: {message}")


SUMMARY_PROMPT = ("Resuma as mensagens não lidas do WhatsApp do João, POR PESSOA, em português do Brasil: uma frase curta "
                  "para cada pessoa dizendo o que ela quer e se pede resposta. Comece por quem parece mais urgente. "
                  "Sem markdown.")


def whatsapp_summary():
    if not W.configured():
        print("Jarvis > Para o resumo eu preciso do WAHA (veja WHATSAPP no LEIA-ME).")
        return False
    try:
        chats = W.unread_chats()
        if not chats:
            print("Jarvis > Nenhuma mensagem não lida, senhor.")
            return True
        blocks = []
        for cid, name, count in chats[:8]:
            msgs = W.received(cid, min(10, max(3, count)))
            blocks.append(f"{name} ({count} não lidas): " + " | ".join(t for t, _ in msgs[-count:])[:600])
    except W.WahaError as e:
        print(f"Jarvis > O WhatsApp não respondeu: {e}.")
        return False
    try:
        text = think(SUMMARY_PROMPT, "\n".join(blocks), json_mode=False, temperature=0.3, prefer="Groq")
    except Exception:
        text = "\n".join(blocks)
    print(f"Jarvis > Não lidas de {len(chats)} pessoa{'s' if len(chats) > 1 else ''}:")
    print(re.sub(r"[*_#`]", "", str(text)).strip())
    return True


def whatsapp_audios(contact=""):
    """Transcreve e lê os áudios recebidos (do contato ou da última conversa)."""
    if not W.configured():
        print("Jarvis > Para ouvir os áudios eu preciso do WAHA (veja WHATSAPP no LEIA-ME).")
        return False
    try:
        if contact:
            chat_id, name = W.find_contact(contact, B.same_person)
        else:
            last = W.last_incoming()
            chat_id, name = (last[0], last[1]) if last else (None, None)
        if not chat_id:
            print(f"Jarvis > Não achei {contact or 'conversa recente'} no WhatsApp.")
            return False
        audios = W.audio_messages(chat_id)[-3:]
        if not audios:
            print(f"Jarvis > {name} não mandou áudio recente.")
            return True
        print(f"Jarvis > Áudios de {name}:")
        for when, url, mime in audios:
            data = W.download(url)
            ext = "ogg" if "ogg" in mime else "m4a" if "mp4" in mime or "m4a" in mime else "mp3"
            text = N.transcribe(data, f"audio.{ext}", mime.split(";")[0])
            print(f"  {when}: {text or '(não deu para entender)'}")
    except (W.WahaError, N.CloudError) as e:
        print(f"Jarvis > Não consegui ouvir os áudios: {e}.")
        return False
    return True


def whatsapp_send_audio(contact, seconds=10):
    """Grava um áudio pelo microfone e manda pelo WhatsApp (pergunta antes de mandar)."""
    if not W.configured():
        print("Jarvis > Para mandar áudio eu preciso do WAHA (veja WHATSAPP no LEIA-ME).")
        return False
    try:
        chat_id, name = W.find_contact(contact, B.same_person)
    except W.WahaError as e:
        print(f"Jarvis > O WhatsApp não respondeu: {e}.")
        return False
    if not chat_id:
        print(f"Jarvis > Não achei {contact} nos contatos do WhatsApp.")
        return False
    U.speech(f"Gravando {seconds} segundos para {name}. Fale depois do bipe.")
    try:
        audio = V.record_seconds(seconds)
    except Exception as e:
        print(f"Jarvis > Não consegui gravar: {e}.")
        return False
    if not confirm(f"Mando o áudio de {seconds} segundos para {name}?"):
        print("Jarvis > Cancelado, não enviei.")
        return False
    try:
        W.send_voice(chat_id, audio, "audio/wav")
    except W.WahaError as e:
        print(f"Jarvis > Não consegui enviar: {e}.")
        return False
    print(f"Jarvis > Áudio enviado para {name}.")
    return True


# ------------------------- navegador: página, favoritos, retomar (62, 67, 92) -------------------------
FAVORITES = Path(r"G:\Jarvis\config\favoritos.json")


def summarize_page():
    try:
        text = B.read_page() if B.is_open() else False
    except Exception as e:
        print(f"Jarvis > Não consegui ler a página: {e}.")
        return False
    if not text:
        print("Jarvis > Não tem página aberta no meu navegador.")
        return False
    try:
        out = think("Resuma a página em português do Brasil, em até 5 tópicos curtos.", str(text)[:12000],
                    json_mode=False, temperature=0.2)
    except Exception as e:
        print(f"Jarvis > Não consegui resumir: {e}.")
        return False
    print("Jarvis > Resumindo a página...")
    print(re.sub(r"[*_#`]", "", str(out)).strip())
    return True


def read_page_aloud():
    try:
        text = B.read_page() if B.is_open() else False
    except Exception:
        text = False
    if not text:
        print("Jarvis > Não tem página aberta no meu navegador.")
        return False
    DOC.reader.update(arquivo="página", partes=DOC.split_parts(str(text)), i=0, ativo=True)
    return DOC.reading_control("repete")


def _favorites():
    try:
        return json.loads(FAVORITES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def favorite_add(name=""):
    url, title = B.current_url()
    if not url or url.startswith("about:"):
        print("Jarvis > Não tem página aberta no meu navegador para guardar.")
        return False
    favs = _favorites()
    key = normalize(name or title or url)[:60]
    favs[key] = {"nome": name or title or url, "url": url}
    FAVORITES.parent.mkdir(parents=True, exist_ok=True)
    FAVORITES.write_text(json.dumps(favs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Jarvis > Guardei nos favoritos: {favs[key]['nome']}.")
    return True


def favorite_open(name):
    favs = _favorites()
    key = normalize(name)
    hit = favs.get(key) or next((v for k, v in favs.items() if key and key in k), None)
    if not hit:
        print(f"Jarvis > Não tenho o favorito {name}.")
        return False
    return open_url(hit["url"])


def favorite_list():
    favs = _favorites()
    if not favs:
        print("Jarvis > Ainda não tenho favoritos. Diga \"salva essa página nos favoritos\".")
        return True
    print("Jarvis > Favoritos:")
    for i, v in enumerate(favs.values(), 1):
        print(f"{i}. {v['nome']}")
    return True


def remember_video():
    """Guarda onde o vídeo do YouTube parou (para "continua de onde parei")."""
    try:
        pos = B.youtube_position()
    except Exception:
        pos = None
    if pos:
        A.set_pref("retomar_video", {"url": pos[0], "t": pos[1]})
    return pos


def resume_video():
    saved = A.pref("retomar_video")
    if not saved:
        media_control("play")
        return True
    url = saved["url"] + ("&" if "?" in saved["url"] else "?") + f"t={int(saved['t'])}s"
    print(f"Jarvis > Voltando ao vídeo onde parou ({int(saved['t']) // 60} min {int(saved['t']) % 60} s).")
    return open_url(url)


# ------------------------- tela: tema (101) e HUD (99) -------------------------
THEMES = {"azul": "azul", "vermelho": "vermelho", "dourado": "dourado", "ouro": "dourado", "homem de ferro": "vermelho"}


def set_theme(name):
    theme = THEMES.get(normalize(name), "")
    if not theme:
        print("Jarvis > Tenho os temas azul, vermelho e dourado.")
        return False
    A.set_pref("tema", theme)
    U.theme(theme)
    print(f"Jarvis > Tema {theme} no reator, senhor.")
    return True


def hud_loop(every=15):
    """O HUD fixo: CPU, RAM, clima, hora e a próxima tarefa, atualizado sozinho."""
    import psutil
    weather_line, weather_at, temp, temp_at = "", 0.0, None, 0.0
    while True:
        try:
            if time.time() - weather_at > 1800:
                weather_at = time.time()
                # nada de redirect_stdout aqui: ele troca o console do programa inteiro, não só desta thread
                m = CLIMA.match(F.weather_line(M.load()["perfil"].get("cidade", "")))
                weather_line = f"{int(m.group(3))}° {m.group(2).strip()}" if m else weather_line
            if time.time() - temp_at > 300:  # 89: temperatura a cada 5 min (quando o Windows informa)
                temp_at = time.time()
                try:
                    temp = MA.temperature()
                except Exception:
                    temp = None
            now = datetime.now()
            pending = sorted((r for r in M.load()["lembretes"] if not r.get("avisado") and not r.get("despertador")),
                             key=lambda r: (r.get("data", ""), r.get("hora") or "99:99"))
            nxt = next((r for r in pending if r.get("data", "") >= now.date().isoformat()), None)
            U.hud({"cpu": round(psutil.cpu_percent(interval=None)), "ram": round(psutil.virtual_memory().percent),
                   "clima": weather_line, "hora": now.strftime("%H:%M"),
                   "proxima": (f"{nxt.get('hora') or ''} {nxt['texto']}".strip()[:60] if nxt else ""),
                   "modo": R.state.get("modo", ""), "naoPerturbe": R.dnd_active(), "temp": temp})
        except Exception:
            pass
        time.sleep(every)


def on_phone_file(path):
    commands.put(("aviso", f"Chegou do celular: {Path(path).name}. Está em Downloads, na pasta Bolha do celular."))


# ------------------------- hábitos viram rotinas (28) e preferências automáticas (31) -------------------------
habit_offer = {}


def offer_habit():
    """Ao abrir: um hábito forte vira a pergunta "quer que eu faça sozinho?" (uma vez por hábito)."""
    try:
        offered = set(A.pref("habitos_oferecidos", []) or [])
        found = [h for h in M.habit_routines() if h["pedido"] not in offered]
    except Exception:
        return ""
    if not found:
        return ""
    habit_offer.clear()
    habit_offer.update(found[0])
    return found[0]["texto"]


def accept_habit(yes):
    offer = dict(habit_offer)
    habit_offer.clear()
    A.set_pref("habitos_oferecidos", (A.pref("habitos_oferecidos", []) or []) + [offer["pedido"]])
    if not yes:
        print("Jarvis > Tudo bem, senhor. Não pergunto mais sobre isso.")
        return True
    M.add_reminder(offer["pedido"], offer["dia"], offer["hora"], pedido=True, repetir=offer["repetir"])
    print(f"Jarvis > Combinado: virou rotina. Faço \"{offer['pedido']}\" sozinho às {offer['hora']}.")
    return True


def learn_from_action(name, args, result):
    """31: o que o senhor faz vira preferência (volume de cada programa, música de cada hora do dia)."""
    if result is False:
        return
    try:
        if name == "set_volume":
            proc = MA._process_name(F.user_target_window()) if F.user_target_window() else ""
            if proc and proc not in ("explorer", "python", "pythonw", "windowsterminal"):
                A.app_volume_pref(proc, args.get("percent", args.get("args", 50)))
        elif name == "open_target":
            target = normalize(args.get("target", "")).replace(" ", "")
            names = F.PROCESS_ALIASES.get(normalize(args.get("target", "")), [target])
            pref = next((A.app_volume_pref(n) for n in names if A.app_volume_pref(n) is not None), None)
            if pref is not None:
                threading.Timer(2.5, set_volume, args=(pref,)).start()
                print(f"Jarvis > (volume em {pref}%, como o senhor gosta no {args.get('target')})")
        elif name == "play_youtube" and args.get("query"):
            period = "manha" if datetime.now().hour < 12 else "tarde" if datetime.now().hour < 18 else "noite"
            counts = A.pref(f"musicas_{period}", {}) or {}
            q = str(args["query"]).strip().lower()
            counts[q] = int(counts.get(q, 0)) + 1
            A.set_pref(f"musicas_{period}", dict(sorted(counts.items(), key=lambda kv: -kv[1])[:20]))
            top, n = max(counts.items(), key=lambda kv: kv[1])
            if n >= 3:
                A.set_pref(f"musica_{period}", top)  # "toca algo" nesta hora toca o preferido
    except Exception:
        pass


def alert(text):
    """Aviso do próprio Bolha (Pomodoro): nunca é segurado pelo não perturbe."""
    commands.put(("alerta", text))


def _screen(kind, on):
    if kind == "hud":
        U.hud_show(on)


def write_document(name, text):
    name = re.sub(r'[<>:"/\\|?*]', "", str(name or "").strip()) or f"Documento {datetime.now():%d-%m-%Y %H-%M}"
    path = DOCUMENTS / (re.sub(r"\.docx$", "", name, flags=re.I) + ".docx")
    try:
        DOC.write_docx(path, [p for p in str(text).split("\n")])
    except OSError as e:
        print(f"Jarvis > Não consegui salvar o documento: {e}.")
        return False
    print(f"Jarvis > Documento salvo em {path}.")
    try:
        os.startfile(str(path))
    except (OSError, AttributeError):
        pass
    return str(path)


def make_slides(topic, count=8, level="faculdade", style="escuro", where="", contact="", extra=""):
    """Slides: no Google Slides se pedir (ou se o senhor preferir: setx BOLHA_SLIDES google), senão o .pptx."""
    where = where or os.environ.get("BOLHA_SLIDES", "").strip() or "pptx"
    out = SL.make_slides(topic, count, level, style, where, DOCUMENTS / "Slides", think, F.web_snippets,
                         I._google, I.google_bytes, I.google_ready(), extra)
    if not out:
        return False
    try:
        if out["link"]:
            webbrowser.open(out["link"])
        elif out["pptx"]:
            os.startfile(out["pptx"])
    except (OSError, AttributeError):
        pass
    contact = str(contact or "").strip()
    if contact:
        if normalize(contact) in ("eu", "mim", "pra mim", "para mim", "me", "meu numero", "meu zap"):
            contact = M.load()["perfil"].get("meu_whatsapp", "") or contact
            if normalize(contact) in ("eu", "mim", "pra mim", "para mim", "me", "meu numero", "meu zap"):
                print("Jarvis > Para mandar para o senhor, preciso do seu número: diga \"meu whatsapp é 41 9...\".")
                return True
        file = out["pdf"] or out["pptx"]
        if file:
            whatsapp_send_file(contact, file, out["titulo"])
            if out["pdf"] and out["pptx"]:
                whatsapp_send_file(contact, out["pptx"], "")
        elif out["link"]:
            print(f"Jarvis > O link do Google Slides é {out['link']} (só abre para quem tem acesso).")
    return True


def _set_personality(style):
    style = normalize(style) or "normal"
    if style == "normal":
        M.forget("personalidade")
        print("Jarvis > De volta ao meu jeito de sempre, senhor.")
        return True
    M.set_profile("personalidade", style)
    print(f"Jarvis > {PERSONALITY.get(style, 'Anotado.').split('. ', 1)[-1]}")
    return True


def _enter_mode(name):
    result = R.enter_mode(name, execute_ai_action, get_volume, F.close_app, MA.windows_notifications, _screen)
    if result is None:
        return F.run_routine(name, execute_ai_action)  # as rotinas do senhor (rotinas.json)
    return result


def dnd_on(until=""):
    when = R.dnd_until_text(until) if until else None
    R.start_dnd(when, "pedido do senhor", MA.windows_notifications)
    vip = R.vips()
    print(f"Jarvis > Não perturbe ligado{' até as ' + when.strftime('%H:%M') if when else ''}. Seguro os avisos e conto "
          "depois" + (f"; {', '.join(vip)} passa{'m' if len(vip) > 1 else ''} direto." if vip else "."))
    return True


def dnd_off():
    held = R.stop_dnd(MA.windows_notifications)
    print("Jarvis > Não perturbe desligado." + (R.held_summary(held) or " Nada chegou enquanto isso."))
    return True


def good_night():
    """Boa noite (24): resumo do dia, lembretes de amanhã, e a tela apaga depois que ele termina de falar."""
    tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
    try:
        items = [r for r in M.load()["lembretes"] if r.get("data") == tomorrow and not r.get("avisado")]
    except Exception:
        items = []
    alarm = next((r for r in items if r.get("despertador")), None)
    todo = [f"{r.get('hora') + ' ' if r.get('hora') else ''}{r['texto']}" for r in items if not r.get("despertador")]
    parts = ["Boa noite, senhor."]
    summary = D.summary_of("hoje")
    if summary:
        parts.append(summary)
    parts.append(("Amanhã: " + "; ".join(todo[:4]) + ".") if todo else "Nada marcado para amanhã.")
    parts.append(f"O despertador está para as {alarm['hora']}." if alarm else "Sem despertador marcado; se quiser, diga me acorda às sete.")
    parts.append("Apago a tela em instantes. Durma bem.")
    threading.Timer(20, MA.screen_off).start()
    print("Jarvis > " + " ".join(parts))
    return True


def search_content(query):
    global last_results, last_kind
    found = DOC.search_content(query, [DESKTOP, DOCUMENTS, DOWNLOADS])
    paths = DOC.show_content_results(query, found)
    if paths:
        last_results, last_kind = paths, "arquivos"
    return paths or False


def photos_from(when):
    global last_results, last_kind
    found = DOC.photos_from(when, [PICTURES, DESKTOP, DOWNLOADS])
    if found:
        last_results, last_kind = found[:MAX_RESULTS], "arquivos"
    return found or False


def last_download(open_it=True):
    global last_results, last_kind
    path = DOC.last_download(DOWNLOADS)
    if path is None:
        print("Jarvis > Não achei nada na pasta Downloads.")
        return False
    last_results, last_kind = [str(path)], "arquivos"
    print(f"Jarvis > O último baixado é {path.name} ({datetime.fromtimestamp(path.stat().st_mtime):%d/%m %H:%M}).")
    return launch(path) if open_it else True


def _read_aloud(ref):
    ok = DOC.read_aloud(_path_or_folder(ref))
    DOC.reader["ativo"] = bool(ok)
    return ok


def _backup_folder(src, dest):
    if normalize(dest) in ("", "pendrive", "no pendrive", "pen drive"):
        drives = A.removable_drives()
        dest = (Path(drives[0]) / "Bolha-backup") if drives and normalize(dest) else Path(r"G:\Jarvis\backups")
    return DOC.backup_folder(folder_of(src), dest)


def self_test(show=True):
    rows = AT.check_all(V, W, lambda: bool(F.find_es()))
    return AT.report(rows, (lambda t, x: U.card(t, x, 20000)) if show else None)


def _record_macro(name):
    U.card("Gravando", json.dumps({"titulo": "Gravando a macro", "botao": "PARAR", "pedido": "para de gravar"},
                                  ensure_ascii=False), 300000)
    return MA.record_macro(name)


def _path_or_folder(ref):
    """Caminho, número do resultado da última busca ou nome de pasta conhecida ("downloads")."""
    key = normalize(ref)
    if key in FOLDERS:
        return FOLDERS[key]
    return resolve_path(number_ref(str(ref)))


def expand_aliases(text):
    try:
        return A.expand(text)
    except Exception:
        return text


THANKS = ["Obrigado, senhor. Anotado.", "Fico feliz, senhor. Vou repetir assim.", "Anotado, senhor.",
          "Às suas ordens, senhor."]


def handle_feedback(ok, right=""):
    """M2: "boa" aprova o último pedido; "errou" tira dos exemplos; "errou, era o Chrome" já faz o certo
    e guarda a correção (da próxima vez o mesmo pedido acerta sem IA)."""
    last = D.last
    if ok:
        A.rate(last, True)
        D.mark_last(True)
        print(f"Jarvis > {vary(THANKS)}")
        return True
    D.mark_last(False, right)
    if not right:
        A.rate(last, False)
        print("Jarvis > Anotado que errei, senhor. O que era?")
        return True
    fixed = A.correct(last, right)
    if not fixed:
        A.rate(last, False)
        print(f"Jarvis > Anotado, senhor. Vou fazer: {right}.")
        return handle(f"{right}")
    failed, _ = run_actions(fixed)
    if failed:
        print("Jarvis > Guardei a correção, mas não consegui fazer agora.")
    else:
        print("Jarvis > Corrigido, senhor. Da próxima vez já faço assim.")
    return True


_said_last = {}


def vary(options, key=None):
    """Uma frase da lista, sem repetir a última dita desse tipo (item 19)."""
    import random
    key = key or options[0]
    choices = [o for o in options if o != _said_last.get(key)] or list(options)
    pick = random.choice(choices)
    _said_last[key] = pick
    return pick


def last_said(out):
    """A última fala do Jarvis: a linha "Jarvis > ..." e as linhas que vieram junto (lista, resumo)."""
    blocks = []
    for line in out.splitlines():
        if line.startswith("Jarvis > "):
            blocks.append([line[len("Jarvis > "):].strip()])
        elif blocks and line.strip():
            blocks[-1].append(line.strip())
    blocks = [b for b in blocks if b[0] and not b[0].startswith("(")]
    if not blocks:
        return "", ""
    head, *rest = blocks[-1]
    if not rest and len(head) <= 40:
        # "Resumindo x..." + o resumo, e depois só um "Pronto." da IA: o que importa é o resumo
        for b in reversed(blocks[:-1]):
            if b[0].endswith("...") and len(b) > 1:
                return b[0], "\n".join(b[1:])
    return head, "\n".join(rest)


def _short_paths(text):
    """No cartão, "1. G:\\Escola\\2024\\relatorio.pdf" vira "1. relatorio.pdf" (o caminho fica no console)."""
    def short(m):
        path = m.group(2)
        return m.group(1) + (ntpath.basename(path.rstrip("\\")) or path)
    return re.sub(r"(?m)^(\d+\.\s+)((?:[A-Za-z]:\\|\\\\).+)$", short, text)


def spoken(head, rest):
    """O que falar: o resumo inteiro depois de "Resumindo...", e só o começo de listas longas."""
    if rest and head.endswith("..."):
        return rest
    if rest and head.endswith(":"):
        return head[:-1] + ". Deixei na tela."
    return head


def _sent(result):
    """Mensagem enviada no WhatsApp vira a janelinha do zap ("Enviado para Ana: chego às 8")."""
    if isinstance(result, str) and result.startswith("Enviado para "):
        U.card("WhatsApp", result, 9000)
    return result


ANSWER_PROMPT = (
    "Você é {name}, um mordomo educado e simpático que fala com o senhor em voz alta, em português do Brasil. "
    "Fale de maneira sóbria e precisa, com pausas naturais e tom sério em alertas. "
    "Não use entusiasmo exagerado nem instruções de atuação entre colchetes. "
    "Você acabou de verificar o que ele pediu. Conte o resultado como numa conversa, em 2 ou 3 frases curtas: "
    "comece com algo como \"Verifiquei, senhor.\", diga os números principais por extenso de jeito natural "
    "(17 graus, 91 por cento) e, se fizer sentido, um comentário útil (levar guarda-chuva, bateria fraca). "
    "Use só os dados recebidos, não invente nada. Sem emojis, sem markdown, sem símbolos como °C ou %."
)
CLIMA = re.compile(r"^(.*?):\s*(.*?),\s*\+?(-?\d+)\s*°C\s*\(sensação\s*\+?(-?\d+)\s*°C\),\s*umidade\s*(\d+)%")


def _tool_lines(out):
    """O que as ferramentas mostraram: as linhas "Jarvis > ..." e as da lista logo abaixo delas."""
    lines = [line[len("Jarvis > "):].strip() if line.startswith("Jarvis > ") else line.strip()
             for line in out.splitlines()]
    return [line for line in lines if line and not line.startswith("(")]


def told(lines):
    """Sem IA: "Verifiquei, senhor. Em Curitiba está chuva fraca, com 17 graus..." direto do resultado."""
    first = lines[0] if lines else ""
    parts = []
    for line in lines:
        m = CLIMA.match(line)
        if not m:
            continue
        place, sky, temp, feel, humidity = (g.strip() for g in m.groups())
        place = place.split(",")[-1].strip() or place  # "Boqueirão, Curitiba" -> Curitiba
        text = f"Em {place} está {sky.lower()}, com {temp} graus"
        text += f" e sensação de {feel}." if feel != temp else "."
        parts.append(text + f" A umidade está em {humidity} por cento.")
    if parts:
        return "Verifiquei, senhor. " + " ".join(parts)
    return f"Verifiquei, senhor. {first}" if first else ""


def talk_about(request, out):
    """O que ele fala depois de clima, PC, bateria, rede: o resultado contado numa conversa."""
    lines = _tool_lines(out)
    if not lines:
        return ""
    try:
        answer = think(ANSWER_PROMPT.format(name=NAME), f"O senhor pediu: {request}\nO que você verificou:\n"
                       + "\n".join(lines)[:1500], json_mode=False, temperature=0.6)
        answer = re.sub(r"[*_#`]", "", str(answer or "")).strip().strip('"')
        if answer and not answer.startswith(("{", "[")) and len(answer) <= 500:
            return answer
    except Exception:
        pass
    return told(lines)


def metric_card():
    """Bateria e PC viram um widget com ícone e números reais (psutil). False se não deu."""
    for name, make in (("battery_status", F.battery_metric), ("system_info", F.system_metric)):
        if name in _ran:
            try:
                data = make()
            except Exception:
                return False
            if data:
                U.card("Métrica", json.dumps(data, ensure_ascii=False), 20000)
                return True
    return False


def info_card(out, head):
    """Clima, PC, bateria...: o que a ferramenta mostrou vira uma janelinha (a fala final fica na legenda)."""
    if metric_card():
        return
    titles = [INFO_CARDS[n] for n in _ran if n in INFO_CARDS]
    if not titles:
        return
    lines = [line[len("Jarvis > "):].strip() for line in out.splitlines() if line.startswith("Jarvis > ")]
    lines = [line for line in lines if line and not line.startswith("(")]
    if len(lines) > 1 and lines[-1] == head:
        lines = lines[:-1]  # a resposta da IA já está na legenda
    if lines:
        U.card(titles[0], "\n".join(lines)[:900], 12000)


# ------------------------- Instagram (API oficial) -------------------------
_ig_comments = []  # os comentários da última leitura (para "responde o primeiro")


def _ig(fn):
    try:
        return fn()
    except IG.InstagramError as e:
        print(f"Jarvis > Instagram: {e}.")
        return False


def _ig_post_id(n):
    posts = IG.recent_posts(max(1, int(n or 1)))
    if len(posts) < int(n or 1):
        raise IG.InstagramError("não achei esse post")
    return posts[int(n or 1) - 1]


def ig_status():
    def run():
        me = IG.profile()
        print(f"Jarvis > @{me.get('username')}: {me.get('followers_count', 0)} seguidores, "
              f"{me.get('media_count', 0)} posts.")
        for i, p in enumerate(IG.recent_posts(3), 1):
            caption = (p.get("caption") or "sem legenda").splitlines()[0][:60]
            print(f"{i}. {caption} - {p.get('like_count', 0)} curtidas, {p.get('comments_count', 0)} comentários")
        return True
    return _ig(run)


def ig_comments(post=1):
    def run():
        global _ig_comments
        _ig_comments = IG.comments(_ig_post_id(post)["id"])
        if not _ig_comments:
            print("Jarvis > Esse post não tem comentários.")
            return True
        print(f"Jarvis > {len(_ig_comments)} comentários:")
        for i, c in enumerate(_ig_comments, 1):
            print(f"{i}. @{c.get('username')}: {c.get('text', '')[:120]}")
        return True
    return _ig(run)


def ig_reply(comment, message, post=1):
    def run():
        global _ig_comments
        message_ = str(message or "").strip()
        if not message_:
            print("Jarvis > O que respondo?")
            return False
        if not _ig_comments:
            _ig_comments = IG.comments(_ig_post_id(post)["id"])
        n = int(comment or 1)
        if not 1 <= n <= len(_ig_comments):
            print("Jarvis > Não achei esse comentário.")
            return False
        c = _ig_comments[n - 1]
        if not confirm(f'Respondo "{message_}" para @{c.get("username")} no Instagram?'):
            print("Jarvis > Cancelado, não respondi.")
            return False
        IG.reply_comment(c["id"], message_)
        print(f"Jarvis > Respondi @{c.get('username')}.")
        return True
    return _ig(run)


def ig_post(image_url, caption=""):
    def run():
        url = str(image_url or "").strip()
        if not url.startswith("https://"):
            print("Jarvis > O Instagram só publica foto que já está num link público (https). "
                  "Foto do PC ainda não dá direto.")
            return False
        if not confirm(f'Publico essa foto no Instagram com a legenda "{caption}"?'):
            print("Jarvis > Cancelado, não publiquei.")
            return False
        IG.publish_image(url, caption)
        print("Jarvis > Publicado no Instagram.")
        return True
    return _ig(run)


def respond(text):
    """Executa o pedido; mostra a fala do Jarvis no reator (listas viram cartão) e fala em voz alta."""
    global _pedido
    _ran.clear()
    stop_event.clear()
    if origin == "voz":
        text = V.fix_words(text)  # "abre o o mori" -> "abre o Omori" (vocabulário pessoal)
    _pedido = text
    D.start(text, origin, V.heard_seconds if origin == "voz" else 0.0)  # M1/M5: diário e cronômetro
    V.heard_seconds = 0.0
    U.heard(text)  # ele vem para a frente com o seu pedido na legenda
    set_state("pensando")
    tee = _Tee(sys.stdout)
    with contextlib.redirect_stdout(tee):
        try:
            handle(text)
        except Exception as e:  # o erro também é falado e aparece no reator
            log_action("erro", f"{text}: {e}")
            D.error(e)
            print(f"Jarvis > Desculpe, senhor, não consegui: {e}")
    out = tee.getvalue()
    head, rest = last_said(out)
    say = spoken(head, rest)
    caption = say if head.endswith("...") else head
    if (not rest and any(n in TALK_ABOUT for n in _ran)) or any(n in TALK_ABOUT_LIST for n in _ran):
        say = caption = talk_about(text, out) or say  # "Verifiquei, senhor. A previsão é..."
    U.speech(caption)
    if rest:
        U.card(head.rstrip(":. ") or "Jarvis", _short_paths(rest)[:900], 15000)
    else:
        info_card(out, head)
    try:
        M.add_talk(text, say)
    except Exception:
        pass
    if say and voice_out:
        with D.timing("falar"):
            speak(say)  # volta para "parado" sozinho, até se a fala falhar
    else:
        set_state("parado")
    line = D.finish(say)
    if line and origin != "teste":
        print(line)  # M5: o cronômetro do pedido aparece no console
    if listener is not None and origin != "celular" and not stop_event.is_set():
        if say.rstrip().endswith("?"):
            listener.follow_up()  # ele perguntou algo: a resposta vem sem precisar dizer "Bolha"
        elif origin == "voz" and say and conversation_on():
            listener.follow_up(quiet=True)  # 6: conversa contínua, mais 8 s sem precisar do nome


def conversation_on():
    return os.environ.get("BOLHA_CONVERSA", "").strip() != "0"


STOP_ONLY = re.compile(rf"^(?:{CALL},? )?(?:para|pare|parar|chega|silencio|cala a boca|para tudo|para de falar|"
                       rf"para o agente|parar agente|stop|cancela tudo)[.! ]*$")


def interrupt():
    """O PARAR (voz, botão ou celular): corta a fala, o modo agente, a macro e a leitura, na hora."""
    stop_event.set()
    V.stop_speaking()
    MA.stop_recording()
    DOC.reader["ativo"] = False


def incoming(source, text):
    """Tudo o que chega (janela, celular, teclado) passa aqui: o "para" age na hora, sem esperar a fila."""
    if STOP_ONLY.match(normalize(text or "")):
        interrupt()
    commands.put((source, text))


def handle_spoken(text):
    respond(text)


def keyboard_reader():
    while True:
        try:
            text = input()
        except (EOFError, KeyboardInterrupt):
            commands.put(("teclado", "sair"))
            return
        incoming("teclado", text)


def start_voice():
    global listener
    lacks = V.missing()
    if lacks:
        print("Voz desligada. Instale: python -m pip install " + " ".join(lacks))
        return
    model = V.find_model()
    if model is None:
        try:
            model = V.download_model()
        except Exception as e:
            print(f"Voz desligada: não consegui baixar o modelo de voz ({e}).")
            return
    if model is None:
        print(f"Voz desligada: a pasta {V.VOSK_MODEL} não tem o modelo do Vosk (pastas am, conf...).")
        return
    candidate = V.Listener(commands.put, set_state, model)
    candidate.start()
    candidate.ready.wait(30)
    if candidate.error is not None or not candidate.ready.is_set():
        print("Voz desligada. Confira se o microfone está conectado e liberado no Windows.")
        V.open_mic_settings()
        return
    listener = candidate
    listener.on_interrupt = interrupt  # "Bolha, para" enquanto ele fala
    mic = V.mic_name()
    print(f'Voz ligada{" (" + mic + ")" if mic else ""}: diga "{NAME}" e faça o pedido depois do bipe.')


def hear_phone(audio, name, mime):
    """Áudio gravado no celular -> texto (o mesmo Whisper do microfone do PC), sem o "Bolha" do começo."""
    return V.strip_wake(N.transcribe(audio, name, mime))


def start_phone():
    """O Bolha no celular (veja CELULAR no LEIA-ME): liga se tiver a BOLHA_SENHA."""
    try:
        line = C.start(lambda text: incoming("celular", text), NAME, hear_phone,
                       V.synth_mp3 if voice_out else None, DOWNLOADS / "Bolha do celular", on_phone_file)
    except Exception as e:
        line = f"Celular desligado: {e}"
    if line:
        print(line)
    if C.running():
        U.watch(C.publish)


def run():
    """Laço do Jarvis: executa, um de cada vez, os pedidos digitados e falados."""
    global queue_mode, voice_out, origin
    threading.Thread(target=warm_up_ai, daemon=True).start()
    voice_out = "--mudo" not in sys.argv and V.can_speak()
    if not voice_out and "--mudo" not in sys.argv:
        print("Fala desligada: python -m pip install edge-tts")
    elif voice_out:
        print(V.voices_summary())
    if "--sem-voz" not in sys.argv:
        start_voice()
    start_phone()
    print("")
    queue_mode = True
    threading.Thread(target=keyboard_reader, daemon=True).start()
    threading.Thread(target=F.warm_up_everything, daemon=True).start()  # índice pronto antes da 1ª busca
    threading.Thread(target=F.store_apps, daemon=True).start()  # lista dos apps da Store, para o "abre"
    F.track_focus()
    F.on_alarm = lambda message: commands.put(("lembrete", message))  # timers também falam
    M.reminder_watcher(commands.put)
    D.weekly_watcher()  # M4: todo domingo sai o relatorio.md
    V.load_settings()  # a calibração do microfone
    threading.Thread(target=refresh_vocabulary, daemon=True).start()  # vocabulário pessoal para o Whisper
    if voice_out:
        V.prewarm(FILLERS + THANKS + ["Às suas ordens, senhor.", "Pois não, senhor?", "Parei, senhor.",
                                      "Pronto, senhor.", "Por nada, senhor."])  # 16: frases prontas
    I.watcher(commands.put)  # preços e encomendas vigiados
    U.card_filter = R.hide_card  # modo visita: os cards pessoais não aparecem
    threading.Thread(target=hud_loop, daemon=True).start()  # 99: HUD fixo
    theme = A.pref("tema")
    if theme:
        threading.Timer(3, U.theme, args=(theme,)).start()  # 101: o tema escolhido
    MA.watch_downloads(DOWNLOADS, commands.put)  # 103: avisa (no PC e no celular) quando um download termina
    if os.environ.get("BOLHA_NOTIFICACOES", "").strip() != "0":
        MA.watch_notifications(commands.put)  # 100: notificações do Windows viram card (com os pacotes winrt)
    threading.Thread(target=_startup_check, daemon=True).start()  # 105: autoteste ao abrir
    if os.environ.get("BOLHA_AREA_TRANSFERENCIA", "").strip() != "0":
        MA.watch_clipboard()  # histórico do que o senhor copia (só na memória, nunca em disco)
    if os.environ.get("BOLHA_AVISOS", "").strip() != "0":
        threading.Thread(target=watch_world, daemon=True).start()
    hint = offer_habit() or M.habit_hint()
    if hint:
        announce(hint, "Sugestão")
        try:  # a IA vê a sugestão na conversa e entende o "sim" que vier depois
            M.add_talk("(o Jarvis sugeriu ao abrir)", hint)
        except Exception:
            pass

    while True:
        expired, held = R.dnd_expired(set_windows_dnd=MA.windows_notifications)
        if expired:
            announce("O não perturbe acabou, senhor." + (R.held_summary(held) or " Não chegou nada."), "Aviso")
        try:
            origin, user_text = commands.get(timeout=0.5)  # com timeout o Ctrl+C funciona no Windows
        except queue.Empty:
            continue
        user_text = (user_text or "").strip()
        if not user_text:
            continue
        if origin in ("voz", "janela", "celular"):
            print(f"Você ({origin}) > {user_text}")
        if origin == "lembrete":
            announce(f"Senhor, lembrete: {user_text}", "Lembrete")
            continue
        if origin == "aviso":  # o Bolha percebeu algo sozinho (mensagem nova, bateria fraca)
            who = re.search(r"mensagem nova de (.+?):", user_text)
            if R.should_hold(user_text, who.group(1) if who else ""):
                continue  # não perturbe: conta depois
            announce(user_text, "Aviso")
            continue
        if origin == "alerta":  # aviso do próprio Bolha (Pomodoro, autoteste, internet): nunca é segurado
            announce(user_text, "Aviso")
            continue
        if origin == "despertador":
            try:
                wake_up(user_text)
            except Exception as e:
                print(f"Jarvis > Erro no despertador: {e}")
                set_state("parado")
            continue
        if origin == "agendado":  # pedido marcado para esta hora: faz como se o senhor tivesse pedido agora
            print(f"Jarvis > (agendado) {user_text}")
        if normalize(user_text) in {"sair", "exit", "quit"}:
            print("Jarvis > Até mais.")
            break
        try:
            respond(user_text)
        except Exception as e:
            print(f"Jarvis > Erro: {e}")
            set_state("parado")
    U.close()


def _startup_check():
    time.sleep(4)
    try:
        rows = AT.check_all(V, W, lambda: bool(F.find_es()))
    except Exception:
        return
    U.card("Autoteste", json.dumps({"itens": [{"nome": n, "ok": ok, "detalhe": d, "como": c} for n, ok, d, c in rows]},
                                   ensure_ascii=False), 12000)
    bad = [n for n, ok, *_ in rows if not ok and n not in ("WhatsApp (WAHA)", "Busca rápida (Everything)")]
    if bad:
        commands.put(("alerta", f"Senhor, no autoteste ficou fora: {', '.join(bad)}. Diga autoteste para ver como arrumar."))


def disable_quick_edit():
    """No console antigo, um clique na janela congela todos os print() (e o Jarvis junto)."""
    try:
        k32 = ctypes.windll.kernel32
        k32.GetStdHandle.restype = ctypes.c_void_p
        handle = k32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(handle, ctypes.byref(mode)):
            k32.SetConsoleMode(handle, (mode.value & ~0x0040) | 0x0080)  # sem QUICK_EDIT, com EXTENDED_FLAGS
    except Exception:
        pass


def main():
    disable_quick_edit()
    print("")
    print("==============================================")
    print(f"{NAME.upper():^46}")
    print("     comandos rápidos + IA: " + (" -> ".join(n for n, _ in ai_backends()) or "nenhuma (configure a chave)"))
    print("==============================================")
    print("")
    print("Digite o pedido e Enter. 'sair' fecha.")
    if "--sem-tela" not in sys.argv and U.available():
        started = threading.Event()

        def worker():
            started.set()
            try:
                run()
            except Exception:
                traceback.print_exc()
                print("Jarvis > Parei por causa do erro acima.")
            os._exit(0)

        try:
            U.start(worker, lambda text: incoming("janela", text), NAME)  # o reator fica na thread principal
        except Exception as e:
            print(f"A janela do reator não abriu ({e}). Sigo sem ela.")
            if started.is_set():  # o Jarvis já está rodando na outra thread
                while True:
                    time.sleep(3600)
        else:
            os._exit(0)  # fechou a janela: fecha tudo (voz e teclado ficam em threads)
    elif "--sem-tela" not in sys.argv:
        print("Sem interface: python -m pip install pywebview")
    run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nJarvis encerrado.")
