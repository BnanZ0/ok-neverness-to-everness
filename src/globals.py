import threading
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event

from ok import Logger, get_path_relative_to_exe
from PySide6.QtCore import QObject

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
        self._openvino_model_future = Future()
        self._sound_context_stop_event = Event()
        threading.Thread(
            target=self.init_sound_context, daemon=True, name="SoundContextInit"
        ).start()
        threading.Thread(target=self.init_openvino, daemon=True, name="OpenVINOInit").start()

    def stop(self):
        self._sound_context_stop_event.set()
        from src.sound_trigger.SoundCombatContext import SoundCombatContext

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
            None,
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
        if self._openvino_model_async is not None:
            return self._openvino_model_async
        return self._openvino_model_future.result()

    @property
    def openvino_latency_async(self):
        return self._openvino_model_async.latency

    @property
    def openvino_latest_image(self):
        return self._openvino_model_async.latest_image if self._openvino_model_async else None

    def openvino_detect(
        self, image, sync=False, box=None, threshold=0.5, force=False, mask_regions=None
    ):
        """异步检测，返回结果可能为缓存值"""
        if not sync:
            ret = self.openvino_model_async.detect(
                image,
                box=box,
                threshold=threshold,
                label="target",
                force=force,
                mask_regions=mask_regions,
            )
        else:
            ret = self.openvino_model_async.detect_sync(
                image,
                box=box,
                threshold=threshold,
                label="target",
                mask_regions=mask_regions,
            )
        # latency = self.openvino_latency_async if ret is not None else -1
        # logger.debug(
        #     f"openvino: sync {sync}, result {ret}, cost {latency:.3f}s"
        # )
        return ret

    def openvino_clear_cache(self):
        """清空缓存"""
        self.openvino_model_async.clear_cache()

    @property
    def openvino_available(self):
        """openvino是否可用"""
        return self.openvino_model_async._openvino_available

    def init_sound_context(self):
        from src.ui.util import wait_main_window

        wait_main_window()

        from src.sound_trigger.SoundCombatContext import SoundCombatContext

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

    def init_openvino(self):
        from src.ui.util import wait_main_window

        wait_main_window()
        try:
            logger.info("openvino_model_async Using YOLO26OpenVINOAsyncDetector")
            from src.YOLO26OpenVINOAsyncDetector import YOLO26OpenVINOAsyncDetector

            detector = YOLO26OpenVINOAsyncDetector(
                xml_path=get_path_relative_to_exe("assets", "openvino", "best.xml")
            )
        except BaseException as error:
            logger.error(f"OpenVINO detector initialization failed: {error}")
            self._openvino_model_future.set_exception(error)
        else:
            self._openvino_model_async = detector
            self._openvino_model_future.set_result(detector)
