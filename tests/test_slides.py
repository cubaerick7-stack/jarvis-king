"""Slides: roteiro arrumado, .pptx de verdade, Google Slides (simulado) e o pedido por voz."""
import importlib.util
import json
from pathlib import Path

import pytest

import slides as SL

ROOT = Path(__file__).resolve().parents[1]
PLANO = {"titulo": "Revolução Francesa", "subtitulo": "História", "slides": [
    {"layout": "topicos", "titulo": "Visão geral", "topicos": ["1789 a 1799", "Fim do Antigo Regime"], "notas": "Começo."},
    {"layout": "duas_colunas", "titulo": "Causas", "colunas": [{"titulo": "Econômicas", "topicos": ["Crise"]},
                                                              {"titulo": "Políticas", "topicos": ["Absolutismo"]}]},
    {"layout": "destaque", "titulo": "Bastilha", "destaque": "14/07/1789", "legenda": "o começo"},
    {"layout": "citacao", "titulo": "Declaração", "destaque": "Os homens nascem livres", "legenda": "1789"},
    {"layout": "inventado", "titulo": "Conclusão", "topicos": ["Napoleão"]},
    {"layout": "duas_colunas", "titulo": "Sem colunas", "topicos": ["vira tópicos"]}],
    "referencias": ["Hobsbawm, 1962"]}


def test_roteiro_arrumado():
    plan = SL.clean_outline(PLANO, "x", 8)
    assert [s["layout"] for s in plan["slides"]] == ["topicos", "duas_colunas", "destaque", "citacao", "topicos", "topicos"]
    assert SL.clean_outline(PLANO, "x", 3)["slides"].__len__() == 3
    with pytest.raises(ValueError):
        SL.clean_outline({"slides": []}, "x", 8)


def test_pptx_de_verdade(tmp_path):
    pptx = pytest.importorskip("pptx")
    path = SL.make_pptx(SL.clean_outline(PLANO, "x", 8), tmp_path / "a.pptx", "claro")
    prs = pptx.Presentation(path)
    assert len(prs.slides) == 8  # capa + 6 + referências
    texts = " ".join(sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)
    assert "Revolução Francesa" in texts and "14/07/1789" in texts and "Referências" in texts
    assert prs.slides[1].notes_slide.notes_text_frame.text == "Começo."


def test_google_slides_simulado(tmp_path):
    calls = []

    def google(url, data=None):
        calls.append((url, data))
        return {"presentationId": "P1", "slides": [{"objectId": "padrao"}]} if url.endswith("presentations") else {}
    link, pdf = SL.make_google(SL.clean_outline(PLANO, "x", 8), google, lambda url: b"%PDF", tmp_path / "a.pdf")
    assert link == "https://docs.google.com/presentation/d/P1/edit" and Path(pdf).read_bytes() == b"%PDF"
    reqs = calls[1][1]["requests"]
    assert reqs[-1] == {"deleteObject": {"objectId": "padrao"}}
    layouts = [r["createSlide"]["slideLayoutReference"]["predefinedLayout"] for r in reqs if "createSlide" in r]
    assert layouts[0] == "TITLE" and "TITLE_AND_TWO_COLUMNS" in layouts and "BIG_NUMBER" in layouts


def test_roteiro_usa_as_fontes():
    seen = {}

    def think(system, user, **kw):
        seen["user"] = user
        return json.dumps(PLANO)
    plan = SL.outline("revolução francesa", 6, "faculdade", think,
                      lambda q, n: [{"titulo": "Revolução", "site": "brasilescola.com", "trecho": "1789"}])
    assert "brasilescola.com" in seen["user"] and "Número de slides: 6" in seen["user"]
    assert len(plan["slides"]) == 6


@pytest.fixture
def jarvis(monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_ai", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.calls = []
    monkeypatch.setattr(mod, "tool", lambda _n, /, **a: mod.calls.append((_n, a)) or True)
    return mod


@pytest.mark.parametrize("frase, esperado", [
    ("faz um slide sobre a revolução francesa com 8 slides e manda pra mim no zap",
     {"topic": "a revolução francesa", "slides": 8, "where": "", "contact": "mim"}),
    ("faz uma apresentação sobre fotossíntese no google slides",
     {"topic": "fotossíntese", "slides": 8, "where": "google", "contact": ""}),
    ("cria 12 slides sobre direito civil", None),
    ("faz slides sobre a segunda guerra com 10 slides e manda pro Erick",
     {"topic": "a segunda guerra", "slides": 10, "where": "", "contact": "erick"}),
])
def test_pedido_de_slides(jarvis, frase, esperado):
    jarvis.fast_local_router(frase)
    if esperado is None:
        return  # vai para a IA (que chama make_slides)
    assert jarvis.calls[0] == ("make_slides", esperado)


def test_meu_whatsapp(jarvis):
    jarvis.fast_local_router("meu whatsapp é 41 99999-8888")
    assert jarvis.calls[0] == ("set_profile", {"key": "meu_whatsapp", "value": "41999998888"})
