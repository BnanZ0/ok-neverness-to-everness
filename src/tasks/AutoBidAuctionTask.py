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

    SCREEN_WIDTH = 1920
    SCREEN_HEIGHT = 1080

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动拍卖"
        self.description = "在拍卖主界面,选择低级会场后开始"

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

    def _safe_int(self, value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            self.log_warning(
                f"配置转换失败: {value!r},使用默认值: {default}"
            )
            return default

    def _try_claim_welfare(self):
        self._check_stop()

        box_welfare_btn = self.box_of_screen_scaled(
            self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
            1602, 50, width_original=95, height_original=39
        )
        box_claim = self.box_of_screen_scaled(
            self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
            1106, 687, width_original=107, height_original=53
        )
        box_cancel = self.box_of_screen_scaled(
            self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
            711, 688, width_original=97, height_original=51
        )

        try:
            self.log_info("执行低保金领取流程")

            self.wait_click_ocr(
                box=box_welfare_btn,
                match=re.compile(r"低保金"),
                time_out=10,
                after_sleep=0.3,
                target_height=self.SCREEN_HEIGHT
            )
            self._check_stop()

            self.wait_click_ocr(
                box=box_claim,
                match=re.compile(r"领取"),
                time_out=5,
                after_sleep=0.5,
                target_height=self.SCREEN_HEIGHT
            )
            self.sleep(1)
            self._check_stop()

            self.wait_click_ocr(
                box=box_cancel,
                match=re.compile(r"取消"),
                time_out=5,
                after_sleep=0.5,
                target_height=self.SCREEN_HEIGHT
            )
            self.sleep(1)

            self.log_info("低保金领取完成")
            return True

        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_warning(f"低保金领取失败: {type(e).__name__}: {e}")
            return False

    def _sell_collections(self):
        self._check_stop()
        self.log_info("开始执行藏品出售流程")

        try:
            self.wait_click_ocr(
                match=re.compile(r"藏品仓库"),
                time_out=10,
                after_sleep=1,
                target_height=self.SCREEN_HEIGHT
            )

            box_sell = self.box_of_screen_scaled(
                self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
                1788, 929, width_original=34, height_original=43
            )
            box_confirm_sell = self.box_of_screen_scaled(
                self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
                1655, 932, width_original=47, height_original=58
            )
            box_blank = self.box_of_screen_scaled(
                self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
                848, 919, width_original=234, height_original=71
            )
            box_close = self.box_of_screen_scaled(
                self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
                1824, 49, width_original=25, height_original=30
            )

            quality_boxes = [
                self.box_of_screen_scaled(self.SCREEN_WIDTH, self.SCREEN_HEIGHT, 1309, 863, width_original=9, height_original=22),
                self.box_of_screen_scaled(self.SCREEN_WIDTH, self.SCREEN_HEIGHT, 1402, 863, width_original=10, height_original=15),
                self.box_of_screen_scaled(self.SCREEN_WIDTH, self.SCREEN_HEIGHT, 1496, 864, width_original=18, height_original=17),
                self.box_of_screen_scaled(self.SCREEN_WIDTH, self.SCREEN_HEIGHT, 1591, 865, width_original=17, height_original=18),
                self.box_of_screen_scaled(self.SCREEN_WIDTH, self.SCREEN_HEIGHT, 1684, 863, width_original=18, height_original=18),
                self.box_of_screen_scaled(self.SCREEN_WIDTH, self.SCREEN_HEIGHT, 1780, 863, width_original=17, height_original=22),
            ]
            quality_keys = ["品质白", "品质绿", "品质蓝", "品质紫", "品质橙", "品质红"]

            self._check_stop()
            self.operate_click(box_sell, after_sleep=1)

            for i, box_quality in enumerate(quality_boxes):
                self._check_stop()
                if self.config.get(self.CONF_KEEP_RED, True) and quality_keys[i] == "品质红":
                    self.log_info("保留品质红")
                    continue
                self.operate_click(box_quality, after_sleep=0.5)
                self.log_info(f"选择{quality_keys[i]}")

            self._check_stop()
            self.operate_click(box_confirm_sell, after_sleep=1.5)
            self.log_info("确认出售")

            self.operate_click(box_blank, after_sleep=0.5)
            self.operate_click(box_close, after_sleep=1)
            self.log_info("藏品出售完成")
            return True

        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_warning(f"藏品出售失败: {type(e).__name__}: {e}")
            return False

    def _send_emote(self):
        self._check_stop()

        box_emote_btn = self.box_of_screen_scaled(
            self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
            58, 972, width_original=27, height_original=27
        )
        box_first_emote = self.box_of_screen_scaled(
            self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
            237, 533, width_original=65, height_original=55
        )

        self.log_info("发送表情包")
        self.operate_click(box_emote_btn, after_sleep=0.8)
        self.sleep(0.6)
        self._check_stop()
        self.operate_click(box_first_emote, after_sleep=0.5)
        self.log_info("表情包发送完成")
        return True

    def _input_fixed_price(self, price: int = None):
        self._check_stop()
        if price is None:
            price = self.config.get(self.CONF_FIXED_PRICE, 1)

        try:
            price = int(price)
        except Exception:
            raise ValueError(f"非法价格: {price}")

        price_str = str(price)
        if not price_str.isdigit() or price <= 0:
            raise ValueError(f"非法价格 '{price}'")

        box_clear = self.box_of_screen_scaled(
            self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
            937, 928, width_original=86, height_original=63
        )
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
            x, y, w, h = pad_map[digit]
            box_digit = self.box_of_screen_scaled(
                self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
                x, y, width_original=w, height_original=h
            )
            self.operate_click(box_digit, after_sleep=0.2)

        box_bid_confirm = self.box_of_screen_scaled(
            self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
            1247, 937, width_original=147, height_original=46
        )

        self.wait_click_ocr(
            box=box_bid_confirm,
            match=re.compile(r"确认出价"),
            time_out=5,
            after_sleep=0.5,
            target_height=self.SCREEN_HEIGHT
        )

        self.log_info(f"输入价格 {price}")
        return True

    def _stage_match(self, box_match, box_confirm, box_bid, re_match, re_confirm, re_bid):
        fail_count = 0
        loop_count = 0
        max_loop = 120

        while loop_count < max_loop:
            self._check_stop()
            loop_count += 1

            self.log_info(f"等待匹配开始 ({loop_count}/{max_loop})")

            if self.ocr(box=box_bid, match=re_bid, target_height=self.SCREEN_HEIGHT):
                self.log_info("检测到已在出价界面")
                return "bid"

            if self.ocr(box=box_confirm, match=re_confirm, target_height=self.SCREEN_HEIGHT):
                self.log_info("检测到已在确认界面")
                return "confirm"

            try:
                self._check_stop()
                self.wait_click_ocr(
                    box=box_match,
                    match=re_match,
                    time_out=10,
                    target_height=self.SCREEN_HEIGHT
                )
                self.log_info("已点击开始匹配,等待状态变化")

                matched_confirm = self.wait_ocr(
                    box=box_confirm,
                    match=re_confirm,
                    time_out=3,
                    target_height=self.SCREEN_HEIGHT
                )
                if matched_confirm:
                    self.log_info("匹配成功,进入确认阶段")
                    return "confirm"

                matched_bid = self.wait_ocr(
                    box=box_bid,
                    match=re_bid,
                    time_out=3,
                    target_height=self.SCREEN_HEIGHT
                )
                if matched_bid:
                    self.log_info("匹配成功,进入出价阶段")
                    return "bid"

                self.log_warning("点击匹配后未检测到后续界面,等待状态稳定后重试")
                self.sleep(1)

            except WaitFailedException:
                fail_count += 1
                self.log_warning(f"匹配等待失败 {fail_count}/3")
                self.operate_click(box_match, after_sleep=0.5)
                if fail_count >= 3:
                    raise WaitFailedException("匹配阶段连续失败")

        raise WaitFailedException("匹配阶段等待超时")

    def _stage_confirm(self, box_confirm, re_confirm):
        self._check_stop()
        self.log_info("等待确认按钮")

        result = self.wait_ocr(
            box=box_confirm,
            match=re_confirm,
            time_out=5,
            target_height=self.SCREEN_HEIGHT
        )

        if not result:
            self.log_warning("确认按钮未出现")
            return False

        self._check_stop()
        self.log_info("点击确认按钮")
        self.operate_click(box_confirm, after_sleep=0)
        return True

    def _stage_bid_loop(self, box_bid, box_bid_confirm, re_bid):
        retry = 0
        max_retry = 3

        while retry < max_retry:
            self._check_stop()

            try:
                self.log_info("等待出价按钮")
                self.wait_click_ocr(
                    box=box_bid,
                    match=re_bid,
                    time_out=5,
                    target_height=self.SCREEN_HEIGHT
                )

                self.log_info("点击出价")
                self.sleep(0.5)

                panel_ready = self.wait_ocr(
                    box=box_bid_confirm,
                    match=re.compile(r"确认出价"),
                    time_out=5,
                    target_height=self.SCREEN_HEIGHT
                )

                if not panel_ready:
                    raise WaitFailedException("数字面板未出现")

                self.log_info("数字面板加载完成")
                self._input_fixed_price()
                self._check_stop()

                self.sleep(0.3)
                if self.ocr(box=box_bid, match=re_bid, target_height=self.SCREEN_HEIGHT):
                    raise WaitFailedException("出价确认失败：出价按钮仍存在")

                if self.config.get(self.CONF_USE_EMOTE, False):
                    self._send_emote()

                return True

            except TaskDisabledException:
                raise

            except Exception as e:
                retry += 1
                self.log_warning(
                    f"出价失败 {retry}/{max_retry}: "
                    f"{type(e).__name__}: {e}"
                )
                if retry >= max_retry:
                    raise
                self.sleep(2)

        return False

    def _stage_result(self, box_match, box_bid, box_skip_area, box_exit, re_match, re_bid, re_skip, re_exit):
        self.log_info("等待拍卖结果")
        loop_count = 0
        max_loop = 180

        while loop_count < max_loop:
            self._check_stop()
            loop_count += 1
            self.next_frame()

            if self.ocr(box=box_match, match=re_match, target_height=self.SCREEN_HEIGHT):
                self.log_info("返回匹配界面")
                return True

            skip_results = self.ocr(box=box_skip_area, match=[re_skip], target_height=self.SCREEN_HEIGHT)
            if skip_results:
                self.log_info("检测到跳过动画")
                self.operate_click(skip_results[0], after_sleep=0.5)

                self.wait_click_ocr(
                    box=box_exit,
                    match=re_exit,
                    time_out=5,
                    after_sleep=0.5,
                    target_height=self.SCREEN_HEIGHT
                )
                self.log_info("退出拍卖")

                if self.config.get(self.CONF_USE_WELFARE, False):
                    self._try_claim_welfare()

                return True

            if self.ocr(box=box_bid, match=re_bid, target_height=self.SCREEN_HEIGHT):
                self.log_info("进入下一轮出价")
                return False

            self.sleep(0.5)

        raise WaitFailedException("结果阶段等待超时")

    def _exec_auction_round(self, box_match, box_confirm, box_bid, re_match, re_confirm, re_bid, re_skip):
        self._check_stop()
        self.info_set("当前阶段", "匹配中")
        self.log_info("开始执行拍卖")
        self.sleep(0.5)

        stage = self._stage_match(box_match, box_confirm, box_bid, re_match, re_confirm, re_bid)

        self.info_set("当前阶段", "确认中" if stage == "confirm" else "出价中")

        if stage == "confirm":
            if not self._stage_confirm(box_confirm, re_confirm):
                raise WaitFailedException("确认阶段未完成")
        else:
            self.log_info("跳过确认阶段")

        box_bid_confirm = self.box_of_screen_scaled(
            self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
            1247, 937, width_original=147, height_original=46
        )
        self.info_set("当前阶段", "出价中")
        self._stage_bid_loop(box_bid, box_bid_confirm, re_bid)

        self.info_set("当前阶段", "结算中")

        box_skip_area = self.box_of_screen_scaled(
            self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
            1384, 986, width_original=140, height_original=50
        )
        box_exit = self.box_of_screen_scaled(
            self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
            1659, 977, width_original=155, height_original=50
        )

        return self._stage_result(
            box_match,
            box_bid,
            box_skip_area,
            box_exit,
            re_match,
            re_bid,
            re_skip,
            re.compile(r"退出")
        )

    def run(self):
        # self.ensure_main()

        max_count = self.configured_rounds()
        sell_interval = self._safe_int(
            self.config.get(self.CONF_SELL_INTERVAL, 0),
            0
        )

        count = 0
        consecutive_failures = 0

        self.info_set("已完成次数", count)

        box_match = self.box_of_screen_scaled(
            self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
            1466, 945, width_original=135, height_original=49
        )
        box_confirm = self.box_of_screen_scaled(
            self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
            1110, 687, width_original=99, height_original=47
        )
        box_bid = self.box_of_screen_scaled(
            self.SCREEN_WIDTH, self.SCREEN_HEIGHT,
            1694, 986, width_original=93, height_original=43
        )

        re_match = re.compile(r"开始匹配")
        re_confirm = re.compile(r"确认")
        re_bid = re.compile(r"出价")
        re_skip = re.compile(r"跳过")

        try:
            while max_count == 0 or count < max_count:
                self._check_stop()

                try:
                    finished = self._exec_auction_round(
                        box_match,
                        box_confirm,
                        box_bid,
                        re_match,
                        re_confirm,
                        re_bid,
                        re_skip
                    )

                    if finished:
                        count += 1
                        consecutive_failures = 0

                        self.info_set("已完成次数", count)
                        self.log_info(f"拍卖完成 {count}")

                        if sell_interval > 0 and count % sell_interval == 0:
                            self._sell_collections()

                except TaskDisabledException:
                    raise

                except Exception as e:
                    consecutive_failures += 1
                    self.log_error(f"拍卖失败 {consecutive_failures}/3 {type(e).__name__}: {e}")
                    if consecutive_failures >= 3:
                        raise
                    self.sleep(3)

        finally:
            self.log_info(f"自动拍卖结束,共完成 {count} 次")