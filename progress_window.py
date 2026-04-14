#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DriverDoktor - Külön Progress Ablak (Software Rendering)
Ez a script egy önálló WebView2 ablakot nyit ami a régi szép progress UI-t mutatja.
Úgy fut, hogy a GPU driver változások nem befolyásolják.
"""
import os
import sys
import json
import time
import threading

# Ellenőrizzük hogy van-e pywebview
try:
    import webview
except ImportError:
    print("HIBA: pywebview nincs telepítve! pip install pywebview")
    sys.exit(1)

# Software rendering bekapcsolása - GPU független
os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = (
    '--disable-gpu '
    '--disable-gpu-compositing '
    '--disable-gpu-vsync '
    '--disable-accelerated-2d-canvas '
    '--disable-accelerated-video-decode '
    '--use-gl=swiftshader '
    '--disable-d3d11 '
    '--disable-features=D3D11,Vulkan '
    '--in-process-gpu '
)

PROGRESS_HTML = '''<!DOCTYPE html>
<html lang="hu">
<head>
<meta charset="UTF-8">
<title>DriverDoktor - Progress</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg-primary:#0d1a14;--bg-secondary:#152820;
  --glass:rgba(20,60,40,0.45);--glass-border:rgba(50,255,120,0.35);
  --accent:#3dff6e;--accent2:#00ff88;--accent-glow:rgba(61,255,110,0.6);
  --green:#3dff6e;--red:#ff6b5b;--yellow:#ffe066;
  --text:rgba(255,255,255,1);--text2:rgba(220,255,230,0.9);--text3:rgba(180,220,195,0.7);
  --r:14px;--r-sm:8px;--t:0.25s ease;
  --font:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
  --mono:'Cascadia Code','Fira Code','Consolas',monospace;
}
html,body{height:100%;overflow:hidden;font-family:var(--font);color:var(--text);font-size:13px;line-height:1.5}
body{
  background:linear-gradient(145deg,#0a1510 0%,#0d1f18 25%,#102a1f 50%,#0d2218 75%,#0a1812 100%);
  display:flex;align-items:center;justify-content:center;padding:20px;
}
body::before{content:'';position:fixed;width:600px;height:600px;background:radial-gradient(circle,rgba(50,255,120,0.12) 0%,transparent 60%);top:-200px;right:-150px;pointer-events:none}
body::after{content:'';position:fixed;width:500px;height:500px;background:radial-gradient(circle,rgba(0,255,150,0.08) 0%,transparent 60%);bottom:-150px;left:-100px;pointer-events:none}

.modal-box{
  width:100%;max-width:700px;max-height:95vh;display:flex;flex-direction:column;
  background:rgba(15,35,28,0.98);backdrop-filter:blur(40px);
  border:2px solid rgba(50,255,120,0.35);border-radius:18px;
  box-shadow:0 30px 90px rgba(0,0,0,0.6),0 0 40px rgba(50,255,120,0.15);
  overflow:hidden;
}
.modal-header{padding:20px 24px;border-bottom:1px solid var(--glass-border);display:flex;align-items:center;gap:10px;background:rgba(20,50,38,0.5)}
.modal-header h3{flex:1;font-size:16px;font-weight:700}
.modal-phase{color:var(--accent);font-size:14px;font-weight:700}
.modal-body{padding:18px 24px;flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:14px}
.modal-counter{text-align:center;font-size:18px;font-weight:700;color:var(--green)}
.modal-status{color:var(--text2);font-size:14px;text-align:center}
.modal-time{color:var(--text3);font-size:12px;text-align:center;margin-top:4px}

.progress{height:10px;background:rgba(50,255,120,0.15);border-radius:5px;overflow:hidden;width:100%;border:1px solid rgba(50,255,120,0.2);margin:10px 0}
.progress-fill{height:100%;background:linear-gradient(90deg,#2dd45a,var(--green));border-radius:5px;transition:width 0.4s ease;box-shadow:0 0 12px var(--accent-glow);width:0%}
.progress-indeterminate .progress-fill{width:30%!important;animation:indeterminate 1.5s ease-in-out infinite}
@keyframes indeterminate{0%{margin-left:-30%}100%{margin-left:100%}}

.modal-log{
  flex:1;min-height:200px;max-height:400px;overflow-y:auto;
  background:rgba(5,15,12,0.8);border-radius:var(--r-sm);padding:14px;
  font-family:var(--mono);font-size:12px;color:var(--accent);line-height:1.8;
  white-space:pre-wrap;word-break:break-all;
  scrollbar-width:thin;scrollbar-color:rgba(50,255,120,0.3) transparent;
  border:1px solid rgba(50,255,120,0.2);
}
.modal-log::-webkit-scrollbar{width:6px}
.modal-log::-webkit-scrollbar-thumb{background:rgba(50,255,120,0.3);border-radius:3px}

.footer-info{
  padding:12px 24px;border-top:1px solid var(--glass-border);
  text-align:center;color:var(--text3);font-size:11px;
  background:rgba(20,50,38,0.3);
}
</style>
</head>
<body>
<div class="modal-box">
  <div class="modal-header">
    <h3 id="title">⚡ 1 Kattintásos Driver Fix</h3>
    <span class="modal-phase" id="phase"></span>
  </div>
  <div class="modal-body">
    <div class="modal-counter" id="counter">Inicializálás...</div>
    <div class="progress" id="progress-bar">
      <div class="progress-fill" id="progress-fill"></div>
    </div>
    <div class="modal-status" id="status">Várakozás...</div>
    <div class="modal-time" id="time"></div>
    <pre class="modal-log" id="log"></pre>
  </div>
  <div class="footer-info">
    🖥️ Ez az ablak software renderinggel fut - GPU driver változások nem befolyásolják
  </div>
</div>
<script>
let startTime = Date.now();
let timerInterval = setInterval(() => {
  const s = Math.floor((Date.now() - startTime) / 1000);
  const m = Math.floor(s / 60);
  document.getElementById('time').textContent = '⏱ ' + (m > 0 ? m + ':' + String(s%60).padStart(2,'0') : s + ' mp');
}, 1000);

function update(data) {
  if (data.title) document.getElementById('title').textContent = data.title;
  if (data.phase) document.getElementById('phase').textContent = data.phase;
  if (data.counter) document.getElementById('counter').textContent = data.counter;
  if (data.status) document.getElementById('status').textContent = data.status;
  if (data.log) {
    const el = document.getElementById('log');
    el.textContent += data.log + '\\n';
    el.scrollTop = el.scrollHeight;
  }
  if (data.indeterminate) {
    document.getElementById('progress-bar').classList.add('progress-indeterminate');
    document.getElementById('progress-fill').style.width = '30%';
  } else if (data.total && data.total > 0) {
    document.getElementById('progress-bar').classList.remove('progress-indeterminate');
    const pct = Math.min(100, (data.current || 0) / data.total * 100);
    document.getElementById('progress-fill').style.width = pct + '%';
  }
  if (data.complete) {
    clearInterval(timerInterval);
    const s = Math.floor((Date.now() - startTime) / 1000);
    const m = Math.floor(s / 60);
    document.getElementById('time').textContent = 'Teljes idő: ' + (m > 0 ? m + ' perc ' + (s%60) + ' mp' : s + ' mp');
    document.getElementById('progress-bar').classList.remove('progress-indeterminate');
    document.getElementById('progress-fill').style.width = '100%';
  }
}
window.update = update;
</script>
</body>
</html>'''


class ProgressApi:
    def __init__(self, log_path):
        self._window = None
        self._log_path = log_path
        self._last_pos = 0
        self._running = True

    def set_window(self, window):
        self._window = window
        # Indítsuk el a fájl figyelőt
        threading.Thread(target=self._watch_file, daemon=True).start()

    def _watch_file(self):
        """Figyeli a log fájlt és küldi az update-eket a UI-nak."""
        while self._running:
            try:
                if os.path.exists(self._log_path):
                    with open(self._log_path, 'r', encoding='utf-8') as f:
                        f.seek(self._last_pos)
                        new_content = f.read()
                        self._last_pos = f.tell()
                        
                        if new_content.strip():
                            for line in new_content.strip().split('\n'):
                                if line.startswith('{'):
                                    try:
                                        data = json.loads(line)
                                        if self._window:
                                            self._window.evaluate_js(f'window.update({json.dumps(data)})')
                                    except json.JSONDecodeError:
                                        pass
            except Exception:
                pass
            time.sleep(0.1)

    def stop(self):
        self._running = False


def main():
    if len(sys.argv) < 2:
        print("Usage: progress_window.py <log_file_path>")
        sys.exit(1)
    
    log_path = sys.argv[1]
    api = ProgressApi(log_path)
    
    window = webview.create_window(
        'DriverDoktor - Autofix Progress',
        html=PROGRESS_HTML,
        width=750,
        height=600,
        min_size=(600, 500),
        on_top=True,  # Mindig felül
    )
    
    def on_start():
        api.set_window(window)
    
    def on_closing():
        api.stop()
        return True
    
    window.events.closing += on_closing
    
    webview.start(func=on_start, debug=False)


if __name__ == '__main__':
    main()
