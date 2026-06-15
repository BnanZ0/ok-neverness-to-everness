from __future__ import annotations

from pathlib import Path

from .models import MidiNoteEvent, MidiTrackInfo, ParsedSong, SongInfo


class MidiParseError(RuntimeError):
    pass


def parse_midi_file(info: SongInfo) -> ParsedSong:
    """Parse one MIDI file on demand into timed note events."""

    try:
        import mido
    except ImportError as exc:
        raise MidiParseError("Missing dependency: mido") from exc

    path = Path(info.path)
    try:
        midi = mido.MidiFile(path)
    except Exception as exc:  # noqa: BLE001 - surface the filename with parser errors.
        raise MidiParseError(f"Failed to read MIDI file: {path}") from exc

    ticks_per_beat = int(midi.ticks_per_beat)
    timed_messages = []
    track_names: dict[int, str] = {}

    for track_index, track in enumerate(midi.tracks):
        tick = 0
        for message in track:
            tick += int(message.time)
            timed_messages.append((tick, track_index, message))
            if message.type == "track_name" and track_index not in track_names:
                track_names[track_index] = str(message.name)

    timed_messages.sort(
        key=lambda item: (item[0], 0 if item[2].type == "set_tempo" else 1, item[1])
    )
    tempo = 500000
    last_tick = 0
    now = 0.0
    active: dict[tuple[int, int, int], list[tuple[float, int]]] = {}
    notes: list[MidiNoteEvent] = []

    for tick, track_index, message in timed_messages:
        if tick > last_tick:
            now += mido.tick2second(tick - last_tick, ticks_per_beat, tempo)
            last_tick = tick

        if message.type == "set_tempo":
            tempo = message.tempo
            continue

        if not hasattr(message, "note"):
            continue

        pitch = int(message.note)
        channel = int(getattr(message, "channel", 0))
        velocity = int(getattr(message, "velocity", 0))
        note_key = (track_index, channel, pitch)
        if message.type == "note_on" and velocity > 0:
            active.setdefault(note_key, []).append((now, velocity))
            continue

        if message.type in {"note_off", "note_on"}:
            starts = active.get(note_key)
            if not starts:
                continue
            start, start_velocity = starts.pop(0)
            if not starts:
                active.pop(note_key, None)
            duration = max(0.0, now - start)
            notes.append(
                MidiNoteEvent(
                    pitch=pitch,
                    start=start,
                    duration=duration,
                    velocity=start_velocity,
                    track_index=track_index,
                )
            )

    duration = 0.0
    if notes:
        duration = max(note.start + note.duration for note in notes)

    track_note_counts: dict[int, int] = {}
    for note in notes:
        track_note_counts[note.track_index] = track_note_counts.get(note.track_index, 0) + 1
    tracks = tuple(
        MidiTrackInfo(
            index=track_index,
            name=track_names.get(track_index) or f"Track {track_index + 1}",
            note_count=track_note_counts.get(track_index, 0),
        )
        for track_index in range(len(midi.tracks))
    )

    return ParsedSong(
        info=info,
        duration=duration,
        ticks_per_beat=ticks_per_beat,
        notes=tuple(sorted(notes, key=lambda note: (note.start, note.pitch))),
        tracks=tracks,
    )
