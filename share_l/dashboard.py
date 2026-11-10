import os
import ast
import glob
import subprocess
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QListWidget, QListWidgetItem, QLabel, QPushButton,
    QCheckBox, QLineEdit, QFileDialog, QComboBox, QSpinBox, QGroupBox,
    QFormLayout, QSystemTrayIcon, QMenu, QStyle, QSplitter
)
from PyQt6.QtCore import Qt, QSize, QTimer, QObject, pyqtSignal
from PyQt6.QtGui import QPixmap, QIcon, QAction, QMovie
from .config import cfg, get_secure_temp_file
from .backends import (
    capture_full_screen, copy_image_to_clipboard, upload_file,
    run_ocr, decode_qr, copy_text_to_clipboard, notify
)
from .overlay import ShareLOverlay
from .tools import QRDialog, HashDialog

try:
    from pynput import keyboard as pynput_kb
    HAS_PYNPUT = True
except Exception:
    HAS_PYNPUT = False


class HotkeyBridge(QObject):
    trigger_region = pyqtSignal()


class ShareLDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Share-L v1.2.0")
        self.resize(1080, 680)
        self.active_overlay = None
        self.force_quit = False
        self.current_movie = None

        QApplication.instance().setQuitOnLastWindowClosed(False)

        self.setStyleSheet('''
            QMainWindow, QWidget {
                background-color: #18191c; color: #e4e6eb;
                font-family: "Cantarell", "Inter", sans-serif; font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #2f3136; border-radius: 6px;
                margin-top: 12px; padding-top: 14px; font-weight: bold;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #00a8fc; }
            QPushButton {
                background-color: #2b2d31; border: 1px solid #3f4147;
                padding: 8px 14px; border-radius: 5px; font-weight: bold; color: #f2f3f5;
            }
            QPushButton:hover { background-color: #35373c; border-color: #00a8fc; }
            QLineEdit, QComboBox, QSpinBox {
                background-color: #111214; border: 1px solid #3f4147;
                padding: 6px 10px; border-radius: 4px; color: #ffffff;
            }
            QListWidget {
                background-color: #111214; border: 1px solid #2b2d31; border-radius: 6px; outline: none;
            }
            QListWidget::item { padding: 8px; border-bottom: 1px solid #1e1f22; }
            QListWidget::item:selected { background-color: #0078d7; color: white; border-radius: 4px; }
            QCheckBox { spacing: 8px; padding: 4px; }
        ''')

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setFixedWidth(245)
        sidebar.setStyleSheet("background-color: #111214; border-right: 1px solid #2b2d31;")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(10, 14, 10, 14)
        sb_layout.setSpacing(6)

        title_lbl = QLabel("⚡ Share-L v1.2")
        title_lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #00a8fc; padding: 6px 4px;")
        sb_layout.addWidget(title_lbl)

        btn_quick_region = QPushButton("📸 Захват области (PrtSc)")
        btn_quick_region.setStyleSheet("background-color: #0078d7; border-color: #0098ff; padding: 10px;")
        btn_quick_region.clicked.connect(lambda: self.trigger_capture("region", 0))
        sb_layout.addWidget(btn_quick_region)

        btn_rec_mp4 = QPushButton("🎥 Запись видео (MP4)")
        btn_rec_mp4.setStyleSheet("background-color: #9e2a2b; border-color: #e05252;")
        btn_rec_mp4.clicked.connect(lambda: self.trigger_capture("record_mp4", 0))
        sb_layout.addWidget(btn_rec_mp4)

        btn_rec_gif = QPushButton("🎞 Запись анимации (GIF)")
        btn_rec_gif.clicked.connect(lambda: self.trigger_capture("record_gif", 0))
        sb_layout.addWidget(btn_rec_gif)

        btn_quick_full = QPushButton("🖥 Весь экран")
        btn_quick_full.clicked.connect(lambda: self.trigger_capture("fullscreen", 0))
        sb_layout.addWidget(btn_quick_full)

        sb_layout.addSpacing(6)

        self.nav_list = QListWidget()
        self.nav_list.setStyleSheet("border: none; background: transparent;")
        nav_items = [
            "📋 История (Снимки и Видео)",
            "☑ Задачи и Безопасность",
            "🎥 Запись экрана (MP4 / GIF)",
            "✨ Эффекты (Тень / Рамка)",
            "⚙ Настройки и Хостинги",
            "🛠 Инструменты Share-L",
            "⌨ Горячие клавиши"
        ]
        for ni in nav_items:
            self.nav_list.addItem(ni)
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self.switch_page)
        sb_layout.addWidget(self.nav_list, 1)

        btn_open_dir = QPushButton("📂 Открыть папку файлов")
        btn_open_dir.clicked.connect(self.open_screenshots_folder)
        sb_layout.addWidget(btn_open_dir)

        root_layout.addWidget(sidebar)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.build_history_page())
        self.pages.addWidget(self.build_after_capture_page())
        self.pages.addWidget(self.build_recorder_settings_page())
        self.pages.addWidget(self.build_effects_page())
        self.pages.addWidget(self.build_settings_page())
        self.pages.addWidget(self.build_tools_page())
        self.pages.addWidget(self.build_hotkeys_page())
        root_layout.addWidget(self.pages, 1)

        self.init_tray()
        self.load_history()
        self.init_global_hotkeys()
        self.ensure_gnome_hotkey_registered()

    def closeEvent(self, event):
        if not self.force_quit:
            event.ignore()
            self.hide()
        else:
            event.accept()

    def switch_page(self, idx):
        self.pages.setCurrentIndex(idx)
        if idx == 0:
            self.load_history()

    def build_history_page(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(72, 72))
        self.list_widget.currentItemChanged.connect(self.on_select_history)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_history_context_menu)
        splitter.addWidget(self.list_widget)

        right_panel = QWidget()
        rp_layout = QVBoxLayout(right_panel)
        rp_layout.setContentsMargins(8, 0, 0, 0)

        self.preview_lbl = QLabel("Сделайте первый скриншот или запись экрана")
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_lbl.setStyleSheet("background: #111214; border: 1px solid #2b2d31; border-radius: 6px;")
        rp_layout.addWidget(self.preview_lbl, 1)

        self.file_info_lbl = QLabel("")
        self.file_info_lbl.setStyleSheet("color: #949ba4; font-size: 12px; padding: 4px;")
        rp_layout.addWidget(self.file_info_lbl)

        act_bar = QHBoxLayout()
        btn_open = QPushButton("▶ Открыть файл")
        btn_open.clicked.connect(self.open_selected_file)
        btn_edit = QPushButton("✏ В редактор")
        btn_edit.clicked.connect(self.edit_selected)
        btn_cp = QPushButton("📋 Копировать")
        btn_cp.clicked.connect(self.copy_current)
        btn_up = QPushButton("☁ Загрузить (URL)")
        btn_up.clicked.connect(self.upload_current)
        btn_del = QPushButton("🗑 Удалить")
        btn_del.setStyleSheet("background-color: #a12828;")
        btn_del.clicked.connect(self.delete_current)

        for b in (btn_open, btn_edit, btn_cp, btn_up, btn_del):
            act_bar.addWidget(b)
        rp_layout.addLayout(act_bar)

        splitter.addWidget(right_panel)
        splitter.setSizes([310, 520])
        layout.addWidget(splitter)
        return page

    def build_after_capture_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)

        grp = QGroupBox("Задачи после захвата (After Capture Tasks)")
        vbox = QVBoxLayout(grp)

        tasks = [
            ("task_open_editor", "Открывать встроенный редактор аннотаций Share-L после выделения области"),
            ("task_add_effects", "Применять эффекты изображения (Тень / Обводка / Водяной знак)"),
            ("task_copy_image", "Копировать изображение в буфер обмена (Wayland / X11)"),
            ("task_save_file", "Сохранять изображение или видео в файл на диске"),
            ("task_pin_to_screen", "Автоматически закреплять скриншот поверх всех окон (Pin to Screen)"),
            ("task_run_ocr", "Автоматически распознавать текст (OCR RU/EN) и копировать в буфер"),
            ("task_scan_qr", "Автоматически сканировать QR-коды на скриншоте"),
            ("task_upload", "Автоматически загружать файл на выбранный хостинг / Telegram"),
            ("task_copy_url", "Копировать прямую ссылку в буфер обмена после загрузки"),
            ("task_show_notification", "Показывать системное всплывающее уведомление с превью")
        ]

        for key, text in tasks:
            cb = QCheckBox(text)
            cb.setChecked(bool(cfg.get(key)))
            cb.toggled.connect(lambda checked, k=key: cfg.set(k, checked))
            vbox.addWidget(cb)

        layout.addWidget(grp)

        grp_sec = QGroupBox("Защита и Приватность (Security Hardening II)")
        vbox_sec = QVBoxLayout(grp_sec)

        cb_exif = QCheckBox("Автоматически очищать EXIF, цветовые профили и метаданные из всех скриншотов")
        cb_exif.setChecked(bool(cfg.get("sec_strip_metadata")))
        cb_exif.toggled.connect(lambda v: cfg.set("sec_strip_metadata", v))
        vbox_sec.addWidget(cb_exif)

        cb_ssrf = QCheckBox("Включить защиту от SSRF (блокировать отправку на локальные и приватные IP)")
        cb_ssrf.setChecked(bool(cfg.get("sec_ssrf_protection")))
        cb_ssrf.toggled.connect(lambda v: cfg.set("sec_ssrf_protection", v))
        vbox_sec.addWidget(cb_ssrf)

        layout.addWidget(grp_sec)
        layout.addStretch(1)
        return page

    def build_recorder_settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)

        grp = QGroupBox("Движок записи экрана (Motion Engine: PipeWire / GNOME D-Bus / FFmpeg)")
        form = QFormLayout(grp)

        spin_vfps = QSpinBox()
        spin_vfps.setRange(10, 60)
        spin_vfps.setValue(int(cfg.get("video_fps") or 30))
        spin_vfps.valueChanged.connect(lambda v: cfg.set("video_fps", v))
        form.addRow("Частота кадров видео (MP4 FPS):", spin_vfps)

        spin_gfps = QSpinBox()
        spin_gfps.setRange(5, 30)
        spin_gfps.setValue(int(cfg.get("gif_fps") or 15))
        spin_gfps.valueChanged.connect(lambda v: cfg.set("gif_fps", v))
        form.addRow("Частота кадров анимации (GIF FPS):", spin_gfps)

        cb_aud = QCheckBox("Записывать звук с аудиовыхода / микрофона по умолчанию (PulseAudio / PipeWire)")
        cb_aud.setChecked(bool(cfg.get("record_audio")))
        cb_aud.toggled.connect(lambda v: cfg.set("record_audio", v))
        form.addRow("", cb_aud)

        layout.addWidget(grp)
        layout.addStretch(1)
        return page

    def build_effects_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)

        grp = QGroupBox("Пост-обработка скриншотов (Image Effects)")
        form = QFormLayout(grp)

        cb_en = QCheckBox("Включить автоматическое наложение эффектов")
        cb_en.setChecked(bool(cfg.get("task_add_effects")))
        cb_en.toggled.connect(lambda v: cfg.set("task_add_effects", v))
        form.addRow("", cb_en)

        cb_sh = QCheckBox("Добавлять мягкую тень (Drop Shadow) вокруг снимка")
        cb_sh.setChecked(bool(cfg.get("fx_shadow")))
        cb_sh.toggled.connect(lambda v: cfg.set("fx_shadow", v))
        form.addRow("", cb_sh)

        cb_br = QCheckBox("Добавлять цветную рамку вокруг снимка")
        cb_br.setChecked(bool(cfg.get("fx_border")))
        cb_br.toggled.connect(lambda v: cfg.set("fx_border", v))
        form.addRow("", cb_br)

        cb_wm = QCheckBox("Добавлять водяной знак (Watermark) в правом нижнем углу")
        cb_wm.setChecked(bool(cfg.get("fx_watermark")))
        cb_wm.toggled.connect(lambda v: cfg.set("fx_watermark", v))
        form.addRow("", cb_wm)

        wm_edit = QLineEdit(cfg.get("fx_watermark_text"))
        wm_edit.textChanged.connect(lambda v: cfg.set("fx_watermark_text", v))
        form.addRow("Текст водяного знака:", wm_edit)

        layout.addWidget(grp)
        layout.addStretch(1)
        return page

    def build_settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)

        grp_paths = QGroupBox("Папка сохранения и именование файлов")
        form_paths = QFormLayout(grp_paths)

        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(cfg.get("save_dir"))
        self.dir_edit.textChanged.connect(lambda val: cfg.set("save_dir", val))
        btn_browse = QPushButton("Обзор...")
        btn_browse.clicked.connect(self.choose_save_dir)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(btn_browse)
        form_paths.addRow("Папка для файлов:", dir_row)

        self.pattern_edit = QLineEdit(cfg.get("filename_pattern"))
        self.pattern_edit.textChanged.connect(lambda val: cfg.set("filename_pattern", val))
        form_paths.addRow("Шаблон имени файла:", self.pattern_edit)

        cb_sub = QCheckBox("Создавать подпапки по месяцам (ГГГГ-ММ)")
        cb_sub.setChecked(bool(cfg.get("use_month_subfolder")))
        cb_sub.toggled.connect(lambda val: cfg.set("use_month_subfolder", val))
        form_paths.addRow("", cb_sub)

        fmt_combo = QComboBox()
        fmt_combo.addItems(["png", "jpg", "webp"])
        fmt_combo.setCurrentText(cfg.get("image_format"))
        fmt_combo.currentTextChanged.connect(lambda val: cfg.set("image_format", val))
        form_paths.addRow("Формат скриншотов:", fmt_combo)

        layout.addWidget(grp_paths)

        grp_up = QGroupBox("Загрузчик и интеграция с Telegram (хранится с правами 0600)")
        form_up = QFormLayout(grp_up)
        up_combo = QComboBox()
        up_combo.addItems(["0x0.st", "x0.at", "catbox.moe", "telegram", "custom"])
        up_combo.setCurrentText(cfg.get("uploader"))
        up_combo.currentTextChanged.connect(lambda val: cfg.set("uploader", val))
        form_up.addRow("Куда выгружать (по клавише U):", up_combo)

        tg_tok = QLineEdit(cfg.get("tg_bot_token"))
        tg_tok.setEchoMode(QLineEdit.EchoMode.Password)
        tg_tok.setPlaceholderText("123456789:AAH...")
        tg_tok.textChanged.connect(lambda v: cfg.set("tg_bot_token", v))
        form_up.addRow("Telegram Bot Token:", tg_tok)

        tg_cid = QLineEdit(cfg.get("tg_chat_id"))
        tg_cid.setPlaceholderText("ID чата или канала (например, 123456789)")
        tg_cid.textChanged.connect(lambda v: cfg.set("tg_chat_id", v))
        form_up.addRow("Telegram Chat ID:", tg_cid)

        sxcu_url = QLineEdit(cfg.get("custom_sxcu_url"))
        sxcu_url.setPlaceholderText("https://your-domain.com/upload")
        sxcu_url.textChanged.connect(lambda v: cfg.set("custom_sxcu_url", v))
        form_up.addRow("Custom HTTPS Upload URL:", sxcu_url)

        layout.addWidget(grp_up)
        layout.addStretch(1)
        return page

    def build_tools_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)

        grp = QGroupBox("Встроенные инструменты Share-L")
        vbox = QVBoxLayout(grp)

        btn_picker = QPushButton("💧 Экранная пипетка (Скопировать HEX-цвет пикселя)")
        btn_picker.clicked.connect(lambda: self.trigger_capture("color_picker", 0))
        vbox.addWidget(btn_picker)

        btn_ruler = QPushButton("📏 Экранная линейка (Измерить размеры, площадь и диагональ)")
        btn_ruler.clicked.connect(lambda: self.trigger_capture("ruler", 0))
        vbox.addWidget(btn_ruler)

        btn_ocr_live = QPushButton("🔍 Распознать текст с экрана (OCR RU + EN)")
        btn_ocr_live.clicked.connect(lambda: self.trigger_capture("ocr", 0))
        vbox.addWidget(btn_ocr_live)

        btn_qr_scan = QPushButton("📷 Сканировать QR-код с экрана")
        btn_qr_scan.clicked.connect(lambda: self.trigger_capture("qr", 0))
        vbox.addWidget(btn_qr_scan)

        btn_qr_gen = QPushButton("🔳 Генератор QR-кодов из текста / ссылок")
        btn_qr_gen.clicked.connect(lambda: QRDialog(self).exec())
        vbox.addWidget(btn_qr_gen)

        btn_hash = QPushButton("🔐 Проверка хэш-сумм файлов (MD5 / SHA256)")
        btn_hash.clicked.connect(lambda: HashDialog(self).exec())
        vbox.addWidget(btn_hash)

        layout.addWidget(grp)
        layout.addStretch(1)
        return page

    def build_hotkeys_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)

        grp = QGroupBox("Глобальные горячие клавиши (Безопасное добавление без удаления чужих биндов)")
        vbox = QVBoxLayout(grp)

        info = QLabel(
            "Активные системные сочетания клавиш:\n\n"
            "• Print Screen — Захват области с лупой, редактором и кнопками записи MP4/GIF\n"
            "• Shift + Print — Мгновенный выбор области для записи Видео (MP4)\n"
            "• Alt + Print — Мгновенный выбор области для записи Анимации (GIF)\n"
            "• Ctrl + Shift + Print — Открыть главное окно Share-L"
        )
        vbox.addWidget(info)

        btn_bind = QPushButton("⚡ Обновить горячие клавиши Share-L (сохранив все существующие)")
        btn_bind.setStyleSheet("background-color: #238636; padding: 12px;")
        btn_bind.clicked.connect(lambda: self.bind_gnome_hotkey(silent=False))
        vbox.addWidget(btn_bind)

        layout.addWidget(grp)
        layout.addStretch(1)
        return page

    def ensure_gnome_hotkey_registered(self):
        self.bind_gnome_hotkey(silent=True)

    def bind_gnome_hotkey(self, silent=False):
        try:
            subprocess.run(
                ["gsettings", "set", "org.gnome.shell.keybindings", "show-screenshot-ui", "[]"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            schema = "org.gnome.settings-daemon.plugins.media-keys"
            base = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
            bindings = [
                (f"{base}/share-l-region/", "Share-L Region Capture", "/usr/local/bin/share-l --region", "Print"),
                (f"{base}/share-l-video/", "Share-L Video Record", "/usr/local/bin/share-l --video", "<Shift>Print"),
                (f"{base}/share-l-gif/", "Share-L GIF Record", "/usr/local/bin/share-l --gif", "<Alt>Print"),
                (f"{base}/share-l-gui/", "Share-L Dashboard", "/usr/local/bin/share-l", "<Ctrl><Shift>Print"),
            ]

            cur_raw = subprocess.check_output(
                ["gsettings", "get", schema, "custom-keybindings"], text=True
            ).strip()

            if cur_raw.startswith("@as"):
                cur_list = []
            else:
                try:
                    cur_list = list(ast.literal_eval(cur_raw))
                except Exception:
                    cur_list = []

            cur_list = [p for p in cur_list if "sharex" not in p]

            for path, _, _, _ in bindings:
                if path not in cur_list:
                    cur_list.append(path)

            subprocess.run(
                ["gsettings", "set", schema, "custom-keybindings", str(cur_list)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

            for path, name, cmd, key in bindings:
                s = f"{schema}.custom-keybinding:{path}"
                subprocess.run(["gsettings", "set", s, "name", name])
                subprocess.run(["gsettings", "set", s, "command", cmd])
                subprocess.run(["gsettings", "set", s, "binding", key])

            if not silent:
                notify("Share-L", "Горячие клавиши для скриншотов и записи MP4/GIF обновлены!")
        except Exception as e:
            if not silent:
                notify("Share-L", f"Ошибка привязки: {e}")

    def init_global_hotkeys(self):
        self.hk_bridge = HotkeyBridge(self)
        self.hk_bridge.trigger_region.connect(lambda: self.trigger_capture("region", 0))
        if not HAS_PYNPUT:
            return
        try:
            def on_press(key):
                try:
                    if key == pynput_kb.Key.print_screen:
                        self.hk_bridge.trigger_region.emit()
                except Exception:
                    pass

            self.kb_listener = pynput_kb.Listener(on_press=on_press)
            self.kb_listener.daemon = True
            self.kb_listener.start()
        except Exception:
            pass

    def init_tray(self):
        self.tray = QSystemTrayIcon(self)
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray.setIcon(icon)
        self.setWindowIcon(icon)

        menu = QMenu()
        act_reg = QAction("📸 Захват области (Print)", self)
        act_reg.triggered.connect(lambda: self.trigger_capture("region", 0))
        act_vid = QAction("🎥 Запись видео MP4 (Shift+Print)", self)
        act_vid.triggered.connect(lambda: self.trigger_capture("record_mp4", 0))
        act_gif = QAction("🎞 Запись анимации GIF (Alt+Print)", self)
        act_gif.triggered.connect(lambda: self.trigger_capture("record_gif", 0))
        act_full = QAction("🖥 Весь экран", self)
        act_full.triggered.connect(lambda: self.trigger_capture("fullscreen", 0))
        act_show = QAction("⚡ Открыть окно Share-L", self)
        act_show.triggered.connect(self.show_window)
        act_quit = QAction("❌ Полный выход", self)
        act_quit.triggered.connect(self.quit_app)

        for a in (act_reg, act_vid, act_gif, act_full):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(act_show)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        self.tray.show()

    def show_window(self):
        self.load_history()
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def quit_app(self):
        self.force_quit = True
        QApplication.quit()

    def choose_save_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения", cfg.get("save_dir"))
        if d:
            self.dir_edit.setText(d)
            cfg.set("save_dir", d)
            self.load_history()

    def open_screenshots_folder(self):
        d = cfg.get("save_dir")
        os.makedirs(d, exist_ok=True)
        subprocess.Popen(["xdg-open", d])

    def trigger_capture(self, mode="region", delay=0):
        if self.active_overlay and self.active_overlay.isVisible():
            return
        was_visible = self.isVisible()
        self.hide()
        QTimer.singleShot(250 + delay * 1000, lambda: self._do_capture(mode, was_visible))

    def _do_capture(self, mode, restore_window=False):
        tmp_file = get_secure_temp_file("raw_", "png")
        if not capture_full_screen(tmp_file):
            notify("Share-L Ошибка", "Не удалось получить снимок экрана.")
            if restore_window:
                self.show_window()
            return

        if mode == "fullscreen":
            ov = ShareLOverlay(tmp_file)
            ov.selection = ov.rect()
            ov.capture_completed.connect(lambda fp: self.on_capture_done(fp, restore_window))
            ov.execute_after_capture_tasks()
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass
            return

        self.active_overlay = ShareLOverlay(tmp_file, mode=mode)
        self.active_overlay.capture_completed.connect(lambda fp: self.on_capture_done(fp, restore_window))
        self.active_overlay.destroyed.connect(
            lambda: os.remove(tmp_file) if os.path.exists(tmp_file) else None
        )
        self.active_overlay.showFullScreen()
        self.active_overlay.activateWindow()

    def on_capture_done(self, filepath, restore_window=False):
        self.load_history()
        if restore_window:
            self.show_window()

    def load_history(self):
        self.list_widget.clear()
        save_dir = cfg.get("save_dir")
        pattern = os.path.join(save_dir, "**", "*.*")
        files = [
            f for f in glob.glob(pattern, recursive=True)
            if f.lower().endswith((".png", ".jpg", ".webp", ".mp4", ".gif"))
        ]
        files.sort(key=os.path.getmtime, reverse=True)
        vid_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        for fp in files[:100]:
            icon = vid_icon if fp.lower().endswith(".mp4") else QIcon(fp)
            item = QListWidgetItem(icon, os.path.basename(fp))
            item.setData(Qt.ItemDataRole.UserRole, fp)
            self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def current_file(self):
        it = self.list_widget.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def on_select_history(self, current, _):
        if self.current_movie:
            self.current_movie.stop()
            self.current_movie = None
        if not current:
            return
        fp = current.data(Qt.ItemDataRole.UserRole)
        if not os.path.exists(fp):
            return
        sz_kb = os.path.getsize(fp) // 1024
        if fp.lower().endswith(".mp4"):
            self.preview_lbl.setPixmap(QPixmap())
            self.preview_lbl.setText(f"🎥 Видеофайл MP4: {os.path.basename(fp)}\n\nНажмите «▶ Открыть файл» для воспроизведения")
            self.file_info_lbl.setText(f"Видео: {fp}  |  {sz_kb} КБ")
        elif fp.lower().endswith(".gif"):
            self.current_movie = QMovie(fp)
            self.preview_lbl.setMovie(self.current_movie)
            self.current_movie.start()
            self.file_info_lbl.setText(f"Анимация GIF: {fp}  |  {sz_kb} КБ")
        else:
            pix = QPixmap(fp)
            self.preview_lbl.setPixmap(pix.scaled(
                540, 450, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            ))
            self.file_info_lbl.setText(f"Файл: {fp}  |  {pix.width()}×{pix.height()} px  |  {sz_kb} КБ")

    def open_selected_file(self):
        fp = self.current_file()
        if fp and os.path.exists(fp):
            subprocess.Popen(["xdg-open", fp])

    def show_history_context_menu(self, pos):
        if not self.current_file():
            return
        menu = QMenu(self)
        menu.addAction("▶ Открыть в системном плеере/просмотрщике", self.open_selected_file)
        menu.addAction("📋 Копировать", self.copy_current)
        menu.addAction("✏ Открыть в редакторе Share-L", self.edit_selected)
        menu.addAction("🔍 Распознать текст (OCR)", self.ocr_current)
        menu.addAction("☁ Загрузить и скопировать ссылку", self.upload_current)
        menu.addSeparator()
        menu.addAction("📂 Показать в проводнике", lambda: subprocess.Popen(["xdg-open", os.path.dirname(self.current_file())]))
        menu.addAction("🗑 Удалить файл", self.delete_current)
        menu.exec(self.list_widget.mapToGlobal(pos))

    def edit_selected(self):
        fp = self.current_file()
        if fp and os.path.exists(fp) and fp.lower().endswith((".png", ".jpg", ".webp")):
            self.active_overlay = ShareLOverlay(fp)
            self.active_overlay.selection = self.active_overlay.rect()
            self.active_overlay.position_toolbar()
            self.active_overlay.capture_completed.connect(lambda f: self.load_history())
            self.active_overlay.showFullScreen()

    def copy_current(self):
        fp = self.current_file()
        if not fp:
            return
        if fp.lower().endswith((".png", ".jpg", ".webp")):
            copy_image_to_clipboard(fp)
            notify("Share-L", "Изображение скопировано в буфер обмена!", fp)
        else:
            copy_text_to_clipboard(fp)
            notify("Share-L", "Путь к видеофайлу скопирован в буфер обмена!")

    def ocr_current(self):
        fp = self.current_file()
        if fp and fp.lower().endswith((".png", ".jpg", ".webp")):
            txt = run_ocr(fp)
            if txt:
                copy_text_to_clipboard(txt)
                notify("Share-L OCR", f"Скопирован текст:\n{txt[:120]}", fp)
            else:
                notify("Share-L OCR", "Текст не найден", fp)

    def upload_current(self):
        fp = self.current_file()
        if fp:
            url = upload_file(fp, cfg.get("uploader"))
            if url:
                copy_text_to_clipboard(url)
                notify("Share-L Upload", f"Ссылка скопирована:\n{url}", fp)

    def delete_current(self):
        fp = self.current_file()
        if fp and os.path.exists(fp):
            os.remove(fp)
            self.load_history()
