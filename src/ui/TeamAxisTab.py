from ok import og
from ok.gui.widget.CustomTab import CustomTab
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TextEdit,
)

from src.char.custom.CustomCharManager import CustomCharManager
from src.team_axis import CustomTeamAxis, get_axis_class, get_axis_classes
from src.ui.common import SmoothSearchBar, char_manager_signals


class TeamAxisSlotCard(CardWidget):
    """Read-only summary of one configured fixed-team slot."""

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(14, 14, 14, 14)
        self.vbox.setSpacing(8)

        self.title = SubtitleLabel(og.app.tr("{} 号位").format(index + 1), self)
        self.char_name = BodyLabel("-", self)
        self.combo_name = BodyLabel("-", self)
        self.char_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.combo_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.combo_name.setWordWrap(True)

        self.vbox.addWidget(self.title, alignment=Qt.AlignmentFlag.AlignCenter)
        self.vbox.addWidget(self.char_name)
        self.vbox.addWidget(self.combo_name)
        self.setMinimumHeight(120)

    def set_slot(self, char_name: str, combo_label: str):
        self.char_name.setText(char_name or "-")
        self.combo_name.setText(combo_label or "-")


class TeamAxisTab(CustomTab):
    """Configure built-in or user-authored fixed rotations for the current fixed team."""

    def __init__(self, manager: CustomCharManager | None = None, owner=None):
        super().__init__()
        self.owner = owner
        self.manager = manager or CustomCharManager()
        self.icon = FluentIcon.SYNC
        self.tr_name_tab = og.app.tr("固定轴")
        self.tr_invalid_title = og.app.tr("固定轴语法错误")
        self.tr_save_success = og.app.tr("保存成功")
        self.tr_delete_success = og.app.tr("删除成功")
        self.tr_no_match_cmd = og.app.tr("没有找到匹配的指令。")
        self._doc_text = ""

        self.vbox = self.vBoxLayout
        self.vbox.setContentsMargins(20, 20, 20, 20)
        self.vbox.setSpacing(20)

        self._build_status_card()
        self._build_team_card()
        self._build_axis_card()
        self._build_doc_card()
        self.vbox.addStretch(1)

        char_manager_signals.refresh_tab.connect(self.refresh_state)
        self.reload_axis_options()
        self.refresh_state()

    @property
    def name(self) -> str:
        return self.tr_name_tab

    @staticmethod
    def is_custom_axis_id(axis_id: str) -> bool:
        return str(axis_id or "").startswith(CustomCharManager.CUSTOM_TEAM_AXIS_PREFIX)

    def _build_status_card(self):
        self.status_card = CardWidget(self.view)
        layout = QVBoxLayout(self.status_card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        self.title = SubtitleLabel(og.app.tr("固定队伍的固定轴"), self)
        self.status = BodyLabel("", self)
        self.status.setWordWrap(True)
        self.summary = BodyLabel(
            og.app.tr(
                "启用后，命中的固定轴将完全接管自动战斗的出招和切人顺序。\n"
                "当前队伍不匹配时会自动回退到普通战斗逻辑。"
            ),
            self,
        )
        self.summary.setWordWrap(True)

        layout.addWidget(self.title)
        layout.addWidget(self.status)
        layout.addWidget(self.summary)
        self.vbox.addWidget(self.status_card)

    def _build_team_card(self):
        self.team_card = CardWidget(self.view)
        layout = QVBoxLayout(self.team_card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(SubtitleLabel(og.app.tr("当前固定队伍"), self))
        slots_layout = QHBoxLayout()
        slots_layout.setSpacing(12)
        self.slot_cards = []
        for index in range(4):
            card = TeamAxisSlotCard(index, self)
            self.slot_cards.append(card)
            slots_layout.addWidget(card)
        layout.addLayout(slots_layout)

        self.team_hint = BodyLabel("", self)
        self.team_hint.setWordWrap(True)
        self.team_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.team_hint)
        self.vbox.addWidget(self.team_card)

    def _build_axis_card(self):
        self.axis_card = CardWidget(self.view)
        layout = QVBoxLayout(self.axis_card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel(og.app.tr("固定轴方案"), self))
        header.addStretch(1)
        self.axis_combo = ComboBox(self)
        self.axis_combo.setMinimumWidth(300)
        self.axis_combo.currentIndexChanged.connect(self.on_axis_changed)
        header.addWidget(self.axis_combo)

        self.new_axis_btn = PushButton(og.app.tr("新建自定义轴"), self)
        self.new_axis_btn.clicked.connect(self.on_new_axis)
        header.addWidget(self.new_axis_btn)

        self.delete_axis_btn = PushButton(FluentIcon.DELETE, og.app.tr("删除"), self)
        self.delete_axis_btn.clicked.connect(self.on_delete_axis)
        header.addWidget(self.delete_axis_btn)

        self.enable_btn = PrimaryPushButton(FluentIcon.ACCEPT, og.app.tr("启用"), self)
        self.enable_btn.clicked.connect(self.on_enable)
        header.addWidget(self.enable_btn)
        self.disable_btn = PushButton(og.app.tr("停用"), self)
        self.disable_btn.clicked.connect(self.on_disable)
        header.addWidget(self.disable_btn)
        layout.addLayout(header)

        layout.addWidget(BodyLabel(og.app.tr("轴名"), self))
        self.axis_name_edit = LineEdit(self)
        self.axis_name_edit.setPlaceholderText(og.app.tr("例如：创生队循环轴"))
        layout.addWidget(self.axis_name_edit)

        layout.addWidget(BodyLabel(og.app.tr("轴简介"), self))
        self.axis_description_edit = TextEdit()
        self.axis_description_edit.setMinimumHeight(60)
        self.axis_description_edit.setMaximumHeight(100)
        layout.addWidget(self.axis_description_edit)

        layout.addWidget(BodyLabel(og.app.tr("轴内容"), self))
        self.axis_content_edit = TextEdit()
        self.axis_content_edit.setPlaceholderText(
            "p1_skill, p2_ultimate, p3_l_click(2), p4_wait(0.5)"
        )
        self.axis_content_edit.setMinimumHeight(140)
        layout.addWidget(self.axis_content_edit)

        actions = QHBoxLayout()
        self.axis_edit_hint = BodyLabel("", self)
        self.axis_edit_hint.setWordWrap(True)
        actions.addWidget(self.axis_edit_hint, 1)
        self.save_axis_btn = PrimaryPushButton(FluentIcon.SAVE, og.app.tr("保存自定义轴"), self)
        self.save_axis_btn.clicked.connect(self.on_save_axis)
        actions.addWidget(self.save_axis_btn)
        layout.addLayout(actions)

        self.vbox.addWidget(self.axis_card)

    def _build_doc_card(self):
        self.doc_card = CardWidget(self.view)
        layout = QVBoxLayout(self.doc_card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel(og.app.tr("自定义固定轴可用指令"), self))
        self.doc_search_line_edit = SmoothSearchBar()
        self.doc_search_line_edit.setMaximumWidth(200)
        self.doc_search_line_edit.textChanged.connect(self._filter_doc_commands)
        header.addWidget(self.doc_search_line_edit)
        header.addStretch(1)
        layout.addLayout(header)

        self.doc_content = TextEdit()
        self.doc_content.setReadOnly(True)
        self.doc_content.setMinimumHeight(180)
        self._doc_text = self.generate_doc()
        self.doc_content.setPlainText(self._doc_text)
        layout.addWidget(self.doc_content)
        self.vbox.addWidget(self.doc_card)

    def reload_axis_options(self, select_axis_id: str = ""):
        saved_axis_id = select_axis_id or self.manager.get_fixed_team_axis().get("axis_id", "")
        self.axis_combo.blockSignals(True)
        self.axis_combo.clear()
        for axis in get_axis_classes():
            if not axis.enabled or not axis.axis_id:
                continue
            prefix = "自定义" if self.is_custom_axis_id(axis.axis_id) else "内建"
            self.axis_combo.addItem(f"[{prefix}] {axis.name}", userData=axis.axis_id)
        if saved_axis_id:
            index = self.axis_combo.findData(saved_axis_id)
            if index >= 0:
                self.axis_combo.setCurrentIndex(index)
        self.axis_combo.blockSignals(False)
        self.update_axis_editor()

    def selected_axis_id(self) -> str:
        data = self.axis_combo.currentData()
        return str(data or "").strip()

    def fixed_team_signature(self) -> tuple[str | None, ...]:
        fixed_team = self.manager.get_fixed_team()
        return tuple(
            self.manager.get_builtin_key(slot.get("combo_ref", ""))
            for slot in fixed_team.get("slots", [])
        )

    def _fixed_team_is_usable_for_custom_axis(self) -> bool:
        signature = self.fixed_team_signature()
        fixed_team = self.manager.get_fixed_team()
        return (
            fixed_team.get("enabled", False)
            and len(signature) == 4
            and all(key is not None for key in signature)
        )

    def update_axis_editor(self):
        axis_id = self.selected_axis_id()
        axis = get_axis_class(axis_id)
        is_custom = self.is_custom_axis_id(axis_id)

        self.delete_axis_btn.setEnabled(is_custom)
        self.save_axis_btn.setEnabled(is_custom)
        self.axis_name_edit.setReadOnly(not is_custom)
        self.axis_description_edit.setReadOnly(not is_custom)
        self.axis_content_edit.setReadOnly(not is_custom)

        if axis is None:
            self.axis_name_edit.clear()
            self.axis_description_edit.clear()
            self.axis_content_edit.clear()
            self.axis_edit_hint.setText(og.app.tr("没有可用的固定轴方案。"))
            return

        self.axis_name_edit.setText(axis.name)
        self.axis_description_edit.setPlainText(axis.description)
        if is_custom:
            config = self.manager.get_custom_team_axis(axis_id) or {}
            self.axis_content_edit.setPlainText(config.get("content", ""))
            self.axis_edit_hint.setText(
                og.app.tr("自定义轴保存时会绑定到当前固定队伍的四个内置角色槽位。")
            )
        else:
            preview = "\n".join(axis.opening_steps or axis.cycle_steps)
            self.axis_content_edit.setPlainText(preview)
            self.axis_edit_hint.setText(og.app.tr("内建固定轴不可在界面中修改。"))

    def _match_state(self):
        fixed_team = self.manager.get_fixed_team()
        axis = get_axis_class(self.selected_axis_id())
        signature = self.fixed_team_signature()

        if axis is None:
            return False, og.app.tr("没有可用的固定轴方案")
        if not fixed_team.get("enabled", False):
            return False, og.app.tr("请先在“队伍管理”中启用固定队伍")
        if len(signature) != 4 or any(key is None for key in signature):
            return False, og.app.tr("固定队伍的四个槽位都必须选择内置角色代码")
        if not axis.matches_signature(signature):
            return False, og.app.tr("当前固定队伍与所选固定轴不匹配")
        return True, og.app.tr("队伍匹配，可以启用该固定轴")

    def refresh_state(self):
        fixed_team = self.manager.get_fixed_team()
        slots = fixed_team.get("slots", [])
        for index, card in enumerate(self.slot_cards):
            slot = slots[index] if index < len(slots) else {}
            combo_ref = slot.get("combo_ref", "")
            card.set_slot(
                slot.get("char_name", ""),
                self.manager.to_combo_label(combo_ref) if combo_ref else "",
            )

        if fixed_team.get("enabled", False):
            self.team_hint.setText(og.app.tr("固定队伍已启用；固定轴将按四个槽位精确匹配。"))
        else:
            self.team_hint.setText(og.app.tr("固定队伍未启用。"))

        self.update_axis_editor()
        valid, reason = self._match_state()
        saved = self.manager.get_fixed_team_axis()
        is_active = (
            valid
            and saved.get("enabled", False)
            and saved.get("axis_id", "") == self.selected_axis_id()
        )
        if is_active:
            self.status.setText(
                '<span style="color: #2ecc71;">● ' + og.app.tr("固定轴：已启用") + "</span>"
            )
            self.enable_btn.setText(og.app.tr("更新"))
        elif valid:
            self.status.setText('<span style="color: #00bcd4;">○ ' + reason + "</span>")
            self.enable_btn.setText(og.app.tr("启用"))
        else:
            self.status.setText('<span style="color: #e67e22;">○ ' + reason + "</span>")
            self.enable_btn.setText(og.app.tr("启用"))

        self.enable_btn.setEnabled(valid)
        self.disable_btn.setEnabled(bool(saved.get("enabled", False)))

    def on_axis_changed(self, _index):
        self.refresh_state()

    def on_new_axis(self):
        if not self._fixed_team_is_usable_for_custom_axis():
            InfoBar.error(
                title=og.app.tr("无法新建固定轴"),
                content=og.app.tr("请先启用固定队伍，并让四个槽位都选择内置角色代码。"),
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self.window(),
            )
            return

        axis_id = self.manager.set_custom_team_axis(
            "",
            og.app.tr("新建自定义固定轴"),
            "",
            "",
            self.fixed_team_signature(),
        )
        self.reload_axis_options(axis_id)
        self.refresh_state()
        char_manager_signals.refresh_tab.emit()

    def on_save_axis(self):
        axis_id = self.selected_axis_id()
        if not self.is_custom_axis_id(axis_id):
            return

        name = self.axis_name_edit.text().strip()
        description = self.axis_description_edit.toPlainText().strip()
        content = self.axis_content_edit.toPlainText().strip()
        if not name:
            name = og.app.tr("自定义固定轴")
        if not content:
            InfoBar.error(
                title=self.tr_invalid_title,
                content=og.app.tr("轴内容不能为空。"),
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=self.window(),
            )
            return

        is_valid, error = CustomTeamAxis.validate_axis_syntax(content)
        if not is_valid:
            InfoBar.error(
                title=self.tr_invalid_title,
                content=error or "",
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=self.window(),
            )
            return

        if not self._fixed_team_is_usable_for_custom_axis():
            InfoBar.error(
                title=og.app.tr("无法保存固定轴"),
                content=og.app.tr("请先启用固定队伍，并让四个槽位都选择内置角色代码。"),
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self.window(),
            )
            return

        saved_id = self.manager.set_custom_team_axis(
            axis_id,
            name,
            description,
            content,
            self.fixed_team_signature(),
        )
        self.reload_axis_options(saved_id)
        self.refresh_state()
        InfoBar.success(
            title=self.tr_save_success,
            content=og.app.tr("自定义固定轴已保存。"),
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self.window(),
        )
        char_manager_signals.refresh_tab.emit()

    def on_delete_axis(self):
        axis_id = self.selected_axis_id()
        if not self.is_custom_axis_id(axis_id):
            return

        self.manager.delete_custom_team_axis(axis_id)
        self.reload_axis_options()
        self.refresh_state()
        InfoBar.success(
            title=self.tr_delete_success,
            content=og.app.tr("自定义固定轴已删除。"),
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self.window(),
        )
        char_manager_signals.refresh_tab.emit()

    def on_enable(self):
        valid, reason = self._match_state()
        if not valid:
            InfoBar.error(
                title=og.app.tr("无法启用固定轴"),
                content=reason,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self.window(),
            )
            return

        self.manager.set_fixed_team_axis(True, self.selected_axis_id())
        self.refresh_state()
        InfoBar.success(
            title=og.app.tr("固定轴已启用"),
            content=og.app.tr("自动战斗将在队伍精确匹配时执行该固定轴。"),
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self.window(),
        )

    def on_disable(self):
        saved = self.manager.get_fixed_team_axis()
        self.manager.set_fixed_team_axis(False, saved.get("axis_id", ""))
        self.refresh_state()
        InfoBar.success(
            title=og.app.tr("固定轴已停用"),
            content=og.app.tr("已恢复普通自动战斗逻辑。"),
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self.window(),
        )

    def generate_doc(self):
        docs = CustomTeamAxis.get_command_definitions()
        text = (
            "自定义固定轴内容使用英文逗号 [ , ] 分隔。\n"
            "p1/p2/p3/p4 分别代表固定队伍中的 1/2/3/4 号位。\n"
            "例如：p1_skill, p2_ultimate, p3_l_click(2), p4_wait(0.5)\n\n"
        )
        empty_text = "无"
        for command in docs:
            command_doc = command.doc or empty_text
            if getattr(command, "if_capable", False):
                command_doc += "（可用于 if_ 条件）"
            text += f"▶ 【 {command.name} 】\n"
            text += f"    • 参数: {command.params or empty_text}\n"
            text += f"    • 说明: {command_doc}\n"
            text += f"    • 示例: {command.example or command.name}\n\n"
        return text

    def _filter_doc_commands(self, command=""):
        filter_text = command.strip().lower()
        if not filter_text:
            self.doc_content.setPlainText(self._doc_text)
            return

        filtered_lines = []
        include_block = False
        for line in self._doc_text.splitlines():
            if line.startswith("▶"):
                include_block = filter_text in line.lower()
            if include_block:
                filtered_lines.append(line)

        self.doc_content.setPlainText("\n".join(filtered_lines) or self.tr_no_match_cmd)

    def showEvent(self, event):
        super().showEvent(event)
        self.reload_axis_options()
        self.refresh_state()
