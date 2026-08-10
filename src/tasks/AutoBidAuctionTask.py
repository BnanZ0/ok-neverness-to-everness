import re
from ok import TaskDisabledException, WaitFailedException
from src.tasks.BaseNTETask import BaseNTETask

class AutoBidAuctionTask(BaseNTETask):

    CONF_FIXED_PRICE = "自定义价格"
    CONF_CYCLES = "循环次数"
    CONF_SELL_INTERVAL = "出售藏品间隔次数"
    CONF_USE_EMOTE = "启用表情包"
    CONF_USE_WELFARE = "启用低保金"
    CONF_KEEP_RED = "保留品质红"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动拍卖"
        self.description = "在拍卖主界面，选择低级会场后开始"

        self.default_config.update({
            self.CONF_FIXED_PRICE: 1,
            self.CONF_CYCLES: 0,
            self.CONF_SELL_INTERVAL: 0,
            self.CONF_USE_EMOTE: False,
            self.CONF_USE_WELFARE: False,
            self.CONF_KEEP_RED: True,
        })

        self.config_description.update({
            self.CONF_CYCLES: "设置为0则一直运行",
            self.CONF_SELL_INTERVAL: "设置为0则不出售",
            self.CONF_USE_EMOTE: "收藏的第一个表情包",
        })

    def _check_stop(self):
        if not self.enabled:
            raise TaskDisabledException("用户停止任务")

    def _try_claim_welfare(self):
        self._check_stop()
        box_welfare_btn = self.box_of_screen_scaled(1920, 1080, 1602, 50, width_original=95, height_original=39)
        box_claim = self.box_of_screen_scaled(1920, 1080, 1106, 687, width_original=107, height_original=53)
        box_cancel = self.box_of_screen_scaled(1920, 1080, 711, 688, width_original=97, height_original=51)

        try:
            self.log_info("执行低保金领取流程")
            self._check_stop()
            welfare_ready = self.wait_click_ocr(
                box=box_welfare_btn,
                match=re.compile(r"低保金"),
                time_out=10,
                after_sleep=0.3,
                target_height=1080
            )
            if not welfare_ready:
                self.log_warning("低保金按钮未出现，跳过本次领取")
                return

            self._check_stop()
            self.wait_click_ocr(
                box=box_claim,
                match=re.compile(r"领取"),
                time_out=5,
                after_sleep=0.5,
                target_height=1080
            )
            self.sleep(1.0)

            self._check_stop()
            self.wait_click_ocr(
                box=box_cancel,
                match=re.compile(r"取消"),
                time_out=5,
                after_sleep=0.5,
                target_height=1080
            )
            self.sleep(1.0)
            self.log_info("低保金领取流程完成")

        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_warning(f"低保金领取异常: {e}")
            try:
                self.wait_click_ocr(
                    box=box_cancel,
                    match=re.compile(r"取消"),
                    time_out=2,
                    after_sleep=0.5,
                    target_height=1080
                )
            except Exception:
                pass

    def _sell_collections(self):
        self._check_stop()
        self.log_info("开始执行藏品出售流程")

        self._check_stop()
        self.wait_click_ocr(
            match=re.compile(r"藏品仓库"),
            time_out=10,
            after_sleep=1.0,
            target_height=1080
        )

        box_sell = self.box_of_screen_scaled(1920, 1080, 1788, 929, width_original=34, height_original=43)
        box_confirm_sell = self.box_of_screen_scaled(1920, 1080, 1655, 932, width_original=47, height_original=58)
        box_blank = self.box_of_screen_scaled(1920, 1080, 848, 919, width_original=234, height_original=71)
        box_close = self.box_of_screen_scaled(1920, 1080, 1824, 49, width_original=25, height_original=30)

        quality_boxes = [
            self.box_of_screen_scaled(1920, 1080, 1309, 863, width_original=9, height_original=22),
            self.box_of_screen_scaled(1920, 1080, 1402, 863, width_original=10, height_original=15),
            self.box_of_screen_scaled(1920, 1080, 1496, 864, width_original=18, height_original=17),
            self.box_of_screen_scaled(1920, 1080, 1591, 865, width_original=17, height_original=18),
            self.box_of_screen_scaled(1920, 1080, 1684, 863, width_original=18, height_original=18),
            self.box_of_screen_scaled(1920, 1080, 1780, 863, width_original=17, height_original=22),
        ]
        quality_keys = ["品质白", "品质绿", "品质蓝", "品质紫", "品质橙", "品质红"]

        try:
            self._check_stop()
            self.operate_click(box_sell, after_sleep=1.0)

            for i, box_quality in enumerate(quality_boxes):
                self._check_stop()
                if self.config.get(self.CONF_KEEP_RED, True) and quality_keys[i] == "品质红":
                    self.log_info("保留品质红")
                    continue
                self.operate_click(box_quality, after_sleep=0.5)
                self.log_info(f"已选择{quality_keys[i]}品质")

            self._check_stop()
            self.operate_click(box_confirm_sell, after_sleep=1.5)
            self.log_info("已确认出售")

            self._check_stop()
            self.operate_click(box_blank, after_sleep=0.5)
            self._check_stop()
            self.operate_click(box_close, after_sleep=1.0)
            self.log_info("藏品出售流程完成")

        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_warning(f"藏品出售异常: {e}")
            try:
                self.operate_click(box_blank, after_sleep=0.5)
                self.operate_click(box_close, after_sleep=0.5)
            except Exception:
                pass

    def _send_emote(self):
        self._check_stop()
        box_emote_btn = self.box_of_screen_scaled(1920, 1080, 58, 972, width_original=27, height_original=27)
        box_first_emote = self.box_of_screen_scaled(1920, 1080, 237, 533, width_original=65, height_original=55)
        self.log_info("准备发送表情包")
        self._check_stop()
        self.operate_click(box_emote_btn, after_sleep=0.8)
        self.sleep(0.6)
        self._check_stop()
        self.operate_click(box_first_emote, after_sleep=0.5)
        self.log_info("表情包发送完成")

    def _input_fixed_price(self, price: int = None):
        self._check_stop()
        if price is None:
            price = self.config[self.CONF_FIXED_PRICE]
        price_str = str(price)

        if not price_str.isdigit() or price <= 0:
            raise ValueError(f"非法价格 '{price}'，仅支持正整数")

        self._check_stop()
        box_clear = self.box_of_screen_scaled(1920, 1080, 937, 928, width_original=86, height_original=63)
        self.operate_click(box_clear, after_sleep=0.3)

        pad_map = {
            "0": (429, 931, 63, 67),
            "1": (431, 551, 61, 66),
            "2": (592, 545, 69, 73),
            "3": (756, 547, 74, 67),
            "4": (445, 679, 43, 58),
            "5": (596, 679, 63, 63),
            "6": (767, 676, 63, 69),
            "7": (434, 804, 50, 73),
            "8": (600, 802, 63, 74),
            "9": (769, 807, 63, 63),
        }

        for digit in price_str:
            self._check_stop()
            coords = pad_map[digit]
            box_digit = self.box_of_screen_scaled(1920, 1080, coords[0], coords[1], width_original=coords[2], height_original=coords[3])
            self.operate_click(box_digit, after_sleep=0.2)

        self._check_stop()
        box_bid_confirm = self.box_of_screen_scaled(1920, 1080, 1247, 937, width_original=147, height_original=46)
        self.log_info("等待确认出价按钮出现...")
        self.wait_click_ocr(
            box=box_bid_confirm,
            match=re.compile(r"确认出价"),
            time_out=5,
            after_sleep=0.5,
            target_height=1080
        )
        self.log_info(f"已输入价格 {price_str} 并确认")

        self._check_stop()
        box_exception_confirm = self.box_of_screen_scaled(1920, 1080, 1111, 692, width_original=105, height_original=43)
        self.operate_click(box_exception_confirm, after_sleep=0.3)
        self.log_info("已点击异常确认框")

    def _stage_match(self, box_match, box_confirm, box_bid, re_match, re_confirm, re_bid):
        fail_count = 0
        while True:
            self._check_stop()
            self.log_info("等待匹配开始...")

            if self.ocr(box=box_bid, match=re_bid, target_height=1080):
                self.log_info("检测到已在出价界面，跳过匹配步骤")
                return "bid"

            if self.ocr(box=box_confirm, match=re_confirm, target_height=1080):
                self.log_info("检测到已在确认界面，跳过匹配步骤")
                return "confirm"

            try:
                self._check_stop()
                self.wait_click_ocr(
                    box=box_match,
                    match=re_match,
                    time_out=10,
                    target_height=1080
                )
                self.log_info("已尝试点击开始匹配，验证界面是否跳转...")

                self._check_stop()
                matched_confirm = self.wait_ocr(box=box_confirm, match=re_confirm, time_out=3, target_height=1080)
                if matched_confirm:
                    self.log_info("确认按钮已出现，匹配真正成功！")
                    return "confirm"

                matched_bid = self.wait_ocr(box=box_bid, match=re_bid, time_out=3, target_height=1080)
                if matched_bid:
                    self.log_info("检测到跳转到出价界面，匹配成功！")
                    return "bid"

                self.log_warning("点击开始匹配后未出现确认或出价，可能是假点击，重新尝试")
                self.operate_click(box_match, after_sleep=1)

            except WaitFailedException:
                fail_count += 1
                self.log_info(f"开始匹配超时，重新点击开始匹配并重试 ({fail_count}/3)")
                self.operate_click(box_match)
                self.sleep(0.5)
                if fail_count >= 3:
                    self.log_error("匹配阶段连续失败已达 3 次，放弃本轮拍卖")
                    raise WaitFailedException("匹配阶段重试次数超出上限")

    def _stage_confirm(self, box_confirm, re_confirm):
        self._check_stop()
        self.log_info("等待确认")
        self.wait_ocr(
            box=box_confirm,
            match=re_confirm,
            time_out=5,
            target_height=1080
        )
        self.log_info("确认按钮已出现，正在点击...")
        self.operate_click(box_confirm, after_sleep=0)
        self.log_info("已点击确认")

    def _stage_bid_loop(self, box_bid, box_bid_confirm, re_bid):
        while True:
            self._check_stop()
            self.log_info("等待出价")
            self.wait_click_ocr(
                box=box_bid,
                match=re_bid,
                time_out=5,
                target_height=1080
            )
            self.log_info("已点击出价")
            self.sleep(0.5)

            self._check_stop()
            self.log_info("等待数字面板加载...")
            panel_ready = self.wait_ocr(
                box=box_bid_confirm,
                match=re.compile(r"确认出价"),
                time_out=5,
                target_height=1080
            )
            if not panel_ready:
                self.log_warning("点击出价后未出现数字面板，可能点击无效，重新开始拍卖")
                raise WaitFailedException("点击出价后未出现数字面板")
            self.log_info("数字面板已加载")

            self._input_fixed_price()

            self._check_stop()
            self.log_info("出价完成")
            self.sleep(0.5)
            if self.config.get(self.CONF_USE_EMOTE, False):
                self._send_emote()
            break

    def _stage_result(self, box_match, box_bid, box_skip_area, box_exit, re_match, re_bid, re_skip, re_exit):
        self.log_info("检查结果区域 / 等待流程结束")
        auction_finished = False

        while True:
            self._check_stop()
            self.next_frame()

            if self.ocr(box=box_match, match=re_match, target_height=1080):
                self.log_info("检测到已回到开始匹配界面，本轮拍卖（被中断）结束")
                auction_finished = True
                break

            skip_results = self.ocr(
                box=box_skip_area,
                match=[re_skip],
                target_height=1080
            )
            if skip_results:
                matched_box = skip_results[0]
                self.log_info("检测到跳过动画，本轮拍卖结束")
                self.operate_click(matched_box, after_sleep=0.5)

                self.log_info("等待退出按钮出现...")
                self.wait_click_ocr(
                    box=box_exit,
                    match=re_exit,
                    time_out=5,
                    after_sleep=0.5,
                    target_height=1080
                )
                self.log_info("已点击退出按钮")

                if self.config.get(self.CONF_USE_WELFARE, False):
                    self._try_claim_welfare()
                auction_finished = True
                break

            if self.ocr(box=box_bid, match=re_bid, target_height=1080):
                self.log_info("检测到新一轮出价，继续出价循环")
                break

            self.sleep(0.5)

        return auction_finished

    def run(self):
        # self.ensure_main()

        max_count = self.configured_rounds()
        sell_interval = int(self.config.get(self.CONF_SELL_INTERVAL, 0))
        count = 0
        consecutive_failures = 0
        self.info_set("已完成次数", count)

        box_match = self.box_of_screen_scaled(1920, 1080, 1466, 945, width_original=135, height_original=49)
        box_confirm = self.box_of_screen_scaled(1920, 1080, 1110, 687, width_original=99, height_original=47)
        box_bid = self.box_of_screen_scaled(1920, 1080, 1694, 986, width_original=93, height_original=43)

        re_match_start = re.compile(r"开始匹配")
        re_confirm = re.compile(r"确认")
        re_bid = re.compile(r"出价")
        re_skip = re.compile(r"跳过")

        try:
            while max_count == 0 or count < max_count:
                try:
                    self._do_one_auction(
                        box_match, box_confirm, box_bid,
                        re_match_start, re_confirm, re_bid, re_skip
                    )
                    count += 1
                    consecutive_failures = 0
                    self.info_set("已完成次数", count)
                    self.log_info(f"拍卖完成 {count}/{max_count if max_count > 0 else '∞'}")

                    if sell_interval > 0 and count % sell_interval == 0:
                        self._sell_collections()

                except TaskDisabledException:
                    self.log_info("用户停止任务")
                    raise
                except Exception as e:
                    consecutive_failures += 1
                    self.log_error(f"发生未知错误: {e}，第 {consecutive_failures} 次重试")
                    if consecutive_failures >= 3:
                        self.log_error("连续失败已达上限，终止任务")
                        raise
                    self.sleep(3)
        finally:
            if max_count > 0:
                self.log_info(f"自动拍卖结束，共完成 {count} 次")
            else:
                self.log_info(f"自动拍卖已停止，共完成 {count} 次")

    def _do_one_auction(self, box_match, box_confirm, box_bid,
                        re_match, re_confirm, re_bid, re_skip):
        self._check_stop()
        self.log_info("已成功进入拍卖环节")
        self.sleep(0.5)

        matched_type = self._stage_match(box_match, box_confirm, box_bid, re_match, re_confirm, re_bid)

        if matched_type == "confirm":
            self._stage_confirm(box_confirm, re_confirm)
        else:
            self.log_info("已跳过确认环节，直接进入出价")

        box_bid_confirm = self.box_of_screen_scaled(1920, 1080, 1247, 937, width_original=147, height_original=46)
        self._stage_bid_loop(box_bid, box_bid_confirm, re_bid)

        box_skip_area = self.box_of_screen_scaled(1920, 1080, 1384, 986, width_original=140, height_original=50)
        box_exit = self.box_of_screen_scaled(1920, 1080, 1659, 977, width_original=155, height_original=50)
        re_exit = re.compile(r"退出")

        if self._stage_result(box_match, box_bid, box_skip_area, box_exit, re_match, re_bid, re_skip, re_exit):
            return