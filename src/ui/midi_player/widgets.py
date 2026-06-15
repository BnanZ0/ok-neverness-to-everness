from ok import og
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ExpandGroupSettingCard, FluentIcon, LineEdit, SubtitleLabel

from src.ui.common import FluentSystemIcon


class _MarqueeLabelMixin:
    def _init_marquee(self):
        self._marquee_text = super().text()
        self._marquee_offset = 0
        self._marquee_gap = 36
        self._marquee_timer = QTimer(self)
        self._marquee_timer.setInterval(35)
        self._marquee_timer.timeout.connect(self._advance_marquee)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def setText(self, text):
        if not hasattr(self, "_marquee_timer"):
            super().setText(text)
            return
        self._marquee_text = text
        self._marquee_offset = 0
        self.setToolTip(text)
        super().setText(text)
        self._sync_marquee_timer()
        self.update()

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(min(hint.width(), 240), hint.height())

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(80, hint.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_marquee_timer()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_marquee_timer()

    def hideEvent(self, event):
        self._marquee_timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        if not self._needs_marquee():
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setClipRect(self.rect())
        painter.setPen(self.palette().color(self.foregroundRole()))
        metrics = QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self._marquee_text)
        y = int((self.height() + metrics.ascent() - metrics.descent()) / 2)
        x = -self._marquee_offset
        painter.drawText(x, y, self._marquee_text)
        painter.drawText(x + text_width + self._marquee_gap, y, self._marquee_text)

    def _needs_marquee(self):
        text = getattr(self, "_marquee_text", super().text())
        if not text:
            return False
        return QFontMetrics(self.font()).horizontalAdvance(text) > max(0, self.width())

    def _advance_marquee(self):
        if not self._needs_marquee():
            self._marquee_offset = 0
            self._marquee_timer.stop()
            self.update()
            return
        text_width = QFontMetrics(self.font()).horizontalAdvance(self._marquee_text)
        self._marquee_offset = (self._marquee_offset + 1) % (text_width + self._marquee_gap)
        self.update()

    def _sync_marquee_timer(self):
        if self.isVisible() and self._needs_marquee():
            if not self._marquee_timer.isActive():
                self._marquee_timer.start()
        else:
            self._marquee_timer.stop()
            self._marquee_offset = 0


class MarqueeBodyLabel(_MarqueeLabelMixin, BodyLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._init_marquee()
        self.setText(text)


class MarqueeSubtitleLabel(_MarqueeLabelMixin, SubtitleLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._init_marquee()
        self.setText(text)


class PitchChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(180)
        self.setMouseTracking(True)
        self.note_counts = {}
        self.min_playable = 48
        self.max_playable = 83
        self.playable_pitches = set(range(48, 84))
        self.hovered_note = None

    def set_data(self, note_counts, min_playable, max_playable, playable_pitches=None):
        self.note_counts = note_counts
        self.min_playable = min_playable
        self.max_playable = max_playable
        if playable_pitches is None:
            self.playable_pitches = set(range(min_playable, max_playable + 1))
        else:
            self.playable_pitches = set(playable_pitches)
        self.hovered_note = None
        self.update()

    def _is_note_playable(self, note):
        return note in self.playable_pitches

    def mouseMoveEvent(self, event):
        if not self.note_counts:
            return

        w = self.width()
        min_note = min(35, min(self.note_counts.keys()))
        max_note = max(90, max(self.note_counts.keys()))
        note_range = max_note - min_note + 1
        spacing = (w - 20) / note_range

        x = event.position().x()
        if 10 <= x <= w - 10:
            note_idx = round((x - 10) / spacing)
            hovered = min_note + note_idx
            if hovered != self.hovered_note:
                self.hovered_note = hovered
                self.update()
        else:
            if self.hovered_note is not None:
                self.hovered_note = None
                self.update()

    def leaveEvent(self, event):
        self.hovered_note = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height() - 30  # Leave space for rotated text

        # Background line
        painter.setPen(QPen(QColor(200, 200, 200, 150), 1))
        painter.drawLine(0, h, w, h)

        if not self.note_counts:
            return

        min_note = min(35, min(self.note_counts.keys()))
        max_note = max(90, max(self.note_counts.keys()))

        note_range = max_note - min_note + 1

        max_count = max(self.note_counts.values()) if self.note_counts else 1
        if max_count == 0:
            max_count = 1

        spacing = (w - 20) / note_range
        bar_width = max(3.0, spacing * 0.5)

        for i, note in enumerate(range(min_note, max_note + 1)):
            count = self.note_counts.get(note, 0)
            is_playable = self._is_note_playable(note)
            color = QColor(33, 150, 243) if is_playable else QColor(255, 17, 17)

            x = 10 + i * spacing
            if count > 0:
                min_bar_h = max(8.0, bar_width)
                bar_h = max(min_bar_h, (count / max_count) * (h - 20))
                y_bottom = h - bar_width / 2
                y_top = h - bar_h + bar_width / 2

                pen = QPen(color, bar_width, Qt.SolidLine, Qt.RoundCap)
                painter.setPen(pen)
                painter.drawLine(int(x), int(y_bottom), int(x), int(y_top))

            # Draw x-axis labels
            if note % 5 == 0:
                painter.save()
                painter.translate(x, h + 15)
                painter.rotate(45)
                painter.setPen(QPen(QColor(100, 100, 100)))
                painter.setFont(QFont("Arial", 8))
                painter.drawText(0, 0, str(note))
                painter.restore()

        # Draw tooltip
        if self.hovered_note is not None and min_note <= self.hovered_note <= max_note:
            self._draw_tooltip(painter, min_note, spacing, h)

    def _draw_tooltip(self, painter, min_note, spacing, base_h):
        note = self.hovered_note
        count = self.note_counts.get(note, 0)
        is_playable = self._is_note_playable(note)

        playable_c = count if is_playable else 0
        unplayable_c = count if not is_playable else 0

        x = 10 + (note - min_note) * spacing
        y = base_h - 40  # Float above the line

        box_w = 120
        box_h = 80
        box_x = x - box_w / 2
        box_y = y - box_h

        # Keep tooltip in bounds
        if box_x < 5:
            box_x = 5
        if box_x + box_w > self.width() - 5:
            box_x = self.width() - box_w - 5
        if box_y < 5:
            box_y = 5

        # Shadow
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 30))
        painter.drawRoundedRect(int(box_x + 2), int(box_y + 2), int(box_w), int(box_h), 8, 8)

        # Tooltip body
        painter.setBrush(QColor(245, 245, 245, 245))
        painter.setPen(QPen(QColor(220, 220, 220)))
        painter.drawRoundedRect(int(box_x), int(box_y), int(box_w), int(box_h), 8, 8)

        # Note number
        painter.setPen(QPen(QColor(0, 0, 0)))
        painter.setFont(QFont("Arial", 11, QFont.Weight.Normal))
        painter.drawText(
            int(box_x), int(box_y + 5), int(box_w), 25, Qt.AlignHCenter | Qt.AlignVCenter, str(note)
        )

        # Red dot
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 17, 17))
        painter.drawEllipse(int(box_x + 10), int(box_y + 40), 10, 10)

        # Blue dot
        painter.setBrush(QColor(33, 150, 243))
        painter.drawEllipse(int(box_x + 10), int(box_y + 60), 10, 10)

        # Texts
        painter.setPen(QPen(QColor(50, 50, 50)))
        painter.setFont(QFont("Arial", 9))
        painter.drawText(
            int(box_x + 28),
            int(box_y + 38),
            60,
            15,
            Qt.AlignLeft | Qt.AlignVCenter,
            og.app.tr("无法弹奏"),
        )
        painter.drawText(
            int(box_x + 28),
            int(box_y + 58),
            60,
            15,
            Qt.AlignLeft | Qt.AlignVCenter,
            og.app.tr("可以弹奏"),
        )

        # Counts
        painter.drawText(
            int(box_x + 85),
            int(box_y + 38),
            25,
            15,
            Qt.AlignRight | Qt.AlignVCenter,
            str(unplayable_c),
        )
        painter.drawText(
            int(box_x + 85),
            int(box_y + 58),
            25,
            15,
            Qt.AlignRight | Qt.AlignVCenter,
            str(playable_c),
        )


class KeyConfigWidget(QFrame):
    def __init__(self, default_x1, default_y1, default_x2, default_y2, parent=None):
        super().__init__(parent)
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(0, 0, 0, 0)

        # Top-Left Key Center
        self.hbox1 = QHBoxLayout()
        self.lbl_top_left = BodyLabel(og.app.tr("左上按键中心: "))
        self.lbl_x1 = BodyLabel("X1:")
        self.spn_x1 = LineEdit()
        self.spn_x1.setText(str(default_x1))
        self.spn_x1.setFixedWidth(120)

        self.lbl_y1 = BodyLabel("Y1:")
        self.spn_y1 = LineEdit()
        self.spn_y1.setText(str(default_y1))
        self.spn_y1.setFixedWidth(120)

        self.hbox1.addWidget(self.lbl_top_left)
        self.hbox1.addStretch()
        self.hbox1.addWidget(self.lbl_x1)
        self.hbox1.addWidget(self.spn_x1)
        self.hbox1.addSpacing(10)
        self.hbox1.addWidget(self.lbl_y1)
        self.hbox1.addWidget(self.spn_y1)

        # Bottom-Right Key Center
        self.hbox2 = QHBoxLayout()
        self.lbl_bottom_right = BodyLabel(og.app.tr("右下按键中心: "))
        self.lbl_x2 = BodyLabel("X2:")
        self.spn_x2 = LineEdit()
        self.spn_x2.setText(str(default_x2))
        self.spn_x2.setFixedWidth(120)

        self.lbl_y2 = BodyLabel("Y2:")
        self.spn_y2 = LineEdit()
        self.spn_y2.setText(str(default_y2))
        self.spn_y2.setFixedWidth(120)

        self.hbox2.addWidget(self.lbl_bottom_right)
        self.hbox2.addStretch()
        self.hbox2.addWidget(self.lbl_x2)
        self.hbox2.addWidget(self.spn_x2)
        self.hbox2.addSpacing(10)
        self.hbox2.addWidget(self.lbl_y2)
        self.hbox2.addWidget(self.spn_y2)

        self.vbox.addLayout(self.hbox1)
        self.vbox.addLayout(self.hbox2)

    def get_coords(self):
        try:
            return (
                float(self.spn_x1.text()),
                float(self.spn_y1.text()),
                float(self.spn_x2.text()),
                float(self.spn_y2.text()),
            )
        except ValueError:
            return (0.0, 0.0, 0.0, 0.0)


class CollapsibleSection(ExpandGroupSettingCard):
    toggled = Signal(str, bool)

    def __init__(self, section_key, title, content, collapsed=False, parent=None):
        self._initializing_expand_state = True
        icons = {
            "playback_settings": FluentIcon.SETTING,
            "track_selection": FluentIcon.ALIGNMENT,
            "pitch_analysis": FluentSystemIcon.MUSIC_NOTE,
            "key_config": FluentIcon.FIT_PAGE,
            "calibration_tools": FluentIcon.DEVELOPER_TOOLS,
        }
        icon = icons.get(section_key, FluentIcon.SETTING)
        super().__init__(icon, title, "", parent)

        self.section_key = section_key
        self.addGroupWidget(content)
        self.setExpand(not collapsed)
        self._initializing_expand_state = False
        self.request_adjust_view_size()

    def setExpand(self, isExpand: bool):
        old_value = getattr(self, "isExpand", None)
        super().setExpand(isExpand)
        if old_value != isExpand and not getattr(self, "_initializing_expand_state", False):
            self.toggled.emit(self.section_key, not isExpand)

    def request_adjust_view_size(self):
        QTimer.singleShot(50, self._adjustViewSize)

    def showEvent(self, event):
        super().showEvent(event)
        self.request_adjust_view_size()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.oldSize().isValid() and e.size().width() == e.oldSize().width():
            return
        self.request_adjust_view_size()

    def _adjustViewSize(self):
        # ExpandGroupSettingCard adds extra spacing per child, which leaves the
        # bottom shadow detached from the card body. Keep the exact layout height.
        h = self.viewLayout.sizeHint().height()
        if hasattr(self, "spaceWidget"):
            self.spaceWidget.setFixedHeight(h)
        if hasattr(self, "view"):
            self.view.setFixedHeight(h)
        if getattr(self, "isExpand", False):
            self.setFixedHeight(self.card.height() + h)

