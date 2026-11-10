import os
import sys
from .config import get_secure_temp_file

def drop_root_privileges_safely():
    if os.geteuid() != 0:
        return
    sudo_uid = os.environ.get("SUDO_UID")
    sudo_gid = os.environ.get("SUDO_GID")
    if sudo_uid and sudo_gid:
        uid = int(sudo_uid)
        gid = int(sudo_gid)
        runtime_dir = f"/run/user/{uid}"
        os.environ["XDG_RUNTIME_DIR"] = runtime_dir
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime_dir}/bus"
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)

def main():
    drop_root_privileges_safely()
    from .backends import capture_full_screen, notify

    for flag, mode in (("--region", "region"), ("--video", "record_mp4"), ("--gif", "record_gif")):
        if flag in sys.argv:
            tmp_file = get_secure_temp_file("raw_", "png")
            if not capture_full_screen(tmp_file):
                notify("Share-L", "Не удалось захватить экран.")
                sys.exit(1)
            os.environ["QT_QPA_PLATFORM"] = "xcb"
            from PyQt6.QtWidgets import QApplication
            from .overlay import ShareLOverlay
            app = QApplication(sys.argv)
            ov = ShareLOverlay(tmp_file, mode=mode)
            ov.destroyed.connect(lambda: os.remove(tmp_file) if os.path.exists(tmp_file) else None)
            ov.showFullScreen()
            ov.activateWindow()
            sys.exit(app.exec())

    os.environ["QT_QPA_PLATFORM"] = "xcb"
    from PyQt6.QtWidgets import QApplication
    from .dashboard import ShareLDashboard
    app = QApplication(sys.argv)
    win = ShareLDashboard()
    if "--daemon" in sys.argv:
        win.hide()
    else:
        win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
