from __future__ import annotations

import asyncio
import json
import shutil
import threading
from pathlib import Path
from typing import Iterable

from .cache import MappedPitchCache, ParsedSongCache
from .models import LibrarySnapshot, ParsedSong, SongInfo
from .parser import parse_midi_file

MIDI_EXTENSIONS = {".mid", ".midi"}


class MidiLibraryService:
    def __init__(
        self,
        library_dir: str | Path | None = None,
        *,
        cache: ParsedSongCache | None = None,
        favorites_file: str | Path | None = None,
    ) -> None:
        self.library_dir = Path(library_dir) if library_dir else self._default_library_dir()
        self.cache = cache or ParsedSongCache()
        self.mapped_pitch_cache = MappedPitchCache()
        self.favorites_file = (
            Path(favorites_file) if favorites_file else self.library_dir / ".favorites.json"
        )
        self._lock = threading.RLock()
        self._favorites: set[str] = set()
        self._songs: dict[str, SongInfo] = {}
        self._loading = False
        self._error: str | None = None
        self._index_task: asyncio.Task[None] | None = None
        self._parse_tasks: dict[tuple[int, str], asyncio.Task[ParsedSong]] = {}

    def _default_library_dir(self) -> Path:
        from ok import get_path_relative_to_exe

        return Path(get_path_relative_to_exe("mid_lib"))

    def start_background_index(self) -> asyncio.Task[None] | None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.index()
            return None
        if self._index_task is None or self._index_task.done():
            self._index_task = loop.create_task(self.index_async())
        return self._index_task

    async def index_async(self) -> None:
        self._loading = True
        self._error = None
        try:
            songs = await asyncio.to_thread(self._scan_library)
            with self._lock:
                self._songs = {song.id: song for song in songs}
        except Exception as exc:  # noqa: BLE001 - UI needs a friendly error string.
            self._error = str(exc)
        finally:
            self._loading = False

    def index(self) -> None:
        self._loading = True
        self._error = None
        try:
            songs = self._scan_library()
            with self._lock:
                self._songs = {song.id: song for song in songs}
        except Exception as exc:  # noqa: BLE001
            self._error = str(exc)
        finally:
            self._loading = False

    def list_songs(self) -> list[SongInfo]:
        with self._lock:
            songs = list(self._songs.values())
        return sorted(songs, key=lambda song: (not song.favorite, song.title.lower()))

    def song_info(self, song_id: str) -> SongInfo:
        return self._require_song(song_id)

    def cache_parsed_song(self, parsed_song: ParsedSong) -> None:
        with self._lock:
            self.cache.put(parsed_song)

    def snapshot(self) -> LibrarySnapshot:
        return LibrarySnapshot(
            loading=self._loading,
            songs=self.list_songs(),
            error=self._error,
        )

    async def get_or_parse_song(self, song_id: str) -> ParsedSong:
        info = self._require_song(song_id)
        with self._lock:
            cached = self.cache.get(info)
        if cached is not None:
            return cached

        loop = asyncio.get_running_loop()
        task_key = (id(loop), song_id)
        with self._lock:
            task = self._parse_tasks.get(task_key)
            if task is None or task.done():
                task = asyncio.create_task(asyncio.to_thread(parse_midi_file, info))
                self._parse_tasks[task_key] = task

        try:
            parsed = await task
        finally:
            if task.done():
                with self._lock:
                    self._parse_tasks.pop(task_key, None)

        with self._lock:
            self.cache.put(parsed)
        return parsed

    def get_or_parse_song_sync(self, song_id: str) -> ParsedSong:
        info = self._require_song(song_id)
        with self._lock:
            cached = self.cache.get(info)
        if cached is not None:
            return cached
        parsed = parse_midi_file(info)
        with self._lock:
            self.cache.put(parsed)
        return parsed

    def import_files(self, paths: Iterable[str | Path]) -> list[SongInfo]:
        self.library_dir.mkdir(parents=True, exist_ok=True)
        imported: list[SongInfo] = []
        for source in paths:
            source_path = Path(source)
            if source_path.suffix.lower() not in MIDI_EXTENSIONS:
                continue
            target = self._unique_target(source_path.name)
            shutil.copy2(source_path, target)
            info = self._song_info_from_path(target)
            with self._lock:
                self._songs[info.id] = info
            imported.append(info)
        return imported

    def set_favorite(self, song_id: str, favorite: bool) -> SongInfo:
        info = self._require_song(song_id)
        with self._lock:
            if favorite:
                self._favorites.add(song_id)
            else:
                self._favorites.discard(song_id)
            self._save_favorites()
        updated = SongInfo(
            id=info.id,
            title=info.title,
            path=info.path,
            size=info.size,
            mtime=info.mtime,
            favorite=favorite,
        )
        with self._lock:
            self._songs[song_id] = updated
        return updated

    def _scan_library(self) -> list[SongInfo]:
        self.library_dir.mkdir(parents=True, exist_ok=True)
        favorites = self._load_favorites()
        with self._lock:
            self._favorites = favorites
        songs = []
        for path in self.library_dir.rglob("*"):
            if path.suffix.lower() in MIDI_EXTENSIONS and path.is_file():
                songs.append(self._song_info_from_path(path))
        return songs

    def _song_info_from_path(self, path: Path) -> SongInfo:
        stat = path.stat()
        song_id = path.resolve().as_posix()
        with self._lock:
            favorite = song_id in self._favorites
        return SongInfo(
            id=song_id,
            title=path.stem,
            path=path,
            size=stat.st_size,
            mtime=stat.st_mtime,
            favorite=favorite,
        )

    def _require_song(self, song_id: str) -> SongInfo:
        with self._lock:
            info = self._songs.get(song_id)
        if info is None:
            raise KeyError(f"Unknown MIDI song: {song_id}")
        return info

    def _unique_target(self, filename: str) -> Path:
        source_name = Path(filename).name
        stem = Path(source_name).stem
        suffix = Path(source_name).suffix
        target = self.library_dir / source_name
        index = 1
        while target.exists():
            target = self.library_dir / f"{stem}_{index}{suffix}"
            index += 1
        return target

    def _load_favorites(self) -> set[str]:
        if not self.favorites_file.exists():
            return set()
        try:
            raw = json.loads(self.favorites_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        if not isinstance(raw, list):
            return set()
        return {str(item) for item in raw}

    def _save_favorites(self) -> None:
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.favorites_file.write_text(
            json.dumps(sorted(self._favorites), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
