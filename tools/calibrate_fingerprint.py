#!/usr/bin/env python3
"""Calibrate fingerprint tunings (primarily the COUNTER cue) for ok-nte.

DODGE already uses NTE-Auto-Skill-Combo's proven template bank + tunings verbatim
(assets/sounds/fingerprint/dodge.wav + dodge3.wav) and needs no calibration.
The COUNTER template (assets/sounds/counter.wav) has no reference tuning, so
re-tune it here, then bake the result into counter_config() in
src/sound_trigger/fingerprint/templates.py:

  1. Record real combat audio with counter/parry events (game running):
       python tools/calibrate_fingerprint.py capture out.wav --seconds 60
  2. Sweep tunings against that audio + the counter template:
       python tools/calibrate_fingerprint.py grid out.wav assets/sounds/counter.wav
  3. Inspect one tuning in detail:
       python tools/calibrate_fingerprint.py report out.wav assets/sounds/counter.wav --votes 6 --coverage 3

(The same commands re-tune dodge against assets/sounds/fingerprint/*.wav if ever
needed.) Analysis subcommands need only numpy + scipy. `capture` additionally
needs the runtime capture deps (comtypes, psutil) and the game running.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from the repo root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sound_trigger.fingerprint import matcher as fp  # noqa: E402

ACCEPT_THRESHOLD = 79.5
ACCEPT_COOLDOWN = 0.05


def _tuning(args) -> fp.Tuning:
    return fp.Tuning(
        prefix_ms=args.prefix_ms,
        tolerance=args.tol,
        votes=args.votes,
        coverage=args.coverage,
        corr=args.corr,
        psr=args.psr,
        prefix_offset_ms=args.offset_ms,
    )


def _format(candidate) -> str:
    return (
        f"{candidate.confidence:.1f}% start={candidate.best_start_sample / fp.ANALYSIS_SAMPLE_RATE:.3f}s "
        f"v={candidate.votes} c={candidate.coverage} corr={candidate.corr:.3f} "
        f"psr={candidate.psr:.2f} verified={candidate.verified}"
    )


def cmd_report(args) -> int:
    audio = fp.load_analysis_samples(args.audio)
    tuning = _tuning(args)
    template = fp.load_template(args.template, tuning)
    candidates = fp.evaluate(audio, fp.extract_peaks(audio), template, tuning)
    accepted = fp.select_matches(candidates, ACCEPT_THRESHOLD, ACCEPT_COOLDOWN)
    print(f"audio={args.audio.name} duration={fp.seconds(audio):.3f}s")
    print(
        f"template={args.template.name} detect={fp.seconds(template.samples):.3f}s "
        f"frames={len(template.peaks)}"
    )
    print(f"candidates={len(candidates)} accepted={len(accepted)}")
    for candidate in accepted[: args.top]:
        print("  accept ", _format(candidate))
    for candidate in candidates[: args.top]:
        print("  cand   ", _format(candidate))
    return 0


def cmd_grid(args) -> int:
    audio = fp.load_analysis_samples(args.audio)
    audio_peaks = fp.extract_peaks(audio)
    prefixes = [120, 150, 180, 220, 307]
    profiles = [
        dict(votes=8, coverage=4, corr=0.08, psr=3.0),
        dict(votes=8, coverage=4, corr=0.08, psr=2.0),
        dict(votes=6, coverage=3, corr=0.08, psr=2.0),
        dict(votes=6, coverage=3, corr=0.05, psr=2.0),
        dict(votes=4, coverage=2, corr=0.02, psr=1.5),
    ]
    for prefix in prefixes:
        for profile in profiles:
            tuning = fp.Tuning(prefix_ms=prefix, tolerance=args.tol, **profile)
            template = fp.load_template(args.template, tuning)
            candidates = fp.evaluate(audio, audio_peaks, template, tuning)
            accepted = fp.select_matches(candidates, ACCEPT_THRESHOLD, ACCEPT_COOLDOWN)
            best = candidates[0] if candidates else None
            print(
                f"prefix={prefix:>3} votes={profile['votes']} coverage={profile['coverage']} "
                f"corr={profile['corr']:.2f} psr={profile['psr']:.1f} "
                f"accepted={len(accepted):>2} best={_format(best) if best else 'n/a'}"
            )
    return 0


def cmd_capture(args) -> int:
    from src.sound_trigger.capture.process_loopback import ProcessLoopbackSource

    source = ProcessLoopbackSource(process_name=args.process)
    if not source.start():
        print(f"failed to start per-process capture for {args.process}: {source.error}")
        return 1
    import time

    import numpy as np
    from scipy.io import wavfile

    print(f"capturing {args.seconds}s of {args.process} audio...")
    collected = []
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            chunk = source.read(timeout=0.5)
            if chunk is not None:
                collected.append(chunk)
    finally:
        source.stop()
    if not collected:
        print("no audio captured (game silent or capture failed)")
        return 1
    mono = np.concatenate(collected).astype(np.float32)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(args.out), fp.ANALYSIS_SAMPLE_RATE, mono)
    print(f"wrote {args.out} ({fp.seconds(mono):.1f}s @ {fp.ANALYSIS_SAMPLE_RATE} Hz mono)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--prefix-ms", type=int, default=180)
    common.add_argument("--tol", type=int, default=2)
    common.add_argument("--votes", type=int, default=8)
    common.add_argument("--coverage", type=int, default=4)
    common.add_argument("--corr", type=float, default=0.08)
    common.add_argument("--psr", type=float, default=2.0)
    common.add_argument("--offset-ms", type=int, default=0)
    common.add_argument("--top", type=int, default=10)

    p_report = sub.add_parser("report", parents=[common])
    p_report.add_argument("audio", type=Path)
    p_report.add_argument("template", type=Path)
    p_report.set_defaults(func=cmd_report)

    p_grid = sub.add_parser("grid", parents=[common])
    p_grid.add_argument("audio", type=Path)
    p_grid.add_argument("template", type=Path)
    p_grid.set_defaults(func=cmd_grid)

    p_cap = sub.add_parser("capture")
    p_cap.add_argument("out", type=Path)
    p_cap.add_argument("--process", default="HTGame.exe")
    p_cap.add_argument("--seconds", type=float, default=60.0)
    p_cap.set_defaults(func=cmd_capture)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
