# ⚡ Share-L

Нативный инструмент для создания скриншотов, аннотаций, распознавания текста (OCR) и быстрой загрузки файлов под Linux (Wayland & X11), вдохновленный функционалом ShareX. Распространяется под лицензией **GNU GPL v3.0**.

## Возможности
- **Захват на Wayland и X11 без черного экрана** и без лишних диалогов портала.
- **Пиксельная лупа (x8)** с сеткой координат и копированием HEX-цвета по клавише `C`.
- **Редактор аннотаций на лету:** стрелки, рамки, заливка, круги, маркер, хайлайтер, пикселизация (блюр), шаги `1, 2, 3`, текст.
- **Задачи после захвата:** автокопирование в буфер обмена (`wl-clipboard` / `xclip`), автосохранение по папкам, наложение тени (Drop Shadow), рамки и водяного знака, автозагрузка на хостинги (`0x0.st`, `x0.at`, `catbox.moe`).
- **Встроенные утилиты:** закрепление области поверх окон (`Pin to Screen`), OCR (Tesseract RU+EN), сканер и генератор QR-кодов, экранная линейка и проверка хэш-сумм (MD5/SHA256).

## Установка (Debian / Ubuntu)
```bash
sudo apt update && sudo apt install -y \
  gnome-screenshot wl-clipboard xclip ffmpeg \
  python3-pyqt6 python3-pil python3-zbar zbar-tools qrencode \
  tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
  libnotify-bin curl xdotool
pip3 install pynput --break-system-packages

git clone [https://github.com/YOUR_USERNAME/share-l.git](https://github.com/macssugar/share-l.git)
cd share-l
./install.sh
