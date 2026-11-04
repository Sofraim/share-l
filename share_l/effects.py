from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QRect
from .config import cfg

def apply_image_effects(pixmap: QPixmap) -> QPixmap:
    if not cfg.get("task_add_effects"):
        return pixmap

    add_border = cfg.get("fx_border")
    border_size = int(cfg.get("fx_border_size") or 2) if add_border else 0
    border_color = QColor(cfg.get("fx_border_color") or "#00a8fc")

    add_shadow = cfg.get("fx_shadow")
    pad = 24 if add_shadow else 0

    w = pixmap.width() + (border_size * 2) + (pad * 2)
    h = pixmap.height() + (border_size * 2) + (pad * 2)

    out = QPixmap(w, h)
    out.fill(Qt.GlobalColor.transparent)

    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Мягкая многослойная тень в стиле Share-L
    if add_shadow:
        for i in range(12, 0, -1):
            alpha = int(85 * (1 - i / 12) ** 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(
                QRect(pad - i, pad - i + 4, pixmap.width() + border_size * 2 + i * 2, pixmap.height() + border_size * 2 + i * 2),
                6, 6
            )

    # Рамка вокруг скриншота
    if add_border and border_size > 0:
        p.fillRect(
            QRect(pad, pad, pixmap.width() + border_size * 2, pixmap.height() + border_size * 2),
            border_color
        )

    # Сам скриншот
    img_x = pad + border_size
    img_y = pad + border_size
    p.drawPixmap(img_x, img_y, pixmap)

    # Водяной знак (Watermark)
    if cfg.get("fx_watermark"):
        wm_text = cfg.get("fx_watermark_text") or "Share-L"
        p.setFont(QFont("Sans", 10, QFont.Weight.Bold))
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(wm_text) + 14
        th = 22
        wx = img_x + pixmap.width() - tw - 8
        wy = img_y + pixmap.height() - th - 8
        p.fillRect(QRect(wx, wy, tw, th), QColor(0, 0, 0, 150))
        p.setPen(QColor(255, 255, 255, 220))
        p.drawText(QRect(wx, wy, tw, th), Qt.AlignmentFlag.AlignCenter, wm_text)

    p.end()
    return out
