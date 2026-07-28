
from src.char.Support import Support


class Iroi(Support):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def combat_plan(self, context):
        skill = self.click_skill_action()
        ultimate = self.click_ultimate_action()

        def entry():
            skill_result = yield skill
            if skill_result and self.ultimate_available():
                self.sleep(0.8)
            yield ultimate

        return self.plan(skill, ultimate, entry=entry)

    def click_ultimate(self, send_click=True, wait_if_no_cd=0):
        try:
            ret = super().click_ultimate(send_click=send_click, wait_if_no_cd=wait_if_no_cd)
            if ret:
                self.sleep(0.7)
            return ret
        finally:
            if ret:
                self.task.mouse_up()

    def _wait_ultimate_unfreeze(self, start, click=False):
        self.task.mouse_down()
        return super()._wait_ultimate_unfreeze(start=start, click=click)
