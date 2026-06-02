import ctypes

KLF_NOTELLSHELL = 0x00000080
MAPVK_VK_TO_VSC = 0
MAPVK_VSC_TO_VK_EX = 3
US_QWERTY_LAYOUT_ID = "00000409"


class QwertyPhysicalKeyMapper:
    def __init__(self):
        self.user32 = ctypes.windll.user32
        self._configure_user32()
        self.qwerty_layout = self.user32.LoadKeyboardLayoutW(
            US_QWERTY_LAYOUT_ID, KLF_NOTELLSHELL
        )

    def map_key(self, key):
        key = str(key).lower()
        if len(key) != 1 or not key.isascii() or not key.isalnum():
            return None

        qwerty_vk = self.user32.VkKeyScanExW(key, self.qwerty_layout) & 0xFF
        if qwerty_vk == 0xFF:
            return None

        qwerty_scan_code = self.user32.MapVirtualKeyExW(
            qwerty_vk, MAPVK_VK_TO_VSC, self.qwerty_layout
        )
        if qwerty_scan_code == 0:
            return None

        current_layout = self.user32.GetKeyboardLayout(0)
        current_vk = self.user32.MapVirtualKeyExW(
            qwerty_scan_code, MAPVK_VSC_TO_VK_EX, current_layout
        )
        if current_vk == 0:
            return None

        return self._to_unmodified_char(current_vk, qwerty_scan_code, current_layout)

    def _to_unmodified_char(self, vk_code, scan_code, keyboard_layout):
        keyboard_state = (ctypes.c_ubyte * 256)()
        buffer = ctypes.create_unicode_buffer(8)
        char_count = self.user32.ToUnicodeEx(
            vk_code,
            scan_code,
            keyboard_state,
            buffer,
            len(buffer),
            0,
            keyboard_layout,
        )
        if char_count <= 0 or not buffer.value:
            return None

        return buffer.value[0].lower()

    def _configure_user32(self):
        self.user32.GetKeyboardLayout.argtypes = [ctypes.c_uint]
        self.user32.GetKeyboardLayout.restype = ctypes.c_void_p
        self.user32.MapVirtualKeyExW.argtypes = [
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_void_p,
        ]
        self.user32.MapVirtualKeyExW.restype = ctypes.c_uint
        self.user32.LoadKeyboardLayoutW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
        self.user32.LoadKeyboardLayoutW.restype = ctypes.c_void_p
        self.user32.VkKeyScanExW.argtypes = [ctypes.c_wchar, ctypes.c_void_p]
        self.user32.VkKeyScanExW.restype = ctypes.c_short
        self.user32.ToUnicodeEx.argtypes = [
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_void_p,
        ]
        self.user32.ToUnicodeEx.restype = ctypes.c_int
