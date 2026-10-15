"""Documentos: busca dentro dos arquivos, ler em voz alta em partes, ditado, planilhas, fotos por data."""
import os
import time
import zipfile
from datetime import date
from pathlib import Path

import documentos as DOC


def test_busca_dentro_dos_arquivos_e_usa_o_indice(tmp_path):
    tmp_path = tmp_path / "docs"
    tmp_path.mkdir()
    (tmp_path / "contrato.txt").write_text("O prazo de entrega é 30 dias e a multa é de 2%.", encoding="utf-8")
    (tmp_path / "outro.txt").write_text("Nada a ver.", encoding="utf-8")
    DOC.write_docx(tmp_path / "carta.docx", ["Querida Ana", "a multa foi paga"])
    found = DOC.search_content("multa", [tmp_path])
    assert {Path(p).name for p, _ in found} == {"contrato.txt", "carta.docx"}
    assert DOC.INDEX.exists()
    assert DOC.search_content("prazo multa", [tmp_path])[0][0].endswith("contrato.txt")


def test_le_em_voz_alta_em_partes(tmp_path, capsys):
    text = " ".join(f"Frase número {i} do documento." for i in range(400))
    (tmp_path / "livro.txt").write_text(text, encoding="utf-8")
    assert DOC.read_aloud(tmp_path / "livro.txt")
    out = capsys.readouterr().out
    total = len(DOC.reader["partes"])
    assert total >= 10 and f"parte 1 de {total}" in out and "Diga continua" in out
    DOC.reading_control("continua")
    assert DOC.reader["i"] == 1
    DOC.reading_control("volta")
    assert DOC.reader["i"] == 0
    DOC.reading_control("lê a parte 5")
    assert DOC.reader["i"] == 4
    DOC.reading_control("para")
    assert "Parei na parte 5" in capsys.readouterr().out


def test_partes_terminam_em_fim_de_frase():
    parts = DOC.split_parts("Primeira frase. " * 200, size=300)
    assert all(p.endswith(".") for p in parts)


def test_ditado_vira_word_com_pontuacao(tmp_path):
    DOC.start_dictation("Carta", tmp_path)
    DOC.dictate("querida ana vírgula tudo bem ponto de interrogação")
    DOC.dictate("frase errada")
    DOC.dictate("apaga a última frase")
    DOC.dictate("um abraço ponto final")
    path = DOC.dictate("fim do ditado")
    assert path.endswith("Carta.docx")
    xml = zipfile.ZipFile(path).read("word/document.xml").decode()
    assert "Querida ana, tudo bem?" in xml and "Um abraço." in xml and "errada" not in xml
    assert DOC.dictation["ativo"] is False


def test_planilha_soma_coluna_pelo_nome_e_pela_letra(tmp_path, capsys):
    path = DOC.create_sheet(tmp_path / "gastos", ["Item", "Valor"], [["luz", 150.5], ["água", 80], ["net", 99.9]])
    assert DOC.sum_column(path, "valor") == 330.4
    assert DOC.sum_column(path, "B") == 330.4
    assert "330,40" in capsys.readouterr().out
    assert DOC.read_sheet(path)[1] == ["luz", 150.5]


def test_planilha_csv_brasileira(tmp_path):
    (tmp_path / "x.csv").write_text("nome;valor\na;1.234,50\nb;10,00\n", encoding="utf-8")
    assert DOC.sum_column(tmp_path / "x.csv", "valor") == 1244.5


def test_fotos_por_data(tmp_path):
    for name, when in (("praia.jpg", (2024, 7, 10)), ("natal.jpg", (2024, 12, 25))):
        p = tmp_path / name
        p.write_bytes(b"x")
        t = time.mktime((*when, 12, 0, 0, 0, 0, -1))
        os.utime(p, (t, t))
    found = DOC.photos_from("julho de 2024", [tmp_path])
    assert [Path(p).name for p in found] == ["praia.jpg"]


def test_entende_o_mes():
    today = date(2026, 10, 15)
    assert DOC.parse_month("julho", today) == (2026, 7)
    assert DOC.parse_month("dezembro", today) == (2025, 12)
    assert DOC.parse_month("mês passado", today) == (2026, 9)
    assert DOC.parse_month("2024", today) == (2024, None)


def test_ultimo_baixado(tmp_path):
    (tmp_path / "a.pdf").write_text("x")
    time.sleep(0.01)
    (tmp_path / "b.zip").write_text("x")
    (tmp_path / "c.crdownload").write_text("x")
    assert DOC.last_download(tmp_path).name == "b.zip"


def test_pergunta_sobre_o_documento(tmp_path, capsys):
    (tmp_path / "c.txt").write_text("Prazo: 30 dias.", encoding="utf-8")
    seen = {}

    def think(system, user, **kw):
        seen["user"] = user
        return "O prazo é de 30 dias."
    assert DOC.ask_document(tmp_path / "c.txt", "qual o prazo?", think)
    assert "Prazo: 30 dias." in seen["user"] and "O prazo é de 30 dias." in capsys.readouterr().out
