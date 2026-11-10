#!/usr/bin/env bash
set -e

PROJ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo chown -R "$USER:$USER" "$PROJ_DIR"
chmod -R u+rwX,go+rX "$PROJ_DIR"

printf '#!/usr/bin/env bash\nexport PYTHONPATH="%s"\nexec python3 -m share_l.main "$@"\n' "$PROJ_DIR" | sudo tee /usr/local/bin/share-l > /dev/null
sudo chmod 0755 /usr/local/bin/share-l

mkdir -p "$HOME/.local/share/applications"
printf '[Desktop Entry]\nName=Share-L\nComment=Screen capture, video/GIF recording and productivity tool for Linux\nExec=/usr/local/bin/share-l\nIcon=applets-screenshooter\nTerminal=false\nType=Application\nCategories=Utility;Graphics;\n' > "$HOME/.local/share/applications/share-l.desktop"
chmod +x "$HOME/.local/share/applications/share-l.desktop"

mkdir -p "$HOME/.config/systemd/user"
printf '[Unit]\nDescription=Share-L Background Daemon (Hardened)\nAfter=graphical-session.target\n\n[Service]\nExecStart=/usr/local/bin/share-l --daemon\nRestart=on-failure\nNoNewPrivileges=yes\nPrivateTmp=yes\nProtectKernelTunables=yes\nProtectControlGroups=yes\nRestrictSUIDSGID=yes\n\n[Install]\nWantedBy=graphical-session.target\n' > "$HOME/.config/systemd/user/share-l.service"

systemctl --user daemon-reload
systemctl --user enable --now share-l.service
echo "✅ Share-L v1.2.0 (Motion Engine & Hardened Service) установлен!"
