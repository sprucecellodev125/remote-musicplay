#!/usr/bin/env python3
"""main.py — the single parent file wiring back-end and front-end.

Run:
    python main.py                          # http://127.0.0.1:5000
    python main.py --host 0.0.0.0 --port 80 # expose on the LAN
    python main.py --music /path/to/music   # custom library folder
"""
from __future__ import annotations

import argparse
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from back import MusicLibrary, PlayerError, VLCPlayer

BASE_DIR = Path(__file__).resolve().parent


class MusicServer:
    """Owns the Flask app, the music library and the server-side player."""

    def __init__(self, music_dir: Path, front_dir: Path):
        self.music_dir = Path(music_dir).resolve()
        self.front_dir = Path(front_dir).resolve()
        self.music_dir.mkdir(parents=True, exist_ok=True)

        self.library = MusicLibrary(self.music_dir)
        self.player = VLCPlayer(self.library)

        self.app = Flask(
            __name__,
            static_folder=str(self.front_dir / "static"),
            static_url_path="/static",
        )
        self._register_routes()

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _error(message: str, code: int = 400):
        return jsonify({"error": message}), code

    # ------------------------------------------------------------- routes
    def _register_routes(self) -> None:
        app = self.app

        @app.get("/")
        def index():
            return send_from_directory(str(self.front_dir), "index.html")

        # ---- library ---------------------------------------------------
        @app.get("/api/tracks")
        def list_tracks():
            return jsonify({
                "root": str(self.music_dir),
                "tracks": [t.to_dict() for t in self.library.all()],
            })

        @app.post("/api/scan")
        def rescan():
            self.library.scan()
            return jsonify({"tracks": [t.to_dict() for t in self.library.all()]})

        @app.get("/api/cover/<track_id>")
        def cover(track_id: str):
            track = self.library.get(track_id)
            if track is None:
                abort(404)
            data, mime = track.cover()
            if not data:
                abort(404)
            return Response(
                data,
                mimetype=mime or "image/jpeg",
                headers={"Cache-Control": "public, max-age=86400"},
            )

        # ---- playback --------------------------------------------------
        @app.get("/api/status")
        def status():
            return jsonify(self.player.status())

        @app.post("/api/play")
        def play():
            payload = request.get_json(silent=True) or {}
            track_id = payload.get("id")
            if not track_id:
                return self._error("missing 'id'")
            try:
                self.player.play(track_id)
            except PlayerError as exc:
                return self._error(str(exc))
            return jsonify(self.player.status())

        @app.post("/api/toggle")
        def toggle():
            self.player.toggle()
            return jsonify(self.player.status())

        @app.post("/api/stop")
        def stop():
            self.player.stop()
            return jsonify(self.player.status())

        @app.post("/api/next")
        def next_track():
            self.player.next()
            return jsonify(self.player.status())

        @app.post("/api/previous")
        def previous_track():
            self.player.previous()
            return jsonify(self.player.status())

        @app.post("/api/seek")
        def seek():
            payload = request.get_json(silent=True) or {}
            try:
                position = float(payload.get("position", 0))
            except (TypeError, ValueError):
                return self._error("invalid 'position'")
            self.player.seek(position)
            return jsonify(self.player.status())

        @app.post("/api/volume")
        def volume():
            payload = request.get_json(silent=True) or {}
            try:
                level = int(payload.get("volume", 80))
            except (TypeError, ValueError):
                return self._error("invalid 'volume'")
            self.player.set_volume(level)
            return jsonify(self.player.status())

        # ---- SPA fallback ---------------------------------------------
        @app.errorhandler(404)
        def not_found(_err):
            if request.path.startswith("/api/"):
                return self._error("not found", 404)
            return send_from_directory(str(self.front_dir), "index.html")

    # ---------------------------------------------------------------- run
    def run(self, host: str = "0.0.0.0", port: int = 5000, debug: bool = False) -> None:
        self.app.run(host=host, port=port, debug=debug, threaded=True)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Server-side music player")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--music", default=str(BASE_DIR / "music"))
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    server = MusicServer(music_dir=Path(args.music), front_dir=BASE_DIR / "front")

    print(f"[music] library : {server.music_dir}")
    print(f"[music] tracks  : {len(server.library.all())}")
    print(f"[web]   listen  : http://{args.host}:{args.port}/")
    print("[hint]  audio leaves through the SERVER's sound card (Hi-Fi).")

    server.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
