"""Janela "Relatar problema": a pessoa escreve, o plugin junta o resto.

O texto e os enderecos saem de ui/bug_report.py, que nao depende de Qt e e
testado sem QGIS. Aqui fica so a janela e o que ela pede ao sistema: abrir o
programa de e-mail, o navegador e a area de transferencia.
"""

import platform

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QVBoxLayout,
)

from . import bug_report
from .support import log_quietly, qt_enum


def environment(plugin_version, language):
    """Versoes de tudo o que costuma explicar um erro."""
    info = {"plugin": plugin_version, "language": language,
            "python": platform.python_version(), "os": platform.platform(terse=True)}
    try:
        from qgis.core import Qgis
        info["qgis"] = Qgis.version()       # desde o QGIS 3.12; o minimo e 3.22
    except Exception as exc:  # o relato sai mesmo sem a versao do QGIS
        log_quietly("versao do QGIS para o relato", exc)
    try:
        from qgis.PyQt.QtCore import QT_VERSION_STR
        info["qt"] = QT_VERSION_STR
    except ImportError as exc:
        log_quietly("versao do Qt para o relato", exc)
    try:
        from osgeo import gdal
        info["gdal"] = gdal.__version__
    except ImportError as exc:
        log_quietly("versao do GDAL para o relato", exc)
    try:
        import numpy
        info["numpy"] = numpy.__version__
    except ImportError as exc:
        log_quietly("versao do NumPy para o relato", exc)
    try:
        import scipy
        info["scipy"] = scipy.__version__
    except ImportError:
        info["scipy"] = "not installed"
    return info


def _open(url):
    """Abre um endereco ja codificado, sem deixar o Qt recodifica-lo."""
    return QDesktopServices.openUrl(QUrl.fromEncoded(url.encode("ascii")))


class ReportDialog(QDialog):
    def __init__(self, parent, t, plugin_dir, plugin_version, language,
                 error="", log_path="", log=""):
        super().__init__(parent)
        self.t = t
        meta = bug_report.read_metadata(plugin_dir)
        self.address = meta.get("email", "").strip()
        self.repository = meta.get("repository", "").strip()
        self.version = plugin_version
        self.info = environment(plugin_version, language)
        self.error, self.log_path, self.log = error, log_path, log

        self.setWindowTitle(t("report_title"))
        self.setObjectName("ttReport")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(10)

        titulo = QLabel(t("report_title"))
        titulo.setObjectName("ttPageTitle")
        layout.addWidget(titulo)
        intro = QLabel(t("report_intro"))
        intro.setObjectName("ttPageSub")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # QTextEdit, e nao QPlainTextEdit, para herdar o estilo dos campos da
        # janela principal; o texto continua puro.
        self.description = QTextEdit()
        self.description.setAcceptRichText(False)
        self.description.setPlaceholderText(t("report_placeholder"))
        self.description.setMinimumHeight(110)
        layout.addWidget(self.description)

        tecnico = QLabel(t("report_tech"))
        tecnico.setObjectName("ttCardTitle")
        layout.addWidget(tecnico)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setAcceptRichText(False)
        self.details.setObjectName("ttLog")
        self.details.setMinimumHeight(120)
        self.details.setPlainText(bug_report.technical_block(self.info, error, log_path, log))
        layout.addWidget(self.details)

        if log_path:
            anexo = QLabel(t("report_attach").format(path=log_path))
            anexo.setObjectName("ttHelp")
            anexo.setWordWrap(True)
            anexo.setTextInteractionFlags(qt_enum("TextInteractionFlag", "TextSelectableByMouse"))
            layout.addWidget(anexo)

        botoes = QHBoxLayout()
        botoes.setSpacing(8)
        self.email_button = QPushButton(t("report_email"))
        self.email_button.setObjectName("ttPrimary")
        self.email_button.setEnabled(bool(self.address))
        self.email_button.clicked.connect(self._send_email)
        self.copy_button = QPushButton(t("report_copy"))
        self.copy_button.clicked.connect(self._copy)
        self.github_button = QPushButton(t("report_github"))
        self.github_button.setToolTip(t("report_github_tip"))
        self.github_button.setEnabled(bool(bug_report.issue_url(self.repository, "x", "", {})))
        self.github_button.clicked.connect(self._open_github)
        fechar = QPushButton(t("report_close"))
        fechar.setObjectName("ttGhost")
        fechar.clicked.connect(self.reject)
        for botao in (self.email_button, self.copy_button, self.github_button):
            botao.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
            botoes.addWidget(botao)
        botoes.addStretch(1)
        botoes.addWidget(fechar)
        layout.addLayout(botoes)

        self.status = QLabel(t("report_note").format(email=self.address))
        self.status.setObjectName("ttHelp")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(qt_enum("TextInteractionFlag", "TextSelectableByMouse"))
        layout.addWidget(self.status)

    def text(self):
        return bug_report.compose(self.description.toPlainText(), self.info,
                                  self.error, self.log_path, self.log)

    def _subject(self):
        return self.t("report_subject").format(version=self.version)

    def _copy(self):
        QApplication.clipboard().setText(self.text())
        self.status.setText(self.t("report_copied").format(email=self.address))

    def _send_email(self):
        # Copia antes de abrir: quem usa webmail nao tem programa de e-mail, e o
        # texto precisa estar pronto para colar de qualquer jeito.
        texto = self.text()
        QApplication.clipboard().setText(texto)
        aberto = _open(bug_report.mailto_url(self.address, self._subject(), texto))
        chave = "report_sent" if aberto else "report_no_mail"
        self.status.setText(self.t(chave).format(email=self.address))

    def _open_github(self):
        url = bug_report.issue_url(self.repository, self._subject(),
                                   self.description.toPlainText(), self.info,
                                   self.error, self.log)
        if url and _open(url):
            self.status.setText(self.t("report_github_done"))
