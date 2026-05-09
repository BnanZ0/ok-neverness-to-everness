from ok import BaseTask
import re
from qfluentwidgets import FluentIcon

class StartTask(BaseTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "启动器任务"
        self.description = "通过启动器启动游戏"
        self.icon = FluentIcon.SYNC

    def run(self):
        self.log_info('启动器任务开始运行!', notify=True)
        if self.wait_click_ocr(match=re.compile("开始")):
            self.log_info('启动器任务运行完成!', notify=True)
        else:
            self.log_error('启动器任务运行失败!', notify=True)