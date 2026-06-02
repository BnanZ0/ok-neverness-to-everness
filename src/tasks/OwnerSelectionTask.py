import time

from ok import TaskDisabledException, og
from qfluentwidgets import FluentIcon

from src.Labels import Labels
from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.tasks.RecordTask import RecordTask

RECORD_INS = (
    "记录点击目标关卡的操作，分为两个步骤：\n"
    "1. 使用滚轮滚动至目标可见 (若不需要则点击目标)\n"
    "2. 点击目标"
)


class OwnerSelectionTask(NTEOneTimeTask, RecordTask):
    CONF_ROUNDS = "循环次数"
    CONF_ROB = "抢钱流"
    CONF_CORDS = "记录坐标"

    REVENUE_CHECK_INTERVAL = 1.0  # OCR 检测营业额间隔（秒）
    CLICK_INTERVAL = 0.5  # 步骤3点击间隔（秒）
    CONTROL_TIMEOUT = 120  # 单轮玩法最长等待（秒）

    POS_START = (0.8957, 0.9326)  # 开始玩法按钮
    POS_TAP = (0.0496, 0.4125)  # 循环点击目标
    OCR_BOX = (0.7977, 0.0882, 0.9711, 0.1257)  # 营业额 OCR 区域
    POS_CLOSE = (0.0230, 0.0361)  # 关闭结果界面
    POS_CONFIRM = (0.5984, 0.7764)  # 结算确认

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "店长特供"
        self.description = "自动循环进出关卡（需配合游戏内挂机流派使用）"
        self.instructions = og.app.tr(
            "功能说明：本功能仅负责『自动退出关卡』与『重新开启关卡』的点击循环，"
            "不包含任何局内的制作食物或招待客人操作。\n\n"
            "使用方法：\n"
            "1. 确保您已配置好游戏内的挂机流派。\n"
            "2. 站在咖啡店可进行 F 交互的位置。\n"
            "3. 首次启动需录制目标, 点击[开始]后请跟随指示操作。"
        )
        self.icon = FluentIcon.SYNC
        self.default_config.update({self.CONF_ROUNDS: 99999, self.CONF_ROB: False})
        self.tr(RECORD_INS)

    def run(self):
        super().run()
        try:
            return self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.screenshot("shop_special_unexpected_exception")
            self.log_error("ShopSpecialTask error", e)
            raise

    def do_run(self):
        success_count = 0
        failed_count = 0
        round_index = 1
        rounds = self._configured_rounds()

        self.info_set("成功次数", "0")
        self.info_set("失败次数", 0)
        self.info_set("失败原因", None)
        self.log_info(f"开始店长特供，共 {rounds} 轮")

        while round_index <= rounds:
            self.log_info(f"开始第 {round_index} 轮")

            if self.run_round(round_index):
                success_count += 1
                self.info_set("成功次数", success_count)
            else:
                failed_count += 1
                self.info_set("失败次数", failed_count)
                self.log_error(f"第 {round_index} 轮失败")

            rounds = self._configured_rounds()
            round_index += 1

            self.info_set("轮次", f"{round_index}/{rounds}")
            self.info_set("成功次数", success_count)
            self.info_set("失败次数", failed_count)

        self.log_info(f"店长特供结束，成功 {success_count}/{rounds}", notify=True)

    def run_round(self, round_index: int) -> bool:
        # 步骤1：按 F 进入店长特供页面
        self.info_set("当前阶段", "进入店长特供")
        self.wait_until(
            lambda: not self.is_in_team(),
            pre_action=lambda: self.send_key("f", interval=1),
            settle_time=0.5,
            time_out=10,
            raise_if_not_found=True,
        )
        self.sleep(0.5)
        self.record_or_replay_operations(2, instruction_text=self.tr(RECORD_INS))
        self.sleep(0.5)
        # 步骤2：点击开始玩法
        self.info_set("当前阶段", "开始玩法")
        start_box = self.box_of_screen(0.922, 0.889, 0.969, 0.972, name="start_btn", hcenter=True)
        button = self.wait_until(
            lambda: self.find_one(Labels.skip_quest_confirm, box=start_box),
            settle_time=0.5,
            time_out=10,
            raise_if_not_found=True,
        )
        self.sleep(0.5)

        change_char_box = self.box_of_screen(
            0.630, 0.889, 0.679, 0.969, name="change_char_btn", hcenter=True
        )
        self.wait_until(
            lambda: not self.find_one(Labels.skip_quest_confirm, box=change_char_box),
            pre_action=lambda: self.operate_click(button, interval=1),
            settle_time=0.5,
            time_out=10,
            raise_if_not_found=True,
        )
        self.sleep(0.5)

        # 步骤3：循环点击 + OCR 检测营业额
        self.info_set("当前阶段", "营业中")
        if not self.run_until_target_revenue():
            return self._fail_round(round_index, "shop_revenue_timeout", "营业额未在超时内达标")

        # 步骤4：关闭结果界面 → 结算确认
        self.info_set("当前阶段", "结算确认")
        claim_box = self.box_of_screen(0.629, 0.734, 0.688, 0.819, name="claim_btn", hcenter=True)
        button = self.wait_until(
            lambda: self.find_one(Labels.skip_quest_confirm, box=claim_box),
            pre_action=lambda: self.operate_click(*self.POS_CLOSE, interval=1),
            settle_time=0.5,
            time_out=10,
            raise_if_not_found=True,
        )
        self.sleep(0.5)

        self.wait_until(
            lambda: not self.find_one(Labels.skip_quest_confirm, box=claim_box),
            pre_action=lambda: self.operate_click(button, interval=2),
            settle_time=0.5,
            time_out=10,
            raise_if_not_found=True,
        )
        self.sleep(0.5)

        self.info_set("当前阶段", "本轮完成")
        return True

    # 工具方法
    def run_until_target_revenue(self) -> bool:
        deadline = time.time() + self.CONTROL_TIMEOUT

        self.log_info("开始营业循环")
        while time.time() < deadline:
            if self.config.get(self.CONF_ROB, True):
                self.operate_click(
                    *self.POS_TAP, interval=self.CLICK_INTERVAL, restore_cursor=False
                )

            if self._check_revenue_reached():
                self.log_info("营业额已达标，退出营业循环")
                return True
            self.sleep(0.01)

        self.log_error("营业额检测超时")
        return False

    def _configured_rounds(self) -> int:
        return max(1, int(self.config.get(self.CONF_ROUNDS, 1)))

    def _check_revenue_reached(self) -> bool:
        box = self.box_of_screen(0.9484, 0.1660, 0.9555, 0.1771, name="star")
        return self.calculate_color_percentage(yellow_star_color, box) > 0.1

    def _fail_round(self, round_index: int, reason: str, message: str) -> bool:
        self.info_set("失败原因", message)
        self.screenshot(f"{reason}_{round_index}")
        self.log_error(message)
        return False


yellow_star_color = {
    "r": (250, 255),
    "g": (200, 220),
    "b": (50, 80),
}
