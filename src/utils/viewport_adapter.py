from dataclasses import dataclass


TARGET_UI_RATIO = 16 / 9
MODE_AUTO_16_9_VIEWPORT = "Auto 16:9 Viewport"
MODE_NATIVE_SCREEN = "Native Screen"
VIEWPORT_MODE_NATIVE_16_9 = "native_16_9"
VIEWPORT_MODE_NATIVE_SCREEN = "native_screen"
VIEWPORT_MODE_16_9_CENTER_CROP = "16_9_center_crop"
LAYOUT_PROFILE_VIEWPORT_16_9 = "viewport_16_9"
LAYOUT_PROFILE_NATIVE_16_9 = "native_16_9"
LAYOUT_PROFILE_NATIVE_16_10 = "native_16_10"
LAYOUT_PROFILE_NATIVE_UNKNOWN = "native_unknown"
LETTERBOX_MEAN_THRESHOLD = 20.0
LETTERBOX_STD_THRESHOLD = 8.0


@dataclass(frozen=True)
class Viewport:
    screen_width: int
    screen_height: int
    left: int
    top: int
    width: int
    height: int
    mode: str = VIEWPORT_MODE_16_9_CENTER_CROP

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def ui_point_to_screen_relative(self, x: float, y: float) -> tuple[float, float]:
        px, py = self.ui_point_to_screen_pixel(x, y)
        return px / self.screen_width, py / self.screen_height

    def ui_point_to_screen_pixel(self, x: float, y: float) -> tuple[int, int]:
        return round(self.left + x * self.width), round(self.top + y * self.height)

    def ui_box_to_screen_relative(
        self,
        x: float,
        y: float,
        to_x: float = 1.0,
        to_y: float = 1.0,
        width: float = 0.0,
        height: float = 0.0,
    ) -> tuple[float, float, float, float]:
        box_x, box_y, box_width, box_height = self.ui_box_to_screen_pixel(
            x, y, to_x=to_x, to_y=to_y, width=width, height=height
        )
        return (
            box_x / self.screen_width,
            box_y / self.screen_height,
            (box_x + box_width) / self.screen_width,
            (box_y + box_height) / self.screen_height,
        )

    def ui_box_to_screen_pixel(
        self,
        x: float,
        y: float,
        to_x: float = 1.0,
        to_y: float = 1.0,
        width: float = 0.0,
        height: float = 0.0,
    ) -> tuple[int, int, int, int]:
        if width == 0:
            width = to_x - x
        if height == 0:
            height = to_y - y

        box_x = round(self.left + x * self.width)
        box_y = round(self.top + y * self.height)
        box_width = round(width * self.width)
        box_height = round(height * self.height)
        return box_x, box_y, box_width, box_height

    def crop_active_frame(self, frame):
        return frame[self.top : self.bottom, self.left : self.right]

    def to_dict(self):
        return {
            "mode": self.mode,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "right": self.right,
            "bottom": self.bottom,
        }


def make_native_viewport(width: int, height: int) -> Viewport:
    return Viewport(
        screen_width=width,
        screen_height=height,
        left=0,
        top=0,
        width=width,
        height=height,
        mode=VIEWPORT_MODE_NATIVE_SCREEN,
    )


def make_16_9_viewport(width: int, height: int) -> Viewport:
    if width <= 0 or height <= 0:
        return make_native_viewport(width, height)

    current_ratio = width / height

    if abs(current_ratio - TARGET_UI_RATIO) < 0.001:
        return Viewport(
            screen_width=width,
            screen_height=height,
            left=0,
            top=0,
            width=width,
            height=height,
            mode=VIEWPORT_MODE_NATIVE_16_9,
        )

    if current_ratio < TARGET_UI_RATIO:
        active_width = width
        active_height = round(width / TARGET_UI_RATIO)
        left = 0
        top = (height - active_height) // 2
    else:
        active_height = height
        active_width = round(height * TARGET_UI_RATIO)
        left = (width - active_width) // 2
        top = 0

    return Viewport(
        screen_width=width,
        screen_height=height,
        left=left,
        top=top,
        width=active_width,
        height=active_height,
        mode=VIEWPORT_MODE_16_9_CENTER_CROP,
    )


def make_auto_viewport(width: int, height: int, frame=None) -> Viewport:
    viewport = make_16_9_viewport(width, height)
    if viewport.mode != VIEWPORT_MODE_16_9_CENTER_CROP:
        return viewport

    if frame is None:
        return viewport

    if _frame_has_letterbox_bands(frame, viewport):
        return viewport

    return make_native_viewport(width, height)


def _frame_has_letterbox_bands(frame, viewport: Viewport) -> bool:
    bands = []
    if viewport.top > 0:
        bands.append(frame[: viewport.top, :])
    if viewport.bottom < viewport.screen_height:
        bands.append(frame[viewport.bottom :, :])
    if viewport.left > 0:
        bands.append(frame[:, : viewport.left])
    if viewport.right < viewport.screen_width:
        bands.append(frame[:, viewport.right :])

    if not bands:
        return False

    return all(_is_flat_dark_band(band) for band in bands if band.size)


def _is_flat_dark_band(band) -> bool:
    if band.size == 0:
        return True

    mean = float(band.mean())
    std = float(band.std())
    return mean <= LETTERBOX_MEAN_THRESHOLD and std <= LETTERBOX_STD_THRESHOLD


def classify_ui_layout_profile(width: int, height: int, viewport_mode: str) -> str:
    if viewport_mode == VIEWPORT_MODE_16_9_CENTER_CROP:
        return LAYOUT_PROFILE_VIEWPORT_16_9
    if viewport_mode == VIEWPORT_MODE_NATIVE_16_9:
        return LAYOUT_PROFILE_NATIVE_16_9
    if viewport_mode != VIEWPORT_MODE_NATIVE_SCREEN:
        return LAYOUT_PROFILE_NATIVE_UNKNOWN

    if width <= 0 or height <= 0:
        return LAYOUT_PROFILE_NATIVE_UNKNOWN

    ratio = width / height
    if abs(ratio - (16 / 10)) < 0.02:
        return LAYOUT_PROFILE_NATIVE_16_10
    if abs(ratio - TARGET_UI_RATIO) < 0.02:
        return LAYOUT_PROFILE_NATIVE_16_9
    return LAYOUT_PROFILE_NATIVE_UNKNOWN
