// components/screens/2D_map.jsx
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

const MAP_W = 3000;
const MAP_H = 2000;
const MARGIN = 50;

export default function TwoDMapScreen() {
  const searchParams = useSearchParams();

  // Single-floor params
  const fileParam = searchParams.get("file") || "/2D_map/maps/lvl1.json";
  const fromParam = searchParams.get("from") || "";
  const toParam = searchParams.get("to") || "";
  const leadInParam = Number(searchParams.get("leadIn") || "800");

  // Highlights (optional)
  const dests = searchParams.getAll("dest"); // ["Clinic A", "Clinic B"]

  // Multi-floor route (optional)
  const routeSegments = useMemo(() => {
    const raw = searchParams.get("route");
    if (!raw) return [];
    try {
      const arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return [];
      return arr
        .filter(
          (s) =>
            s &&
            typeof s.file === "string" &&
            Array.isArray(s.labels) &&
            s.labels.length >= 2
        )
        .map((s) => ({ file: s.file, labels: s.labels }));
    } catch {
      return [];
    }
  }, [searchParams]);

  const svgRef = useRef(null);
  const mapContentRef = useRef(null);
  const frameRef = useRef(null);
  const clipRectRef = useRef(null);
  const stageRef = useRef(null);

  const [mapName, setMapName] = useState("Loading...");
  const replayRef = useRef<() => void>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    const svg = svgRef.current;
    const mapContent = mapContentRef.current;
    const frame = frameRef.current;
    const clipRect = clipRectRef.current;
    const stage = stageRef.current;
    if (!svg || !mapContent || !frame || !clipRect || !stage) return;

    // Geometry (once)
    svg.setAttribute("viewBox", `0 0 ${MAP_W} ${MAP_H}`);
    frame.setAttribute("x", String(MARGIN));
    frame.setAttribute("y", String(MARGIN));
    frame.setAttribute("width", String(MAP_W - 2 * MARGIN));
    frame.setAttribute("height", String(MAP_H - 2 * MARGIN));
    clipRect.setAttribute("x", String(MARGIN));
    clipRect.setAttribute("y", String(MARGIN));
    clipRect.setAttribute("width", String(MAP_W - 2 * MARGIN));
    clipRect.setAttribute("height", String(MAP_H - 2 * MARGIN));

    // View state
    let zoom = 1;
    let panX = 0;
    let panY = 0;
    let viewFromJSON = false; // lock view if JSON provides settings

    const cx = MARGIN + (MAP_W - 2 * MARGIN) / 2;
    const cy = MARGIN + (MAP_H - 2 * MARGIN) / 2;

    const STEP_MS = 120;
    const CLOSE_THRESHOLD = 30;
    const IMAGE_SIZE = 120;

    let rafId = 0;

    function centerOnSmooth(x, y, duration = 220) {
	const startX = panX, startY = panY;
	const endX = -zoom * (x - cx);
	const endY = -zoom * (y - cy);
	const t0 = performance.now();
	cancelAnimationFrame(rafId);
    	function step(now) {
		const p = Math.min(1, (now - t0) / duration);
		const e = p * (2 - p); // easeOutQuad
		panX = startX + (endX - startX) * e;
		panY = startY + (endY - startY) * e;
		applyTransform();
		if (p < 1) rafId = requestAnimationFrame(step);
    	}
	rafId = requestAnimationFrame(step);
    }

    function maybeCenter(x, y, minDelta = 80, dur = 220) {
	const tx = -zoom * (x - cx);
	const ty = -zoom * (y - cy);
	if (Math.hypot(tx - panX, ty - panY) > minDelta) centerOnSmooth(x, y, dur);
    }

    const clampZoom = (z) => Math.min(6, Math.max(0.3, z));

    const applyTransform = () => {
      mapContent.setAttribute(
        "transform",
        `translate(${panX},${panY}) translate(${cx},${cy}) scale(${zoom}) translate(${-cx},${-cy})`
      );
    };

    const fitToStage = () => {
      const { clientWidth: w, clientHeight: h } = stage;
      const sx = (w * 0.92) / MAP_W;
      const sy = (h * 0.92) / MAP_H;
      zoom = clampZoom(Math.min(sx, sy));
      panX = 0;
      panY = 0;
      applyTransform();
    };

    const centerOn = (x, y) => {
      panX = -zoom * (x - cx);
      panY = -zoom * (y - cy);
      applyTransform();
    };

    // ---------- helpers ----------
    const verticesToPath = (verts) =>
      verts.map((v, i) => (i ? "L" : "M") + " " + v[0] + " " + v[1]).join(" ") + " Z";

    function getOrMakeNodeLabel(x, y, G) {
      for (const lbl in G)
        if (Math.hypot(G[lbl].x - x, G[lbl].y - y) < CLOSE_THRESHOLD) return lbl;
      const lbl = `P${Object.keys(G).length + 1}`;
      G[lbl] = { x, y, neighbors: new Set() };
      return lbl;
    }

    function buildGraph() {
      const G = {};

      document.querySelectorAll("#markers-layer circle").forEach((c) => {
        const lbl = c.dataset.label;
        if (!lbl) return;
        G[lbl] = {
          x: +c.getAttribute("cx"),
          y: +c.getAttribute("cy"),
          neighbors: new Set(),
        };
      });

      document.querySelectorAll("#lines-layer line").forEach((l) => {
        const x1 = +l.getAttribute("x1");
        const y1 = +l.getAttribute("y1");
        const x2 = +l.getAttribute("x2");
        const y2 = +l.getAttribute("y2");
        const n1 = getOrMakeNodeLabel(x1, y1, G);
        const n2 = getOrMakeNodeLabel(x2, y2, G);
        if (n1 === n2) return;
        G[n1].neighbors.add(n2);
        G[n2].neighbors.add(n1);
        l._markers = [n1, n2]; // for highlightPath stitching
      });

      return G;
    }

    function shortestPath(startLbl, endLbl) {
      const G = buildGraph();
      if (!G[startLbl] || !G[endLbl]) return null;

      const q = [startLbl];
      const prev = { [startLbl]: null };
      while (q.length) {
        const v = q.shift();
        if (v === endLbl) break;
        G[v].neighbors.forEach((n) => {
          if (!(n in prev)) {
            prev[n] = v;
            q.push(n);
          }
        });
      }
      if (!(endLbl in prev)) return null;

      const out = [];
      for (let cur = endLbl; cur; cur = prev[cur]) out.push(cur);
      return out.reverse();
    }

    // ---------- image triggers + highlight ----------
    const imgTriggers = [];
    let pathTimer = null;

    const addImgTrigger = (x, y, url, w = IMAGE_SIZE, h = IMAGE_SIZE) => {
      const img = document.createElementNS(svg.namespaceURI, "image");
      img.setAttribute("href", url);
      img.setAttribute("x", String(x - w / 2));
      img.setAttribute("y", String(y - h / 2));
      img.setAttribute("width", String(w));
      img.setAttribute("height", String(h));
      img.classList.add("img-trigger");
      document.getElementById("markers-layer").appendChild(img);
      imgTriggers.push({ id: `img-${imgTriggers.length}`, x, y, el: img, active: false, hideTimer: null });
      return img;
    };

    const clearHighlight = () => {
      if (pathTimer) window.clearInterval(pathTimer);
      pathTimer = null;
      document.querySelectorAll(".map-line-dot")
        .forEach((d:any) => {
		d.style.fill = "#fff"
		d.style.display = "none";
	});
      imgTriggers.forEach((t) => {
        t.active = false;
        t.el.style.transform = "scale(.12)";
        t.el.style.opacity = "0";
      });
    };

    const updateImageTriggers = (dotX, dotY) => {
      const HIT = 100;
      const HOLD = 4000;
      imgTriggers.forEach((t) => {
        const near = Math.hypot(t.x - dotX, t.y - dotY) < HIT;
        if (near && !t.active) {
          t.active = true;
          clearTimeout(t.hideTimer);
          t.el.style.opacity = "1";
          t.el.style.transform = "scale(1.6)";
        } else if (!near && t.active) {
          t.active = false;
          t.hideTimer = setTimeout(() => {
            if (!t.active) {
              t.el.style.transform = "scale(.12)";
              t.el.style.opacity = "0";
            }
          }, HOLD);
        }
      });
    };
	const highlightPath = (labels, leadIn = 0) => {
	  clearHighlight();
	  if (!labels || labels.length < 2) return 0;

	  // Ensure _markers are set on lines
	  buildGraph();

	  const allLines = Array.from(document.querySelectorAll("#lines-layer line"));
	  const lineFor = (a, b) =>
	    allLines.find(
	      (ln) =>
		ln._markers &&
		((ln._markers[0] === a && ln._markers[1] === b) ||
		 (ln._markers[0] === b && ln._markers[1] === a))
	    );

	  const sequence = [];
	  for (let i = 0; i < labels.length - 1; i++) {
	    const a = labels[i], b = labels[i + 1];

	    // Use BFS path through nodes
	    const pathNodes = shortestPath(a, b);
	    if (!pathNodes || pathNodes.length < 2) {
	      console.warn("No path between", a, b);
	      continue;
	    }

	    for (let j = 0; j < pathNodes.length - 1; j++) {
	      const L = lineFor(pathNodes[j], pathNodes[j + 1]);
	      if (!L || !L._dots || !L._dots.length) {
		console.warn("Missing line/dots between", pathNodes[j], pathNodes[j + 1]);
		continue;
	      }
	      const ordered =
		L._markers[0] === pathNodes[j] ? L._dots : L._dots.slice().reverse();
	      sequence.push(...ordered);
	    }
	  }

	  if (!sequence.length) return 0;

	  const d0 = sequence[0];
	  centerOn(+d0.getAttribute("cx"), +d0.getAttribute("cy"));

	  const CENTER_EVERY = 4; // throttle camera panning
	  window.setTimeout(() => {
	    let idx = 0;
	    pathTimer = window.setInterval(() => {
	      if (idx >= sequence.length) {
		window.clearInterval(pathTimer);
		pathTimer = null;
		return;
	      }
	      const dot = sequence[idx];
	      dot.style.display = "inline";
	      dot.style.fill = "#38bdf8";
	      const x = +dot.getAttribute("cx");
	      const y = +dot.getAttribute("cy");
	      updateImageTriggers(x, y);
    	      if (idx % CENTER_EVERY === 0) centerOn(x, y);	      
	      idx++;
	    }, STEP_MS);
	  }, leadIn);

	  return sequence.length; // IMPORTANT: used for timing
	};

	
    // ---------- import & paint ----------
    const importJSONData = (data) => {
      // clear
      ["#lines-layer", "#markers-layer"].forEach((sel) => {
        const g = document.querySelector(sel);
        if (g) g.innerHTML = "";
      });
      svg.querySelectorAll("#map-content > path").forEach((p) => p.remove());
      imgTriggers.length = 0;

      // zones
      (data.zones || []).forEach((z) => {
        const p = document.createElementNS(svg.namespaceURI, "path");
        p.setAttribute("d", verticesToPath(z.vertices));
        if (z.id) p.setAttribute("id", z.id);
        if (z.label) p.dataset.label = z.label;
        p.setAttribute("fill", z.color || "#d1d5db");
        p.setAttribute("stroke", "none"); // crisp edges
        mapContent.insertBefore(p, mapContent.firstChild);
      });

      // markers (highlight if label in dests)
      const mLayer = document.getElementById("markers-layer");
      (data.markers || []).forEach((m) => {
        const c = document.createElementNS(svg.namespaceURI, "circle");
        c.classList.add("map-marker");
        c.dataset.label = m.label || "";
        c.setAttribute("cx", String(m.cx));
        c.setAttribute("cy", String(m.cy));
        c.setAttribute("r", String(m.radius ?? 12));
        const isHL = dests.length > 0 && m.label && dests.includes(m.label);
        c.setAttribute("fill", isHL ? "#10b981" : "#f59e0b");
        c.setAttribute("stroke", "#000");
        c.setAttribute("stroke-width", "2");
        mLayer.appendChild(c);

        if (m.icon) {
          const i = document.createElementNS(svg.namespaceURI, "image");
          i.setAttribute("href", m.icon);
          i.setAttribute("x", String(m.cx - 60));
          i.setAttribute("y", String(m.cy - 60));
          i.setAttribute("width", "120");
          i.setAttribute("height", "120");
          i.classList.add("marker-icon");
          mLayer.appendChild(i);
        }
      });

      // images
      (data.images || []).forEach((I) =>
        addImgTrigger(I.cx, I.cy, I.url, I.width, I.height)
      );

      // lines + dots
      const linesLayer = document.getElementById("lines-layer");
	  (data.lines || []).forEach((L) => {
	    const ghost = document.createElementNS(svg.namespaceURI, "line");
	    if (L.id) ghost.setAttribute("id", L.id);
	    ghost.setAttribute("x1", String(L.x1));
	    ghost.setAttribute("y1", String(L.y1));
	    ghost.setAttribute("x2", String(L.x2));
	    ghost.setAttribute("y2", String(L.y2));
	    ghost.setAttribute("stroke", "transparent");
	    ghost.setAttribute("stroke-width", "20");
	    ghost._dots = [];
	    linesLayer.appendChild(ghost);

	    // Auto-generate dots if missing
	    let dots = Array.isArray(L.dots) ? L.dots.slice() : [];
	    if (!dots.length) {
	      const spacing = 28; // px between dots (tune)
	      const dx = L.x2 - L.x1, dy = L.y2 - L.y1;
	      const len = Math.hypot(dx, dy);
	      const n = Math.max(1, Math.floor(len / spacing));
	      for (let k = 0; k <= n; k++) {
		const t = k / n;
		dots.push({ cx: L.x1 + dx * t, cy: L.y1 + dy * t });
	      }
	    }

	    dots.forEach(({ cx, cy }) => {
	      const d = document.createElementNS(svg.namespaceURI, "circle");
	      d.setAttribute("cx", String(cx));
	      d.setAttribute("cy", String(cy));
	      d.setAttribute("r", "6");
	      d.setAttribute("fill", "#fff");
	      d.setAttribute("stroke", "#000");
	      d.setAttribute("stroke-width", "2");
	      d.style.display = "none";          // hidden until animated
	      d.classList.add("map-line-dot");
	      ghost._dots.push(d);
	      linesLayer.appendChild(d);
	    });
	  });

      // apply view or fit
      const s = data.settings || {};
      if (typeof s.zoom === "number") {
        viewFromJSON = true;
        zoom = clampZoom(s.zoom);
        panX = Number.isFinite(s.panX) ? s.panX : 0;
        panY = Number.isFinite(s.panY) ? s.panY : 0;
        applyTransform();
      } else {
        viewFromJSON = false;
        fitToStage();
      }

      setMapName(data.mapName || "Untitled map");

      // auto center if only highlights (no path)
      if (!(fromParam && toParam) && dests.length) {
        const target = Array.from(mLayer.querySelectorAll("circle")).find((c) =>
          dests.includes(c.dataset.label || "")
        );
        if (target) {
          centerOn(+target.getAttribute("cx"), +target.getAttribute("cy"));
        }
      }

      // run path highlight if from/to provided
      if (fromParam && toParam) {
        const labels = shortestPath(fromParam, toParam);
        if (labels) highlightPath(labels, leadInParam);
        else console.warn(`No path found between "${fromParam}" and "${toParam}"`);
      }
    };

    // --- helpers for multi-floor orchestration ---
    function sequenceDotCount(labels) {
      buildGraph();
      const allLines = Array.from(document.querySelectorAll("#lines-layer line"));
      let count = 0;
      for (let i = 0; i < labels.length - 1; i++) {
        const F = labels[i],
          T = labels[i + 1];
        const l = allLines.find(
          (ln) =>
            ln._markers &&
            ((ln._markers[0] === F && ln._markers[1] === T) ||
              (ln._markers[0] === T && ln._markers[1] === F))
        );
        if (l && l._dots) count += l._dots.length;
      }
      return count;
    }

function playLabelsAsync(labels, leadIn = 0) {
  	const seqLen = highlightPath(labels, leadIn); // highlightPath returns #dots
 	const dots = Math.max(1, seqLen);
  	const duration = leadIn + dots * STEP_MS + 200; // small safety buffer
  	return new Promise((res) => setTimeout(res, duration));
}


    async function crossfadeToFile(file) {
      svg.style.transition = "opacity .45s ease";
      svg.style.opacity = "0";
      await new Promise((r) => setTimeout(r, 450));
      const data = await fetch(file).then((r) => r.json());
      importJSONData(data);
      svg.style.opacity = "1";
      await new Promise((r) => setTimeout(r, 50));
    }

    async function playRoute() {
      // Case A: multi-floor route
      if (routeSegments.length) {
        for (let i = 0; i < routeSegments.length; i++) {
          const seg = routeSegments[i];
          await crossfadeToFile(seg.file);
          await playLabelsAsync(seg.labels, i === 0 ? leadInParam : 400);
        }
        return;
      }

      // Case B: single-floor
      const data = await fetch(fileParam).then((r) => r.json());
      importJSONData(data);
      if (fromParam && toParam) {
        const labels = shortestPath(fromParam, toParam);
        if (labels) await playLabelsAsync(labels, leadInParam);
      }
    }

    // initial fit and listeners
    fitToStage();

    const onResize = () => {
      if (!viewFromJSON) fitToStage();
    };
    window.addEventListener("resize", onResize);

    const onWheel = (e) => {
      e.preventDefault();
      const dz = e.deltaY > 0 ? -0.1 : 0.1;
      zoom = clampZoom(zoom + dz);
      applyTransform();
    };

    let panning = false;
    const onPointerDown = (e) => {
      if (e.button !== 1) return; // middle mouse to pan
      panning = true;
      svg.setPointerCapture(e.pointerId);
      e.preventDefault();
    };
    const onPointerMove = (e) => {
      if (!panning) return;
      const m = mapContent.getScreenCTM();
      if (!m) return;
      panX += e.movementX / m.a;
      panY += e.movementY / m.d;
      applyTransform();
    };
    const onPointerUp = () => {
      panning = false;
    };

    svg.addEventListener("wheel", onWheel, { passive: false });
    svg.addEventListener("pointerdown", onPointerDown);
    svg.addEventListener("pointermove", onPointerMove);
    svg.addEventListener("pointerup", onPointerUp);
    svg.addEventListener("pointercancel", onPointerUp);

    let cancelled = false;
    (async () => {
      if (!cancelled) await playRoute();
    })();

    return () => {
      cancelled = true;
      window.removeEventListener("resize", onResize);
      svg.removeEventListener("wheel", onWheel);
      svg.removeEventListener("pointerdown", onPointerDown);
      svg.removeEventListener("pointermove", onPointerMove);
      svg.removeEventListener("pointerup", onPointerUp);
      svg.removeEventListener("pointercancel", onPointerUp);
    };
  }, [
    fileParam,
    fromParam,
    toParam,
    leadInParam,
    dests.join("|"),
    JSON.stringify(routeSegments),
  ]);

  return (
    <>
      <style jsx global>{`
        html,
        body {
          height: 100%;
          margin: 0;
          font-family: system-ui, -apple-system, "Segoe UI", Helvetica, Arial,
            sans-serif;
          background: #fff;
        }
        .wrap {
          height: 100%;
          display: grid;
          place-items: center;
        }
        .stage {
          position: relative;
          width: 100%;
          height: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #f9fafb;
        }
        #map-name {
          position: absolute;
          right: 1rem;
          bottom: 1rem;
          font-weight: 600;
          background: rgba(255, 255, 255, 0.9);
          padding: 0.25rem 0.5rem;
          border-radius: 0.5rem;
          box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
        }
        svg path {
          stroke: none;
          filter: drop-shadow(0 3px 8px rgba(0, 0, 0, 0.12));
        }
        .map-line-dot {
          r: 7;
          fill: #fff;
          stroke: #2f2f2f;
          stroke-width: 1.6;
        }
        .marker-icon {
          pointer-events: none;
        }
        .img-trigger {
          transform-box: fill-box;
          transform-origin: center;
          transform: scale(0.12);
          opacity: 0;
          transition: transform 0.8s ease, opacity 0.8s ease;
        }
      `}</style>

      <div className="wrap">
        <div className="stage" ref={stageRef}>
          <svg
            id="map-svg"
            ref={svgRef}
            width="100%"
            height="100%"
            preserveAspectRatio="xMidYMid meet"
          >
            <rect
              id="frame"
              ref={frameRef}
              fill="#f9fafb"
              stroke="#9ca3af"
              strokeWidth={4}
            />
            <clipPath id="viewport-clip" clipPathUnits="userSpaceOnUse">
              <rect ref={clipRectRef} />
            </clipPath>
            <g id="viewport" clipPath="url(#viewport-clip)">
              <g id="map-content" ref={mapContentRef}>
                <g id="markers-layer" />
                <g id="lines-layer" />
              </g>
            </g>
          </svg>
          <div id="map-name">{mapName}</div>
        </div>
      </div>
    </>
  );
}

