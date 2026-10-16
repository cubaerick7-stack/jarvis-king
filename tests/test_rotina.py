"""Rotina: modos com "sai do modo", não perturbe, VIP, visita, Pomodoro, listas, contas, chuva, humor e contagem."""
import importlib.util
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import memoria
import rotina as R

ROOT = Path(__file__).resolve().parents[1]


def test_modo_faz_tudo_e_sai_do_modo_desfaz():
    done = []
    execute = lambda name, args: done.append((name, args)) or True  # noqa: E731
    assert R.enter_mode("modo aula", execute, get_volume=lambda: 70)
    assert ("set_volume", {"percent": 30}) in done and R.dnd_active()
    done.clear()
    assert R.exit_mode(execute)
    assert done == [("set_volume", {"percent": 70})] and not R.dnd_active()


def test_modo_desconhecido_volta_none():
    assert R.enter_mode("modo xyz", lambda n, a: True) is None


def test_modos_do_senhor_por_cima_dos_de_fabrica():
    R._save(R.USER_MODES, {"aula": {"acoes": [{"name": "set_volume", "args": {"percent": 5}}]}, "leitura": {"acoes": []}})
    assert R.modes()["aula"]["acoes"] == [{"name": "set_volume", "args": {"percent": 5}}]
    assert R.find_mode("modo leitura") == "leitura"


def test_nao_perturbe_segura_e_vip_passa():
    R.set_vip("Mãe")
    R.start_dnd(None)
    assert R.should_hold("Senhor, mensagem nova de Erick: oi", "Erick")
    assert not R.should_hold("Senhor, mensagem nova de Mãe: oi", "Mãe")
    held = R.stop_dnd()
    assert len(held) == 1 and "Erick" in R.held_summary(held)


def test_nao_perturbe_ate_um_horario():
    now = datetime(2026, 10, 15, 14, 0)
    assert R.dnd_until_text("até as 18h", now) == datetime(2026, 10, 15, 18, 0)
    assert R.dnd_until_text("por 30 minutos", now) == now + timedelta(minutes=30)
    assert R.dnd_until_text("até as 9", now) == datetime(2026, 10, 16, 9, 0)
    agora = datetime.now()  # o "segura o aviso" olha o relógio de verdade: data fixa aqui quebrava no dia seguinte
    R.start_dnd(agora + timedelta(minutes=1))
    R.should_hold("aviso 1")
    assert R.dnd_expired(agora) == (False, [])
    expired, held = R.dnd_expired(agora + timedelta(minutes=2))
    assert expired and held[0][1] == "aviso 1"


def test_modo_visita_esconde_cards_pessoais():
    assert not R.hide_card("WhatsApp")
    R.state["visita"] = True
    assert R.hide_card("WhatsApp") and R.hide_card("Lembrete") and not R.hide_card("Clima")


def test_listas_de_compras_por_secao_e_riscar(capsys):
    R.add_items("compras", "ovo, arroz e detergente")
    R.add_items("lista de compras", "ovo")  # já estava
    R.check_item("compras", "arroz")
    key, text = R.list_text("compras")
    assert "Laticínios:" in text and "Mercearia:" in text and "✓ arroz" in text and "• ovo" in text
    assert R.remove_items("compras", "detergente")
    assert R.clear_list("compras", lambda q: False) is False


def test_tarefas_com_prioridade():
    R.add_items("tarefas", "lavar o carro")
    R.add_items("tarefas", "pagar o boleto", "alta")
    _, text = R.list_text("tarefas")
    assert text.splitlines()[0] == "1. pagar o boleto (alta)"


def test_contas_com_lembrete_mensal(capsys):
    added = []
    R.add_bill("luz", "dia 10", "150,90", lambda *a, **k: added.append((a, k)))
    assert len(added) == 2 and all(k["repetir"] == "mensal" for _, k in added)
    R.list_bills(date(2026, 10, 15))
    out = capsys.readouterr().out
    assert "luz R$ 150,90: dia 10" in out


def test_proximo_vencimento():
    assert R.next_due(10, date(2026, 10, 15)) == date(2026, 11, 10)
    assert R.next_due(31, date(2026, 2, 1)) == date(2026, 2, 28)


def test_chuva_antes_de_sair(capsys):
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    hours = [(now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(8)]

    def get_json(url):
        if "geocoding" in url:
            return {"results": [{"latitude": 1, "longitude": 2, "name": "Curitiba"}]}
        return {"hourly": {"time": hours, "precipitation_probability": [0, 10, 80, 20, 0, 0, 0, 0]}}
    R.rain_warning("Curitiba", get_json=get_json)
    assert "Leve o guarda-chuva" in capsys.readouterr().out


def test_musica_por_humor_e_hora():
    assert "animadas" in R.mood_query("algo para animar")
    assert "lofi" in R.mood_query("focar")
    assert R.mood_query("", hour=23) == "música relaxante calma"


def test_contagem_regressiva(capsys):
    R.add_countdown("a prova", (date.today() + timedelta(days=10)).isoformat())
    assert R.days_until("prova") == 10
    reminders = [{"texto": "viagem para a praia", "data": (date.today() + timedelta(days=3)).isoformat()}]
    assert R.days_until("viagem", reminders) == 3


def test_lembrete_repetido_continua_marcado():
    memoria.add_reminder("aluguel", "2026-10-05", "09:00", repetir="mensal")
    items = memoria.due_items(datetime(2026, 10, 5, 9, 1))
    assert items == [("lembrete", "aluguel")]
    [r] = memoria.load()["lembretes"]
    assert r["data"] == "2026-11-05" and not r["avisado"]


def test_proxima_data_dos_lembretes_que_repetem():
    assert memoria.next_date(date(2026, 10, 16), "dias úteis") == date(2026, 10, 19)
    assert memoria.next_date(date(2026, 1, 31), "mensal") == date(2026, 2, 28)
    assert memoria.next_date(date(2024, 2, 29), "anual") == date(2025, 2, 28)


# ------------------------- comandos de voz -------------------------

@pytest.fixture
def jarvis(monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_ai", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.calls = []
    monkeypatch.setattr(mod, "tool", lambda _n, /, **a: mod.calls.append((_n, a)) or True)
    monkeypatch.setattr(mod, "act", lambda _n, fn, *a: mod.calls.append((_n, a)) or True)
    return mod


@pytest.mark.parametrize("frase, esperado", [
    ("modo aula", ("enter_mode", {"name": "aula"})),
    ("ativa o modo jogo", ("enter_mode", {"name": "jogo"})),
    ("sai do modo", ("exit_mode", {})),
    ("vou dormir", ("good_night", {})),
    ("não perturbe até as 18h", ("dnd_on", {"until": "ate as 18h"})),
    ("desliga o não perturbe", ("dnd_off", {})),
    ("a Mãe é VIP", ("set_vip", {"name": "Mãe", "on": True})),
    ("começa um pomodoro", ("start_pomodoro", {"minutes": 25})),
    ("pomodoro de 50", ("start_pomodoro", {"minutes": 50})),
    ("para o pomodoro", ("stop_pomodoro", {})),
    ("anota ovo e leite na lista de compras", ("list_add", {"list": "compras", "items": "ovo e leite"})),
    ("mostra a lista de compras", ("list_show", {"list": "compras"})),
    ("já comprei o leite", ("list_check", {"list": "compras", "items": "leite"})),
    ("tira o arroz da lista", ("list_remove", {"list": "compras", "items": "arroz"})),
    ("liga o lembrete de água", ("wellness_on", {"kind": "agua", "minutes": 60})),
    ("a conta de luz vence dia 10", ("add_bill", {"name": "luz", "day": 10, "value": ""})),
    ("quais contas vencem esse mês?", ("list_bills", {})),
    ("levo guarda-chuva?", ("rain_warning", {})),
    ("toca algo para animar", ("play_mood", {"mood": "animar"})),
    ("quantos dias faltam para a prova?", ("days_until", {"name": "prova"})),
    ("quais integrações eu tenho?", ("integrations", {})),
    ("tenho e-mail novo?", ("gmail_list", {})),
    ("o que tenho hoje na agenda?", ("calendar_events", {"day": "hoje"})),
    ("rastreia a encomenda AB123456789BR", ("track_parcel", {"code": "AB123456789BR"})),
    ("faz um autoteste", ("self_test", {})),
    ("se atualiza", ("update_bolha", {})),
    ("procura o documento que fala de multa", ("search_content", {"query": "multa"})),
    ("lê o primeiro em voz alta", ("read_aloud", {"path": "1"})),
    ("quero ditar uma carta", ("start_dictation", {"name": ""})),
    ("soma a coluna valor da planilha gastos", ("sum_column", {"path": "gastos", "column": "valor"})),
    ("mostra as fotos de julho", ("photos_from", {"when": "julho"})),
    ("abre o último arquivo baixado", ("last_download", {"open": True})),
])
def test_comandos_da_rotina(jarvis, frase, esperado):
    assert jarvis.fast_local_router(frase)
    assert jarvis.calls[0] == esperado


def test_continua_so_vira_leitura_quando_esta_lendo(jarvis):
    import documentos
    jarvis.fast_local_router("continua")
    assert jarvis.calls[0][0] == "media_control"
    documentos.reader.update(partes=["a", "b"], i=0, ativo=True)
    jarvis.calls.clear()
    jarvis.fast_local_router("continua")
    assert jarvis.calls[0][0] == "reading_control"
    documentos.reader.update(partes=[], i=0, ativo=False)


def test_ditado_pega_tudo_que_o_senhor_fala(jarvis, tmp_path):
    import documentos
    documentos.start_dictation("teste.txt", tmp_path)
    jarvis.handle("abre o chrome")  # durante o ditado, isso é texto
    jarvis.handle("fim do ditado")
    assert (tmp_path / "teste.txt").read_text(encoding="utf-8").strip() == "Abre o chrome"
