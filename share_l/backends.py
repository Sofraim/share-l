import os
import json
import shutil
import subprocess
from .config import cfg, USER_UID

def get_wayland_env():
    env = os.environ.copy()
    env.pop("QT_QPA_PLATFORM", None)
    env["GDK_BACKEND"] = "wayland,x11"

    runtime_dir = f"/run/user/{USER_UID}"
    env["XDG_RUNTIME_DIR"] = runtime_dir
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime_dir}/bus"

    for sock in ("wayland-0", "wayland-1"):
        if os.path.exists(os.path.join(runtime_dir, sock)):
            env["WAYLAND_DISPLAY"] = sock
            break

    if "DISPLAY" not in env:
        env["DISPLAY"] = ":0"
    return env

def detect_desktop_environment() -> str:
    de = (os.environ.get("XDG_CURRENT_DESKTOP", "") + " " + os.environ.get("DESKTOP_SESSION", "")).lower()
    if "gnome" in de or "ubuntu" in de:
        return "gnome"
    if "kde" in de or "plasma" in de:
        return "kde"
    if "hyprland" in de:
        return "hyprland"
    if "sway" in de:
        return "sway"
    return "generic"

def capture_full_screen(tmp_path: str, delay_sec: int = 0) -> bool:
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    env = get_wayland_env()
    de = detect_desktop_environment()

    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(fd)

    if de == "kde":
        backends_order = ["spectacle", "gnome-screenshot", "grim", "maim", "scrot"]
    elif de in ("hyprland", "sway"):
        backends_order = ["grim", "gnome-screenshot", "spectacle", "maim"]
    else:
        backends_order = ["gnome-screenshot", "spectacle", "grim", "maim", "scrot"]

    for tool in backends_order:
        if not shutil.which(tool):
            continue
        cmd = []
        if tool == "gnome-screenshot":
            cmd = ["gnome-screenshot", "-f", tmp_path]
            if delay_sec > 0:
                cmd.extend(["-d", str(delay_sec)])
        elif tool == "spectacle":
            cmd = ["spectacle", "-b", "-n", "-f", "-o", tmp_path]
            if delay_sec > 0:
                cmd.extend(["-d", str(delay_sec * 1000)])
        elif tool == "grim":
            cmd = ["grim", tmp_path]
        elif tool == "maim":
            cmd = ["maim", "-u", tmp_path]
        elif tool == "scrot":
            cmd = ["scrot", "-o", tmp_path]

        if cmd:
            res = subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            if res.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 500:
                os.chmod(tmp_path, 0o600)
                return True

    return False

def get_visible_windows_rects() -> list:
    rects = []
    if not shutil.which("xdotool"):
        return rects
    try:
        out = subprocess.check_output(
            ["xdotool", "search", "--onlyvisible", "."],
            stderr=subprocess.DEVNULL, text=True, timeout=2
        )
        for wid in out.strip().splitlines()[:30]:
            geo = subprocess.check_output(
                ["xdotool", "getwindowgeometry", "--shell", wid],
                stderr=subprocess.DEVNULL, text=True, timeout=1
            )
            vals = {}
            for line in geo.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
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
            subprocess.Popen(["wl-copy", "--type", "image/png"], stdin=f, env=env)
    elif shutil.which("xclip"):
        subprocess.Popen(["xclip", "-selection", "clipboard", "-t", "image/png", "-i", image_path], env=env)

def copy_text_to_clipboard(text: str):
    env = get_wayland_env()
    if shutil.which("wl-copy") and "WAYLAND_DISPLAY" in env:
        p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, env=env)
        p.communicate(input=text.encode("utf-8"), timeout=3)
    elif shutil.which("xclip"):
        p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE, env=env)
        p.communicate(input=text.encode("utf-8"), timeout=3)

def notify(title: str, body: str, icon_path: str = ""):
    if shutil.which("notify-send"):
        cmd = ["notify-send", "-a", "Share-L", "--", title, body]
        if icon_path and os.path.exists(icon_path):
            cmd = ["notify-send", "-a", "Share-L", "-i", icon_path, "--", title, body]
        subprocess.Popen(cmd, env=get_wayland_env())

def run_ocr(image_path: str) -> str:
    if not shutil.which("tesseract"):
        return ""
    res = subprocess.run(
        ["tesseract", image_path, "stdout", "-l", "rus+eng"],
        capture_output=True, text=True, timeout=20
    )
    return res.stdout.strip()

def decode_qr(image_path: str) -> str:
    if not shutil.which("zbarimg"):
        return ""
    res = subprocess.run(
        ["zbarimg", "--quiet", "--raw", "--", image_path],
        capture_output=True, text=True, timeout=10
    )
    return res.stdout.strip()

def generate_qr(text: str, out_path: str) -> bool:
    if shutil.which("qrencode"):
        fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.close(fd)
        res = subprocess.run(["qrencode", "-s", "8", "-o", out_path, "--", text], timeout=5)
        return res.returncode == 0 and os.path.exists(out_path)
    return False

def upload_file(image_path: str, uploader: str = "0x0.st") -> str:
    if not shutil.which("curl") or not os.path.exists(image_path):
        return ""

    base_curl = [
        "curl", "-sS",
        "--proto", "=https",
        "--tlsv1.2",
        "--connect-timeout", "7",
        "--max-time", "25"
    ]

    try:
        if uploader == "telegram":
            token = (cfg.get("tg_bot_token") or "").strip()
            chat_id = (cfg.get("tg_chat_id") or "").strip()
            if not token or not chat_id:
                notify("Share-L Telegram", "Заполните Bot Token и Chat ID в настройках!")
                return ""
            tg_url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(image_path, "rb") as f:
                res = subprocess.run(
                    base_curl + [
                        "-F", f"chat_id={chat_id}",
                        "-F", "photo=@-;filename=screenshot.png",
                        tg_url
                    ],
                    stdin=f, capture_output=True, text=True, timeout=30
                )
            data = json.loads(res.stdout)
            if data.get("ok"):
                return f"https://t.me/c/{str(chat_id).replace('-100', '')}/{data['result']['message_id']}"
            return ""

        endpoints = {
            "0x0.st": ("https://0x0.st", "file"),
            "x0.at": ("https://x0.at", "file"),
            "catbox.moe": ("https://catbox.moe/user/api.php", "fileToUpload"),
        }

        if uploader == "custom":
            url = (cfg.get("custom_sxcu_url") or "").strip()
            field = (cfg.get("custom_sxcu_field") or "file").strip()
            if not url.startswith("https://"):
                return ""
        else:
            url, field = endpoints.get(uploader, ("https://0x0.st", "file"))

        cmd = list(base_curl)
        if uploader == "catbox.moe":
            cmd.extend(["-F", "reqtype=fileupload"])
        cmd.extend(["-F", f"{field}=@-;filename=upload.png", url])

        with open(image_path, "rb") as f:
            res = subprocess.run(cmd, stdin=f, capture_output=True, text=True, timeout=30)
        out = res.stdout.strip()
        return out if out.startswith("https://") else ""
    except Exception:
        return ""
