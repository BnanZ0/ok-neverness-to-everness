import json
import os
from datetime import datetime

import cv2
from qfluentwidgets import FluentIcon

from ok import TaskDisabledException
from src.Labels import Labels
from src.tasks.DailyActivityAnalyzer import DailyActivityAnalyzer
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.DailyTask import DailyTask
from src.tasks.F1PanelDetector import F1PanelDetector


class DailyActivityCaptureTask(BaseNTETask):
    """采集 F1 每日活跃度面板，用于补充模板特征。"""

    DEFAULT_MOVE = True
    DAILY_ACTIVITY_TAB_INDEX = DailyTask.DAILY_ACTIVITY_TAB_INDEX
    DAILY_ACTIVITY_TAB_POSITION = DailyTask.DAILY_ACTIVITY_TAB_POSITION
    ACTIVITY_TAB_POSITION = DAILY_ACTIVITY_TAB_POSITION
    CAPTURE_NAME_PREFIX = "daily_activity_capture"
    CAPTURE_FOLDER = os.path.join("screenshots", CAPTURE_NAME_PREFIX)
    CANDIDATE_REGION_DEFINITIONS = (
        ("daily_activity_panel", (0.1800, 0.1550, 0.9400, 0.8750)),
        ("daily_activity_score_area", (0.1350, 0.1720, 0.3400, 0.2850)),
        ("daily_task_card_strip", (0.1450, 0.2900, 0.9100, 0.7850)),
        ("daily_task_card_body", (0.1600, 0.3250, 0.8950, 0.7150)),
        ("daily_task_card_footer", (0.1600, 0.7300, 0.9100, 0.8000)),
        ("daily_task_card_action_area", (0.6450, 0.3300, 0.9100, 0.7950)),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "每日活跃度采集"
        self.description = "采集每日活跃度面板截图和候选区域，用于补充识别特征"
        self.icon = FluentIcon.CAMERA
        self.support_schedule_task = False
        self.default_config.update(
            {
                "保存候选区域标注": True,
                "保存OCR结果": False,
            }
        )
        self.add_exit_after_config()

    def run(self):
        try:
            return self.do_run()
        except TaskDisabledException:
            pass

    def do_run(self):
        self.log_info("开始采集每日活跃度面板特征")
        self._ensure_capture_main()
        open_result = self._open_activity_panel()
        self._capture_current_activity_panel(self.frame, open_result=open_result)
        self._ensure_capture_main()
        self.log_info("每日活跃度面板截图已保存")
        return True

    def _ensure_capture_main(self):
        self.info_set("current task", "wait daily capture main esc=True")
        if self.wait_until(
            lambda: self.in_team_and_world() or self.handle_monthly_card(),
            time_out=30,
            raise_if_not_found=False,
            post_action=lambda: self.back(after_sleep=2),
        ):
            self._logged_in = True
            self.sleep(0.5)
            self.info_set("current task", "in daily capture main")
            return True

        raise Exception("Please start in game world and in team!")

    def _open_activity_panel(self):
        detector = F1PanelDetector(self)
        try:
            self.openF1panel()
            f1_panel_opened = True
        except Exception:
            return detector.make_open_result(False, False, False)

        self.info_set("每日活跃度目标栏目", f"第{self.DAILY_ACTIVITY_TAB_INDEX}栏目")
        self.click_ui(*self.DAILY_ACTIVITY_TAB_POSITION, after_sleep=1)
        result = detector.make_open_result(f1_panel_opened, True)
        if not result.daily_activity_panel_detected:
            self.log_info(result.reason)
        return result

    def _capture_current_activity_panel(self, frame, panel_detected=True, open_result=None):
        capture_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        detector = F1PanelDetector(self)
        if open_result is None:
            open_result = detector.make_open_result(
                bool(panel_detected),
                bool(panel_detected),
                bool(panel_detected),
            )
        panel_detected = open_result.daily_activity_panel_detected
        feature_probe = detector.probe_features()
        candidate_boxes = self._candidate_region_boxes()
        probe_boxes = detector.probe_boxes(feature_probe)
        ocr_boxes = []
        if self.config.get("保存OCR结果", False):
            ocr_boxes = self.ocr(frame=frame, log=True)

        image_paths = self._save_capture_images(
            capture_id,
            frame,
            candidate_boxes + probe_boxes,
            ocr_boxes,
        )
        analysis = DailyActivityAnalyzer(self).analyze(frame=frame, panel_detected=panel_detected)
        self.screenshot(f"{self.CAPTURE_NAME_PREFIX}/{capture_id}_panel_raw", frame=frame)

        if self.config.get("保存候选区域标注", True):
            self.clear_box()
            self.draw_boxes("daily_activity_candidate_regions", candidate_boxes, color="blue")
            if probe_boxes:
                self.draw_boxes("daily_activity_feature_probe", probe_boxes, color="red")
            if ocr_boxes:
                self.draw_boxes("daily_activity_ocr", ocr_boxes, color="green")
            self.screenshot(
                f"{self.CAPTURE_NAME_PREFIX}/{capture_id}_panel_regions",
                frame=frame,
                show_box=True,
            )

        metadata_path = self._write_capture_metadata(
            capture_id,
            candidate_boxes,
            ocr_boxes,
            image_paths,
            panel_detected,
            analysis,
            open_result,
            feature_probe,
        )
        self.info_set("每日活跃度采集ID", capture_id)
        self.info_set("每日活跃度采集元数据", metadata_path)
        self.info_set("每日活跃度面板特征命中", str(panel_detected))
        self.info_set("每日活跃度打开状态", open_result.reason)
        return True

    def _save_capture_images(self, capture_id, frame, candidate_boxes, ocr_boxes):
        if frame is None:
            raise ValueError("daily activity capture frame cannot be None")

        os.makedirs(self.CAPTURE_FOLDER, exist_ok=True)
        viewport = self.get_ui_viewport(frame=frame)
        image_paths = {
            "raw": os.path.join(self.CAPTURE_FOLDER, f"{capture_id}_panel_raw.png"),
            "active": os.path.join(
                self.CAPTURE_FOLDER, f"{capture_id}_panel_active_ui.png"
            ),
            "regions": os.path.join(self.CAPTURE_FOLDER, f"{capture_id}_panel_regions.png"),
        }
        image_paths["clean"] = image_paths["raw"]

        self._write_frame(image_paths["raw"], frame)
        self._write_frame(image_paths["active"], viewport.crop_active_frame(frame))

        boxed_frame = frame.copy()
        self._draw_viewport_overlay(boxed_frame, viewport)
        self._draw_box_overlays(boxed_frame, candidate_boxes, (255, 0, 0))
        self._draw_box_overlays(boxed_frame, ocr_boxes, (0, 255, 0))
        self._write_frame(image_paths["regions"], boxed_frame)
        return image_paths

    @staticmethod
    def _write_frame(path, frame):
        if not cv2.imwrite(path, frame):
            raise OSError(f"failed to write screenshot: {path}")

    @staticmethod
    def _draw_box_overlays(frame, boxes, color):
        for box in boxes:
            x = int(getattr(box, "x", 0))
            y = int(getattr(box, "y", 0))
            width = int(getattr(box, "width", 0))
            height = int(getattr(box, "height", 0))
            if width <= 0 or height <= 0:
                continue

            cv2.rectangle(frame, (x, y), (x + width, y + height), color, 2)
            name = str(getattr(box, "name", ""))
            if name:
                cv2.putText(
                    frame,
                    name,
                    (x, max(20, y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    color,
                    2,
                    cv2.LINE_AA,
                )

    @staticmethod
    def _draw_viewport_overlay(frame, viewport):
        cv2.rectangle(
            frame,
            (viewport.left, viewport.top),
            (max(0, viewport.right - 1), max(0, viewport.bottom - 1)),
            (0, 255, 255),
            2,
        )
        cv2.putText(
            frame,
            viewport.mode,
            (viewport.left + 10, max(20, viewport.top - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

    def _candidate_region_boxes(self):
        boxes = [
            self.box_of_ui(*definition, name=name)
            for name, definition in self.CANDIDATE_REGION_DEFINITIONS
        ]
        x, y, width, height = DailyActivityAnalyzer.ACTIVITY_REWARD_REGION
        boxes.append(
            self.box_of_ui(
                x,
                y,
                width=width,
                height=height,
                name=Labels.box_f1_activity_reward.value,
            )
        )
        return boxes

    def _write_capture_metadata(
        self,
        capture_id,
        candidate_boxes,
        ocr_boxes,
        image_paths,
        panel_detected,
        analysis,
        open_result,
        feature_probe,
    ):
        folder = os.path.join("logs", self.CAPTURE_NAME_PREFIX)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{capture_id}.json")
        viewport = self.get_ui_viewport()
        payload = {
            "schema_version": 3,
            "capture_id": capture_id,
            "timestamp": capture_id,
            "panel_detected": panel_detected,
            "panel": {
                "detected": panel_detected,
                "label": Labels.f1_activity_panel.value,
            },
            "target_tab": {
                "name": "daily",
                "display_name": "每日",
                "index": self.DAILY_ACTIVITY_TAB_INDEX,
                "position": {
                    "x": self.DAILY_ACTIVITY_TAB_POSITION[0],
                    "y": self.DAILY_ACTIVITY_TAB_POSITION[1],
                },
            },
            "images": image_paths,
            "capture_files": {
                "raw": image_paths.get("raw") or image_paths.get("clean"),
                "active": image_paths.get("active"),
                "regions": image_paths.get("regions"),
            },
            "screen": {"width": self.width, "height": self.height},
            "resolution": {"width": self.width, "height": self.height},
            "viewport": viewport.to_dict(),
            "layout_profile": open_result.layout_profile,
            "ui_coordinate_mode": self.get_ui_coordinate_mode(),
            "open_result": open_result.to_dict(),
            "feature_probe": feature_probe,
            "regions": self._regions_to_dict(candidate_boxes),
            "candidate_regions": [self._box_to_dict(box) for box in candidate_boxes],
            "ocr": [self._box_to_dict(box) for box in ocr_boxes],
            "analysis": analysis.to_dict(),
            "missing_features": DailyTask.DAILY_ACTIVITY_MISSING_FEATURES,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    def _regions_to_dict(self, boxes):
        return {
            str(getattr(box, "name", "")): {
                "pixel": [
                    getattr(box, "x", None),
                    getattr(box, "y", None),
                    getattr(box, "width", None),
                    getattr(box, "height", None),
                ],
                "relative": [
                    self._safe_ratio(getattr(box, "x", 0), self.width),
                    self._safe_ratio(getattr(box, "y", 0), self.height),
                    self._safe_ratio(getattr(box, "width", 0), self.width),
                    self._safe_ratio(getattr(box, "height", 0), self.height),
                ],
            }
            for box in boxes
        }

    @staticmethod
    def _safe_ratio(value, total):
        if not total:
            return 0
        return round(value / total, 4)

    @staticmethod
    def _box_to_dict(box):
        return {
            "name": str(getattr(box, "name", "")),
            "x": getattr(box, "x", None),
            "y": getattr(box, "y", None),
            "width": getattr(box, "width", None),
            "height": getattr(box, "height", None),
            "confidence": getattr(box, "confidence", None),
        }
