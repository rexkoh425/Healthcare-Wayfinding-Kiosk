(() => {
  // ----- configuration -----
  const wordsPerMinute = 220;            // reading speed (adjustable)
  const minSentenceDuration = 2;         // seconds minimum to keep short sentences readable
  const startOffset = 0.8;               // seconds after video start to show first subtitle
  const gapBetweenSentences = 0.7;       // seconds pause between sentences
  const hideDelayBuffer = 0.5;
  // -------------------------

  function resolveWsUrl() {
    if (window.HOLOGRAM_WS_URL) {
      return window.HOLOGRAM_WS_URL;
    }
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const host = window.location.hostname || "localhost";
    return `${proto}://${host}:8080`;
  }

  const WS_URL = resolveWsUrl();
  const video = document.getElementById("player");
  const subtitleEl = document.getElementById("subtitle");

  function setVideoFile(filename) {
    if (!filename) return;
    const src = `assets/${filename}`;
    // if same file already loaded and playing, do nothing
    if (video.currentSrc && video.currentSrc.includes(filename)) {
      // ensure loop and play
      video.loop = true;
      video.muted = true;
      video.play().catch(() => {});
      return;
    }

    // replace source
    video.pause();
    const source = video.querySelector("source") || document.createElement("source");
    source.src = src;
    source.type = "video/mp4";
    if (!video.querySelector("source")) video.appendChild(source);
    video.load();
    video.loop = true;
    video.muted = true; // allow autoplay in many browsers
    video.play().catch((e) => {
      // autoplay may fail if browser blocks it
      console.warn("Autoplay blocked:", e);
    });
  }

  // default already points to wave.mp4 via HTML, but ensure play
  setVideoFile("wave.mp4");

  function splitIntoSentences(text) {
    // capture sentences including trailing punctuation
    const sentences = text.match(/[^.!?]+[.!?]?/g) || [text];
    return sentences.map(s => s.trim()).filter(Boolean);
  }

  function sentenceDurationSeconds(sentence) {
    const words = sentence.trim().split(/\s+/).filter(Boolean).length;
    const wps = wordsPerMinute / 60;
    const dur = words / wps;
    return Math.max(minSentenceDuration, dur);
  }

  // Keep track of timeouts for word reveals to cancel when needed
  let revealTimeouts = [];
  let hideTimeout = null;

  function clearRevealTimeouts() {
    revealTimeouts.forEach(id => clearTimeout(id));
    revealTimeouts = [];
    if (hideTimeout) {
      clearTimeout(hideTimeout);
      hideTimeout = null;
    }
  }

  function renderSubtitle(sentence, duration) {
    clearRevealTimeouts();

    subtitleEl.innerHTML = ""; // clear
    subtitleEl.classList.add("active");

    const words = sentence.split(/(\s+)/).filter(Boolean);
    // create spans: keep whitespace tokens so spacing preserved
    words.forEach((token, i) => {
      const span = document.createElement("span");
      // classify punctuation-only tokens slightly different
      const isSpace = /^\s+$/.test(token);
      if (isSpace) {
        span.textContent = token;
        span.className = "word space";
        // spaces don't get reveal animations
        span.style.opacity = 1;
      } else {
        span.textContent = token;
        // small class for punctuation-only tokens (keep margin tight)
        const isPunct = /^[.,:;!?-]+$/.test(token);
        span.className = "word" + (isPunct ? " punct" : "");
      }
      subtitleEl.appendChild(span);
    });

    // collect non-space word spans to animate
    const wordSpans = Array.from(subtitleEl.querySelectorAll(".word")).filter(s => !s.classList.contains("space"));

    // schedule reveals; distribute duration across visible words
    const visibleCount = wordSpans.length || 1;
    const interval = duration / visibleCount;
    wordSpans.forEach((sp, i) => {
      const id = setTimeout(() => {
        sp.classList.add("visible");
      }, Math.round(i * interval * 1000));
      revealTimeouts.push(id);
    });

    // schedule hide (give a small buffer)
    hideTimeout = setTimeout(() => {
      subtitleEl.classList.remove("active");
      // remove visible classes for next time
      wordSpans.forEach(s => s.classList.remove("visible"));
      clearRevealTimeouts();
    }, Math.round((duration + hideDelayBuffer) * 1000));
  }

  class SubtitleScheduler {
    constructor(cues, opts = {}) {
      this.cues = cues.map(c => ({ ...c })); // copy
      this.duration = Math.max(0, opts.duration ?? (this.cues.length ? this.cues[this.cues.length - 1].end : 0));
      this.rate = opts.rate || 1.0;      // playback rate for timeline
      this.loop = !!opts.loop;           // whether timeline loops
      this.running = false;
      this._rafId = null;
      this._startPerf = 0;               // performance.now() at start
      this._pausedOffset = 0;            // seconds offset when paused
      this._lastElapsed = -1;
      this._onCueShow = opts.onCueShow || ((cue) => renderSubtitle(cue.text, cue.duration));
      this._onEnd = opts.onEnd || (() => {});
      this.syncMode = null;              // null | { type: "video", video }
    }

    // real elapsed timeline seconds, respecting rate, loops, etc.
    _elapsedSeconds() {
      if (this.syncMode && this.syncMode.type === "video" && this.syncMode.video) {
        // in video-sync mode, follow video.currentTime directly
        return this.syncMode.video.currentTime;
      }
      // otherwise compute from perf time
      const now = performance.now();
      const raw = ((now - this._startPerf) / 1000) * this.rate + this._pausedOffset;
      if (this.loop && this.duration > 0) {
        return raw % this.duration;
      }
      return Math.min(raw, this.duration);
    }

    _tick = () => {
      if (!this.running) return;
      const elapsed = this._elapsedSeconds();

      // if elapsed decreased drastically (seek or wrap), reset shownAt so cues can re-show
      if (this._lastElapsed > 0 && elapsed + 0.001 < this._lastElapsed && Math.abs(this._lastElapsed - elapsed) > 0.2) {
        // treat as a seek/wrap event -> allow cues after elapsed to be shown again
        this.cues.forEach(c => { if (c.start >= elapsed) c.shownAt = null; });
      }
      this._lastElapsed = elapsed;

      // find cue(s) that should be shown now (start <= elapsed <= end)
      for (const cue of this.cues) {
        if (elapsed + 0.0001 >= cue.start && elapsed <= cue.end + 0.05) {
          // show cue if not shown recently (prevent duplicate rapid shows)
          if (!cue.shownAt) {
            cue.shownAt = performance.now();
            this._onCueShow(cue);
          }
        } else {
          // if cue is out-of-window and previously shown but the elapsed is now before cue.start,
          // allow re-show on future passes (useful for looping)
          if (cue.shownAt && elapsed + 0.01 < cue.start) cue.shownAt = null;
        }
      }

      // if reached (non-loop) end, stop
      if (!this.loop && elapsed >= this.duration - 0.001) {
        this.stop();
        this._onEnd();
        return;
      }

      this._rafId = requestAnimationFrame(this._tick);
    }

    start(offsetSeconds = 0) {
      // offsetSeconds is where the timeline should start (relative)
      this.stop(); // ensure no double-run
      this.running = true;
      this._pausedOffset = offsetSeconds;
      this._startPerf = performance.now();
      this._lastElapsed = -1;
      // clear shownAt for cues before offset so they're not shown
      for (const c of this.cues) c.shownAt = (c.start < offsetSeconds) ? performance.now() : null;
      this._rafId = requestAnimationFrame(this._tick);
    }

    pause() {
      if (!this.running) return;
      // compute current elapsed and store it as paused offset
      const elapsedNow = this._elapsedSeconds();
      this._pausedOffset = elapsedNow;
      this.running = false;
      if (this._rafId) cancelAnimationFrame(this._rafId);
      this._rafId = null;
    }

    resume() {
      if (this.running) return;
      this.running = true;
      this._startPerf = performance.now();
      // keep _pausedOffset as-is
      this._rafId = requestAnimationFrame(this._tick);
    }

    stop(resetToZero = true) {
      this.running = false;
      if (this._rafId) cancelAnimationFrame(this._rafId);
      this._rafId = null;
      if (resetToZero) {
        this._pausedOffset = 0;
        for (const c of this.cues) c.shownAt = null;
        this._lastElapsed = -1;
      }
    }

    seek(timeSeconds) {
      // set paused offset to timeSeconds and continue running if running
      this._pausedOffset = Math.max(0, Math.min(timeSeconds, this.duration));
      this._startPerf = performance.now();
      // clear shownAt for cues after current time so they'll show
      for (const c of this.cues) {
        if (c.start >= this._pausedOffset) c.shownAt = null;
      }
    }

    setRate(rate) {
      // change playback rate; adjust internal timers so elapsed doesn't jump
      const elapsedNow = this._elapsedSeconds();
      this.rate = rate;
      this._pausedOffset = elapsedNow;
      this._startPerf = performance.now();
    }

    setLooping(loop) {
      this.loop = !!loop;
    }

    // sync mode: tie subtitle timeline to a video's currentTime (still tolerant of video loops)
    enableVideoSync(videoEl) {
      this.syncMode = { type: "video", video: videoEl };
      // when entering sync mode, clear shownAt for cues < currentTime so they can show correctly
      const t = videoEl.currentTime || 0;
      for (const c of this.cues) c.shownAt = (c.start < t) ? performance.now() : null;
    }

    disableVideoSync() {
      this.syncMode = null;
    }
  }

  // ---------------- create scheduler and expose API ----------------
  const scheduler = new SubtitleScheduler([], {
    duration: 0,
    rate: 1.0,
    loop: false,
    onCueShow: (cue) => renderSubtitle(cue.text, cue.duration),
    onEnd: () => {
      // if non-looping, hide subtitle after end
      subtitleEl.classList.remove("active");
      clearRevealTimeouts();
    }
  });

  // Expose a friendly API
  window.hologramSubtitles = {
    scheduler,
    start: (offset = 0) => scheduler.start(offset),
    pause: () => scheduler.pause(),
    resume: () => scheduler.resume(),
    stop: (reset = true) => scheduler.stop(reset),
    seek: (t) => scheduler.seek(t),
    setRate: (r) => scheduler.setRate(r),
    setLooping: (b) => scheduler.setLooping(!!b),
    enableVideoSync: () => scheduler.enableVideoSync(video),
    disableVideoSync: () => scheduler.disableVideoSync(),
    clear: () => {
      scheduler.stop(true);
      subtitleEl.classList.remove("active");
      clearRevealTimeouts();
    }
  };

  function syncSubtitlesForVideo(filename, customText) {
    if (!subtitleEl) return;
    if (filename === "reply.mp4") {
      // Decoupled: just start the scheduler, do NOT sync to video
      scheduler.disableVideoSync();
      if (typeof customText === "string" && customText.trim().length > 0) {
        updateSubtitleText(customText);
      }
      scheduler.start(0);
    } else {
      // any other video -> hide subtitles and stop scheduler
      scheduler.disableVideoSync();
      scheduler.stop(true);
      subtitleEl.classList.remove("active");
      clearRevealTimeouts();
    }
  }

  // Helper to update cues and scheduler with new text
  function updateSubtitleText(newText) {
    const sentences = splitIntoSentences(newText);
    let t = startOffset;
    const newCues = sentences.map((s, i) => {
      const dur = sentenceDurationSeconds(s);
      const cue = { id: i, text: s, start: t, end: t + dur, duration: dur, shownAt: null };
      t = cue.end + gapBetweenSentences;
      return cue;
    });
    scheduler.cues = newCues;
    scheduler.duration = newCues.length ? newCues[newCues.length - 1].end : 0;
  }

  // WebSocket connection
  let ws;
  function connect() {
    ws = new WebSocket(WS_URL);
    ws.addEventListener("open", () => {
      console.log("WS open -> registering as hologram");
      ws.send(JSON.stringify({ type: "register", role: "hologram" }));
    });

    ws.addEventListener("message", (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "set" && msg.video) {
          console.log("Set video to", msg.video, "reason:", msg.reason);
          setVideoFile(msg.video);
          // syncSubtitlesForVideo(msg.video);
        } else if (msg.type === "subtitle" && typeof msg.text === "string") {
          // Only show subtitle if reply.mp4 is active
          if (video.currentSrc && video.currentSrc.includes("reply.mp4")) {
            syncSubtitlesForVideo("reply.mp4", msg.text); // Pass custom text
          }
        } else if (msg.type === "registered") {
          console.log("Registered OK as", msg.role);
        } else {
          console.log("WS msg:", msg);
        }
      } catch (err) {
        console.warn("Invalid WS payload", ev.data);
      }
    });

    ws.addEventListener("close", () => {
      console.warn("WS closed, will attempt reconnect in 2s");
      setTimeout(connect, 2000);
    });

    ws.addEventListener("error", (err) => {
      console.warn("WS error", err);
    });
  }

  connect();
})();
