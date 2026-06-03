import threading
from typing import Any

from ok import Logger
from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget

logger = Logger.get_logger(__name__)

_dialog_dispatcher = None
_dialog_dispatcher_lock = threading.Lock()


class _DialogDispatcher(QObject):
    show_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self._dialogs = []
        self.show_requested.connect(self._show_dialog)

    @Slot(object)
    def _show_dialog(self, request: dict[str, Any]):
        event = request["event"]
        result = request["result"]
        try:
            dialog = _create_dialog(
                request["title"],
                request["content"],
                parent=request.get("parent"),
                copyable=request["copyable"],
                rich_text=request["rich_text"],
                open_external_links=request["open_external_links"],
                hide_cancel=request["hide_cancel"],
                close_delay_seconds=request["close_delay_seconds"],
            )
            self._dialogs.append(dialog)

            def on_finished(dialog_result):
                if dialog in self._dialogs:
                    self._dialogs.remove(dialog)
                result.append(dialog_result)
                event.set()

            dialog.finished.connect(on_finished)
            dialog.open()
        except Exception as e:
            logger.error("show dialog failed", e)
            event.set()


def _get_dialog_dispatcher(app: QApplication):
    global _dialog_dispatcher
    with _dialog_dispatcher_lock:
        if _dialog_dispatcher is None:
            _dialog_dispatcher = _DialogDispatcher()
            _dialog_dispatcher.moveToThread(app.thread())
        return _dialog_dispatcher


def _create_dialog(
    title: str,
    content: str,
    *,
    parent: QWidget | None = None,
    copyable: bool = True,
    rich_text: bool = True,
    open_external_links: bool = True,
    hide_cancel: bool = True,
    close_delay_seconds: int = 0,
):
    from qfluentwidgets import Dialog

    dialog = Dialog(title, "", parent)
    dialog.setContentCopyable(copyable)
    if hide_cancel:
        dialog.cancelButton.hide()
    if rich_text:
        dialog.contentLabel.setTextFormat(Qt.TextFormat.RichText)
    if open_external_links:
        dialog.contentLabel.setOpenExternalLinks(True)
        dialog.contentLabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    dialog.contentLabel.setText(content)
    _apply_close_delay(dialog, close_delay_seconds)
    return dialog


class _CloseDelayGuard(QObject):
    def __init__(self, seconds: int, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.remaining_seconds = max(0, int(seconds))
        self.can_close = self.remaining_seconds <= 0
        self.button = getattr(dialog, "yesButton", None)
        self.button_text = self.button.text() if self.button is not None else ""
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def start(self):
        if self.can_close:
            return
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        if self.button is not None:
            self.button.setEnabled(False)
            self._update_button_text()
        self.timer.start(1000)

    def eventFilter(self, obj, event):
        if not self.can_close and self._is_dialog_event(obj):
            if event.type() == QEvent.Type.Close:
                event.ignore()
                return True
            if event.type() == QEvent.Type.KeyPress and event.key() in (
                Qt.Key.Key_Escape,
                Qt.Key.Key_Enter,
                Qt.Key.Key_Return,
            ):
                event.ignore()
                return True
        return super().eventFilter(obj, event)

    def _tick(self):
        self.remaining_seconds -= 1
        if self.remaining_seconds <= 0:
            self.can_close = True
            self.timer.stop()
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            if self.button is not None:
                self.button.setEnabled(True)
                self.button.setText(self.button_text)
            return
        self._update_button_text()

    def _is_dialog_event(self, obj):
        return obj is self.dialog or (isinstance(obj, QWidget) and self.dialog.isAncestorOf(obj))

    def _update_button_text(self):
        if self.button is not None:
            self.button.setText(f"{self.button_text} ({self.remaining_seconds})")


def _apply_close_delay(dialog, seconds: int):
    seconds = max(0, int(seconds))
    if seconds <= 0:
        return
    guard = _CloseDelayGuard(seconds, dialog)
    dialog.installEventFilter(guard)
    dialog._close_delay_guard = guard
    guard.start()


def show_dialog_and_wait(
    title: str,
    content: str,
    *,
    parent: QWidget | None = None,
    copyable: bool = True,
    rich_text: bool = True,
    open_external_links: bool = True,
    hide_cancel: bool = True,
    close_delay_seconds: int = 0,
) -> int | None:
    """Show a qfluentwidgets Dialog on the GUI thread and wait until it closes."""
    app = QApplication.instance()
    if app is None or QThread.currentThread() == app.thread():
        return _create_dialog(
            title,
            content,
            parent=parent,
            copyable=copyable,
            rich_text=rich_text,
            open_external_links=open_external_links,
            hide_cancel=hide_cancel,
            close_delay_seconds=close_delay_seconds,
        ).exec()

    event = threading.Event()
    result: list[int] = []
    _get_dialog_dispatcher(app).show_requested.emit(
        {
            "title": title,
            "content": content,
            "parent": parent,
            "copyable": copyable,
            "rich_text": rich_text,
            "open_external_links": open_external_links,
            "hide_cancel": hide_cancel,
            "close_delay_seconds": close_delay_seconds,
            "event": event,
            "result": result,
        }
    )
    event.wait()
    return result[0] if result else None
