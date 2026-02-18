#!/usr/bin/env python3
"""
Exam Support Bot - Cloud Edition
Deployable to Render.com (or any cloud platform).
Excel data is loaded from OneDrive/SharePoint on startup and
refreshed on demand via the /api/refresh endpoint.
"""

import os
import sys
import io
import time
import threading

from flask import Flask, request, jsonify
import pandas as pd
import requests
from difflib import get_close_matches

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG  — set via Environment Variables on Render (never hard-code secrets)
# ─────────────────────────────────────────────────────────────────────────────
#
#  ONEDRIVE_SHARE_LINK  — direct share link to the Excel file on SharePoint.
#                         How to get it:
#                           1. Open the file in SharePoint / OneDrive.
#                           2. Click Share → "Copy link" (Anyone with link can view).
#                           3. Paste that URL as the env var on Render.
#
#  REFRESH_INTERVAL_MINUTES — how often to auto-refresh data (default 30).
#
#  PORT — Render sets this automatically; you don't need to touch it.
# ─────────────────────────────────────────────────────────────────────────────

ONEDRIVE_SHARE_LINK     = os.environ.get("ONEDRIVE_SHARE_LINK", "")
REFRESH_INTERVAL_MINUTES = int(os.environ.get("REFRESH_INTERVAL_MINUTES", "30"))
EXCEL_FILENAME           = "exam_support_data.xlsx"
LOCAL_EXCEL_PATH         = os.path.join(os.path.dirname(__file__), EXCEL_FILENAME)

# ─────────────────────────────────────────────────────────────────────────────
# OneDrive download helper
# ─────────────────────────────────────────────────────────────────────────────

def build_download_url(share_link: str) -> str:
    """Convert a SharePoint share link to a direct-download URL."""
    if not share_link:
        return ""
    # SharePoint pattern: /:x:/g/personal/...  → append ?download=1
    if "download=1" in share_link:
        return share_link
    sep = "&" if "?" in share_link else "?"
    return share_link + sep + "download=1"


def download_excel(share_link: str, dest_path: str) -> bool:
    """Download Excel from OneDrive. Returns True on success."""
    url = build_download_url(share_link)
    if not url:
        print("[OneDrive] No share link configured.")
        return False
    print(f"[OneDrive] Downloading from OneDrive…")
    try:
        resp = requests.get(url, timeout=60, allow_redirects=True)
        if resp.status_code == 200:
            ct = resp.headers.get("Content-Type", "")
            if "html" in ct.lower() and len(resp.content) < 100_000:
                print("[OneDrive] ⚠  Got an HTML page – link may need auth or be wrong.")
                return False
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            print(f"[OneDrive] ✓ Downloaded {len(resp.content):,} bytes → {dest_path}")
            return True
        print(f"[OneDrive] ✗ HTTP {resp.status_code}")
        return False
    except Exception as exc:
        print(f"[OneDrive] ✗ Error: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Bot
# ─────────────────────────────────────────────────────────────────────────────

class ExamSupportBot:
    def __init__(self):
        self.df   = None
        self._lock = threading.Lock()
        self._last_refresh = None

    # ---------- loading ----------

    def load_from_path(self, path: str):
        df = pd.read_excel(path)
        with self._lock:
            self.df = df
            self._last_refresh = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        print(f"[Bot] Loaded {len(df)} rows, {df['Issue'].nunique()} unique issues.")

    def load_from_bytes(self, data: bytes):
        df = pd.read_excel(io.BytesIO(data))
        with self._lock:
            self.df = df
            self._last_refresh = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        print(f"[Bot] Loaded {len(df)} rows from bytes.")

    def refresh(self) -> dict:
        """Re-download from OneDrive and reload. Returns status dict."""
        ok = download_excel(ONEDRIVE_SHARE_LINK, LOCAL_EXCEL_PATH)
        if ok:
            self.load_from_path(LOCAL_EXCEL_PATH)
            return {"success": True,
                    "total_records": self.total_records,
                    "unique_issues": self.unique_issues,
                    "last_refresh": self._last_refresh}
        return {"success": False, "message": "Download failed – check ONEDRIVE_SHARE_LINK env var."}

    # ---------- search ----------

    def search_issue(self, query: str):
        with self._lock:
            df = self.df
        if df is None or not query.strip():
            return None

        q = query.lower().strip()
        results = []

        for _, row in df.iterrows():
            issue       = str(row.get("Issue", "")).lower()
            description = str(row.get("Description of Issues Reported", "")).lower()
            solution    = str(row.get("Solutions", ""))

            score = 0
            if q in issue:               score += 100
            elif any(w in issue for w in q.split()):        score += 50
            if q in description:         score += 75
            elif any(w in description for w in q.split()):  score += 30

            if score > 0:
                results.append({
                    "score":       score,
                    "issue":       row.get("Issue", ""),
                    "description": row.get("Description of Issues Reported", ""),
                    "solution":    solution,
                })

        results.sort(key=lambda x: x["score"], reverse=True)

        if not results:
            with self._lock:
                issue_list = self.df["Issue"].dropna().unique().tolist()
            for match in get_close_matches(query, issue_list, n=3, cutoff=0.4):
                rows = df[df["Issue"] == match]
                for _, row in rows.iterrows():
                    results.append({
                        "score": 25,
                        "issue": row.get("Issue", ""),
                        "description": row.get("Description of Issues Reported", ""),
                        "solution": str(row.get("Solutions", "")),
                    })

        return results[:5] or None

    def get_all_issues(self):
        with self._lock:
            return sorted(self.df["Issue"].dropna().unique().tolist()) if self.df is not None else []

    @property
    def total_records(self):
        with self._lock:
            return len(self.df) if self.df is not None else 0

    @property
    def unique_issues(self):
        with self._lock:
            return self.df["Issue"].nunique() if self.df is not None else 0

    @property
    def last_refresh(self):
        return self._last_refresh or "–"

    @property
    def ready(self):
        with self._lock:
            return self.df is not None


# ─────────────────────────────────────────────────────────────────────────────
# Startup – load data
# ─────────────────────────────────────────────────────────────────────────────

bot = ExamSupportBot()

def startup_load():
    # 1. Try existing local file first (fast restart)
    if os.path.exists(LOCAL_EXCEL_PATH):
        print("[Startup] Found local cache – loading…")
        try:
            bot.load_from_path(LOCAL_EXCEL_PATH)
            print("[Startup] ✓ Loaded from local cache.")
            return
        except Exception as exc:
            print(f"[Startup] Local load failed: {exc}")

    # 2. Download from OneDrive
    if ONEDRIVE_SHARE_LINK:
        ok = download_excel(ONEDRIVE_SHARE_LINK, LOCAL_EXCEL_PATH)
        if ok:
            bot.load_from_path(LOCAL_EXCEL_PATH)
            return

    print("[Startup] ⚠  No data loaded. Set the ONEDRIVE_SHARE_LINK environment variable.")

startup_load()

# Background auto-refresh
if REFRESH_INTERVAL_MINUTES > 0:
    def _refresh_loop():
        while True:
            time.sleep(REFRESH_INTERVAL_MINUTES * 60)
            print("[AutoRefresh] Refreshing data from OneDrive…")
            bot.refresh()
    threading.Thread(target=_refresh_loop, daemon=True).start()
    print(f"[AutoRefresh] Enabled – every {REFRESH_INTERVAL_MINUTES} min.")


# ─────────────────────────────────────────────────────────────────────────────
# HTML (fully embedded – no templates folder)
# ─────────────────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Exam Support Bot</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;
     background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);
     min-height:100vh;padding:20px}
.container{max-width:960px;margin:0 auto}

/* Header */
.header{background:#fff;border-radius:18px;padding:32px;text-align:center;
        margin-bottom:24px;box-shadow:0 12px 32px rgba(0,0,0,.18)}
.header h1{color:#667eea;font-size:2.4em;margin-bottom:6px}
.header p{color:#666;font-size:1.05em}
.badges{margin:10px 0 4px}
.badge{display:inline-block;padding:4px 14px;border-radius:20px;font-size:.82em;
       color:#fff;margin:3px}
.b-green{background:#27ae60}.b-blue{background:#0078d4}.b-purple{background:#667eea}
.stats{display:flex;gap:14px;justify-content:center;margin-top:18px;flex-wrap:wrap}
.stat-box{background:#f0f4ff;padding:14px 22px;border-radius:10px;text-align:center;min-width:120px}
.stat-num{font-size:2em;font-weight:700;color:#667eea}
.stat-lbl{color:#888;font-size:.82em;margin-top:4px}

/* Search */
.search-box{background:#fff;border-radius:18px;padding:28px;margin-bottom:24px;
            box-shadow:0 12px 32px rgba(0,0,0,.18)}
.search-box h2{color:#34495e;margin-bottom:14px;font-size:1.15em}
.search-row{display:flex;gap:10px;flex-wrap:wrap}
.search-input{flex:1;min-width:200px;padding:14px 18px;font-size:1.05em;
              border:2px solid #ddd;border-radius:10px;outline:none;
              transition:border-color .25s}
.search-input:focus{border-color:#667eea}
.btn{padding:14px 28px;border:none;border-radius:10px;font-size:1em;
     font-weight:700;cursor:pointer;transition:filter .2s;white-space:nowrap}
.btn:hover{filter:brightness(.9)}
.btn-search{background:#667eea;color:#fff}
.btn-refresh{background:#0078d4;color:#fff}
.quick-lbl{margin-top:16px;color:#666;font-size:.88em;font-weight:700}
.quick-btns{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.quick-btn{padding:9px 16px;background:#f0f4ff;border:2px solid #667eea;
           border-radius:8px;color:#667eea;cursor:pointer;
           transition:all .2s;font-size:.9em}
.quick-btn:hover{background:#667eea;color:#fff}

/* Results */
.results-box{background:#fff;border-radius:18px;padding:28px;
             box-shadow:0 12px 32px rgba(0,0,0,.18);min-height:260px}
.welcome{text-align:center;padding:40px 0;color:#888}
.welcome h2{color:#667eea;font-size:1.8em;margin-bottom:14px}
.welcome p{margin:6px 0;line-height:1.6}
.result-item{border:1px solid #e0e0e0;border-radius:12px;margin-bottom:16px;
             overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.result-head{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;
             padding:14px 18px;display:flex;align-items:center;gap:12px}
.result-num{background:rgba(255,255,255,.25);border-radius:50%;
            width:32px;height:32px;display:flex;align-items:center;
            justify-content:center;font-weight:700;flex-shrink:0}
.result-issue{font-weight:700;font-size:1.04em}
.result-body{padding:18px}
.sec-title{font-weight:700;color:#555;font-size:.88em;margin-bottom:6px}
.sec-desc{background:#f8f9fa;padding:12px;border-radius:8px;color:#444;
          margin-bottom:14px;font-size:.94em;line-height:1.55}
.sec-sol{background:#e8f5e9;border-left:4px solid #27ae60;padding:12px 16px;
         border-radius:0 8px 8px 0;color:#1a5c2a;font-size:.94em;
         line-height:1.65;white-space:pre-wrap}
.no-results{text-align:center;padding:50px 0;color:#aaa}
.no-results h2{color:#e74c3c;margin-bottom:16px}
.loading{text-align:center;padding:60px 0}
.spinner{border:4px solid #f3f3f3;border-top:4px solid #667eea;
         border-radius:50%;width:48px;height:48px;
         animation:spin .9s linear infinite;margin:0 auto 16px}
@keyframes spin{to{transform:rotate(360deg)}}
.not-ready{background:#fff3cd;border:1px solid #ffc107;border-radius:10px;
           padding:20px;text-align:center;color:#856404;margin-bottom:20px}
.footer{text-align:center;color:rgba(255,255,255,.65);font-size:.82em;
        margin-top:18px;padding-bottom:8px}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>🤖 Exam Support Bot</h1>
    <p>Issue Resolution System</p>
    <div class="badges">
      <span class="badge b-green">🌐 Live on Cloud</span>
      <span class="badge b-blue">☁️ OneDrive Data</span>
      <span class="badge b-purple">⚡ Always Online</span>
    </div>
    <div class="stats">
      <div class="stat-box">
        <div class="stat-num" id="statRecords">…</div>
        <div class="stat-lbl">Total Records</div>
      </div>
      <div class="stat-box">
        <div class="stat-num" id="statIssues">…</div>
        <div class="stat-lbl">Unique Issues</div>
      </div>
      <div class="stat-box">
        <div class="stat-num" id="statRefresh" style="font-size:1em;padding-top:4px">…</div>
        <div class="stat-lbl">Last Refreshed</div>
      </div>
    </div>
  </div>

  <div id="notReadyBanner" class="not-ready" style="display:none">
    ⚠️ Data not yet loaded. Please set the <strong>ONEDRIVE_SHARE_LINK</strong>
    environment variable on Render and restart the service.
  </div>

  <div class="search-box">
    <h2>🔍 Search for Solutions</h2>
    <div class="search-row">
      <input id="searchInput" class="search-input" type="text"
             placeholder="Describe your issue… (e.g. login problem, camera not working)"
             onkeypress="if(event.key==='Enter')searchIssue()">
      <button class="btn btn-search" onclick="searchIssue()">Search</button>
      <button class="btn btn-refresh" onclick="refreshData()" title="Reload from OneDrive">☁️ Refresh</button>
    </div>
    <div class="quick-lbl">Quick Select Common Issues:</div>
    <div class="quick-btns">
      <button class="quick-btn" onclick="q('Login Issue')">Login Issue</button>
      <button class="quick-btn" onclick="q('SEB Installation Issue')">SEB Installation</button>
      <button class="quick-btn" onclick="q('Webcam Mic Issue')">Webcam / Mic</button>
      <button class="quick-btn" onclick="q('Blank Screen')">Blank Screen</button>
      <button class="quick-btn" onclick="q('QP Not download')">QP Not Download</button>
      <button class="quick-btn" onclick="q('Logout Issue')">Logout Issue</button>
      <button class="quick-btn" onclick="q('Internet connection')">Internet Issue</button>
      <button class="quick-btn" onclick="q('Audio')">Audio Problem</button>
    </div>
  </div>

  <div class="results-box" id="resultsBox">
    <div class="welcome">
      <h2>Welcome! 👋</h2>
      <p>Search for any exam-related technical issue above.</p>
      <br>
      <p>This bot is <strong>hosted on the cloud</strong> — no localhost needed.</p>
      <p>Accessible from any device, anywhere, via this URL.</p>
      <br>
      <p style="color:#0078d4">☁️ Data is pulled live from OneDrive and auto-refreshes every 30 min.</p>
    </div>
  </div>

  <div class="footer">Exam Support Bot &nbsp;|&nbsp; Cloud Edition &nbsp;|&nbsp; Data: OneDrive / SharePoint</div>
</div>

<script>
// Load status on page open
fetch('/api/status').then(r=>r.json()).then(d=>{
  document.getElementById('statRecords').textContent = d.total_records;
  document.getElementById('statIssues').textContent  = d.unique_issues;
  document.getElementById('statRefresh').textContent = d.last_refresh;
  if(!d.ready) document.getElementById('notReadyBanner').style.display='block';
}).catch(()=>{});

function q(issue){ document.getElementById('searchInput').value=issue; searchIssue(); }

function searchIssue(){
  const query = document.getElementById('searchInput').value.trim();
  if(!query){ alert('Please enter an issue to search for.'); return; }
  const box = document.getElementById('resultsBox');
  box.innerHTML='<div class="loading"><div class="spinner"></div><p>Searching…</p></div>';
  fetch('/api/search',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({query})})
  .then(r=>r.json()).then(d=>renderResults(d,query))
  .catch(()=>{ box.innerHTML='<div class="no-results"><h2>❌ Error</h2><p>Could not reach server. Please try again.</p></div>'; });
}

function renderResults(data,query){
  const box=document.getElementById('resultsBox');
  if(data.success && data.results && data.results.length){
    let html=`<h2 style="color:#34495e;margin-bottom:18px">Found ${data.count} solution(s) for:
              <span style="color:#e74c3c">"${esc(query)}"</span></h2>`;
    data.results.forEach((r,i)=>{
      html+=`<div class="result-item">
        <div class="result-head">
          <div class="result-num">${i+1}</div>
          <div class="result-issue">${esc(r.issue)}</div>
        </div>
        <div class="result-body">
          <div class="sec-title">📝 Description</div>
          <div class="sec-desc">${esc(r.description)}</div>
          <div class="sec-title">✅ Solution</div>
          <div class="sec-sol">${esc(r.solution)}</div>
        </div></div>`;
    });
    box.innerHTML=html;
  } else {
    box.innerHTML=`<div class="no-results">
      <h2>No Solutions Found ❌</h2>
      <p style="margin-top:16px">No match for: <strong>${esc(query)}</strong></p>
      <br><p>Try different keywords or use the quick buttons above.</p></div>`;
  }
}

function refreshData(){
  const btn=document.querySelector('.btn-refresh');
  btn.textContent='⏳ Refreshing…'; btn.disabled=true;
  fetch('/api/refresh',{method:'POST'}).then(r=>r.json()).then(d=>{
    btn.textContent='☁️ Refresh'; btn.disabled=false;
    if(d.success){
      document.getElementById('statRecords').textContent=d.total_records;
      document.getElementById('statIssues').textContent=d.unique_issues;
      document.getElementById('statRefresh').textContent=d.last_refresh;
      alert('✅ Data refreshed!\n'+d.total_records+' records loaded.');
    } else { alert('⚠️ Refresh failed:\n'+(d.message||'Unknown error')); }
  }).catch(()=>{ btn.textContent='☁️ Refresh'; btn.disabled=false;
    alert('❌ Refresh request failed.'); });
}

function esc(t){ const d=document.createElement('div'); d.textContent=String(t); return d.innerHTML; }
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Flask routes
# ─────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)

@app.route("/")
def index():
    return HTML

@app.route("/api/search", methods=["POST"])
def search():
    data  = request.get_json() or {}
    query = data.get("query", "")
    if not query:
        return jsonify({"error": "No query provided"}), 400
    results = bot.search_issue(query)
    if results:
        return jsonify({"success": True, "count": len(results), "results": results})
    return jsonify({"success": False, "message": "No solutions found"})

@app.route("/api/issues")
def get_issues():
    return jsonify({"issues": bot.get_all_issues()})

@app.route("/api/refresh", methods=["POST"])
def refresh():
    return jsonify(bot.refresh())

@app.route("/api/status")
def status():
    return jsonify({
        "ready":         bot.ready,
        "total_records": bot.total_records,
        "unique_issues": bot.unique_issues,
        "last_refresh":  bot.last_refresh,
    })

@app.route("/health")
def health():
    return jsonify({"status": "ok", "ready": bot.ready})

# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
