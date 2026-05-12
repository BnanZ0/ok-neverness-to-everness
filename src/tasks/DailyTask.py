from datetime import datetime
from typing import Callable, List, Tuple

import cv2
import numpy as np
from qfluentwidgets import FluentIcon

from ok import TaskDisabledException, find_color_rectangles
from src import text_white_color
from src.Labels import Labels
from src.tasks.AnomalyTask import AnomalyTask
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.utils import image_utils as iu


class DailyTask(NTEOneTimeTask, BaseNTETask):
    """日常任务执行器"""

    # --- 配置项键名 ---
    CONF_CLAIM_MAIL = "领取邮件"
    CONF_COMPLETE_DAILY = "完成每日活跃度"
    CONF_CLAIM_ACTIVITY = "领取活跃度奖励"
    CONF_CLAIM_BP = "领取环期任务奖励"

    CONF_AUTO_CYCLE_SUB_TASK = "自动循环项目"
    DAILY_STAMINA_TARGET = 180
    MAIL_BUTTON_POSITION = (0.8707, 0.8736)
    MAIL_PANEL_WAIT_TIMEOUT = 4.5
    MAIL_PHONE_MENU_MAIL_ICON_REGION = (0.50, 0.83, 0.72, 0.97)
    MAIL_PHONE_MENU_GLOBAL_MAIL_ICON_REGION = (0.82, 0.78, 0.92, 0.91)
    MAIL_PHONE_MENU_MAIL_ICON_THRESHOLD = 135
    MAIL_PHONE_MENU_MAIL_ICON_MIN_AREA = 160

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "日常任务"
        self.icon = FluentIcon.CAR
        self.support_schedule_task = True
        self.task_status = {"success": [], "failed": [], "skipped": [], "pending": []}
        
        AnomalyTask.setup_config(self)
        self.default_config.update(
            {
                self.CONF_AUTO_CYCLE_SUB_TASK: False,
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
        self.log_info("正在打开邮件面板")
        panel = self.openESCpanel()
        phone_click = self._click_mail_button_from_phone_menu(panel)
        if phone_click is False:
            self.info_set("邮件入口恢复失败", "phone_menu_mail_icon_not_found")
            self.log_error("检测到手机菜单但无法定位邮件入口", notify=True)
            return False
        if phone_click is None:
            self.operate_click(*self.MAIL_BUTTON_POSITION)
            self.sleep(1)
        result = self._wait_mail_panel()
        if not result:
            self.info_set("邮件入口恢复失败", "mail_panel_not_found")
            self.log_error("无法找到邮件面板", notify=True)
            return False
        return result

    def claim_mail(self):
        """领取邮件"""
        self.log_info("正在领取邮件奖励")
        if not self._open_mail_panel():
            return False
        self.operate_click(0.1289, 0.9299)
        self.sleep(1)
        return True

    def _wait_mail_panel(self):
        result = self.wait_panel(Labels.mail_panel, time_out=self.MAIL_PANEL_WAIT_TIMEOUT)
        if not result:
            return None
        name = str(getattr(result, "name", "") or "")
        if name and name not in {Labels.mail_panel, Labels.mail_panel.value}:
            self.log_info(f"邮件面板识别结果不是邮件面板: {name}")
            return None
        return result

    def _click_mail_button_from_phone_menu(self, panel):
        target = self._find_mail_icon_from_phone_menu(panel)
        if target is None and self._is_mail_phone_menu_box(panel):
            return False
        if target is None:
            return None
        self.log_info("识别到手机菜单邮件入口，点击信封图标中心")
        self.operate_click(int(target[0]), int(target[1]), down_time=0.08)
        self.sleep(1)
        return True

    @staticmethod
    def _is_mail_phone_menu_box(panel):
        return getattr(panel, "name", "") in {"mail_phone_menu", "esc_phone_menu"}

    def _find_mail_icon_from_phone_menu(self, panel):
        frame = self._mail_current_frame()
        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return None
        height, width = shape[:2]
        if self._is_mail_phone_menu_box(panel):
            px, py = int(getattr(panel, "x", 0) or 0), int(getattr(panel, "y", 0) or 0)
            pw, ph = int(getattr(panel, "width", 0) or 0), int(getattr(panel, "height", 0) or 0)
            if pw <= 0 or ph <= 0:
                return None
            x1, y1, x2, y2 = self._ratio_region_bounds(pw, ph, self.MAIL_PHONE_MENU_MAIL_ICON_REGION)
            x1, x2 = max(0, px + x1), min(width, px + x2)
            y1, y2 = max(0, py + y1), min(height, py + y2)
        else:
            x1, y1, x2, y2 = self._ratio_region_bounds(
                width,
                height,
                self.MAIL_PHONE_MENU_GLOBAL_MAIL_ICON_REGION,
            )
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame[y1:y2, x1:x2]
        if getattr(crop, "size", 0) == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
        mask = (gray > self.MAIL_PHONE_MENU_MAIL_ICON_THRESHOLD).astype(np.uint8)
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        candidates = []
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            box_width = int(stats[label, cv2.CC_STAT_WIDTH])
            box_height = int(stats[label, cv2.CC_STAT_HEIGHT])
            if area < self.MAIL_PHONE_MENU_MAIL_ICON_MIN_AREA or box_width < 20 or box_height < 14:
                continue
            x = int(stats[label, cv2.CC_STAT_LEFT])
            y = int(stats[label, cv2.CC_STAT_TOP])
            candidates.append((area, x1 + x + box_width / 2, y1 + y + box_height / 2))
        if not candidates:
            return None
        _, center_x, center_y = max(candidates, key=lambda item: item[0])
        return center_x, center_y

    def _mail_current_frame(self):
        next_frame = getattr(self, "next_frame", None)
        if callable(next_frame):
            try:
                frame = next_frame()
                if frame is not None:
                    return frame
            except Exception:
                pass
        try:
            return self.frame
        except Exception:
            return None

    @staticmethod
    def _ratio_region_bounds(width, height, region):
        left, top, right, bottom = region
        return int(width * left), int(height * top), int(width * right), int(height * bottom)

    def complete_daily_activities(self):
        """执行操作完成每日活跃度""" 
        self.log_info("正在执行每日活跃度任务")
        task: AnomalyTask = self.get_task_by_class(AnomalyTask)
        ret = task.do_run(self.config, stamina_target=self.DAILY_STAMINA_TARGET)
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
                    self.config[task.CONF_EXP_TARGET] = task.EXP_ALL[next_idx]
                else:
                    conf_key = {
                        task.TASK_ABILITY: task.CONF_ABILITY_ID,
                        task.TASK_ARC: task.CONF_ARC_ID,
                        task.TASK_CONSOLE: task.CONF_CONSOLE_ID,
                    }.get(task_type)
                    if conf_key:
                        self.config[conf_key] = int(next_idx + 1)
            self.sync_config()

    def claim_activity_rewards(self):
        """领取活跃度奖励"""
        self.log_info("正在领取活跃度奖励")
        self.openF1panel()
        self.operate_click(0.0551, 0.3833)
        if not self.wait_panel(Labels.f1_activity_panel):
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
        self.log_info("正在领取环期任务奖励")
        self.openF2panel()
        self.operate_click(0.0570, 0.3451)
        if not self.wait_panel(Labels.f2_mission_panel):
            self.log_error("无法找到环期任务面板")
            return False
        self.operate_click(0.8777, 0.8187)
        self.sleep(1)
        self.operate_click(0.0570, 0.2333)
        self.sleep(1)
        self.operate_click(0.6934, 0.8229)
        self.sleep(1)
        return True
