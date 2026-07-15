from ok import og, relative_box
from ok.gui.Communicate import communicate
from ok.gui.widget.CustomTab import CustomTab
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QListWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FluentIcon,
    ImageLabel,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    SettingCard,
    SimpleCardWidget,
    SmoothScrollArea,
    SwitchButton,
    TitleLabel,
)

from src.gifts.GiftManager import GiftManager
from src.tasks.GiftTask import GiftTask
from src.ui.common import cv_to_pixmap
from src.ui.util import ensure_scan_capture


class GiftManagerSignals(QObject):
    capture_done = Signal(object, str, str, object)


gift_manager_signals = GiftManagerSignals()


class GiftPriorityCard(SimpleCardWidget):
    slot_clicked = Signal(int)

    def __init__(self, slot: int, image, parent=None):
        super().__init__(parent)
        self.slot = slot
        self.blocked = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumWidth(128)
        self.setFixedHeight(132)
        self.caption = BodyLabel(self)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.image = ImageLabel(self)
        self.image.setFixedSize(108, 72)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.image.setImage(
            cv_to_pixmap(image).scaled(
                104,
                72,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.set_priority(None)

    def set_priority(self, priority: int | None) -> None:
        if self.blocked:
            self.caption.setText(og.app.tr("不可赠送"))
            self.setStyleSheet(
                "GiftPriorityCard { border: 2px solid #d13438; border-radius: 8px; }"
            )
            self._position_content()
            return
        if priority is None:
            self.caption.setText(og.app.tr("不赠送"))
            self.setStyleSheet("")
        else:
            self.caption.setText(og.app.tr("优先级 {}").format(priority))
            self.setStyleSheet(
                "GiftPriorityCard { border: 2px solid #00b7c3; border-radius: 8px; }"
            )
        self._position_content()

    def set_blocked(self, blocked: bool) -> None:
        self.blocked = blocked
        self.setCursor(
            QCursor(
                Qt.CursorShape.ForbiddenCursor if blocked else Qt.CursorShape.PointingHandCursor
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_content()

    def _position_content(self) -> None:
        """Keep the gift artwork at the actual center; reserve only the bottom for its label."""
        self.image.move(
            max(0, (self.width() - self.image.width()) // 2),
            max(0, (self.height() - self.image.height()) // 2),
        )
        self.caption.adjustSize()
        self.caption.move(
            max(0, (self.width() - self.caption.width()) // 2),
            max(0, self.height() - self.caption.height() - 10),
        )

    def mouseReleaseEvent(self, e) -> None:
        clicked_here = self.rect().contains(e.position().toPoint())
        if not self.blocked and e.button() == Qt.MouseButton.LeftButton and clicked_here:
            self.slot_clicked.emit(self.slot)
        super().mouseReleaseEvent(e)


class GiftManagerTab(CustomTab):
    """A single-screen editor for captured character gifts and task controls."""

    def __init__(self):
        super().__init__()
        self.icon = FluentIcon.HEART
        self.tr_name = og.app.tr("羁遇赠礼")
        self.manager = GiftManager()
        self.current_profile_id: str | None = None
        self._loading_profile = False
        self.gift_cards: list[GiftPriorityCard] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        root.addWidget(self._build_profile_panel(), 1)
        root.addWidget(self._build_editor_panel(), 4)

        self.capture_button.clicked.connect(lambda: self._start_capture(None))
        self.recapture_button.clicked.connect(lambda: self._start_capture(self.current_profile_id))
        self.delete_button.clicked.connect(self._delete_current)
        self.start_button.clicked.connect(self._start_run)
        self.stop_button.clicked.connect(self._stop_run)
        self.profile_list.currentItemChanged.connect(self._on_profile_selected)
        self.enabled_switch.checkedChanged.connect(self._update_enabled_status)
        self.enabled_switch.checkedChanged.connect(self._save_current_options)
        self.count_combo.currentIndexChanged.connect(self._save_current_options)
        self.name_edit.editingFinished.connect(self._save_current_options)
        gift_manager_signals.capture_done.connect(self._on_capture_done)
        communicate.task.connect(self._on_framework_task_changed)
        communicate.task_done.connect(self._on_framework_task_done)

        self._refresh_profiles()
        self._refresh_task_controls()

    @property
    def name(self):
        return self.tr_name

    def _update_enabled_status(self, enabled: bool) -> None:
        self.enabled_status.setText(og.app.tr("已启用") if enabled else og.app.tr("未启用"))

    def _build_profile_panel(self) -> SimpleCardWidget:
        panel = SimpleCardWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.capture_button = PrimaryPushButton(FluentIcon.CAMERA, og.app.tr("新增角色"), panel)
        self.recapture_button = PushButton(FluentIcon.SYNC, og.app.tr("更新当前角色"), panel)
        self.delete_button = PushButton(FluentIcon.DELETE, og.app.tr("删除当前角色"), panel)
        for button in (self.capture_button, self.recapture_button, self.delete_button):
            layout.addWidget(button)

        self.profile_list = ListWidget(panel)
        layout.addWidget(self.profile_list, 1)

        self.start_button = PrimaryPushButton(FluentIcon.PLAY, og.app.tr("开始赠礼"), panel)
        self.stop_button = PushButton(FluentIcon.CLOSE, og.app.tr("停止"), panel)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        return panel

    def _build_editor_panel(self) -> QWidget:
        editor = QWidget(self)
        layout = QVBoxLayout(editor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(TitleLabel(self.tr_name, editor))

        hint = BodyLabel(
            og.app.tr("在游戏赠礼页点击{}。点击礼物卡片可设定优先级，再次点击取消。").format(
                og.app.tr("新增角色")
            ),
            editor,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        settings = QWidget(editor)
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(2)
        self.status_setting_card = SettingCard(
            FluentIcon.HEART,
            og.app.tr("赠礼状态"),
            parent=settings,
        )
        self.enabled_switch = SwitchButton(self.status_setting_card)
        self.enabled_switch.setOnText("")
        self.enabled_switch.setOffText("")
        self.enabled_status = BodyLabel(og.app.tr("未启用"), self.status_setting_card)
        self.status_setting_card.hBoxLayout.addWidget(self.enabled_switch)
        self.status_setting_card.hBoxLayout.addSpacing(8)
        self.status_setting_card.hBoxLayout.addWidget(self.enabled_status)
        self.status_setting_card.hBoxLayout.addSpacing(16)
        self.count_combo = ComboBox(settings)
        for count in range(1, 4):
            self.count_combo.addItem(str(count), userData=count)
        self.name_edit = LineEdit(settings)
        self.name_edit.setMinimumWidth(360)
        self.name_edit.setPlaceholderText(og.app.tr("角色显示名称"))
        self.name_setting_card = SettingCard(FluentIcon.EDIT, og.app.tr("名称"), parent=settings)
        self.name_setting_card.hBoxLayout.addWidget(self.name_edit)
        self.name_setting_card.hBoxLayout.addSpacing(16)
        self.count_setting_card = SettingCard(
            FluentIcon.TAG, og.app.tr("赠送次数"), parent=settings
        )
        self.count_setting_card.hBoxLayout.addWidget(self.count_combo)
        self.count_setting_card.hBoxLayout.addSpacing(16)
        settings_layout.addWidget(self.status_setting_card)
        settings_layout.addWidget(self.name_setting_card)
        settings_layout.addWidget(self.count_setting_card)
        layout.addWidget(settings)

        self.name_card = SimpleCardWidget(editor)
        name_layout = QHBoxLayout(self.name_card)
        name_layout.setContentsMargins(14, 10, 14, 10)
        self.name_preview = ImageLabel(self.name_card)
        name_layout.addWidget(BodyLabel(og.app.tr("角色名称"), self.name_card))
        name_layout.addWidget(self.name_preview, 1)
        layout.addWidget(self.name_card)

        gifts_card = SimpleCardWidget(editor)
        gifts_layout = QVBoxLayout(gifts_card)
        gifts_layout.setContentsMargins(14, 14, 14, 14)
        gifts_layout.addWidget(BodyLabel(og.app.tr("礼物优先级"), gifts_card))
        self.gift_grid_widget = QWidget(gifts_card)
        self.gift_grid = QGridLayout(self.gift_grid_widget)
        self.gift_grid.setContentsMargins(0, 4, 0, 0)
        self.gift_grid.setSpacing(10)
        self.gift_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        gift_scroll = SmoothScrollArea(gifts_card)
        gift_scroll.setWidgetResizable(True)
        gift_scroll.setWidget(self.gift_grid_widget)
        gift_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.gift_grid_widget.setStyleSheet("background: transparent;")
        gifts_layout.addWidget(gift_scroll, 1)
        layout.addWidget(gifts_card, 1)
        return editor

    def _show_error(self, title: str, content: str) -> None:
        InfoBar.error(
            title=title,
            content=content,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=4500,
            parent=self.window(),
        )

    def _gift_task(self) -> GiftTask | None:
        try:
            return self.get_task(GiftTask)
        except (AttributeError, RuntimeError):
            return None

    def _refresh_profiles(self, selected_id=None) -> None:
        selected_id = selected_id or self.current_profile_id
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for profile_id, profile in self.manager.get_profiles().items():
            item = QListWidgetItem(profile["display_name"])
            item.setData(Qt.ItemDataRole.UserRole, profile_id)
            self.profile_list.addItem(item)
            if profile_id == selected_id:
                self.profile_list.setCurrentItem(item)
        self.profile_list.blockSignals(False)
        if self.profile_list.currentItem() is None and self.profile_list.count():
            self.profile_list.setCurrentRow(0)
        current_item = self.profile_list.currentItem()
        self.current_profile_id = (
            current_item.data(Qt.ItemDataRole.UserRole) if current_item is not None else None
        )
        self._render_current()

    def _on_profile_selected(self, current, _previous) -> None:
        self.current_profile_id = (
            current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        )
        self._render_current()

    def _clear_gift_grid(self) -> None:
        self.gift_cards = []
        while self.gift_grid.count():
            item = self.gift_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _render_current(self) -> None:
        self._loading_profile = True
        self._clear_gift_grid()
        profile = (
            self.manager.get_profile(self.current_profile_id) if self.current_profile_id else None
        )
        has_profile = profile is not None
        self.recapture_button.setEnabled(has_profile)
        self.delete_button.setEnabled(has_profile)
        self.enabled_switch.setEnabled(has_profile)
        self.count_combo.setEnabled(has_profile)
        self.name_edit.setEnabled(has_profile)
        self.name_card.setVisible(has_profile)
        self.gift_grid_widget.setVisible(has_profile)
        if not profile:
            self.enabled_switch.setChecked(False)
            self._update_enabled_status(False)
            self.count_combo.setCurrentIndex(2)
            self.name_edit.clear()
            self.name_preview.clear()
            self._loading_profile = False
            return

        self.enabled_switch.setChecked(profile["enabled"])
        self._update_enabled_status(profile["enabled"])
        self.count_combo.setCurrentIndex(profile["target_count"] - 1)
        self.name_edit.setText(profile["display_name"])
        frame = self.manager.load_frame(profile)
        if frame is not None:
            height, width = frame.shape[:2]
            name_box = relative_box(width, height, *GiftTask.NAME_RATIO, name="gift_character_name")
            name_image = name_box.crop_frame(frame)
            self.name_preview.setImage(
                cv_to_pixmap(name_image).scaled(
                    300,
                    72,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            priorities = {slot: index + 1 for index, slot in enumerate(profile["selected_slots"])}
            blocked_slots = set(profile.get("blocked_slots", []))
            first_x, first_y, first_to_x, first_to_y = GiftTask.GIFT_FIRST_RATIO
            box_width = first_to_x - first_x
            box_height = first_to_y - first_y
            for index in range(GiftTask.GIFT_ROWS * GiftTask.GIFT_COLUMNS):
                row, column = divmod(index, GiftTask.GIFT_COLUMNS)
                gift_box = relative_box(
                    width,
                    height,
                    first_x + column * GiftTask.GIFT_COLUMN_STEP,
                    first_y + row * GiftTask.GIFT_ROW_STEP,
                    first_x + column * GiftTask.GIFT_COLUMN_STEP + box_width,
                    first_y + row * GiftTask.GIFT_ROW_STEP + box_height,
                    name=f"gift_slot_{index}",
                )
                card = GiftPriorityCard(
                    index,
                    gift_box.crop_frame(frame),
                    self.gift_grid_widget,
                )
                card.set_blocked(index in blocked_slots)
                card.set_priority(priorities.get(index))
                card.slot_clicked.connect(self._toggle_gift_slot)
                self.gift_cards.append(card)
                self.gift_grid.addWidget(card, index // 5, index % 5)
        self._loading_profile = False

    def _toggle_gift_slot(self, slot: int) -> None:
        if self._loading_profile or not self.current_profile_id:
            return
        profile = self.manager.get_profile(self.current_profile_id)
        if not profile:
            return
        if slot in profile.get("blocked_slots", []):
            return
        slots = list(profile["selected_slots"])
        if slot in slots:
            slots.remove(slot)
        else:
            slots.append(slot)
        self.manager.update_profile(self.current_profile_id, selected_slots=slots)
        self._render_current()

    def _save_current_options(self) -> None:
        if self._loading_profile or not self.current_profile_id:
            return
        self.manager.update_profile(
            self.current_profile_id,
            enabled=self.enabled_switch.isChecked(),
            target_count=self.count_combo.currentData(),
            display_name=self.name_edit.text(),
        )
        self._refresh_profiles(self.current_profile_id)

    def _start_capture(self, profile_id: str | None) -> None:
        self.capture_button.setEnabled(False)
        self.recapture_button.setEnabled(False)
        self._pending_recapture_id = profile_id
        og.app.start_controller.handler.post(self._capture_in_worker)

    def _capture_in_worker(self) -> None:
        error = ensure_scan_capture()
        if error:
            gift_manager_signals.capture_done.emit(None, error, "", [])
            return
        task = self._gift_task()
        if not task:
            gift_manager_signals.capture_done.emit(None, og.app.tr("赠礼任务未注册"), "", [])
            return
        frame = task.frame
        if frame is None or not getattr(frame, "size", 0):
            gift_manager_signals.capture_done.emit(None, og.app.tr("没有可用的游戏画面"), "", [])
            return
        name = og.app.tr("未命名角色")
        try:
            results = task.ocr(box=task.get_name_box(), frame=frame)
            recognized = "".join(str(result.name).strip() for result in results or [])
            if recognized:
                name = recognized
        except Exception as error:
            task.log_debug(f"gift capture name OCR failed: {type(error).__name__}")
        blocked_slots = []
        try:
            blocked_slots = [
                index
                for index, badge_box in enumerate(task.get_unlimit_gift_boxes())
                if task.find_one("unlimit_gift", box=badge_box, frame=frame)
            ]
        except Exception as error:
            task.log_debug(f"gift capture unlimited-gift detection failed: {type(error).__name__}")
        gift_manager_signals.capture_done.emit(frame, "", name, blocked_slots)

    def _on_capture_done(
        self, frame, error: str, recognized_name: str, blocked_slots: list[int]
    ) -> None:
        self.capture_button.setEnabled(True)
        self.recapture_button.setEnabled(self.current_profile_id is not None)
        if error:
            self._show_error(og.app.tr("捕获失败"), error)
            return
        profile = self.manager.get_profile(getattr(self, "_pending_recapture_id", None))
        try:
            if profile:
                self.manager.recapture_profile(
                    self._pending_recapture_id,
                    frame,
                    profile["selected_slots"],
                    profile["target_count"],
                    profile["display_name"],
                    blocked_slots=blocked_slots,
                )
                selected_id = self._pending_recapture_id
            else:
                selected_id = self.manager.create_profile(
                    recognized_name or og.app.tr("未命名角色"),
                    frame,
                    [],
                    target_count=3,
                    blocked_slots=blocked_slots,
                )
            self._refresh_profiles(selected_id)
        except Exception as error:
            self._show_error(og.app.tr("保存失败"), str(error).strip() or type(error).__name__)

    def _delete_current(self) -> None:
        if not self.current_profile_id:
            return
        self.manager.delete_profile(self.current_profile_id)
        self.current_profile_id = None
        self._refresh_profiles()

    def _start_run(self) -> None:
        if not self.manager.get_enabled_profiles():
            self._show_error(
                og.app.tr("无法开始"), og.app.tr("请先捕获、选择礼物并启用至少一个角色。")
            )
            return
        task = self._gift_task()
        if not task:
            self._show_error(og.app.tr("无法开始"), og.app.tr("赠礼任务未注册"))
            return
        og.app.start_controller.start(task)
        self._refresh_task_controls(task)

    def _stop_run(self) -> None:
        task = self._gift_task()
        if not task:
            return
        if task.executor.current_task is task:
            task.executor.stop_current_task()
        else:
            task.disable()
            task.unpause()
        self._refresh_task_controls(task)

    def _on_framework_task_changed(self, task) -> None:
        if task is None or isinstance(task, GiftTask):
            self._refresh_task_controls(task)

    def _on_framework_task_done(self, task) -> None:
        if isinstance(task, GiftTask):
            self._refresh_task_controls(task)

    def _refresh_task_controls(self, task=None) -> None:
        task = task or self._gift_task()
        if not task:
            # CustomTab receives its executor after construction. Keep Start available until then.
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            return
        active = task.running or task.enabled
        self.stop_button.setEnabled(active)
        if task.paused:
            self.start_button.setText(og.app.tr("继续赠礼"))
            self.start_button.setEnabled(True)
        else:
            self.start_button.setText(og.app.tr("开始赠礼"))
            self.start_button.setEnabled(not active)
