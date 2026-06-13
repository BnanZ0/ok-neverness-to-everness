#!/usr/bin/env python3
"""Diagnose WASAPI per-process loopback activation (the 0x8000000E failure).

Run with the GAME RUNNING, from the project venv:

    python tools/diag_process_loopback.py
    python tools/diag_process_loopback.py --process HTGame.exe

It reuses the real activation code from
src/sound_trigger/capture/process_loopback.py, prints Windows' decoded message
for every HRESULT, and tries a couple of ways of passing the COM completion
handler so we can pinpoint the cause. Copy the whole output back.
"""
from __future__ import annotations

import argparse
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import comtypes  # noqa: E402

from src.sound_trigger.capture import process_loopback as pl  # noqa: E402


def decode_hresult(hr: int) -> str:
    code = hr & 0xFFFFFFFF
    FORMAT_MESSAGE_FROM_SYSTEM = 0x1000
    FORMAT_MESSAGE_IGNORE_INSERTS = 0x200
    buf = ctypes.create_unicode_buffer(512)
    n = ctypes.windll.kernel32.FormatMessageW(
        FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        None, ctypes.c_uint(code), 0, buf, len(buf), None
    )
    msg = buf.value.strip() if n else "(no system message)"
    return f"0x{code:08X} ({msg})"


def attempt(pid: int, include_tree: bool, handler_mode: str) -> None:
    print(f"\n--- activation attempt: handler_mode={handler_mode} ---")
    params = pl.AUDIOCLIENT_ACTIVATION_PARAMS()
    params.ActivationType = pl.AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
    params.ProcessLoopbackParams.TargetProcessId = pid
    params.ProcessLoopbackParams.ProcessLoopbackMode = (
        pl.PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
        if include_tree
        else pl.PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE
    )
    propvar = pl.PROPVARIANT_BLOB()
    propvar.vt = pl.VT_BLOB
    propvar.blob.cbSize = ctypes.sizeof(params)
    propvar.blob.pBlobData = ctypes.cast(ctypes.byref(params), ctypes.c_void_p)
    print(f"  activation_params sizeof={ctypes.sizeof(params)} blob.cbSize={propvar.blob.cbSize} "
          f"vt={propvar.vt} pid={pid} mode={params.ProcessLoopbackParams.ProcessLoopbackMode}")
    raw = ctypes.string_at(ctypes.byref(params), ctypes.sizeof(params))
    print(f"  activation_params bytes={raw.hex()}")

    handler = pl._ActivateHandler()
    if handler_mode == "comobject":
        handler_arg = handler
    elif handler_mode == "queryinterface":
        handler_arg = handler.QueryInterface(pl.IActivateAudioInterfaceCompletionHandler)
    else:
        raise ValueError(handler_mode)

    operation = ctypes.POINTER(pl.IActivateAudioInterfaceAsyncOperation)()
    iid = pl.IAudioClient._iid_
    try:
        hr = pl._ActivateAudioInterfaceAsync(
            pl.VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
            ctypes.byref(iid),
            ctypes.byref(propvar),
            handler_arg,
            ctypes.byref(operation),
        )
    except Exception as exc:
        print(f"  CALL RAISED: {exc!r}")
        return
    print(f"  sync HRESULT = {decode_hresult(hr)}")
    if hr < 0:
        print("  -> synchronous failure (callback will not fire)")
        return
    print("  sync OK, waiting for ActivateCompleted callback...")
    if not handler.completed.wait(5.0):
        print("  -> callback DID NOT fire within 5s")
        return
    print(f"  activate HRESULT = {decode_hresult(handler.activate_hr or 0)}")
    print(f"  audio_client obtained = {handler.audio_client is not None}")
    _ = params  # keep-alive


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--process", default="HTGame.exe")
    ap.add_argument("--no-tree", action="store_true", help="exclude target process tree")
    args = ap.parse_args()

    print(f"platform={sys.platform}")
    try:
        wv = sys.getwindowsversion()
        print(f"windows build={wv.build} (min for process loopback ~{pl.MIN_PROCESS_LOOPBACK_BUILD})")
    except Exception as exc:
        print(f"windows version unknown: {exc}")
    print(f"capability_available={pl._capability_available()}")

    pid = pl.resolve_target_pid(args.process)
    print(f"resolve_target_pid({args.process!r}) = {pid}")
    if not pid:
        print("Game process not found — is it running?")
        return 1

    import threading

    def run_on_mta(mode: str) -> None:
        # Run on a FRESH thread so CoInitializeEx(MTA) succeeds (mirrors the app's
        # dedicated capture thread). The main thread is already STA (PySide/comtypes).
        def worker():
            try:
                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
                print(f"[{mode}] worker CoInitializeEx(MTA) ok")
            except OSError as exc:
                # Activation requires MTA; without it the result is meaningless.
                print(f"[{mode}] worker CoInitializeEx(MTA) failed: {exc} — skipping attempt")
                return
            try:
                attempt(pid, not args.no_tree, mode)
            except Exception as exc:
                print(f"  attempt({mode}) crashed: {exc!r}")
            finally:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass

        th = threading.Thread(target=worker)
        th.start()
        th.join()

    for mode in ("comobject", "queryinterface"):
        run_on_mta(mode)

    # End-to-end: the real capture source (activation + Initialize format tiers +
    # Start + GetBuffer loop + mono conversion), exactly as the app uses it.
    print("\n=== full per-process capture test (3s) ===")
    import time

    import numpy as np

    source = pl.ProcessLoopbackSource(args.process)
    started = source.start()
    print(f"ProcessLoopbackSource.start() = {started}")
    if started:
        chunks = samples = 0
        peak = 0.0
        deadline = time.time() + 3.0
        try:
            while time.time() < deadline:
                chunk = source.read(timeout=0.5)
                if chunk is not None and len(chunk):
                    chunks += 1
                    samples += len(chunk)
                    peak = max(peak, float(np.max(np.abs(chunk))))
        finally:
            source.stop()
        print(f"captured chunks={chunks} samples={samples} (~{samples / 48000:.2f}s) peak_amp={peak:.4f}")
        print("  (peak_amp ~0 just means the game was silent; nonzero = real audio captured)")
        print(f"  source error after run = {source.error}")
    else:
        print(f"  start failed; error={source.error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
