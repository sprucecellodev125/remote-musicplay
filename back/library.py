"""Scans the music/ directory and extracts metadata + cover art."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".mp4",
    ".aac", ".wav", ".wma", ".aiff", ".aif", ".ape", ".alac", ".wv",
}


class Track:
    """A single audio file + lazily-extracted metadata and cover art."""

    _COVER_NAMES = (
        "cover.jpg", "cover.jpeg", "cover.png",
        "folder.jpg", "folder.jpeg", "folder.png",
        "front.jpg", "front.png",
        "album.jpg", "album.png", "albumart.jpg",
    )

    def __init__(self, path: Path, root: Path):
        self.path = path.resolve()
        self.root = root
        self.id = hashlib.sha1(str(self.path).encode("utf-8")).hexdigest()[:16]
        self.title = self.path.stem
        self.artist = "Unknown artist"
        self.album = "Unknown album"
        self.duration = 0.0
        self._cover: Optional[bytes] = None
        self._cover_mime: Optional[str] = None
        self._cover_loaded = False
        self._read_tags()

    # ------------------------------------------------------------------ tags
    def _read_tags(self) -> None:
        try:
            audio = mutagen.File(self.path, easy=True)
        except Exception:
            audio = None
        if audio is None:
            return

        tags = getattr(audio, "tags", None)
        if tags:
            def first(key: str) -> Optional[str]:
                try:
                    values = tags.get(key)
                    return str(values[0]) if values else None
                except Exception:
                    return None

            self.title = first("title") or self.title
            self.artist = first("artist") or self.artist
            self.album = first("album") or self.album

        try:
            self.duration = float(audio.info.length)
        except Exception:
            self.duration = 0.0

    # ----------------------------------------------------------------- cover
    def _extract_cover(self) -> None:
        if self._cover_loaded:
            return
        self._cover_loaded = True

        try:
            raw = mutagen.File(self.path)
        except Exception:
            raw = None

        data, mime = self._embedded_cover(raw)
        if not data:
            data, mime = self._sibling_cover()

        if data:
            self._cover = data
            self._cover_mime = mime or "image/jpeg"

    @staticmethod
    def _embedded_cover(raw) -> Tuple[Optional[bytes], Optional[str]]:
        if raw is None:
            return None, None
        try:
            if isinstance(raw, FLAC) and raw.pictures:
                pic = raw.pictures[0]
                return pic.data, pic.mime or "image/jpeg"

            if isinstance(raw, MP4):
                tags = raw.tags or {}
                if "covr" in tags and len(tags["covr"]):
                    covr = tags["covr"][0]
                    fmt = getattr(covr, "imageformat", None)
                    mime = "image/png" if fmt == getattr(covr, "FORMAT_PNG", None) else "image/jpeg"
                    return bytes(covr), mime

            tags = getattr(raw, "tags", None)
            if tags is not None:
                # ID3 (MP3/WAV/AIFF) -> APIC frames
                for key in list(tags.keys()):
                    if str(key).startswith("APIC"):
                        apic = tags[key]
                        return apic.data, apic.mime or "image/jpeg"

                # Vorbis / Opus -> METADATA_BLOCK_PICTURE
                if "metadata_block_picture" in tags:
                    pic = Picture(base64.b64decode(tags["metadata_block_picture"][0]))
                    return pic.data, pic.mime or "image/jpeg"
        except Exception:
            pass
        return None, None

    def _sibling_cover(self) -> Tuple[Optional[bytes], Optional[str]]:
        try:
            files = {p.name.lower(): p for p in self.path.parent.iterdir() if p.is_file()}
        except OSError:
            return None, None
        for name in self._COVER_NAMES:
            target = files.get(name)
            if target:
                mime = "image/png" if target.suffix.lower() == ".png" else "image/jpeg"
                try:
                    return target.read_bytes(), mime
                except OSError:
                    return None, None
        return None, None

    # ------------------------------------------------------------------ api
    def cover(self) -> Tuple[Optional[bytes], Optional[str]]:
        self._extract_cover()
        return self._cover, self._cover_mime

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "duration": round(self.duration, 2),
            "filename": self.path.name,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Track {self.artist} - {self.title}>"


class MusicLibrary:
    """Holds every Track found under a root directory."""

    def __init__(self, music_dir: Path | str):
        self.root = Path(music_dir).resolve()
        self._tracks: Dict[str, Track] = {}
        self._order: List[str] = []
        self.scan()

    def scan(self) -> None:
        self._tracks.clear()
        self._order.clear()
        if not self.root.is_dir():
            return
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            try:
                track = Track(path, self.root)
            except Exception:
                continue
            self._tracks[track.id] = track
            self._order.append(track.id)

    def get(self, track_id: Optional[str]) -> Optional[Track]:
        return self._tracks.get(track_id) if track_id else None

    def all(self) -> List[Track]:
        return [self._tracks[i] for i in self._order]

    def next_id(self, track_id: Optional[str]) -> Optional[str]:
        if not self._order:
            return None
        if track_id not in self._order:
            return self._order[0]
        return self._order[(self._order.index(track_id) + 1) % len(self._order)]

    def previous_id(self, track_id: Optional[str]) -> Optional[str]:
        if not self._order:
            return None
        if track_id not in self._order:
            return self._order[0]
        return self._order[(self._order.index(track_id) - 1) % len(self._order)]
