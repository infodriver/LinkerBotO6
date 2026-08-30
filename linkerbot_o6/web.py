"""linkerbot_o6.web — browser control panel for the LinkerHand O6.

Run:  python3 -m linkerbot_o6.web [--port 8080]
Open: http://127.0.0.1:8080

Features: live status, joint sliders, presets, ball grasp card, emergency
stop, and in-browser camera hand tracking (MediaPipe, single-hand gating).

Endpoints:
  GET  /          -> control panel HTML
  GET  /status    -> JSON: positions (pct), faults, temps, serial
  POST /move      -> JSON {"pos": [6x 0-100], "speed": N}
  POST /preset    -> JSON {"name": ..., "speed": N}
  POST /grasp     -> JSON {"ball_cm": N, "strength": N}
  POST /release   -> {}
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .hand import LinkerHand, PRESETS_RAW, pct_to_raw, raw_to_pct, grasp_pose

JOINTS = ["thumb_flex", "thumb_abd", "index", "middle", "ring", "pinky"]

lock = threading.Lock()
hand = None


def hand_status():
    with lock:
        pos = hand.get_positions()
        faults = hand.get_faults()
        temps = hand.get_temps()
    return {
        "serial": getattr(hand, "serial", None),
        "positions_pct": raw_to_pct(pos) if pos else None,
        "positions_raw": list(pos) if pos else None,
        "faults": list(faults) if faults else None,
        "temps": list(temps) if temps else None,
        "joints": JOINTS,
    }


def do_grasp(ball_cm, strength, speed=40):
    pose = grasp_pose(ball_cm)
    with lock:
        hand.move_raw(pct_to_raw([100] * 6), speed=80)
        time.sleep(0.8)
        hand.set_torque([strength] * 6)
        time.sleep(0.05)
        fingers_only = [90, pose[1], pose[2], pose[3], pose[4], pose[5]]
        hand.move_raw(pct_to_raw(fingers_only), speed=speed)
        time.sleep(0.6)
        hand.move_raw(pct_to_raw(pose), speed=speed)
    return pose


def do_release(speed=60):
    with lock:
        hand.move_raw(pct_to_raw([100] * 6), speed=speed)
    return [100] * 6


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>LinkerBot O6 — Control</title>
<style>
  body { font: 14px/1.5 system-ui, sans-serif; max-width: 680px; margin: 2rem auto; padding: 0 1rem; background:#111; color:#eee; }
  h1 { font-size: 1.3rem; }
  .card { background:#1b1b1b; border:1px solid #333; border-radius:10px; padding:1rem 1.2rem; margin-bottom:1rem; }
  .row { display:flex; align-items:center; gap:.6rem; margin:.45rem 0; }
  .row label { width:110px; color:#aaa; }
  .row output { width:64px; text-align:right; font-variant-numeric:tabular-nums; color:#7fd07f; }
  input[type=range] { flex:1; accent-color:#3b8f3b; }
  button { background:#2a6e2a; color:#fff; border:0; border-radius:8px; padding:.55rem 1.1rem; font-size:.95rem; cursor:pointer; }
  button:hover { filter:brightness(1.2); }
  button.blue { background:#2a5a8f; }
  button.warn { background:#8f6a2a; }
  button.danger { background:#7a2a2a; }
  button.on { outline:3px solid #7fd07f; }
  .presets { display:flex; gap:.6rem; flex-wrap:wrap; }
  .status { color:#9fc; font-variant-numeric:tabular-nums; }
  .err { color:#f88; }
  .camwrap { position:relative; width:100%; max-width:480px; aspect-ratio:4/3; background:#000; border-radius:10px; overflow:hidden; margin:.6rem 0; }
  video, canvas { position:absolute; inset:0; width:100%; height:100%; }
  video { transform:scaleX(-1); }
  canvas { z-index:2; }
  .camrow { display:flex; gap:.6rem; flex-wrap:wrap; align-items:center; }
  small { color:#888; }
</style>
</head>
<body>
<h1>🤖 LinkerBot O6 — hand control</h1>
<div class="card">
  <div class="status" id="status">connecting…</div>
</div>
<div class="card">
  <h2>📷 Camera hand control</h2>
  <div class="camrow">
    <button id="camStart" class="blue">Start camera</button>
    <button id="handToggle" class="warn" disabled>Enable hand control</button>
    <button id="stop" class="danger">Emergency stop</button>
  </div>
  <div class="camwrap"><video id="video" playsinline muted></video><canvas id="canvas"></canvas></div>
  <div class="row">
    <label>Follow speed</label>
    <input type="range" id="camSpeed" min="10" max="255" value="80">
    <output id="camSpeedOut">80</output>
  </div>
  <div class="status" id="camStatus">camera off</div>
  <small>Robot follows your hand only when <b>exactly one hand</b> is visible.
  Two hands or no hand = no motion (robot holds last pose). Straight fingers = open,
  curled = fist; thumb spread controls abduction.</small>
</div>
<div class="card">
  <h2>🤏 Grasp &amp; hold</h2>
  <div class="row">
    <label>Ball size</label>
    <input type="range" id="ball" min="3" max="12" value="6">
    <output id="ballOut">6 cm</output>
  </div>
  <div class="row">
    <label>Grip strength</label>
    <input type="range" id="strength" min="50" max="255" value="150">
    <output id="strengthOut">150</output>
  </div>
  <div class="row">
    <button id="graspBtn">Grasp 🏀</button>
    <button id="releaseBtn">Release</button>
  </div>
  <div class="status" id="graspStatus"></div>
  <small>Opens the hand wide, closes fingers around the object, then wraps the
  thumb over it and holds with the chosen grip strength.</small>
</div>
<div class="card">
  <h2>Joint angles (0–100%, higher = extends)</h2>
  <div id="sliders"></div>
  <div class="row">
    <label>Speed (0–255)</label>
    <input type="range" id="speed" min="1" max="255" value="50">
    <output id="speedOut">50</output>
  </div>
  <div class="row">
    <button id="apply">Apply position</button>
    <button id="stop2" class="danger">Emergency stop</button>
  </div>
</div>
<div class="card">
  <h2>Presets</h2>
  <div class="presets">
    <button data-preset="open">Open ✋</button>
    <button data-preset="fist">Fist ✊</button>
    <button data-preset="thumbs_up">Thumbs up 👍</button>
    <button data-preset="v_sign">V-sign ✌️</button>
    <button data-preset="point">Point ☝️</button>
    <button data-preset="middle">Middle 🖕</button>
    <button data-preset="rock_on">Rock on 🤘</button>
  </div>
</div>
<script type="module">
import { FilesetResolver, HandLandmarker } from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs";
const JOINTS = ["thumb_flex","thumb_abd","index","middle","ring","pinky"];
const slidersEl = document.getElementById('sliders');
let current = [100,100,100,100,100,100];

function buildSliders(vals) {
  slidersEl.innerHTML = '';
  JOINTS.forEach((name, i) => {
    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML = `<label>${name}</label>
      <input type="range" min="0" max="100" value="${vals[i]}">
      <output>${vals[i]}%</output>`;
    const inp = row.querySelector('input'), out = row.querySelector('output');
    inp.addEventListener('input', () => { out.textContent = inp.value + '%'; });
    inp.addEventListener('change', () => { current[i] = +inp.value; });
    slidersEl.appendChild(row);
  });
}
buildSliders(current);

document.getElementById('speed').addEventListener('input', e => {
  document.getElementById('speedOut').textContent = e.target.value;
});
document.getElementById('camSpeed').addEventListener('input', e => {
  document.getElementById('camSpeedOut').textContent = e.target.value;
});
document.getElementById('ball').addEventListener('input', e => {
  document.getElementById('ballOut').textContent = e.target.value + ' cm';
});
document.getElementById('strength').addEventListener('input', e => {
  document.getElementById('strengthOut').textContent = e.target.value;
});

async function api(path, body) {
  const r = await fetch(path, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
  if (!r.ok) throw new Error((await r.json()).error || r.status);
  return r.json();
}

const doStop = async () => {
  try { await api('/move', { pos: current, speed: 255 }); setStatus('holding current pose'); }
  catch (e) { setStatus('error: ' + e.message, true); }
};
document.getElementById('stop').onclick = doStop;
document.getElementById('stop2').onclick = doStop;

document.getElementById('apply').onclick = async () => {
  const pos = [...slidersEl.querySelectorAll('input[type=range]')].map(i => +i.value);
  current = pos;
  const speed = +document.getElementById('speed').value;
  try { await api('/move', { pos, speed }); setStatus('move sent'); }
  catch (e) { setStatus('error: ' + e.message, true); }
};

document.querySelectorAll('[data-preset]').forEach(b => {
  b.onclick = async () => {
    try {
      const r = await api('/preset', { name: b.dataset.preset, speed: +document.getElementById('speed').value });
      buildSliders(r.pos_pct); current = r.pos_pct;
      setStatus(`preset '${b.dataset.preset}' applied`);
    } catch (e) { setStatus('error: ' + e.message, true); }
  };
});

const doGrasp = async () => {
  const btn = document.getElementById('graspBtn');
  btn.disabled = true;
  const gs = document.getElementById('graspStatus');
  gs.textContent = 'grasping…';
  try {
    const r = await api('/grasp', {
      ball_cm: +document.getElementById('ball').value,
      strength: +document.getElementById('strength').value,
    });
    gs.textContent = 'holding — pose ' + r.pos_pct.join(' ') + '%';
  } catch (e) { gs.textContent = 'error: ' + e.message; gs.className = 'err'; }
  btn.disabled = false;
};
document.getElementById('graspBtn').onclick = doGrasp;
document.getElementById('releaseBtn').onclick = async () => {
  try {
    await api('/release', {});
    document.getElementById('graspStatus').textContent = 'released';
  } catch (e) { document.getElementById('graspStatus').textContent = 'error: ' + e.message; }
};

function setStatus(text, isErr) {
  const el = document.getElementById('status');
  el.textContent = text;
  el.className = 'status' + (isErr ? ' err' : '');
}
function setCamStatus(text, isErr) {
  const el = document.getElementById('camStatus');
  el.textContent = text;
  el.className = 'status' + (isErr ? ' err' : '');
}

async function refresh() {
  try {
    const r = await fetch('/status');
    const s = await r.json();
    if (s.positions_pct) {
      setStatus(`serial ${s.serial} · pos ${s.positions_pct.join(' ')} · faults ${s.faults.join(' ')} · temps ${s.temps.join(' ')}°C`);
    } else {
      setStatus('hand not responding', true);
    }
  } catch (e) { setStatus('status error: ' + e.message, true); }
}
setInterval(refresh, 2000);
refresh();

/* ---------------- camera hand tracking (MediaPipe in-browser) ---------------- */
const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const camStart = document.getElementById('camStart');
const handToggle = document.getElementById('handToggle');

let landmarker = null;
let camOn = false;
let handControl = false;
let lastHandSeen = 0;
let raf = null;
let lastSent = null;
let lastSentT = 0;
const ema = [100,100,100,100,100,100];

const L = {
  WRIST: 0,
  THUMB_CMC: 1, THUMB_MCP: 2, THUMB_IP: 3, THUMB_TIP: 4,
  INDEX_MCP: 5, INDEX_PIP: 6, INDEX_DIP: 7, INDEX_TIP: 8,
  MIDDLE_MCP: 9, MIDDLE_PIP: 10, MIDDLE_DIP: 11, MIDDLE_TIP: 12,
  RING_MCP: 13, RING_PIP: 14, RING_DIP: 15, RING_TIP: 16,
  PINKY_MCP: 17, PINKY_PIP: 18, PINKY_DIP: 19, PINKY_TIP: 20,
};

function dist(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
}
function angleDeg(a, b, c) { // angle at b
  const abx = a.x - b.x, aby = a.y - b.y, abz = a.z - b.z;
  const cbx = c.x - b.x, cby = c.y - b.y, cbz = c.z - b.z;
  const dot = abx*cbx + aby*cby + abz*cbz;
  const m = Math.hypot(abx,aby,abz) * Math.hypot(cbx,cby,cbz);
  return Math.acos(Math.max(-1, Math.min(1, dot/m))) * 180 / Math.PI;
}
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function fingerCurl(lm, mcp, pip, dip) {
  return clamp((180 - angleDeg(lm[mcp], lm[pip], lm[dip])) / 90, 0, 1);
}

function landmarksToPose(lm) {
  const curl = (mcp, pip, dip) => fingerCurl(lm, mcp, pip, dip);
  const index   = 100 - curl(L.INDEX_MCP,  L.INDEX_PIP,  L.INDEX_DIP)   * 100;
  const middle  = 100 - curl(L.MIDDLE_MCP, L.MIDDLE_PIP, L.MIDDLE_DIP)  * 100;
  const ring    = 100 - curl(L.RING_MCP,   L.RING_PIP,   L.RING_DIP)    * 100;
  const pinky   = 100 - curl(L.PINKY_MCP,  L.PINKY_PIP,  L.PINKY_DIP)   * 100;
  const thumbC  = 100 - clamp((180 - angleDeg(lm[L.THUMB_CMC], lm[L.THUMB_IP], lm[L.THUMB_TIP])) / 110, 0, 1) * 100;
  const spread = dist(lm[L.THUMB_TIP], lm[L.INDEX_MCP]) / Math.max(dist(lm[L.WRIST], lm[L.MIDDLE_MCP]), 1e-6);
  const thumbA = clamp((spread - 0.12) * 250, 0, 100);
  return [thumbC, thumbA, index, middle, ring, pinky];
}

function drawSkeleton(lm) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const W = canvas.width, H = canvas.height;
  const connections = [
    [0,1],[1,2],[2,3],[3,4],
    [0,5],[5,6],[6,7],[7,8],
    [5,9],[9,10],[10,11],[11,12],
    [9,13],[13,14],[14,15],[15,16],
    [13,17],[17,18],[18,19],[19,20],
    [0,17],
  ];
  ctx.strokeStyle = '#7fd07f';
  ctx.lineWidth = 3;
  for (const [a, b] of connections) {
    ctx.beginPath();
    ctx.moveTo(lm[a].x * W, lm[a].y * H);
    ctx.lineTo(lm[b].x * W, lm[b].y * H);
    ctx.stroke();
  }
  ctx.fillStyle = '#7fd07f';
  for (const p of lm) {
    ctx.beginPath();
    ctx.arc(p.x * W, p.y * H, 4, 0, Math.PI * 2);
    ctx.fill();
  }
}

function loop(ts) {
  raf = requestAnimationFrame(loop);
  if (!camOn || !landmarker) return;
  let hands = [];
  try {
    const res = landmarker.detectForVideo(video, ts);
    if (res.landmarks && res.landmarks.length > 0) hands = res.landmarks;
  } catch (e) { /* frame skipped */ }
  const now = Date.now();
  if (hands.length === 0) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (handControl && now - lastHandSeen > 400) setCamStatus('no hand — holding last pose');
    return;
  }
  if (hands.length > 1) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (handControl) setCamStatus(`${hands.length} hands visible — show only one (holding pose)`);
    return;
  }
  lastHandSeen = now;
  const lm = hands[0];
  drawSkeleton(lm);
  if (!handControl) return;

  const pose = landmarksToPose(lm);
  for (let i = 0; i < 6; i++) ema[i] = ema[i] * 0.45 + pose[i] * 0.55;
  const cmd = ema.map(v => Math.round(v));
  const changed = !lastSent || cmd.some((v, i) => Math.abs(v - lastSent[i]) > 2);
  const due = now - lastSentT > 50;
  if (changed && due) {
    lastSent = cmd.slice();
    lastSentT = now;
    const speed = +document.getElementById('camSpeed').value;
    api('/move', { pos: cmd, speed })
      .then(() => { setCamStatus(`1 hand · ${cmd.join(' ')}`); })
      .catch(e => setCamStatus('error: ' + e.message, true));
  } else {
    setCamStatus(`1 hand · ${cmd.join(' ')}`);
  }
}

camStart.onclick = async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
    video.srcObject = stream;
    await video.play();
    camOn = true;
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    camStart.disabled = true;
    handToggle.disabled = false;
    setCamStatus('loading hand model…');
    let lm = null;
    for (const delegate of ['GPU', 'CPU']) {
      try {
        lm = await HandLandmarker.createFromOptions(
          await FilesetResolver.forVisionTasks(
            'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm'
          ), {
            baseOptions: {
              modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
              delegate,
            },
            runningMode: 'VIDEO',
            numHands: 2,
          }
        );
        break;
      } catch (e) {
        setCamStatus(`delegate ${delegate} failed (${e.message}) — trying next…`, true);
      }
    }
    if (!lm) throw new Error('hand landmarker failed to load on GPU and CPU');
    landmarker = lm;
    setCamStatus('model ready — show your hand, then enable hand control');
    raf = requestAnimationFrame(loop);
  } catch (e) {
    setCamStatus('camera/model error: ' + e.message, true);
  }
};

handToggle.onclick = () => {
  handControl = !handControl;
  handToggle.classList.toggle('on', handControl);
  handToggle.textContent = handControl ? 'Hand control ON' : 'Enable hand control';
  if (handControl) setCamStatus('hand control enabled — moving the robot');
  else setCamStatus('hand control disabled');
};
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/status":
            self._json(hand_status())
        elif self.path == "/" or self.path == "/index.html":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json({"error": "bad json"}, 400)
        try:
            if self.path == "/move":
                pos = data.get("pos")
                if not isinstance(pos, list) or len(pos) != 6 or any(not (0 <= v <= 100) for v in pos):
                    return self._json({"error": "pos must be 6 values 0-100"}, 400)
                speed = int(data.get("speed", 50))
                with lock:
                    hand.move_raw(pct_to_raw([float(v) for v in pos]), speed=speed)
                return self._json({"ok": True})
            if self.path == "/preset":
                name = data.get("name")
                if name not in PRESETS_RAW:
                    return self._json({"error": "unknown preset"}, 400)
                speed = int(data.get("speed", 50))
                raw = PRESETS_RAW[name]
                with lock:
                    hand.move_raw(list(raw), speed=speed)
                return self._json({"ok": True, "pos_raw": raw, "pos_pct": raw_to_pct(raw)})
            if self.path == "/grasp":
                ball = float(data.get("ball_cm", 6))
                strength = int(data.get("strength", 150))
                pose = do_grasp(ball, strength)
                return self._json({"ok": True, "pos_pct": pose})
            if self.path == "/release":
                pose = do_release()
                return self._json({"ok": True, "pos_pct": pose})
            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": str(e)}, 500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--side", choices=["left", "right"], default="left")
    args = ap.parse_args()

    global hand
    print("Opening CAN bus (PCAN-USB @ 1 Mbit/s)...")
    hand = LinkerHand(side=args.side)
    hand.serial = None
    try:
        hand.serial = hand.get_serial()
    except Exception:
        pass
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"\nLinkerBot O6 control panel:  http://127.0.0.1:{args.port}\n"
          f"Press Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        hand.close()


if __name__ == "__main__":
    main()
