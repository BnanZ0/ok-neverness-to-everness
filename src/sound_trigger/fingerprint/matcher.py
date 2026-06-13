# ============================================================================
# Spectral-fingerprint matcher (Shazam-style peak-constellation hashing +
# matched-filter verification).
#
# Faithful port of NTE-Auto-Skill-Combo/scripts/analyze_dodge_match.py
# (the diagnostic-only argparse/reporting helpers are omitted; the detection
# pipeline is kept verbatim so behaviour and tuning carry over exactly).
#
# Original algorithm: NTE-Auto-Skill-Combo (src/dodge/fingerprint/*).
# ============================================================================
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ANALYSIS_SAMPLE_RATE = 48_000
FFT_SIZE = 1024
HOP_SIZE = 512
MIN_FREQUENCY = 80.0
MAX_FREQUENCY = 12_000.0
MAX_PEAKS_PER_FRAME = 5
FALLBACK_PEAKS_PER_FRAME = 3
MIN_PEAK_SEPARATION_DB = 6.0
PEAK_BIN_GUARD = 3
FINGERPRINT_BIN_STRIDE = 4
HASH_TIME_SPAN_FRAMES = 2
VERIFICATION_LAG_SAMPLES = HOP_SIZE
VERIFICATION_LAG_STEP_SAMPLES = HOP_SIZE // 8
PREEMPHASIS = 0.97
SILENCE_TRIM_RELATIVE_THRESHOLD = 0.02
SILENCE_TRIM_PADDING_SECONDS = 0.020


@dataclass(frozen=True)
class Tuning:
    prefix_ms: int = 180
    tolerance: int = 2
    votes: int = 8
    coverage: int = 4
    corr: float = 0.08
    psr: float = 2.0
    prefix_offset_ms: int = 0


@dataclass(frozen=True)
class FingerprintHash:
    anchor_bin: int
    target_bin: int
    delta_frames: int
    anchor_frame: int


@dataclass
class Candidate:
    frame_offset: int
    votes: int
    anchor_mask: int
    corr: float = 0.0
    psr: float = 0.0
    best_start_sample: int = 0
    confidence: float = 0.0
    verified: bool = False

    @property
    def coverage(self) -> int:
        return self.anchor_mask.bit_count()

    @property
    def predicted_start_sample(self) -> int:
        return self.frame_offset * HOP_SIZE


@dataclass(frozen=True)
class TemplateData:
    samples: np.ndarray
    peaks: list[list[tuple[int, int]]]
    index: dict[tuple[int, int, int], list[int]]
    source_seconds: float
    trimmed_seconds: float
    verifier: np.ndarray | None


def load_template(path: Path, tuning: Tuning) -> TemplateData:
    source = load_analysis_samples(path)
    trimmed = trim_silence(source)
    offset_samples = round(tuning.prefix_offset_ms * ANALYSIS_SAMPLE_RATE / 1000)
    if offset_samples >= len(trimmed):
        raise ValueError("dodge template prefix offset exceeds trimmed audio")
    prefix_samples = round(tuning.prefix_ms * ANALYSIS_SAMPLE_RATE / 1000)
    detect_count = min(len(trimmed) - offset_samples, max(prefix_samples, FFT_SIZE))
    samples = trimmed[offset_samples : offset_samples + detect_count]
    peaks = extract_peaks(samples)
    index = build_index(build_hashes(peaks), tuning.tolerance)
    return TemplateData(
        samples=samples,
        peaks=peaks,
        index=index,
        source_seconds=seconds(source),
        trimmed_seconds=seconds(trimmed),
        verifier=whiten_and_normalize(samples),
    )


def evaluate(
    audio: np.ndarray,
    audio_peaks: list[list[tuple[int, int]]],
    template: TemplateData,
    tuning: Tuning,
) -> list[Candidate]:
    if len(audio_peaks) < len(template.peaks):
        return []

    max_frame_offset = len(audio_peaks) - len(template.peaks)
    votes: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for observed in build_hashes(audio_peaks):
        for template_anchor_frame in template.index.get(
            (observed.anchor_bin, observed.target_bin, observed.delta_frames), []
        ):
            if observed.anchor_frame < template_anchor_frame:
                continue
            frame_offset = observed.anchor_frame - template_anchor_frame
            if frame_offset > max_frame_offset:
                continue
            vote = votes[frame_offset]
            vote[0] += 1
            if template_anchor_frame < 128:
                vote[1] |= 1 << template_anchor_frame

    candidates = []
    verifier_template = template.verifier
    sample_count = len(template.samples)
    for frame_offset, (vote_count, anchor_mask) in votes.items():
        candidate = Candidate(frame_offset, vote_count, anchor_mask)
        if vote_count < tuning.votes or candidate.coverage < tuning.coverage:
            continue
        verified = verify_candidate(audio, verifier_template, sample_count, candidate, tuning)
        if verified is None:
            continue
        candidates.append(verified)

    candidates.sort(key=lambda candidate: candidate.confidence, reverse=True)
    return candidates


def verify_candidate(
    audio: np.ndarray,
    verifier_template: np.ndarray | None,
    sample_count: int,
    candidate: Candidate,
    tuning: Tuning,
) -> Candidate | None:
    if verifier_template is None or len(audio) < sample_count:
        return None
    predicted = candidate.predicted_start_sample
    max_start = len(audio) - sample_count
    min_start = max(0, predicted - VERIFICATION_LAG_SAMPLES)
    max_start = min(max_start, predicted + VERIFICATION_LAG_SAMPLES)
    if min_start > max_start:
        return None

    starts = []
    correlations = []
    start = min_start
    while True:
        window = whiten_and_normalize(audio[start : start + sample_count])
        if window is not None:
            starts.append(start)
            correlations.append(float(np.clip(np.dot(verifier_template, window), -1.0, 1.0)))
        if start == max_start:
            break
        start = min(start + VERIFICATION_LAG_STEP_SAMPLES, max_start)

    if not correlations:
        return None
    correlations_array = np.array(correlations, dtype=np.float32)
    best_index = int(np.argmax(correlations_array))
    sidelobes = np.delete(correlations_array, best_index)
    candidate.corr = float(correlations_array[best_index])
    candidate.psr = peak_to_sidelobe(candidate.corr, sidelobes)
    candidate.best_start_sample = starts[best_index]
    candidate.verified = (
        candidate.votes >= tuning.votes
        and candidate.coverage >= tuning.coverage
        and candidate.corr >= tuning.corr
        and candidate.psr >= tuning.psr
    )
    candidate.confidence = confidence(candidate, tuning)
    return candidate


def load_analysis_samples(path: Path) -> np.ndarray:
    sample_rate, samples = wavfile.read(path)
    samples = to_float_mono(samples)
    if sample_rate != ANALYSIS_SAMPLE_RATE:
        samples = linear_resample(samples, sample_rate, ANALYSIS_SAMPLE_RATE)
    return samples.astype(np.float32, copy=False)


def to_float_mono(samples: np.ndarray) -> np.ndarray:
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    if np.issubdtype(samples.dtype, np.integer):
        max_value = float(np.iinfo(samples.dtype).max)
        samples = samples.astype(np.float32) / max_value
    else:
        samples = samples.astype(np.float32)
    return samples


def linear_resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or len(samples) == 0:
        return samples.copy()
    output_len = max(1, len(samples) * target_rate // source_rate)
    position = np.arange(output_len, dtype=np.float64) * (source_rate / target_rate)
    left = np.floor(position).astype(np.int64)
    right = np.minimum(left + 1, len(samples) - 1)
    fraction = (position - left).astype(np.float32)
    return samples[left] * (1.0 - fraction) + samples[right] * fraction


def trim_silence(samples: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak <= np.finfo(np.float32).eps:
        return samples.copy()
    threshold = peak * SILENCE_TRIM_RELATIVE_THRESHOLD
    active = np.flatnonzero(np.abs(samples) >= threshold)
    if len(active) == 0:
        return samples.copy()
    padding = round(SILENCE_TRIM_PADDING_SECONDS * ANALYSIS_SAMPLE_RATE)
    start = max(0, int(active[0]) - padding)
    end = min(len(samples), int(active[-1]) + padding + 1)
    return samples[start:end].copy()


def extract_peaks(samples: np.ndarray) -> list[list[tuple[int, int]]]:
    if len(samples) < FFT_SIZE:
        return []
    window = (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(FFT_SIZE) / FFT_SIZE)).astype(np.float32)
    min_bin = frequency_to_bin(MIN_FREQUENCY)
    max_frequency = min(MAX_FREQUENCY, ANALYSIS_SAMPLE_RATE / 2)
    max_bin = min(FFT_SIZE // 2, max(frequency_to_bin(max_frequency), min_bin + 2))
    frame_count = (len(samples) - FFT_SIZE) // HOP_SIZE + 1
    frames = []
    for frame_index in range(frame_count):
        start = frame_index * HOP_SIZE
        frame = samples[start : start + FFT_SIZE] * window
        spectrum = np.fft.rfft(frame)
        power = np.maximum(np.abs(spectrum) ** 2, 1.0e-20)
        levels = 10.0 * np.log10(power[min_bin : max_bin + 1])
        threshold = float(np.median(levels) + MIN_PEAK_SEPARATION_DB)
        local = []
        for index in range(1, len(levels) - 1):
            current = float(levels[index])
            if current >= levels[index - 1] and current > levels[index + 1]:
                local.append((min_bin + index, current))
        local.sort(key=lambda item: item[1], reverse=True)
        selected = []
        for bin_index, level_db in local:
            if level_db < threshold and len(selected) >= FALLBACK_PEAKS_PER_FRAME:
                continue
            if any(abs(bin_index - selected_bin) <= PEAK_BIN_GUARD for selected_bin, _ in selected):
                continue
            selected.append((bin_index, quantize_bin(bin_index)))
            if len(selected) >= MAX_PEAKS_PER_FRAME:
                break
        frames.append(selected)
    return frames


def build_hashes(frames: list[list[tuple[int, int]]]) -> list[FingerprintHash]:
    hashes = []
    for anchor_frame, anchor_peaks in enumerate(frames):
        for _anchor_bin, anchor_quantized in anchor_peaks:
            for delta_frames in range(1, HASH_TIME_SPAN_FRAMES + 1):
                target_frame = anchor_frame + delta_frames
                if target_frame >= len(frames):
                    continue
                for _target_bin, target_quantized in frames[target_frame]:
                    hashes.append(
                        FingerprintHash(anchor_quantized, target_quantized, delta_frames, anchor_frame)
                    )
    return hashes


def build_index(hashes: list[FingerprintHash], tolerance: int) -> dict[tuple[int, int, int], list[int]]:
    index = defaultdict(list)
    for fingerprint_hash in hashes:
        for anchor_delta in range(-tolerance, tolerance + 1):
            for target_delta in range(-tolerance, tolerance + 1):
                anchor_bin = fingerprint_hash.anchor_bin + anchor_delta
                target_bin = fingerprint_hash.target_bin + target_delta
                if anchor_bin < 0 or target_bin < 0:
                    continue
                index[(anchor_bin, target_bin, fingerprint_hash.delta_frames)].append(
                    fingerprint_hash.anchor_frame
                )
    return index


def whiten_and_normalize(samples: np.ndarray) -> np.ndarray | None:
    if len(samples) == 0:
        return None
    output = samples.astype(np.float32, copy=True)
    previous = np.concatenate(([0.0], samples[:-1]))
    output = output - PREEMPHASIS * previous
    output = output - float(np.mean(output))
    norm = float(np.linalg.norm(output))
    if norm <= np.finfo(np.float32).eps:
        return None
    return output / norm


def confidence(candidate: Candidate, tuning: Tuning) -> float:
    vote_quality = np.clip(candidate.votes / (max(tuning.votes, 1) * 4.0), 0.0, 1.0)
    coverage_quality = np.clip(candidate.coverage / (max(tuning.coverage, 1) * 2.0), 0.0, 1.0)
    correlation_quality = np.clip(
        (candidate.corr - tuning.corr) / max(0.55 - tuning.corr, 0.01), 0.0, 1.0
    )
    psr_quality = np.clip((candidate.psr - tuning.psr) / max(8.0 - tuning.psr, 0.01), 0.0, 1.0)
    quality = (
        0.25 * vote_quality
        + 0.20 * coverage_quality
        + 0.40 * correlation_quality
        + 0.15 * psr_quality
    )
    if candidate.verified:
        return float(np.clip(80.0 + 20.0 * quality, 0.0, 100.0))
    return float(np.clip(60.0 * quality, 0.0, 79.0))


def select_matches(
    candidates: list[Candidate], threshold: float, cooldown_seconds: float
) -> list[Candidate]:
    selected = []
    for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
        if not candidate.verified or candidate.confidence < threshold:
            continue
        start_seconds = candidate.best_start_sample / ANALYSIS_SAMPLE_RATE
        if any(
            abs((existing.best_start_sample / ANALYSIS_SAMPLE_RATE) - start_seconds)
            < cooldown_seconds
            for existing in selected
        ):
            continue
        selected.append(candidate)
    selected.sort(key=lambda item: item.best_start_sample)
    return selected


def peak_to_sidelobe(peak: float, sidelobes: np.ndarray) -> float:
    if len(sidelobes) == 0:
        return 0.0
    mean = float(np.mean(sidelobes))
    stddev = float(np.std(sidelobes))
    if stddev <= 1.0e-6:
        return 99.0 if peak > mean else 0.0
    return max(0.0, (peak - mean) / stddev)


def frequency_to_bin(frequency: float) -> int:
    return max(1, round(frequency * FFT_SIZE / ANALYSIS_SAMPLE_RATE))


def quantize_bin(bin_index: int) -> int:
    return min(65535, (bin_index + FINGERPRINT_BIN_STRIDE // 2) // FINGERPRINT_BIN_STRIDE)


def seconds(samples: np.ndarray) -> float:
    return len(samples) / ANALYSIS_SAMPLE_RATE
