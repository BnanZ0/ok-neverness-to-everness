# ============================================================================
# WASAPI per-process loopback capture (primary source).
#
# Captures ONLY the target game process's audio (and its process tree), exactly
# like NTE-Auto-Skill-Combo's Rust capture
# (AudioClient::new_application_loopback_client). This eliminates false dodge
# triggers from music / Discord / other apps.
#
# Uses ActivateAudioInterfaceAsync + AUDIOCLIENT_ACTIVATION_PARAMS (PROCESS_LOOPBACK)
# via comtypes/ctypes. Format/buffer choices mirror audio.rs: 48 kHz float32
# stereo, EventsShared + AUTOCONVERTPCM, 5 ms buffer (fallback 20 ms), include
# process tree, silent-flag -> zeros. PID resolution and the wait/reconnect loop
# mirror the Rust resolve_/wait_for_game_audio_capture_target behaviour.
#
# Capability gating: if the activation cannot run on this machine the source
# raises before delivering audio so the listener falls back to system loopback.
# ============================================================================
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from typing import Optional

import comtypes
import numpy as np
import psutil
from comtypes import COMMETHOD, GUID, COMObject, IUnknown
from comtypes.hresult import S_OK
from ok import Logger

from src.sound_trigger.capture.base import AudioCaptureSource, PushFn
from src.sound_trigger.fingerprint.matcher import ANALYSIS_SAMPLE_RATE

logger = Logger.get_logger(__name__)

CAPTURE_CHANNELS = 2
# Minimum Windows 10 build that exposes process-loopback activation in practice
# (MS documents 20348+, but it works on 19041+; the runtime activation attempt
# is the real gate and any failure cleanly triggers fallback).
MIN_PROCESS_LOOPBACK_BUILD = 19041
PROCESS_WAIT_INTERVAL = 0.5
PROCESS_CHECK_INTERVAL = 1.0
# Consecutive activation failures (with the game present) before we give up and
# let the listener fall back to system loopback.
MAX_ACTIVATION_FAILURES = 5

# -- WASAPI / activation constants ----------------------------------------

AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE = 1

VT_BLOB = 65
VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"

AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
INIT_STREAM_FLAGS = (
    AUDCLNT_STREAMFLAGS_LOOPBACK
    | AUDCLNT_STREAMFLAGS_EVENTCALLBACK
    | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
)

AUDCLNT_BUFFERFLAGS_SILENT = 0x2

WAVE_FORMAT_PCM = 0x0001
WAVE_FORMAT_IEEE_FLOAT = 0x0003
WAVE_FORMAT_EXTENSIBLE = 0xFFFE

LOW_LATENCY_BUFFER_HNS = 50_000  # 5 ms
FALLBACK_BUFFER_HNS = 200_000  # 20 ms

REFERENCE_TIME = ctypes.c_longlong


class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(ctypes.Structure):
    _fields_ = [
        ("TargetProcessId", wintypes.DWORD),
        ("ProcessLoopbackMode", ctypes.c_int),
    ]


class _APUnion(ctypes.Union):
    _fields_ = [("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS)]


class AUDIOCLIENT_ACTIVATION_PARAMS(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("ActivationType", ctypes.c_int),
        ("u", _APUnion),
    ]


class _BLOB(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.ULONG), ("pBlobData", ctypes.c_void_p)]


class PROPVARIANT_BLOB(ctypes.Structure):
    # vt(2) + 3x reserved WORD(6) => union begins at offset 8 on x64.
    _fields_ = [
        ("vt", wintypes.USHORT),
        ("wReserved1", wintypes.USHORT),
        ("wReserved2", wintypes.USHORT),
        ("wReserved3", wintypes.USHORT),
        ("blob", _BLOB),
    ]


class WAVEFORMATEX(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class WAVEFORMATEXTENSIBLE(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("Format", WAVEFORMATEX),
        ("wValidBitsPerSample", wintypes.WORD),
        ("dwChannelMask", wintypes.DWORD),
        ("SubFormat", GUID),
    ]


KSDATAFORMAT_SUBTYPE_IEEE_FLOAT = GUID("{00000003-0000-0010-8000-00AA00389B71}")
SPEAKER_FRONT_LEFT_RIGHT = 0x3  # FL | FR


# -- COM interfaces --------------------------------------------------------


class IAudioCaptureClient(IUnknown):
    # Defined before IAudioClient so IAudioClient.GetService can return a
    # comtypes-managed POINTER(POINTER(IAudioCaptureClient)) (auto Release on GC).
    _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
    _methods_ = (
        COMMETHOD(
            [], comtypes.HRESULT, "GetBuffer",
            (["out"], ctypes.POINTER(ctypes.c_void_p), "ppData"),
            (["out"], ctypes.POINTER(wintypes.UINT), "pNumFramesToRead"),
            (["out"], ctypes.POINTER(wintypes.DWORD), "pdwFlags"),
            (["out"], ctypes.POINTER(ctypes.c_ulonglong), "pu64DevicePosition"),
            (["out"], ctypes.POINTER(ctypes.c_ulonglong), "pu64QPCPosition"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "ReleaseBuffer",
            (["in"], wintypes.UINT, "NumFramesRead"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetNextPacketSize",
            (["out"], ctypes.POINTER(wintypes.UINT), "pNumFramesInNextPacket"),
        ),
    )


class IAudioClient(IUnknown):
    _iid_ = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
    _methods_ = (
        COMMETHOD(
            [], comtypes.HRESULT, "Initialize",
            (["in"], ctypes.c_int, "ShareMode"),
            (["in"], wintypes.DWORD, "StreamFlags"),
            (["in"], REFERENCE_TIME, "hnsBufferDuration"),
            (["in"], REFERENCE_TIME, "hnsPeriodicity"),
            (["in"], ctypes.POINTER(WAVEFORMATEX), "pFormat"),
            (["in"], ctypes.POINTER(GUID), "AudioSessionGuid"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetBufferSize",
            (["out"], ctypes.POINTER(wintypes.UINT), "pNumBufferFrames"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetStreamLatency",
            (["out"], ctypes.POINTER(REFERENCE_TIME), "phnsLatency"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetCurrentPadding",
            (["out"], ctypes.POINTER(wintypes.UINT), "pNumPaddingFrames"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "IsFormatSupported",
            (["in"], ctypes.c_int, "ShareMode"),
            (["in"], ctypes.POINTER(WAVEFORMATEX), "pFormat"),
            (["out"], ctypes.POINTER(ctypes.POINTER(WAVEFORMATEX)), "ppClosestMatch"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetMixFormat",
            (["out"], ctypes.POINTER(ctypes.POINTER(WAVEFORMATEX)), "ppDeviceFormat"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetDevicePeriod",
            (["out"], ctypes.POINTER(REFERENCE_TIME), "phnsDefaultDevicePeriod"),
            (["out"], ctypes.POINTER(REFERENCE_TIME), "phnsMinimumDevicePeriod"),
        ),
        COMMETHOD([], comtypes.HRESULT, "Start"),
        COMMETHOD([], comtypes.HRESULT, "Stop"),
        COMMETHOD([], comtypes.HRESULT, "Reset"),
        COMMETHOD(
            [], comtypes.HRESULT, "SetEventHandle",
            (["in"], wintypes.HANDLE, "eventHandle"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetService",
            (["in"], ctypes.POINTER(GUID), "riid"),
            (["out"], ctypes.POINTER(ctypes.POINTER(IAudioCaptureClient)), "ppv"),
        ),
    )


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
    _methods_ = (
        COMMETHOD(
            [], comtypes.HRESULT, "GetActivateResult",
            (["out"], ctypes.POINTER(ctypes.c_int), "activateResult"),
            (["out"], ctypes.POINTER(ctypes.POINTER(IUnknown)), "activatedInterface"),
        ),
    )


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
    _methods_ = (
        COMMETHOD(
            [], comtypes.HRESULT, "ActivateCompleted",
            (["in"], ctypes.POINTER(IActivateAudioInterfaceAsyncOperation), "activateOperation"),
        ),
    )


_mmdevapi = ctypes.WinDLL("mmdevapi.dll")
_ActivateAudioInterfaceAsync = _mmdevapi.ActivateAudioInterfaceAsync
_ActivateAudioInterfaceAsync.restype = ctypes.c_long
_ActivateAudioInterfaceAsync.argtypes = [
    wintypes.LPCWSTR,
    ctypes.POINTER(GUID),
    ctypes.c_void_p,
    ctypes.POINTER(IActivateAudioInterfaceCompletionHandler),
    ctypes.POINTER(ctypes.POINTER(IActivateAudioInterfaceAsyncOperation)),
]

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_CreateEventW = _kernel32.CreateEventW
_CreateEventW.restype = wintypes.HANDLE
_CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_WaitForSingleObject = _kernel32.WaitForSingleObject
_WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_WaitForSingleObject.restype = wintypes.DWORD
_CloseHandle = _kernel32.CloseHandle
_CloseHandle.argtypes = [wintypes.HANDLE]


# -- PID resolution --------------------------------------------------------


def _foreground_pid() -> Optional[int]:
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) or None
    except Exception:
        return None


def _process_name(pid: int) -> Optional[str]:
    try:
        return psutil.Process(pid).name()
    except Exception:
        return None


def _name_set(process_name) -> set:
    """Normalize a process name (str or list/tuple — ok-script stores `exe` as a
    list) into a set of casefolded names to match against."""
    if isinstance(process_name, (list, tuple, set)):
        names = process_name
    else:
        names = [process_name]
    return {str(n).casefold() for n in names if n}


def resolve_target_pid(process_name) -> Optional[int]:
    """Foreground window's process if it matches `process_name`, else a scan.

    `process_name` may be a single name or a list of candidate names.
    """
    targets = _name_set(process_name)
    if not targets:
        return None

    foreground = _foreground_pid()
    if foreground and (_process_name(foreground) or "").casefold() in targets:
        return foreground

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").casefold() in targets:
                return int(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
            continue
    return None


def process_is_alive(pid: int, process_name) -> bool:
    return (_process_name(pid) or "").casefold() in _name_set(process_name)


# -- activation ------------------------------------------------------------


class _ActivateHandler(COMObject):
    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler]

    def __init__(self):
        super().__init__()
        import threading

        self.completed = threading.Event()
        self.activate_hr: Optional[int] = None
        self.audio_client = None

    def IActivateAudioInterfaceCompletionHandler_ActivateCompleted(self, this, operation):
        try:
            hr, unk = operation.GetActivateResult()
            self.activate_hr = int(hr)
            if hr >= 0 and unk:
                self.audio_client = unk.QueryInterface(IAudioClient)
        except Exception as exc:  # never raise across the COM boundary
            self.activate_hr = getattr(exc, "hresult", -1) or -1
        finally:
            self.completed.set()
        return S_OK


def _activate_audio_client(pid: int, include_tree: bool, timeout_s: float = 5.0):
    params = AUDIOCLIENT_ACTIVATION_PARAMS()
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
    params.ProcessLoopbackParams.TargetProcessId = pid
    params.ProcessLoopbackParams.ProcessLoopbackMode = (
        PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
        if include_tree
        else PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE
    )

    propvar = PROPVARIANT_BLOB()
    propvar.vt = VT_BLOB
    propvar.blob.cbSize = ctypes.sizeof(params)
    propvar.blob.pBlobData = ctypes.cast(ctypes.byref(params), ctypes.c_void_p)

    handler = _ActivateHandler()
    operation = ctypes.POINTER(IActivateAudioInterfaceAsyncOperation)()
    iid_audioclient = IAudioClient._iid_

    hr = _ActivateAudioInterfaceAsync(
        VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
        ctypes.byref(iid_audioclient),
        ctypes.byref(propvar),
        handler,
        ctypes.byref(operation),
    )
    if hr < 0:
        raise OSError(f"ActivateAudioInterfaceAsync failed: 0x{hr & 0xFFFFFFFF:08X}")

    if not handler.completed.wait(timeout_s):
        raise TimeoutError("ActivateCompleted did not fire within timeout")
    if handler.activate_hr is None or handler.activate_hr < 0:
        code = (handler.activate_hr or 0) & 0xFFFFFFFF
        raise OSError(f"process-loopback activation failed: 0x{code:08X}")
    if handler.audio_client is None:
        raise OSError("activation returned no IAudioClient")
    _ = params  # keep BLOB target alive until the wait returns
    return handler.audio_client


def _make_float_extensible_format() -> WAVEFORMATEXTENSIBLE:
    wfx = WAVEFORMATEXTENSIBLE()
    fmt = wfx.Format
    fmt.wFormatTag = WAVE_FORMAT_EXTENSIBLE
    fmt.nChannels = CAPTURE_CHANNELS
    fmt.nSamplesPerSec = ANALYSIS_SAMPLE_RATE
    fmt.wBitsPerSample = 32
    fmt.nBlockAlign = fmt.nChannels * fmt.wBitsPerSample // 8
    fmt.nAvgBytesPerSec = fmt.nSamplesPerSec * fmt.nBlockAlign
    fmt.cbSize = 22
    wfx.wValidBitsPerSample = 32
    wfx.dwChannelMask = SPEAKER_FRONT_LEFT_RIGHT
    wfx.SubFormat = KSDATAFORMAT_SUBTYPE_IEEE_FLOAT
    return wfx


def _make_float_format() -> WAVEFORMATEX:
    fmt = WAVEFORMATEX()
    fmt.wFormatTag = WAVE_FORMAT_IEEE_FLOAT
    fmt.nChannels = CAPTURE_CHANNELS
    fmt.nSamplesPerSec = ANALYSIS_SAMPLE_RATE
    fmt.wBitsPerSample = 32
    fmt.nBlockAlign = fmt.nChannels * fmt.wBitsPerSample // 8
    fmt.nAvgBytesPerSec = fmt.nSamplesPerSec * fmt.nBlockAlign
    fmt.cbSize = 0
    return fmt


def _make_pcm16_format() -> WAVEFORMATEX:
    fmt = WAVEFORMATEX()
    fmt.wFormatTag = WAVE_FORMAT_PCM
    fmt.nChannels = CAPTURE_CHANNELS
    fmt.nSamplesPerSec = ANALYSIS_SAMPLE_RATE
    fmt.wBitsPerSample = 16
    fmt.nBlockAlign = fmt.nChannels * fmt.wBitsPerSample // 8
    fmt.nAvgBytesPerSec = fmt.nSamplesPerSec * fmt.nBlockAlign
    fmt.cbSize = 0
    return fmt


# (builder, is_float, bits) in preference order. A fresh IAudioClient is
# activated per format because IAudioClient.Initialize is one-shot.
_FORMAT_TIERS = (
    (_make_float_extensible_format, True, 32),
    (_make_float_format, True, 32),
    (_make_pcm16_format, False, 16),
)


def _to_mono(raw: bytes, is_float: bool) -> np.ndarray:
    if is_float:
        inter = np.frombuffer(raw, dtype=np.float32)
    else:
        inter = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if inter.size == 0:
        return np.zeros(0, dtype=np.float32)
    mono = (inter[0::CAPTURE_CHANNELS] + inter[1::CAPTURE_CHANNELS]) * np.float32(0.5)
    np.clip(mono, -1.0, 1.0, out=mono)
    return np.ascontiguousarray(mono, dtype=np.float32)


# -- capture source --------------------------------------------------------


class ProcessLoopbackSource(AudioCaptureSource):
    used_sr = ANALYSIS_SAMPLE_RATE
    used_channel = CAPTURE_CHANNELS

    def __init__(self, process_name, include_process_tree: bool = True):
        super().__init__()
        # `process_name` may be a str or a list of candidate exe names (ok-script
        # stores `exe` as a list); resolve_target_pid/process_is_alive accept both.
        self.process_name = process_name
        self._display_name = ",".join(sorted(_name_set(process_name))) or "?"
        self.include_process_tree = include_process_tree
        self._stream_started_once = False

    @property
    def name(self) -> str:
        return f"process-loopback({self._display_name})"

    def _produce(self, push: PushFn) -> None:
        if not _capability_available():
            raise RuntimeError("WASAPI per-process loopback is not available on this system")

        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except OSError as exc:
            # RPC_E_CHANGED_MODE: thread already initialized differently; tolerate.
            logger.warning(f"CoInitializeEx(MTA) returned {exc}; continuing")

        # Capability present: we are the live source even while the game is not
        # running yet, so the listener does not fall back spuriously.
        self._mark_ready()

        failure_streak = 0
        try:
            while not self._stop.is_set():
                pid = resolve_target_pid(self.process_name)
                if pid is None:
                    if self._stop.wait(PROCESS_WAIT_INTERVAL):
                        return
                    continue

                logger.info(f"Process loopback capture source: {self.process_name} pid={pid}")
                try:
                    self._run_loopback_stream(pid, push)
                    failure_streak = 0  # clean exit (process ended) -> reconnect
                except Exception as exc:
                    if self._stream_started_once:
                        # The stream was live before; treat as a transient drop.
                        logger.warning(
                            f"Process loopback stream pid={pid} dropped; reconnecting: {exc}"
                        )
                        failure_streak = 0
                    else:
                        failure_streak += 1
                        logger.warning(
                            f"Process loopback activation failed "
                            f"({failure_streak}/{MAX_ACTIVATION_FAILURES}) for "
                            f"{self.process_name} pid={pid}: {exc}"
                        )
                        if failure_streak >= MAX_ACTIVATION_FAILURES:
                            # Genuinely cannot activate; die so the listener
                            # falls back to system loopback.
                            raise
                    if self._stop.wait(PROCESS_WAIT_INTERVAL):
                        return
        finally:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass

    def _run_loopback_stream(self, pid: int, push: PushFn) -> None:
        audio_client, block_align, is_float = self._activate_and_initialize(pid)

        h_event = _CreateEventW(None, False, False, None)
        if not h_event:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            audio_client.SetEventHandle(h_event)
            # comtypes-managed pointer (Release on GC); riid matches the out type.
            capture = audio_client.GetService(ctypes.byref(IAudioCaptureClient._iid_))

            audio_client.Start()
            try:
                self._stream_started_once = True
                next_check = time.time() + PROCESS_CHECK_INTERVAL
                while not self._stop.is_set():
                    now = time.time()
                    if now >= next_check:
                        if not process_is_alive(pid, self.process_name):
                            logger.info(f"{self.process_name} pid={pid} ended; will rebind")
                            return
                        next_check = now + PROCESS_CHECK_INTERVAL

                    next_frames = capture.GetNextPacketSize()
                    if next_frames == 0:
                        _WaitForSingleObject(h_event, 20)
                        continue

                    while next_frames > 0 and not self._stop.is_set():
                        ppData, frames, flags, _devpos, _qpc = capture.GetBuffer()
                        # Every GetBuffer MUST be paired with ReleaseBuffer, even
                        # if downstream processing raises -> release in finally.
                        try:
                            if frames > 0:
                                if (flags & AUDCLNT_BUFFERFLAGS_SILENT) or not ppData:
                                    mono = np.zeros(frames, dtype=np.float32)
                                else:
                                    # string_at accepts an int address or c_void_p
                                    # and copies, so the buffer is safe to release.
                                    raw = ctypes.string_at(ppData, frames * block_align)
                                    mono = _to_mono(raw, is_float)
                                push(mono)
                        finally:
                            capture.ReleaseBuffer(frames)
                        next_frames = capture.GetNextPacketSize()
            finally:
                try:
                    audio_client.Stop()
                except Exception:
                    pass
        finally:
            _CloseHandle(h_event)

    def _activate_and_initialize(self, pid: int):
        """Activate + Initialize an IAudioClient, trying format tiers in order.

        Returns (audio_client, block_align, is_float). Raises if every format
        and buffer size fails. A FRESH client is activated for every attempt
        because IAudioClient.Initialize is one-shot (mirrors audio.rs, which
        re-creates the loopback client per buffer attempt).
        """
        last_error: Optional[BaseException] = None
        for make_format, is_float, bits in _FORMAT_TIERS:
            block_align = CAPTURE_CHANNELS * bits // 8
            for buffer_hns in (LOW_LATENCY_BUFFER_HNS, FALLBACK_BUFFER_HNS):
                # Activation failure is terminal (no point trying other formats):
                # let it propagate out of the function.
                audio_client = _activate_audio_client(pid, self.include_process_tree)
                fmt = make_format()
                fmt_ptr = ctypes.cast(ctypes.byref(fmt), ctypes.POINTER(WAVEFORMATEX))
                try:
                    audio_client.Initialize(
                        AUDCLNT_SHAREMODE_SHARED,
                        INIT_STREAM_FLAGS,
                        REFERENCE_TIME(buffer_hns),
                        REFERENCE_TIME(0),
                        fmt_ptr,
                        None,
                    )
                    logger.info(
                        f"Process loopback initialized: "
                        f"{'float' if is_float else 'pcm16'} buffer={buffer_hns // 10_000}ms"
                    )
                    return audio_client, block_align, is_float
                except Exception as exc:
                    last_error = exc
                    # This client is spent (Initialize is one-shot); drop it and
                    # activate a fresh one for the next attempt.
                    del audio_client
        raise OSError(f"IAudioClient.Initialize failed for all formats: {last_error}")


def _capability_available() -> bool:
    """True if this machine can do WASAPI per-process loopback capture."""
    if sys.platform != "win32":
        return False
    try:
        build = sys.getwindowsversion().build  # type: ignore[attr-defined]
    except Exception:
        return False
    if build < MIN_PROCESS_LOOPBACK_BUILD:
        return False
    try:
        ctypes.WinDLL("mmdevapi.dll")
    except Exception:
        return False
    return True
