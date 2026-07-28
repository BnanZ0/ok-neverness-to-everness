from enum import Enum
from typing import Any

from ok import get_path_relative_to_exe, og
from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QStringListModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCompleter,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    EditableComboBox,
    FluentIcon,
    FluentIconBase,
    IconWidget,
    ListWidget,
    SearchLineEdit,
    Theme,
    getIconColor,
    isDarkTheme,
)


def get_tr(text):
    if og.app is None:
        return text
    return og.app.tr(text)


COMBO = get_tr("出招表")
TEAM_MANAGEMENT = get_tr("队伍管理")


def cv_to_pixmap(cv_img):
    if cv_img is None or getattr(cv_img, "size", 0) == 0:
        return QPixmap()
    if not cv_img.flags["C_CONTIGUOUS"]:
        cv_img = cv_img.copy()
    height, width = cv_img.shape[:2]
    channels = cv_img.shape[2] if len(cv_img.shape) > 2 else 1
    bytes_per_line = channels * width

    if channels == 3:
        qimg = QImage(
            cv_img.data, width, height, bytes_per_line, QImage.Format.Format_RGB888
        ).rgbSwapped()
    elif channels == 4:
        qimg = QImage(
            cv_img.data, width, height, bytes_per_line, QImage.Format.Format_RGBA8888
        ).rgbSwapped()
    else:
        qimg = QImage(cv_img.data, width, height, bytes_per_line, QImage.Format.Format_Grayscale8)

    return QPixmap.fromImage(qimg)


class CharManagerSignals(QObject):
    refresh_tab = Signal()


char_manager_signals = CharManagerSignals()


class BorderCardWidget(CardWidget):
    """A Fluent card widget with adjustable border width and color."""

    def __init__(self, parent=None, border_width: float = 1.0, border_color=None):
        super().__init__(parent)
        self._border_width = max(0.0, border_width)
        self._border_color = None
        self.setBorderColor(border_color)

    def borderWidth(self) -> float:
        return self._border_width

    def setBorderWidth(self, width: float):
        """Set the border width in device-independent pixels."""
        width = max(0.0, width)
        if self._border_width != width:
            self._border_width = width
            self.update()

    def borderColor(self) -> QColor | None:
        return QColor(self._border_color) if self._border_color is not None else None

    def setBorderColor(self, color):
        """Set a solid border color, or ``None`` to use the Fluent default."""
        border_color = None if color is None else QColor(color)
        if border_color is not None and not border_color.isValid():
            raise ValueError(f"Invalid border color: {color!r}")
        if self._border_color != border_color:
            self._border_color = border_color
            self.update()

    def paintEvent(self, e):
        if self._border_width == 1 and self._border_color is None:
            super().paintEvent(e)
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        r = self.borderRadius
        d = 2 * r
        border_width = min(self._border_width, w, h)
        is_dark = isDarkTheme()

        # draw top border
        top_border_color = QColor(0, 0, 0, 20)
        if is_dark:
            if self.isPressed:
                top_border_color = QColor(255, 255, 255, 18)
            elif self.isHover:
                top_border_color = QColor(255, 255, 255, 13)
        else:
            top_border_color = QColor(0, 0, 0, 15)

        # draw bottom border
        bottom_border_color = top_border_color
        if not is_dark and self.isHover and not self.isPressed:
            bottom_border_color = QColor(0, 0, 0, 27)

        if self._border_color is not None:
            top_border_color = bottom_border_color = self._border_color

        if border_width > 1:
            inset = border_width / 2
            r = max(0, min(r, w / 2, h / 2) - inset)
            d = 2 * r
            left, top = inset, inset
            right, bottom = w - inset, h - inset

            path = QPainterPath()
            path.arcMoveTo(left, bottom - d, d, d, 225)
            path.arcTo(left, bottom - d, d, d, 225, -60)
            path.lineTo(left, top + r)
            path.arcTo(left, top, d, d, -180, -90)
            path.lineTo(right - r, top)
            path.arcTo(right - d, top, d, d, 90, -90)
            path.lineTo(right, bottom - r)
            path.arcTo(right - d, bottom - d, d, d, 0, -45)
            pen = QPen(top_border_color, border_width)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.strokePath(path, pen)

            path = QPainterPath()
            path.arcMoveTo(left, bottom - d, d, d, 225)
            path.arcTo(left, bottom - d, d, d, 225, 45)
            path.lineTo(right - r, bottom)
            path.arcTo(right - d, bottom - d, d, d, 270, 45)
            pen = QPen(bottom_border_color, border_width)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.strokePath(path, pen)
        elif border_width > 0:
            path = QPainterPath()
            path.arcMoveTo(1, h - d - 1, d, d, 240)
            path.arcTo(1, h - d - 1, d, d, 225, -60)
            path.lineTo(1, r)
            path.arcTo(1, 1, d, d, -180, -90)
            path.lineTo(w - r, 1)
            path.arcTo(w - d - 1, 1, d, d, 90, -90)
            path.lineTo(w - 1, h - r)
            path.arcTo(w - d - 1, h - d - 1, d, d, 0, -60)
            painter.strokePath(path, top_border_color)

            path = QPainterPath()
            path.arcMoveTo(1, h - d - 1, d, d, 240)
            path.arcTo(1, h - d - 1, d, d, 240, 30)
            path.lineTo(w - r - 1, h - 1)
            path.arcTo(w - d - 1, h - d - 1, d, d, 270, 30)
            painter.strokePath(path, bottom_border_color)

        # draw background
        painter.setPen(Qt.NoPen)
        if border_width > 1:
            inset = border_width / 2
            rect = self.rect().adjusted(inset, inset, -inset, -inset)
            painter.setBrush(self.backgroundColor)
            painter.drawRoundedRect(rect, r, r)
        else:
            rect = self.rect().adjusted(1, 1, -1, -1)
            painter.setBrush(self.backgroundColor)
            painter.drawRoundedRect(rect, r, r)


class SearchableComboBox(EditableComboBox):
    """
    基于 PySide6 的可搜寻下拉框
    继承自 EditableComboBox，实现输入关键字自动过滤清单范围
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.search_items = []
        self._setup_search_engine()

    def _setup_search_engine(self):
        completer = QCompleter(self.search_items)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.setCompleter(completer)

    def addItem(
        self, text: str, icon: QIcon | str | FluentIconBase | None = None, userData: Any = None
    ):
        """重写以同步更新搜寻清单"""
        super().addItem(text, icon, userData)
        self.search_items.append(text)
        self._sync_completer_model()

    def _sync_completer_model(self):
        """同步内部资料模型至补全器"""
        completer = self.completer()
        model = QStringListModel(self.search_items, completer)
        completer.setModel(model)

    def clear(self):
        """清空时同步重置搜寻引擎"""
        super().clear()
        self.search_items.clear()
        self._sync_completer_model()


class SearchableListWidget(QWidget):
    """
    可搜索的列表控件，包含搜索框和列表
    利用 __getattr__ 自动转发方法，免去写大量包装方法的烦恼。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 创建布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 搜索框
        self.search_edit = SearchLineEdit(self)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_edit)

        # 列表
        self.list_widget = ListWidget(self)
        layout.addWidget(self.list_widget)

        self.setLayout(layout)

    def setPlaceholderText(self, text: str):
        """特例：搜索框的方法需要保留在这里"""
        self.search_edit.setPlaceholderText(text)

    def setFixedWidth(self, width: int):
        """特例：需要同时作用于两个子控件的方法"""
        super().setFixedWidth(width)  # 设置自身的宽度
        self.list_widget.setFixedWidth(width)
        self.search_edit.setFixedWidth(width)

    def _apply_filter(self, keyword: str):
        """
        更优的过滤方式：隐藏/显示 Item，而不是清空重建。
        这样即使 Item 包含 Icon 或复杂的 user_data 也不会丢失。
        """
        normalized = keyword.strip().lower()

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            # 如果关键字在文本中，hidden 为 False（显示）；否则为 True（隐藏）
            should_hide = normalized not in item.text().lower()
            item.setHidden(should_hide)

    def reapply_filter(self):
        self._apply_filter(self.search_edit.text())

    def __getattr__(self, name):
        if hasattr(self.list_widget, name):
            return getattr(self.list_widget, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")


class SmoothSearchBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(35)
        self.setLayout(QHBoxLayout(self))
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().setSpacing(0)

        # 1. 使用 IconWidget 代替 ToolButton
        # IconWidget 看起来就是一个纯粹的图标，没有背景色，不会有禁用变暗的问题
        self.icon_label = IconWidget(FluentIcon.SEARCH, self)
        self.icon_label.setFixedSize(15, 15)

        # 2. 搜索框
        self.search_edit = SearchLineEdit(self)
        self.search_edit.setFixedWidth(0)  # 初始宽度为0

        self.layout().addWidget(self.search_edit)
        self.layout().addWidget(self.icon_label)

        # 安装事件过滤器，让整个容器响应鼠标悬停
        self.setMouseTracking(True)

        self.icon_label_anim = QPropertyAnimation(self.icon_label, b"maximumWidth")
        self.icon_label_anim.finished.connect(self._on_icon_anim_finished)

        self.should_hide_icon = False
        self.textChanged = self.search_edit.textChanged

    def _on_icon_anim_finished(self):
        # 2. 只有当锁打开时才执行 hide
        if self.should_hide_icon:
            self.icon_label.hide()

    def enterEvent(self, event):
        if self.search_edit.text():
            super().enterEvent(event)
            return

        self.should_hide_icon = True  # 开启隐藏锁

        # 停止动画并设置参数
        self.icon_label_anim.stop()
        self.icon_label_anim.setDuration(100)
        self.icon_label_anim.setStartValue(self.icon_label.width())
        self.icon_label_anim.setEndValue(0)

        # 3. 准备搜索框动画
        self.anim = QPropertyAnimation(self.search_edit, b"maximumWidth")
        self.anim.setDuration(300)
        self.anim.setStartValue(self.search_edit.width())
        self.anim.setEndValue(220)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.icon_label_anim.start()
        self.anim.start()
        self.search_edit.setFocus()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.search_edit.text():
            self.should_hide_icon = False

            # 停止并清理之前的连接
            if hasattr(self, "anim"):
                self.anim.stop()
            if hasattr(self, "icon_label_anim"):
                self.icon_label_anim.stop()

            # 搜索框收起
            self.anim = QPropertyAnimation(self.search_edit, b"maximumWidth")
            self.anim.setDuration(300)
            self.anim.setStartValue(self.search_edit.width())
            self.anim.setEndValue(0)
            self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)

            # 图标重现
            self.icon_label.show()
            self.icon_label.setMaximumWidth(15)

            self.anim.start()
            self.search_edit.clearFocus()

        super().leaveEvent(event)


class FluentSystemIcon(FluentIconBase, Enum):
    """Custom icons"""

    MUSIC_NOTE = "MusicNote1"
    NEXT = "Next"
    PREVIOUS = "Previous"
    HEART_FILL = "HeartFill"

    def path(self, theme=Theme.AUTO):
        path = get_path_relative_to_exe(
            "assets", "fluenticons", f"{self.value}_{getIconColor(theme)}.svg"
        )
        return path or ""
