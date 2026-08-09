import re
from ok import TaskDisabledException, WaitFailedException
from src.tasks.BaseNTETask import BaseNTETask


class AutoBidAuctionTask(BaseNTETask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动拍卖"
        self.description = "在拍卖活动界面，选择会场后开始"
        self.default_config = {
            '固定价格': 1,
            '循环次数': 0,
            '出售藏品间隔次数': 0,
            '启用表情包': False,
            '启用低保金': False,
            '保留品质红': True,
            '显示坐标配置': False,
            '显示时间配置': False,
            '基准宽度': 1920,
            '基准高度': 1080,
            '表情按钮X': 58, '表情按钮Y': 972, '表情按钮宽': 27, '表情按钮高': 27,
            '首个表情X': 237, '首个表情Y': 533, '首个表情宽': 65, '首个表情高': 55,
            '匹配按钮X': 1466, '匹配按钮Y': 945, '匹配按钮宽': 135, '匹配按钮高': 49,
            '确认按钮X': 1110, '确认按钮Y': 687, '确认按钮宽': 99, '确认按钮高': 47,
            '出价按钮X': 1694, '出价按钮Y': 986, '出价按钮宽': 93, '出价按钮高': 43,
            '跳过识别区域X': 1384, '跳过识别区域Y': 986, '跳过识别区域宽': 140, '跳过识别区域高': 50,
            '出价识别区域X': 1694, '出价识别区域Y': 986, '出价识别区域宽': 93, '出价识别区域高': 43,
            '确认出价X': 1247, '确认出价Y': 937, '确认出价宽': 147, '确认出价高': 46,
            '空白区域X': 848, '空白区域Y': 919, '空白区域宽': 234, '空白区域高': 71,
            '低保金按钮X': 1602, '低保金按钮Y': 50, '低保金按钮宽': 95, '低保金按钮高': 39,
            '领取按钮X': 1106, '领取按钮Y': 687, '领取按钮宽': 107, '领取按钮高': 53,
            '取消按钮X': 711, '取消按钮Y': 688, '取消按钮宽': 97, '取消按钮高': 51,
            '出售X': 1788, '出售Y': 929, '出售宽': 34, '出售高': 43,
            '品质白X': 1309, '品质白Y': 863, '品质白宽': 9, '品质白高': 22,
            '品质绿X': 1402, '品质绿Y': 863, '品质绿宽': 10, '品质绿高': 15,
            '品质蓝X': 1496, '品质蓝Y': 864, '品质蓝宽': 18, '品质蓝高': 17,
            '品质紫X': 1591, '品质紫Y': 865, '品质紫宽': 17, '品质紫高': 18,
            '品质橙X': 1684, '品质橙Y': 863, '品质橙宽': 18, '品质橙高': 18,
            '品质红X': 1780, '品质红Y': 863, '品质红宽': 17, '品质红高': 22,
            '确认出售X': 1655, '确认出售Y': 932, '确认出售宽': 47, '确认出售高': 58,
            '关闭X_X': 1824, '关闭X_Y': 49, '关闭X_宽': 25, '关闭X_高': 30,
            '退出按钮X': 1659, '退出按钮Y': 977, '退出按钮宽': 155, '退出按钮高': 50,
            '数字0_X': 429, '数字0_Y': 931, '数字0_宽': 63, '数字0_高': 67,
            '数字1_X': 431, '数字1_Y': 551, '数字1_宽': 61, '数字1_高': 66,
            '数字2_X': 592, '数字2_Y': 545, '数字2_宽': 69, '数字2_高': 73,
            '数字3_X': 756, '数字3_Y': 547, '数字3_宽': 74, '数字3_高': 67,
            '数字4_X': 445, '数字4_Y': 679, '数字4_宽': 43, '数字4_高': 58,
            '数字5_X': 596, '数字5_Y': 679, '数字5_宽': 63, '数字5_高': 63,
            '数字6_X': 767, '数字6_Y': 676, '数字6_宽': 63, '数字6_高': 69,
            '数字7_X': 434, '数字7_Y': 804, '数字7_宽': 50, '数字7_高': 73,
            '数字8_X': 600, '数字8_Y': 802, '数字8_宽': 63, '数字8_高': 74,
            '数字9_X': 769, '数字9_Y': 807, '数字9_宽': 63, '数字9_高': 63,
            '清除键_X': 937, '清除键_Y': 928, '清除键_宽': 86, '清除键_高': 63,
            '异常确认X': 1111, '异常确认Y': 692, '异常确认宽': 105, '异常确认高': 43,
            '匹配点击超时': 10,
            '匹配验证超时': 3,
            '确认等待超时': 5,
            '出价点击超时': 5,
            '面板加载超时': 5,
            '退出点击超时': 5,
            '低保金按钮超时': 10,
            '领取按钮超时': 5,
            '取消按钮超时': 5,
            '出售仓库超时': 10,
            '确认出售等待': 1.5,
            '错误重试等待': 3,
            '点击后缓冲': 0.5,
            '表情包等待': 0.6,
            '关闭后等待': 1.0,
        }

        self.config_description = {
            '循环次数': '设置为0则一直运行',
            '出售藏品间隔次数': '设置为0则不出售',
            '启用表情包': '收藏的第一个表情包',
            '匹配点击超时': '等待点击“开始匹配”的超时秒数',
            '匹配验证超时': '点击匹配后等待“确认/出价”出现的超时',
            '确认等待超时': '等待“确认”按钮出现的超时',
            '出价点击超时': '等待点击“出价”按钮的超时',
            '面板加载超时': '等待数字面板（确认出价）加载的超时',
            '退出点击超时': '等待点击“退出”按钮的超时',
            '低保金按钮超时': '等待“低保金”按钮出现的超时',
            '领取按钮超时': '等待“领取”按钮出现的超时',
            '取消按钮超时': '等待“取消”按钮出现的超时',
            '出售仓库超时': '等待“藏品仓库”按钮出现的超时',
            '确认出售等待': '点击确认出售后的等待时间',
            '错误重试等待': '发生错误后重试前的等待时间',
            '点击后缓冲': '点击按钮后的固定等待时间',
            '表情包等待': '发送表情包过程中的等待时间',
            '关闭后等待': '点击关闭按钮后的等待时间',
        }

        self._coordinate_keys = [
            '基准宽度', '基准高度',
            '表情按钮X', '表情按钮Y', '表情按钮宽', '表情按钮高',
            '首个表情X', '首个表情Y', '首个表情宽', '首个表情高',
            '匹配按钮X', '匹配按钮Y', '匹配按钮宽', '匹配按钮高',
            '确认按钮X', '确认按钮Y', '确认按钮宽', '确认按钮高',
            '出价按钮X', '出价按钮Y', '出价按钮宽', '出价按钮高',
            '跳过识别区域X', '跳过识别区域Y', '跳过识别区域宽', '跳过识别区域高',
            '出价识别区域X', '出价识别区域Y', '出价识别区域宽', '出价识别区域高',
            '确认出价X', '确认出价Y', '确认出价宽', '确认出价高',
            '空白区域X', '空白区域Y', '空白区域宽', '空白区域高',
            '低保金按钮X', '低保金按钮Y', '低保金按钮宽', '低保金按钮高',
            '领取按钮X', '领取按钮Y', '领取按钮宽', '领取按钮高',
            '取消按钮X', '取消按钮Y', '取消按钮宽', '取消按钮高',
            '出售X', '出售Y', '出售宽', '出售高',
            '品质白X', '品质白Y', '品质白宽', '品质白高',
            '品质绿X', '品质绿Y', '品质绿宽', '品质绿高',
            '品质蓝X', '品质蓝Y', '品质蓝宽', '品质蓝高',
            '品质紫X', '品质紫Y', '品质紫宽', '品质紫高',
            '品质橙X', '品质橙Y', '品质橙宽', '品质橙高',
            '品质红X', '品质红Y', '品质红宽', '品质红高',
            '确认出售X', '确认出售Y', '确认出售宽', '确认出售高',
            '关闭X_X', '关闭X_Y', '关闭X_宽', '关闭X_高',
            '退出按钮X', '退出按钮Y', '退出按钮宽', '退出按钮高',
            '数字0_X', '数字0_Y', '数字0_宽', '数字0_高',
            '数字1_X', '数字1_Y', '数字1_宽', '数字1_高',
            '数字2_X', '数字2_Y', '数字2_宽', '数字2_高',
            '数字3_X', '数字3_Y', '数字3_宽', '数字3_高',
            '数字4_X', '数字4_Y', '数字4_宽', '数字4_高',
            '数字5_X', '数字5_Y', '数字5_宽', '数字5_高',
            '数字6_X', '数字6_Y', '数字6_宽', '数字6_高',
            '数字7_X', '数字7_Y', '数字7_宽', '数字7_高',
            '数字8_X', '数字8_Y', '数字8_宽', '数字8_高',
            '数字9_X', '数字9_Y', '数字9_宽', '数字9_高',
            '清除键_X', '清除键_Y', '清除键_宽', '清除键_高',
            '异常确认X', '异常确认Y', '异常确认宽', '异常确认高',
        ]

        self._time_config_keys = [
            '匹配点击超时', '匹配验证超时', '确认等待超时', '出价点击超时',
            '面板加载超时', '退出点击超时', '低保金按钮超时', '领取按钮超时',
            '取消按钮超时', '出售仓库超时', '确认出售等待', '错误重试等待',
            '点击后缓冲', '表情包等待', '关闭后等待'
        ]

        self.config_type = {
            '显示坐标配置': {
                'sub_configs': {
                    True: self._coordinate_keys,
                    False: []
                }
            },
            '显示时间配置': {
                'sub_configs': {
                    True: self._time_config_keys,
                    False: []
                }
            }
        }

    def _make_box(self, x, y, w, h):
        return self.box_of_screen_scaled(
            original_screen_width=self.config['基准宽度'],
            original_screen_height=self.config['基准高度'],
            x_original=x, y_original=y,
            width_original=w, height_original=h
        )

    def _check_stop(self):
        if not self.enabled or self.executor.paused:
            raise TaskDisabledException("用户停止任务")

    def _try_claim_welfare(self):
        self._check_stop()
        box_welfare_btn = self._make_box(
            self.config['低保金按钮X'], self.config['低保金按钮Y'],
            self.config['低保金按钮宽'], self.config['低保金按钮高']
        )
        box_claim = self._make_box(
            self.config['领取按钮X'], self.config['领取按钮Y'],
            self.config['领取按钮宽'], self.config['领取按钮高']
        )
        box_cancel = self._make_box(
            self.config['取消按钮X'], self.config['取消按钮Y'],
            self.config['取消按钮宽'], self.config['取消按钮高']
        )

        try:
            self.log_info("执行低保金领取流程")
            self._check_stop()
            welfare_ready = self.wait_click_ocr(
                box=box_welfare_btn,
                match=re.compile(r"低保金"),
                time_out=self.config['低保金按钮超时'],
                after_sleep=0.3,
                target_height=720
            )
            if not welfare_ready:
                self.log_warning("低保金按钮未出现，跳过本次领取")
                return

            self._check_stop()
            self.wait_click_ocr(
                box=box_claim,
                match=re.compile(r"领取"),
                time_out=self.config['领取按钮超时'],
                after_sleep=0.5,
                target_height=720
            )
            self.sleep(1.0)

            self._check_stop()
            self.wait_click_ocr(
                box=box_cancel,
                match=re.compile(r"取消"),
                time_out=self.config['取消按钮超时'],
                after_sleep=0.5,
                target_height=720
            )
            self.sleep(1.0)
            self.log_info("低保金领取流程完成")

        except Exception as e:
            self.log_warning(f"低保金领取异常: {e}")
            try:
                self.wait_click_ocr(
                    box=box_cancel,
                    match=re.compile(r"取消"),
                    time_out=2,
                    after_sleep=0.5,
                    target_height=720
                )
            except Exception:
                pass

    def _sell_collections(self):
        self._check_stop()
        self.log_info("开始执行藏品出售流程")

        self._check_stop()
        self.wait_click_ocr(
            match=re.compile(r"藏品仓库"),
            time_out=self.config['出售仓库超时'],
            after_sleep=1.0,
            target_height=720
        )

        box_sell = self._make_box(
            self.config['出售X'], self.config['出售Y'],
            self.config['出售宽'], self.config['出售高']
        )
        box_confirm_sell = self._make_box(
            self.config['确认出售X'], self.config['确认出售Y'],
            self.config['确认出售宽'], self.config['确认出售高']
        )
        box_blank = self._make_box(
            self.config['空白区域X'], self.config['空白区域Y'],
            self.config['空白区域宽'], self.config['空白区域高']
        )
        box_close = self._make_box(
            self.config['关闭X_X'], self.config['关闭X_Y'],
            self.config['关闭X_宽'], self.config['关闭X_高']
        )

        quality_keys = ['品质白', '品质绿', '品质蓝', '品质紫', '品质橙', '品质红']
        quality_boxes = [
            self._make_box(
                self.config[f'{key}X'], self.config[f'{key}Y'],
                self.config[f'{key}宽'], self.config[f'{key}高']
            ) for key in quality_keys
        ]

        try:
            self._check_stop()
            self.operate_click(box_sell, after_sleep=1.0)

            for i, box_quality in enumerate(quality_boxes):
                self._check_stop()
                if self.config.get('保留品质红', False) and quality_keys[i] == '品质红':
                    self.log_info("保留品质红")
                    continue
                self.operate_click(box_quality, after_sleep=0.5)
                self.log_info(f"已选择{quality_keys[i]}品质")

            self._check_stop()
            self.operate_click(box_confirm_sell, after_sleep=self.config['确认出售等待'])
            self.log_info("已确认出售")

            self._check_stop()
            self.operate_click(box_blank, after_sleep=0.5)
            self._check_stop()
            self.operate_click(box_close, after_sleep=self.config['关闭后等待'])
            self.log_info("藏品出售流程完成")

        except Exception as e:
            self.log_warning(f"藏品出售异常: {e}")
            try:
                self.operate_click(box_blank, after_sleep=0.5)
                self.operate_click(box_close, after_sleep=0.5)
            except Exception:
                pass

    def _send_emote(self):
        self._check_stop()
        box_emote_btn = self._make_box(
            self.config['表情按钮X'], self.config['表情按钮Y'],
            self.config['表情按钮宽'], self.config['表情按钮高']
        )
        box_first_emote = self._make_box(
            self.config['首个表情X'], self.config['首个表情Y'],
            self.config['首个表情宽'], self.config['首个表情高']
        )
        self.log_info("准备发送表情包")
        self._check_stop()
        self.operate_click(box_emote_btn, after_sleep=0.8)
        self.sleep(self.config['表情包等待'])
        self._check_stop()
        self.operate_click(box_first_emote, after_sleep=0.5)
        self.log_info("表情包发送完成")

    def _input_fixed_price(self, price: int = None):
        self._check_stop()
        if price is None:
            price = self.config['固定价格']
        price_str = str(price)

        if not price_str.isdigit():
            raise ValueError(f"非法价格 '{price}'，仅支持正整数")

        self._check_stop()
        box_clear = self._make_box(
            self.config['清除键_X'], self.config['清除键_Y'],
            self.config['清除键_宽'], self.config['清除键_高']
        )
        self.operate_click(box_clear, after_sleep=0.3)

        for digit in price_str:
            self._check_stop()
            box_digit = self._make_box(
                self.config[f'数字{digit}_X'], self.config[f'数字{digit}_Y'],
                self.config[f'数字{digit}_宽'], self.config[f'数字{digit}_高']
            )
            self.operate_click(box_digit, after_sleep=0.2)

        self._check_stop()
        box_bid_confirm = self._make_box(
            self.config['确认出价X'], self.config['确认出价Y'],
            self.config['确认出价宽'], self.config['确认出价高']
        )
        self.log_info("等待确认出价按钮出现...")
        self.wait_click_ocr(
            box=box_bid_confirm,
            match=re.compile(r"确认出价"),
            time_out=self.config['面板加载超时'],
            after_sleep=0.5,
            target_height=720
        )
        self.log_info(f"已输入价格 {price_str} 并确认")

        self._check_stop()
        box_exception_confirm = self._make_box(
            self.config['异常确认X'], self.config['异常确认Y'],
            self.config['异常确认宽'], self.config['异常确认高']
        )
        self.operate_click(box_exception_confirm, after_sleep=0.3)
        self.log_info("已点击异常确认框")

    def run(self):
        max_count = self.config['循环次数']
        sell_interval = self.config['出售藏品间隔次数']
        count = 0
        self.info_set("已完成次数", count)

        box_match = self._make_box(
            self.config['匹配按钮X'], self.config['匹配按钮Y'],
            self.config['匹配按钮宽'], self.config['匹配按钮高']
        )
        box_confirm = self._make_box(
            self.config['确认按钮X'], self.config['确认按钮Y'],
            self.config['确认按钮宽'], self.config['确认按钮高']
        )
        box_bid = self._make_box(
            self.config['出价按钮X'], self.config['出价按钮Y'],
            self.config['出价按钮宽'], self.config['出价按钮高']
        )

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
                    self.info_set("已完成次数", count)
                    self.log_info(f"拍卖完成 {count}/{max_count if max_count > 0 else '∞'}")

                    if sell_interval > 0 and count % sell_interval == 0:
                        self._sell_collections()
                except TaskDisabledException:
                    self.log_info("用户停止任务")
                    raise
                except Exception as e:
                    self.log_error(f"发生未知错误: {e}，下一轮重新开始")
                    self.sleep(self.config['错误重试等待'])
        finally:
            if max_count > 0:
                self.log_info(f"自动拍卖结束，共完成 {count} 次")
            else:
                self.log_info(f"自动拍卖已停止，共完成 {count} 次")

    def _do_one_auction(self, box_match, box_confirm, box_bid,
                        re_match, re_confirm, re_bid, re_skip):
        matched_type = None

        while True:
            self._check_stop()
            self.log_info("等待匹配开始...")

            if self.ocr(box=box_bid, match=re_bid, target_height=720):
                self.log_info("检测到已在出价界面，跳过匹配步骤")
                matched_type = 'bid'
                break

            if self.ocr(box=box_confirm, match=re_confirm, target_height=720):
                self.log_info("检测到已在确认界面，跳过匹配步骤")
                matched_type = 'confirm'
                break

            try:
                self._check_stop()
                self.wait_click_ocr(
                    box=box_match,
                    match=re_match,
                    time_out=self.config['匹配点击超时'],
                    target_height=720
                )
                self.log_info("已尝试点击开始匹配，验证界面是否跳转...")

                self._check_stop()
                matched_confirm = self.wait_ocr(
                    box=box_confirm,
                    match=re_confirm,
                    time_out=self.config['匹配验证超时'],
                    target_height=720
                )
                matched_bid = self.wait_ocr(
                    box=box_bid,
                    match=re_bid,
                    time_out=self.config['匹配验证超时'],
                    target_height=720
                )

                if matched_confirm:
                    self.log_info("确认按钮已出现，匹配真正成功！")
                    matched_type = 'confirm'
                    break
                elif matched_bid:
                    self.log_info("检测到跳转到出价界面，匹配成功！")
                    matched_type = 'bid'
                    break
                else:
                    self.log_warning("点击开始匹配后未出现确认或出价，可能是假点击，重新尝试")
                    self.operate_click(box_match, after_sleep=1)
                    continue

            except WaitFailedException:
                self.log_info("开始匹配超时，重新点击开始匹配并重试")
                self.operate_click(box_match)
                self.sleep(0.5)

        self._check_stop()
        self.log_info("已成功进入拍卖环节")
        self.sleep(self.config['点击后缓冲'])

        if matched_type == 'confirm':
            self.log_info("等待确认")
            self.wait_ocr(
                box=box_confirm,
                match=re_confirm,
                time_out=self.config['确认等待超时'],
                target_height=720
            )
            self.log_info("确认按钮已出现，正在点击...")
            self.operate_click(box_confirm, after_sleep=0)
            self.log_info("已点击确认")
        else:
            self.log_info("已跳过确认环节，直接进入出价")

        while True:
            self._check_stop()
            self.log_info("等待出价")
            self.wait_click_ocr(
                box=box_bid,
                match=re_bid,
                time_out=self.config['出价点击超时'],
                target_height=720
            )
            self.log_info("已点击出价")
            self.sleep(self.config['点击后缓冲'])

            box_bid_confirm = self._make_box(
                self.config['确认出价X'], self.config['确认出价Y'],
                self.config['确认出价宽'], self.config['确认出价高']
            )

            self._check_stop()
            self.log_info("等待数字面板加载...")
            panel_ready = self.wait_ocr(
                box=box_bid_confirm,
                match=re.compile(r"确认出价"),
                time_out=self.config['面板加载超时'],
                target_height=720
            )
            if not panel_ready:
                self.log_warning("点击出价后未出现数字面板，可能点击无效，重新开始拍卖")
                raise WaitFailedException("点击出价后未出现数字面板")
            self.log_info("数字面板已加载")

            self._input_fixed_price()

            self._check_stop()
            self.log_info("出价完成")
            self.sleep(self.config['点击后缓冲'])
            if self.config.get('启用表情包', True):
                self._send_emote()

            self.log_info("检查结果区域 / 等待流程结束")
            auction_finished = False

            while True:
                self._check_stop()
                self.next_frame()

                if self.ocr(box=box_match, match=re_match, target_height=720):
                    self.log_info("检测到已回到开始匹配界面，本轮拍卖（被中断）结束")
                    auction_finished = True
                    break

                box_skip_area = self._make_box(
                    self.config['跳过识别区域X'], self.config['跳过识别区域Y'],
                    self.config['跳过识别区域宽'], self.config['跳过识别区域高']
                )
                skip_results = self.ocr(
                    box=box_skip_area,
                    match=[re_skip],
                    target_height=720
                )
                if skip_results:
                    matched_box = skip_results[0]
                    self.log_info("检测到跳过动画，本轮拍卖结束")
                    self.operate_click(matched_box, after_sleep=0.5)

                    box_exit = self._make_box(
                        self.config['退出按钮X'], self.config['退出按钮Y'],
                        self.config['退出按钮宽'], self.config['退出按钮高']
                    )
                    self.log_info("等待退出按钮出现...")
                    self.wait_click_ocr(
                        box=box_exit,
                        match=re.compile(r"退出"),
                        time_out=self.config['退出点击超时'],
                        after_sleep=0.5,
                        target_height=720
                    )
                    self.log_info("已点击退出按钮")

                    if self.config.get('启用低保金', True):
                        self._try_claim_welfare()
                    auction_finished = True
                    break

                if self.ocr(box=box_bid, match=re_bid, target_height=720):
                    self.log_info("检测到新一轮出价，继续出价循环")
                    break

                self.sleep(0.5)

            if auction_finished:
                break