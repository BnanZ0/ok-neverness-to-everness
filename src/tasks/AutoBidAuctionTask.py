import re

from ok import TaskDisabledException, WaitFailedException
from src.tasks.BaseNTETask import BaseNTETask


class AutoBidAuctionTask(BaseNTETask):
    """自动完成游戏内拍卖流程。

    功能包括：匹配、确认、出价、出价重试、低保金领取、表情包发送、藏品出售。
    需要在拍卖主界面选择低级会场后开始执行。
    """

    # --- 拍卖核心配置 ---
    CONF_FIXED_PRICE = "自定义价格"
    CONF_SELL_INTERVAL = "出售藏品间隔次数"
    CONF_KEEP_RED = "保留品质红"

    # --- 拍卖辅助功能 ---
    CONF_USE_EMOTE = "启用表情包"
    CONF_USE_WELFARE = "启用低保金"

    # 上一轮出价记录，用于价格快捷输入
    last_bid_price = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 设置 OCR 语言为简体中文，提高识别准确率
        self.supported_languages = ["zh_CN"]

        self.name = "自动拍卖"
        self.description = "在拍卖主界面，选择低级会场后开始"

        # 使用基类方法添加标准的轮次配置
        self.add_rounds_config()

        self.default_config.update({
            self.CONF_FIXED_PRICE: 1,
            self.CONF_SELL_INTERVAL: 0,
            self.CONF_USE_EMOTE: False,
            self.CONF_USE_WELFARE: False,
            self.CONF_KEEP_RED: True,
        })

        self.config_description.update({
            self.CONF_SELL_INTERVAL: "设置为0则不出售",
            self.CONF_USE_EMOTE: "收藏的第一个表情包",
        })

        self.last_bid_price = None

        # --- 坐标定义（保留供后续功能扩展） ---
        self.box_abandon = self.box_of_screen(0.7250, 0.9120, to_x=0.7885, to_y=0.9556)
        self.box_my_assets = self.box_of_screen(0.7484, 0.0315, to_x=0.9911, to_y=0.0861)
        self.box_asset_value = self.box_of_screen(0.8583, 0.0426, to_x=0.9870, to_y=0.0806)
        self.box_current_estimate = self.box_of_screen(0.7797, 0.1333, to_x=0.9812, to_y=0.1824)
        self.box_estimate_value = self.box_of_screen(0.8427, 0.1361, to_x=0.9781, to_y=0.1741)

    def run(self):
        """任务入口，确保游戏窗口捕获和连接已就绪。"""
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_error("AutoBidAuctionTask 执行异常", e)
            raise

    def do_run(self):
        """主执行逻辑，使用基类的轮次管理框架。"""
        self.start_rounds()

        # 拍卖主界面 UI 元素坐标
        box_match = self.box_of_screen(0.764, 0.875, to_x=0.834, to_y=0.920)
        box_confirm = self.box_of_screen(0.578, 0.636, to_x=0.630, to_y=0.680)
        box_bid = self.box_of_screen(0.882, 0.913, to_x=0.930, to_y=0.953)

        # 正则匹配模式
        re_match = re.compile(r"开始匹配")
        re_confirm = re.compile(r"确认")
        re_bid = re.compile(r"出价")
        re_skip = re.compile(r"跳过")
        re_exit = re.compile(r"退出")

        try:
            while self.has_remaining_rounds():
                if not self.begin_round():
                    break

                try:
                    if self._exec_auction_round(
                        box_match,
                        box_confirm,
                        box_bid,
                        re_match,
                        re_confirm,
                        re_bid,
                        re_skip,
                        re_exit
                    ):
                        self.add_success()
                    else:
                        self.add_failed("结果阶段进入下一轮出价")

                    self.log_info(f"拍卖完成 ({self.current_round}/{self._round_state.total_text})")

                    # 定期出售藏品
                    sell_interval = int(self.config.get(self.CONF_SELL_INTERVAL, 0))
                    if sell_interval > 0 and self.current_round % sell_interval == 0:
                        self._sell_collections()

                except TaskDisabledException:
                    raise
                except Exception as e:
                    self.add_failed("拍卖执行异常")
                    self.log_error(f"拍卖失败: {type(e).__name__}: {e}")
                    self.sleep(3)

        finally:
            # 输出最终统计信息
            self.finish_rounds()

    def _exec_auction_round(
        self,
        box_match,
        box_confirm,
        box_bid,
        re_match,
        re_confirm,
        re_bid,
        re_skip,
        re_exit
    ) -> bool:
        """执行单轮拍卖，按序调度各阶段。

        Returns:
            bool: 拍卖是否顺利进入结算（进入下一轮出价时返回 False）。
        """
        self.info_set("当前阶段", "匹配中")
        self.log_info("开始执行拍卖")
        self.sleep(0.5)

        # 提前创建后续阶段需要的 Box
        box_skip_area = self.box_of_screen(0.721, 0.913, to_x=0.794, to_y=0.959)
        box_exit = self.box_of_screen(0.864, 0.905, to_x=0.945, to_y=0.951)
        box_bid_confirm = self.box_of_screen(0.649, 0.868, to_x=0.726, to_y=0.911)

        stage = self._stage_match(
            box_match, box_confirm, box_bid, box_skip_area,
            re_match, re_confirm, re_bid, re_skip
        )

        # 匹配阶段意外识别到跳过动画，直接进入结算
        if stage == "skip":
            return self._stage_result(
                box_match, box_bid, box_skip_area, box_exit,
                re_match, re_bid, re_skip, re_exit
            )

        self.info_set("当前阶段", "确认中" if stage == "confirm" else "出价中")

        if stage == "confirm":
            if not self._stage_confirm(box_confirm, re_confirm):
                raise WaitFailedException("确认阶段未完成")
        else:
            self.log_info("跳过确认阶段")

        self.info_set("当前阶段", "出价中")
        self._stage_bid_loop(box_bid, box_bid_confirm, re_bid)

        self.info_set("当前阶段", "结算中")
        return self._stage_result(
            box_match,
            box_bid,
            box_skip_area,
            box_exit,
            re_match,
            re_bid,
            re_skip,
            re_exit
        )

    def _stage_match(
        self,
        box_match,
        box_confirm,
        box_bid,
        box_skip_area,
        re_match,
        re_confirm,
        re_bid,
        re_skip
    ):
        """匹配阶段：等待进入可出价状态。

        尝试点击“开始匹配”按钮，并根据后续界面进入确认或出价阶段。
        """
        fail_count = 0
        loop_count = 0
        max_loop = 120

        while loop_count < max_loop:
            loop_count += 1
            self.log_info(f"等待匹配开始 ({loop_count}/{max_loop})")

            if self.ocr(box=box_bid, match=re_bid):
                self.log_info("检测到已在出价界面")
                return "bid"

            if self.ocr(box=box_confirm, match=re_confirm):
                self.log_info("检测到已在确认界面")
                return "confirm"

            # 检测是否意外进入了跳过动画界面
            if self.ocr(box=box_skip_area, match=[re_skip]):
                self.log_info("匹配阶段检测到跳过动画，拍卖已意外结束")
                return "skip"

            try:
                result = self._handle_match_click(
                    box_match, box_confirm, box_bid,
                    re_match, re_confirm, re_bid
                )
                if result:
                    return result
            except TaskDisabledException:
                raise
            except WaitFailedException:
                fail_count += 1
                self.log_warning(f"匹配等待失败 ({fail_count}/3)")
                self.operate_click(box_match, after_sleep=0.5)
                if fail_count >= 3:
                    raise WaitFailedException("匹配阶段连续失败")

        raise WaitFailedException("匹配阶段等待超时")

    def _handle_match_click(self, box_match, box_confirm, box_bid,
                            re_match, re_confirm, re_bid):
        """匹配点击核心逻辑：点击开始匹配并等待后续状态变化。"""
        self.wait_click_ocr(
            box=box_match,
            match=re_match,
            time_out=10
        )
        self.log_info("已点击开始匹配，等待状态变化")

        matched_confirm = self.wait_ocr(
            box=box_confirm,
            match=re_confirm,
            time_out=3,
            raise_if_not_found=False
        )
        if matched_confirm:
            self.log_info("匹配成功，进入确认阶段")
            return "confirm"

        matched_bid = self.wait_ocr(
            box=box_bid,
            match=re_bid,
            time_out=3,
            raise_if_not_found=False
        )
        if matched_bid:
            self.log_info("匹配成功，进入出价阶段")
            return "bid"

        self.log_warning("点击匹配后未检测到后续界面，等待状态稳定后重试")
        self.sleep(1)
        return None

    def _stage_confirm(self, box_confirm, re_confirm) -> bool:
        """确认阶段：点击确认按钮。"""
        self.log_info("等待确认按钮")

        result = self.wait_ocr(
            box=box_confirm,
            match=re_confirm,
            time_out=5,
            raise_if_not_found=False
        )

        if not result:
            self.log_warning("确认按钮未出现")
            return False

        self.log_info("点击确认按钮")
        self.operate_click(box_confirm, after_sleep=0)
        self.log_info("已点击确认")
        return True

    def _stage_bid_loop(self, box_bid, box_bid_confirm, re_bid) -> bool:
        """出价阶段：循环尝试出价，包含重试机制。"""
        retry = 0
        max_retry = 3

        while retry < max_retry:
            try:
                return self._attempt_bid(box_bid, box_bid_confirm, re_bid)
            except TaskDisabledException:
                raise
            except Exception as e:
                retry += 1
                self.log_warning(
                    f"出价失败 ({retry}/{max_retry})：{type(e).__name__}: {e}"
                )
                if retry >= max_retry:
                    raise
                self.sleep(2)

        return False

    def _attempt_bid(self, box_bid, box_bid_confirm, re_bid) -> bool:
        """单次出价尝试：包含出价、面板确认和表情包动作。"""
        # --- 新增：资产值判断（资产值为 0 时放弃出价） ---
        assets = self.ocr(box=self.box_asset_value, match=re.compile(r"^\s*0\s*$"))
        if assets:
            # 只有明确识别到 "0" 才执行放弃
            self.log_info(f"检测到当前资产值: {assets[0].name}")
            self.log_info("当前资产值为 0，放弃本轮出价")
            self.operate_click(self.box_abandon, after_sleep=0.5)
            return True  # 返回 True 表示本轮已处理（放弃），进入结算阶段
        # 资产值非 0 或 OCR 失败 → 继续原有出价逻辑

        self.log_info("等待出价按钮")
        found = self.wait_click_ocr(
            box=box_bid,
            match=re_bid,
            time_out=30,
            raise_if_not_found=False
        )

        if not found:
            self.log_warning("未找到出价按钮，准备重试")
            raise WaitFailedException("出价按钮未出现")

        self.log_info("点击出价")
        self.sleep(0.5)

        panel_ready = self.wait_ocr(
            box=box_bid_confirm,
            match=re.compile(r"确认出价"),
            time_out=5,
            raise_if_not_found=False
        )

        if not panel_ready:
            raise WaitFailedException("数字面板未出现")

        self.log_info("数字面板加载完成")
        self._input_fixed_price()

        self.sleep(0.3)
        if self.ocr(box=box_bid, match=re_bid):
            raise WaitFailedException("出价确认失败：出价按钮仍存在")

        if self.config.get(self.CONF_USE_EMOTE, False):
            self._send_emote()

        return True

    def _stage_result(
        self,
        box_match,
        box_bid,
        box_skip_area,
        box_exit,
        re_match,
        re_bid,
        re_skip,
        re_exit
    ) -> bool:
        """结果阶段：等待拍卖结算，处理跳过动画或返回匹配界面。"""
        self.log_info("等待拍卖结算结果")
        loop_count = 0
        max_loop = 180

        while loop_count < max_loop:
            loop_count += 1
            self.next_frame()

            if self.ocr(box=box_match, match=re_match):
                self.log_info("返回匹配界面")
                return True

            skip_results = self.ocr(box=box_skip_area, match=[re_skip])
            if skip_results:
                self.log_info("检测到跳过动画")
                self.operate_click(skip_results[0], after_sleep=0.5)

                self.wait_click_ocr(
                    box=box_exit,
                    match=re_exit,
                    time_out=5,
                    after_sleep=0.5
                )
                self.log_info("退出拍卖")

                if self.config.get(self.CONF_USE_WELFARE, False):
                    self._try_claim_welfare()

                return True

            if self.ocr(box=box_bid, match=re_bid):
                self.log_info("进入下一轮出价")
                return False

            self.sleep(0.5)

        raise WaitFailedException("结果阶段等待超时")

    # --- 具体操作辅助方法 ---

    def _input_fixed_price(self, price: int = None) -> bool:
        """使用游戏内数字键盘输入固定价格。支持快捷按钮：
        - 上轮出价
        - 00
        - 0000
        """
        if price is None:
            price = self.config.get(self.CONF_FIXED_PRICE, 1)

        try:
            price = int(price)
        except Exception:
            raise ValueError(f"非法价格: {price}")

        price_str = str(price)
        if not price_str.isdigit() or price <= 0:
            raise ValueError(f"非法价格 '{price}'")

        # 快捷输入：上轮出价
        if self.last_bid_price is not None and price == self.last_bid_price:
            box_last_bid = self.box_of_screen(0.473, 0.733, 0.546, 0.807)
            self.operate_click(box_last_bid, after_sleep=0.2)
            self.log_info(f"使用上轮出价快捷输入价格 {price}")
        else:
            box_clear = self.box_of_screen(0.488, 0.859, to_x=0.533, to_y=0.917)
            self.operate_click(box_clear, after_sleep=0.3)

            # 数字键盘坐标
            pad_map = {
                "0": (0.223, 0.862, 0.256, 0.924),
                "1": (0.224, 0.510, 0.256, 0.571),
                "2": (0.308, 0.505, 0.344, 0.573),
                "3": (0.394, 0.506, 0.433, 0.568),
                "4": (0.232, 0.629, 0.254, 0.683),
                "5": (0.310, 0.629, 0.343, 0.687),
                "6": (0.399, 0.626, 0.432, 0.690),
                "7": (0.226, 0.744, 0.252, 0.812),
                "8": (0.313, 0.743, 0.346, 0.812),
                "9": (0.401, 0.747, 0.434, 0.805),
                "00": (0.304, 0.853, 0.356, 0.935),
                "0000": (0.383, 0.855, 0.449, 0.932),
            }

            i = 0
            while i < len(price_str):
                remaining = price_str[i:]
                # 优先匹配 0000
                if remaining == "0000" and len(remaining) >= 4:
                    x, y, to_x, to_y = pad_map["0000"]
                    box_digit = self.box_of_screen(x, y, to_x=to_x, to_y=to_y)
                    self.operate_click(box_digit, after_sleep=0.2)
                    i += 4
                # 其次匹配 00
                elif remaining == "00" and len(remaining) >= 2:
                    x, y, to_x, to_y = pad_map["00"]
                    box_digit = self.box_of_screen(x, y, to_x=to_x, to_y=to_y)
                    self.operate_click(box_digit, after_sleep=0.2)
                    i += 2
                else:
                    digit = price_str[i]
                    x, y, to_x, to_y = pad_map[digit]
                    box_digit = self.box_of_screen(x, y, to_x=to_x, to_y=to_y)
                    self.operate_click(box_digit, after_sleep=0.2)
                    i += 1

        # 确认出价
        box_bid_confirm = self.box_of_screen(0.649, 0.868, to_x=0.726, to_y=0.911)
        self.wait_click_ocr(
            box=box_bid_confirm,
            match=re.compile(r"确认出价"),
            time_out=5,
            after_sleep=0.5,
            raise_if_not_found=False
        )

        # 处理价格过高时的异常确认框
        box_exception_area = self.box_of_screen(0.579, 0.641, to_x=0.634, to_y=0.681)
        if self.wait_click_ocr(
            box=box_exception_area,
            match=re.compile(r"确认"),
            time_out=5,
            after_sleep=0.3,
            raise_if_not_found=False
        ):
            self.log_info("检测到异常确认框，点击确认")
        else:
            self.log_info("未检测到异常确认框")

        self.log_info(f"输入价格 {price}")

        # 保存本轮价格，供下一轮使用
        self.last_bid_price = price

        return True

    def _try_claim_welfare(self) -> bool:
        """尝试领取每日低保金。"""
        box_welfare_btn = self.box_of_screen(0.834, 0.046, to_x=0.883, to_y=0.082)
        box_claim = self.box_of_screen(0.576, 0.636, to_x=0.632, to_y=0.685)
        box_cancel = self.box_of_screen(0.370, 0.637, to_x=0.421, to_y=0.684)

        try:
            self.log_info("执行低保金领取流程")

            self.wait_click_ocr(
                box=box_welfare_btn,
                match=re.compile(r"低保金"),
                time_out=10,
                after_sleep=0.3
            )

            self.wait_click_ocr(
                box=box_claim,
                match=re.compile(r"领取"),
                time_out=5,
                after_sleep=0.5
            )
            self.sleep(1)

            self.wait_click_ocr(
                box=box_cancel,
                match=re.compile(r"取消"),
                time_out=5,
                after_sleep=0.5
            )
            self.sleep(1)

            self.log_info("低保金领取完成")
            return True

        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_warning(f"低保金领取失败: {type(e).__name__}: {e}")
            return False

    def _sell_collections(self) -> bool:
        """尝试出售藏品仓库中的藏品。"""
        self.log_info("开始执行藏品出售流程")

        try:
            self.wait_click_ocr(
                match=re.compile(r"藏品仓库"),
                time_out=10,
                after_sleep=1
            )

            box_sell = self.box_of_screen(0.931, 0.860, to_x=0.949, to_y=0.900)
            box_confirm_sell = self.box_of_screen(0.862, 0.863, to_x=0.886, to_y=0.917)
            box_blank = self.box_of_screen(0.442, 0.851, to_x=0.564, to_y=0.917)
            box_close = self.box_of_screen(0.950, 0.045, to_x=0.963, to_y=0.073)

            quality_boxes = [
                self.box_of_screen(0.682, 0.799, to_x=0.687, to_y=0.819),
                self.box_of_screen(0.730, 0.799, to_x=0.735, to_y=0.813),
                self.box_of_screen(0.779, 0.800, to_x=0.788, to_y=0.816),
                self.box_of_screen(0.829, 0.801, to_x=0.838, to_y=0.818),
                self.box_of_screen(0.877, 0.799, to_x=0.886, to_y=0.816),
                self.box_of_screen(0.927, 0.799, to_x=0.936, to_y=0.819),
            ]
            quality_keys = ["品质白", "品质绿", "品质蓝", "品质紫", "品质橙", "品质红"]

            self.operate_click(box_sell, after_sleep=1)

            for i, box_quality in enumerate(quality_boxes):
                if self.config.get(self.CONF_KEEP_RED, True) and quality_keys[i] == "品质红":
                    self.log_info("保留品质红")
                    continue
                self.operate_click(box_quality, after_sleep=0.5)
                self.log_info(f"选择{quality_keys[i]}")

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

    def _send_emote(self) -> bool:
        """发送表情菜单中的第一个表情。"""
        box_emote_btn = self.box_of_screen(0.030, 0.900, to_x=0.044, to_y=0.925)
        box_first_emote = self.box_of_screen(0.123, 0.493, to_x=0.157, to_y=0.544)

        self.log_info("发送表情包")
        self.operate_click(box_emote_btn, after_sleep=0.8)
        self.sleep(0.6)
        self.operate_click(box_first_emote, after_sleep=0.5)
        self.log_info("表情包发送完成")
        return True