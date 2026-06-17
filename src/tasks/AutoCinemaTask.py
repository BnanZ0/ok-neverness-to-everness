import re

from qfluentwidgets import FluentIcon
from src.Labels import Labels
from src import text_black_color
from src.tasks.BaseNTETask import BaseNTETask
from src.utils import image_utils as iu

class AutoCinemaTask(BaseNTETask):
    # --- 配置项键名 ---
    CONF_MOVIE_CHAR = "邀约角色"
    CONF_TP_CHAR = "匹配文字"
    CONF_RUN_CHAR = "薄荷位置"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动影院邀约"
        self.description = "自动影院邀约，每日白嫖200好感度。"
        self.match = ["Teleport", "传送"]
        self.instructions = ""
        self.group_name = "日常/周常"
        self.icon = FluentIcon.MOVIE
        self.support_schedule_task = True
        self.default_config.update(
            {
                self.CONF_RUN_CHAR: "1",
                self.CONF_MOVIE_CHAR: "薄荷",
                self.CONF_TP_CHAR: "",
            }
        )
        self.config_description.update(
            {
                self.CONF_RUN_CHAR: "跑图角色为薄荷，选择薄荷在几号位",
                self.CONF_MOVIE_CHAR: "在这里输入你要邀约的角色，会用于OCR识别。",
                self.CONF_TP_CHAR: "供非中/英语用户自定义传送文字, 逗号分隔\n例: Teleport, 传送",
            }
        )
        self.config_type.update(
            {
                self.CONF_RUN_CHAR: {
                    "type": "drop_down",
                    "options": ["1","2","3","4"],
                }
            }
        )

    # 主程序
    def run(self):
        self.log_info(f"{self.name}开始")
        self.ensure_main(esc=True, time_out=60)
        self.sleep(0.64)
        self.send_key(self.config.get(self.CONF_RUN_CHAR,"1"), down_time=0.15)
        self.sleep(0.64)
        self.send_key('f1', down_time=0.15)
        self.sleep(2.56)
        self.operate_click(0.05, 0.50, down_time=0.15)
        self.sleep(2.56)
        self.operate_click(0.90, 0.15, down_time=0.15)
        self.sleep(2.56)
        for i in range(3):
            self.scroll_relative(0.50, 0.50, -5)
            self.sleep(1.14)
        self.operate_click(0.86, 0.78, down_time=0.15)
        self.sleep(2.56)
        if not self.click_tp():
            raise RuntimeError("未能确认影院传送，停止自动影院邀约")
        self.sleep(2.56)
        self.ensure_main(esc=True, time_out=60)
        self.log_info("寻路到影院前台")
        self.sleep(1.14)
        self.to_front_desk()
        self.sleep(1.14)
        self.send_key('f', down_time=0.15)
        self.sleep(1.14)
        self.operate_click(0.50, 0.50, down_time=0.15)
        self.sleep(1.14)
        self.send_key('f', down_time=0.15)
        self.sleep(2.56)
        self.operate_click(0.50, 0.50, down_time=0.15)
        self.log_info("进行邀约!")
        self.sleep(3.14)
        self.select_date()
        self.log_info("邀约成功!")
        self.sleep(11.4)
        self.date_movie()
        self.ensure_main(esc=True, time_out=64)
        self.log_info(f"{self.name}完成")

    # 寻路到影院前台
    def to_front_desk(self):
        self.sleep(1.14)
        self.send_key('w', down_time=1.78, after_sleep=0.21)
        self.send_key('d', down_time=2.62, after_sleep=0.19)
        self.send_key('w', down_time=0.10)
        self.send_key('w', down_time=0.13, after_sleep=0.16)
        self.send_key('d', down_time=0.12, after_sleep=0.31)
        self.send_key('s', down_time=0.11)
        self.send_key('s', down_time=0.10, after_sleep=0.46)
        self.click_relative(0.5396, 0.0009, key="middle", down_time=0.15) 
        self.sleep(0.42)
        self.send_key('d', down_time=0.45, after_sleep=0.18)
        self.send_key_down('w', after_sleep=4.12)
        try:
            self.send_key('d', down_time=0.99, after_sleep=1.03)
            self.send_key('d', down_time=0.61, after_sleep=3.78)
        finally:
            self.send_key_up('w', after_sleep=2.16)

    # 选择邀约电影对象
    def select_date(self):
        have_date = False
        regex_str = self.config.get(self.CONF_MOVIE_CHAR,"薄荷")
        match_regex = re.compile(regex_str)
        attempts = 0
        while self.enabled and not have_date and attempts < 12:
            if self.ocr(0.77, 0.22, 0.9, 0.86, match=match_regex):
                have_date =True
                self.sleep(1.14)
                btn_date = self.wait_ocr(0.77, 0.22, 0.9, 0.86, match=match_regex, time_out=1.14)
                confirm_range = (0.6465, 0.6125, 0.7047, 0.7049)
                self.wait_until(
                    lambda: self.find_confirm(confirm_range),
                    pre_action=lambda btn=btn_date: self.operate_click(btn, interval=3.14),
                    time_out=30,
                    raise_if_not_found=True,
                )
                self.sleep(1.14)
                self.wait_click_confirm(range=(0.6465, 0.6125, 0.7047, 0.7049))
                self.sleep(1.14)
                break
            self.scroll_relative(0.80, 0.50, -4)
            attempts += 1
            self.sleep(1.14)
        if self.enabled and not have_date:
            raise RuntimeError(f"未找到可邀约角色: {regex_str}")
            

    # 看完电影
    def date_movie(self):
        self.sleep(1.14)
        self.send_key('z', down_time=0.16, after_sleep=1.14)
        self.sleep(1.14)
        self.send_key('z', down_time=0.16, after_sleep=1.14)
        self.sleep(1.14)
        self.send_key('z', down_time=0.16, after_sleep=1.14)
        self.sleep(1.14)
        self.send_key('z', down_time=0.16, after_sleep=1.14)
        self.sleep(1.14)

    # 点击传送
    def click_tp(self):
        if self.scene.is_in_team(self.is_in_team) or not self.find_one(
            Labels.close_button, threshold=0.8
        ):
            return False
        if btn := self.find_traval_button():
            match_words = self.match
            if config_match := self.config.get(self.CONF_TP_CHAR):
                match_words = [s.strip() for s in config_match.split(",") if s.strip()] or self.match
            to_x = (btn.x + btn.width) / self.width
            results = self.ocr(
                box=self.box_of_screen(0.7438, 0.8736, to_x, 0.9118),
                match=match_words,
                frame_processor=lambda image: iu.create_color_mask(
                    image, text_black_color, invert=True
                ),
            )

            if results:
                self.click_traval_button(btn)
                return True
        return False
