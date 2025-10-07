(() => {
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
