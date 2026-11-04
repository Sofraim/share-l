import os
import json
import secrets
from pathlib import Path

def get_real_user_info():
    sudo_user = os.environ.get("SUDO_USER")
    sudo_uid = os.environ.get("SUDO_UID")
    if sudo_user and sudo_uid and os.geteuid() == 0:
        return Path(f"/home/{sudo_user}"), int(sudo_uid)
    return Path.home(), os.getuid()

USER_HOME, USER_UID = get_real_user_info()
CONFIG_DIR = USER_HOME / ".config" / "share-l"
CONFIG_PATH = CONFIG_DIR / "settings.json"
HISTORY_DB_PATH = CONFIG_DIR / "history.json"

def get_secure_runtime_dir() -> Path:
    base_runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{USER_UID}"
    if not os.path.exists(base_runtime):
        base_runtime = f"/tmp/share-l-{USER_UID}"
    sec_dir = Path(base_runtime) / "share-l"
    sec_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(sec_dir, 0o700)
    except Exception:
        pass
    return sec_dir

def get_secure_temp_file(prefix: str = "cap_", ext: str = "png") -> str:
    sec_dir = get_secure_runtime_dir()
    token = secrets.token_hex(8)
    return str(sec_dir / f"{prefix}{token}.{ext}")

def atomic_secure_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except Exception:
        pass
    tmp_path = path.with_suffix(".tmp")
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp_path, path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass

DEFAULT_SAVE_DIR = str(USER_HOME / "Pictures" / "Share-L")
if (USER_HOME / "Изображения").exists():
    DEFAULT_SAVE_DIR = str(USER_HOME / "Изображения" / "Share-L")

DEFAULT_CONFIG = {
    "save_dir": DEFAULT_SAVE_DIR,
    "filename_pattern": "ShareL_%Y-%m-%d_%H-%M-%S",
    "use_month_subfolder": True,
    "image_format": "png",
    "jpeg_quality": 95,
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
    "fx_border": False,
    "fx_border_color": "#00a8fc",
    "fx_border_size": 2,
    "fx_shadow": True,
    "fx_shadow_blur": 14,
    "fx_watermark": False,
    "fx_watermark_text": "Share-L",
    "show_magnifier": True,
    "magnifier_zoom": 8,
    "magnifier_size": 15,
    "show_crosshair": True,
    "smart_window_snap": True,
    "uploader": "0x0.st",
    "tg_bot_token": "",
    "tg_chat_id": "",
    "custom_sxcu_url": "",
    "custom_sxcu_field": "file"
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
                os.chmod(CONFIG_PATH, 0o600)
            except Exception:
                pass
        else:
            self.save()

    def save(self):
        atomic_secure_write(CONFIG_PATH, json.dumps(self.data, indent=4, ensure_ascii=False))

    def get(self, key):
        return self.data.get(key, DEFAULT_CONFIG.get(key))

    def set(self, key, val):
        self.data[key] = val
        self.save()

    def load_history(self):
        if HISTORY_DB_PATH.exists():
            try:
                self.history = json.loads(HISTORY_DB_PATH.read_text(encoding="utf-8"))
                os.chmod(HISTORY_DB_PATH, 0o600)
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
        atomic_secure_write(HISTORY_DB_PATH, json.dumps(self.history, indent=2, ensure_ascii=False))

cfg = ConfigManager()
