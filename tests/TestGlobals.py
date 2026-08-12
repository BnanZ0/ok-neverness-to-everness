import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

from src.globals import Globals


class _FakeDetector:
    created = 0
    created_lock = threading.Lock()

    def __init__(self, xml_path):
        del xml_path
        with self.created_lock:
            type(self).created += 1
        time.sleep(0.02)


class TestGlobals(unittest.TestCase):
    def test_openvino_model_is_initialized_once_when_accessed_concurrently(self):
        _FakeDetector.created = 0
        fake_module = types.ModuleType("src.YOLO26OpenVINOAsyncDetector")
        fake_module.YOLO26OpenVINOAsyncDetector = _FakeDetector
        app = Globals.__new__(Globals)
        app._openvino_model_async = None
        app._openvino_model_init_lock = threading.Lock()
        start = threading.Barrier(8)
        results = []

        def get_model():
            start.wait()
            results.append(app.openvino_model_async)

        with (
            patch.dict(sys.modules, {"src.YOLO26OpenVINOAsyncDetector": fake_module}),
            patch("src.globals.get_path_relative_to_exe", return_value="model.xml"),
        ):
            threads = [threading.Thread(target=get_model) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(_FakeDetector.created, 1)
        self.assertEqual(len({id(model) for model in results}), 1)


if __name__ == "__main__":
    unittest.main()
