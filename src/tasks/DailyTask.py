from datetime import datetime
from typing import Callable, List, Tuple

from ok import CannotFindException, TaskDisabledException, find_color_rectangles
from qfluentwidgets import FluentIcon

from src import text_white_color
from src.Labels import Labels
from src.tasks.AnomalyTask import AnomalyTask
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.F1PanelDetector import F1PanelDetector
from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.utils import image_utils as iu


class DailyTask(NTEOneTimeTask, BaseNTETask):
    """日常任务执行器"""

    # --- 配置项键名 ---
    CONF_CLAIM_MAIL = "领取邮件"
    CONF_COMPLETE_DAILY = "完成每日活跃度"
    CONF_CLAIM_ACTIVITY = "领取活跃度奖励"
    CONF_CLAIM_BP = "领取环期任务奖励"
    CONF_CLAIM_COFFEE = "领取/补货一咖舍"

    CONF_AUTO_CYCLE_SUB_TASK = "自动循环项目"
    DAILY_STAMINA_TARGET = "目标消耗体力"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "日常任务"
        self.icon = FluentIcon.CAR
        self.support_schedule_task = True
        self.task_status = {"success": [], "failed": [], "skipped": [], "pending": []}

        AnomalyTask.setup_config(self)
        self.default_config.update(
            {
                self.CONF_CLAIM_COFFEE: False,
                self.CONF_AUTO_CYCLE_SUB_TASK: False,
                self.DAILY_STAMINA_TARGET: 180,
            }
        )
        self.config_description.update(
            {
                self.CONF_AUTO_CYCLE_SUB_TASK: "任务完成后自动切换至下一个项目",
            }
        )
        self.current_task_key = None
        self.add_exit_after_config()

    def run(self):
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self._handle_exception(e)

    def do_run(self):
        """执行日常任务主流程"""
        self._logged_in = False
        self.ensure_main()
        self.log_info("开始执行日常任务")

        tasks: List[Tuple[str, Callable]] = [
            (self.CONF_CLAIM_MAIL, self.claim_mail),
            (self.CONF_CLAIM_COFFEE, self.claim_coffee),
            (self.CONF_COMPLETE_DAILY, self.complete_daily_activities),
            (self.CONF_CLAIM_ACTIVITY, self.claim_activity_rewards),
            (self.CONF_CLAIM_BP, self.claim_battle_pass_rewards),
        ]

        self._reset_task_status(tasks)

        for key, func in tasks:
            self.execute_task(key, func)

        self.ensure_main()
        self._print_result()
        self.log_info("结束执行日常任务", notify=True)

    def execute_task(self, key, func):
        """执行单个子任务。

        Args:
            key (str): 任务名称
            func (Callable): 任务执行函数

        根据配置决定是否跳过，并记录执行结果。
        """

        self.task_status["pending"].remove(key)

        # 开关控制
        if not self.config.get(key, True):
            self.task_status["skipped"].append(key)
            return

        self.current_task_key = key
        self.log_info(f"开始任务: {key}")

        self.ensure_main()

        result = func()

        if result is False:
            self.task_status["failed"].append(key)
            self.screenshot(f"fail_{key}")
            self.log_info(f"任务失败: {key}")
            return

        self.task_status["success"].append(key)
        self.log_info(f"任务完成: {key}")
        self.current_task_key = None

    def _reset_task_status(self, tasks):
        """重置任务状态。

        Args:
            tasks (list): [(key, func)] 任务列表
        """
        self.task_status = {
            "success": [],
            "failed": [],
            "skipped": [],
            "pending": [t[0] for t in tasks],
        }

    def _print_result(self):
        """输出任务执行结果。"""
        self.info_set("success", f"{self.task_status['success']}")
        self.info_set("failed", f"{self.task_status['failed']}")
        self.info_set("skipped", f"{self.task_status['skipped']}")

    def _handle_exception(self, e):
        """处理执行异常并记录状态。

        Args:
            e (Exception): 捕获到的异常
        """
        self.screenshot(f"{datetime.now().strftime('%Y%m%d')}_exception")

        if self.current_task_key:
            self.info_set("当前失败任务", self.current_task_key)
        self._print_result()
        raise e

    def _open_mail_panel(self):
        """打开mail panel。

        Returns:
            bool: True 表示成功，False 表示失败
        """

        def action():
            self.openESCpanel()
            self.operate_click(0.8707, 0.8736)
            self.sleep(0.5)
            return self.wait_panel(Labels.mail_panel)

        self.log_info("正在打开邮件面板")
        result = self.retry_on_action(action, self.ensure_main)
        if not result:
            self.log_error("无法找到邮件面板", notify=True)
            raise CannotFindException("can't find mail panel")
        return result

    def claim_mail(self):
        """领取邮件"""
        self.log_info("正在领取邮件奖励")
        self._open_mail_panel()
        self.operate_click(0.1289, 0.9299)
        self.sleep(1)
        return True

    def complete_daily_activities(self):
        """执行操作完成每日活跃度"""
        self.log_info("正在执行每日活跃度任务")
        task: AnomalyTask = self.get_task_by_class(AnomalyTask)
        ret = task.do_run(
            self.config, stamina_target=self.config.get(self.DAILY_STAMINA_TARGET, 180)
        )
        if ret:
            self.shift_idx(task)
        return ret

    def shift_idx(self, task):
        """切换任务索引"""
        if self.config.get(self.CONF_AUTO_CYCLE_SUB_TASK):
            if isinstance(task, AnomalyTask):
                task_type = self.config.get(task.CONF_TASK_TYPE)
                next_idx = task.get_next_sub_idx(self.config)
                if task_type == task.TASK_EXP_COIN:
                    self.config[task.CONF_EXP_TARGET] = task.EXP_ALL[next_idx]  # type: ignore
                else:
                    conf_key = {
                        task.TASK_ABILITY: task.CONF_ABILITY_ID,
                        task.TASK_ARC: task.CONF_ARC_ID,
                        task.TASK_CONSOLE: task.CONF_CONSOLE_ID,
                    }.get(task_type)
                    if conf_key:
                        self.config[conf_key] = int(next_idx + 1)  # type: ignore
            self.sync_config()

    def claim_activity_rewards(self):
        """领取活跃度奖励"""

        def action():
            self.openF1panel()
            self.operate_click(0.0551, 0.3833)
            self.sleep(0.5)
            return F1PanelDetector(self).wait_daily_activity_panel()

        self.log_info("正在领取活跃度奖励")
        result = self.retry_on_action(action, self.ensure_main)
        if not result:
            self.log_error("无法找到活跃度面板")
            return False
        if self.find_one(Labels.f1_activity_mission):
            self.operate_click(0.2348, 0.7653)
            self.sleep(2)

        if target := self._get_activity_reward_box():
            self.operate_click(target)
            self.sleep(1)
        else:
            self.log_error("无法找到活跃度奖励领取框")
            return False
        return True

    def _get_activity_reward_box(self):
        target = None
        box = self.get_box_by_name(Labels.box_f1_activity_reward)
        mask = iu.binarize_bgr_by_brightness(self.frame, threshold=245, to_bgr=False)
        mask = iu.morphology_mask(mask, kernel_size=7, to_bgr=True)
        reward_boxes = find_color_rectangles(
            mask, color_range=text_white_color, min_width=10, min_height=10, box=box, threshold=0.6
        )
        if reward_boxes:
            target = max(reward_boxes, key=lambda x: x.x)
            self.draw_boxes(boxes=target)
        return target

    def claim_battle_pass_rewards(self):
        """领取环期任务奖励"""

        def action():
            self.openF2panel()
            self.operate_click(0.0570, 0.3451)
            self.sleep(0.5)
            return self.wait_panel(Labels.f2_mission_panel)

        self.log_info("正在领取环期任务奖励")
        result = self.retry_on_action(action, self.ensure_main)
        if not result:
            self.log_error("无法找到环期任务面板")
            return False
        self.operate_click(0.8777, 0.8187)
        self.sleep(1)
        self.operate_click(0.0570, 0.2333)
        self.sleep(1)
        self.operate_click(0.6934, 0.8229)
        self.sleep(1)
        return True

    def claim_coffee(self):
        """领取一咖舍奖励"""

        def action():
            self.openF5panel()
            self.sleep(1)
            self.operate_click(0.415, 0.753)
            self.sleep(0.5)
            return self.wait_panel(Labels.f5_coffee_panel)

        self.log_info("正在领取一咖舍奖励")
        result = self.retry_on_action(action, self.ensure_main)
        if not result:
            self.log_error("无法找到一咖舍面板")
            return False
        self.sleep(1)

        # 提取收益
        self.operate_click(0.188, 0.877)
        self.sleep(1)
        self.wait_until(
            lambda: self.find_one(Labels.f5_coffee_panel),
            pre_action=lambda: self.operate_click(0.072, 0.886, interval=1),
            time_out=10,
            settle_time=0.5,
        )
        self.sleep(1)

        # 进入补货
        
        self.wait_until(
            lambda: not self.find_one(Labels.f5_coffee_panel),
            pre_action=lambda: self.operate_click(0.115, 0.530, interval=1),
            time_out=10,
            settle_time=0.5,
        )
        self.sleep(1)

        # 补货
        self.operate_click(0.340, 0.785)  # 24hr
        self.sleep(1)
        self.operate_click(0.717, 0.787)  # 补货
        self.sleep(1)
        self.operate_click(0.595, 0.776)  # 送货上门
        self.sleep(1)
        self.operate_click(0.600, 0.656)  # 确认
        return True
