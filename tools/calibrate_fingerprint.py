#!/usr/bin/env python3
"""Calibrate fingerprint tunings (primarily the COUNTER cue) for ok-nte.

DODGE already uses NTE-Auto-Skill-Combo's proven template bank + tunings verbatim
and needs no calibration. The COUNTER template (assets/sounds/counter.wav) has no
reference tuning, so re-tune it here against REAL captured audio, then bake the
result into counter_config() in src/sound_trigger/fingerprint/templates.py.

Recommended (ground-truth) workflow — tap a label key on every counter so we can
score detections exactly:

  1. Capture positives WITH labels (game running; tap the label key on each parry):
       python tools/calibrate_fingerprint.py capture counter_pos.wav --seconds 90 --label-key f8
     -> writes counter_pos.wav + counter_pos.wav.labels.json
     Capture a negative (combat, NO parries, music/voice/SFX on, no label key):
       python tools/calibrate_fingerprint.py capture counter_neg.wav --seconds 60 --label-key ""
  2. Score detections vs labels and sweep tunings to pick the best:
       python tools/calibrate_fingerprint.py eval assets/sounds/counter.wav \
           --pos counter_pos.wav --neg counter_neg.wav --grid
  3. Inspect one tuning in detail:
       python tools/calibrate_fingerprint.py report counter_pos.wav assets/sounds/counter.wav

Analysis subcommands (report/grid/eval) need only numpy + scipy. `capture` also
needs the runtime capture deps (comtypes, psutil), pynput for labels, and the
game running.
"""
from __future__ import annotations

import argparse
import json
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


def _labels_path(audio_path: Path) -> Path:
    return audio_path.with_name(audio_path.name + ".labels.json")


def _detection_times(audio, audio_peaks, template, tuning, threshold) -> list:
    candidates = fp.evaluate(audio, audio_peaks, template, tuning)
    accepted = fp.select_matches(candidates, threshold, ACCEPT_COOLDOWN)
    return sorted(c.best_start_sample / fp.ANALYSIS_SAMPLE_RATE for c in accepted)


def _score(detections, labels, pre, post):
    """Match detections to labels within [label-pre, label+post].

    Returns (true_positives, false_negatives, false_positives). A press is a
    coarse ground-truth mark; the counter sound (and detection) precedes it by
    the player's reaction time, hence the asymmetric window.
    """
    matched_labels, matched_dets = set(), set()
    for li, lt in enumerate(labels):
        for di, dt in enumerate(detections):
            if lt - pre <= dt <= lt + post:
                matched_labels.add(li)
                matched_dets.add(di)
    tp = len(matched_labels)
    fn = len(labels) - tp
    false_pos = len(detections) - len(matched_dets)
    return tp, fn, false_pos


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
        {"votes": 8, "coverage": 4, "corr": 0.08, "psr": 3.0},
        {"votes": 8, "coverage": 4, "corr": 0.08, "psr": 2.0},
        {"votes": 6, "coverage": 3, "corr": 0.08, "psr": 2.0},
        {"votes": 6, "coverage": 3, "corr": 0.05, "psr": 2.0},
        {"votes": 4, "coverage": 2, "corr": 0.02, "psr": 1.5},
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


def cmd_eval(args) -> int:
    pos_paths = [Path(p) for p in (args.pos or [])]
    neg_paths = [Path(p) for p in (args.neg or [])]
    if not pos_paths and not neg_paths:
        print("provide at least one --pos or --neg")
        return 1

    # Preload audio + peaks (peaks are tuning-independent -> computed once/file).
    positives = []
    for path in pos_paths:
        labels_path = _labels_path(path)
        if not labels_path.exists():
            print(f"missing labels for {path.name} (expected {labels_path.name})")
            return 1
        labels = json.loads(labels_path.read_text())
        audio = fp.load_analysis_samples(path)
        positives.append((path.name, audio, fp.extract_peaks(audio), labels))
    negatives = []
    for path in neg_paths:
        audio = fp.load_analysis_samples(path)
        negatives.append((path.name, audio, fp.extract_peaks(audio)))

    total_labels = sum(len(labels) for _, _, _, labels in positives)
    print(
        f"template={args.template.name} | positives={len(positives)} (labels={total_labels}) "
        f"negatives={len(negatives)} | window=[-{args.window_pre}s,+{args.window_post}s] "
        f"threshold={args.threshold}"
    )

    if args.grid:
        prefixes = [120, 150, 180, 220, 307]
        corrs = [0.060, 0.066, 0.072, 0.078, 0.084, 0.090]
        print(f"{'prefix':>6} {'corr':>6} {'TP':>3} {'FN':>3} {'FP':>3} {'prec':>5} {'rec':>5} {'F1':>5}")
        for prefix in prefixes:
            template = fp.load_template(
                args.template, fp.Tuning(prefix_ms=prefix, tolerance=args.tol)
            )
            for corr in corrs:
                tuning = fp.Tuning(
                    prefix_ms=prefix, tolerance=args.tol, votes=args.votes,
                    coverage=args.coverage, corr=corr, psr=args.psr,
                )
                _eval_print_row(f"{prefix:>6} {corr:>6.3f}", template, tuning, positives, negatives, args)
        return 0

    tuning = _tuning(args)
    template = fp.load_template(args.template, tuning)
    for name, audio, peaks, labels in positives:
        dets = _detection_times(audio, peaks, template, tuning, args.threshold)
        tp, fn, fpos = _score(dets, labels, args.window_pre, args.window_post)
        print(f"  pos {name}: labels={len(labels)} detections={len(dets)} TP={tp} FN={fn} FP={fpos}")
    for name, audio, peaks in negatives:
        dets = _detection_times(audio, peaks, template, tuning, args.threshold)
        print(f"  neg {name}: detections={len(dets)} (all FP)")
    _eval_print_row("AGGREGATE", template, tuning, positives, negatives, args)
    return 0


def _eval_print_row(prefix_label, template, tuning, positives, negatives, args) -> None:
    tp = fn = fpos = 0
    for _, audio, peaks, labels in positives:
        dets = _detection_times(audio, peaks, template, tuning, args.threshold)
        a, b, c = _score(dets, labels, args.window_pre, args.window_post)
        tp += a
        fn += b
        fpos += c
    for _, audio, peaks in negatives:
        dets = _detection_times(audio, peaks, template, tuning, args.threshold)
        fpos += len(dets)
    precision = tp / (tp + fpos) if (tp + fpos) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    print(f"{prefix_label} {tp:>3} {fn:>3} {fpos:>3} {precision:>5.2f} {recall:>5.2f} {f1:>5.2f}")


def _resolve_label_key(keyboard, name):
    name = (name or "").strip().lower()
    if hasattr(keyboard.Key, name):
        return getattr(keyboard.Key, name)
    return name  # single character


def cmd_capture(args) -> int:
    import time

    import numpy as np
    from scipy.io import wavfile

    from src.sound_trigger.capture.process_loopback import ProcessLoopbackSource

    presses: list = []
    listener = None
    start = None
    if args.label_key:
        try:
            from pynput import keyboard

            target = _resolve_label_key(keyboard, args.label_key)

            def on_press(key):
                if start is None:
                    return
                matched = (
                    getattr(key, "char", None) == target
                    if isinstance(target, str)
                    else key == target
                )
                if matched:
                    t = round(time.time() - start, 3)
                    presses.append(t)
                    print(f"  label #{len(presses)} @ {t:.2f}s")

            listener = keyboard.Listener(on_press=on_press)
            listener.start()
        except Exception as exc:
            print(f"pynput unavailable, labels disabled: {exc}")

    source = ProcessLoopbackSource(process_name=args.process)
    if not source.start():
        print(f"failed to start per-process capture for {args.process}: {source.error}")
        if listener:
            listener.stop()
        return 1

    key_hint = f" — tap '{args.label_key}' on each counter" if listener else ""
    print(f"capturing {args.seconds}s of {args.process} audio{key_hint}...")
    collected = []
    start = time.time()
    deadline = start + args.seconds
    try:
        while time.time() < deadline:
            chunk = source.read(timeout=0.5)
            if chunk is not None:
                collected.append(chunk)
    finally:
        source.stop()
        if listener:
            listener.stop()

    if not collected:
        print("no audio captured (game silent or capture failed)")
        return 1
    mono = np.concatenate(collected).astype(np.float32)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(args.out), fp.ANALYSIS_SAMPLE_RATE, mono)
    print(f"wrote {args.out} ({fp.seconds(mono):.1f}s @ {fp.ANALYSIS_SAMPLE_RATE} Hz mono)")
    if listener is not None:
        labels_path = _labels_path(args.out)
        labels_path.write_text(json.dumps(presses))
        print(f"wrote {labels_path} ({len(presses)} labels)")
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

    p_eval = sub.add_parser("eval", parents=[common])
    p_eval.add_argument("template", type=Path)
    p_eval.add_argument("--pos", action="append", help="positive .wav (uses its .labels.json)")
    p_eval.add_argument("--neg", action="append", help="negative .wav (no labels; detections = FP)")
    p_eval.add_argument("--threshold", type=float, default=ACCEPT_THRESHOLD)
    p_eval.add_argument("--window-pre", type=float, default=1.0)
    p_eval.add_argument("--window-post", type=float, default=0.5)
    p_eval.add_argument("--grid", action="store_true", help="sweep prefix x corr")
    p_eval.set_defaults(func=cmd_eval)

    p_cap = sub.add_parser("capture")
    p_cap.add_argument("out", type=Path)
    p_cap.add_argument("--process", default="HTGame.exe")
    p_cap.add_argument("--seconds", type=float, default=60.0)
    p_cap.add_argument("--label-key", default="f8", help="key to tap on each event ('' to disable)")
    p_cap.set_defaults(func=cmd_capture)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
