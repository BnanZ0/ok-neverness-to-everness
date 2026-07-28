from ok import BaseTask, TaskDisabledException

from src.flow import Flow


class FlowTaskMixin(BaseTask):
    """Adapt Flow to tasks that provide frame refresh and monthly-card handling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.flow = Flow()
        self.flow.propagate(TaskDisabledException)
        self.flow.before_step(self.next_frame)

    def wait_until(
        self,
        condition,
        time_out=0,
        pre_action=None,
        post_action=None,
        settle_time=-1,
        raise_if_not_found=False,
    ):
        """Make ordinary waits a Flow interrupt safe point while Flow is active."""
        if not self.flow.active or self.flow.handling_interrupt:
            return super().wait_until(
                condition,
                time_out=time_out,
                pre_action=pre_action,
                post_action=post_action,
                settle_time=settle_time,
                raise_if_not_found=raise_if_not_found,
            )

        def observed_condition():
            self.flow.safe_point()
            return condition()

        return super().wait_until(
            observed_condition,
            time_out=time_out,
            pre_action=pre_action,
            post_action=post_action,
            settle_time=settle_time,
            raise_if_not_found=raise_if_not_found,
        )
