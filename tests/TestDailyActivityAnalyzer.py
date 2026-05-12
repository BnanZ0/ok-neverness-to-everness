import json
import unittest

import cv2
import numpy as np

from src.Labels import Labels
from src.tasks.DailyActivityAnalyzer import DailyActivityAnalyzer, DailyActivityState
from src.tasks.DailyUIContext import ReadOnlyUIContext


class FakeBox:
    def __init__(self, name, x=0, y=0, width=1, height=1, confidence=1.0):
        self.name = name
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.confidence = confidence


class FakeDailyActivityTask:
    width = 1920
    height = 1080

    def __init__(self, frame, panel_detected=True, ocr_boxes=None):
        self.frame = frame
        self.panel_detected = panel_detected
        self.ocr_boxes = ocr_boxes or []
        self.reward_box = FakeBox(Labels.box_f1_activity_reward.value, 658, 217, 1016, 49)

    def find_one(self, label):
        if label == Labels.f1_activity_panel and self.panel_detected:
            return FakeBox(label.value, 288, 217, 65, 66)
        return None

    def get_box_by_name(self, label):
        if label == Labels.box_f1_activity_reward:
            return self.reward_box
        return None

    def ocr_ui(self, *args, **kwargs):
        return self.ocr_boxes


class TestDailyActivityAnalyzer(unittest.TestCase):
    def make_frame(
        self,
        full_activity=False,
        claimable_mission=False,
        activity_score=None,
        milestone_claimable=(),
        milestone_locked=(),
        go_buttons=0,
    ):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        if full_activity:
            for x in (684, 926, 1165, 1404, 1646):
                cv2.circle(frame, (x, 242), 18, (180, 40, 255), -1)
        if claimable_mission:
            cv2.rectangle(frame, (360, 830), (580, 880), (180, 40, 255), -1)
        if activity_score is not None:
            start_x = int(1920 * DailyActivityAnalyzer.PROGRESS_START_X_RATIO)
            end_x = int(1920 * DailyActivityAnalyzer.PROGRESS_END_X_RATIO)
            filled_x = int(start_x + (end_x - start_x) * activity_score / 100)
            y1 = int(1080 * DailyActivityAnalyzer.PROGRESS_REGION[1])
            y2 = int(1080 * DailyActivityAnalyzer.PROGRESS_REGION[3])
            cv2.rectangle(frame, (start_x, y1), (filled_x, y2), (255, 255, 0), -1)
        for value, center_x_ratio in zip(
            DailyActivityAnalyzer.MILESTONE_VALUES,
            DailyActivityAnalyzer.MILESTONE_CENTER_X_RATIOS,
        ):
            if value not in milestone_claimable and value not in milestone_locked:
                continue
            center = (
                int(1920 * center_x_ratio),
                int(1080 * DailyActivityAnalyzer.MILESTONE_CENTER_Y_RATIO),
            )
            color = (255, 120, 20) if value in milestone_claimable else (80, 80, 80)
            cv2.circle(frame, center, 28, color, -1)
        for index in range(go_buttons):
            left = 340 + index * 330
            cv2.rectangle(frame, (left, 830), (left + 220, 880), (235, 235, 235), -1)
        return frame

    def test_analyze_full_activity_panel(self):
        task = FakeDailyActivityTask(self.make_frame(full_activity=True))

        analysis = DailyActivityAnalyzer(task).analyze()

        self.assertEqual(analysis.state, DailyActivityState.NO_ACTION_NEEDED)
        self.assertTrue(analysis.panel_detected)
        self.assertTrue(analysis.daily_tab_detected)
        self.assertTrue(analysis.activity_full)
        self.assertTrue(analysis.all_daily_done)
        self.assertFalse(analysis.has_go_button)
        self.assertTrue(analysis.no_claimable_reward)
        self.assertEqual(analysis.reason, "今日活跃度已完成")

    def test_analyze_panel_detected(self):
        task = FakeDailyActivityTask(self.make_frame())

        analysis = DailyActivityAnalyzer(task).analyze()

        self.assertTrue(analysis.panel_detected)
        self.assertTrue(analysis.daily_tab_detected)
        self.assertEqual(analysis.state, DailyActivityState.UNKNOWN)

    def test_analyzer_accepts_read_only_ui_context(self):
        task = FakeDailyActivityTask(self.make_frame(claimable_mission=True))
        context = ReadOnlyUIContext(task)

        analysis = DailyActivityAnalyzer(context).analyze()

        self.assertEqual(analysis.state, DailyActivityState.HAS_CLAIMABLE_REWARD)
        self.assertTrue(analysis.has_claimable_reward)

    def test_analyze_detects_claimable_daily_mission_button(self):
        task = FakeDailyActivityTask(self.make_frame(claimable_mission=True))

        analysis = DailyActivityAnalyzer(task).analyze()

        self.assertEqual(analysis.state, DailyActivityState.HAS_CLAIMABLE_REWARD)
        self.assertTrue(analysis.has_claimable_reward)
        self.assertFalse(analysis.no_claimable_reward)
        self.assertEqual(analysis.reason, "检测到可领取每日任务奖励")
        buttons = DailyActivityAnalyzer(task).find_claimable_mission_buttons()
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].name, Labels.f1_activity_mission.value)

    def test_analyze_distinguishes_score_milestones_and_go_buttons(self):
        task = FakeDailyActivityTask(
            self.make_frame(
                activity_score=90,
                milestone_claimable=(20, 40, 60, 80),
                milestone_locked=(100,),
                go_buttons=4,
            )
        )

        analysis = DailyActivityAnalyzer(task).analyze()

        self.assertEqual(analysis.page.activity_score, 90)
        self.assertEqual(analysis.page.milestone_claimable_values, [20, 40, 60, 80])
        self.assertEqual(analysis.page.milestone_locked_values, [100])
        self.assertTrue(analysis.has_go_button)
        self.assertFalse(analysis.has_claimable_reward)
        self.assertEqual(len(analysis.page.task_cards), 4)
        self.assertTrue(all(card.action == "前往" for card in analysis.page.task_cards))

    def test_task_card_ocr_text_stays_inside_each_card(self):
        task = FakeDailyActivityTask(
            self.make_frame(go_buttons=2),
            ocr_boxes=[
                FakeBox("累计消耗180点本性像素", x=360, y=690, width=180, height=30),
                FakeBox("0/180", x=430, y=770, width=80, height=30),
                FakeBox("+60", x=430, y=610, width=80, height=30),
                FakeBox("释放3次极轨攻击", x=700, y=690, width=160, height=30),
                FakeBox("1/3", x=760, y=770, width=60, height=30),
                FakeBox("+20", x=760, y=610, width=80, height=30),
            ],
        )

        page = DailyActivityAnalyzer(task, enable_text_ocr=True).analyze().page

        self.assertEqual([card.title for card in page.task_cards], ["累计消耗180点本性像素", "释放3次极轨攻击"])
        self.assertEqual([card.progress_text for card in page.task_cards], ["0/180", "1/3"])
        self.assertEqual([card.reward_points for card in page.task_cards], [60, 20])

    def test_task_cards_mark_claimable_and_go_states(self):
        frame = self.make_frame()
        cv2.rectangle(frame, (360, 830), (580, 880), (180, 40, 255), -1)
        cv2.rectangle(frame, (700, 830), (920, 880), (235, 235, 235), -1)
        task = FakeDailyActivityTask(
            frame,
            ocr_boxes=[
                FakeBox("释放3次极轨攻击", x=380, y=690, width=160, height=30),
                FakeBox("3/3", x=430, y=770, width=60, height=30),
                FakeBox("+20", x=430, y=610, width=80, height=30),
                FakeBox("赠送1次礼物", x=720, y=690, width=140, height=30),
                FakeBox("0/1", x=780, y=770, width=60, height=30),
                FakeBox("+20", x=780, y=610, width=80, height=30),
            ],
        )

        page = DailyActivityAnalyzer(task, enable_text_ocr=True).analyze().page

        self.assertEqual([card.action for card in page.task_cards], ["领取", "前往"])
        self.assertEqual([card.state for card in page.task_cards], ["claimable", "go"])
        self.assertEqual(
            [card.title for card in page.task_cards],
            ["释放3次极轨攻击", "赠送1次礼物"],
        )
        self.assertEqual([card.progress_text for card in page.task_cards], ["3/3", "0/1"])
        self.assertEqual(len(page.claimable_task_cards), 1)
        self.assertEqual(len(page.go_task_cards), 1)

    def test_task_card_button_text_can_resolve_complete_and_unknown_actions(self):
        frame = self.make_frame(go_buttons=2)
        task = FakeDailyActivityTask(
            frame,
            ocr_boxes=[
                FakeBox("每日登录1次", x=360, y=690, width=140, height=30),
                FakeBox("1/1", x=430, y=770, width=60, height=30),
                FakeBox("完成", x=410, y=840, width=70, height=30),
                FakeBox("查看异常", x=700, y=690, width=140, height=30),
                FakeBox("0/1", x=760, y=770, width=60, height=30),
                FakeBox("查看", x=750, y=840, width=70, height=30),
            ],
        )

        page = DailyActivityAnalyzer(task, enable_text_ocr=True).analyze().page

        self.assertEqual([card.action for card in page.task_cards], ["完成", "unknown"])
        self.assertEqual([card.state for card in page.task_cards], ["completable", "unknown"])
        self.assertEqual([card.button_text for card in page.task_cards], ["完成", "查看"])

    def test_analyze_panel_not_found(self):
        task = FakeDailyActivityTask(self.make_frame(), panel_detected=False)

        analysis = DailyActivityAnalyzer(task).analyze()

        self.assertEqual(analysis.state, DailyActivityState.PANEL_NOT_FOUND)
        self.assertFalse(analysis.panel_detected)
        self.assertFalse(analysis.daily_tab_detected)

    def test_unknown_state_does_not_guess_claimable_reward(self):
        task = FakeDailyActivityTask(self.make_frame())

        analysis = DailyActivityAnalyzer(task).analyze()

        self.assertEqual(analysis.state, DailyActivityState.UNKNOWN)
        self.assertFalse(analysis.has_claimable_reward)
        self.assertTrue(analysis.no_claimable_reward)

    def test_analysis_result_serializable(self):
        task = FakeDailyActivityTask(self.make_frame(full_activity=True))

        payload = DailyActivityAnalyzer(task).analyze().to_dict()

        self.assertEqual(payload["state"], "no_action_needed")
        self.assertIn("activity_full", payload)
        self.assertIn("milestone_rewards", payload)
        json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
