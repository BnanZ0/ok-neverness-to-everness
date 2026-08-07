import traceback
from typing import Literal

from ok import og
from ok.gui.widget.CustomTab import CustomTab
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QCheckBox, QGraphicsDropShadowEffect, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    FluentIcon,
    Flyout,
    ImageLabel,
    InfoBar,
    InfoBarIcon,
    InfoBarPosition,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TransparentToolButton,
)

from src.char.custom.CustomCharManager import CustomCharManager
from src.tasks.trigger.AutoCombatTask import AutoCombatTask
from src.ui.common import (
    COMBO,
    TEAM_MANAGEMENT,
    SearchableComboBox,
    char_manager_signals,
    cv_to_pixmap,
)
from src.ui.TeamScanner import TeamScanError, TeamScanner
from src.ui.util import tr_fmt


class TeamManagerSignals(QObject):
    scan_done = Signal(list, str)


team_manager_signals = TeamManagerSignals()


class NewCharDialog(MessageBoxBase):
    def __init__(self, mat, manager: CustomCharManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.tr_title = og.app.tr("关联特征")
        self.tr_name_ph = og.app.tr("输入或选择关联的角色名称")
        self.tr_list_ph = tr_fmt("输入或选择绑定的{combo} (可选)", combo=COMBO)

        self.viewLayout.setSpacing(10)
        self.viewLayout.addWidget(
            SubtitleLabel(self.tr_title, self), alignment=Qt.AlignmentFlag.AlignCenter
        )

        img_label = ImageLabel()
        img_label.setImage(
            cv_to_pixmap(mat).scaled(
                80,
                80,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.viewLayout.addWidget(img_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.tip_label = BodyLabel(og.app.tr("※ 列表可直接输入并创建"))
        self.viewLayout.addWidget(self.tip_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.char_combo = SearchableComboBox()
        self.char_combo.setPlaceholderText(self.tr_name_ph)
        self.char_combo.addItem("", userData="")
        for char_id, char_data in self.manager.get_all_characters().items():
            self.char_combo.addItem(char_data["char_name"], userData=char_id)
        self.char_combo.currentTextChanged.connect(self._on_char_select)
        self.viewLayout.addWidget(self.char_combo)

        self.combo_list = SearchableComboBox()
        self.combo_list.setPlaceholderText(self.tr_list_ph)
        self.combo_list.addItem("", userData="")
        for combo_name, combo_id in self.manager.get_all_impl_items(with_source_prefix=True):
            self.combo_list.addItem(combo_name, userData=combo_id)
        self.viewLayout.addWidget(self.combo_list)

        self.widget.setMinimumWidth(320)

    def _on_char_select(self, text):
        if not text:
            return
        idx = self.char_combo.findText(text)
        char_id = self.char_combo.itemData(idx) if idx >= 0 else ""
        char_info = self.manager.get_character_info_by_id(char_id)
        combo_id = char_info["impl_id"] if char_info else ""
        if combo_id:
            idx = self.combo_list.findData(combo_id)
            if idx >= 0:
                self.combo_list.setCurrentIndex(idx)
            else:
                self.combo_list.setCurrentText(
                    self.manager.get_impl_name(combo_id, with_source_prefix=True)
                )
        elif char_info:
            self.combo_list.setCurrentIndex(0)

    def get_data(self):
        char_name = self.char_combo.currentText().strip()
        idx_char = self.char_combo.findText(char_name)
        char_id = self.char_combo.itemData(idx_char) if idx_char >= 0 else ""

        combo_name = self.combo_list.currentText().strip()
        combo_id = ""
        idx = self.combo_list.currentIndex()
        if idx >= 0 and combo_name == self.combo_list.itemText(idx):
            data = self.combo_list.itemData(idx)
            if isinstance(data, str):
                combo_id = data
        if not char_name.strip():
            combo_id = ""
            combo_name = ""
            char_id = ""
        return char_name, char_id, combo_id, combo_name


class SlotCard(CardWidget):
    def __init__(self, index, manager: CustomCharManager, parent=None):
        super().__init__(parent)
        self.index = index
        self.manager = manager
        self.tr_match_success = og.app.tr("匹配成功: {}")
        self.tr_unrecognized = og.app.tr("未能识别该特征")
        self.tr_no_image = og.app.tr("无画面")
        self.tr_slot_title = og.app.tr("{} 号位")
        self.tr_scan_prompt = og.app.tr("点击上方按钮扫描...")
        self.tr_action_btn = og.app.tr("关联特征")
        self.tr_add_match_feature_btn = og.app.tr("加入特征")
        self.tr_feature_added_btn = og.app.tr("特征已加入")
        self.tr_confidence = og.app.tr("置信度: {:.2f}")

        self.shadow_effect = QGraphicsDropShadowEffect(self)
        self.shadow_effect.setBlurRadius(30)
        self.shadow_effect.setOffset(2, 2)
        self.shadow_effect.setColor(QColor(0, 0, 0, 40))
        self.setGraphicsEffect(self.shadow_effect)

        self.vbox = QVBoxLayout(self)
        self.title = SubtitleLabel(self.tr_slot_title.format(index + 1))
        self.image = ImageLabel()
        self.image.setFixedSize(120, 120)
        self.status = BodyLabel(self.tr_scan_prompt)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_act = PrimaryPushButton(self.tr_action_btn, self)
        self.btn_act.hide()

        self.vbox.addWidget(self.title, alignment=Qt.AlignmentFlag.AlignCenter)
        self.vbox.addWidget(self.image, alignment=Qt.AlignmentFlag.AlignCenter)
        self.vbox.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignCenter)
        self.vbox.addWidget(self.btn_act, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_act.clicked.connect(self.on_action)
        self.current_mat = None
        self.current_w = 0
        self.current_h = 0
        self.current_match_char_id = ""
        self.current_confidence = None

    def _status_text(self, text, confidence=None):
        if confidence is None:
            return text
        return f"{text}\n{self.tr_confidence.format(confidence)}"

    def update_result(self, mat, w, h, match_char_id, confidence=None):
        self.current_mat = mat
        self.current_w = w
        self.current_h = h
        self.current_match_char_id = match_char_id or ""
        self.current_confidence = confidence
        if mat is not None and getattr(mat, "size", 0) > 0:
            pixmap = cv_to_pixmap(mat)
            self.image.setImage(
                pixmap.scaled(
                    120,
                    120,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            empty_pixmap = QPixmap(120, 120)
            empty_pixmap.fill(Qt.GlobalColor.transparent)
            self.image.setImage(empty_pixmap)

        if match_char_id:
            char_info = self.manager.get_character_info_by_id(match_char_id)
            display_name = char_info["char_name"] if char_info else match_char_id
            self.status.setText(
                self._status_text(self.tr_match_success.format(display_name), confidence)
            )
            if confidence is not None and confidence > 0.95:
                self.btn_act.setEnabled(False)
            else:
                self.btn_act.setEnabled(True)
            self.btn_act.setText(self.tr_add_match_feature_btn)
            self.btn_act.show()
        elif mat is not None:
            self.status.setText(self._status_text(self.tr_unrecognized, confidence))
            self.btn_act.setEnabled(True)
            self.btn_act.setText(self.tr_action_btn)
            self.btn_act.show()
        else:
            self.status.setText(self.tr_no_image)
            self.btn_act.setEnabled(True)
            self.btn_act.hide()

    def on_action(self):
        if self.current_match_char_id and self.current_mat is not None:
            self.manager.add_feature_to_character(
                self.current_match_char_id,
                self.current_mat,
                width=self.current_w,
                height=self.current_h,
            )
            self.update_result(
                self.current_mat,
                self.current_w,
                self.current_h,
                self.current_match_char_id,
                self.current_confidence,
            )
            self.btn_act.setText(self.tr_feature_added_btn)
            self.btn_act.setEnabled(False)
            char_manager_signals.refresh_tab.emit()
            return

        dialog = NewCharDialog(self.current_mat, self.manager, self.window())
        if dialog.exec():
            char_name, char_id, combo_id, combo_name = dialog.get_data()
            if char_id or char_name:
                if combo_name and not combo_id:
                    combo_id = self.manager.add_combo(combo_name, "")
                if not char_id and char_name:
                    char_id = self.manager.create_character(char_name, combo_id)
                elif char_id:
                    self.manager.update_character(char_id, impl_id=combo_id)
                self.manager.add_feature_to_character(
                    char_id,
                    self.current_mat,
                    width=self.current_w,
                    height=self.current_h,
                )
                self.update_result(
                    self.current_mat,
                    self.current_w,
                    self.current_h,
                    char_id,
                    1.0,
                )
                char_manager_signals.refresh_tab.emit()


class FixedTeamSlotCard(CardWidget):
    def __init__(self, index, manager: CustomCharManager, parent=None):
        super().__init__(parent)
        self.index = index
        self.manager = manager
        self.tr_slot_title = og.app.tr("{} 号位")
        self.tr_char_ph = og.app.tr("输入或选择角色")
        self.tr_combo_ph = COMBO

        self.shadow_effect = QGraphicsDropShadowEffect(self)
        self.shadow_effect.setBlurRadius(30)
        self.shadow_effect.setOffset(2, 2)
        self.shadow_effect.setColor(QColor(0, 0, 0, 40))
        self.setGraphicsEffect(self.shadow_effect)

        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(14, 14, 14, 14)
        self.vbox.setSpacing(10)

        self.title = SubtitleLabel(self.tr_slot_title.format(index + 1))
        self.char_combo = SearchableComboBox()
        self.char_combo.setPlaceholderText(self.tr_char_ph)
        self.combo_list = SearchableComboBox()
        self.combo_list.setPlaceholderText(self.tr_combo_ph)

        self.vbox.addWidget(self.title, alignment=Qt.AlignmentFlag.AlignCenter)
        self.vbox.addWidget(self.char_combo)
        self.vbox.addWidget(self.combo_list)

        self.char_combo.currentTextChanged.connect(self._on_char_select)
        self.reload_options()

    def _resolve_combo_id(self, text: str | None = None) -> str:
        if text is None:
            text = self.combo_list.currentText()
        text = str(text or "").strip()
        idx = self.combo_list.currentIndex()
        if idx >= 0 and text == self.combo_list.itemText(idx):
            data = self.combo_list.itemData(idx)
            if isinstance(data, str):
                return data
        return ""

    def _set_combo_by_id(self, combo_id: str):
        combo_name = self.manager.get_impl_name(combo_id, with_source_prefix=True)
        idx = self.combo_list.findData(combo_id)
        if idx >= 0:
            self.combo_list.setCurrentIndex(idx)
        else:
            self.combo_list.addItem(combo_name, userData=combo_id)
            self.combo_list.setCurrentIndex(self.combo_list.count() - 1)

    def reload_options(self):
        current_char_name, current_char_id, current_combo_id, current_combo_name = self.get_data()

        self.char_combo.blockSignals(True)
        self.char_combo.clear()
        self.char_combo.addItem("", userData="")
        for char_id, char_data in self.manager.get_all_characters().items():
            self.char_combo.addItem(char_data["char_name"], userData=char_id)

        idx = self.char_combo.findData(current_char_id) if current_char_id else -1
        if idx >= 0:
            self.char_combo.setCurrentIndex(idx)
        else:
            self.char_combo.setCurrentText(current_char_name)
        self.char_combo.blockSignals(False)

        self.combo_list.blockSignals(True)
        self.combo_list.clear()
        self.combo_list.addItem("", userData="")
        for combo_name, combo_id in self.manager.get_all_impl_items(with_source_prefix=True):
            self.combo_list.addItem(combo_name, userData=combo_id)
        if current_combo_id:
            self._set_combo_by_id(current_combo_id)
        else:
            self.combo_list.setCurrentText(current_combo_name)
        self.combo_list.blockSignals(False)

    def _on_char_select(self, text):
        if not text:
            return
        idx = self.char_combo.findText(text)
        char_id = self.char_combo.itemData(idx) if idx >= 0 else ""
        char_info = self.manager.get_character_info_by_id(char_id)
        combo_id = char_info["impl_id"] if char_info else ""
        if combo_id:
            self._set_combo_by_id(combo_id)
        elif char_info:
            self.combo_list.setCurrentIndex(0)

    def set_data(self, char_id: str, combo_id: str):
        self.char_combo.blockSignals(True)
        idx = self.char_combo.findData(char_id) if char_id else -1
        if idx >= 0:
            self.char_combo.setCurrentIndex(idx)
        else:
            char_info = self.manager.get_character_info_by_id(char_id)
            if char_info:
                self.char_combo.addItem(char_info["char_name"], userData=char_id)
                self.char_combo.setCurrentIndex(self.char_combo.count() - 1)
            else:
                self.char_combo.setCurrentIndex(-1)
                self.char_combo.setCurrentText("")
        self.char_combo.blockSignals(False)

        self.combo_list.blockSignals(True)
        if combo_id:
            self._set_combo_by_id(combo_id)
        else:
            self.combo_list.setCurrentIndex(-1)
            self.combo_list.setCurrentText("")
        self.combo_list.blockSignals(False)

    def get_data(self):
        char_name = self.char_combo.currentText().strip()
        idx_char = self.char_combo.findText(char_name)
        char_id = self.char_combo.itemData(idx_char) if idx_char >= 0 else ""

        combo_name = self.combo_list.currentText().strip()
        combo_id = self._resolve_combo_id(combo_name)
        if not char_id and not char_name:
            combo_id = ""
            combo_name = ""
            char_name = ""
        return char_name, char_id, combo_id, combo_name


class TeamManagerTab(CustomTab):
    ABYSS_PRESET_OPTIONS = (
        ("team_baicang_speed", "白藏竞速队"),
        ("team_chiz", "小吱盈蓄队"),
        ("team_999night", "999夜挂机队"),
    )

    # Built-in combo_id list for each preset. Used to auto-fill slots
    # when the user selects a preset that has not been saved yet.
    PRESET_DEFAULT_COMBOS = {
        "team_baicang_speed": [
            "char_baicang",
            "char_daphneel",
            "char_hania",
            "char_sakiri",
        ],
        "team_chiz": [
            "char_chiz",
            "char_zero",
            "char_iloy",
            "char_yi",
        ],
        "team_999night": [
            "char_iloy",
            "char_mint",
            "char_zero",
            "char_shinku",
        ],
    }

    def __init__(self, manager: CustomCharManager = None, owner=None):
        super().__init__()
        self.owner = owner
        self._executor = None
        self.tr_scan_btn = og.app.tr("扫描队伍")
        self.tr_scanning = og.app.tr("扫描中...")
        self.tr_no_feature = og.app.tr("未获取到特征")
        self.tr_scan_task_missing = og.app.tr("自动战斗任务不可用")
        self.tr_name_tab = TEAM_MANAGEMENT
        self.tr_scan_desc = og.app.tr(
            "关联角色特征后，即可自动识别角色并使用绑定的出招表；"
            "游戏内换人/换队无需手动调整。\n"
            "未关联时，将使用通用脚本。"
        )
        self.tr_fixed_team_title = og.app.tr("固定队伍")
        self.tr_fixed_team_enabled = og.app.tr("已启用 {}/4")
        self.tr_fixed_team_saved = og.app.tr("已保存 {}/4")
        self.tr_fixed_team_empty = og.app.tr("未启用")
        self.tr_fill_from_scan = og.app.tr("填入扫描")
        self.tr_save_fixed_team = og.app.tr("启用")
        self.tr_update_fixed_team = og.app.tr("更新")
        self.tr_disable_fixed_team = og.app.tr("停用")
        self.tr_clear_fixed_team = og.app.tr("清空")
        self.tr_preset_placeholder = og.app.tr("选择深渊队伍")
        self.tr_save_preset = og.app.tr("保存预设")
        self.tr_arm_preset = og.app.tr("用于下一场")
        self.tr_auto_dual_team = og.app.tr("深渊自动双队")
        self.tr_preset_incomplete = og.app.tr("预设必须填写四名不同角色")
        self.tr_preset_save_failed = og.app.tr("队伍预设保存失败，请检查配置文件权限")
        self.tr_preset_arm_failed = og.app.tr("无法武装该预设，请先完整保存四名角色")
        self.tr_preset_saved = og.app.tr("队伍预设已保存")
        self.tr_preset_armed = og.app.tr("下一场已启用严格队伍校验")
        self.tr_fixed_team_status_auto = og.app.tr(
            '<span style="color: #2ecc71;">● 深渊自动双队：严格识别已启用</span>'
        )
        self.tr_fill_failed_title = og.app.tr("没有可用扫描结果")
        self.tr_fill_failed_desc = og.app.tr("先扫描并关联特征或手动填写")
        self.tr_fill_partial_title = og.app.tr("已填入扫描结果")
        self.tr_fill_partial_desc = og.app.tr("已填入 {}")
        self.tr_save_success_title = tr_fmt(
            "{fixed_team}已保存", fixed_team=self.tr_fixed_team_title
        )
        self.tr_save_success_desc = tr_fmt(
            "已启用{fixed_team}", fixed_team=self.tr_fixed_team_title
        )
        self.tr_disable_success_title = tr_fmt(
            "{fixed_team}已停用", fixed_team=self.tr_fixed_team_title
        )
        self.tr_disable_success_desc = og.app.tr("已恢复自动识别")
        self.tr_clear_success_title = tr_fmt(
            "{fixed_team}已清空", fixed_team=self.tr_fixed_team_title
        )
        self.tr_clear_success_desc = og.app.tr("已清空槽位")
        self.tr_fixed_team_desc = tr_fmt(
            "※ {fixed_team}会优先使用已填写槽位；未填写的槽位仍会自动识别。\n"
            "深渊预设需完整保存四人；点击“用于下一场”后会严格核对四个头像，"
            "不一致时不会启动自动战斗。",
            fixed_team=self.tr_fixed_team_title,
        )
        self.tr_scan_status_active = og.app.tr(
            '<span style="color: #2ecc71;">● 自动识别：已启用</span>'
        )
        self.tr_scan_status_paused = og.app.tr(
            '<span style="color: #95a5a6;">○ 自动识别：仅空槽启用</span>'
        )
        self.tr_fixed_team_status_active = tr_fmt(
            '<span style="color: #2ecc71;">● {fixed_team}：已启用 ({count}/4)</span>',
            fixed_team=self.tr_fixed_team_title,
        )
        self.tr_fixed_team_status_empty = tr_fmt(
            '<span style="color: #95a5a6;">○ {fixed_team}：已停用</span>',
            fixed_team=self.tr_fixed_team_title,
        )
        self.tr_fixed_team_status_selected = og.app.tr(
            '<span style="color: #0078d7;">● 当前预设：{name}（尚未用于下一场）</span>'
        )
        self.tr_fixed_team_status_armed = og.app.tr(
            '<span style="color: #2ecc71;">● 下一场：{name}（严格校验）</span>'
        )
        # ruff: disable[E501]
        self.tr_scan_tips = tr_fmt(
            '这是个用于向数据库关联或添加 <b style="color: #0078d7;">角色特征</b> 的工具面板。<br>'
            '点击 <b style="color: #0078d7;">{scan_team}</b> 后点击 <b style="color: #0078d7;">关联或添加</b> 特征，自动战斗时就会识别对应的角色。<br>'
            '<b style="color: #d83b01;">💡 注意：</b>此面板 <b style="color: #d83b01;">不会</b> 在进入战斗或更换阵容时实时自动刷新或同步显示, 因为这是工具面板。<br>'
            '如果不想管理 <b style="color: #0078d7;">角色特征</b>，可以直接使用 <b style="color: #0078d7;">{fixed_team}</b> 功能。',
            fixed_team=self.tr_fixed_team_title, scan_team=og.app.tr("扫描队伍")
        )
        # ruff: enable[E501]
        self.tr_fixed_team_tips = tr_fmt(
            '<b style="color: #0078d7;">角色</b> 和 '
            '<b style="color: #0078d7;">{combo}</b> '
            "支持输入并创建，也支持选择已有项。",
            combo=COMBO,
        )

        self.manager = manager or CustomCharManager()
        self.icon = FluentIcon.CAMERA
        self.last_scan_results = []
        self.logger.info("Init TeamManagerTab")

        self.vbox = self.vBoxLayout
        self.vbox.setContentsMargins(20, 20, 20, 20)
        self.vbox.setSpacing(20)

        self.scan_card = CardWidget(self.view)
        self.scan_layout = QVBoxLayout(self.scan_card)
        self.scan_layout.setContentsMargins(16, 16, 16, 16)
        self.scan_layout.setSpacing(12)

        self.scan_header = QHBoxLayout()
        self.scan_header_text = QVBoxLayout()
        self.scan_title_row = QHBoxLayout()
        self.scan_title = SubtitleLabel(self.tr_scan_btn)
        self.scan_title_row.addWidget(self.scan_title)

        self.scan_info_btn = TransparentToolButton(FluentIcon.INFO, self)
        self.scan_info_btn.clicked.connect(self.show_scan_flyout)
        self.scan_title_row.addWidget(self.scan_info_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        self.scan_title_row.addStretch(1)

        self.scan_status = BodyLabel()
        self.scan_status.setWordWrap(True)
        self.scan_header_text.addLayout(self.scan_title_row)
        self.scan_header_text.addWidget(self.scan_status)
        self.scan_header.addLayout(self.scan_header_text, 1)

        self.scan_btn = PrimaryPushButton(FluentIcon.SYNC, self.tr_scan_btn)
        self.scan_btn.clicked.connect(self.on_scan_clicked)
        self.scan_header.addWidget(self.scan_btn)
        self.scan_layout.addLayout(self.scan_header)

        self.cards_layout = QHBoxLayout()
        self.slots: list[SlotCard] = []
        for i in range(4):
            card = SlotCard(i, self.manager, self)
            self.slots.append(card)
            self.cards_layout.addWidget(card)
        self.scan_layout.addLayout(self.cards_layout)

        self.scan_desc = BodyLabel(self.tr_scan_desc)
        self.scan_desc.setWordWrap(True)
        self.scan_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scan_layout.addWidget(self.scan_desc)

        self.vbox.addWidget(self.scan_card)

        self.fixed_team_card = CardWidget(self.view)
        self.fixed_team_layout = QVBoxLayout(self.fixed_team_card)
        self.fixed_team_layout.setContentsMargins(16, 16, 16, 16)
        self.fixed_team_layout.setSpacing(12)

        self.fixed_team_header = QHBoxLayout()
        self.fixed_team_header_text = QVBoxLayout()
        self.fixed_team_title_row = QHBoxLayout()
        self.fixed_team_title = SubtitleLabel(self.tr_fixed_team_title)
        self.fixed_team_title_row.addWidget(self.fixed_team_title)

        self.fixed_team_info_btn = TransparentToolButton(FluentIcon.INFO, self)
        self.fixed_team_info_btn.clicked.connect(self.show_fixed_team_flyout)
        self.fixed_team_title_row.addWidget(
            self.fixed_team_info_btn, alignment=Qt.AlignmentFlag.AlignLeft
        )
        self.fixed_team_title_row.addStretch(1)

        self.fixed_team_status = BodyLabel(self.tr_fixed_team_empty)
        self.fixed_team_status.setWordWrap(True)
        self.fixed_team_header_text.addLayout(self.fixed_team_title_row)
        self.fixed_team_header_text.addWidget(self.fixed_team_status)
        self.fixed_team_header.addLayout(self.fixed_team_header_text, 1)

        self.fill_fixed_team_btn = PushButton(self.tr_fill_from_scan, self)
        self.fill_fixed_team_btn.clicked.connect(self.on_fill_from_scan)
        self.fixed_team_header.addWidget(self.fill_fixed_team_btn)

        self.save_fixed_team_btn = PrimaryPushButton(FluentIcon.SAVE, self.tr_save_fixed_team, self)
        self.save_fixed_team_btn.clicked.connect(self.on_save_fixed_team)
        self.fixed_team_header.addWidget(self.save_fixed_team_btn)

        self.disable_fixed_team_btn = PushButton(self.tr_disable_fixed_team, self)
        self.disable_fixed_team_btn.clicked.connect(self.on_disable_fixed_team)
        self.fixed_team_header.addWidget(self.disable_fixed_team_btn)

        self.clear_fixed_team_btn = PushButton(FluentIcon.DELETE, self.tr_clear_fixed_team, self)
        self.clear_fixed_team_btn.clicked.connect(self.on_clear_fixed_team)
        self.fixed_team_header.addWidget(self.clear_fixed_team_btn)

        self.fixed_team_layout.addLayout(self.fixed_team_header)

        self.team_preset_row = QHBoxLayout()
        self.team_preset_combo = SearchableComboBox()
        self.team_preset_combo.setPlaceholderText(self.tr_preset_placeholder)
        self.team_preset_combo.blockSignals(True)
        for preset_id, preset_name in self.ABYSS_PRESET_OPTIONS:
            self.team_preset_combo.addItem(og.app.tr(preset_name), userData=preset_id)
        self.team_preset_combo.blockSignals(False)
        self.team_preset_row.addWidget(self.team_preset_combo, 1)

        self.save_preset_btn = PushButton(FluentIcon.SAVE, self.tr_save_preset, self)
        self.save_preset_btn.clicked.connect(self.on_save_team_preset)
        self.team_preset_row.addWidget(self.save_preset_btn)

        self.arm_preset_btn = PrimaryPushButton(FluentIcon.PLAY, self.tr_arm_preset, self)
        self.arm_preset_btn.clicked.connect(self.on_arm_team_preset)
        self.team_preset_row.addWidget(self.arm_preset_btn)
        self.auto_dual_team_check = QCheckBox(self.tr_auto_dual_team, self)
        self.auto_dual_team_check.toggled.connect(self.on_auto_dual_team_toggled)
        self.team_preset_row.addWidget(self.auto_dual_team_check)
        self.fixed_team_layout.addLayout(self.team_preset_row)

        self.fixed_team_slots_layout = QHBoxLayout()
        self.fixed_team_slots: list[FixedTeamSlotCard] = []
        for i in range(4):
            card = FixedTeamSlotCard(i, self.manager, self)
            card.char_combo.currentTextChanged.connect(self.update_fixed_team_status)
            self.fixed_team_slots.append(card)
            self.fixed_team_slots_layout.addWidget(card)
        self.fixed_team_layout.addLayout(self.fixed_team_slots_layout)
        self.team_preset_combo.currentIndexChanged.connect(self.on_team_preset_selected)

        self.fixed_team_desc = BodyLabel(self.tr_fixed_team_desc)
        self.fixed_team_desc.setWordWrap(True)
        self.fixed_team_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fixed_team_layout.addWidget(self.fixed_team_desc)

        self.vbox.addWidget(self.fixed_team_card)

        self.vbox.addStretch(1)

        team_manager_signals.scan_done.connect(
            self.on_scan_done, Qt.ConnectionType.QueuedConnection
        )
        char_manager_signals.refresh_tab.connect(self.reload_fixed_team_options)
        self.refresh_fixed_team_state()

    @property
    def name(self) -> Literal["CustomTab"]:
        return self.tr_name_tab  # type: ignore

    @property
    def executor(self):
        return self.owner.executor if self.owner else self._executor

    @executor.setter
    def executor(self, value):
        self._executor = value

    def _show_bar(self, title: str, content: str, success=True):
        fn = InfoBar.success if success else InfoBar.error
        fn(
            title=title,
            content=content,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2500 if success else 3500,
            parent=self.window(),
        )

    def _collect_fixed_team_slots(self, persist=False, update_character_default=True):
        slots = []
        filled_count = 0
        for card in self.fixed_team_slots:
            char_name, char_id, combo_id, combo_name = card.get_data()
            if char_id or char_name:
                filled_count += 1
                if persist:
                    if combo_name and not combo_id:
                        combo_id = self.manager.add_combo(combo_name, "")
                    if not char_id and char_name:
                        char_id = self.manager.create_character(char_name, combo_id)
                    if char_id and update_character_default:
                        self.manager.update_character(char_id, impl_id=combo_id)
            else:
                combo_id = ""
                char_id = ""
            slots.append(
                {
                    "char_id": char_id,
                    "impl_id": combo_id,
                }
            )
        return slots, filled_count

    def reload_fixed_team_options(self):
        for card in self.fixed_team_slots:
            card.reload_options()

    def _selected_team_preset(self):
        index = self.team_preset_combo.currentIndex()
        preset_id = self.team_preset_combo.itemData(index) if index >= 0 else ""
        preset_name = self.team_preset_combo.currentText().strip()
        return str(preset_id or ""), preset_name

    def update_fixed_team_status(self):
        fixed_team = self.manager.get_fixed_team()
        enabled = fixed_team.get("enabled", False)
        active_id = fixed_team.get("active_preset_id", "")
        armed_id = fixed_team.get("armed_for_next_battle", "")
        auto_selection = fixed_team.get("selection_mode") == "auto"
        presets = fixed_team.get("presets", {})

        _, filled_count = self._collect_fixed_team_slots()

        if auto_selection:
            self.fixed_team_status.setText(self.tr_fixed_team_status_auto)
            self.scan_status.setText(self.tr_scan_status_paused)
            self.save_fixed_team_btn.setText(self.tr_update_fixed_team)
            self.disable_fixed_team_btn.setEnabled(False)
        elif armed_id and armed_id in presets:
            name = presets[armed_id].get("name", armed_id)
            self.fixed_team_status.setText(self.tr_fixed_team_status_armed.format(name=name))
            self.scan_status.setText(self.tr_scan_status_paused)
            self.save_fixed_team_btn.setText(self.tr_update_fixed_team)
            self.disable_fixed_team_btn.setEnabled(True)
        elif active_id and active_id in presets:
            name = presets[active_id].get("name", active_id)
            self.fixed_team_status.setText(self.tr_fixed_team_status_selected.format(name=name))
            self.scan_status.setText(self.tr_scan_status_active)
            self.save_fixed_team_btn.setText(self.tr_update_fixed_team)
            self.disable_fixed_team_btn.setEnabled(False)
        elif enabled and filled_count:
            status_text = self.tr_fixed_team_status_active.format(count=filled_count)
            self.fixed_team_status.setText(status_text)
            self.scan_status.setText(self.tr_scan_status_paused)
            self.save_fixed_team_btn.setText(self.tr_update_fixed_team)
            self.disable_fixed_team_btn.setEnabled(True)
        else:
            self.fixed_team_status.setText(self.tr_fixed_team_status_empty)
            self.scan_status.setText(self.tr_scan_status_active)
            self.save_fixed_team_btn.setText(self.tr_save_fixed_team)
            self.disable_fixed_team_btn.setEnabled(False)

    def refresh_fixed_team_state(self):
        fixed_team = self.manager.get_fixed_team()
        self.auto_dual_team_check.blockSignals(True)
        self.auto_dual_team_check.setChecked(fixed_team.get("selection_mode") == "auto")
        self.auto_dual_team_check.blockSignals(False)
        active_id = fixed_team.get("active_preset_id", "")
        if active_id:
            preset_index = self.team_preset_combo.findData(active_id)
            if preset_index >= 0:
                self.team_preset_combo.blockSignals(True)
                self.team_preset_combo.setCurrentIndex(preset_index)
                self.team_preset_combo.blockSignals(False)
        slots = fixed_team.get("slots", [])
        for i, card in enumerate(self.fixed_team_slots):
            slot = slots[i] if i < len(slots) else {}
            char_id = slot.get("char_id", "")
            card.set_data(char_id, slot.get("impl_id", ""))
        self.update_fixed_team_status()

    def on_auto_dual_team_toggled(self, enabled: bool):
        mode = "auto" if enabled else "manual"
        if not self.manager.set_team_selection_mode(mode):
            self.auto_dual_team_check.blockSignals(True)
            self.auto_dual_team_check.setChecked(not enabled)
            self.auto_dual_team_check.blockSignals(False)
            self._show_bar("", self.tr_preset_save_failed, success=False)
            return
        self.refresh_fixed_team_state()

    def on_team_preset_selected(self, _index=None):
        preset_id, _ = self._selected_team_preset()
        preset = self.manager.get_team_preset(preset_id)
        slots = preset.get("slots", []) if preset else []
        # If preset has not been saved yet, auto-fill from built-in combo IDs
        # by matching against characters already in the user's database.
        if not slots or not all(s.get("char_id") for s in slots):
            default_combos = self.PRESET_DEFAULT_COMBOS.get(preset_id)
            if default_combos:
                slots = self._auto_fill_slots_by_combos(default_combos)
        for index, card in enumerate(self.fixed_team_slots):
            slot = slots[index] if index < len(slots) else {}
            card.set_data(slot.get("char_id", ""), slot.get("impl_id", ""))
        self.update_fixed_team_status()

    def _auto_fill_slots_by_combos(self, combo_ids: list[str]) -> list[dict]:
        """Match built-in combo_ids to characters in the user's database.

        If a character exists with the given combo_id, use its char_id.
        If not, auto-create a placeholder character with the builtin cn_name
        so the user can scan and associate features later.  The combo_id is
        always set so the UI shows the expected combo even before scanning.
        """
        all_chars = self.manager.get_all_characters()
        # Build a map: combo_id -> char_id (first match)
        combo_to_char = {}
        for char_id, char_data in all_chars.items():
            cid = char_data.get("impl_id", "")
            if cid and cid not in combo_to_char:
                combo_to_char[cid] = char_id
        slots = []
        for combo_id in combo_ids:
            char_id = combo_to_char.get(combo_id, "")
            if not char_id and self.manager.is_builtin_impl(combo_id):
                # Auto-create a placeholder so the slot is not blank.
                # The user can scan the character later to add features.
                cn_name = self.manager.get_builtin_impl_name(combo_id)
                char_id = self.manager.create_character(cn_name, combo_id)
            slots.append({"char_id": char_id, "impl_id": combo_id})
        return slots

    def on_save_team_preset(self):
        preset_id, preset_name = self._selected_team_preset()
        slots, filled_count = self._collect_fixed_team_slots(
            persist=True,
            update_character_default=False,
        )
        char_ids = [slot.get("char_id", "") for slot in slots]
        if filled_count != 4 or not all(char_ids) or len(set(char_ids)) != 4:
            self._show_bar("", self.tr_preset_incomplete, success=False)
            return
        if not self.manager.set_team_preset(preset_id, preset_name, slots, activate=True):
            self._show_bar("", self.tr_preset_save_failed, success=False)
            return
        self.refresh_fixed_team_state()
        char_manager_signals.refresh_tab.emit()
        self._show_bar(self.tr_preset_saved, preset_name)

    def on_arm_team_preset(self):
        preset_id, preset_name = self._selected_team_preset()
        if not self.manager.arm_team_preset(preset_id):
            self._show_bar("", self.tr_preset_arm_failed, success=False)
            return
        self.refresh_fixed_team_state()
        self._show_bar(preset_name, self.tr_preset_armed)

    def on_scan_clicked(self):
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText(self.tr_scanning)
        for card in self.slots:
            card.btn_act.hide()
        og.app.start_controller.handler.post(self.scan_team)

    def scan_team(self):

        from src.ui.util import ensure_scan_capture

        error_msg = ensure_scan_capture()
        if error_msg:
            team_manager_signals.scan_done.emit([], error_msg)
            return

        task = self.get_task(AutoCombatTask)
        if not task:
            team_manager_signals.scan_done.emit([], self.tr_scan_task_missing)
            return

        results = []
        error_msg = ""
        try:
            results = TeamScanner(self.manager).scan(task)
        except TeamScanError as e:
            error_msg = og.app.tr(str(e))
        except Exception as e:
            error_msg = str(e).strip() or e.__class__.__name__
            self.logger.error(f"扫描失败: {error_msg}\n{traceback.format_exc()}")
        finally:
            team_manager_signals.scan_done.emit(results, error_msg)

    def on_fill_from_scan(self):
        if not self.last_scan_results:
            self._show_bar(self.tr_fill_failed_title, self.tr_fill_failed_desc, success=False)
            return

        filled_count = 0
        for result in self.last_scan_results:
            idx = result.get("index")
            match_char_id = result.get("match")
            if not (0 <= idx < 4) or not match_char_id:
                continue
            char_info = self.manager.get_character_info_by_id(match_char_id)
            combo_id = char_info["impl_id"] if char_info else ""
            self.fixed_team_slots[idx].set_data(match_char_id, combo_id)
            filled_count += 1

        if filled_count == 0:
            self._show_bar(self.tr_fill_failed_title, self.tr_fill_failed_desc, success=False)
            return

        self._show_bar(self.tr_fill_partial_title, self.tr_fill_partial_desc.format(filled_count))

    def on_save_fixed_team(self):
        slots, filled_count = self._collect_fixed_team_slots(persist=True)
        if filled_count == 0:
            saved = self.manager.clear_fixed_team()
            if not saved:
                self._show_bar("", self.tr_preset_save_failed, success=False)
                return
            self.refresh_fixed_team_state()
            char_manager_signals.refresh_tab.emit()
            self._show_bar(self.tr_clear_success_title, self.tr_clear_success_desc)
        else:
            saved = self.manager.set_fixed_team(True, slots)
            if not saved:
                self._show_bar("", self.tr_preset_save_failed, success=False)
                return
            self.refresh_fixed_team_state()
            char_manager_signals.refresh_tab.emit()
            self._show_bar(self.tr_save_success_title, self.tr_save_success_desc)

    def on_disable_fixed_team(self):
        fixed_team = self.manager.get_fixed_team()
        if not self.manager.set_fixed_team(False, fixed_team.get("slots", [])):
            self._show_bar("", self.tr_preset_save_failed, success=False)
            return
        self.refresh_fixed_team_state()
        self._show_bar(self.tr_disable_success_title, self.tr_disable_success_desc)

    def on_clear_fixed_team(self):
        if not self.manager.clear_fixed_team():
            self._show_bar("", self.tr_preset_save_failed, success=False)
            return
        self.refresh_fixed_team_state()
        char_manager_signals.refresh_tab.emit()
        self._show_bar(self.tr_clear_success_title, self.tr_clear_success_desc)

    def on_scan_done(self, results, error_msg=""):
        self.last_scan_results = results or []
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText(self.tr_scan_btn)

        if error_msg:
            self._show_bar("", error_msg, success=False)
            return

        if not results:
            for card in self.slots:
                card.update_result(None, 0, 0, "")
                card.status.setText(self.tr_no_feature)
            return

        updated_indices = set()
        for res in results:
            idx = res.get("index")
            mat = res.get("mat")
            w = res.get("width", 0)
            h = res.get("height", 0)
            match_name = res.get("match")
            confidence = res.get("confidence")
            if 0 <= idx < 4:
                self.slots[idx].update_result(mat, w, h, match_name, confidence)
                updated_indices.add(idx)

        for i in range(4):
            if i not in updated_indices:
                self.slots[i].update_result(None, 0, 0, "")
                self.slots[i].status.setText(self.tr_no_feature)

    def show_scan_flyout(self):
        Flyout.create(
            icon=InfoBarIcon.INFORMATION,
            title="Tips",
            content=self.tr_scan_tips,
            target=self.scan_info_btn,
            parent=self,
            isClosable=False,
        )

    def show_fixed_team_flyout(self):
        Flyout.create(
            icon=InfoBarIcon.INFORMATION,
            title="Tips",
            content=self.tr_fixed_team_tips,
            target=self.fixed_team_info_btn,
            parent=self,
            isClosable=False,
        )
