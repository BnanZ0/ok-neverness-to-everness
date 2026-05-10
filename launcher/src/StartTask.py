from ok import BaseTask
import re
from qfluentwidgets import FluentIcon

class StartTask(BaseTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "启动器任务"
        self.description = "通过启动器启动游戏"
        self.icon = FluentIcon.SYNC

    def _start(self, time_out=10):
        '''点击开始'''
        if self.wait_click_ocr(match=re.compile("开始"), time_out=time_out):
            self.log_info('启动器点击开始', notify=True)
        else:
            self.log_error('启动器点击开始失败', notify=True)

    def run(self):
        '''检测更新 -> 点击开始'''
        self.log_info('启动器任务开始运行', notify=True)
        if self.wait_click_ocr(match=re.compile("更新"), after_sleep=60):
            self.log_info('启动器更新', notify=True)
            self._start()
        else:
            self.log_info('未找到更新', notify=True)
            self._start()
