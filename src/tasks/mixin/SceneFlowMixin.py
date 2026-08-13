from ok import BaseTask, TaskDisabledException

from src.scene_flow import SceneFlow


class SceneFlowMixin(BaseTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scene_flow = SceneFlow()
        self.scene_flow.propagate(TaskDisabledException)
        self.scene_flow.before_step(self.next_frame)

    def wait_until(
        self,
        condition,
        time_out=0,
        pre_action=None,
        post_action=None,
        settle_time=-1,
        raise_if_not_found=False,
    ):
        """Make ordinary waits SceneFlow interrupt safe points while active."""
        if not self.scene_flow.active or self.scene_flow.handling_interrupt:
            return super().wait_until(
                condition,
                time_out=time_out,
                pre_action=pre_action,
                post_action=post_action,
                settle_time=settle_time,
                raise_if_not_found=raise_if_not_found,
            )

        def observed_condition():
            self.scene_flow.safe_point()
            return condition()

        return super().wait_until(
            observed_condition,
            time_out=time_out,
            pre_action=pre_action,
            post_action=post_action,
            settle_time=settle_time,
            raise_if_not_found=raise_if_not_found,
        )
