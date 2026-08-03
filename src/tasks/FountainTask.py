import re
import time

from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask, interac_pink_color
from src.tasks.trigger.SkipDialogTask import SkipDialogTask
from src.utils import image_utils as iu


class FountainTask(BaseNTETask):
    CONF_SIGN_MODE = "签到方式"
    SIGN_MODE_SIGN = "签到"
    SIGN_MODE_COIN = "捞币"
    DOMAIN_ENTRY_POS = (0.668, 0.150)
    DOMAIN_CONFIRM_POS = (0.917, 0.335)
    PHONE_BOOTH_BOX = (0.300, 0.420, 0.375, 0.545)
    BOOKSHOP_LOGO_BOX = (0.092, 0.170, 0.113, 0.206)
    BOOKSHOP_LOGO_SECOND_BOX = (0.080, 0.180, 0.096, 0.210)
    ICECAR_LIGHT_BOX = (0.650, 0.350, 0.885, 0.600)
    FOUNTAIN_SIGN_COUNT_BOX = (0.695, 0.528, 0.730, 0.565)
    FOUNTAIN_SIGN_BTN_BOX = (0.655, 0.570, 0.790, 0.645)
    BOOKSHOP_LOGO_TIMEOUT = 15
    ICECAR_LIGHT_TIMEOUT = 40
    INTERAC_TIMEOUT = 30
    SIGN_SKIP_TIMEOUT = 20
    TASK_TIMEOUT = 180
    TASK_RETRY_COUNT = 1
    FOUNTAIN_SIGN_COUNT_RE = re.compile(r"\d")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._check_confirm_timer = 0
        self.name = "喷泉签到"
        self.icon = FluentIcon.SYNC
        self.group_name = "日常/周常"
        self.group_icon = FluentIcon.CALENDAR
        self.default_config.update({self.CONF_SIGN_MODE: self.SIGN_MODE_SIGN})
        self.config_description.update({self.CONF_SIGN_MODE: "选择喷泉签到或捞币"})
        self.config_type.update(
            {
                self.CONF_SIGN_MODE: {
                    "type": "drop_down",
                    "options": [self.SIGN_MODE_SIGN, self.SIGN_MODE_COIN],
                }
            }
        )

    def run(self):
        super().run()
        try:
            self.do_run(self.config.get(self.CONF_SIGN_MODE, self.SIGN_MODE_SIGN))
        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_error("FountainTask Error", e, notify=True)
            raise

    def do_run(self, sign_mode=SIGN_MODE_SIGN):
        last_error = None
        for attempt in range(1, self.TASK_RETRY_COUNT + 2):
            self._fountain_task_start = time.time()
            self.log_info(f"attempt {attempt}/{self.TASK_RETRY_COUNT + 1}")
            try:
                if self.run_fountain_flow(sign_mode):
                    return True
            except TaskDisabledException:
                raise
            except Exception as e:
                last_error = e
                self.log_warning(f"attempt {attempt} failed: {e}")
            finally:
                self._fountain_task_start = None
                self.release_fountain_move_keys()

            if attempt <= self.TASK_RETRY_COUNT:
                self.log_info("retry once")

        if last_error is not None:
            raise last_error
        raise RuntimeError("failed after retries")

    def run_fountain_flow(self, sign_mode):
        self.transport_to_fountain_teleport()
        self.check_fountain_task_timeout()
        self.run_to_fountain()
        self.check_fountain_task_timeout()
        result = self.fountain_sign_in(sign_mode)
        self.check_fountain_task_timeout()
        return result

    def check_fountain_task_timeout(self):
        start = getattr(self, "_fountain_task_start", None)
        if start is not None and time.time() - start >= self.TASK_TIMEOUT:
            raise TimeoutError(f"timed out after {self.TASK_TIMEOUT}s")

    def release_fountain_move_keys(self):
        self.send_key_up("w")
        self.send_key_up("a")
        self.send_key_up("d")

    def transport_to_fountain_teleport(self):
        self.ensure_main(time_out=30)
        self.open_f1_domain_page()
        self.operate_click(*self.DOMAIN_ENTRY_POS, after_sleep=1)
        self.operate_click(*self.DOMAIN_CONFIRM_POS, after_sleep=2)
        self.click_traval_button()
        self.wait_in_team(time_out=30)
        self.sleep(0.5)
        self.click_fountain_map_teleport(time_out=5)
        self.wait_in_team_and_world(time_out=30)

    def run_to_fountain(self):
        self.middle_click(after_sleep=0.4)
        self.send_key_down("a", after_sleep=0.4)
        self.send_key("lshift", after_sleep=0.4)
        try:
            self.wait_until(
                self.find_bookshop_logo,
                time_out=self.BOOKSHOP_LOGO_TIMEOUT,
                raise_if_not_found=True,
            )
            self.sleep(1)
        finally:
            self.send_key_up("a")

        self.middle_click(after_sleep=0.4)
        self.send_key_down("a", after_sleep=0.2)
        try:
            self.wait_until(
                self.find_second_bookshop_logo,
                time_out=self.BOOKSHOP_LOGO_TIMEOUT,
                raise_if_not_found=True,
            )
        finally:
            self.send_key_up("a")

        self.send_key_down("w", after_sleep=0.4)
        self.send_key("lshift", after_sleep=0.4)
        self.sleep(20)
        try:
            self.wait_until(
                self.find_icecar_light,
                time_out=self.ICECAR_LIGHT_TIMEOUT,
                raise_if_not_found=True,
            )
        finally:
            self.send_key_up("w")

        self.send_key("d", down_time=0.5, after_sleep=0.2)
        self.middle_click(after_sleep=0.2)
        self.send_key_down("w", after_sleep=0.4)
        self.send_key("lshift", after_sleep=2)
        self.send_key("a", down_time=0.5, after_sleep=0.4)
        self.sleep(5)
        self.send_key("d", down_time=1, after_sleep=0.4)
        self.send_key("space", after_sleep=0.4)
        self.sleep(5)
        try:
            return self.wait_until(
                self.find_interac,
                time_out=self.INTERAC_TIMEOUT,
                raise_if_not_found=True,
            )
        finally:
            self.send_key_up("w")

    def find_bookshop_logo(self):
        box = self.box_of_screen(*self.BOOKSHOP_LOGO_BOX, name="bookshop_logo_area")
        return self.find_one(Labels.bookshop_logo, box=box)

    def find_second_bookshop_logo(self):
        box = self.box_of_screen(
            *self.BOOKSHOP_LOGO_SECOND_BOX, name="bookshop_logo_second_area"
        )
        return self.find_one(Labels.bookshop_logo, box=box)

    def find_icecar_light(self):
        box = self.box_of_screen(*self.ICECAR_LIGHT_BOX, name="icecar_light_area")
        return self.find_one(Labels.icecar_lights, box=box, threshold=0.75)

    def fountain_sign_in(self, sign_mode):
        sign_count = self.read_fountain_sign_count()
        if sign_count == -1:
            self.log_warning("喷泉签到OCR识别次数失败")
            return False
        if sign_count == 0:
            self.log_info("当日已经完成喷泉签到")
            return True
        if sign_count != 1:
            self.log_warning(f"识别到未知喷泉签到次数 {sign_count}, 喷泉签到失败")
            return False

        self.send_key("f", after_sleep=0.4)
        sign_btn = self.wait_until(
            self.find_sign_in_btn,
            time_out=self.INTERAC_TIMEOUT,
            raise_if_not_found=True,
        )
        self.click_sign_action(sign_btn, sign_mode)
        if not self.wait_skip_dialog_until_world(self.SIGN_SKIP_TIMEOUT):
            self.log_warning("对话异常，无法返回大世界")
            return False
        signed_count = self.read_fountain_sign_count()
        if signed_count == 0:
            self.log_info("喷泉签到完成")
            return True

        self.log_warning(f"喷泉签到失败, 当前可签到次数={signed_count}")
        return False

    def find_sign_in_btn(self):
        box = self.box_of_screen(
            *self.FOUNTAIN_SIGN_BTN_BOX, name="fountain_sign_btn_area"
        )
        regions = iu.find_color_enriched_regions(
            interac_pink_color,
            box,
            self.frame,
            min_area=0.03,
        )
        if not regions:
            return None
        return max(regions, key=lambda region: region.width * region.height)

    def click_sign_action(self, sign_btn, sign_mode):
        self.log_info("图色识别，并确定点击选项")
        target = sign_btn
        if sign_mode == self.SIGN_MODE_COIN:
            target = sign_btn.copy(
                y_offset=self.height_of_screen(0.07),
                name="fountain_sign_coin_target",
            )
        self.operate_click(target, after_sleep=1)

    def find_skip(self):
        return SkipDialogTask.find_skip(self)

    def try_click_skip(self):
        return SkipDialogTask.try_click_skip(self)

    def skip_confirm(self):
        return SkipDialogTask.skip_confirm(self)

    def check_skip(self):
        return SkipDialogTask.check_skip(self)

    def wait_skip_dialog_until_world(self, time_out=10):
        def check_skip_and_world():
            self.check_skip()
            return self.in_team_and_world()

        return self.wait_until(
            check_skip_and_world,
            time_out=time_out,
            raise_if_not_found=False,
        )

    def read_fountain_sign_count(self):
        results = self.wait_ocr(
            *self.FOUNTAIN_SIGN_COUNT_BOX,
            match=self.FOUNTAIN_SIGN_COUNT_RE,
            time_out=3,
            raise_if_not_found=False,
        )
        if not results:
            self.log_warning("fountain sign OCR raw results: []")
            return -1

        recognized_texts = [str(result.name).strip() for result in results]
        self.log_info(f"fountain sign OCR raw results: {recognized_texts}")
        for text in recognized_texts:
            match = self.FOUNTAIN_SIGN_COUNT_RE.search(text)
            if match:
                sign_count = int(match.group(0))
                self.log_info(f"fountain sign OCR parsed digit: {sign_count}")
                return sign_count
        return -1

    def click_fountain_map_teleport(self, threshold=0.7, time_out=5):
        self.ensure_main(time_out=30)
        self.wait_until(
            lambda: self.find_one(Labels.map_city_tycoon_activities),
            time_out=10,
            pre_action=lambda: self.send_key("m", interval=2),
            raise_if_not_found=True,
        )

        def find_near_fountain_teleport():
            box = self.box_of_screen(*self.PHONE_BOOTH_BOX, name="fountain_phone_booth")
            return self.find_best_match_in_box(
                box, [Labels.map_small_teleport], threshold=threshold
            )

        teleport = self.wait_until(
            find_near_fountain_teleport,
            time_out=time_out,
            raise_if_not_found=True,
        )
        self.log_info(f"找到喷泉最近的电话亭 {teleport}")
        self.operate_click(
            teleport, action_name="click_fountain_map_teleport", interval=1
        )
        self.sleep(0.5)
        self.click_traval_button()
        return teleport
