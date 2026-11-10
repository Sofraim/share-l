import os
import sys
import time
import signal
import shutil
import subprocess
from datetime import datetime
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import Qt, QTimer, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from .config import cfg, get_secure_temp_file
from .backends import get_wayland_env, notify, upload_file, copy_text_to_clipboard

GNOME_DBUS_HELPER = """
import sys, signal
from gi.repository import Gio, GLib

x, y, w, h, fps, out_tmpl = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), sys.argv[6]
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
proxy = Gio.DBusProxy.new_sync(
    bus, Gio.DBusProxyFlags.NONE, None,
    'org.gnome.Shell.Screencast', '/org/gnome/Shell/Screencast', 'org.gnome.Shell.Screencast', None
)
opts = {'draw-cursor': GLib.Variant('b', True), 'framerate': GLib.Variant('i', fps)}
res = proxy.call_sync('ScreencastArea', GLib.Variant('(iiiisa{sv})', (x, y, w, h, out_tmpl, opts)), Gio.DBusCallFlags.NONE, -1, None)
ok, fname = res.unpack()
if not ok:
    sys.exit(1)
print(fname, flush=True)
loop = GLib.MainLoop()
def stop_handler(*args):
    try:
        proxy.call_sync('StopScreencast', None, Gio.DBusCallFlags.NONE, -1, None)
    except Exception:
        pass
    loop.quit()
signal.signal(signal.SIGTERM, stop_handler)
signal.signal(signal.SIGINT, stop_handler)
loop.run()
"""

class RecordingBorderOverlay(QWidget):
    def __init__(self, target_rect: QRect):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(target_rect.adjusted(-3, -3, 3, 3))

    def paintEvent(self, event):
        p = QPainter(self)
        pen = QPen(QColor(255, 55, 55, 230), 2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(1, 1, self.width() - 2, self.height() - 2)


class RecordControlBar(QWidget):
    recording_finished = pyqtSignal(str)

    def __init__(self, rect: QRect, fmt: str = "mp4"):
        super().__init__()
        self.capture_rect = rect
        self.fmt = fmt.lower()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setStyleSheet('''
            QWidget { background: #141517; border: 1px solid #ff4444; border-radius: 8px; }
            QLabel { color: #ffffff; font-family: Monospace; font-size: 13px; font-weight: bold; border: none; padding: 0 6px; }
            QPushButton {
                background: #2b2d31; color: #f0f0f0; border: 1px solid #3f4147;
                padding: 5px 10px; border-radius: 5px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: #383a40; border-color: #00a8fc; }
        ''')

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        badge = "🎞 GIF" if self.fmt == "gif" else "🎥 MP4"
        self.timer_lbl = QLabel(f"🔴 {badge} 00:00")
        layout.addWidget(self.timer_lbl)

        self.btn_stop = QPushButton("⏹ Стоп и сохранить")
        self.btn_stop.setStyleSheet("background: #d93838; color: white; border-color: #ff5555;")
        self.btn_stop.clicked.connect(self.stop_recording)
        layout.addWidget(self.btn_stop)

        self.btn_cancel = QPushButton("✖")
        self.btn_cancel.setToolTip("Отменить запись")
        self.btn_cancel.clicked.connect(self.cancel_recording)
        layout.addWidget(self.btn_cancel)

        self.adjustSize()
        bx = max(10, rect.left())
        by = rect.bottom() + 10
        if by + self.height() > 1040:
            by = max(10, rect.top() - self.height() - 10)
        self.move(bx, by)

        self.border_win = RecordingBorderOverlay(rect)
        self.border_win.show()

        self.proc = None
        self.audio_proc = None
        self.backend_type = None
        self.raw_video_path = ""
        self.raw_audio_path = ""
        self.start_time = time.time()
        self.drag_pos = QPoint()

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self.update_timer_ui)

        QTimer.singleShot(200, self.start_backend)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)

    def update_timer_ui(self):
        elapsed = int(time.time() - self.start_time)
        mins, secs = divmod(elapsed, 60)
        badge = "🎞 GIF" if self.fmt == "gif" else "🎥 MP4"
        self.timer_lbl.setText(f"🔴 {badge} {mins:02d}:{secs:02d}")

    def start_backend(self):
        x = max(0, self.capture_rect.x() & ~1)
        y = max(0, self.capture_rect.y() & ~1)
        w = max(16, self.capture_rect.width() & ~1)
        h = max(16, self.capture_rect.height() & ~1)
        fps = int(cfg.get("gif_fps") or 15) if self.fmt == "gif" else int(cfg.get("video_fps") or 30)
        env = get_wayland_env()

        # 1. Пробуем нативный GNOME Wayland Screencast D-Bus (без черного экрана)
        if "WAYLAND_DISPLAY" in env:
            tmp_webm = get_secure_temp_file("rec_gnome_", "webm")
            try:
                p = subprocess.Popen(
                    ["python3", "-c", GNOME_DBUS_HELPER, str(x), str(y), str(w), str(h), str(fps), tmp_webm],
                    env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
                )
                line = p.stdout.readline().strip()
                if line and p.poll() is None:
                    self.proc = p
                    self.backend_type = "gnome_dbus"
                    self.raw_video_path = line
                    self.start_optional_audio(env)
                    self.start_time = time.time()
                    self.ui_timer.start(500)
                    return
            except Exception:
                pass

        # 2. Пробуем wf-recorder (для Hyprland / Sway)
        if "WAYLAND_DISPLAY" in env and shutil.which("wf-recorder"):
            tmp_mp4 = get_secure_temp_file("rec_wf_", "mp4")
            cmd = ["wf-recorder", "-g", f"{x},{y} {w}x{h}", "-r", str(fps), "-f", tmp_mp4]
            if cfg.get("record_audio") and self.fmt == "mp4":
                cmd.append("-a")
            self.proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.backend_type = "wf"
            self.raw_video_path = tmp_mp4
            self.start_time = time.time()
            self.ui_timer.start(500)
            return

        # 3. Универсальный FFmpeg x11grab (X11 / Xwayland)
        if shutil.which("ffmpeg"):
            tmp_mp4 = get_secure_temp_file("rec_x11_", "mp4")
            display = env.get("DISPLAY", ":0")
            cmd = [
                "ffmpeg", "-y", "-f", "x11grab",
                "-video_size", f"{w}x{h}",
                "-framerate", str(fps),
                "-i", f"{display}+{x},{y}",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                tmp_mp4
            ]
            self.proc = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.backend_type = "ffmpeg"
            self.raw_video_path = tmp_mp4
            self.start_optional_audio(env)
            self.start_time = time.time()
            self.ui_timer.start(500)
            return

        notify("Share-L Запись", "Не найден движок записи (установите ffmpeg)!")
        self.cancel_recording()

    def start_optional_audio(self, env):
        if self.fmt != "mp4" or not cfg.get("record_audio") or not shutil.which("ffmpeg"):
            return
        try:
            self.raw_audio_path = get_secure_temp_file("rec_aud_", "aac")
            self.audio_proc = subprocess.Popen(
                ["ffmpeg", "-y", "-f", "pulse", "-i", "default", "-c:a", "aac", self.raw_audio_path],
                env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            self.raw_audio_path = ""

    def build_final_path(self) -> str:
        base_dir = cfg.get("save_dir")
        if cfg.get("use_month_subfolder"):
            base_dir = os.path.join(base_dir, datetime.now().strftime("%Y-%m"))
        os.makedirs(base_dir, exist_ok=True)
        pattern = cfg.get("filename_pattern") or "ShareL_%Y-%m-%d_%H-%M-%S"
        fname = datetime.now().strftime(pattern) + f".{self.fmt}"
        return os.path.join(base_dir, fname)

    def stop_recording(self):
        self.ui_timer.stop()
        self.btn_stop.setEnabled(False)
        self.timer_lbl.setText("⏳ Обработка...")
        self.border_win.close()
        self.hide()

        if self.proc and self.proc.poll() is None:
            try:
                self.proc.send_signal(signal.SIGTERM)
                self.proc.wait(timeout=6)
            except Exception:
                self.proc.kill()

        if self.audio_proc and self.audio_proc.poll() is None:
            try:
                self.audio_proc.send_signal(signal.SIGINT)
                self.audio_proc.wait(timeout=4)
            except Exception:
                self.audio_proc.kill()

        time.sleep(0.3)
        final_path = self.build_final_path()

        if not os.path.exists(self.raw_video_path) or os.path.getsize(self.raw_video_path) < 200:
            notify("Share-L Ошибка", "Видеофайл пуст или запись прервана.")
            self.cleanup_temp()
            self.close()
            return

        if self.fmt == "gif":
            fps = int(cfg.get("gif_fps") or 15)
            vf = f"fps={fps},scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
            subprocess.run(
                ["ffmpeg", "-y", "-i", self.raw_video_path, "-vf", vf, "-loop", "0", final_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90
            )
        else:
            if self.raw_audio_path and os.path.exists(self.raw_audio_path) and os.path.getsize(self.raw_audio_path) > 200:
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-i", self.raw_video_path, "-i", self.raw_audio_path,
                        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", final_path
                    ],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90
                )
            elif self.raw_video_path.endswith(".webm"):
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-i", self.raw_video_path,
                        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
                        final_path
                    ],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90
                )
            else:
                shutil.move(self.raw_video_path, final_path)

        self.cleanup_temp()

        if os.path.exists(final_path):
            url = ""
            if cfg.get("task_upload"):
                url = upload_file(final_path, cfg.get("uploader"))
                if url and cfg.get("task_copy_url"):
                    copy_text_to_clipboard(url)
                    notify("Share-L Upload", f"Запись выгружена:\n{url}")
            else:
                copy_text_to_clipboard(final_path)
                notify("Share-L Запись готова", f"Сохранено: {os.path.basename(final_path)}\n(Путь скопирован в буфер)")
            cfg.add_history_entry(final_path, url=url)
            self.recording_finished.emit(final_path)

        self.close()

    def cancel_recording(self):
        self.ui_timer.stop()
        self.border_win.close()
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        if self.audio_proc and self.audio_proc.poll() is None:
            self.audio_proc.kill()
        self.cleanup_temp()
        self.close()

    def cleanup_temp(self):
        for p in (self.raw_video_path, self.raw_audio_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
