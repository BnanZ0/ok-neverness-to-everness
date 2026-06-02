from src.char.BaseChar import BaseChar


class Jiuyuan(BaseChar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def do_perform(self):
        self.wait_intro()
        self.click_ultimate()
        if self.click_skill()[0]:
            self.continues_normal_attack(1.4)
            self.sleep(0.5)
        self.fire_bullets()

    def fire_bullets(self):
        box = self.task.box_of_screen(
            0.4191, 0.8799, 0.4348, 0.9076, name="jiuyuan_bullet", hcenter=True
        )
        if not self.has_bullets(box):
            return
        self.heavy_attack()
        self.sleep(0.1)

    def has_bullets(self, box):
        pct = self.task.calculate_color_percentage(bullet_color, box)
        # self.logger.debug(f"Jiuyuan has_bullets {pct}")
        return pct > 0.1


bullet_color = {
    "r": (97, 253),
    "g": (101, 181),
    "b": (168, 255),
}
