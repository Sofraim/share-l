#!/usr/bin/env bash
set -e

PROJ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo chown -R "$USER:$USER" "$PROJ_DIR"
chmod -R u+rwX,go+rX "$PROJ_DIR"

cat << LAUNCHER | sudo tee /usr/local/bin/share-l > /dev/null
#!/usr/bin/env bash
export PYTHONPATH="$PROJ_DIR"
exec python3 -m share_l.main "\$@"
LAUNCHER

sudo chmod 0755 /usr/local/bin/share-l

mkdir -p "$HOME/.local/share/applications"
cat << DESKTOP > "$HOME/.local/share/applications/share-l.desktop"
[Desktop Entry]
Name=Share-L
Comment=Screen capture, file sharing and productivity tool for Linux
Exec=/usr/local/bin/share-l
Icon=applets-screenshooter
Terminal=false
Type=Application
Categories=Utility;Graphics;
DESKTOP

chmod +x "$HOME/.local/share/applications/share-l.desktop"

mkdir -p "$HOME/.config/systemd/user"
cat << SERVICE > "$HOME/.config/systemd/user/share-l.service"
[Unit]
Description=Share-L Background Daemon
After=graphical-session.target

[Service]
ExecStart=/usr/local/bin/share-l --daemon
Restart=on-failure

[Install]
WantedBy=graphical-session.target
SERVICE

systemctl --user daemon-reload
systemctl --user enable --now share-l.service
echo "✅ Share-L успешно установлен!"
