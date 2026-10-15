"""Cérebro e voz da fase 1: roteador Groq/Gemini com ferramentas nativas, escolha das ferramentas, contexto,
PARAR, papo, ver a tela, personalidade, perguntas com opções, frases prontas, fala em pedaços e vocabulário."""
import importlib.util
import json
from pathlib import Path

import pytest

import nuvem as N
import voz as V

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def jarvis(monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_ai", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.calls = []
    for fn in ("heard", "speech", "card", "state", "behind", "front"):
        monkeypatch.setattr(mod.U, fn, lambda *a, **k: mod.calls.append(("ui", a)) if fn == "card" else None)
    monkeypatch.setattr(mod.F, "foreground_window", lambda: None)
    monkeypatch.setattr(mod.F, "second_monitor", lambda: None)
    monkeypatch.setattr(mod, "open_target", lambda t: mod.calls.append(("open_target", t)) or True)
    mod.origin = "teste"
    return mod


# ------------------------- 14: quem decide e com quais ferramentas -------------------------

def test_escolhe_poucas_ferramentas_e_as_do_assunto(jarvis):
    names = [t["name"] for t in jarvis.select_tools("instala o VLC para mim")]
    assert "install_program" in names and "open_target" in names
    assert len(names) <= jarvis.MAX_TOOLS
    assert "gmail_send" not in names


def test_prompt_do_pedido_e_menor_que_o_catalogo_inteiro(jarvis):
    small = jarvis.build_ai_prompt(jarvis.select_tools("aumenta o volume"))
    assert len(small) < len(jarvis.AI_PROMPT) * 0.6


def test_esquema_das_ferramentas_nativas(jarvis):
    schemas = {s["function"]["name"]: s["function"]["parameters"]["properties"] for s in jarvis.tool_schemas(jarvis.TOOLS)}
    assert schemas["set_volume"]["percent"]["type"] == "number"
    assert schemas["mute_audio"]["mute"]["type"] == "boolean"
    assert schemas["search_web"]["site"]["type"] == "string"
    assert schemas["ask_choice"]["options"]["type"] == "array"
    assert schemas["create_sheet"]["rows"]["items"]["type"] == "array"
    assert all("_continuar" in p for p in schemas.values())


def test_pedido_simples_vai_pelo_groq_com_ferramentas_nativas(jarvis, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "y")
    seen = {}

    def groq_tools(system, user, tools, **kw):
        seen["tools"] = [t["function"]["name"] for t in tools]
        return {"actions": [{"name": "open_target", "args": {"target": "steam", "_continuar": False}}], "reply": "Abrindo."}
    monkeypatch.setattr(N, "groq_tools", groq_tools)
    monkeypatch.setattr(jarvis, "think", lambda *a, **k: pytest.fail("não devia usar o modo texto"))
    jarvis.ask_ai_router("quero jogar alguma coisa na steam")
    assert jarvis.calls[-1] == ("open_target", "steam")
    assert "open_target" in seen["tools"]


def test_pedido_pesado_vai_para_o_gemini(jarvis, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setattr(N, "groq_tools", lambda *a, **k: pytest.fail("pesado não vai pelo Groq"))
    used = {}

    def think(system, prompt, parse=None, prefer=None, **kw):
        used["prefer"] = prefer
        return parse('{"actions":[],"reply":"Explicado."}')
    monkeypatch.setattr(jarvis, "think", think)
    jarvis.ask_ai_router("me explica detalhadamente como funciona a fotossíntese")
    assert used["prefer"] is None


def test_se_as_ferramentas_nativas_falham_usa_o_texto(jarvis, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")

    def broken(*a, **k):
        raise N.CloudError("HTTP 400 tool_use_failed")
    monkeypatch.setattr(N, "groq_tools", broken)
    monkeypatch.setattr(jarvis, "think", lambda s, p, parse=None, **k: parse('{"actions":[],"reply":"Ok, senhor."}'))
    assert jarvis.ask_ai_router("abre algo legal") is True


def test_groq_tools_le_as_chamadas(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setattr(N, "_groq_listed", ["llama-3.3-70b-versatile"])
    answer = {"choices": [{"message": {"content": "", "tool_calls": [
        {"function": {"name": "set_volume", "arguments": '{"percent": 30}'}}]}}]}
    monkeypatch.setattr(N, "_groq_post", lambda body, key: answer)
    assert N.groq_tools("s", "u", []) == {"actions": [{"name": "set_volume", "args": {"percent": 30}}], "reply": ""}


# ------------------------- 13: contexto -------------------------

@pytest.mark.parametrize("frase, local", [
    ("fecha ele", False),
    ("manda isso pra Ana", False),
    ("fecha essa janela", True),
    ("me lembra em 10 minutos de tirar o bolo", True),
    ("isso", True),  # "isso" sozinho é um "sim" sem pergunta: não vai para a IA
])
def test_frases_com_ele_isso_la_vao_para_a_ia(jarvis, monkeypatch, frase, local):
    monkeypatch.setattr(jarvis, "tool", lambda *a, **k: True)
    monkeypatch.setattr(jarvis, "act", lambda *a, **k: True)
    jarvis.last_results = []
    assert jarvis.fast_local_router(frase) is local


# ------------------------- 5: PARAR -------------------------

def test_para_age_na_hora(jarvis, monkeypatch):
    stopped = []
    monkeypatch.setattr(V, "stop_speaking", lambda: stopped.append(True))
    jarvis.incoming("janela", "Bolha, para!")
    assert jarvis.stop_event.is_set() and stopped
    assert jarvis.commands.get_nowait() == ("janela", "Bolha, para!")


def test_parar_interrompe_o_agente(jarvis, monkeypatch):
    steps = []

    def think(*a, parse=None, **k):
        steps.append(1)
        jarvis.stop_event.set()  # o senhor apertou PARAR durante o passo
        return parse('{"actions":[{"name":"open_target","args":{"target":"x"}}],"reply":"","continue":true}')
    monkeypatch.setattr(jarvis, "think", think)
    jarvis.agent_task("abre tudo")
    assert len(steps) == 1


def test_nome_e_para_corta_a_fala():
    assert V.asks_stop("Bolha para") and V.asks_stop("bolha, chega")
    assert not V.asks_stop("o bolha vai para casa") and not V.asks_stop("para bolha")


# ------------------------- 18, 19, 20, 21, 23 -------------------------

def test_pergunta_com_opcoes(jarvis):
    jarvis.queue_mode = True
    jarvis.commands.put(("voz", "o segundo"))
    assert jarvis.choose("Qual dos dois, senhor?", ["Relatório 2024.pdf", "Relatório 2025.pdf"]) == "Relatório 2025.pdf"
    jarvis.commands.put(("janela", "relatório 2024"))
    assert jarvis.choose("Qual?", ["Relatório 2024.pdf", "Contrato.pdf"]) == "Relatório 2024.pdf"


def test_nao_repete_a_mesma_frase(jarvis, capsys):
    jarvis.fast_local_router("valeu")
    jarvis.fast_local_router("valeu")
    a, b = [line for line in capsys.readouterr().out.splitlines() if line.startswith("Jarvis >")]
    assert a != b


def test_personalidade_ajustavel(jarvis):
    jarvis.handle("fica mais sério")
    assert "SÉRIO" in jarvis.build_ai_prompt([])
    jarvis.handle("personalidade normal")
    assert "SÉRIO" not in jarvis.build_ai_prompt([])


def test_modo_papo_pergunta_de_volta_e_sai(jarvis, monkeypatch, capsys):
    monkeypatch.setattr(jarvis, "think", lambda *a, **k: "Boa escolha, senhor. Qual o seu preferido?")
    jarvis.handle("vamos conversar")
    jarvis.handle("gosto muito de filmes de ficção")
    jarvis.handle("abre o chrome")  # comando no meio do papo continua funcionando
    assert ("open_target", "chrome") in jarvis.calls
    jarvis.handle("tchau")
    assert jarvis.papo["ativo"] is False
    import aprende
    assert aprende.pref("papo_assunto") == "gosto muito de filmes de ficção"


def test_ve_a_tela(jarvis, monkeypatch, capsys):
    monkeypatch.setattr(jarvis, "_screen_png", lambda: b"png")
    monkeypatch.setattr(N, "vision", lambda prompt, png, mime="image/png": "É o erro 404: a página não existe.")
    jarvis.handle("qual o erro aqui?")
    assert "erro 404" in capsys.readouterr().out


def test_visao_do_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    sent = {}

    def post(model, body, key):
        sent["body"] = body
        return {"candidates": [{"content": {"parts": [{"text": "Uma tela azul."}]}}]}
    monkeypatch.setattr(N, "_search_post", post)
    assert N.vision("o que é?", b"\x89PNG") == "Uma tela azul."
    assert sent["body"]["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "image/png"


# ------------------------- voz: 7, 8, 2, 15, 16 -------------------------

def test_vocabulario_vai_para_o_whisper_e_corrige(monkeypatch):
    V.set_vocabulary(["Omori", "Erick Cuba"])
    assert "Omori" in N.STT_PROMPT and "Erick Cuba" in N.STT_PROMPT
    assert V.fix_words("abre o o mori") == "abre o Omori"
    assert V.fix_words("manda pro erik cuba") == "manda pro Erick Cuba"
    assert V.fix_words("toca para mim") == "toca para mim"
    V.set_vocabulary([])


def test_calibracao_do_microfone():
    threshold, noise, voice = V.calibration_threshold([200] * 60 + [3000] * 15)
    assert noise == 200 and voice == 3000 and 200 < threshold < 3000
    assert V.calibration_threshold([300] * 80) is None  # não ouviu voz


def test_fala_em_pedacos_e_cache(monkeypatch, tmp_path):
    made, played = [], []
    monkeypatch.setattr(V, "_synth", lambda text, path: made.append(text) or Path(path).write_bytes(b"mp3"))
    monkeypatch.setattr(V, "_play_mp3", lambda path: played.append(Path(path).name))
    V.say("Verifiquei, senhor. Em Curitiba está frio, com doze graus. Leve um casaco.")
    assert made == ["Verifiquei, senhor. Em Curitiba está frio, com doze graus.", "Leve um casaco."]
    assert len(played) == 2
    made.clear()
    V.say("Leve um casaco.")  # já falou essa: vem do cache, sem gerar de novo
    assert made == []


def test_para_no_meio_da_fala(monkeypatch):
    played = []
    monkeypatch.setattr(V, "_synth", lambda text, path: Path(path).write_bytes(b"mp3"))
    monkeypatch.setattr(V, "_mci", lambda cmd: None)

    def play(path):
        played.append(path)
        V.stop_speaking()  # o senhor disse "Bolha, para" durante a primeira frase
    monkeypatch.setattr(V, "_play_mp3", play)
    V.say("Primeira frase bem comprida aqui. Segunda frase que não deve tocar. Terceira também não.")
    assert len(played) == 1


def test_nome_parecido_so_vale_antes_de_um_pedido():
    assert V.after_wake("Bola, toca lofi", lenient_first=True) == "toca lofi"
    assert V.after_wake("Olha só que legal", lenient_first=True) is None


def test_frase_pronta_nao_toca_depois_da_resposta(monkeypatch):
    played = []
    monkeypatch.setattr(V, "_synth", lambda text, path: Path(path).write_bytes(b"mp3"))
    monkeypatch.setattr(V, "_play_mp3", lambda path: played.append(path))
    with V._say_lock:  # a resposta pede para falar enquanto a frase pronta ainda nem começou
        V.say_async("Verificando, senhor.")
        V._main_calls[0] += 1
    import time
    time.sleep(0.2)
    assert played == []
