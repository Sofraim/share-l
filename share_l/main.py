import os
import sys
import subprocess

def main():
    sudo_user = os.environ.get("SUDO_USER")
    sudo_uid = os.environ.get("SUDO_UID")
    if os.geteuid() == 0 and sudo_user and sudo_uid:
        runtime_dir = f"/run/user/{sudo_uid}"
        os.execvp("sudo", [
            "sudo", "-u", sudo_user, "env",
            f"XDG_RUNTIME_DIR={runtime_dir}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime_dir}/bus",
            "WAYLAND_DISPLAY=wayland-0",
            f"DISPLAY={os.environ.get('DISPLAY', ':0')}",
            f"PYTHONPATH={os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}",
            sys.executable, "-m", "share_l.main"
        ] + sys.argv[1:])

    from .backends import capture_full_screen, notify

    if "--region" in sys.argv:
        tmp_file = "/tmp/share_l_raw.png"
        if not capture_full_screen(tmp_file):
            notify("Share-L", "Не удалось захватить экран Wayland.")
            sys.exit(1)
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        from PyQt6.QtWidgets import QApplication
        from .overlay import ShareLOverlay
        app = QApplication(sys.argv)
        ov = ShareLOverlay(tmp_file)
        ov.showFullScreen()
        ov.activateWindow()
        sys.exit(app.exec())

    # Режим фонового демона глобальных хоткеев
    if "--daemon" in sys.argv:
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        from PyQt6.QtWidgets import QApplication
        from .dashboard import ShareLDashboard
        app = QApplication(sys.argv)
        win = ShareLDashboard()
        win.hide() # Прячем главное окно, оставляем трей и слушатель хоткеев
        sys.exit(app.exec())

    # По умолчанию — главное окно
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    from PyQt6.QtWidgets import QApplication
    from .dashboard import ShareLDashboard
    app = QApplication(sys.argv)
    win = ShareLDashboard()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
