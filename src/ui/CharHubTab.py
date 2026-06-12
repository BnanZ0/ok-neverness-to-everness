from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QStackedWidget, QVBoxLayout
from qfluentwidgets import FluentIcon, Pivot, isDarkTheme, qconfig

from ok import og
from ok.gui.widget.CustomTab import CustomTab
from src.char.custom.CustomCharManager import CustomCharManager
from src.ui.CharManagerTab import CharManagerTab
from src.ui.TeamManagerTab import TeamManagerTab


class CharHubTab(CustomTab):
    def __init__(self, manager: CustomCharManager = None):
        super().__init__()
        self.icon = FluentIcon.PEOPLE
        self.tr_name_tab = og.app.tr("角色中心")
        self.manager = manager or CustomCharManager()

        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.vbox.setSpacing(0)

        # Header area
        self.header_layout = QVBoxLayout()
        self.header_layout.setContentsMargins(15, 0, 15, 0)
        self.header_layout.setSpacing(0)

        self.pivot = Pivot(self)
        self.header_layout.addWidget(self.pivot, alignment=Qt.AlignmentFlag.AlignLeft)

        # Add separator line right below the Pivot
        self.separator = QFrame(self)
        self.separator.setFixedHeight(1)
        self.set_separator_color()
        self.header_layout.addWidget(self.separator)

        self.vbox.addLayout(self.header_layout)

        qconfig.themeChanged.connect(self.set_separator_color)

        self.stacked_widget = QStackedWidget(self)
        self.vbox.addWidget(self.stacked_widget)

        self.team_manager_tab = TeamManagerTab(self.manager, owner=self)
        self.char_manager_tab = CharManagerTab(owner=self)

        self.add_sub_interface(self.char_manager_tab, "CharManagerTab", self.char_manager_tab.name)
        self.add_sub_interface(self.team_manager_tab, "TeamManagerTab", self.team_manager_tab.name)

        self.stacked_widget.currentChanged.connect(self.on_current_index_changed)
        self.pivot.setCurrentItem(self.char_manager_tab.objectName())

    def add_sub_interface(self, widget, object_name, text):
        widget.setObjectName(object_name)
        self.stacked_widget.addWidget(widget)
        self.pivot.addItem(
            routeKey=object_name,
            text=text,
            onClick=lambda: self.stacked_widget.setCurrentWidget(widget),
        )

    def on_current_index_changed(self, index):
        widget = self.stacked_widget.widget(index)
        if widget:
            self.pivot.setCurrentItem(widget.objectName())

    def set_separator_color(self, theme=None):
        color = "rgba(255, 255, 255, 0.1)" if isDarkTheme() else "rgba(0, 0, 0, 0.1)"
        self.separator.setStyleSheet(f"background-color: {color}; border: none;")

    @property
    def name(self):
        return self.tr_name_tab
