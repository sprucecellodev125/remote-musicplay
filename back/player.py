"""Server-side playback engine (libVLC).

The Flask process owns the audio output, so whatever is wired to the
machine's sound card — the Hi-Fi system — is what actually plays.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional

import vlc

from .library import MusicLibrary


class PlayerError(RuntimeError):
    """Raised when a playback command cannot be fulfilled."""


class VLCPlayer:
    """Thread-safe wrapper around a libVLC MediaPlayer."""

    _STATE_MAP = {
        "NothingSpecial": "stopped",
        "Stopped": "stopped",
        "Ended": "stopped",
        "Error": "stopped",
        "Playing": "playing",
        "Buffering": "playing",
        "Paused": "paused",
    }

    def __init__(self, library: MusicLibrary, volume: int = 80):
        self._library = library
        self._lock = threading.RLock()
        self._current_id: Optional[str] = None
        self._end_pending = False
        self._volume = max(0, min(100, int(volume)))

        try:
            self._instance = vlc.Instance("--no-video", "--aout=pulse", "--quiet")
        except Exception as exc:  # libvlc missing
            raise PlayerError(
                "libVLC is unavailable. Install VLC (e.g. `sudo apt install vlc`) "
                "and the `python-vlc` package."
            ) from exc
        if self._instance is None:
            raise PlayerError("Could not initialise libVLC.")

        self._player = self._instance.media_player_new()
        self._player.event_manager().event_attach(
            vlc.EventType.MediaPlayerEndReached, self._on_end_reached
        )
        self._player.audio_set_volume(self._volume)

    # ------------------------------------------------------------- internals
    def _on_end_reached(self, _event) -> None:
        # Runs on a libVLC thread — do NOT call back into libVLC here.
        # Just flag it; the status poll advances the queue safely.
        self._end_pending = True

    def _current_track(self):
        return self._library.get(self._current_id)

    def _start(self, track_id: str) -> None:
        track = self._library.get(track_id)
        if track is None:
            raise PlayerError(f"Unknown track: {track_id}")
        media = self._instance.media_new(str(track.path))
        media.add_option("no-video")
        self._player.set_media(media)
        self._player.play()
        self._current_id = track.id

    def _advance(self, direction: int) -> None:
        next_id = (
            self._library.next_id(self._current_id)
            if direction > 0
            else self._library.previous_id(self._current_id)
        )
        if next_id:
            self._start(next_id)
        else:
            self._player.stop()
            self._current_id = None

    # ------------------------------------------------------------ public API
    def play(self, track_id: str) -> None:
        with self._lock:
            self._start(track_id)

    def toggle(self) -> None:
        with self._lock:
            state = self._player.get_state()
            if state == vlc.State.Playing:
                self._player.set_pause(1)
            elif state == vlc.State.Paused:
                self._player.set_pause(0)
            elif self._current_id:
                self._start(self._current_id)
            else:
                first = self._library.next_id(None)
                if first:
                    self._start(first)

    def stop(self) -> None:
        with self._lock:
            self._player.stop()
            self._current_id = None
            self._end_pending = False

    def next(self) -> None:
        with self._lock:
            self._advance(1)

    def previous(self) -> None:
        with self._lock:
            self._advance(-1)

    def seek(self, seconds: float) -> None:
        with self._lock:
            self._player.set_time(max(0, int(float(seconds) * 1000)))

    def set_volume(self, volume: int) -> None:
        with self._lock:
            self._volume = max(0, min(100, int(volume)))
            self._player.audio_set_volume(self._volume)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            if self._end_pending:
                self._end_pending = False
                if self._current_id is not None:
                    self._advance(1)

            raw_state = self._player.get_state()
            name = getattr(raw_state, "name", str(raw_state))
            playback = self._STATE_MAP.get(name, "stopped")

            track = self._current_track()
            pos_ms = self._player.get_time()
            len_ms = self._player.get_length()
            if len_ms <= 0 and track is not None:
                len_ms = int(track.duration * 1000)

            return {
                "state": playback,
                "track": track.to_dict() if track else None,
                "position": round(max(0, pos_ms) / 1000.0, 2),
                "duration": round(max(0, len_ms) / 1000.0, 2),
                "volume": self._volume,
            }
