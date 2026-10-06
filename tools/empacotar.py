#!/usr/bin/env python3
"""Monta o zip publicavel do TopoTrail a partir do HEAD do repositorio.

Ate a 1.2.0 nao havia script nenhum: o zip era um `zip` da arvore de trabalho,
e por isso o pacote publicado levava 17 arquivos nao versionados de cache --
`.ruff_cache/` inteiro e `.pytest_cache/`, incluindo o `v/cache/lastfailed`,
que ia com os nomes dos testes que falhavam na maquina de quem empacotou para o
computador de cada usuario.

Aqui o conteudo sai de `git archive HEAD`, e nao do diretorio: nada que nao
esteja versionado entra, por construcao. Sobre isso ficam as exclusoes de
publicacao -- o que e versionado e util ao desenvolvimento, mas nao ao usuario
do plugin.

    python3 tools/empacotar.py                  # dist/TopoTrail-<versao>.zip
    python3 tools/empacotar.py --listar         # so lista o que entraria
    python3 tools/empacotar.py --saida /tmp/x   # outro diretorio de destino
"""
import argparse
import configparser
import io
import os
import subprocess
import sys
import tarfile
import zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_RAIZ_DO_ZIP = "TopoTrail"

# Diretorios versionados que nao vao para o usuario final.
DIRETORIOS_EXCLUIDOS = (
    "tests",
    "integracao",
    ".github",
    "validation",
    "tools",
    # O exemplo reprodutivel serve a quem le o repositorio, nao a quem instala o
    # plugin: sao 200 kB de MDE sintetico que o QGIS copiaria para o perfil de
    # cada usuario sem que nada os lesse.
    "exemplo",
)

# Qualquer cache de ferramenta, em qualquer profundidade. Nao deveriam estar
# versionados; a exclusao existe para que uma inclusao acidental no indice do
# git nao volte a vazar para o pacote.
DIRETORIOS_DE_CACHE = (
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tox",
    ".venv",
)


def versao_do_manifesto():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(os.path.join(RAIZ, "metadata.txt"), encoding="utf-8")
    return parser["general"]["version"].strip()


def deve_excluir(caminho):
    """Decide pela posicao do caminho DENTRO do plugin (sem a pasta raiz)."""
    partes = caminho.split("/")
    if partes[0] in DIRETORIOS_EXCLUIDOS:
        return True
    if any(parte in DIRETORIOS_DE_CACHE for parte in partes):
        return True
    if any(parte.endswith((".pyc", ".pyo")) for parte in partes):
        return True
    return False


def conteudo_do_head(raiz=RAIZ):
    """Devolve [(caminho_relativo, modo, bytes)] do HEAD, ja filtrado."""
    try:
        # core.autocrlf=false: sem isto, num Windows com autocrlf=true o
        # git archive grava CRLF e o mesmo HEAD da um zip diferente do Linux.
        tar_bytes = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "archive", "--format=tar", "HEAD"],
            cwd=raiz, check=True, stdout=subprocess.PIPE).stdout
    except (OSError, subprocess.CalledProcessError) as erro:
        raise SystemExit(
            "nao consegui rodar 'git archive HEAD' em {}: {}".format(raiz, erro))

    itens = []
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as arquivo:
        for membro in arquivo.getmembers():
            if not membro.isfile():
                continue
            if deve_excluir(membro.name):
                continue
            extraido = arquivo.extractfile(membro)
            itens.append((membro.name, membro.mode, extraido.read()))
    return sorted(itens)


def empacotar(destino=None, raiz=RAIZ):
    versao = versao_do_manifesto()
    destino = destino or os.path.join(raiz, "dist")
    os.makedirs(destino, exist_ok=True)
    caminho_zip = os.path.join(
        destino, "{}-{}.zip".format(PASTA_RAIZ_DO_ZIP, versao))
    itens = conteudo_do_head(raiz)
    if os.path.exists(caminho_zip):
        os.remove(caminho_zip)
    with zipfile.ZipFile(caminho_zip, "w", zipfile.ZIP_DEFLATED) as zip_saida:
        for caminho, modo, dados in itens:
            info = zipfile.ZipInfo("{}/{}".format(PASTA_RAIZ_DO_ZIP, caminho))
            # Data fixa: o mesmo HEAD tem de produzir o mesmo zip, byte a byte.
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.external_attr = (modo & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zip_saida.writestr(info, dados)
    return caminho_zip, [c for c, _, _ in itens]


def main(argv=None):
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--listar", action="store_true",
                            help="so lista o que entraria no pacote")
    analisador.add_argument("--saida", default=None,
                            help="diretorio de destino (padrao: dist/)")
    opcoes = analisador.parse_args(argv)

    if opcoes.listar:
        for caminho, _, _ in conteudo_do_head():
            print("{}/{}".format(PASTA_RAIZ_DO_ZIP, caminho))
        return 0

    caminho_zip, caminhos = empacotar(opcoes.saida)
    tamanho = os.path.getsize(caminho_zip)
    print("{} ({:,} bytes, {} arquivos, pasta raiz {}/)".format(
        caminho_zip, tamanho, len(caminhos), PASTA_RAIZ_DO_ZIP))
    return 0


if __name__ == "__main__":
    sys.exit(main())
