"""Habilidades (skills): receitas em SKILL.md, criadas por voz, importadas só como texto."""
import importlib.util
from pathlib import Path

import pytest

import habilidades as H

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def jarvis(monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_ai", ROOT / "windows" / "jarvis_ai.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.calls = []
    for name in ("open_target", "set_volume", "mute_audio", "media_control", "change_volume"):
        monkeypatch.setattr(mod, name, lambda *a, _n=name: mod.calls.append((_n, a)) or True)
    for fn in ("heard", "speech", "card", "state", "behind"):
        monkeypatch.setattr(mod.U, fn, lambda *a, **k: None)
    monkeypatch.setattr(mod.F, "foreground_window", lambda: None)
    monkeypatch.setattr(mod.F, "second_monitor", lambda: None)
    monkeypatch.setattr(mod, "play_youtube", lambda q: mod.calls.append(("play_youtube", (q,))) or True)
    mod.TOOLS_BY_NAME["play_youtube"]["run"] = lambda a: mod.play_youtube(a.get("query", ""))
    mod.origin = "teste"
    return mod


def test_formato_do_skill_md():
    s = H.parse("---\nnome: Modo Aula\ndescricao: prepara a aula\ngatilhos: modo aula; vou ter aula\n---\n"
                "Abra o Teams.\n\n```acoes\n[{\"name\": \"set_volume\", \"args\": {\"percent\": 30}}]\n```\n"
                "```pedidos\nabre o Teams\n```\n")
    assert s.name == "modo-aula" and s["gatilhos"] == ["modo aula", "vou ter aula"]
    assert s["acoes"] == [{"name": "set_volume", "args": {"percent": 30}}]
    assert s["pedidos"] == ["abre o Teams"] and s["receita"] == "Abra o Teams." and s["aprovada"]


def test_aprende_habilidade_por_voz_e_usa_no_dia_seguinte(jarvis):
    jarvis.respond("Bolha, aprende uma habilidade: quando eu disser modo cinema, abrir a Netflix e colocar o volume em 80")
    assert (H.USER / "modo-cinema" / "SKILL.md").is_file()
    jarvis.calls.clear()
    jarvis.respond("modo cinema")
    assert ("open_target", ("a Netflix",)) in jarvis.calls or ("open_target", ("Netflix",)) in jarvis.calls
    assert ("set_volume", (80,)) in jarvis.calls


def test_varios_pedidos_numa_frase(jarvis):
    jarvis.respond("abre o Spotify, toca lofi e baixa o volume")
    names = [c[0] for c in jarvis.calls]
    assert names == ["open_target", "play_youtube", "change_volume"]


@pytest.mark.parametrize("frase", [
    "abre o bloco de notas e escreve lista de compras",  # escreve no que abriu: a IA faz junto
    "toca lofi às 7h e abre o Spotify",  # tem hora: a IA agenda
    "abre o chrome e fecha ele",  # "ele" depende da conversa
])
def test_nao_corta_o_que_depende_do_contexto(jarvis, frase):
    assert jarvis.split_multi(frase) == [frase]


RECEITAS = pytest.mark.skipif(False, reason="")


@RECEITAS
def test_habilidades_de_fabrica_existem_e_sao_validas():
    skills = H.load_all()
    assert len(skills) >= 70
    for s in skills.values():
        assert s["descricao"], s.name


def test_acoes_das_habilidades_existem_no_catalogo(jarvis):
    for s in H.load_all().values():
        for a in s["acoes"]:
            assert a["name"] in jarvis.TOOLS_BY_NAME, (s.name, a["name"])


@RECEITAS
def test_ia_ve_so_as_habilidades_do_assunto():
    text = H.prompt_for("quero fazer uma lista de compras")
    assert "lista-de-compras" in text
    assert text.count("\n- ") <= 8


def test_importa_so_o_texto_e_espera_aprovacao(jarvis, capsys):
    md = ("---\nnome: perigosa\ndescricao: teste\n---\nFaça isso.\n```python\nimport os; os.remove('x')\n```\n"
          "```acoes\n[{\"name\": \"set_volume\", \"args\": {\"percent\": 5}}]\n```\n")
    name = H.import_skill("https://exemplo.com/SKILL.md", fetch=lambda url: md.encode())
    text = (H.USER / name / "SKILL.md").read_text(encoding="utf-8")
    assert "os.remove" not in text and "aprovada: nao" in text
    jarvis.calls.clear()
    assert H.use(name, jarvis.run_actions, jarvis.handle) is False
    assert jarvis.calls == []  # não agiu sem aprovação
    assert H.approve(name, lambda q: True)
    assert H.use(name, jarvis.run_actions, jarvis.handle)
    assert jarvis.calls == [("set_volume", (5,))]


def test_so_importa_https():
    assert H.import_skill("http://exemplo.com/x.md", fetch=lambda u: b"") is False


def test_receita_sem_acoes_volta_para_a_ia_seguir(jarvis, monkeypatch):
    folder = H.USER / "receita"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nnome: receita\ndescricao: x\n---\nPasso 1: pesquise.", encoding="utf-8")
    answers = iter(['{"actions":[{"name":"use_skill","args":{"name":"receita"}}],"reply":""}',
                    '{"actions":[],"reply":"Feito, senhor."}'])
    seen = []

    def think(system, prompt, parse=None, **k):
        seen.append(prompt)
        return jarvis.parse_json(next(answers))
    monkeypatch.setattr(jarvis, "think", think)
    jarvis.ask_ai_router("faz a receita")
    assert "Passo 1: pesquise." in seen[1]


def test_ferramentas_citadas_nas_receitas_existem(jarvis):
    import re
    for s in H.load_all().values():
        for name in re.findall(r"\b[a-z]+_[a-z_]+\b", s["receita"]):
            if name in ("time_favorito",):  # campo do perfil, não ferramenta
                continue
            assert name in jarvis.TOOLS_BY_NAME, (s.name, name)


def test_gatilho_faz_as_acoes_e_a_ia_termina_a_receita(jarvis, monkeypatch):
    done = []
    jarvis.TOOLS_BY_NAME["rain_warning"]["run"] = lambda a: done.append("chuva") or True
    jarvis.TOOLS_BY_NAME["list_show"]["run"] = lambda a: done.append("lista") or True
    seen = []
    monkeypatch.setattr(jarvis, "ask_ai_router", lambda text, **k: seen.append(text) or True)
    jarvis.handle("vou sair")
    assert done == ["chuva", "lista"]
    assert "bloquear" in seen[0] and "Já feito" in seen[0]


def test_setenta_receitas_do_plano():
    planned = {s.get("plano") for s in H.load_all().values()}
    import re
    nums = sorted(int(p[1:]) for f in H.BUILTIN.glob("*/SKILL.md")
                  for p in re.findall(r"^plano: (S\d+)$", f.read_text(encoding="utf-8"), re.M))
    assert nums == list(range(1, 71))
