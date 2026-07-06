from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PORT = int(os.environ.get("PORT", "8000"))

INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Tiny Reaction Arena</title>
    <style>
      :root {
        --bg: #0f172a;
        --panel: #f8fafc;
        --ink: #172033;
        --accent: #0f766e;
        --danger: #be123c;
        --muted: #64748b;
      }
      * { box-sizing: border-box; }
      body {
        min-height: 100vh;
        margin: 0;
        display: grid;
        place-items: center;
        background:
          radial-gradient(circle at 20% 20%, rgba(20, 184, 166, 0.35), transparent 26rem),
          radial-gradient(circle at 80% 10%, rgba(59, 130, 246, 0.28), transparent 24rem),
          var(--bg);
        color: var(--ink);
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      main {
        width: min(92vw, 780px);
        background: var(--panel);
        border: 1px solid rgba(255, 255, 255, 0.5);
        border-radius: 8px;
        box-shadow: 0 24px 70px rgba(15, 23, 42, 0.32);
        overflow: hidden;
      }
      header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 20px;
        border-bottom: 1px solid #d9e2ec;
      }
      h1, p { margin: 0; }
      h1 { font-size: clamp(22px, 4vw, 34px); letter-spacing: 0; }
      .muted { color: var(--muted); }
      .stats {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
      }
      .stat {
        min-width: 96px;
        border: 1px solid #d9e2ec;
        border-radius: 6px;
        padding: 8px 10px;
        background: #ffffff;
      }
      .stat strong {
        display: block;
        font-size: 24px;
      }
      .arena {
        position: relative;
        height: min(52vh, 420px);
        min-height: 320px;
        background:
          linear-gradient(90deg, rgba(15, 118, 110, 0.08) 1px, transparent 1px),
          linear-gradient(rgba(15, 118, 110, 0.08) 1px, transparent 1px),
          #edf6f5;
        background-size: 34px 34px;
      }
      .target {
        position: absolute;
        width: 62px;
        height: 62px;
        border: 0;
        border-radius: 50%;
        background: var(--danger);
        box-shadow: 0 8px 18px rgba(190, 18, 60, 0.32);
        color: #ffffff;
        font-weight: 800;
        cursor: pointer;
      }
      .target:focus {
        outline: 4px solid rgba(15, 118, 110, 0.35);
      }
      .controls {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 16px 20px;
        border-top: 1px solid #d9e2ec;
      }
      button.start {
        min-height: 40px;
        border: 0;
        border-radius: 6px;
        background: var(--accent);
        color: #ffffff;
        font-weight: 800;
        padding: 0 16px;
        cursor: pointer;
      }
      @media (max-width: 640px) {
        header, .controls {
          align-items: stretch;
          flex-direction: column;
        }
      }
    </style>
  </head>
  <body>
    <main>
      <header>
        <div>
          <h1>Tiny Reaction Arena</h1>
          <p class="muted">A tiny game server provisioned by TinyProvisioner.</p>
        </div>
        <div class="stats">
          <div class="stat"><span class="muted">Score</span><strong id="score">0</strong></div>
          <div class="stat"><span class="muted">Time</span><strong id="time">20</strong></div>
          <div class="stat"><span class="muted">Best</span><strong id="best">0</strong></div>
        </div>
      </header>
      <section id="arena" class="arena" aria-label="Game arena"></section>
      <div class="controls">
        <p id="status" class="muted">Press start, then click the red target as fast as you can.</p>
        <button id="start" class="start">Start game</button>
      </div>
    </main>
    <script>
      const arena = document.querySelector("#arena");
      const scoreEl = document.querySelector("#score");
      const timeEl = document.querySelector("#time");
      const bestEl = document.querySelector("#best");
      const statusEl = document.querySelector("#status");
      const startButton = document.querySelector("#start");
      let score = 0;
      let time = 20;
      let timer = null;
      let target = null;
      bestEl.textContent = localStorage.getItem("tinyReactionBest") || "0";

      function placeTarget() {
        if (!target) {
          target = document.createElement("button");
          target.className = "target";
          target.textContent = "+1";
          target.addEventListener("click", () => {
            score += 1;
            scoreEl.textContent = String(score);
            placeTarget();
          });
          arena.append(target);
        }
        const bounds = arena.getBoundingClientRect();
        const x = Math.max(0, Math.random() * (bounds.width - 70));
        const y = Math.max(0, Math.random() * (bounds.height - 70));
        target.style.left = `${x}px`;
        target.style.top = `${y}px`;
      }

      function finishGame() {
        clearInterval(timer);
        timer = null;
        if (target) {
          target.remove();
          target = null;
        }
        const best = Number(localStorage.getItem("tinyReactionBest") || "0");
        if (score > best) {
          localStorage.setItem("tinyReactionBest", String(score));
          bestEl.textContent = String(score);
          statusEl.textContent = `New best score: ${score}.`;
        } else {
          statusEl.textContent = `Final score: ${score}. Try again.`;
        }
        startButton.disabled = false;
      }

      function startGame() {
        score = 0;
        time = 20;
        scoreEl.textContent = "0";
        timeEl.textContent = "20";
        statusEl.textContent = "Game running.";
        startButton.disabled = true;
        placeTarget();
        timer = setInterval(() => {
          time -= 1;
          timeEl.textContent = String(time);
          if (time <= 0) {
            finishGame();
          }
        }, 1000);
      }

      startButton.addEventListener("click", startGame);
    </script>
  </body>
</html>
"""


class GameHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(INDEX_HTML.encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        print(f"tiny-browser-game: {format % args}")


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), GameHandler)
    print(f"tiny-browser-game listening on {PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
