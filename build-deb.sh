#!/usr/bin/env bash
set -e

VERSION="1.1.0"
BUILD_DIR="build_deb"

echo "📦 Сборка .deb пакета для Share-L..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/usr/share/share-l"
mkdir -p "$BUILD_DIR/usr/local/bin"
mkdir -p "$BUILD_DIR/usr/share/applications"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps"

# Копируем исходники python
cp -r share_l "$BUILD_DIR/usr/share/share-l/"
cp pyproject.toml LICENSE README.md "$BUILD_DIR/usr/share/share-l/"

# Создаем бинарник-обертку
cat << 'LAUNCHER' > "$BUILD_DIR/usr/local/bin/share-l"
#!/usr/bin/env bash
export PYTHONPATH="/usr/share/share-l"
exec python3 -m share_l.main "$@"
LAUNCHER
chmod +x "$BUILD_DIR/usr/local/bin/share-l"

# Создаем .desktop ярлык
cat << 'DESKTOP' > "$BUILD_DIR/usr/share/applications/share-l.desktop"
[Desktop Entry]
Name=Share-L
Comment=Screen capture, file sharing and productivity tool for Linux
Exec=/usr/local/bin/share-l
Icon=applets-screenshooter
Terminal=false
Type=Application
Categories=Utility;Graphics;
DESKTOP

# Копируем метаданные DEBIAN
cp -r packaging/deb/DEBIAN "$BUILD_DIR/"
chmod 755 "$BUILD_DIR/DEBIAN/postinst" 2>/dev/null || true

# Собираем пакет
dpkg-deb --build "$BUILD_DIR" "share-l_${VERSION}_all.deb"
rm -rf "$BUILD_DIR"
echo "✅ Готово! Пакет создан: share-l_${VERSION}_all.deb"
echo "Установка: sudo apt install ./share-l_${VERSION}_all.deb"
