(() => {
  "use strict";

  const PLACEHOLDER =
    "data:image/svg+xml;utf8," +
    encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' +
        '<rect width="100" height="100" fill="#212529"/>' +
        '<path d="M42 68a8 8 0 1 1-6-7.7V38l30-6v26.3a8 8 0 1 1-6-7.7V40l-18 3.6z" fill="#495057"/>' +
      "</svg>"
    );

  const $ = (id) => document.getElementById(id);

  const ui = {
    cover: $("cover"), title: $("np-title"), artist: $("np-artist"), album: $("np-album"),
    progress: $("progress"), pos: $("pos"), dur: $("dur"),
    toggle: $("toggle"), iconPlay: $("icon-play"), iconPause: $("icon-pause"),
    prev: $("prev"), next: $("next"), stop: $("stop"),
    volume: $("volume"), volLabel: $("vol-label"),
    list: $("track-list"), search: $("search"), count: $("count"), rescan: $("rescan"),
  };

  const state = {
    tracks: [], currentId: null, playing: false,
    duration: 0, seeking: false, volumeDragging: false, lastCoverId: null,
  };

  /* ------------------------------- helpers ------------------------------- */
  const fmtTime = (sec) => {
    sec = Number(sec) || 0;
    return `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;
  };

  const escapeHtml = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));

  async function api(path, options = {}) {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
    return data;
  }
  const post = (path, body) =>
    api(path, { method: "POST", body: JSON.stringify(body || {}) });

  /* --------------------------- library rendering ------------------------- */
  function renderTracks() {
    const term = ui.search.value.trim().toLowerCase();
    const visible = state.tracks.filter((t) =>
      !term || `${t.title} ${t.artist} ${t.album}`.toLowerCase().includes(term));

    ui.list.innerHTML = "";
    ui.count.textContent = state.tracks.length;

    if (!visible.length) {
      ui.list.innerHTML =
        '<div class="p-4 text-center text-secondary">' +
        'No tracks found. Drop audio files into the <code>music/</code> folder and press ' +
        '<i class="bi bi-arrow-clockwise"></i> Rescan.</div>';
      return;
    }

    const frag = document.createDocumentFragment();
    for (const track of visible) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "list-group-item list-group-item-action track-item";
      btn.dataset.id = track.id;
      if (track.id === state.currentId) btn.classList.add("active");

      const img = document.createElement("img");
      img.className = "mini-cover";
      img.alt = "";
      img.addEventListener("error", () => { img.src = PLACEHOLDER; }, { once: true });
      img.src = `/api/cover/${track.id}`;

      const info = document.createElement("div");
      info.className = "flex-grow-1 overflow-hidden";
      info.innerHTML =
        `<div class="text-truncate fw-semibold">${escapeHtml(track.title)}</div>` +
        `<div class="small text-secondary text-truncate">${escapeHtml(track.artist)} · ${escapeHtml(track.album)}</div>`;

      const time = document.createElement("span");
      time.className = "small text-secondary ms-2";
      time.textContent = fmtTime(track.duration);

      btn.append(img, info, time);
      frag.appendChild(btn);
    }
    ui.list.appendChild(frag);
  }

  function highlightActive() {
    ui.list.querySelectorAll(".track-item").forEach((el) =>
      el.classList.toggle("active", el.dataset.id === state.currentId));
  }

  /* ------------------------------ status sync ---------------------------- */
  function updateNowPlaying(s) {
    const track = s.track;
    state.playing = s.state === "playing";
    state.currentId = track ? track.id : null;
    state.duration = s.duration || 0;

    ui.iconPlay.classList.toggle("d-none", state.playing);
    ui.iconPause.classList.toggle("d-none", !state.playing);

    if (track) {
      ui.title.textContent = track.title;
      ui.artist.textContent = track.artist;
      ui.album.textContent = track.album;
      if (track.id !== state.lastCoverId) {
        state.lastCoverId = track.id;
        ui.cover.src = `/api/cover/${track.id}`;
      }
    } else {
      ui.title.textContent = "Nothing playing";
      ui.artist.textContent = "—";
      ui.album.textContent = "—";
      if (state.lastCoverId !== null) {
        state.lastCoverId = null;
        ui.cover.src = PLACEHOLDER;
      }
    }

    if (!state.seeking) {
      const pos = Math.min(s.position || 0, state.duration || 0);
      ui.progress.value = state.duration ? Math.round((pos / state.duration) * 1000) : 0;
      ui.pos.textContent = fmtTime(pos);
      ui.dur.textContent = fmtTime(state.duration);
    }

    if (!state.volumeDragging && typeof s.volume === "number" && s.volume >= 0) {
      ui.volume.value = s.volume;
      ui.volLabel.textContent = s.volume;
    }

    highlightActive();
  }

  async function poll() {
    try {
      updateNowPlaying(await api("/api/status"));
    } catch (_) { /* server busy / restarting — keep polling */ }
    setTimeout(poll, 700);
  }

  /* -------------------------------- actions ------------------------------ */
  async function run(fn) {
    try {
      const s = await fn();
      if (s && s.state !== undefined) updateNowPlaying(s);
    } catch (err) {
      console.error(err);
    }
  }

  ui.list.addEventListener("click", (e) => {
    const item = e.target.closest(".track-item");
    if (item) run(() => post("/api/play", { id: item.dataset.id }));
  });

  ui.toggle.addEventListener("click", () => run(() => post("/api/toggle")));
  ui.stop.addEventListener("click", () => run(() => post("/api/stop")));
  ui.next.addEventListener("click", () => run(() => post("/api/next")));
  ui.prev.addEventListener("click", () => run(() => post("/api/previous")));

  ui.progress.addEventListener("input", () => {
    state.seeking = true;
    ui.pos.textContent = fmtTime((Number(ui.progress.value) / 1000) * state.duration);
  });
  ui.progress.addEventListener("change", () => {
    const position = (Number(ui.progress.value) / 1000) * state.duration;
    state.seeking = false;
    run(() => post("/api/seek", { position }));
  });

  ui.volume.addEventListener("input", () => {
    state.volumeDragging = true;
    ui.volLabel.textContent = ui.volume.value;
  });
  ui.volume.addEventListener("change", () => {
    const volume = Number(ui.volume.value);
    state.volumeDragging = false;
    run(() => post("/api/volume", { volume }));
  });

  ui.search.addEventListener("input", renderTracks);
  ui.rescan.addEventListener("click", async () => {
    ui.rescan.disabled = true;
    try {
      const data = await post("/api/scan");
      state.tracks = data.tracks || [];
      renderTracks();
    } catch (err) {
      console.error(err);
    } finally {
      ui.rescan.disabled = false;
    }
  });

  ui.cover.addEventListener("error", () => { ui.cover.src = PLACEHOLDER; });

  /* --------------------------------- init -------------------------------- */
  (async function init() {
    try {
      const data = await api("/api/tracks");
      state.tracks = data.tracks || [];
    } catch (err) {
      console.error(err);
    }
    renderTracks();
    ui.cover.src = PLACEHOLDER;
    poll();
  })();
})();
