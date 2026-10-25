"""O relato de problema: o que vai junto, o que fica de fora e os enderecos."""

from urllib.parse import parse_qs, unquote, urlparse

from ui import bug_report

INFO = {"plugin": "1.5.1", "qgis": "4.0.2-Norrkoping", "qt": "6.8.3", "python": "3.12.10",
        "gdal": "3.11.4", "numpy": "2.2.6", "scipy": "1.15.3",
        "os": "Windows-11", "language": "pt"}
CASA = r"C:\Users\Fulana de Tal"


def test_o_nome_da_pessoa_nao_vai_no_relato():
    texto = bug_report.compose(
        "travou", INFO, error=r"Erro ao ler C:\Users\Fulana de Tal\Documents\mde.tif",
        log_path=r"c:/users/fulana de tal/Documents/saida_diagnostico_topotrail.log",
        log="linha 1\n" + CASA + r"\x.tif nao existe")
    texto = bug_report.anonymize(texto, CASA)
    assert "Fulana" not in texto and "fulana" not in texto
    assert r"~\Documents\mde.tif" in texto


def test_o_relato_leva_versoes_erro_e_fim_do_andamento():
    log = "\n".join("linha {}".format(i) for i in range(100))
    texto = bug_report.compose("A rota nao saiu.", INFO, error="Pontos nao se ligam",
                               log_path="", log=log)
    assert texto.startswith("A rota nao saiu.")
    for trecho in ("TopoTrail: 1.5.1", "QGIS: 4.0.2", "GDAL: 3.11.4", "Pontos nao se ligam",
                   "linha 99"):
        assert trecho in texto
    assert "linha 79" not in texto              # so as ultimas 20 linhas


def test_sem_descricao_o_relato_ainda_sai():
    assert bug_report.compose("", {}).startswith("(sem descricao)")


def test_mailto_vai_para_o_endereco_com_assunto_e_corpo():
    url = bug_report.mailto_url("herpetomantiqueira@gmail.com", "TopoTrail 1.5.1: relato",
                                "Texto com acento: travessia, cume & vale")
    partes = urlparse(url)
    assert partes.scheme == "mailto" and partes.path == "herpetomantiqueira@gmail.com"
    campos = parse_qs(partes.query)
    assert campos["subject"] == ["TopoTrail 1.5.1: relato"]
    assert campos["body"] == ["Texto com acento: travessia, cume & vale"]
    assert "+" not in url                       # espaco como %20: mailto nao entende +


def test_mailto_longo_e_cortado_e_avisa_que_o_resto_foi_copiado():
    corpo = "inicio importante\n" + "x" * 10000
    url = bug_report.mailto_url("a@b.c", "s", corpo)
    assert len(url) <= bug_report.MAILTO_LIMIT + 200
    texto = unquote(url.split("body=", 1)[1])
    assert texto.startswith("inicio importante")
    assert "area de transferencia" in texto


def test_o_github_abre_o_formulario_de_bug_preenchido():
    url = bug_report.issue_url("https://github.com/LuanCortesM/Topotrail", "TopoTrail 1.5.1: relato",
                               "Travou no passo 4", INFO, error="Erro X", log="a\nb")
    partes = urlparse(url)
    assert partes.netloc == "github.com" and partes.path == "/LuanCortesM/Topotrail/issues/new"
    campos = parse_qs(partes.query)
    # os ids sao os de .github/ISSUE_TEMPLATE/bug_report.yml
    assert campos["template"] == ["bug_report.yml"]
    assert campos["what-happened"] == ["Travou no passo 4"]
    assert campos["version"] == ["1.5.1"] and campos["qgis"] == ["4.0.2-Norrkoping"]
    assert "Erro X" in campos["log"][0]


def test_os_ids_do_formulario_existem_no_modelo_do_repositorio():
    import pathlib
    modelo = (pathlib.Path(__file__).resolve().parent.parent
              / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(encoding="utf-8")
    for campo in ("what-happened", "log", "qgis", "os", "version"):
        assert "id: " + campo in modelo


def test_github_com_registro_enorme_corta_o_comeco_e_cabe():
    log = "\n".join("linha {:05d} ".format(i) * 5 for i in range(5000))
    url = bug_report.issue_url("https://github.com/a/b", "t", "d", INFO, error="", log=log)
    assert len(url) <= bug_report.ISSUE_LIMIT


def test_repositorio_que_nao_e_do_github_nao_gera_endereco():
    assert bug_report.issue_url("", "t", "d", INFO) == ""
    assert bug_report.issue_url("https://gitlab.com/a/b", "t", "d", INFO) == ""


def test_o_metadata_tem_o_email_e_o_repositorio_do_relato():
    import pathlib
    meta = bug_report.read_metadata(str(pathlib.Path(__file__).resolve().parent.parent))
    assert meta["email"] == "herpetomantiqueira@gmail.com"
    assert meta["repository"].startswith("https://github.com/")
