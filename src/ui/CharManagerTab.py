import json
import platform
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import requests
from ok import og
from ok.gui.widget.CustomTab import CustomTab
from PySide6.QtCore import QEvent, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QGraphicsBlurEffect,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    FlowLayout,
    FluentIcon,
    ImageLabel,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    PrimaryToolButton,
    PushButton,
    QColor,
    SimpleCardWidget,
    SmoothScrollArea,
    SubtitleLabel,
    TextEdit,
    TitleLabel,
    TransparentToolButton,
    isDarkTheme,
)

from src.char.custom.CustomCharManager import CustomCharManager
from src.ui.common import (
    COMBO,
    TEAM_MANAGEMENT,
    SearchableComboBox,
    SearchableListWidget,
    SmoothSearchBar,
    char_manager_signals,
    cv_to_pixmap,
)


def get_builtin_prefix():
    # Backward-compatible export for modules that still import this symbol.
    return CustomCharManager.get_builtin_prefix()


def tr_fmt(text_id, **kwargs):
    t = og.app.tr(text_id)
    for k, v in kwargs.items():
        t = t.replace(f"{{{k}}}", str(v))
    return t


class CharManagerTab(CustomTab):
    doc_translation_ready = Signal(str, str)

    def __init__(self, owner=None):
        super().__init__()
        self.owner = owner
        self._executor = None
        self.tr_combo_title = COMBO
        self.tr_save_success = og.app.tr("保存成功")
        self.tr_combo_msg = tr_fmt("{combo}: {} 绑定成功", combo=COMBO)
        self.tr_del_success = og.app.tr("删除成功")
        self.tr_del_combo_msg = tr_fmt("{combo}: {} 删除成功", combo=COMBO)
        self.tr_del_char_msg = og.app.tr("已成功删除角色: {} 以及关联的特征图")
        self.tr_unbind_success = og.app.tr("解除绑定")
        self.tr_unbind_msg = tr_fmt("已解除 {} 的{combo}绑定", combo=COMBO)
        self.tr_import_data = og.app.tr("导入数据")
        self.tr_import_failed = og.app.tr("导入失败")
        self.tr_import_success = og.app.tr("导入成功")
        self.tr_import_msg = og.app.tr("已导入 {} 个文件")
        self.tr_combo_invalid_title = tr_fmt("{combo}语法错误", combo=COMBO)
        self.tr_edit_char_name = og.app.tr("编辑名称")
        self.tr_rename_failed_title = og.app.tr("重命名失败")
        self.tr_rename_failed = og.app.tr("角色名称无效或已存在")
        self.tr_rename_msg = og.app.tr("角色已重命名为: {}")

        self.tr_name = og.app.tr("角色管理")
        self.tr_choose_char = tr_fmt("请在左侧选择一个角色以管理特征和{combo}", combo=COMBO)
        self.tr_first_time_hint = tr_fmt(
            "初次使用请先至 [{team_mgmt}] 进行设置", team_mgmt=TEAM_MANAGEMENT
        )
        self.tr_delete = og.app.tr("删除")
        self.tr_unbound_text = tr_fmt(
            "当前未绑定任何{combo}。\n遇到此角色将默认使用基础通用脚本(BaseChar)。",
            combo=COMBO,
        )
        self.tr_builtin_text = og.app.tr(
            "此为内建 Python 脚本，不可在此修改。\n请在对应的源文件中直接修改代码。"
        )
        self.tr_no_match_cmd = og.app.tr("没有找到匹配的指令。")

        self.icon = FluentIcon.PEOPLE
        self.manager = CustomCharManager()
        self._doc_cache_by_locale = {}
        self._doc_cache = None
        self._pending_command = ""
        self._doc_translation_pending_locales = set()
        self._all_characters = []
        self.doc_translation_ready.connect(self._on_doc_translation_ready)
        char_manager_signals.refresh_tab.connect(self.refresh_list)

        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)  # 设置为单次触发
        self._filter_timer.timeout.connect(self._run_doc_filter)

        # main layout
        self.main_h_layout = QHBoxLayout(self)
        self.main_h_layout.setContentsMargins(0, 0, 0, 0)

        # Left side: Character list
        self.left_widget = QWidget()
        self.left_v_layout = QVBoxLayout(self.left_widget)
        self.left_v_layout.setContentsMargins(10, 10, 10, 10)

        self.char_list_widget = SearchableListWidget(self)
        self.char_list_widget.setPlaceholderText(og.app.tr("搜索角色"))
        self.char_list_widget.currentItemChanged.connect(self.on_char_selected)

        self.refresh_btn = PushButton(FluentIcon.SYNC, og.app.tr("刷新列表"), self)
        self.refresh_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.refresh_btn.clicked.connect(self.refresh_list)

        self.delete_char_btn = PushButton(FluentIcon.DELETE, og.app.tr("删除角色"), self)
        self.delete_char_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.delete_char_btn.clicked.connect(self.on_delete_char)
        self.delete_char_btn.setEnabled(False)

        self.import_btn = PushButton(FluentIcon.DOWNLOAD, self.tr_import_data, self)
        self.import_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.import_btn.clicked.connect(self.on_import_data)

        self.export_btn = PushButton(FluentIcon.SHARE, og.app.tr("导出数据"), self)
        self.export_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.export_btn.clicked.connect(self.on_export_data)

        self.left_v_layout.addWidget(self.refresh_btn)
        self.left_v_layout.addWidget(self.delete_char_btn)
        self.left_v_layout.addWidget(self.import_btn)
        self.left_v_layout.addWidget(self.export_btn)
        self.left_v_layout.addWidget(self.char_list_widget)

        # Right side: Detail View
        self.detail_widget = QWidget()
        self.detail_v_layout = QVBoxLayout(self.detail_widget)
        self.detail_v_layout.setContentsMargins(20, 20, 20, 20)

        self.title_h_layout = QHBoxLayout()

        self.char_title = TitleLabel(self.tr_choose_char)
        self.char_title.setWordWrap(True)
        self.title_h_layout.addWidget(self.char_title, 1)

        self.char_name_edit_btn = TransparentToolButton(FluentIcon.EDIT)
        self.char_name_edit_btn.setToolTip(self.tr_edit_char_name)
        self.char_name_edit_btn.clicked.connect(self.on_edit_char_name)
        self.char_name_edit_btn.hide()
        self.title_h_layout.addWidget(
            self.char_name_edit_btn,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
        )
        self.detail_v_layout.addLayout(self.title_h_layout)

        self.char_subtitle = SubtitleLabel(self.tr_first_time_hint)
        self.char_subtitle.setWordWrap(True)
        self.char_subtitle.setTextColor(QColor("#FF0000"), QColor("#FF0000"))
        self.detail_v_layout.addWidget(self.char_subtitle)

        # === 特征图区 ===
        # self.detail_v_layout.addWidget(SubtitleLabel(og.app.tr("已绑定的特征图")))

        # 1. 准备核心内容
        self.feature_grid_widget = QWidget()
        self.feature_grid_widget.installEventFilter(self)
        self.feature_grid = FlowLayout(self.feature_grid_widget)

        # 2. 准备滚动卷轴，并把内容包进去
        self.feature_scroll = SmoothScrollArea()
        self.feature_scroll.setWidgetResizable(True)
        self.feature_scroll.setWidget(self.feature_grid_widget)

        # 3. 准备最外层，并把卷轴包进去
        self.feature_scroll_card = SimpleCardWidget()
        self.feature_scroll_card.setMinimumHeight(20)
        self.feature_scroll_card.setMaximumHeight(20)
        self.feature_scroll_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self.feature_scroll_card_layout = QVBoxLayout(self.feature_scroll_card)
        self.feature_scroll_card_layout.setContentsMargins(2, 2, 2, 2)
        self.feature_scroll_card_layout.addWidget(self.feature_scroll)

        # 4. set style
        self.feature_scroll.enableTransparentBackground()

        self.detail_v_layout.addWidget(self.feature_scroll_card, stretch=3)

        # === 出招表区 ===
        self.detail_v_layout.addWidget(SubtitleLabel(COMBO))

        self.combo_h_layout = QHBoxLayout()
        self.combo_select = SearchableComboBox()
        self.combo_select.setPlaceholderText(tr_fmt("选择或输入{combo}名", combo=COMBO))
        self.combo_select.currentTextChanged.connect(self.on_combo_changed)
        self.combo_h_layout.addWidget(self.combo_select, 1)

        self.combo_unbind_btn = PushButton(FluentIcon.LINK, self.tr_unbind_success)
        self.combo_unbind_btn.clicked.connect(self.on_unbind_combo)
        self.combo_h_layout.addWidget(self.combo_unbind_btn)

        self.combo_delete_btn = PushButton(FluentIcon.DELETE, self.tr_delete)
        self.combo_delete_btn.clicked.connect(self.on_delete_combo)
        self.combo_h_layout.addWidget(self.combo_delete_btn)

        self.detail_v_layout.addLayout(self.combo_h_layout)

        self.combo_text = TextEdit()
        self.combo_text.setPlaceholderText("skill,wait(0.5),l_click(3),ultimate")
        self.combo_text.setMinimumHeight(20)
        self.combo_text.setMaximumHeight(100)
        self.detail_v_layout.addWidget(self.combo_text, 1)

        self.combo_actions_layout = QHBoxLayout()
        self.combo_actions_layout.addStretch(1)

        self.combo_test_btn = PushButton(FluentIcon.PLAY_SOLID, og.app.tr("运行一次测试"))
        self.combo_test_btn.clicked.connect(self.on_test_combo)
        self.combo_actions_layout.addWidget(self.combo_test_btn)

        self.combo_save_btn = PrimaryPushButton(FluentIcon.SAVE, og.app.tr("应用更改"))
        self.combo_save_btn.clicked.connect(self.on_save_combo)
        self.combo_actions_layout.addWidget(self.combo_save_btn)

        self.detail_v_layout.addLayout(self.combo_actions_layout)

        self.doc_h_layout = QHBoxLayout()
        self.doc_search_line_edit = SmoothSearchBar()
        self.doc_search_line_edit.setMaximumWidth(200)
        self.doc_search_line_edit.textChanged.connect(self._filter_doc_commands)
        self.doc_h_layout.addWidget(SubtitleLabel(og.app.tr("可用指令")))
        self.doc_h_layout.addWidget(self.doc_search_line_edit)
        self.doc_h_layout.addStretch(1)

        self.detail_v_layout.addLayout(self.doc_h_layout)

        self.doc_content = TextEdit()
        self.doc_content.setReadOnly(True)
        self.doc_content.setPlainText(self.generate_doc())
        self.detail_v_layout.addWidget(self.doc_content, 2)

        self.main_h_layout.addWidget(self.left_widget, 1)
        self.main_h_layout.addWidget(self.detail_widget, 4)

        self.current_char = None
        self.refresh_list()

    def eventFilter(self, watched, event: QEvent):
        if hasattr(self, "feature_grid_widget") and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._update_feature_widget_height)

        return super().eventFilter(watched, event)

    @property
    def name(self):
        return self.tr_name

    @property
    def executor(self):
        return self.owner.executor if self.owner else self._executor

    @executor.setter
    def executor(self, value):
        self._executor = value

    def refresh_list(self):
        select = self.char_list_widget.currentItem()
        select_text = select.text() if select else None
        self.current_char = None
        self._all_characters = list(self.manager.get_all_characters().keys())
        self.char_list_widget.setUpdatesEnabled(False)
        self.char_list_widget.clear()
        for name in self._all_characters:
            self.char_list_widget.addItem(name)
        self.char_list_widget.setUpdatesEnabled(True)

        # Test Code: Add dummy items
        # for i in range(20):
        #     self.char_list_widget.addItem(f"测试角色 {i}")

        if self.char_list_widget.count() != 0:
            self.char_subtitle.hide()
        else:
            self.char_subtitle.show()

        self._reload_combo_options()

        self.on_combo_changed("")

        self.delete_char_btn.setEnabled(False)
        self.char_title.setText(self.tr_choose_char)
        self.char_name_edit_btn.hide()
        for i in reversed(range(self.feature_grid.count())):
            layout_item = self.feature_grid.takeAt(i)  # 1. 从布局中取回 QLayoutItem
            if layout_item:
                layout_item.deleteLater()

        items = self.char_list_widget.findItems(select_text or "", Qt.MatchFlag.MatchExactly)
        if items:
            self.char_list_widget.setCurrentItem(items[0])
        else:
            self.char_list_widget.setCurrentItem(None)

        QTimer.singleShot(0, self._update_feature_widget_height)

    def on_export_data(self):
        downloads_path = Path.home() / "Downloads"
        base_name = "ok-nte-custom"
        extension = ".zip"
        zip_path = downloads_path / f"{base_name}{extension}"

        counter = 1
        while zip_path.exists():
            zip_path = downloads_path / f"{base_name} ({counter}){extension}"
            counter += 1

        source_dir = Path.cwd() / "custom_chars"

        if not source_dir.is_dir():
            return

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in source_dir.rglob("*"):
                if file_path.is_file():
                    zipf.write(file_path, file_path.relative_to(Path.cwd()))

        subprocess.run(f'explorer /select,"{zip_path.resolve()}"')

    def on_import_data(self):
        downloads_path = Path.home() / "Downloads"
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr_import_data, str(downloads_path), "Zip Files (*.zip)"
        )
        if not file_path:
            return

        try:
            imported = self._import_custom_data_zip(Path(file_path))
        except Exception as e:
            InfoBar.error(
                title=self.tr_import_failed,
                content=str(e),
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self.window(),
            )
            self.logger.error(str(e))
            return

        # Reload DB from disk and refresh UI
        self.manager.load_db()
        self.manager.migrate_db_schema()
        self.manager.validate_db()
        self.refresh_list()
        char_manager_signals.refresh_tab.emit()

        InfoBar.success(
            title=self.tr_import_success,
            content=self.tr_import_msg.format(imported),
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self.window(),
        )

    def _import_custom_data_zip(self, zip_path: Path) -> int:
        if not zip_path.is_file():
            raise ValueError("文件不存在")

        def norm(name: str) -> str:
            return name.replace("\\", "/").lstrip("/")

        with zipfile.ZipFile(zip_path, "r") as zipf:
            infos = [i for i in zipf.infolist() if not i.is_dir()]
            custom_infos = []
            has_db = False
            db_info = None
            for info in infos:
                name = norm(info.filename)
                if not name.startswith("custom_chars/"):
                    continue

                parts = [p for p in name.split("/") if p]
                if not parts or parts[0] != "custom_chars":
                    raise ValueError("不支持的导入格式")
                if any(p == ".." or ":" in p for p in parts):
                    raise ValueError("不安全的压缩包路径")

                if "/".join(parts) == "custom_chars/db.json":
                    has_db = True
                    db_info = info
                custom_infos.append((info, parts))

            if not has_db:
                raise ValueError("仅支持导入导出数据的 zip（缺少 custom_chars/db.json）")
            if not custom_infos:
                raise ValueError("压缩包内没有可导入的数据")

            try:
                json.loads(zipf.read(db_info).decode("utf-8"))
            except Exception:
                raise ValueError("仅支持导入导出数据的 zip（custom_chars/db.json 无效）")

            dest_root = Path.cwd().resolve()
            imported = 0
            for info, parts in custom_infos:
                target = (dest_root / Path(*parts)).resolve()
                if not target.is_relative_to(dest_root):
                    raise ValueError("不安全的压缩包路径")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipf.open(info, "r") as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                imported += 1

        return imported

    def on_char_selected(self, item):
        if not item:
            self.current_char = None
            self.char_name_edit_btn.hide()
            return
        self.current_char = item.text()
        self._render_right_panel()

    def _reload_combo_options(self):
        self.combo_select.blockSignals(True)
        self.combo_select.clear()
        for label, combo_ref in self.manager.get_all_combo_items():
            self.combo_select.addItem(label, user_data=combo_ref)
        self.combo_select.setCurrentIndex(-1)
        self.combo_select.blockSignals(False)

    def _resolve_combo_ref(self, text: str | None = None) -> str:
        if text is None:
            text = self.combo_select.currentText()
        text = text.strip()

        idx = self.combo_select.currentIndex()
        if idx >= 0 and text == self.combo_select.itemText(idx):
            data = self.combo_select.itemData(idx)
            if isinstance(data, str) and data:
                return data
        return self.manager.to_combo_ref(text)

    def _set_combo_selection_by_ref(self, combo_ref: str):
        combo_label = self.manager.to_combo_label(combo_ref)
        self.combo_select.blockSignals(True)
        idx = self.combo_select.findData(combo_ref)
        if idx >= 0:
            self.combo_select.setCurrentIndex(idx)
        else:
            self.combo_select.setCurrentText(combo_label)
        self.combo_select.blockSignals(False)

    def _render_right_panel(self):
        if not self.current_char:
            return
        char_info = self.manager.get_character_info(self.current_char)
        if not char_info:
            return

        self.delete_char_btn.setEnabled(True)
        self.char_title.setText(self.current_char)
        self.char_name_edit_btn.show()
        combo_ref = char_info.get("combo_ref", "")
        combo_label = self.manager.to_combo_label(combo_ref)
        self._set_combo_selection_by_ref(combo_ref)

        # Manually trigger the text change logic to ensure built-in warnings render
        self.on_combo_changed(combo_label)

        # update feature grid
        while self.feature_grid.count() > 0:
            item: FeatureCard = self.feature_grid.takeAt(0)
            if item:
                item.deleteLater()

        feature_ids = char_info.get("feature_ids", [])
        for fid in feature_ids:
            img_mat, _, _ = self.manager.load_feature_image(fid)
            if img_mat is not None:
                card = FeatureCard(fid, img_mat, self.on_delete_feature)
                self.feature_grid.addWidget(card)

        # Test Code: Add dummy items
        # for i in range(20):
        #     test_fid = f"test_feature_{i}"
        #     if img_mat is not None:
        #         card = FeatureCard(test_fid, img_mat, lambda fid: None)
        #         self.feature_grid.addWidget(card)

        QTimer.singleShot(0, self._update_feature_widget_height)

    def on_delete_feature(self, fid):
        if self.current_char:
            self.manager.remove_feature_from_character(self.current_char, fid)
            self._render_right_panel()

    def on_combo_changed(self, combo_label, combo_ref=None):
        if combo_label == "":
            self.combo_text.setText(self.tr_unbound_text)
            self.combo_text.setReadOnly(True)
            self.combo_text.setEnabled(False)
            self.combo_save_btn.setEnabled(True)
            self.combo_unbind_btn.setEnabled(False)
            self.combo_delete_btn.setEnabled(False)
            self.combo_test_btn.setEnabled(False)
            self.combo_select.setText(combo_label)
            self.combo_select.setReadOnly(False)
            self.combo_select.setCurrentIndex(-1)
            return

        if combo_ref is None:
            combo_ref = self._resolve_combo_ref(combo_label)

        is_builtin = self.manager.is_builtin_combo(combo_ref)
        if is_builtin:
            self.combo_text.setText(self.tr_builtin_text)
            self.combo_text.setReadOnly(True)
            self.combo_text.setEnabled(False)
            self.combo_save_btn.setEnabled(self.current_char is not None)
            self.combo_unbind_btn.setEnabled(self.current_char is not None)
            self.combo_delete_btn.setEnabled(False)  # Built-ins cannot be deleted
            self.combo_test_btn.setEnabled(getattr(og.app, "debug", False))
            self.combo_select.setReadOnly(False)
            return

        self.combo_text.setReadOnly(False)
        self.combo_text.setEnabled(True)
        self.combo_save_btn.setEnabled(True)
        self.combo_unbind_btn.setEnabled(self.current_char is not None)
        self.combo_delete_btn.setEnabled(True)
        self.combo_select.setReadOnly(False)

        # If the combo matches an existing one, update the text area to show its content
        combo_content = self.manager.get_combo(combo_ref)
        if combo_content:
            self.combo_text.setText(combo_content)
        else:
            self.combo_text.clear()

        # Update test button state
        self.combo_test_btn.setEnabled(True)

    def on_test_combo(self):
        combo_input = self.combo_select.currentText().strip()
        combo_ref = self._resolve_combo_ref(combo_input)
        is_builtin = self.manager.is_builtin_combo(combo_ref)

        if not is_builtin:
            combo_content = self.combo_text.toPlainText().strip()
            if not combo_content:
                return
            from src.char.custom.CustomChar import CustomChar

            is_valid, error = CustomChar.validate_combo_syntax(combo_content)
            if not is_valid:
                InfoBar.error(
                    title=self.tr_combo_invalid_title,
                    content=error or "",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3500,
                    parent=self.window(),
                )
                return
        og.app.start_controller.handler.post(self._run_combo_test)

    def _run_combo_test(self):
        og.app.start_controller.do_start()
        from src.char.CharFactory import get_char_by_name
        from src.char.custom.CustomChar import CustomChar
        from src.tasks.trigger.AutoCombatTask import AutoCombatTask

        task = self.get_task(AutoCombatTask)
        if not task:
            return

        combo_input = self.combo_select.currentText().strip()
        combo_ref = self._resolve_combo_ref(combo_input)
        test_char = get_char_by_name(
            task, index=0, char_name=self.current_char or "TEST_CHAR", combo_ref=combo_ref
        )

        if not hasattr(task, "_ocr_lock"):
            task._ocr_lock = threading.Lock()

        old_ocr = task.ocr
        old_chars = task.chars
        old_sleep = task.sleep

        def locked_ocr(*args, **kwargs):
            with task._ocr_lock:
                return old_ocr(*args, **kwargs)

        def simple_sleep(timeout):
            if timeout > 0:
                time.sleep(timeout)
            return True

        task.ocr = locked_ocr
        task.chars = [test_char]
        task.sleep = simple_sleep
        try:
            test_char.is_current_char = True
            test_char.switch_next_char = lambda *args, **kwargs: None

            if isinstance(test_char, CustomChar):
                test_char.combo_str = self.combo_text.toPlainText().strip()
                test_char._compile_combo()

            test_char.perform()
        finally:
            task.sleep = old_sleep
            task.chars = old_chars
            task.ocr = old_ocr

    def on_save_combo(self):
        combo_input = self.combo_select.currentText().strip()
        combo_content = self.combo_text.toPlainText().strip()
        combo_ref = self._resolve_combo_ref(combo_input)
        combo_label = self.manager.to_combo_label(combo_ref)

        is_builtin = self.manager.is_builtin_combo(combo_ref)

        if is_builtin and not self.current_char:
            return

        if combo_ref:
            if not is_builtin:
                from src.char.custom.CustomChar import CustomChar

                is_valid, error = CustomChar.validate_combo_syntax(combo_content)
                if not is_valid:
                    InfoBar.error(
                        title=self.tr_combo_invalid_title,
                        content=error or "",
                        orient=Qt.Orientation.Horizontal,
                        isClosable=True,
                        position=InfoBarPosition.TOP,
                        duration=3500,
                        parent=self.window(),
                    )
                    return
                self.manager.add_combo(combo_ref, combo_content)

            if self.current_char:
                self.manager.add_character(self.current_char, combo_ref)

            # update combo dropdown
            self._reload_combo_options()
            self._set_combo_selection_by_ref(combo_ref)

            InfoBar.success(
                title=self.tr_save_success,
                content=self.tr_combo_msg.format(combo_label),
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self.window(),
            )
            char_manager_signals.refresh_tab.emit()

    def on_delete_char(self):
        if not self.current_char:
            return

        char_to_delete = self.current_char
        self.manager.delete_character(char_to_delete)

        # Reset current selection and refresh UI
        self.current_char = None
        self.delete_char_btn.setEnabled(False)
        self.refresh_list()

        InfoBar.success(
            title=self.tr_del_success,
            content=self.tr_del_char_msg.format(char_to_delete),
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self.window(),
        )
        char_manager_signals.refresh_tab.emit()

    def _show_edit_dialog(self, old_name):
        w = MessageBoxBase(self)
        w.viewLayout.setSpacing(20)
        w.widget.setMinimumWidth(320)

        w.viewLayout.addWidget(SubtitleLabel(self.tr_edit_char_name, self))

        line_edit = LineEdit(w)
        line_edit.setText(old_name)
        line_edit.setClearButtonEnabled(True)

        w.viewLayout.addWidget(line_edit)

        if w.exec():
            new_name = line_edit.text()
            if new_name and new_name != old_name:
                return new_name, True
        return old_name, False

    def on_edit_char_name(self):
        if not self.current_char:
            return

        old_name = self.current_char
        new_name, ok = self._show_edit_dialog(old_name)
        if not ok:
            return

        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return

        if not self.manager.rename_character(old_name, new_name):
            InfoBar.error(
                title=self.tr_rename_failed_title,
                content=self.tr_rename_failed,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self.window(),
            )
            return

        self.refresh_list()
        items = self.char_list_widget.findItems(new_name, Qt.MatchFlag.MatchExactly)
        if items:
            self.char_list_widget.setCurrentItem(items[0])

        InfoBar.success(
            title=self.tr_save_success,
            content=self.tr_rename_msg.format(new_name),
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self.window(),
        )
        char_manager_signals.refresh_tab.emit()

    def on_unbind_combo(self):
        if not self.current_char:
            return

        self.manager.add_character(self.current_char, "")

        # 刷新列表和右侧界面
        self._render_right_panel()

        InfoBar.success(
            title=self.tr_unbind_success,
            content=self.tr_unbind_msg.format(self.current_char),
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self.window(),
        )
        char_manager_signals.refresh_tab.emit()

    def on_delete_combo(self):
        combo_label = self.combo_select.currentText().strip()
        combo_ref = self._resolve_combo_ref(combo_label)
        if not combo_ref or self.manager.is_builtin_combo(combo_ref):
            return

        self.manager.delete_combo(combo_ref)

        # 解绑所有正在使用该出招表的角色
        for c_name, c_data in self.manager.get_all_characters().items():
            if self.manager.to_combo_ref(c_data.get("combo_ref", "")) == combo_ref:
                self.manager.add_character(c_name, "")

        # 刷新出招表下拉列表
        self._reload_combo_options()

        # 刷新当前角色的内容显示
        if self.current_char:
            self._render_right_panel()
        else:
            self.on_combo_changed("")

        InfoBar.success(
            title=self.tr_del_success,
            content=self.tr_del_combo_msg.format(self.manager.to_combo_label(combo_ref)),
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self.window(),
        )
        char_manager_signals.refresh_tab.emit()

    def generate_doc(self):
        try:
            from src.char.custom.CustomChar import CustomChar

            docs = CustomChar.get_available_commands()
            text = "可以在出招表中输入以下指令 (以英文逗号 [ , ] 分隔):\n\n"
            translatable_text = text
            empty_text = "无"
            protected_literals = {}
            delimiter_literal = "[ , ]"
            delimiter_token = "__COMMA_SEPARATOR_LITERAL__"
            protected_literals[delimiter_token] = delimiter_literal
            translatable_text = translatable_text.replace(delimiter_literal, delimiter_token)
            for index, cmd in enumerate(docs):
                cmd_name = str(cmd.name)
                cmd_example = str(cmd.example or cmd_name)
                cmd_doc = str(cmd.doc or empty_text)
                if getattr(cmd, "if_capable", False):
                    cmd_doc += "（可用于 if_ 条件）"
                name_token = f"__CMD_NAME_{index}__"
                example_token = f"__CMD_EXAMPLE_{index}__"
                protected_literals[name_token] = cmd_name
                protected_literals[example_token] = cmd_example

                text += f"▶ 【 {cmd_name} 】\n"
                text += f"    • 参数: {cmd.params or empty_text}\n"
                text += f"    • 说明: {cmd_doc}\n"
                text += f"    • 示例: {cmd_example}\n\n"

                translatable_text += f"▶ 【 {name_token} 】\n"
                translatable_text += f"    • 参数: {cmd.params or empty_text}\n"
                translatable_text += f"    • 说明: {cmd_doc}\n"
                translatable_text += f"    • 示例: {example_token}\n\n"

            self._doc_cache = text
            locale_name = self._locale_name()
            if not locale_name or locale_name == "zh_CN":
                return text

            if locale_name in self._doc_cache_by_locale:
                return self._doc_cache_by_locale[locale_name]

            if locale_name not in self._doc_translation_pending_locales:
                self._doc_translation_pending_locales.add(locale_name)
                self._start_doc_translation(
                    text, translatable_text, locale_name, protected_literals
                )
            return "[Translating with Google...]\n\n" + text
        except Exception as e:
            return self.tr("生成文档失败: {}").format(e)

    def _filter_doc_commands(self, command=""):
        self._pending_command = command
        self._filter_timer.start(300)

    def _run_doc_filter(self):
        command = self._pending_command
        content = self._doc_cache_by_locale.get(self._locale_name(), self._doc_cache)
        if not isinstance(content, str) or not hasattr(self, "doc_content"):
            return

        filter_text = command.strip().lower()
        if not filter_text:
            self.doc_content.setPlainText(content)
            return

        filtered_lines = []
        include_block = False

        for line in content.splitlines():
            if line.startswith("▶"):
                include_block = filter_text in line

            if include_block:
                filtered_lines.append(line)

        self.doc_content.setPlainText("\n".join(filtered_lines) or self.tr_no_match_cmd)

    def _start_doc_translation(
        self,
        source_text: str,
        translatable_text: str,
        locale_name: str,
        protected_literals: dict[str, str],
    ):
        threading.Thread(
            target=self._translate_doc_worker,
            args=(source_text, translatable_text, locale_name, protected_literals),
            daemon=True,
        ).start()

    def _translate_doc_worker(
        self,
        source_text: str,
        translatable_text: str,
        locale_name: str,
        protected_literals: dict[str, str],
    ):
        try:
            target_lang = locale_name.replace("_", "-")
            translated_text = self._google_translate_text(translatable_text, target_lang)
            translated_text = self._restore_protected_literals(translated_text, protected_literals)
            translated_text = f"[Translated by Google]\n\n{translated_text}"
        except Exception as translate_error:
            self.logger.warning(
                f"Google translate failed for locale '{locale_name}': {translate_error}"
            )
            translated_text = (
                "[Google Translate unavailable, showing zh_CN source text]\n\n" + source_text
            )
        self.doc_translation_ready.emit(locale_name, translated_text)

    @Slot(str, str)
    def _on_doc_translation_ready(self, locale_name: str, translated_text: str):
        self._doc_translation_pending_locales.discard(locale_name)
        self._doc_cache_by_locale[locale_name] = translated_text
        if self._locale_name() == locale_name and hasattr(self, "doc_content"):
            self.doc_content.setPlainText(translated_text)

    @staticmethod
    def _locale_name() -> str:
        app = getattr(og, "app", None)
        if app and hasattr(app, "locale"):
            try:
                return app.locale.name()
            except Exception:
                return ""
        return ""

    @staticmethod
    def _google_translate_text(text: str, target_lang: str) -> str:
        os_info = platform.system()
        ua = (
            f"Mozilla/5.0 ({os_info}) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": target_lang,
                "dt": "t",
                "q": text,
            },
            headers={"User-Agent": ua},
            timeout=4,
        )
        response.raise_for_status()
        data = response.json()
        segments = data[0] if isinstance(data, list) and data else []
        translated = "".join(
            segment[0]
            for segment in segments
            if isinstance(segment, list) and segment and segment[0]
        )
        if not translated:
            raise ValueError("Google translate returned empty content")
        return translated

    @staticmethod
    def _restore_protected_literals(text: str, literals: dict[str, str]) -> str:
        restored = text
        for token, value in literals.items():
            restored = restored.replace(token, value)
        return restored

    def _update_feature_widget_height(self):
        layout = self.feature_grid_widget.layout()
        if layout.count() > 0:
            last_item = layout.itemAt(layout.count() - 1)
            h = last_item.geometry().bottom() + layout.contentsMargins().bottom()
        else:
            h = 20
        final_h = max(20, min(h + 5, 225))
        self.feature_scroll_card.setMaximumHeight(final_h)


class FeatureCard(CardWidget):
    def __init__(self, fid, img_mat, delete_callback, parent=None):
        super().__init__(parent)
        self.fid = fid
        self.delete_callback = delete_callback

        self.shadow_effect = QGraphicsDropShadowEffect(self)
        self.shadow_effect.setBlurRadius(15)
        self.shadow_effect.setOffset(4, 4)
        self.shadow_effect.setColor(QColor(0, 0, 0, 40))
        self.setGraphicsEffect(self.shadow_effect)

        # 1. 图片组件
        self.lbl = ImageLabel()
        self.lbl.setImage(
            cv_to_pixmap(img_mat).scaled(
                70,
                70,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        # 2. 布局
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self.lbl, alignment=Qt.AlignmentFlag.AlignCenter)

        # 3. 删除按钮
        self.del_btn = PrimaryToolButton(FluentIcon.CLOSE, self)
        self.del_btn.hide()
        self.del_btn.setFixedSize(30, 30)
        self.del_btn.clicked.connect(lambda: self.delete_callback(self.fid))

        # 4. 设置初始尺寸
        lbl_size = self.lbl.sizeHint()
        self.setFixedSize(lbl_size.width() + 30, lbl_size.height() + 30)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        center_x = (self.width() - self.del_btn.width()) // 2
        center_y = (self.height() - self.del_btn.height()) // 2
        self.del_btn.move(center_x, center_y)

    def enterEvent(self, e):
        blur = QGraphicsBlurEffect(self)
        blur.setBlurRadius(15)
        self.lbl.setGraphicsEffect(blur)
        self.del_btn.show()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.lbl.setGraphicsEffect(None)
        self.del_btn.hide()
        super().leaveEvent(e)

    def _normalBackgroundColor(self):
        return QColor(255, 255, 255, 25 if isDarkTheme() else 170)
