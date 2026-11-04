import os
import hashlib
import subprocess
from datetime import datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel, QFileDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from .config import cfg
from .backends import generate_qr, copy_image_to_clipboard, copy_text_to_clipboard, notify

class QRDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Share-L — Генератор QR-кодов")
        self.resize(420, 460)
        layout = QVBoxLayout(self)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Введите ссылку или текст для генерации QR...")
        layout.addWidget(self.input_edit)

        btn_gen = QPushButton("Сгенерировать QR-код")
        btn_gen.clicked.connect(self.make_qr)
        layout.addWidget(btn_gen)

        self.qr_lbl = QLabel("Здесь появится QR-код")
        self.qr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.qr_lbl, 1)

        btn_copy = QPushButton("📋 Скопировать QR в буфер обмена")
        btn_copy.clicked.connect(self.copy_qr)
        layout.addWidget(btn_copy)
        self.tmp_qr = "/tmp/sharex_qr.png"

    def make_qr(self):
        txt = self.input_edit.text().strip()
        if txt and generate_qr(txt, self.tmp_qr):
            self.qr_lbl.setPixmap(QPixmap(self.tmp_qr).scaled(280, 280, Qt.AspectRatioMode.KeepAspectRatio))

    def copy_qr(self):
        if os.path.exists(self.tmp_qr):
            copy_image_to_clipboard(self.tmp_qr)
            notify("Share-L QR", "QR-код скопирован в буфер обмена!", self.tmp_qr)

class HashDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Share-L — Проверка хэш-сумм (MD5 / SHA256)")
        self.resize(520, 240)
        layout = QVBoxLayout(self)

        btn_pick = QPushButton("📂 Выбрать файл для расчета хэша...")
        btn_pick.clicked.connect(self.pick_file)
        layout.addWidget(btn_pick)

        self.md5_edit = QLineEdit()
        self.md5_edit.setReadOnly(True)
        self.md5_edit.setPlaceholderText("MD5...")
        layout.addWidget(self.md5_edit)

        self.sha_edit = QLineEdit()
        self.sha_edit.setReadOnly(True)
        self.sha_edit.setPlaceholderText("SHA256...")
        layout.addWidget(self.sha_edit)

    def pick_file(self):
        fp, _ = QFileDialog.getOpenFileName(self, "Выберите файл")
        if fp and os.path.exists(fp):
            m = hashlib.md5()
            s = hashlib.sha256()
            with open(fp, "rb") as f:
                while chunk := f.read(65536):
                    m.update(chunk)
                    s.update(chunk)
            self.md5_edit.setText(f"MD5:    {m.hexdigest()}")
            self.sha_edit.setText(f"SHA256: {s.hexdigest()}")
