import re
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from ok import CannotFindException, TaskDisabledException, find_color_rectangles, og
from qfluentwidgets import FluentIcon

from src import text_white_color
from src.Labels import Labels
from src.tasks.AnomalyTask import AnomalyTask
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.CoffeeTask import CoffeeTask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.utils import image_utils as iu


class DailyTask(NTEOneTimeTask, BaseNTETask):
    """日常任务执行器"""

    # --- 配置项键名 ---
    CONF_CLAIM_MAIL = "领取邮件"
    CONF_COMPLETE_DAILY = "完成每日活跃度"
    CONF_CLAIM_ACTIVITY = "领取活跃度奖励"
    CONF_CLAIM_BP = "领取环期任务奖励"
    CONF_COFFEE_TASK = "一咖舍任务"
    CONF_AUTO_CYCLE_SUB_TASK = "自动循环项目"
    DAILY_STAMINA_TARGET = "目标消耗体力"

    # --- 一咖舍任务选项 ---
    COFFEE_MODE_NONE = "不执行"
    COFFEE_MODE_CLAIM_AND_RESTOCK = "领取/补货一咖舍"
    COFFEE_MODE_AUTO = "运行一咖舍自动化"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "日常任务"
        self.icon = FluentIcon.CAR
        self.group_name = "日常/周常"
        self.group_icon = FluentIcon.CALENDAR
        self.support_schedule_task = True
        self.task_status = {"success": [], "failed": [], "skipped": [], "pending": []}

        AnomalyTask.setup_config(self)
        self.default_config.update(
            {
                self.DAILY_STAMINA_TARGET: 180,
                self.CONF_AUTO_CYCLE_SUB_TASK: False,
                self.CONF_COFFEE_TASK: self.COFFEE_MODE_NONE,
            }
        )
        self.config_description.update(
            {
                self.CONF_AUTO_CYCLE_SUB_TASK: "任务完成后自动切换至下一个项目",
                self.CONF_COFFEE_TASK: "选择日常任务中的一咖舍处理方式",
            }
        )
        coffee_options = [self.COFFEE_MODE_NONE, self.COFFEE_MODE_CLAIM_AND_RESTOCK]
        # 一咖舍自动化页面 OCR 仅匹配简体中文; 在非 zh_CN 下不向用户暴露自动化选项.
        if self._is_zh_cn_locale():
            coffee_options.append(self.COFFEE_MODE_AUTO)
        self.config_type[self.CONF_COFFEE_TASK] = {
            "type": "drop_down",
            "options": coffee_options,
        }
        self.current_task_key = None
        self.add_exit_after_config()

    @staticmethod
    def _is_zh_cn_locale() -> bool:
        """Return True iff the running app reports zh_CN as its locale.

        Defensive against early init / test contexts where ``og.app`` may be
        missing or ``locale.name()`` may raise.
        """
        app = getattr(og, "app", None)
        if app is None or not hasattr(app, "locale"):
            return False
        try:
            return app.locale.name() == "zh_CN"
        except Exception:
            return False

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

        tasks: List[Tuple[str, bool, Callable]] = [
            (
                self.CONF_CLAIM_MAIL,
                self._task_enabled(self.CONF_CLAIM_MAIL, True),
                self.claim_mail,
            ),
            *self._coffee_task_entries(),
            (
                self.CONF_COMPLETE_DAILY,
                self._task_enabled(self.CONF_COMPLETE_DAILY, True),
                self.complete_daily_activities,
            ),
            (
                self.CONF_CLAIM_ACTIVITY,
                self._task_enabled(self.CONF_CLAIM_ACTIVITY, True),
                self.claim_activity_rewards,
            ),
            (
                self.CONF_CLAIM_BP,
                self._task_enabled(self.CONF_CLAIM_BP, True),
                self.claim_battle_pass_rewards,
            ),
        ]

        self._reset_task_status(tasks)

        for task in tasks:
            self.execute_task(*task)

        self.ensure_main()
        self._print_result()
        self.log_info("结束执行日常任务", notify=True)

    def _task_enabled(self, key, default):
        return bool(self.config.get(key, default))

    def _coffee_task_entries(self) -> List[Tuple[str, bool, Callable]]:
        coffee_task = self._coffee_task_entry()
        return [coffee_task] if coffee_task else []

    def _coffee_task_entry(self) -> Optional[Tuple[str, bool, Callable]]:
        mode = self._coffee_task_mode()
        if mode == self.COFFEE_MODE_CLAIM_AND_RESTOCK:
            return (self.COFFEE_MODE_CLAIM_AND_RESTOCK, True, self.claim_coffee)
        if mode == self.COFFEE_MODE_AUTO:
            return (self.COFFEE_MODE_AUTO, True, self.run_coffee_task)
        return None

    def _coffee_task_mode(self):
        mode = self.config.get(self.CONF_COFFEE_TASK)
        if mode in (
            self.COFFEE_MODE_NONE,
            self.COFFEE_MODE_CLAIM_AND_RESTOCK,
            self.COFFEE_MODE_AUTO,
        ):
            return mode
        return self.COFFEE_MODE_NONE

    def execute_task(self, key, enabled, func):
        """执行单个子任务。

        Args:
            key (str): 任务名称
            enabled (bool): 是否执行
            func (Callable): 任务执行函数

        根据配置决定是否跳过，并记录执行结果。
        """

        self.task_status["pending"].remove(key)

        if not enabled:
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
        if self.check_activity():
            self.log_info("当前体力消耗或每日活跃度已达标，跳过每日活跃度任务")
            return True

        used_stamina = self.info_get("used stamina")
        must_use = self.config.get(self.DAILY_STAMINA_TARGET, 180) - used_stamina
        self.info_set("must use stamina", must_use)

        task: AnomalyTask = self.get_task_by_class(AnomalyTask)
        ret = task.do_run(self.config, stamina_target=must_use)
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

    def _open_activity(self):
        def action():
            self.openF1panel()
            self.operate_click(0.0551, 0.3833)
            self.sleep(0.5)
            return self.wait_panel(Labels.f1_activity_panel)

        self.log_info("开启活跃度面板")
        result = self.retry_on_action(action, self.ensure_main)
        if not result:
            self.log_error("无法找到活跃度面板")
            return False
        return True

    def check_activity(self):
        if not self._open_activity():
            return False
        activity_re = re.compile(r"(\d+)")
        mission_re = re.compile(r"^(\d+)/180$")
        used_stamina = 0
        daily_activity = 0

        mission_box = self.box_of_screen(0.184, 0.652, 0.781, 0.710, name="mission", hcenter=True)
        activity_box = self.box_of_screen(0.184, 0.188, 0.256, 0.255, name="activity", hcenter=True)

        activity = self.ocr(box=activity_box, match=activity_re)
        mission = self.ocr(box=mission_box, match=mission_re)

        if mission:
            match = mission_re.search(mission[0].name)
            if match:
                used_stamina = int(match.group(1))
                self.log_info(f"ocr found used stamina {used_stamina}")

        if activity:
            match = activity_re.search(activity[0].name)
            if match:
                daily_activity = int(match.group(1))
                self.log_info(f"ocr found daily activity {daily_activity}")

        self.info_set("used stamina", used_stamina)
        self.info_set("daily activity", daily_activity)

        return used_stamina >= 180 or daily_activity >= 100

    def claim_activity_rewards(self, in_panel=False):
        """领取活跃度奖励"""
        self.log_info("正在领取活跃度奖励")
        if not in_panel and not self._open_activity():
            return False
        if self.find_one(Labels.f1_activity_mission):
            self.operate_click(0.2348, 0.7653)
            self.sleep(2)

        if target := self._get_activity_reward_box():
            self.wait_until(
                lambda: not self._get_activity_reward_box(),
                pre_action=lambda: self.operate_click(target, interval=1),
            )
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

    def run_coffee_task(self):
        task: CoffeeTask = self.get_task_by_class(CoffeeTask)
        return task.do_run()
