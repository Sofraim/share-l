import os
import shutil
import subprocess
from .config import get_real_user_home

def get_wayland_env():
    env = os.environ.copy()
    env.pop("QT_QPA_PLATFORM", None)
    env["GDK_BACKEND"] = "wayland,x11"

    uid = os.getuid()
    sudo_uid = os.environ.get("SUDO_UID")
    if uid == 0 and sudo_uid:
        uid = int(sudo_uid)

    runtime_dir = f"/run/user/{uid}"
    env["XDG_RUNTIME_DIR"] = runtime_dir
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime_dir}/bus"

    for sock in ("wayland-0", "wayland-1"):
        if os.path.exists(os.path.join(runtime_dir, sock)):
            env["WAYLAND_DISPLAY"] = sock
            break

    if "DISPLAY" not in env:
        env["DISPLAY"] = ":0"
    return env

def run_as_user_cmd(cmd: list):
    sudo_user = os.environ.get("SUDO_USER")
    if os.geteuid() == 0 and sudo_user:
        env = get_wayland_env()
        env_args = [
            f"XDG_RUNTIME_DIR={env['XDG_RUNTIME_DIR']}",
            f"DBUS_SESSION_BUS_ADDRESS={env['DBUS_SESSION_BUS_ADDRESS']}",
            f"WAYLAND_DISPLAY={env.get('WAYLAND_DISPLAY', 'wayland-0')}",
            f"DISPLAY={env.get('DISPLAY', ':0')}"
        ]
        return ["sudo", "-u", sudo_user, "env"] + env_args + cmd
    return cmd

def capture_full_screen(tmp_path: str, delay_sec: int = 0) -> bool:
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    env = get_wayland_env()

    # 1. Нативный gnome-screenshot в чистом Wayland-окружении пользователя
    if shutil.which("gnome-screenshot"):
        cmd = ["gnome-screenshot", "-f", tmp_path]
        if delay_sec > 0:
            cmd.extend(["-d", str(delay_sec)])
        res = subprocess.run(run_as_user_cmd(cmd), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 1000:
            return True

    # 2. grim (для wlroots композиторов)
    if shutil.which("grim"):
        res = subprocess.run(run_as_user_cmd(["grim", tmp_path]), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0 and os.path.exists(tmp_path):
            return True

    # 3. Spectacle (для KDE)
    if shutil.which("spectacle"):
        res = subprocess.run(run_as_user_cmd(["spectacle", "-b", "-n", "-f", "-o", tmp_path]), env=env)
        if res.returncode == 0 and os.path.exists(tmp_path):
            return True

    return False

def get_visible_windows_rects() -> list:
    rects = []
    if not shutil.which("xdotool"):
        return rects
    try:
        out = subprocess.check_output(["xdotool", "search", "--onlyvisible", "."], stderr=subprocess.DEVNULL, text=True)
        for wid in out.strip().splitlines()[:30]:
            geo = subprocess.check_output(["xdotool", "getwindowgeometry", "--shell", wid], stderr=subprocess.DEVNULL, text=True)
            vals = {}
            for line in geo.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    vals[k] = int(v)
            if vals.get("WIDTH", 0) > 40 and vals.get("HEIGHT", 0) > 40:
                rects.append((vals["X"], vals["Y"], vals["WIDTH"], vals["HEIGHT"]))
    except Exception:
        pass
    return rects

def copy_image_to_clipboard(image_path: str):
    env = get_wayland_env()
    if shutil.which("wl-copy") and "WAYLAND_DISPLAY" in env:
        with open(image_path, "rb") as f:
            subprocess.Popen(run_as_user_cmd(["wl-copy", "--type", "image/png"]), stdin=f, env=env)
    elif shutil.which("xclip"):
        subprocess.Popen(run_as_user_cmd(["xclip", "-selection", "clipboard", "-t", "image/png", "-i", image_path]), env=env)

def copy_text_to_clipboard(text: str):
    env = get_wayland_env()
    if shutil.which("wl-copy") and "WAYLAND_DISPLAY" in env:
        p = subprocess.Popen(run_as_user_cmd(["wl-copy"]), stdin=subprocess.PIPE, env=env)
        p.communicate(input=text.encode("utf-8"))
    elif shutil.which("xclip"):
        p = subprocess.Popen(run_as_user_cmd(["xclip", "-selection", "clipboard"]), stdin=subprocess.PIPE, env=env)
        p.communicate(input=text.encode("utf-8"))

def notify(title: str, body: str, icon_path: str = ""):
    if shutil.which("notify-send"):
        cmd = ["notify-send", "-a", "Share-L", title, body]
        if icon_path and os.path.exists(icon_path):
            cmd.extend(["-i", icon_path])
        subprocess.Popen(run_as_user_cmd(cmd), env=get_wayland_env())

def run_ocr(image_path: str) -> str:
    if not shutil.which("tesseract"):
        return ""
    res = subprocess.run(
        ["tesseract", image_path, "stdout", "-l", "rus+eng"],
        capture_output=True, text=True
    )
    return res.stdout.strip()

def decode_qr(image_path: str) -> str:
    if not shutil.which("zbarimg"):
        return ""
    res = subprocess.run(
        ["zbarimg", "--quiet", "--raw", image_path],
        capture_output=True, text=True
    )
    return res.stdout.strip()

def generate_qr(text: str, out_path: str) -> bool:
    if shutil.which("qrencode"):
        res = subprocess.run(["qrencode", "-s", "8", "-o", out_path, text])
        return res.returncode == 0 and os.path.exists(out_path)
    return False

def upload_file(image_path: str, uploader: str = "0x0.st") -> str:
    if not shutil.which("curl"):
        return ""
    endpoints = {
        "0x0.st": ("https://0x0.st", "file"),
        "x0.at": ("https://x0.at", "file"),
        "catbox.moe": ("https://catbox.moe/user/api.php", "fileToUpload"),
    }
    url, field = endpoints.get(uploader, ("https://0x0.st", "file"))
    cmd = ["curl", "-s"]
    if uploader == "catbox.moe":
        cmd.extend(["-F", "reqtype=fileupload"])
    cmd.extend(["-F", f"{field}=@{image_path}", url])
    res = subprocess.run(cmd, capture_output=True, text=True)
    out = res.stdout.strip()
    return out if out.startswith("http") else ""
