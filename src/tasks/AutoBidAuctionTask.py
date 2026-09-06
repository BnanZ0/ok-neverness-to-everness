import re
import time

from ok import TaskDisabledException, WaitFailedException

from src.tasks.BaseNTETask import BaseNTETask


class AutoBidAuctionTask(BaseNTETask):
    """自动完成游戏内拍卖流程。

    功能包括: 匹配、确认、出价、出价重试、低保金领取、表情包发送、藏品出售。
    需要在拍卖主界面选择低级会场后开始执行。
    """

    # --- 拍卖核心配置 ---
    CONF_FIXED_PRICE = "基础价"
    CONF_SELL_INTERVAL = "出售藏品间隔次数"
    CONF_KEEP_QUALITIES = "保留藏品品质"

    # --- 自动加价配置 ---
    CONF_AUTO_RAISE = "启用自动加价"
    CONF_RAISE_MODE = "加价方式"
    CONF_RAISE_VALUE = "加价数值"
    CONF_RAISE_ROUND = "加价回合数"

    # --- 指定回合单独出价配置 ---
    CONF_SPECIAL_ROUND = "启用指定回合单独出价"
    CONF_SPECIAL_ROUNDS = "指定回合(可多选)"
    CONF_SPECIAL_ROUND_PRICE = "指定回合价格"

    # --- 拍卖辅助功能 ---
    CONF_USE_EMOTE = "启用表情包"
    CONF_USE_WELFARE = "启用低保金"
    CONF_AUTO_CLEAR_COLLECTIONS = "启用自动清理藏品"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.supported_languages = ["zh_CN"]
        self.name = "自动拍卖"
        self.description = "在拍卖主界面, 选择低级会场后开始"
        self.group_name = "都市闲趣"
        self.add_rounds_config()

        self.default_config.update(
            {
                self.CONF_SELL_INTERVAL: 0,
                self.CONF_KEEP_QUALITIES: ["品质红"],
                self.CONF_AUTO_RAISE: False,
                self.CONF_FIXED_PRICE: 1,
                self.CONF_RAISE_MODE: "倍数",
                self.CONF_RAISE_VALUE: "1.6",
                self.CONF_RAISE_ROUND: 2,
                self.CONF_SPECIAL_ROUND: False,
                self.CONF_SPECIAL_ROUNDS: ["5"],
                self.CONF_SPECIAL_ROUND_PRICE: "66666",
                self.CONF_USE_EMOTE: False,
                self.CONF_USE_WELFARE: False,
                self.CONF_AUTO_CLEAR_COLLECTIONS: False,
            }
        )

        # 配置类型定义，用于下拉框和子配置显隐
        self.config_type = {
            self.CONF_RAISE_MODE: {
                "options": ["倍数", "自定义", "百分比"],
                "sub_configs": {
                    "倍数": [self.CONF_RAISE_VALUE],
                    "自定义": [self.CONF_RAISE_VALUE],
                    "百分比": [self.CONF_RAISE_VALUE],
                },
            },
            self.CONF_KEEP_QUALITIES: {
                "type": "multi_selection",
                "options": ["品质白", "品质绿", "品质蓝", "品质紫", "品质橙", "品质红"],
            },
            # 指定回合单独出价：开启开关才显示子配置，回合为多选（1-6）
            self.CONF_SPECIAL_ROUND: {
                "sub_configs": {
                    True: [self.CONF_SPECIAL_ROUNDS, self.CONF_SPECIAL_ROUND_PRICE],
                }
            },
            self.CONF_SPECIAL_ROUNDS: {
                "type": "multi_selection",
                "options": ["1", "2", "3", "4", "5", "6"],
            },
        }

        self.config_description.update(
            {
                self.CONF_SELL_INTERVAL: "设置为0则不出售",
                self.CONF_USE_EMOTE: "收藏的第一个表情包",
                self.CONF_AUTO_CLEAR_COLLECTIONS: "启用会禁用出售间隔",
                self.CONF_AUTO_RAISE: "在自定义价格基础上自动加价",
                self.CONF_RAISE_MODE: "倍数: 基础价*(倍数^出价次数), 百分比: 基础价*(1+百分比/100*"
                "出价次数), 自定义: 基础价+自定义值*出价次数",
                self.CONF_RAISE_VALUE: "加价数值(支持小数)",
                self.CONF_RAISE_ROUND: "0为从第1次出价开始加, N为从第N次出价开始加",
                self.CONF_FIXED_PRICE: "固定出价（自定义）",
                self.CONF_USE_WELFARE: "我的资产低于10万领取",
                self.CONF_KEEP_QUALITIES: "选中品质不会被出售",
                self.CONF_SPECIAL_ROUND: "启用指定回合单独出价",
                self.CONF_SPECIAL_ROUNDS: "勾选需要使用单独价格的回合(1-6, 可多选)",
                self.CONF_SPECIAL_ROUND_PRICE: "这些回合使用的价格（整数）",
            }
        )

        self.last_bid_price = None
        self.current_bid_count = 0
        self.add_exit_after_config()

    def run(self):
        """任务入口, 确保游戏窗口捕获和连接已就绪。"""
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_error("AutoBidAuctionTask 执行异常", e)
            raise

    def do_run(self):
        """主执行逻辑, 使用基类的轮次管理框架。"""
        self.start_rounds()

        # 拍卖主界面 UI 元素坐标(多个阶段共享)
        # 开始匹配按钮
        box_match = self.box_of_screen(0.7427, 0.8972, 0.8360, 0.9472)
        # 确认按钮(匹配成功后的确认)
        box_confirm = self.box_of_screen(0.578, 0.636, 0.630, 0.680)
        # 出价按钮(出现此按钮表示可以出价)
        box_bid = self.box_of_screen(0.882, 0.913, 0.930, 0.953)

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
                        re_exit,
                    ):
                        self.add_success()
                    else:
                        self.add_failed("结果阶段进入下一轮出价")

                    self.log_info(f"拍卖完成 ({self.current_round}/{self._round_state.total_text})")

                    # 互斥逻辑: 自动清理开启时禁用定期出售
                    auto_clear = self.config.get(self.CONF_AUTO_CLEAR_COLLECTIONS, False)
                    if not auto_clear:
                        try:
                            sell_interval = int(self.config.get(self.CONF_SELL_INTERVAL, 0))
                        except (TypeError, ValueError):
                            self.log_warning("出售藏品间隔次数配置无效, 按0处理")
                            sell_interval = 0
                        if sell_interval > 0 and self.current_round % sell_interval == 0:
                            self._sell_collections()
                except TaskDisabledException:
                    raise
                except Exception as e:
                    self.add_failed("拍卖执行异常")
                    self.log_error(f"拍卖失败: {type(e).__name__}: {e}")
                    self.sleep(3)
        finally:
            self.finish_rounds()

    def _exec_auction_round(
        self, box_match, box_confirm, box_bid, re_match, re_confirm, re_bid, re_skip, re_exit
    ) -> bool:
        """执行单轮拍卖, 按序调度各阶段。

        Returns:
            bool: 拍卖是否顺利进入结算(进入下一轮出价时返回 False)。
        """
        self.info_set("当前阶段", "匹配中")
        self.log_info("开始执行拍卖")
        self.sleep(0.5)

        # 提前创建后续阶段需要的 Box
        box_skip_area = self.box_of_screen(0.721, 0.913, 0.794, 0.959)
        box_exit = self.box_of_screen(0.864, 0.905, 0.945, 0.951)
        box_bid_confirm = self.box_of_screen(0.649, 0.868, 0.726, 0.911)

        stage = self._stage_match(
            box_match, box_confirm, box_bid, box_skip_area, re_match, re_confirm, re_bid, re_skip
        )

        if stage == "skip":
            return self._stage_result(
                box_match, box_bid, box_skip_area, box_exit, re_match, re_bid, re_skip, re_exit
            )

        self.info_set("当前阶段", "确认中" if stage == "confirm" else "出价中")
        if stage == "confirm":
            if not self._stage_confirm(box_confirm, re_confirm):
                raise WaitFailedException("确认阶段未完成")
        else:
            self.log_info("跳过确认阶段")

        self.info_set("当前阶段", "出价中")
        self._stage_bid_loop(
            box_bid, box_bid_confirm, re_bid, box_skip_area, box_match, re_skip, re_match
        )

        self.info_set("当前阶段", "结算中")
        return self._stage_result(
            box_match, box_bid, box_skip_area, box_exit, re_match, re_bid, re_skip, re_exit
        )

    def _stage_match(
        self, box_match, box_confirm, box_bid, box_skip_area, re_match, re_confirm, re_bid, re_skip
    ):
        """匹配阶段: 等待进入可出价状态。"""
        fail_count = 0
        loop_count = 0
        max_loop = 120

        while loop_count < max_loop:
            loop_count += 1
            self.log_debug(f"等待匹配 ({loop_count}/{max_loop})")

            if self.ocr(box=box_bid, match=re_bid):
                self.log_info("检测到已在出价界面")
                return "bid"

            if self.ocr(box=box_confirm, match=re_confirm):
                self.log_info("检测到已在确认界面")
                return "confirm"

            if self.ocr(box=box_skip_area, match=[re_skip]):
                self.log_info("匹配阶段检测到跳过动画, 拍卖已意外结束")
                return "skip"

            try:
                result = self._handle_match_click(
                    box_match, box_confirm, box_bid, re_match, re_confirm, re_bid
                )
                if result:
                    return result
            except TaskDisabledException:
                raise
            except WaitFailedException:
                fail_count += 1
                self.log_warning(f"匹配等待失败 ({fail_count}/3)")
                if fail_count >= 3:
                    raise WaitFailedException("匹配阶段连续失败")
            self.sleep(0.5)

        raise WaitFailedException("匹配阶段等待超时")

    def _handle_match_click(self, box_match, box_confirm, box_bid, re_match, re_confirm, re_bid):
        """点击开始匹配, 并等待后续界面状态变化。"""
        self.wait_click_ocr(box=box_match, match=re_match, time_out=10)
        self.log_info("已点击开始匹配, 等待状态变化")

        matched_confirm = self.wait_ocr(
            box=box_confirm, match=re_confirm, time_out=3, raise_if_not_found=False
        )
        if matched_confirm:
            self.log_info("匹配成功, 进入确认阶段")
            return "confirm"

        matched_bid = self.wait_ocr(box=box_bid, match=re_bid, time_out=3, raise_if_not_found=False)
        if matched_bid:
            self.log_info("匹配成功, 进入出价阶段")
            return "bid"

        self.log_warning("点击匹配后未检测到后续界面, 等待状态稳定后重试")
        self.sleep(1)
        return None

    def _stage_confirm(self, box_confirm, re_confirm) -> bool:
        """确认阶段: 点击确认按钮。"""
        self.log_info("等待确认按钮")
        result = self.wait_ocr(
            box=box_confirm, match=re_confirm, time_out=5, raise_if_not_found=False
        )
        if not result:
            self.log_warning("确认按钮未出现")
            return False
        self.log_info("点击确认按钮")
        self.operate_click(box_confirm, after_sleep=0)
        self.log_info("已点击确认")
        return True

    def _stage_bid_loop(
        self, box_bid, box_bid_confirm, re_bid, box_skip_area, box_match, re_skip, re_match
    ) -> bool:
        """出价阶段: 循环出价直到拍卖结束(支持多轮竞拍)。"""
        # 每轮拍卖开始前重置出价计数和上次价格
        self.current_bid_count = 0
        self.last_bid_price = None

        retry = 0
        max_retry = 3

        while retry < max_retry:
            try:
                if not self._attempt_bid(box_bid, box_bid_confirm, re_bid):
                    retry += 1
                    self.log_warning(f"出价失败 ({retry}/{max_retry}), 尝试重新出价")
                    continue
            except TaskDisabledException:
                raise
            except Exception as e:
                retry += 1
                self.log_warning(f"出价异常 ({retry}/{max_retry}): {type(e).__name__}: {e}")
                if retry >= max_retry:
                    raise
                self.sleep(2)
                continue

            # 出价成功，递增计数
            self.current_bid_count += 1
            self.log_info(f"当前拍卖内第 {self.current_bid_count} 次出价成功")

            self.log_info("出价成功, 等待拍卖结果或加价信号")
            wait_deadline = time.time() + 60

            while time.time() < wait_deadline:
                self.next_frame()
                if self.ocr(box=box_skip_area, match=[re_skip]):
                    self.log_info("检测到跳过动画, 拍卖结束")
                    return True
                if self.ocr(box=box_match, match=re_match):
                    self.log_info("返回匹配界面, 拍卖结束")
                    return True
                if self.ocr(box=box_bid, match=re_bid):
                    self.log_info("检测到有人加价, 准备再次出价")
                    break
                self.sleep(0.5)
            else:
                self.log_info("等待出价超时, 默认拍卖结束")
                return True

        self.log_error("出价阶段重试次数耗尽")
        return False

    def _attempt_bid(self, box_bid, box_bid_confirm, re_bid) -> bool:
        """单次出价尝试: 包含出价、面板确认和表情包动作。"""
        # 放弃按钮
        box_abandon = self.box_of_screen(0.7276, 0.9083, 0.7833, 0.9583)
        # 资产值区域(出价面板右上角)
        box_asset_value = self.box_of_screen(0.8583, 0.0426, 0.9870, 0.0806)

        # 出价前资产判断(资产值为0时放弃)
        self.sleep(0.2)  # 等待 UI 渲染稳定, 避免因面板刚弹出导致 OCR 读取空白
        self.next_frame()

        asset_boxes = self.ocr(box=box_asset_value)
        if asset_boxes:
            raw_text = "".join(box.name for box in asset_boxes)
            asset_value = self._parse_asset_value(raw_text)

            self.log_debug(f"出价前资产原始 OCR: '{raw_text}'")
            self.log_debug(f"解析后资产值: {asset_value}")

            # 资产明确为 0 时放弃本轮出价
            if asset_value == 0:
                self.log_info("检测到当前资产值: 0")
                self.log_info("当前资产值为 0, 放弃本轮出价")
                self.operate_click(box_abandon, after_sleep=0.5)
                self.sleep(0.5)

                # 确认放弃弹窗
                box_abandon_confirm = self.box_of_screen(0.5474, 0.6389, 0.6714, 0.6861)
                self.operate_click(box_abandon_confirm, after_sleep=0.5)

                return True
            elif asset_value is not None:
                self.log_debug(f"当前资产值为 {asset_value}, 不等于 0, 继续执行出价")
            else:
                self.log_debug("资产值解析失败(未识别到有效数字), 按安全策略继续出价")
        else:
            self.log_debug("资产值识别失败(OCR 未匹配到有效文本), 按安全策略继续出价")

        # 后续正常出价逻辑
        self.log_info("等待出价按钮")
        found = self.wait_click_ocr(
            box=box_bid, match=re_bid, time_out=10, raise_if_not_found=False
        )
        if not found:
            self.log_warning("未找到出价按钮, 准备重试")
            raise WaitFailedException("出价按钮未出现")

        self.log_info("点击出价")
        self.sleep(0.5)

        panel_ready = self.wait_ocr(
            box=box_bid_confirm,
            match=re.compile(r"确认出价|[0-9]"),
            time_out=5,
            raise_if_not_found=False,
        )
        if not panel_ready:
            self.log_warning("数字面板识别失败, 按 ESC 关闭可能残留的面板")
            self.send_key("esc", after_sleep=0.5)
            raise WaitFailedException("数字面板未出现")

        self.log_info("数字面板加载完成")
        self._input_fixed_price()

        self.sleep(0.3)
        if self.ocr(box=box_bid, match=re_bid):
            raise WaitFailedException("出价确认失败: 出价按钮仍存在")

        if self.config.get(self.CONF_USE_EMOTE, False):
            self._send_emote()

        return True

    def _stage_result(
        self, box_match, box_bid, box_skip_area, box_exit, re_match, re_bid, re_skip, re_exit
    ) -> bool:
        """结果阶段: 等待拍卖结算, 处理跳过动画或返回匹配界面。"""
        self.log_info("等待拍卖结算结果")
        loop_count = 0
        max_loop = 180

        # 藏品库存不足提示区域
        box_collection_insufficient = self.box_of_screen(0.240, 0.467, 0.747, 0.536)
        # 主界面资产区域 - 适当扩大, 避免资产为 0 时单字符偏移导致漏识别
        box_main_asset = self.box_of_screen(0.670, 0.025, 0.830, 0.095)

        while loop_count < max_loop:
            loop_count += 1
            self.next_frame()

            skip_results = self.ocr(box=box_skip_area, match=[re_skip])
            if skip_results:
                self.log_info("检测到跳过动画")
                self.operate_click(skip_results[0], after_sleep=0.5)

                self.wait_click_ocr(box=box_exit, match=re_exit, time_out=5, after_sleep=0.5)
                self.log_info("退出拍卖")

                self.log_info("等待主界面加载稳定...")
                # 等待时同样使用带 match 的 OCR, 确保能捕获到资产数字(包括单字符 0)
                self.wait_until(
                    lambda: self.ocr(box=box_main_asset, match=re.compile(r"[0-9\uff10-\uff19,]+")),
                    time_out=15,
                    raise_if_not_found=False,
                    settle_time=0.2,
                )

                need_clear_collections = False
                auto_clear = self.config.get(self.CONF_AUTO_CLEAR_COLLECTIONS, False)
                if auto_clear:
                    insufficient_text = self.ocr(
                        box=box_collection_insufficient, match=re.compile(r"少于200格")
                    )
                    if insufficient_text:
                        self.log_info("检测到库存不足提示, 标记需要自动清理藏品")
                        need_clear_collections = True
                    else:
                        self.log_info("未检测到库存不足提示, 跳过自动清理")

                # 低保金领取
                if self.config.get(self.CONF_USE_WELFARE, False):
                    self.next_frame()
                    # 资产为 0 时单字符识别容易失败, 强制使用 match 正则捕获数字模式
                    asset_re = re.compile(r"[0-9\uff10-\uff19,]+")
                    asset_boxes = self.ocr(box=box_main_asset, match=asset_re)
                    if not asset_boxes:
                        self.sleep(0.5)  # 增加等待时间让 UI 完全稳定
                        self.next_frame()
                        asset_boxes = self.ocr(box=box_main_asset, match=asset_re)

                    if asset_boxes:
                        raw_text = "".join(box.name for box in asset_boxes)
                        self.log_debug(f"主界面资产原始 OCR: '{raw_text}'")
                        asset_value = self._parse_asset_value(raw_text)

                        if asset_value is not None:
                            self.log_info(f"当前资产: {asset_value}")
                            if asset_value < 100000:
                                self.log_info("资产低于100000, 执行低保金领取")
                                self._try_claim_welfare()
                            else:
                                self.log_info("资产达到100000, 跳过低保金领取")
                        else:
                            self.log_warning(
                                f"资产值解析失败, OCR 原始文本为: {raw_text}, 跳过本次低保金领取"
                            )
                    else:
                        self.log_warning("资产值识别失败(OCR 未匹配到有效文本), 跳过本次低保金领取")

                if need_clear_collections:
                    self.log_info("根据之前的标记, 现在执行自动清理藏品")
                    self._sell_collections()

                return True

            if self.ocr(box=box_match, match=re_match):
                self.log_info("返回匹配界面")
                return True

            if self.ocr(box=box_bid, match=re_bid):
                self.log_info("进入下一轮出价")
                return False

            self.sleep(0.5)

        raise WaitFailedException("结果阶段等待超时")

    # --- 资产解析公共方法 ---
    def _parse_asset_value(self, raw_text: str) -> int | None:
        """统一解析资产 OCR 文本, 返回整数或 None。

        处理流程:
        1. 全角数字转半角
        2. 提取纯数字
        3. 常见 OCR 错误纠正(O→0, l/I→1)
        4. 转 int, 失败返回 None
        """
        full_to_half_map = {
            "\uff10": "0",
            "\uff11": "1",
            "\uff12": "2",
            "\uff13": "3",
            "\uff14": "4",
            "\uff15": "5",
            "\uff16": "6",
            "\uff17": "7",
            "\uff18": "8",
            "\uff19": "9",
        }
        normalized_text = "".join(full_to_half_map.get(c, c) for c in raw_text)
        digits = re.sub(r"[^\d]", "", normalized_text)

        if not digits:
            return None

        # 常见 OCR 错误纠正
        corrected = digits.replace("l", "1").replace("I", "1").replace("O", "0")
        try:
            return int(corrected)
        except ValueError:
            return None

    # --- 自动加价计算逻辑 ---
    def _calculate_auction_price(self) -> int:
        """计算当前出价应该输入的价格。

        基准价格为自定义价格, 如果启用自动加价, 则根据模式计算加价结果。
        出价序号从1开始计数, 基于成功出价次数+1。
        如果启用了指定回合单独出价, 且当前序号在勾选的回合列表中, 则直接使用该价格。
        """
        try:
            base_price = int(self.config.get(self.CONF_FIXED_PRICE, 1))
        except (TypeError, ValueError):
            base_price = 1

        # 当前出价序号
        bid_count = self.current_bid_count + 1

        # 检查指定回合单独出价（支持多选）
        if self.config.get(self.CONF_SPECIAL_ROUND, False):
            try:
                special_rounds = [int(x) for x in self.config.get(self.CONF_SPECIAL_ROUNDS, [])]
                special_price = int(self.config.get(self.CONF_SPECIAL_ROUND_PRICE, 0))
            except (TypeError, ValueError):
                special_rounds = []
                special_price = 0
            if special_price > 0 and bid_count in special_rounds:
                self.log_info(f"指定回合 {bid_count} 使用单独价格 {special_price}")
                return special_price

        if not self.config.get(self.CONF_AUTO_RAISE, False):
            return base_price

        try:
            mode = self.config.get(self.CONF_RAISE_MODE, "倍数")
            value = float(self.config.get(self.CONF_RAISE_VALUE, 0.0))
        except (TypeError, ValueError):
            mode = "倍数"
            value = 0.0

        try:
            raise_round = int(self.config.get(self.CONF_RAISE_ROUND, 0))
        except (TypeError, ValueError):
            raise_round = 0

        # 如果设置了指定回合，并且当前出价序号还没到该回合，则不启用加价（使用自定义价格）
        if raise_round > 0 and bid_count < raise_round:
            return base_price

        # 计算加价偏移次数（从第几次出价开始加价，偏移从1开始）
        if raise_round == 0:
            offset = bid_count
        else:
            offset = bid_count - raise_round + 1

        # 根据加价方式计算价格
        if mode == "倍数":
            # 指数增长: 基础价 * (倍数 ^ offset)
            result = base_price * (value**offset)
        elif mode == "百分比":
            # 线性: 基础价 * (1 + 百分比/100 * offset)
            result = base_price * (1 + value / 100 * offset)
        else:  # 自定义
            # 线性: 基础价 + 自定义值 * offset
            result = base_price + value * offset

        # 四舍五入为整数
        final_price = int(round(result))

        # 防御: 确保价格为正整数
        if final_price <= 0:
            self.log_warning(f"计算出的价格 {final_price} 无效, 回退到基础价 {base_price}")
            final_price = base_price

        self.log_info(
            f"自动加价计算: 基础价 {base_price}, 模式 {mode}, 数值 {value}, "
            f"出价序号 {bid_count}, 加价偏移 {offset}, 出价 {final_price}"
        )
        return final_price

    # --- 具体操作辅助方法 ---
    def _input_fixed_price(self, price: int = None) -> bool:
        """使用游戏内数字键盘输入固定价格。支持快捷按钮: 上轮出价、00、0000。"""
        if price is None:
            price = self._calculate_auction_price()

        price_str = str(price)
        if not price_str.isdigit() or price <= 0:
            raise ValueError(f"非法价格 '{price}'")

        # 仅在未启用自动加价时，才使用上轮快捷输入（避免自动加价时快捷输入可能带来的不确定性）
        if (
            not self.config.get(self.CONF_AUTO_RAISE, False)
            and self.last_bid_price is not None
            and price == self.last_bid_price
        ):
            box_last_bid = self.box_of_screen(0.473, 0.733, 0.546, 0.807)
            self.operate_click(box_last_bid, after_sleep=0.2)
            self.log_info(f"使用上轮出价快捷输入价格 {price}")
        else:
            box_clear = self.box_of_screen(0.488, 0.859, 0.533, 0.917)
            self.operate_click(box_clear, after_sleep=0.3)

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
                if remaining == "0000" and len(remaining) >= 4:
                    x, y, to_x, to_y = pad_map["0000"]
                    box_digit = self.box_of_screen(x, y, to_x, to_y)
                    self.operate_click(box_digit, after_sleep=0.2)
                    i += 4
                elif remaining == "00" and len(remaining) >= 2:
                    x, y, to_x, to_y = pad_map["00"]
                    box_digit = self.box_of_screen(x, y, to_x, to_y)
                    self.operate_click(box_digit, after_sleep=0.2)
                    i += 2
                else:
                    digit = price_str[i]
                    x, y, to_x, to_y = pad_map[digit]
                    box_digit = self.box_of_screen(x, y, to_x, to_y)
                    self.operate_click(box_digit, after_sleep=0.2)
                    i += 1

        box_bid_confirm = self.box_of_screen(0.649, 0.868, 0.726, 0.911)
        self.wait_click_ocr(
            box=box_bid_confirm,
            match=re.compile(r"确认出价"),
            time_out=5,
            after_sleep=0.5,
            raise_if_not_found=False,
        )

        box_exception_area = self.box_of_screen(0.579, 0.641, 0.634, 0.681)
        if self.wait_click_ocr(
            box=box_exception_area,
            match=re.compile(r"确认"),
            time_out=5,
            after_sleep=0.3,
            raise_if_not_found=False,
        ):
            self.log_info("检测到异常确认框, 点击确认")
        else:
            self.log_info("未检测到异常确认框")

        self.log_info(f"输入价格 {price}")
        self.last_bid_price = price
        return True

    def _try_claim_welfare(self) -> bool:
        """尝试领取每日低保金。"""
        # 低保金按钮
        box_welfare_btn = self.box_of_screen(0.8266, 0.0398, 0.8984, 0.0778)
        box_claim = self.box_of_screen(0.576, 0.636, 0.632, 0.685)
        box_cancel = self.box_of_screen(0.370, 0.637, 0.421, 0.684)

        try:
            self.log_info("执行低保金领取流程")
            self.wait_click_ocr(
                box=box_welfare_btn, match=re.compile(r"低保金"), time_out=5, after_sleep=0.5
            )
            self.wait_click_ocr(
                box=box_claim, match=re.compile(r"领取"), time_out=5, after_sleep=0.5
            )
            self.sleep(1)
            self.wait_click_ocr(
                box=box_cancel, match=re.compile(r"取消"), time_out=5, after_sleep=0.5
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
        # 藏品仓库按钮
        box_warehouse_btn = self.box_of_screen(0.2109, 0.8583, 0.2740, 0.9713)

        try:
            self.wait_click_ocr(
                box=box_warehouse_btn, match=re.compile(r"藏品仓库"), time_out=10, after_sleep=1
            )

            box_sell = self.box_of_screen(0.931, 0.860, 0.949, 0.900)
            box_confirm_sell = self.box_of_screen(0.862, 0.863, 0.886, 0.917)
            box_blank = self.box_of_screen(0.442, 0.851, 0.564, 0.917)
            box_close = self.box_of_screen(0.950, 0.045, 0.963, 0.073)

            quality_boxes = [
                self.box_of_screen(0.682, 0.799, 0.687, 0.819),
                self.box_of_screen(0.730, 0.799, 0.735, 0.813),
                self.box_of_screen(0.779, 0.800, 0.788, 0.816),
                self.box_of_screen(0.829, 0.801, 0.838, 0.818),
                self.box_of_screen(0.877, 0.799, 0.886, 0.816),
                self.box_of_screen(0.927, 0.799, 0.936, 0.819),
            ]
            quality_keys = ["品质白", "品质绿", "品质蓝", "品质紫", "品质橙", "品质红"]

            # 获取保留的品质列表
            keep_qualities = self.config.get(self.CONF_KEEP_QUALITIES, [])

            self.operate_click(box_sell, after_sleep=1)

            for i, box_quality in enumerate(quality_boxes):
                if quality_keys[i] in keep_qualities:
                    self.log_info(f"保留{quality_keys[i]}")
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
        box_emote_btn = self.box_of_screen(0.030, 0.900, 0.044, 0.925)
        box_first_emote = self.box_of_screen(0.123, 0.493, 0.157, 0.544)

        self.log_info("发送表情包")
        self.operate_click(box_emote_btn, after_sleep=0.8)
        self.sleep(0.5)
        self.operate_click(box_first_emote, after_sleep=0.5)
        self.log_info("表情包发送完成")
        return True
