from ok import Logger, TriggerTask

from src import text_black_color
from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask
from src.utils import image_utils as iu

logger = Logger.get_logger(__name__)


class FastTravelTask(BaseNTETask, TriggerTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {"_enabled": False}
        self.name = "快速传送"
        self.description = "地图中自动点击传送"
        self.match = ["Teleport", "传送"]
        self.default_config.update(
            {
                "匹配文字": "",
            }
        )
        self.config_description.update(
            {
                "匹配文字": "供非中/英语用户自定义传送文字, 逗号分隔\n例: Teleport, 传送",
            }
        )

    def run(self):
        if self.scene.is_in_team(self.is_in_team) or not self.find_one(
            Labels.close_button, threshold=0.8
        ):
            return
        if btn := self.find_traval_button():
            if config_match := self.config.get("匹配文字"):
                self.match = [s.strip() for s in config_match.split(",")]
            to_x = (btn.x + btn.width) / self.width
            results = self.ocr(
                box=self.box_of_screen(0.7438, 0.8736, to_x, 0.9118),
                match=self.match,
                frame_processor=lambda image: iu.create_color_mask(
                    image, text_black_color, invert=True
                ),
            )

            if results:
                self.click_traval_button(btn)
                return
