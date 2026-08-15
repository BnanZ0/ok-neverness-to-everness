
from ok import TaskDisabledException

from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.tasks.trigger.SkipDialogTask import SkipDialogTask

INST = "进入比赛后开始任务"
EN_INST = "Start the mission after entering the game"
class VolleyballTask(NTEOneTimeTask, BaseNTETask):
    CONF_MODE = "模式"
    MODE_EXP = "刷经验"
    MODE_SUP = "辅助扣发球"
    MODES = [MODE_EXP]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "排球之星"
        self.default_config.update(
            {
                self.CONF_MODE: self.MODE_EXP,
            }
        )
        self.config_type.update(
            {
                self.CONF_MODE: {
                    "type": "drop_down",
                    "options": self.MODES,
                }
            }
        )
        self.instructions = INST if self.is_chinese() else EN_INST
        self.sleep_check_interval = 0.2

    def run(self):
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_error("VolleyballTask error", e)
            raise

    def do_run(self):
        ret = None
        match self.config.get(self.CONF_MODE):
            case self.MODE_EXP:
                ret = self.farm_exp()
            # case self.MODE_SUP:
            #     ret = self.support_mode()
        return ret

    def sleep_check(self):
        super().sleep_check()
        if self.check_monthly_card():
            self.handle_monthly_card()

    def farm_exp(self):
        skip_task = self.get_task_by_class(SkipDialogTask)
        while True:
            self.send_key("j")
            self.sleep(0.5)
            self.send_key("k")
            self.sleep(0.5)
            if box := self.find_one(Labels.volleyball_restart):
                self.operate_click(box, after_sleep=1)
            skip_task.check_skip()
            self.sleep(0.1)

    # def support_mode(self):
    #     skip_task = self.get_task_by_class(SkipDialogTask)
    #     while True:
    #         if self.find_exit():
    #             if self.is_service():
    #                 self.send_key("j")
    #                 self.sleep(2.5)
    #                 self.send_key("k")

    #             if self.is_spike():
    #                 self.send_key("space")
    #                 self.sleep(1)
    #                 self.send_key("k")

    #         if box := self.find_one(Labels.volleyball_restart):
    #             self.operate_click(box, after_sleep=1)
    #         skip_task.check_skip()
    #         self.sleep(0.1)

    # def is_service(self):
    #     from src import text_white_color
    #     upper = self.box_of_screen(0.947, 0.405, 0.965, 0.419)
    #     lower = self.box_of_screen(0.947, 0.514, 0.965, 0.530)
    #     upper_white = self.calculate_color_percentage(text_white_color, upper)
    #     lower_white = self.calculate_color_percentage(text_white_color, lower)
    #     return upper_white > lower_white

    # def is_spike(self):
    #     pass
