import re
import time

from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.tasks.RecordTask import RecordTask

RECORD_INS = (
    "记录点击目标关卡的操作，分为两个步骤：\n"
    "1. 点击滚动条至目标可见 (若不需要则点击目标)\n"
    "2. 点击目标"
)


class DarkTask(NTEOneTimeTask, RecordTask):
    CONF_TIME = "循环次数(0为无限次)"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "黑暗赛车"
        self.description = "自动执行黑暗赛车,请在大世界开始执行"
        self.icon = FluentIcon.CAR
        self.default_config.update(
            {
                self.CONF_TIME: 0,
            }
        )
        self.tr(RECORD_INS)

    def run(self):
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.log_error("DarkTask error", e)
            raise

    def do_run(self):
        current_time = 0
        max_time = self.config.get(self.CONF_TIME, 0)
        running = True
        while running:
            # 判断是否达到次数
            if max_time > 0 and current_time >= max_time:
                self.log_info("达到最大循环次数")
                running = False
                break

            # 逻辑
            self.one_time()

            # 完成一次后计数
            current_time += 1

            self.log_info(f"当前次数: {current_time}/{max_time}")

            self.sleep(0.1)

    def one_time(self):
        self.send_key("f4", after_sleep=3)
        self.record_or_replay_operations(2, instruction_text=self.tr(RECORD_INS))
        self.sleep(2)
        self.operate_click(0.8995, 0.9546, after_sleep=2)
        self.go()
        while not self.ocr(
            x=0.7839, y=0.8769, to_x=0.9792, to_y=0.9806, match=re.compile(r".*?\((\d+)\).*")
        ):
            self.sleep(1)
        self.operate_click(0.8995, 0.9546, after_sleep=1)
        while not self.in_world():
            self.sleep(1)

    def go(self):
        self.wait_in_team(time_out=120, settle_time=2)
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time

            # 剩余时间
            remain = 150 - elapsed

            if remain <= 0:
                break
            if elapsed > 15 and elapsed < 40:
                try:
                    self.send_key_down("w")
                    self.send_key("space")
                    self.sleep(0.25)
                    self.send_key("space")
                    self.sleep(1)
                finally:
                    self.send_key_up("w")
            self.sleep(1)
        self.wait_until(lambda: not self.is_in_team(), time_out=600)
