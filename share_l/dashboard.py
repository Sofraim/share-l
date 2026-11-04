import os
import glob
import subprocess
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QListWidget, QListWidgetItem, QLabel, QPushButton,
    QCheckBox, QLineEdit, QFileDialog, QComboBox, QSpinBox, QGroupBox,
    QFormLayout, QSystemTrayIcon, QMenu, QStyle, QSplitter
)
from PyQt6.QtCore import Qt, QSize, QTimer, QObject, pyqtSignal
from PyQt6.QtGui import QPixmap, QIcon, QAction
from .config import cfg
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
    trigger_fullscreen = pyqtSignal()
    trigger_ocr = pyqtSignal()


class ShareLDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Share-L")
        self.resize(1060, 660)
        self.active_overlay = None
        self.force_quit = False

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
        sidebar.setFixedWidth(240)
        sidebar.setStyleSheet("background-color: #111214; border-right: 1px solid #2b2d31;")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(10, 14, 10, 14)
        sb_layout.setSpacing(6)

        title_lbl = QLabel("⚡ Share-L")
        title_lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #00a8fc; padding: 6px 4px;")
        sb_layout.addWidget(title_lbl)

        btn_quick_region = QPushButton("📸 Захват области (PrtSc)")
        btn_quick_region.setStyleSheet("background-color: #0078d7; border-color: #0098ff; padding: 10px;")
        btn_quick_region.clicked.connect(lambda: self.trigger_capture("region", 0))
        sb_layout.addWidget(btn_quick_region)

        btn_quick_full = QPushButton("🖥 Весь экран")
        btn_quick_full.clicked.connect(lambda: self.trigger_capture("fullscreen", 0))
        sb_layout.addWidget(btn_quick_full)

        btn_quick_delay = QPushButton("⏱ С задержкой (3 сек)")
        btn_quick_delay.clicked.connect(lambda: self.trigger_capture("region", 3))
        sb_layout.addWidget(btn_quick_delay)

        sb_layout.addSpacing(8)

        self.nav_list = QListWidget()
        self.nav_list.setStyleSheet("border: none; background: transparent;")
        nav_items = [
            "📋 История снимков",
            "☑ Задачи после захвата",
            "✨ Эффекты (Тень / Рамка)",
            "⚙ Настройки и папки",
            "🛠 Инструменты Share-L",
            "⌨ Горячие клавиши GNOME"
        ]
        for ni in nav_items:
            self.nav_list.addItem(ni)
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self.switch_page)
        sb_layout.addWidget(self.nav_list, 1)

        btn_open_dir = QPushButton("📂 Открыть папку скринов")
        btn_open_dir.clicked.connect(self.open_screenshots_folder)
        sb_layout.addWidget(btn_open_dir)

        root_layout.addWidget(sidebar)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.build_history_page())
        self.pages.addWidget(self.build_after_capture_page())
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

        self.preview_lbl = QLabel("Сделайте первый скриншот или выберите из списка")
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_lbl.setStyleSheet("background: #111214; border: 1px solid #2b2d31; border-radius: 6px;")
        rp_layout.addWidget(self.preview_lbl, 1)

        self.file_info_lbl = QLabel("")
        self.file_info_lbl.setStyleSheet("color: #949ba4; font-size: 12px; padding: 4px;")
        rp_layout.addWidget(self.file_info_lbl)

        act_bar = QHBoxLayout()
        btn_edit = QPushButton("✏ В редактор")
        btn_edit.clicked.connect(self.edit_selected)
        btn_cp = QPushButton("📋 Копировать")
        btn_cp.clicked.connect(self.copy_current)
        btn_ocr = QPushButton("🔍 OCR текст")
        btn_ocr.clicked.connect(self.ocr_current)
        btn_up = QPushButton("☁ Загрузить (URL)")
        btn_up.clicked.connect(self.upload_current)
        btn_del = QPushButton("🗑 Удалить")
        btn_del.setStyleSheet("background-color: #a12828;")
        btn_del.clicked.connect(self.delete_current)

        for b in (btn_edit, btn_cp, btn_ocr, btn_up, btn_del):
            act_bar.addWidget(b)
        rp_layout.addLayout(act_bar)

        splitter.addWidget(right_panel)
        splitter.setSizes([300, 500])
        layout.addWidget(splitter)
        return page

    def build_after_capture_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)

        grp = QGroupBox("Задачи после захвата (After Capture Tasks — работают автоматически)")
        vbox = QVBoxLayout(grp)

        tasks = [
            ("task_open_editor", "Открывать встроенный редактор аннотаций Share-L после выделения области"),
            ("task_add_effects", "Применять эффекты изображения (Тень / Обводка / Водяной знак)"),
            ("task_copy_image", "Копировать изображение в буфер обмена (Wayland / X11)"),
            ("task_save_file", "Сохранять изображение в файл на диске"),
            ("task_pin_to_screen", "Автоматически закреплять скриншот поверх всех окон (Pin to Screen)"),
            ("task_run_ocr", "Автоматически распознавать текст (OCR RU/EN) и копировать в буфер"),
            ("task_scan_qr", "Автоматически сканировать QR-коды на скриншоте"),
            ("task_upload", "Автоматически загружать скриншот на файл-хостинг"),
            ("task_copy_url", "Копировать прямую ссылку в буфер обмена после загрузки"),
            ("task_show_notification", "Показывать системное всплывающее уведомление с превью")
        ]

        for key, text in tasks:
            cb = QCheckBox(text)
            cb.setChecked(bool(cfg.get(key)))
            cb.toggled.connect(lambda checked, k=key: cfg.set(k, checked))
            vbox.addWidget(cb)

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
        form_paths.addRow("Папка для скриншотов:", dir_row)

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
        form_paths.addRow("Формат изображения:", fmt_combo)

        layout.addWidget(grp_paths)

        grp_mag = QGroupBox("Настройки прицела, лупы и автоопределения окон")
        form_mag = QFormLayout(grp_mag)

        cb_mag = QCheckBox("Показывать пиксельную лупу возле курсора")
        cb_mag.setChecked(bool(cfg.get("show_magnifier")))
        cb_mag.toggled.connect(lambda val: cfg.set("show_magnifier", val))
        form_mag.addRow("", cb_mag)

        cb_cross = QCheckBox("Показывать перекрестие на весь экран")
        cb_cross.setChecked(bool(cfg.get("show_crosshair")))
        cb_cross.toggled.connect(lambda val: cfg.set("show_crosshair", val))
        form_mag.addRow("", cb_cross)

        cb_snap = QCheckBox("Автоматически подсвечивать границы окон под курсором")
        cb_snap.setChecked(bool(cfg.get("smart_window_snap")))
        cb_snap.toggled.connect(lambda val: cfg.set("smart_window_snap", val))
        form_mag.addRow("", cb_snap)

        spin_zoom = QSpinBox()
        spin_zoom.setRange(4, 16)
        spin_zoom.setValue(int(cfg.get("magnifier_zoom")))
        spin_zoom.valueChanged.connect(lambda val: cfg.set("magnifier_zoom", val))
        form_mag.addRow("Кратность увеличения лупы:", spin_zoom)

        layout.addWidget(grp_mag)

        grp_up = QGroupBox("Загрузчик изображений (Destinations)")
        form_up = QFormLayout(grp_up)
        up_combo = QComboBox()
        up_combo.addItems(["0x0.st", "x0.at", "catbox.moe"])
        up_combo.setCurrentText(cfg.get("uploader"))
        up_combo.currentTextChanged.connect(lambda val: cfg.set("uploader", val))
        form_up.addRow("Сервер загрузки:", up_combo)
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

        grp = QGroupBox("Глобальные горячие клавиши (GNOME Wayland + X11)")
        vbox = QVBoxLayout(grp)

        info = QLabel(
            "Активные системные сочетания клавиш:\n\n"
            "• Print Screen — Захват области с лупой и редактором Share-L\n"
            "• Ctrl + Shift + Print — Открыть главное окно Share-L\n\n"
            "Внутри режима выделения области:\n"
            "• Enter / Двойной клик — Сохранить и скопировать в буфер\n"
            "• C — Скопировать HEX-цвет пикселя под лупой\n"
            "• P — Закрепить область поверх всех окон (Pin to Screen)\n"
            "• O — Распознать текст (OCR) в буфер обмена\n"
            "• U — Загрузить на хостинг и скопировать прямую ссылку"
        )
        vbox.addWidget(info)

        btn_bind = QPushButton("⚡ Перепрописать горячие клавиши в GNOME Wayland")
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
            p1 = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/sharex-region/"
            p2 = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/sharex-gui/"
            subprocess.run([
                "gsettings", "set", "org.gnome.settings-daemon.plugins.media-keys",
                "custom-keybindings", f"['{p1}', '{p2}']"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            s1 = f"org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{p1}"
            subprocess.run(["gsettings", "set", s1, "name", "Share-L Region Capture"])
            subprocess.run(["gsettings", "set", s1, "command", "/usr/local/bin/share-l --region"])
            subprocess.run(["gsettings", "set", s1, "binding", "Print"])

            s2 = f"org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{p2}"
            subprocess.run(["gsettings", "set", s2, "name", "Share-L Dashboard"])
            subprocess.run(["gsettings", "set", s2, "command", "/usr/local/bin/share-l"])
            subprocess.run(["gsettings", "set", s2, "binding", "<Ctrl><Shift>Print"])

            if not silent:
                notify("Share-L", "Горячие клавиши Print Screen и Ctrl+Shift+Print успешно привязаны!")
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
        act_full = QAction("🖥 Весь экран", self)
        act_full.triggered.connect(lambda: self.trigger_capture("fullscreen", 0))
        act_ocr = QAction("🔍 OCR Распознать текст", self)
        act_ocr.triggered.connect(lambda: self.trigger_capture("ocr", 0))
        act_show = QAction("⚡ Открыть окно Share-L", self)
        act_show.triggered.connect(self.show_window)
        act_quit = QAction("❌ Полный выход", self)
        act_quit.triggered.connect(self.quit_app)

        for a in (act_reg, act_full, act_ocr):
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
        d = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения скриншотов", cfg.get("save_dir"))
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
        tmp_file = "/tmp/share_l_raw.png"
        if not capture_full_screen(tmp_file):
            notify("Share-L Ошибка", "Не удалось получить снимок экрана Wayland.")
            if restore_window:
                self.show_window()
            return

        if mode == "fullscreen":
            ov = ShareLOverlay(tmp_file)
            ov.selection = ov.rect()
            ov.capture_completed.connect(lambda fp: self.on_capture_done(fp, restore_window))
            ov.execute_after_capture_tasks()
            return

        self.active_overlay = ShareLOverlay(tmp_file, mode=mode)
        self.active_overlay.capture_completed.connect(lambda fp: self.on_capture_done(fp, restore_window))
        if restore_window:
            self.active_overlay.destroyed.connect(self.show_window)
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
            if f.lower().endswith((".png", ".jpg", ".webp"))
        ]
        files.sort(key=os.path.getmtime, reverse=True)
        for fp in files[:100]:
            item = QListWidgetItem(QIcon(fp), os.path.basename(fp))
            item.setData(Qt.ItemDataRole.UserRole, fp)
            self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def current_file(self):
        it = self.list_widget.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def on_select_history(self, current, _):
        if not current:
            return
        fp = current.data(Qt.ItemDataRole.UserRole)
        if not os.path.exists(fp):
            return
        pix = QPixmap(fp)
        self.preview_lbl.setPixmap(pix.scaled(
            540, 450, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        sz_kb = os.path.getsize(fp) // 1024
        self.file_info_lbl.setText(f"Файл: {fp}  |  {pix.width()}×{pix.height()} px  |  {sz_kb} КБ")

    def show_history_context_menu(self, pos):
        if not self.current_file():
            return
        menu = QMenu(self)
        menu.addAction("📋 Копировать картинку", self.copy_current)
        menu.addAction("✏ Открыть в редакторе Share-L", self.edit_selected)
        menu.addAction("🔍 Распознать текст (OCR)", self.ocr_current)
        menu.addAction("📷 Декодировать QR-код", self.qr_current)
        menu.addAction("☁ Загрузить и скопировать ссылку", self.upload_current)
        menu.addSeparator()
        menu.addAction("📂 Показать в проводнике", lambda: subprocess.Popen(["xdg-open", os.path.dirname(self.current_file())]))
        menu.addAction("🗑 Удалить файл", self.delete_current)
        menu.exec(self.list_widget.mapToGlobal(pos))

    def edit_selected(self):
        fp = self.current_file()
        if fp and os.path.exists(fp):
            self.active_overlay = ShareLOverlay(fp)
            self.active_overlay.selection = self.active_overlay.rect()
            self.active_overlay.position_toolbar()
            self.active_overlay.capture_completed.connect(lambda f: self.load_history())
            self.active_overlay.showFullScreen()

    def copy_current(self):
        fp = self.current_file()
        if fp:
            copy_image_to_clipboard(fp)
            notify("Share-L", "Изображение скопировано в буфер обмена!", fp)

    def ocr_current(self):
        fp = self.current_file()
        if fp:
            txt = run_ocr(fp)
            if txt:
                copy_text_to_clipboard(txt)
                notify("Share-L OCR", f"Скопирован текст:\n{txt[:120]}", fp)
            else:
                notify("Share-L OCR", "Текст не найден", fp)

    def qr_current(self):
        fp = self.current_file()
        if fp:
            txt = decode_qr(fp)
            if txt:
                copy_text_to_clipboard(txt)
                notify("Share-L QR", f"Декодировано:\n{txt}", fp)
            else:
                notify("Share-L QR", "QR-код не найден", fp)

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
