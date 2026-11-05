#!/usr/bin/env python3
"""Swap Resizer — GUI para visualizar y redimensionar el swapfile de Linux."""

import math
import os
import subprocess
import sys

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

SWAPFILE = "/swapfile"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APPLY_SCRIPT = os.path.join(SCRIPT_DIR, "apply_swap.sh")


def read_swap_info():
    """Lee SwapTotal/SwapFree de /proc/meminfo. Devuelve (total_kb, used_kb)."""
    total = free = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("SwapTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("SwapFree:"):
                    free = int(line.split()[1])
    except OSError:
        pass
    return total, max(0, total - free)


def read_swappiness():
    try:
        with open("/proc/sys/vm/swappiness", "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def fmt_gb(kb):
    return kb / 1024 / 1024


def read_mem_info():
    """Lee MemTotal/MemAvailable/caché de /proc/meminfo.
    Devuelve (total_kb, used_kb, cache_kb)."""
    vals = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                key = line.split(":")[0]
                if key in ("MemTotal", "MemAvailable",
                           "Cached", "Buffers", "SReclaimable"):
                    vals[key] = int(line.split()[1])
    except OSError:
        pass
    total = vals.get("MemTotal", 0)
    used = total - vals.get("MemAvailable", total)
    cache = (vals.get("Cached", 0) + vals.get("Buffers", 0)
             + vals.get("SReclaimable", 0))
    return total, max(0, used), cache


class PieIcon(QWidget):
    """Mini quesito de uso estilo monitor de sistema de GNOME."""

    def __init__(self, diameter=44, parent=None):
        super().__init__(parent)
        self._fraction = 0.0
        self._color = QColor("#4caf50")
        self.setFixedSize(diameter, diameter)

    def set_value(self, fraction, color):
        self._fraction = max(0.0, min(1.0, fraction))
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = 3
        d = self.width() - 2 * m
        painter.setPen(QPen(QColor("#3b3b3b"), 2))
        painter.setBrush(QColor("#2a2a2a"))
        painter.drawEllipse(m, m, d, d)
        if self._fraction > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color)
            painter.drawPie(m, m, d, d, 90 * 16,
                            int(-360 * 16 * self._fraction))
        painter.end()


class CircularGauge(QWidget):
    """Anillo interactivo: el arco exterior (arrastrable) define el nuevo
    tamaño del swap y el arco interior muestra los GB realmente usados."""

    sizeChanged = pyqtSignal(int)

    MIN_GB = 1
    MAX_GB = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_gb = 8
        self._used_gb = 0.0
        self._total_gb = 0.0
        self._dragging = False
        self.setMinimumSize(240, 240)

    # ---------------- API ----------------

    @property
    def selected_gb(self):
        return self._selected_gb

    def set_selected_gb(self, gb):
        gb = max(self.MIN_GB, min(self.MAX_GB, int(round(gb))))
        if gb != self._selected_gb:
            self._selected_gb = gb
            self.sizeChanged.emit(gb)
            self.update()

    def set_usage(self, used_gb, total_gb):
        self._used_gb = used_gb
        self._total_gb = total_gb
        self.update()

    # ---------------- Pintura ----------------

    def _usage_fraction(self):
        return self._used_gb / self._total_gb if self._total_gb else 0.0

    def _usage_color(self):
        frac = self._usage_fraction()
        if frac < 0.60:
            return QColor("#4caf50")
        if frac < 0.85:
            return QColor("#ff9800")
        return QColor("#f44336")

    def _angle_point(self, fraction, radius):
        """Punto del anillo para una fracción (0 = arriba, sentido horario)."""
        angle = math.radians(fraction * 360)
        cx, cy = self.width() / 2, self.height() / 2
        return cx + radius * math.sin(angle), cy - radius * math.cos(angle)

    def paintEvent(self, event):  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height()) - 44
        x = (self.width() - side) // 2
        y = (self.height() - side) // 2
        radius = side / 2

        # Pista exterior (escala 0..MAX_GB GB)
        pen = QPen(QColor("#3b3b3b"), 18)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(x, y, side, side, 0, 360 * 16)

        # Interior: quesito de uso estilo GNOME (relleno = usado/total)
        inner_margin = 26
        inner = side - 2 * inner_margin
        ix, iy = x + inner_margin, y + inner_margin
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2a2a2a"))
        painter.drawEllipse(ix, iy, inner, inner)
        frac = self._usage_fraction()
        if frac > 0:
            painter.setBrush(self._usage_color())
            painter.drawPie(ix, iy, inner, inner,
                            90 * 16, int(-360 * 16 * frac))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#3b3b3b"), 2))
        painter.drawEllipse(ix, iy, inner, inner)

        # Arco exterior: tamaño seleccionado (arrastrable)
        sel_fraction = self._selected_gb / self.MAX_GB
        pen = QPen(QColor("#2d6cdf"), 18)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(x, y, side, side, 90 * 16, int(-360 * 16 * sel_fraction))

        # Manija arrastrable al final del arco
        hx, hy = self._angle_point(sel_fraction, radius)
        painter.setPen(QPen(QColor("#e6e6e6"), 3))
        painter.setBrush(QColor("#2d6cdf"))
        painter.drawEllipse(int(hx - 10), int(hy - 10), 20, 20)

        # Chip oscuro centrado para que el texto sea legible sobre el quesito
        cx, cy = self.width() / 2, self.height() / 2
        chip_w, chip_h = 140, 66
        chip = QRectF(cx - chip_w / 2, cy - chip_h / 2, chip_w, chip_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 20, 210))
        painter.drawRoundedRect(chip, 12, 12)

        # Texto: tamaño elegido
        font = QFont()
        font.setPointSize(20)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#e6e6e6"))
        painter.drawText(
            QRectF(chip.left(), chip.top() + 6, chip_w, 32),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            f"{self._selected_gb} GB",
        )

        # Texto: uso actual
        font.setPointSize(9)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(self._usage_color())
        frac = self._usage_fraction()
        painter.drawText(
            QRectF(chip.left(), chip.top() + 38, chip_w, 22),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            f"{self._used_gb:.1f} GB usados · {frac * 100:.0f}%",
        )
        painter.end()

    # ---------------- Interacción ----------------

    def _ring_hit(self, pos):
        cx, cy = self.width() / 2, self.height() / 2
        radius = (min(self.width(), self.height()) - 44) / 2
        dist = math.hypot(pos.x() - cx, pos.y() - cy)
        return abs(dist - radius) <= 24

    def _size_from_pos(self, pos):
        cx, cy = self.width() / 2, self.height() / 2
        angle = math.degrees(
            math.atan2(pos.x() - cx, -(pos.y() - cy))
        ) % 360
        gb = round(angle / 360 * self.MAX_GB)
        return max(self.MIN_GB, min(self.MAX_GB, gb))

    def mousePressEvent(self, event):  # noqa: N802
        if (event.button() == Qt.MouseButton.LeftButton
                and self._ring_hit(event.position())):
            self._dragging = True
            self.set_selected_gb(self._size_from_pos(event.position()))

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._dragging:
            self.set_selected_gb(self._size_from_pos(event.position()))

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._dragging = False


class SwapResizerWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Swap Resizer")
        self.setMinimumWidth(420)
        self.setStyleSheet(
            """
            QWidget { background-color: #1e1e1e; color: #e6e6e6; }
            QGroupBox {
                border: 1px solid #444; border-radius: 8px;
                margin-top: 12px; padding-top: 8px; font-weight: bold;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; }
            QPushButton {
                background-color: #2d6cdf; border: none; border-radius: 6px;
                padding: 8px 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3d7cef; }
            QPushButton:pressed { background-color: #245cbd; }
            QPushButton:disabled { background-color: #444; color: #888; }
            QSlider::groove:horizontal {
                height: 6px; background: #3b3b3b; border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 16px; height: 16px; margin: -6px 0;
                background: #2d6cdf; border-radius: 8px;
            }
            QSpinBox {
                background: #2b2b2b; border: 1px solid #444;
                border-radius: 4px; padding: 4px;
            }
            QProgressBar {
                background: #3b3b3b; border-radius: 7px;
                height: 16px; text-align: center; color: #e6e6e6;
            }
            QProgressBar::chunk {
                background: #2d6cdf; border-radius: 7px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- Gauge ---
        self.gauge = CircularGauge()
        layout.addWidget(self.gauge, alignment=Qt.AlignmentFlag.AlignCenter)

        # --- Filas estilo monitor de sistema (quesitos + texto) ---
        stats_row = QHBoxLayout()
        self.mem_pie = PieIcon()
        self.mem_label = QLabel("Memoria\n—")
        self.swap_pie = PieIcon()
        self.swap_label = QLabel("Intercambio\n—")
        for pie, label in ((self.mem_pie, self.mem_label),
                           (self.swap_pie, self.swap_label)):
            label.setStyleSheet("font-weight: normal;")
            cell = QHBoxLayout()
            cell.addWidget(pie)
            cell.addSpacing(6)
            cell.addWidget(label)
            cell.addStretch(1)
            stats_row.addLayout(cell, stretch=1)
        layout.addLayout(stats_row)

        # --- Redimensionar ---
        resize_group = QGroupBox("Redimensionar swap")
        resize_layout = QVBoxLayout(resize_group)

        hint = QLabel("Arrastra el anillo para elegir el nuevo tamaño")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #9a9a9a; font-weight: normal;")
        resize_layout.addWidget(hint)

        self.size_label = QLabel("Nuevo tamaño: 8 GB")
        self.size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        resize_layout.addWidget(self.size_label)
        self.gauge.sizeChanged.connect(
            lambda gb: self.size_label.setText(f"Nuevo tamaño: {gb} GB")
        )

        self.usage_bar = QProgressBar()
        self.usage_bar.setRange(0, 1000)
        self.usage_bar.setTextVisible(True)
        resize_layout.addWidget(self.usage_bar)

        self.resize_button = QPushButton("Aplicar nuevo tamaño")
        self.resize_button.clicked.connect(self.apply_resize)
        resize_layout.addWidget(self.resize_button)
        layout.addWidget(resize_group)

        # --- Swappiness ---
        sw_group = QGroupBox("Swappiness — cuánto usa el sistema el swap")
        sw_layout = QVBoxLayout(sw_group)

        sw_hint = QLabel(
            "Controla la tendencia de Linux a mover cosas de la RAM al swap."
        )
        sw_hint.setStyleSheet("color: #9a9a9a; font-weight: normal;")
        sw_hint.setWordWrap(True)
        sw_layout.addWidget(sw_hint)

        sw_row = QHBoxLayout()
        self.sw_slider = QSlider(Qt.Orientation.Horizontal)
        self.sw_slider.setRange(0, 100)
        self.sw_spin = QSpinBox()
        self.sw_spin.setRange(0, 100)
        # Las flechas del spinbox se ven rotas con el tema oscuro
        self.sw_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.sw_spin.setFixedWidth(52)
        self.sw_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sw_slider.valueChanged.connect(self.sw_spin.setValue)
        self.sw_spin.valueChanged.connect(self.sw_slider.setValue)
        sw_row.addWidget(self.sw_slider, stretch=1)
        sw_row.addWidget(self.sw_spin)
        sw_layout.addLayout(sw_row)

        # Etiquetas en los extremos del slider
        ends_row = QHBoxLayout()
        left_lbl = QLabel("0 — solo si la RAM se agota")
        left_lbl.setStyleSheet(
            "color: #4caf50; font-weight: normal; font-size: 10px;")
        right_lbl = QLabel("100 — usa swap a menudo")
        right_lbl.setStyleSheet(
            "color: #f44336; font-weight: normal; font-size: 10px;")
        ends_row.addWidget(left_lbl)
        ends_row.addStretch(1)
        ends_row.addWidget(right_lbl)
        sw_layout.addLayout(ends_row)

        # Descripción dinámica según el valor elegido
        self.sw_desc = QLabel()
        self.sw_desc.setWordWrap(True)
        self.sw_desc.setStyleSheet("color: #9a9a9a; font-weight: normal;")
        self.sw_slider.valueChanged.connect(self._update_sw_desc)
        self._update_sw_desc(self.sw_slider.value())
        sw_layout.addWidget(self.sw_desc)

        self.sw_button = QPushButton("Aplicar swappiness (permanente)")
        self.sw_button.clicked.connect(self.apply_swappiness)
        sw_layout.addWidget(self.sw_button)
        layout.addWidget(sw_group)

        # Estado inicial + refresco periódico
        self._busy = False
        self._initialized = False
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)

    # ---------------- Lógica ----------------

    def refresh(self):
        # Fila de memoria (estilo monitor de GNOME)
        mem_total, mem_used, mem_cache = read_mem_info()
        if mem_total > 0:
            mem_frac = mem_used / mem_total
            self.mem_pie.set_value(mem_frac, "#ef5350")
            self.mem_label.setText(
                f"Memoria\n{fmt_gb(mem_used):.1f} GB "
                f"({mem_frac * 100:.1f}%) de {fmt_gb(mem_total):.1f} GB\n"
                f"Caché {fmt_gb(mem_cache):.1f} GB"
            )

        total_kb, used_kb = read_swap_info()
        if total_kb <= 0:
            self.gauge.set_usage(0, 0)
            self.swap_label.setText("Intercambio\nsin swap activo")
            return

        fraction = used_kb / total_kb
        used_gb, total_gb = fmt_gb(used_kb), fmt_gb(total_kb)
        self.gauge.set_usage(used_gb, total_gb)
        self.swap_pie.set_value(fraction, "#4caf50")
        self.swap_label.setText(
            f"Intercambio\n{used_gb:.1f} GB ({fraction * 100:.1f}%) "
            f"de {total_gb:.1f} GB"
        )
        self.usage_bar.setValue(int(fraction * 1000))
        self.usage_bar.setFormat(
            f"{used_gb:.1f} / {total_gb:.1f} GB ({fraction * 100:.0f}%)"
        )

        # Inicializa el selector con el tamaño actual (solo la primera vez)
        if not self._initialized and total_gb >= 1:
            self._initialized = True
            self.gauge.set_selected_gb(round(total_gb))
            sw = read_swappiness()
            if sw is not None:
                self.sw_slider.setValue(sw)

    def _run_pkexec(self, args, success_msg):
        if self._busy:
            return
        self._busy = True
        self.resize_button.setEnabled(False)
        self.sw_button.setEnabled(False)
        try:
            result = subprocess.run(
                ["pkexec"] + args,
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                QMessageBox.information(self, "Listo", success_msg)
            elif result.returncode == 126:
                QMessageBox.warning(self, "Cancelado", "Autenticación cancelada.")
            else:
                QMessageBox.critical(
                    self, "Error",
                    f"Falló la operación:\n{result.stderr or result.stdout}",
                )
        except subprocess.TimeoutExpired:
            QMessageBox.critical(self, "Error", "La operación tardó demasiado.")
        except FileNotFoundError:
            QMessageBox.critical(self, "Error", "No se encontró 'pkexec'.")
        finally:
            self._busy = False
            self.resize_button.setEnabled(True)
            self.sw_button.setEnabled(True)
            self.refresh()

    def apply_resize(self):
        size_gb = self.gauge.selected_gb
        total_kb, _ = read_swap_info()
        current = fmt_gb(total_kb)
        answer = QMessageBox.question(
            self, "Confirmar",
            f"Se desactivará el swap temporalmente y se recreará "
            f"{SWAPFILE} con {size_gb} GB (ahora: {current:.1f} GB).\n\n"
            f"Se pedirá tu contraseña (pkexec). ¿Continuar?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_pkexec(
            ["bash", APPLY_SCRIPT, str(size_gb)],
            f"Swap redimensionado a {size_gb} GB.",
        )

    def _update_sw_desc(self, value):
        if value <= 10:
            text = ("Bajo — el swap solo se usa cuando la RAM está casi "
                    "llena. El sistema se mantiene ágil; recomendado "
                    "con 8 GB+ de RAM.")
        elif value <= 30:
            text = ("Moderado — usa swap solo si la RAM empieza a "
                    "escasear. Buen equilibrio.")
        elif value <= 60:
            text = ("Medio (valor por defecto) — usa swap con cierta "
                    "frecuencia aunque aún quede RAM libre.")
        else:
            text = ("Alto — envía memoria al swap pronto y a menudo. "
                    "Más RAM libre, pero más accesos a disco: más lento "
                    "y más desgaste del SSD.")
        self.sw_desc.setText(text)

    def apply_swappiness(self):
        value = self.sw_spin.value()
        self._run_pkexec(
            [
                "sh", "-c",
                f"sysctl -w vm.swappiness={value} && "
                f"echo 'vm.swappiness={value}' > /etc/sysctl.d/99-swappiness.conf",
            ],
            f"Swappiness fijado a {value} (persistente tras reinicio).",
        )


def main():
    app = QApplication(sys.argv)
    window = SwapResizerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
