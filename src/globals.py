import threading
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from ok import Logger, get_path_relative_to_exe
from PySide6.QtCore import QObject

from src.sound_trigger.SoundCombatContext import SoundCombatContext

logger = Logger.get_logger(__name__)


class Globals(QObject):
    def __init__(self, exit_event):
        super().__init__()
        self._thread_pool_executor_max_workers = 0
        self.thread_pool_executor = None
        self.thread_pool_exit_event = Event()
        self._periodic_tasks = {}
        self._periodic_tasks_lock = threading.Lock()
        exit_event.bind_stop(self)
        self._openvino_model_async = None
        self._sound_context_stop_event = Event()
        threading.Thread(
            target=self.init_sound_context, daemon=True, name="SoundContextInit"
        ).start()

    def stop(self):
        self._sound_context_stop_event.set()
        SoundCombatContext().shutdown()
        self.shutdown_thread_pool_executor()

    def get_thread_pool_executor(self, max_workers=6):
        """
        获取全局执行器。
        如果请求的 max_workers 大于当前值，将安全地重建线程池。
        """
        if (
            self.thread_pool_executor is not None
            and max_workers > self._thread_pool_executor_max_workers
        ):
            logger.info(
                "thread pool max_workers not enough, reset max_workers"
                f" {self._thread_pool_executor_max_workers} -> {max_workers}"
            )
            self.shutdown_thread_pool_executor()

        if self.thread_pool_executor is None:
            logger.info(f"create thread pool executor, max_workers: {max_workers}")
            self.thread_pool_exit_event = Event()
            self.thread_pool_executor = ThreadPoolExecutor(max_workers=max_workers)
            self._thread_pool_executor_max_workers = max_workers

        return self.thread_pool_executor

    def shutdown_thread_pool_executor(self):
        if self.thread_pool_executor is not None:
            logger.info("Shutting down thread pool executor...")
            with self._periodic_tasks_lock:
                for record in self._periodic_tasks.values():
                    record["stop_event"].set()
                self._periodic_tasks.clear()
            self.thread_pool_exit_event.set()
            self.thread_pool_executor.shutdown(wait=False, cancel_futures=True)
            self.thread_pool_executor = None
            self._thread_pool_executor_max_workers = 0

    def _get_periodic_task_key(self, task):
        bound_self = getattr(task, "__self__", None)
        func = getattr(task, "__func__", task)
        func_name = getattr(func, "__name__", repr(task))

        if bound_self is not None:
            cls = bound_self.__class__
            return ("bound_method", cls.__module__, cls.__qualname__, func_name)

        return (
            "callable",
            getattr(func, "__module__", None),
            getattr(func, "__qualname__", func_name),
        )

    def _get_periodic_task_name(self, task):
        bound_self = getattr(task, "__self__", None)
        func = getattr(task, "__func__", task)
        func_name = getattr(func, "__name__", repr(task))
        if bound_self is None:
            return func_name
        return f"{bound_self.__class__.__name__}.{func_name}"

    def submit_periodic_task(self, delay, task, *args, **kwargs):
        """
        提交一个循环任务到线程池。
        如果要停止循环，任务函数应返回 False。

        :param task: 要执行的函数
        :param delay: 每次执行后的间隔时间（秒）
        :param args: 位置参数
        :param kwargs: 关键字参数
        """
        executor = self.get_thread_pool_executor()
        exit_event = self.thread_pool_exit_event
        task_key = self._get_periodic_task_key(task)
        task_name = self._get_periodic_task_name(task)
        task_stop_event = Event()

        with self._periodic_tasks_lock:
            old_record = self._periodic_tasks.get(task_key)
            if old_record is not None:
                logger.debug(f"Stopping previous periodic task {task_name}.")
                old_record["stop_event"].set()
                old_future = old_record.get("future")
                if old_future is not None:
                    old_future.cancel()

            self._periodic_tasks[task_key] = {
                "stop_event": task_stop_event,
                "future": None,
            }

        def loop_wrapper():
            logger.debug(f"Periodic task {task_name} started.")

            try:
                while not exit_event.is_set() and not task_stop_event.is_set():
                    should_stop = False
                    try:
                        if task(*args, **kwargs) is False:
                            should_stop = True
                    except Exception as e:
                        logger.error(f"Error in periodic task {task_name}: {e}")

                    if should_stop:
                        logger.debug(f"Periodic task {task_name} decided to stop.")
                        break

                    if task_stop_event.wait(timeout=delay) or exit_event.is_set():
                        logger.debug(f"Periodic task {task_name} received stop signal.")
                        break

                logger.debug(f"Periodic task {task_name} stopped.")
            finally:
                with self._periodic_tasks_lock:
                    current_record = self._periodic_tasks.get(task_key)
                    if (
                        current_record is not None
                        and current_record["stop_event"] is task_stop_event
                    ):
                        del self._periodic_tasks[task_key]

        future = executor.submit(loop_wrapper)
        with self._periodic_tasks_lock:
            current_record = self._periodic_tasks.get(task_key)
            if current_record is not None and current_record["stop_event"] is task_stop_event:
                current_record["future"] = future
        return future

    @property
    def openvino_model_async(self):
        if self._openvino_model_async is None:
            logger.info("openvino_model_async Using YOLO26OpenVINOAsyncDetector")
            from src.YOLO26OpenVINOAsyncDetector import YOLO26OpenVINOAsyncDetector

            self._openvino_model_async = YOLO26OpenVINOAsyncDetector(
                xml_path=get_path_relative_to_exe("assets", "openvino", "best.xml")
            )
        return self._openvino_model_async

    @property
    def openvino_latency_async(self):
        return self._openvino_model_async.latency

    def openvino_detect_async(self, image, box=None, threshold=0.5, force=False, mask_regions=None):
        """异步检测，返回结果可能为缓存值"""
        ret = self.openvino_model_async.detect(
            image,
            box=box,
            threshold=threshold,
            label="target",
            force=force,
            mask_regions=mask_regions,
        )
        # logger.debug(f"openvino async: {ret}, cost {self.openvino_latency_async:.3f} s")
        return ret

    def openvino_detect_sync(self, image, box=None, threshold=0.5, mask_regions=None):
        """同步检测"""
        ret = self.openvino_model_async.detect_sync(
            image, box=box, threshold=threshold, label="target", mask_regions=mask_regions
        )
        # logger.debug(f"openvino sync: {ret}, cost {self.openvino_latency_async:.3f} s")
        return ret

    def openvino_clear_cache(self):
        """清空缓存"""
        self.openvino_model_async.clear_cache()

    def init_sound_context(self):
        context = SoundCombatContext()
        if self._sound_context_stop_event.is_set():
            return
        dodge = get_path_relative_to_exe("assets", "sounds", "dodge.wav")
        counter_attack = get_path_relative_to_exe("assets", "sounds", "counter.wav")
        context.setup(
            task=None,
            sample_path=dodge,
            counter_attack_sample_path=counter_attack,
        )
        if self._sound_context_stop_event.is_set():
            context.shutdown()
            return
        if context.enter() and not self._sound_context_stop_event.is_set():
            logger.info("SoundCombatContext initialized globally")
        else:
            context.shutdown()
