class ReadOnlyUIContext:
    """Narrow read-only UI surface for screen analyzers and detectors."""

    def __init__(self, source):
        self.source = source

    @classmethod
    def coerce(cls, source):
        return source if isinstance(source, cls) else cls(source)

    @property
    def frame(self):
        try:
            return getattr(self.source, "frame", None)
        except Exception:
            return None

    @property
    def width(self):
        return int(getattr(self.source, "width", 0) or 0)

    @property
    def height(self):
        return int(getattr(self.source, "height", 0) or 0)

    def get_ui_layout_profile(self):
        getter = getattr(self.source, "get_ui_layout_profile", None)
        if callable(getter):
            return getter()
        return "native_unknown"

    def find_one(self, *args, **kwargs):
        finder = getattr(self.source, "find_one", None)
        if not callable(finder):
            return None
        return finder(*args, **kwargs)

    def box_of_ui(self, *args, **kwargs):
        converter = getattr(self.source, "box_of_ui", None)
        if not callable(converter):
            return None
        return converter(*args, **kwargs)

    def get_box_by_name(self, *args, **kwargs):
        getter = getattr(self.source, "get_box_by_name", None)
        if not callable(getter):
            return None
        return getter(*args, **kwargs)

    def ocr_ui(self, *args, **kwargs):
        ocr = getattr(self.source, "ocr_ui", None)
        if not callable(ocr):
            return None
        return ocr(*args, **kwargs)


class TaskUIAdapter(ReadOnlyUIContext):
    """Executable UI surface for runtime flows that need input actions."""

    @classmethod
    def coerce(cls, source):
        return source if isinstance(source, cls) else cls(source)

    @property
    def config(self):
        return getattr(self.source, "config", {}) or {}

    def has_ensure_daily_main(self):
        return callable(getattr(self.source, "_ensure_daily_main", None))

    def ensure_daily_main(self):
        ensure = getattr(self.source, "_ensure_daily_main", None)
        if not callable(ensure):
            return False
        ensure()
        return True

    def next_frame(self):
        getter = getattr(self.source, "next_frame", None)
        if not callable(getter):
            return None
        return getter()

    def click(self, *args, **kwargs):
        click = getattr(self.source, "click", None)
        if not callable(click):
            raise AttributeError("UI source does not provide click()")
        return click(*args, **kwargs)

    def click_ui(self, *args, **kwargs):
        click = getattr(self.source, "click_ui", None)
        if not callable(click):
            raise AttributeError("UI source does not provide click_ui()")
        return click(*args, **kwargs)

    def scroll(self, *args, **kwargs):
        scroll = getattr(self.source, "scroll", None)
        if not callable(scroll):
            raise AttributeError("UI source does not provide scroll()")
        return scroll(*args, **kwargs)

    def swipe(self, *args, **kwargs):
        swipe = getattr(self.source, "swipe", None)
        if not callable(swipe):
            raise AttributeError("UI source does not provide swipe()")
        return swipe(*args, **kwargs)

    def sleep(self, seconds):
        sleep = getattr(self.source, "sleep", None)
        if callable(sleep):
            sleep(seconds)

    def operate(self, func, block=False):
        operate = getattr(self.source, "operate", None)
        if not callable(operate):
            return False
        operate(func, block=block)
        return True

    def send_key(self, *args, **kwargs):
        sender = getattr(self.source, "send_key", None)
        if not callable(sender):
            raise AttributeError("UI source does not provide send_key()")
        return sender(*args, **kwargs)

    def send_foreground_key(self, *args, **kwargs):
        sender = getattr(self.source, "_send_foreground_key", None)
        if not callable(sender):
            return None
        return sender(*args, **kwargs)

    def has_send_foreground_key(self):
        return callable(getattr(self.source, "_send_foreground_key", None))

    def ui_point(self, x, y):
        viewport_getter = getattr(self.source, "get_ui_viewport", None)
        if callable(viewport_getter):
            viewport = viewport_getter()
            converter = getattr(viewport, "ui_point_to_screen_pixel", None)
            if callable(converter):
                converted = converter(x, y)
                if (
                    isinstance(converted, (tuple, list))
                    and len(converted) == 2
                    and all(isinstance(value, (int, float)) for value in converted)
                ):
                    return int(converted[0]), int(converted[1])

        point = getattr(self.source, "ui_point", None)
        if callable(point):
            px, py = point(x, y)
            if abs(px) <= 1 and abs(py) <= 1:
                return int(self.width * px), int(self.height * py)
            return px, py

        return int(self.width * x), int(self.height * y)

    def screen_height(self, default=1600):
        if self.height:
            return self.height
        frame = self.frame
        shape = getattr(frame, "shape", None)
        if shape is not None and len(shape) >= 2:
            return int(shape[0])
        return default
