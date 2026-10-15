"""O motor que faz o Bolha melhorar: diário (M1), errou/boa (M2), exemplos (M3), relatório (M4),
cronômetro (M5), apelidos, pessoas e backup."""
import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import aprende as A
import diario as D

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def jarvis(monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_ai", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.calls = []
    monkeypatch.setattr(mod, "open_target", lambda t: mod.calls.append(("open_target", t)) or True)
    monkeypatch.setattr(mod.U, "heard", lambda t: None)
    monkeypatch.setattr(mod.U, "speech", lambda t: None)
    monkeypatch.setattr(mod.U, "card", lambda *a, **k: None)
    monkeypatch.setattr(mod.U, "state", lambda s: None)
    monkeypatch.setattr(mod.F, "foreground_window", lambda: None)
    monkeypatch.setattr(mod.F, "wait_new_window", lambda *a, **k: True)
    monkeypatch.setattr(mod.F, "second_monitor", lambda: None)
    monkeypatch.setattr(mod.U, "behind", lambda: None)
    mod.origin = "teste"
    return mod


# ------------------------- M1 e M5: diário e cronômetro -------------------------

def test_cada_pedido_vai_para_o_diario_com_tempos(jarvis):
    jarvis.respond("abre o edge")
    [e] = D.requests()
    assert e["disse"] == "abre o edge" and e["rota"] == "atalho" and e["ok"] is True
    assert e["acoes"] == [{"nome": "open_target", "args": {"target": "edge"}, "ok": True}]
    assert set(e["tempos"]) == {"ouvir", "pensar", "fazer", "falar"}


def test_o_que_deu_errado_hoje_lista_os_que_falharam(jarvis, monkeypatch, capsys):
    monkeypatch.setattr(jarvis, "open_target", lambda t: False)
    jarvis.respond("abre o programa que não existe")
    jarvis.respond("o que deu errado hoje?")
    out = capsys.readouterr().out
    assert "1 pedido deu errado" in out and "programa que não existe" in out


def test_cronometro_aparece_no_console(jarvis, capsys, monkeypatch):
    jarvis.origin = "teclado"
    jarvis.respond("abre o edge")
    assert "(tempo " in capsys.readouterr().out


def test_tempo_aninhado_nao_conta_duas_vezes():
    D.start("x")
    with D.timing("fazer"):
        with D.timing("fazer"):
            pass
    assert D.current["tempos"]["fazer"] < 0.5
    D.finish("ok")


def test_por_que_voce_fez_isso(jarvis, capsys):
    jarvis.respond("abre o edge")
    capsys.readouterr()
    jarvis.respond("por que você fez isso?")
    out = capsys.readouterr().out
    assert "abre o edge" in out and "open_target" in out


# ------------------------- M2 e M3: errou e boa -------------------------

def test_errou_era_o_chrome_corrige_e_aprende(jarvis):
    jarvis.respond("abre o edge")
    assert jarvis.calls == [("open_target", "edge")]
    jarvis.respond("errou, era o Chrome")
    assert jarvis.calls[-1] == ("open_target", "Chrome")  # já fez o certo
    jarvis.calls.clear()
    jarvis.respond("abre o edge")  # da próxima vez acerta sozinho, sem IA
    assert jarvis.calls == [("open_target", "Chrome")]
    assert D.requests()[-1]["rota"] == "aprendido"


def test_nota_nao_vira_o_ultimo_pedido(jarvis):
    jarvis.respond("abre o edge")
    jarvis.respond("boa")
    assert D.last["disse"] == "abre o edge"
    assert A.load()["exemplos"][0]["nota"] == 1


def test_feedback_reconhece_as_frases():
    assert A.is_feedback("Errou, era o Chrome.") == (False, "Chrome")
    assert A.is_feedback("não, eu queria o spotify") == (False, "Spotify")
    assert A.is_feedback("errou") == (False, "")
    assert A.is_feedback("boa, Bolha!") == (True, "")
    assert A.is_feedback("abre o chrome") is None
    assert A.is_feedback("não") is None  # "não" sozinho é resposta de confirmação


def test_acerto_da_ia_vira_exemplo_para_pedido_parecido(jarvis, monkeypatch):
    answer = '{"actions":[{"name":"open_target","args":{"target":"omori"}}],"reply":"Abrindo."}'
    monkeypatch.setattr(jarvis, "think", lambda *a, **k: jarvis.parse_json(answer))
    jarvis.respond("quero jogar aquele jogo do omori")
    prompt = A.examples_prompt("quero jogar o jogo do omori")
    assert "aquele jogo do omori" in prompt and "open_target" in prompt
    assert jarvis.ai_context("quero jogar o jogo do omori").count("Pedidos parecidos") == 1


def test_errou_tira_dos_exemplos():
    A.learn_example("toca lofi", [{"name": "play_youtube", "args": {"query": "lofi"}}])
    A.rate({"disse": "toca lofi", "acoes": []}, False)
    assert A.load()["exemplos"] == []


def test_correcao_troca_o_argumento_principal():
    acts = [{"nome": "play_youtube", "args": {"query": "lofi"}, "ok": True}]
    assert A.corrected_actions(acts, "jazz") == [{"name": "play_youtube", "args": {"query": "jazz"}}]
    assert A.corrected_actions([], "jazz") is None


# ------------------------- M4: relatório da semana -------------------------

def test_relatorio_da_semana_tem_falhas_e_lentidao():
    for i in range(3):
        D.start("abre o omori")
        D.action("open_target", {"target": "omori"}, False)
        D.current.add_time("pensar", 5.0)
        D.finish("Não achei")
    D.start("qual o volume")
    D.finish("50")
    text = D.build_report()
    assert '1. "abre o omori" (3x)' in text
    assert "pensar: 5.0 s em média" in text
    assert "Pedidos: 4" in text


def test_relatorio_sai_no_domingo():
    sunday = datetime(2026, 10, 18, 10)
    assert D.report_due(sunday) is True
    D.write_report(sunday)
    assert D.REPORT.exists()
    import os
    os.utime(D.REPORT, (sunday.timestamp(), sunday.timestamp()))
    assert D.report_due(sunday) is False
    assert D.report_due(sunday - timedelta(days=1)) is False


def test_relatorio_de_erro_esconde_chaves(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_segredo1234567890abcdefghij")
    D.start("pesquisa algo")
    D.error("falhou com a chave gsk_segredo1234567890abcdefghij")
    D.finish("")
    D.error_report()
    text = D.ERROR_REPORT.read_text(encoding="utf-8")
    assert "segredo" not in text and "[escondido]" in text


# ------------------------- apelidos, pessoas, backup -------------------------

@pytest.mark.parametrize("frase, esperado", [
    ("quando eu falar meu jogo é o Omori", ("meu jogo", "Omori")),
    ("o patrão é apelido do Erick Cuba", ("o patrao", "Erick Cuba")),
    ("apelido: a casa da vó é Curitiba", ("a casa da vo", "Curitiba")),
    ("quando eu disser modo aula, abre o Teams", None),  # isso é habilidade
    ("abre o chrome", None),
])
def test_entende_apelido(frase, esperado):
    assert A.parse_alias(frase) == esperado


def test_apelido_e_usado_nos_pedidos(jarvis):
    jarvis.respond("quando eu falar meu jogo é o Omori")
    jarvis.calls.clear()
    jarvis.respond("abre o meu jogo")
    assert jarvis.calls == [("open_target", "Omori")]


def test_aniversario_e_pessoas(jarvis, capsys):
    jarvis.respond("o aniversário do Erick é 3 de maio")
    assert A.load()["pessoas"]["erick"]["aniversario"] == "3 de maio"
    assert A.birthdays_on(datetime(2027, 5, 3).date()) == ["Erick"]
    jarvis.respond("o que você sabe sobre o Erick?")
    assert "3 de maio" in capsys.readouterr().out


def test_o_que_aprendeu_essa_semana(jarvis, capsys):
    A.set_alias("meu jogo", "Omori")
    capsys.readouterr()
    jarvis.respond("o que você aprendeu essa semana?")
    assert "meu jogo" in capsys.readouterr().out


def test_backup_da_memoria(tmp_path):
    A.CONFIG.mkdir(parents=True, exist_ok=True)
    (A.CONFIG / "memoria.json").write_text("{}", encoding="utf-8")
    target = A.backup(str(tmp_path / "bk"))
    import zipfile
    assert any(n.endswith("memoria.json") for n in zipfile.ZipFile(target).namelist())


def test_painel_da_memoria_tem_botao_de_apagar():
    A.set_alias("meu jogo", "Omori")
    items = A.panel_items({"perfil": {"nome": "João"}, "fatos": [], "lembretes": []})
    assert {"tipo": "apelido", "texto": "meu jogo = Omori", "apaga": "esquece o apelido meu jogo"} in items
    assert items[0]["apaga"] == "esquece nome"


# ------------------------- 28: hábito vira rotina; 31: preferências automáticas -------------------------

def _log(lines):
    import memoria
    memoria.ACTION_LOG.write_text("".join(f"{t}\t{n}\t{d}\n" for t, n, d in lines), encoding="utf-8")


def test_habito_de_toda_segunda_vira_rotina(jarvis, monkeypatch):
    import memoria
    mondays = ["2026-09-21", "2026-09-28", "2026-10-05"]
    _log([(f"{d}T08:0{i}:00", "open_target", '{"target": "teams"}') for i, d in enumerate(mondays)])
    now = datetime(2026, 10, 10, 9, 0)
    [h] = memoria.habit_routines(now)
    assert h["pedido"] == "abre teams" and h["repetir"] == "semanal" and h["dia"] == "2026-10-12"
    assert "toda segunda" in h["texto"]
    monkeypatch.setattr(memoria, "habit_routines", lambda: [h])
    assert jarvis.offer_habit().startswith("Senhor, toda segunda")
    jarvis.respond("sim")
    [r] = memoria.load()["lembretes"]
    assert r["texto"] == "abre teams" and r["repetir"] == "semanal" and r["pedido"] and r["hora"] == "08:01"
    assert jarvis.offer_habit() == ""  # não pergunta de novo


def test_horarios_espalhados_nao_viram_rotina():
    import memoria
    _log([("2026-10-01T08:00:00", "play_youtube", '{"query": "lofi"}'),
          ("2026-10-02T15:00:00", "play_youtube", '{"query": "lofi"}'),
          ("2026-10-03T22:00:00", "play_youtube", '{"query": "lofi"}')])
    assert memoria.habit_routines(datetime(2026, 10, 10)) == []


def test_aprende_a_musica_de_cada_hora(jarvis):
    for _ in range(3):
        jarvis.learn_from_action("play_youtube", {"query": "Lofi"}, True)
    period = "manha" if datetime.now().hour < 12 else "tarde" if datetime.now().hour < 18 else "noite"
    assert A.pref(f"musica_{period}") == "lofi"
    import rotina
    assert rotina.mood_query("") == "lofi"


def test_volume_preferido_de_cada_programa(jarvis, monkeypatch):
    A.app_volume_pref("spotify", 35)
    applied = []
    monkeypatch.setattr(jarvis, "set_volume", lambda v: applied.append(v))
    import threading
    monkeypatch.setattr(threading, "Timer", lambda s, fn, args=(): type("T", (), {"start": lambda self: fn(*args)})())
    jarvis.learn_from_action("open_target", {"target": "Spotify"}, True)
    assert applied == [35]


def test_perguntas_sobre_o_bolha_nao_viram_o_ultimo_pedido(jarvis, capsys):
    jarvis.respond("abre o edge")
    jarvis.respond("o que deu errado hoje?")
    capsys.readouterr()
    jarvis.respond("por que você fez isso?")
    assert "abre o edge" in capsys.readouterr().out
