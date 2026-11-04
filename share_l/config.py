import os
import json
from pathlib import Path

def get_real_user_home() -> Path:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and os.geteuid() == 0:
        return Path(f"/home/{sudo_user}")
    return Path.home()

USER_HOME = get_real_user_home()
CONFIG_PATH = USER_HOME / ".config" / "share-l" / "settings.json"
HISTORY_DB_PATH = USER_HOME / ".config" / "share-l" / "history.json"

DEFAULT_SAVE_DIR = str(USER_HOME / "Pictures" / "Share-L")
if (USER_HOME / "Изображения").exists():
    DEFAULT_SAVE_DIR = str(USER_HOME / "Изображения" / "Share-L")

DEFAULT_CONFIG = {
    "save_dir": DEFAULT_SAVE_DIR,
    "filename_pattern": "ShareL_%Y-%m-%d_%H-%M-%S",
    "use_month_subfolder": True,
    "image_format": "png",
    "jpeg_quality": 95,
    # After Capture Tasks (Задачи после захвата)
    "task_open_editor": True,
    "task_add_effects": False,
    "task_copy_image": True,
    "task_save_file": True,
    "task_pin_to_screen": False,
    "task_run_ocr": False,
    "task_scan_qr": False,
    "task_upload": False,
    "task_copy_url": True,
    "task_show_notification": True,
    # Эффекты изображения (Image Effects)
    "fx_border": False,
    "fx_border_color": "#00a8fc",
    "fx_border_size": 2,
    "fx_shadow": True,
    "fx_shadow_blur": 14,
    "fx_watermark": False,
    "fx_watermark_text": "Share-L Linux",
    # Прицел и Лупа
    "show_magnifier": True,
    "magnifier_zoom": 8,
    "magnifier_size": 15,
    "show_crosshair": True,
    "smart_window_snap": True,
    # Хостинг и запись экрана
    "uploader": "0x0.st",
    "custom_uploader_url": "",
    "record_fps": 30,
    "record_format": "mp4"
}

class ConfigManager:
    def __init__(self):
        self.data = DEFAULT_CONFIG.copy()
        self.history = []
        self.load()
        self.load_history()

    def load(self):
        if CONFIG_PATH.exists():
            try:
                loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                self.data.update(loaded)
            except Exception:
                pass
        else:
            self.save()

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(self.data, indent=4, ensure_ascii=False), encoding="utf-8")

    def get(self, key):
        return self.data.get(key, DEFAULT_CONFIG.get(key))

    def set(self, key, val):
        self.data[key] = val
        self.save()

    def load_history(self):
        if HISTORY_DB_PATH.exists():
            try:
                self.history = json.loads(HISTORY_DB_PATH.read_text(encoding="utf-8"))
            except Exception:
                self.history = []

    def add_history_entry(self, filepath: str, url: str = "", ocr_text: str = ""):
        entry = {
            "filepath": filepath,
            "filename": os.path.basename(filepath),
            "url": url,
            "ocr": ocr_text,
            "timestamp": os.path.getmtime(filepath) if os.path.exists(filepath) else 0
        }
        self.history = [h for h in self.history if h.get("filepath") != filepath]
        self.history.insert(0, entry)
        self.history = self.history[:200]
        HISTORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_DB_PATH.write_text(json.dumps(self.history, indent=2, ensure_ascii=False), encoding="utf-8")

cfg = ConfigManager()
