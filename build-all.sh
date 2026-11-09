#!/usr/bin/env bash
set -e

VERSION="1.1.0"
WORK_DIR="$(pwd)/build_multi"
STAGE_DIR="$WORK_DIR/stage"
DIST_DIR="$(pwd)/dist"

echo "🚀 Старт мульти-сборки Share-L v${VERSION} (DEB + RPM + Arch Pacman)..."
rm -rf "$WORK_DIR" "$DIST_DIR"
mkdir -p "$STAGE_DIR/usr/share/share-l"
mkdir -p "$STAGE_DIR/usr/bin"
mkdir -p "$STAGE_DIR/usr/share/applications"
mkdir -p "$DIST_DIR"

# 1. Подготовка общих файлов программы
cp -r share_l "$STAGE_DIR/usr/share/share-l/"
cp pyproject.toml LICENSE README.md "$STAGE_DIR/usr/share/share-l/"

# Заменяем путь /usr/local/bin/share-l на стандартный системный /usr/bin/share-l внутри пакета
sed -i 's|/usr/local/bin/share-l|/usr/bin/share-l|g' "$STAGE_DIR/usr/share/share-l/share_l/"*.py

cat << 'LAUNCHER' > "$STAGE_DIR/usr/bin/share-l"
#!/usr/bin/env bash
export PYTHONPATH="/usr/share/share-l"
exec python3 -m share_l.main "$@"
LAUNCHER
chmod 0755 "$STAGE_DIR/usr/bin/share-l"

cat << 'DESKTOP' > "$STAGE_DIR/usr/share/applications/share-l.desktop"
[Desktop Entry]
Name=Share-L
Comment=Screen capture, file sharing and productivity tool for Linux
Exec=/usr/bin/share-l
Icon=applets-screenshooter
Terminal=false
Type=Application
Categories=Utility;Graphics;
DESKTOP
chmod 0644 "$STAGE_DIR/usr/share/applications/share-l.desktop"

# ==========================================
# 2. Сборка .DEB (Debian / Ubuntu / Mint)
# ==========================================
echo "📦 [1/4] Сборка пакета .deb (для apt)..."
DEB_DIR="$WORK_DIR/deb"
mkdir -p "$DEB_DIR/DEBIAN"
cp -r "$STAGE_DIR/usr" "$DEB_DIR/"

cat << EOF > "$DEB_DIR/DEBIAN/control"
Package: share-l
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Maintainer: Sofraim <sofraim@users.noreply.github.com>
Depends: python3 (>= 3.9), python3-pyqt6, python3-pil, python3-zbar, tesseract-ocr, tesseract-ocr-rus, tesseract-ocr-eng, wl-clipboard, xclip, xdotool, curl, ffmpeg, qrencode, libnotify-bin
Description: Native screen capture, OCR and productivity tool for Linux (Wayland & X11)
 Share-L is a screen capture tool inspired by ShareX, built for Linux
 with Wayland and X11 support, annotation tools, and secure RAM buffers.
EOF

dpkg-deb --root-owner-group --build "$DEB_DIR" "$DIST_DIR/share-l_${VERSION}_all.deb"

# ==========================================
# 3. Сборка .RPM (Fedora / RHEL / RedOS)
# ==========================================
echo "📦 [2/4] Сборка пакета .rpm (для dnf / rpm)..."
RPM_TOP="$WORK_DIR/rpm"
mkdir -p "$RPM_TOP"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

cat << EOF > "$RPM_TOP/SPECS/share-l.spec"
Name:           share-l
Version:        ${VERSION}
Release:        1
Summary:        Native screen capture, OCR and productivity tool for Linux (Wayland & X11)
License:        GPL-3.0-or-later
URL:            https://github.com/Sofraim/share-l
BuildArch:      noarch
Requires:       python3, python3-pyqt6, python3-pillow, zbar, tesseract, wl-clipboard, xclip, xdotool, curl, qrencode, libnotify

%description
Share-L is a powerful screen capture tool inspired by ShareX, built for Linux
with Wayland and X11 support, annotation tools, and secure RAM buffers.

%install
mkdir -p %{buildroot}/usr
cp -r "$STAGE_DIR/usr/"* %{buildroot}/usr/

%files
/usr/bin/share-l
/usr/share/share-l
/usr/share/applications/share-l.desktop
EOF

rpmbuild --define "_topdir $RPM_TOP" -bb "$RPM_TOP/SPECS/share-l.spec" >/dev/null 2>&1
cp "$RPM_TOP/RPMS/noarch/"*.rpm "$DIST_DIR/share-l-${VERSION}-1.noarch.rpm"

# ==========================================
# 4. Сборка .pkg.tar.zst (Arch Linux / Manjaro)
# ==========================================
echo "📦 [3/4] Сборка пакета .pkg.tar.zst (для pacman)..."
ARCH_DIR="$WORK_DIR/arch"
mkdir -p "$ARCH_DIR"
cp -r "$STAGE_DIR/usr" "$ARCH_DIR/"

INSTALLED_SIZE=$(du -sb "$ARCH_DIR/usr" | awk '{print $1}')
BUILD_DATE=$(date +%s)

cat << EOF > "$ARCH_DIR/.PKGINFO"
pkgname = share-l
pkgbase = share-l
pkgver = ${VERSION}-1
pkgdesc = Native screen capture, OCR and productivity tool for Linux (Wayland & X11)
url = https://github.com/Sofraim/share-l
builddate = ${BUILD_DATE}
packager = Sofraim <sofraim@users.noreply.github.com>
size = ${INSTALLED_SIZE}
arch = any
license = GPL-3.0-or-later
depend = python
depend = python-pyqt6
depend = python-pillow
depend = python-pynput
depend = zbar
depend = tesseract
depend = tesseract-data-rus
depend = tesseract-data-eng
depend = wl-clipboard
depend = xclip
depend = xdotool
depend = curl
depend = ffmpeg
depend = qrencode
depend = libnotify
EOF

(
  cd "$ARCH_DIR"
  LANG=C bsdtar --uid 0 --gid 0 -czf .MTREE --format=mtree \
    --options='!all,use-set,type,uid,gid,mode,time,size,md5,sha256,link' \
    .PKGINFO usr
  LANG=C bsdtar --uid 0 --gid 0 -cf - .MTREE .PKGINFO usr | zstd -c -z -q - > "$DIST_DIR/share-l-${VERSION}-1-any.pkg.tar.zst"
)

# ==========================================
# 5. Генерация PKGBUILD (для AUR / makepkg)
# ==========================================
echo "📦 [4/4] Генерация PKGBUILD для Arch Linux..."
cat << EOF > "$DIST_DIR/PKGBUILD"
# Maintainer: Sofraim <https://github.com/Sofraim>
pkgname=share-l
pkgver=${VERSION}
pkgrel=1
pkgdesc="Native screen capture, OCR and productivity tool for Linux (Wayland & X11)"
arch=('any')
url="https://github.com/Sofraim/share-l"
license=('GPL-3.0-or-later')
depends=(
  'python' 'python-pyqt6' 'python-pillow' 'python-pynput'
  'zbar' 'tesseract' 'tesseract-data-rus' 'tesseract-data-eng'
  'wl-clipboard' 'xclip' 'xdotool' 'curl' 'ffmpeg' 'qrencode' 'libnotify'
)
source=("git+\${url}.git#tag=v\${pkgver}")
sha256sums=('SKIP')

package() {
  cd "\$srcdir/share-l"
  install -dm755 "\$pkgdir/usr/share/share-l"
  cp -r share_l pyproject.toml LICENSE README.md "\$pkgdir/usr/share/share-l/"
  sed -i 's|/usr/local/bin/share-l|/usr/bin/share-l|g' "\$pkgdir/usr/share/share-l/share_l/"*.py

  install -dm755 "\$pkgdir/usr/bin"
  printf '#!/usr/bin/env bash\nexport PYTHONPATH="/usr/share/share-l"\nexec python3 -m share_l.main "\$@"\n' > "\$pkgdir/usr/bin/share-l"
  chmod 0755 "\$pkgdir/usr/bin/share-l"
}
EOF

rm -rf "$WORK_DIR"
echo ""
echo "✅ Все пакеты успешно собраны в папку dist/:"
ls -lh "$DIST_DIR"
