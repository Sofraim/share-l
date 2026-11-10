import os
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QPushButton, QHBoxLayout, QInputDialog, QColorDialog
)
from PyQt6.QtCore import Qt, QRect, QPoint, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QPixmap, QImage, QColor, QPen, QFont,
    QPolygonF, QCursor, QGuiApplication, QPainterPath
)
from .config import cfg
from .effects import apply_image_effects
from .recorder import RecordControlBar
from .backends import (
    copy_image_to_clipboard, copy_text_to_clipboard, notify,
    run_ocr, decode_qr, upload_file, get_visible_windows_rects,
    strip_image_metadata
)

class PinnedWindow(QWidget):
    def __init__(self, pixmap: QPixmap, pos: QPoint):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.pixmap = pixmap
        self.opacity_level = 1.0
        self.resize(pixmap.width() + 4, pixmap.height() + 4)
        self.move(pos)
        self.drag_pos = QPoint()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 174, 255))
        p.drawPixmap(2, 2, self.pixmap)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif event.button() == Qt.MouseButton.RightButton:
            self.close()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)

    def wheelEvent(self, event):
        delta = 0.1 if event.angleDelta().y() > 0 else -0.1
        self.opacity_level = max(0.2, min(1.0, self.opacity_level + delta))
        self.setWindowOpacity(self.opacity_level)


class ShareLOverlay(QWidget):
    capture_completed = pyqtSignal(str)

    def __init__(self, img_path: str, mode: str = "region"):
        super().__init__()
        self.mode = mode
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.BypassWindowManagerHint
        )
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.BlankCursor)

        raw = QImage(img_path)
        screen_geo = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(screen_geo)
        self.bg_pixmap = QPixmap.fromImage(raw).scaled(
            screen_geo.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.bg_image = self.bg_pixmap.toImage()

        self.window_rects = [QRect(*r) for r in get_visible_windows_rects()] if cfg.get("smart_window_snap") else []
        self.hovered_window = QRect()

        self.mouse_pos = self.mapFromGlobal(QCursor.pos())
        self.selecting = False
        self.drawing = False
        self.selection = QRect()
        self.start_pt = QPoint()

        self.current_tool = None
        self.draw_color = QColor(255, 45, 45)
        self.stroke_width = 4
        self.step_counter = 1
        self.annotations = []
        self.current_action = None
        self.rec_bar = None

        self.init_toolbar()

    def init_toolbar(self):
        self.toolbar = QWidget(self)
        self.toolbar.setCursor(Qt.CursorShape.ArrowCursor)
        self.toolbar.setStyleSheet('''
            QWidget { background: #141517; border: 1px solid #3d3d3d; border-radius: 6px; }
            QPushButton {
                color: #f0f0f0; background: #232529; border: 1px solid #383a40;
                padding: 5px 8px; border-radius: 4px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: #34373c; border-color: #00a8fc; }
            QPushButton:checked { background: #0078d7; border-color: #3399ff; }
        ''')
        layout = QHBoxLayout(self.toolbar)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.tool_buttons = {}
        tools = [
            ("rect", "▭ Рамка"),
            ("fill_rect", "◼ Заливка"),
            ("eraser", "🧽 Ластик"),
            ("ellipse", "◯ Круг"),
            ("arrow", "↗ Стрелка"),
            ("pen", "✎ Маркер"),
            ("highlight", "🖍 Хайлайт"),
            ("blur", "▦ Пиксели"),
            ("magnify", "🔎 Линза 2x"),
            ("step", "① Шаг"),
            ("callout", "💬 Выноска"),
            ("text", "T Текст"),
        ]
        for key, label in tools:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, k=key: self.select_tool(k))
            layout.addWidget(btn)
            self.tool_buttons[key] = btn

        btn_color = QPushButton("🎨")
        btn_color.setToolTip("Выбрать цвет")
        btn_color.clicked.connect(self.pick_color)
        layout.addWidget(btn_color)

        btn_undo = QPushButton("↶")
        btn_undo.setToolTip("Отменить (Ctrl+Z)")
        btn_undo.clicked.connect(self.undo_last)
        layout.addWidget(btn_undo)

        btn_vid = QPushButton("🎥 MP4")
        btn_vid.setToolTip("Записать видео выделенной области")
        btn_vid.clicked.connect(lambda: self.start_region_recording("mp4"))
        layout.addWidget(btn_vid)

        btn_gif = QPushButton("🎞 GIF")
        btn_gif.setToolTip("Записать GIF выделенной области")
        btn_gif.clicked.connect(lambda: self.start_region_recording("gif"))
        layout.addWidget(btn_gif)

        btn_pin = QPushButton("📌 Pin (P)")
        btn_pin.clicked.connect(self.pin_selection)
        layout.addWidget(btn_pin)

        btn_ocr = QPushButton("🔍 OCR (O)")
        btn_ocr.clicked.connect(self.ocr_selection)
        layout.addWidget(btn_ocr)

        btn_up = QPushButton("☁ Upload (U)")
        btn_up.clicked.connect(self.upload_selection)
        layout.addWidget(btn_up)

        btn_save = QPushButton("✔ Готово (Enter)")
        btn_save.setStyleSheet("background: #238636; color: white; border-color: #2ea043;")
        btn_save.clicked.connect(self.execute_after_capture_tasks)
        layout.addWidget(btn_save)

        self.toolbar.hide()

    def start_region_recording(self, fmt: str):
        target = self.selection if not self.selection.isNull() and self.selection.width() >= 16 else self.rect()
        self.hide()
        self.rec_bar = RecordControlBar(target, fmt=fmt)
        self.rec_bar.recording_finished.connect(self.capture_completed.emit)
        self.rec_bar.destroyed.connect(self.close)
        self.rec_bar.show()

    def select_tool(self, key):
        for k, b in self.tool_buttons.items():
            b.setChecked(k == key)
        self.current_tool = key
        self.setCursor(Qt.CursorShape.CrossCursor)

    def pick_color(self):
        c = QColorDialog.getColor(self.draw_color, self, "Цвет инструмента Share-L")
        if c.isValid():
            self.draw_color = c

    def undo_last(self):
        if self.annotations:
            last = self.annotations.pop()
            if last["type"] == "step":
                self.step_counter = max(1, self.step_counter - 1)
            self.update()

    def position_toolbar(self):
        if self.selection.isNull() or self.selection.width() < 15:
            self.toolbar.hide()
            return
        self.toolbar.adjustSize()
        x = max(10, min(self.selection.right() - self.toolbar.width(), self.width() - self.toolbar.width() - 10))
        y = self.selection.bottom() + 8
        if y + self.toolbar.height() > self.height() - 10:
            y = max(10, self.selection.top() - self.toolbar.height() - 8)
        self.toolbar.move(x, y)
        self.toolbar.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            if not self.selection.isNull():
                self.selection = QRect()
                self.annotations.clear()
                self.current_tool = None
                self.toolbar.hide()
                self.setCursor(Qt.CursorShape.BlankCursor)
                self.update()
            else:
                self.close()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            if self.mode == "color_picker":
                px_c = self.bg_image.pixelColor(
                    max(0, min(pos.x(), self.bg_image.width() - 1)),
                    max(0, min(pos.y(), self.bg_image.height() - 1))
                ).name().upper()
                copy_text_to_clipboard(px_c)
                notify("Share-L Пипетка", f"Цвет {px_c} скопирован в буфер обмена!")
                self.close()
                return

            if self.current_tool is None or self.selection.isNull():
                self.selecting = True
                self.start_pt = pos
                self.selection = QRect(pos, pos)
                self.toolbar.hide()
            else:
                if self.current_tool == "step":
                    self.annotations.append({
                        "type": "step", "pos": pos,
                        "num": self.step_counter, "color": self.draw_color
                    })
                    self.step_counter += 1
                elif self.current_tool == "text":
                    text, ok = QInputDialog.getText(self, "Share-L Текст", "Введите подпись:")
                    if ok and text:
                        self.annotations.append({
                            "type": "text", "pos": pos, "text": text,
                            "color": self.draw_color, "size": max(14, self.stroke_width * 4)
                        })
                elif self.current_tool == "callout":
                    text, ok = QInputDialog.getText(self, "Share-L Выноска", "Текст облачка-выноски:")
                    if ok and text:
                        self.annotations.append({
                            "type": "callout", "pos": pos, "text": text,
                            "color": self.draw_color
                        })
                else:
                    sample_c = self.bg_image.pixelColor(
                        max(0, min(pos.x(), self.bg_image.width() - 1)),
                        max(0, min(pos.y(), self.bg_image.height() - 1))
                    )
                    self.drawing = True
                    self.current_action = {
                        "type": self.current_tool, "start": pos, "end": pos,
                        "points": [pos],
                        "color": sample_c if self.current_tool == "eraser" else self.draw_color,
                        "width": self.stroke_width
                    }
            self.update()

    def mouseMoveEvent(self, event):
        self.mouse_pos = event.pos()
        if self.selecting:
            self.selection = QRect(self.start_pt, self.mouse_pos).normalized()
        elif self.drawing and self.current_action:
            self.current_action["end"] = self.mouse_pos
            if self.current_action["type"] in ("pen", "highlight"):
                self.current_action["points"].append(self.mouse_pos)
        elif self.selection.isNull() and self.window_rects:
            self.hovered_window = QRect()
            for r in self.window_rects:
                if r.contains(self.mouse_pos):
                    self.hovered_window = r
                    break
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.selecting:
                self.selecting = False
                if self.selection.width() < 6 and self.selection.height() < 6:
                    if not self.hovered_window.isNull():
                        self.selection = self.hovered_window
                    else:
                        self.selection = QRect()
                        self.update()
                        return

                if self.mode == "ruler":
                    return
                if self.mode == "ocr":
                    self.ocr_selection()
                    return
                if self.mode == "qr":
                    self.qr_selection()
                    return
                if self.mode in ("record_mp4", "record_gif"):
                    fmt = "gif" if self.mode == "record_gif" else "mp4"
                    self.start_region_recording(fmt)
                    return

                if not cfg.get("task_open_editor"):
                    self.execute_after_capture_tasks()
                    return

                self.setCursor(Qt.CursorShape.CrossCursor)
                self.position_toolbar()
            elif self.drawing and self.current_action:
                self.drawing = False
                self.annotations.append(self.current_action)
                self.current_action = None
            self.update()

    def mouseDoubleClickEvent(self, event):
        if not self.selection.isNull():
            self.execute_after_capture_tasks()

    def wheelEvent(self, event):
        delta = 1 if event.angleDelta().y() > 0 else -1
        self.stroke_width = max(1, min(25, self.stroke_width + delta))
        self.update()

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.execute_after_capture_tasks()
        elif key == Qt.Key.Key_Z and (mods & Qt.KeyboardModifier.ControlModifier):
            self.undo_last()
        elif key == Qt.Key.Key_C and not (mods & Qt.KeyboardModifier.ControlModifier):
            mx, my = self.mouse_pos.x(), self.mouse_pos.y()
            px_c = self.bg_image.pixelColor(
                max(0, min(mx, self.bg_image.width() - 1)),
                max(0, min(my, self.bg_image.height() - 1))
            ).name().upper()
            copy_text_to_clipboard(px_c)
            notify("Share-L Пипетка", f"Цвет {px_c} скопирован!")
            self.close()
        elif key == Qt.Key.Key_P:
            self.pin_selection()
        elif key == Qt.Key.Key_O:
            self.ocr_selection()
        elif key == Qt.Key.Key_U:
            self.upload_selection()

    def render_canvas(self, p: QPainter):
        p.drawPixmap(0, 0, self.bg_pixmap)
        items = self.annotations + ([self.current_action] if self.current_action else [])
        for it in items:
            t = it["type"]
            if t == "blur":
                r = QRect(it["start"], it["end"]).normalized().intersected(self.bg_pixmap.rect())
                if r.width() > 4 and r.height() > 4:
                    sub = self.bg_pixmap.copy(r)
                    sm = sub.scaled(
                        max(1, r.width() // 12), max(1, r.height() // 12),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation
                    )
                    px = sm.scaled(
                        r.width(), r.height(),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation
                    )
                    p.drawPixmap(r.topLeft(), px)
            elif t == "magnify":
                r = QRect(it["start"], it["end"]).normalized().intersected(self.bg_pixmap.rect())
                if r.width() > 10 and r.height() > 10:
                    center = r.center()
                    src_w, src_h = max(4, r.width() // 2), max(4, r.height() // 2)
                    src_rect = QRect(center.x() - src_w // 2, center.y() - src_h // 2, src_w, src_h).intersected(self.bg_pixmap.rect())
                    zoomed = self.bg_pixmap.copy(src_rect).scaled(
                        r.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
                    )
                    p.save()
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addEllipse(QRect(r.topLeft(), r.size()))
                    p.setClipPath(path)
                    p.drawPixmap(r.topLeft(), zoomed)
                    p.restore()
                    p.setPen(QPen(it["color"], 3))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(r)
            elif t == "rect":
                p.setPen(QPen(it["color"], it["width"]))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRect(it["start"], it["end"]).normalized())
            elif t in ("fill_rect", "eraser"):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(it["color"])
                p.drawRect(QRect(it["start"], it["end"]).normalized())
            elif t == "ellipse":
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setPen(QPen(it["color"], it["width"]))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QRect(it["start"], it["end"]).normalized())
            elif t in ("pen", "highlight"):
                c = QColor(it["color"])
                w = it["width"]
                if t == "highlight":
                    c.setAlpha(110)
                    w = max(14, w * 4)
                pen = QPen(c, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                pts = it["points"]
                for i in range(1, len(pts)):
                    p.drawLine(pts[i - 1], pts[i])
            elif t == "arrow":
                self.draw_arrow(p, it["start"], it["end"], it["color"], it["width"])
            elif t == "step":
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setBrush(it["color"])
                p.setPen(QPen(Qt.GlobalColor.white, 2))
                c = it["pos"]
                p.drawEllipse(c, 14, 14)
                p.setFont(QFont("Sans", 11, QFont.Weight.Bold))
                p.drawText(QRect(c.x() - 14, c.y() - 14, 28, 28), Qt.AlignmentFlag.AlignCenter, str(it["num"]))
            elif t == "callout":
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setFont(QFont("Sans", 11, QFont.Weight.Bold))
                fm = p.fontMetrics()
                tw = fm.horizontalAdvance(it["text"]) + 20
                th = 30
                tip = it["pos"]
                bx = tip.x() - tw // 2
                by = tip.y() - th - 14
                box_rect = QRect(bx, by, tw, th)
                p.setBrush(it["color"])
                p.setPen(QPen(Qt.GlobalColor.white, 2))
                p.drawRoundedRect(box_rect, 6, 6)
                tail = QPolygonF([
                    QPointF(tip.x() - 6, by + th),
                    QPointF(tip.x() + 6, by + th),
                    QPointF(tip.x(), tip.y())
                ])
                p.drawPolygon(tail)
                p.setPen(Qt.GlobalColor.white)
                p.drawText(box_rect, Qt.AlignmentFlag.AlignCenter, it["text"])
            elif t == "text":
                p.setPen(it["color"])
                p.setFont(QFont("Sans", it["size"], QFont.Weight.Bold))
                p.drawText(it["pos"], it["text"])

    def draw_arrow(self, p, start, end, color, width):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(start, end)
        dx, dy = end.x() - start.x(), end.y() - start.y()
        ln = (dx**2 + dy**2) ** 0.5
        if ln == 0:
            return
        ux, uy = dx / ln, dy / ln
        hl = max(14, width * 3.5)
        hx, hy = end.x() - ux * hl, end.y() - uy * hl
        px, py = -uy * (hl * 0.5), ux * (hl * 0.5)
        poly = QPolygonF([QPointF(end), QPointF(hx + px, hy + py), QPointF(hx - px, hy - py)])
        p.setBrush(color)
        p.drawPolygon(poly)

    def paintEvent(self, event):
        p = QPainter(self)
        canvas = QPixmap(self.size())
        cp = QPainter(canvas)
        self.render_canvas(cp)
        cp.end()

        p.drawPixmap(0, 0, canvas)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))

        if self.selection.isNull() and not self.hovered_window.isNull():
            p.drawPixmap(self.hovered_window.topLeft(), canvas, self.hovered_window)
            p.setPen(QPen(QColor(0, 174, 255), 2, Qt.PenStyle.DashLine))
            p.drawRect(self.hovered_window)

        if not self.selection.isNull():
            p.drawPixmap(self.selection.topLeft(), canvas, self.selection)
            p.setPen(QPen(Qt.GlobalColor.white, 1, Qt.PenStyle.SolidLine))
            p.drawRect(self.selection)
            p.setPen(QPen(Qt.GlobalColor.black, 1, Qt.PenStyle.DashLine))
            p.drawRect(self.selection)

            w_px, h_px = self.selection.width(), self.selection.height()
            diag = int((w_px**2 + h_px**2) ** 0.5)
            angle_txt = f" | Перо: {self.stroke_width}px" if self.mode != "ruler" else f" | Площадь: {w_px*h_px}px²"
            txt = f"X:{self.selection.x()} Y:{self.selection.y()} | {w_px}×{h_px} px (Диаг: {diag}px){angle_txt}"
            p.setFont(QFont("Monospace", 9, QFont.Weight.Bold))
            tw = p.fontMetrics().horizontalAdvance(txt) + 16
            by = max(4, self.selection.top() - 26)
            bx = max(4, self.selection.left())
            p.fillRect(QRect(bx, by, tw, 22), QColor(20, 20, 20, 225))
            p.setPen(Qt.GlobalColor.white)
            p.drawText(QRect(bx, by, tw, 22), Qt.AlignmentFlag.AlignCenter, txt)

        if self.selecting or self.selection.isNull():
            mx, my = self.mouse_pos.x(), self.mouse_pos.y()
            if cfg.get("show_crosshair"):
                p.setPen(QPen(QColor(0, 174, 255, 195), 1, Qt.PenStyle.DashLine))
                p.drawLine(0, my, self.width(), my)
                p.drawLine(mx, 0, mx, self.height())

            if cfg.get("show_magnifier"):
                gc = int(cfg.get("magnifier_size") or 15)
                zm = int(cfg.get("magnifier_zoom") or 8)
                ms = gc * zm
                bx = mx + 24 if mx + 24 + ms < self.width() else mx - ms - 24
                by = my + 24 if my + 24 + ms + 48 < self.height() else my - ms - 68

                src = QRect(mx - gc // 2, my - gc // 2, gc, gc)
                sub = self.bg_pixmap.copy(src).scaled(
                    ms, ms, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation
                )
                p.drawPixmap(bx, by, sub)

                p.setPen(QPen(QColor(255, 255, 255, 45), 1))
                for i in range(gc + 1):
                    p.drawLine(bx + i * zm, by, bx + i * zm, by + ms)
                    p.drawLine(bx, by + i * zm, bx + ms, by + i * zm)

                co = (gc // 2) * zm
                p.fillRect(QRect(bx + co, by, zm, ms), QColor(0, 174, 255, 75))
                p.fillRect(QRect(bx, by + co, ms, zm), QColor(0, 174, 255, 75))
                p.setPen(QPen(QColor(255, 50, 50), 1))
                p.drawRect(bx + co, by + co, zm, zm)
                p.setPen(QPen(Qt.GlobalColor.white, 2))
                p.drawRect(bx, by, ms, ms)

                px_c = self.bg_image.pixelColor(
                    max(0, min(mx, self.bg_image.width() - 1)),
                    max(0, min(my, self.bg_image.height() - 1))
                )
                c_str = f"({mx},{my}) {px_c.name().upper()} [C]"
                p.fillRect(QRect(bx, by + ms + 2, ms + 20, 22), QColor(20, 20, 20, 235))
                p.fillRect(QRect(bx + 4, by + ms + 6, 14, 14), px_c)
                p.setPen(Qt.GlobalColor.white)
                p.setFont(QFont("Monospace", 8, QFont.Weight.Bold))
                p.drawText(QRect(bx + 22, by + ms + 2, ms, 22), Qt.AlignmentFlag.AlignVCenter, c_str)

    def build_save_path(self) -> str:
        base_dir = cfg.get("save_dir")
        if cfg.get("use_month_subfolder"):
            base_dir = os.path.join(base_dir, datetime.now().strftime("%Y-%m"))
        os.makedirs(base_dir, exist_ok=True)
        pattern = cfg.get("filename_pattern") or "ShareL_%Y-%m-%d_%H-%M-%S"
        ext = cfg.get("image_format") or "png"
        fname = datetime.now().strftime(pattern) + f".{ext}"
        return os.path.join(base_dir, fname)

    def get_cropped_pixmap_and_save(self):
        if self.selection.isNull() or self.selection.width() < 2:
            self.selection = self.rect()
        fc = QPixmap(self.size())
        cp = QPainter(fc)
        self.render_canvas(cp)
        cp.end()
        crop = fc.copy(self.selection)
        crop = apply_image_effects(crop)

        fp = self.build_save_path()
        fmt = (cfg.get("image_format") or "png").upper()
        crop.save(fp, fmt, int(cfg.get("jpeg_quality") or 95))
        strip_image_metadata(fp)
        return crop, fp

    def execute_after_capture_tasks(self):
        crop, fp = self.get_cropped_pixmap_and_save()
        self.hide()

        url = ""
        ocr_txt = ""

        if cfg.get("task_copy_image"):
            copy_image_to_clipboard(fp)

        if cfg.get("task_pin_to_screen"):
            self.pin_win = PinnedWindow(crop, self.selection.topLeft())
            self.pin_win.show()

        if cfg.get("task_run_ocr"):
            ocr_txt = run_ocr(fp)
            if ocr_txt:
                copy_text_to_clipboard(ocr_txt)
                notify("Share-L OCR", f"Текст скопирован:\n{ocr_txt[:100]}", fp)

        if cfg.get("task_scan_qr"):
            qr_txt = decode_qr(fp)
            if qr_txt:
                copy_text_to_clipboard(qr_txt)
                notify("Share-L QR", f"QR декодирован:\n{qr_txt}", fp)

        if cfg.get("task_upload"):
            url = upload_file(fp, cfg.get("uploader"))
            if url and cfg.get("task_copy_url"):
                copy_text_to_clipboard(url)
                notify("Share-L Upload", f"Ссылка в буфере:\n{url}", fp)
        elif cfg.get("task_show_notification"):
            notify("Share-L", f"Скриншот сохранен и очищен от метаданных!\n{os.path.basename(fp)}", fp)

        cfg.add_history_entry(fp, url=url, ocr_text=ocr_txt)
        self.capture_completed.emit(fp)
        self.close()

    def pin_selection(self):
        crop, fp = self.get_cropped_pixmap_and_save()
        self.pin_win = PinnedWindow(crop, self.selection.topLeft())
        self.pin_win.show()
        cfg.add_history_entry(fp)
        self.capture_completed.emit(fp)
        self.hide()

    def ocr_selection(self):
        _, fp = self.get_cropped_pixmap_and_save()
        self.hide()
        txt = run_ocr(fp)
        if txt:
            copy_text_to_clipboard(txt)
            notify("Share-L OCR", f"Текст скопирован в буфер:\n{txt[:120]}", fp)
        else:
            notify("Share-L OCR", "Текст не обнаружен", fp)
        cfg.add_history_entry(fp, ocr_text=txt)
        self.capture_completed.emit(fp)
        self.close()

    def qr_selection(self):
        _, fp = self.get_cropped_pixmap_and_save()
        self.hide()
        txt = decode_qr(fp)
        if txt:
            copy_text_to_clipboard(txt)
            notify("Share-L QR-Сканер", f"QR-код скопирован в буфер:\n{txt}", fp)
        else:
            notify("Share-L QR-Сканер", "QR-код не найден в выделенной области", fp)
        self.close()

    def upload_selection(self):
        _, fp = self.get_cropped_pixmap_and_save()
        self.hide()
        url = upload_file(fp, cfg.get("uploader"))
        if url:
            copy_text_to_clipboard(url)
            notify("Share-L Upload", f"Ссылка скопирована в буфер:\n{url}", fp)
        else:
            notify("Share-L Upload", "Ошибка загрузки", fp)
        cfg.add_history_entry(fp, url=url)
        self.capture_completed.emit(fp)
        self.close()
