"""Integrações: lista do que falta, preço vigiado, encomenda, casa inteligente; autoteste e sem internet."""
import autoteste as AT
import integracoes as I


def test_area_de_integracoes(monkeypatch, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    rows = I.integrations()
    out = capsys.readouterr().out
    assert any(r["nome"].startswith("Groq") and r["ligado"] for r in rows)
    assert "✗ Gemini" in out and "setx GEMINI_API_KEY" in out


def test_preco_da_pagina():
    assert I.extract_price('<script type="application/ld+json">{"price": "1299.90"}</script>') == 1299.9
    assert I.extract_price("<span>R$ 1.234,56</span>") == 1234.56
    assert I.extract_price("sem preço") is None


def test_vigia_preco_e_avisa_quando_baixa():
    pages = {"p": "R$ 100,00"}
    fetch = lambda url: pages["p"]  # noqa: E731
    assert I.watch_price("https://loja.com/fone", "fone", fetch=fetch)
    assert I.check_prices(fetch) == []
    pages["p"] = "R$ 89,90"
    assert I.check_prices(fetch) == ["Senhor, fone baixou de R$ 100,00 para R$ 89,90."]
    assert I.check_prices(fetch) == []  # já avisou


def test_encomenda_avisa_quando_muda(monkeypatch):
    monkeypatch.setenv("LINKETRACK_USER", "u")
    monkeypatch.setenv("LINKETRACK_TOKEN", "t")
    status = {"s": "Objeto postado"}
    fetch = lambda url: {"eventos": [{"status": status["s"], "data": "15/10", "hora": "10:00", "local": "SP"}]}  # noqa
    assert I.track_parcel("AB123456789BR", "tênis", fetch=fetch)
    assert I.check_parcels(fetch) == []
    status["s"] = "Objeto saiu para entrega"
    assert I.check_parcels(fetch) == ["Senhor, a encomenda tênis mudou: Objeto saiu para entrega."]
    status["s"] = "Objeto entregue ao destinatário"
    I.check_parcels(fetch)
    assert I._load(I.PARCELS, []) == []  # entregue sai da lista


def test_rastreio_sem_chave_explica(capsys, monkeypatch):
    monkeypatch.setattr("webbrowser.open", lambda url: True)
    assert I.track_parcel("AB123456789BR") is False
    assert "LINKETRACK" in capsys.readouterr().out


def test_google_sem_configurar_explica(capsys):
    assert I.gmail_list() is False
    assert "GOOGLE_CLIENT_ID" in capsys.readouterr().out


def test_mandar_email_pede_sim(monkeypatch):
    for v in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        monkeypatch.setenv(v, "x")
    sent = []
    monkeypatch.setattr(I, "_google", lambda *a, **k: sent.append(a))
    assert I.gmail_send("ana@x.com", "oi", "tudo bem?", lambda q: False) is False
    assert sent == []


def test_casa_inteligente_acha_pelo_nome(monkeypatch):
    monkeypatch.setenv("HA_URL", "http://ha")
    monkeypatch.setenv("HA_TOKEN", "t")
    calls = []

    def ha(path, data=None):
        if path == "/api/states":
            return [{"entity_id": "light.sala", "attributes": {"friendly_name": "Luz da Sala"}},
                    {"entity_id": "light.quarto", "attributes": {"friendly_name": "Luz do Quarto"}}]
        calls.append((path, data))
        return {}
    monkeypatch.setattr(I, "_ha", ha)
    assert I.home_control("luz do quarto", "desligar")
    assert calls == [("/api/services/light/turn_off", {"entity_id": "light.quarto"})]


def test_autoteste_diz_o_que_falta_e_como_arrumar(capsys):
    class Voz:
        def missing(self): return ["vosk"]
        def find_model(self): return None
    rows = AT.check_all(Voz(), None, lambda: False, net=True, mic=lambda: "")
    assert ("Microfone", False) == rows[1][:2]
    assert AT.report(rows) is False
    out = capsys.readouterr().out
    assert "Como arrumar" in out and "pip install vosk" in out


def test_sem_internet_avisa_uma_vez():
    assert AT.connection_changed(True) == ""
    assert "sem internet" in AT.connection_changed(False)
    assert AT.connection_changed(False) == ""
    assert "voltou" in AT.connection_changed(True)
