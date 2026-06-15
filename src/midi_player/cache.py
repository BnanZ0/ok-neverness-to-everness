from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock

from .models import ParsedSong, SongInfo


@dataclass(frozen=True)
class _CacheEntry:
    song: ParsedSong
    mtime: float
    size: int


class ParsedSongCache:
    def __init__(self, max_items: int = 8) -> None:
        self.max_items = max(1, max_items)
        self._items: OrderedDict[str, _CacheEntry] = OrderedDict()

    def get(self, info: SongInfo) -> ParsedSong | None:
        entry = self._items.get(info.id)
        if entry is None:
            return None
        if entry.mtime != info.mtime or entry.size != info.size:
            self._items.pop(info.id, None)
            return None
        self._items.move_to_end(info.id)
        return entry.song

    def put(self, song: ParsedSong) -> None:
        self._items[song.info.id] = _CacheEntry(
            song=song,
            mtime=song.info.mtime,
            size=song.info.size,
        )
        self._items.move_to_end(song.info.id)
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)

    def remove(self, song_id: str) -> None:
        self._items.pop(song_id, None)

    def clear(self) -> None:
        self._items.clear()


@dataclass(frozen=True)
class MappedPitchCacheKey:
    song_id: str
    mtime: float
    size: int
    track_indices: tuple[int, ...] | None
    playable_pitches: tuple[int, ...]
    transpose: int
    smart_remap: bool


@dataclass(frozen=True)
class _MappedPitchEntry:
    pitches: tuple[int, ...]
    mtime: float
    size: int


class MappedPitchCache:
    def __init__(self, max_items: int = 16) -> None:
        self.max_items = max(1, max_items)
        self._items: OrderedDict[MappedPitchCacheKey, _MappedPitchEntry] = OrderedDict()
        self._lock = RLock()

    def get(self, key: MappedPitchCacheKey) -> tuple[int, ...] | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            if entry.mtime != key.mtime or entry.size != key.size:
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return entry.pitches

    def put(self, key: MappedPitchCacheKey, pitches: tuple[int, ...]) -> None:
        with self._lock:
            self._items[key] = _MappedPitchEntry(
                pitches=pitches,
                mtime=key.mtime,
                size=key.size,
            )
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    def remove_song(self, song_id: str) -> None:
        with self._lock:
            for key in tuple(self._items):
                if key.song_id == song_id:
                    self._items.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
