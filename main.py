import os
import html
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from services.extractor import extract_video_info, get_native_youtube_captions, get_video_metadata
from services.transcriber import download_and_transcribe
from services.formatter import format_script
from services.notifier import send_ntfy_notification

load_dotenv()

app = FastAPI(
    title="Short Script Extractor API",
    description="Extracts and cleans scripts from YouTube Shorts, TikTok, and Reels.",
    version="1.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = Path(__file__).parent / "scripts"
OUTPUT_DIR.mkdir(exist_ok=True)

class ExtractRequest(BaseModel):
    url: str
    format_style: Optional[str] = "verbatim"
    async_mode: Optional[bool] = True

class ExtractResponse(BaseModel):
    status: str
    message: str
    platform: Optional[str] = None
    video_id: Optional[str] = None
    script: Optional[str] = None

def save_script_to_disk(url: str, platform: str, video_id: Optional[str], source: str, raw_text: str, script: str, metadata: Optional[dict] = None):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_id = video_id or "unknown"
    filename = OUTPUT_DIR / f"{timestamp}_{clean_id}.md"

    meta = metadata or {}
    title = meta.get("title") or clean_id
    channel = meta.get("channel") or "Unknown Channel"
    views = meta.get("views_formatted") or "N/A"
    likes = meta.get("likes_formatted") or "N/A"

    content = f"""# {title}
- **Channel**: {channel}
- **Views**: {views}
- **Likes**: {likes}
- **URL**: {url}
- **Platform**: {platform}
- **Source**: {source}
- **Recorded At**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

{script}
"""
    filename.write_text(content, encoding="utf-8")
    print(f"\n[Background Worker] 💾 Saved script to: {filename.name}")

def background_extractor_worker(url: str, format_style: str):
    print(f"\n[Background Worker] 🚀 Processing: {url}")
    platform, video_id = extract_video_info(url)
    raw_text: Optional[str] = None
    source = "none"

    # Step 1: Concurrently fetch metadata and native captions (Cuts latency in half!)
    with ThreadPoolExecutor(max_workers=2) as executor:
        meta_future = executor.submit(get_video_metadata, url)
        caps_future = executor.submit(get_native_youtube_captions, video_id) if (platform == "youtube" and video_id) else None
        
        metadata = meta_future.result()
        if not video_id and metadata.get("video_id"):
            video_id = metadata["video_id"]
        if caps_future:
            raw_text = caps_future.result()
            if raw_text:
                source = "native_captions"
                print(f"[Background Worker] Found native captions ({len(raw_text)} chars).")

    print(f"[Background Worker] Video: '{metadata['title']}' by {metadata['channel']} (👁️ {metadata['views_formatted']} | ❤️ {metadata['likes_formatted']})")

    # Step 2: Fallback Whisper
    if not raw_text:
        print(f"[Background Worker] Native captions missing. Falling back to audio download & Whisper...")
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            try:
                raw_text = download_and_transcribe(url, groq_api_key=groq_key)
                source = "whisper_fallback"
                print(f"[Background Worker] Whisper transcribed ({len(raw_text)} chars).")
            except Exception as e:
                print(f"[Background Worker] ❌ Whisper failed: {e}")
                return
        else:
            print("[Background Worker] ❌ GROQ_API_KEY missing for Whisper fallback.")
            return

    if not raw_text:
        print("[Background Worker] ❌ No captions or transcript available.")
        return

    # Step 3: LLM Formatting (Verbatim clean)
    gemini_key = os.getenv("GEMINI_API_KEY")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    print(f"[Background Worker] Formatting script using {gemini_model}...")
    formatted_script = format_script(
        raw_transcript=raw_text,
        style=format_style or "verbatim",
        api_key=gemini_key,
        model_name=gemini_model
    )

    # Step 4: Save to scripts/
    save_script_to_disk(url, platform, video_id, source, raw_text, formatted_script, metadata=metadata)

    # Step 5: Send Push Notification via ntfy.sh (if configured)
    send_ntfy_notification(
        title=metadata.get("title") or "Video Script",
        channel=metadata.get("channel") or "Unknown Channel",
        script_text=formatted_script,
        video_url=url,
        metadata=metadata
    )

@app.get("/")
def root():
    return RedirectResponse(url="/scripts")

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "groq_configured": bool(os.getenv("GROQ_API_KEY")),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "ntfy_configured": bool(os.getenv("NTFY_TOPIC"))
    }

@app.post("/api/extract-script", response_model=ExtractResponse)
def extract_script_endpoint(req: ExtractRequest, background_tasks: BackgroundTasks):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty.")

    platform, video_id = extract_video_info(url)

    if req.async_mode:
        background_tasks.add_task(background_extractor_worker, url, req.format_style or "verbatim")
        return ExtractResponse(
            status="accepted",
            message="✅ Video received! Recording in background.",
            platform=platform,
            video_id=video_id
        )

    # Synchronous mode
    with ThreadPoolExecutor(max_workers=2) as executor:
        meta_future = executor.submit(get_video_metadata, url)
        caps_future = executor.submit(get_native_youtube_captions, video_id) if (platform == "youtube" and video_id) else None
        
        metadata = meta_future.result()
        raw_text = caps_future.result() if caps_future else None
        source = "native_captions" if raw_text else "none"

    if not raw_text:
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            raise HTTPException(status_code=500, detail="GROQ_API_KEY missing.")
        raw_text = download_and_transcribe(url, groq_api_key=groq_key)
        source = "whisper_fallback"

    gemini_key = os.getenv("GEMINI_API_KEY")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    save_script_to_disk(url, platform, video_id, source, raw_text, formatted, metadata=metadata)
    send_ntfy_notification(
        title=metadata.get("title") or "Video Script",
        channel=metadata.get("channel") or "Unknown Channel",
        script_text=formatted,
        video_url=url,
        metadata=metadata
    )

    return ExtractResponse(
        status="completed",
        message="Script extracted successfully!",
        platform=platform,
        video_id=video_id,
        script=formatted
    )

@app.delete("/api/scripts/{filename}")
def delete_script(filename: str):
    safe_name = Path(filename).name
    target = OUTPUT_DIR / safe_name
    if target.exists() and target.is_file():
        target.unlink()
        return {"success": True, "deleted": safe_name}
    raise HTTPException(status_code=404, detail="Script not found.")

@app.get("/scripts", response_class=HTMLResponse)
def scripts_web_gallery():
    """Stitch-grade modern, responsive mobile dashboard to view and manage recorded scripts."""
    files = sorted(OUTPUT_DIR.glob("*.md"), reverse=True)
    cards_html = ""
    total_scripts = len(files)
    channels_set = set()

    for f in files:
        raw_md = f.read_text(encoding="utf-8")
        
        title = f.stem
        channel = "Unknown Channel"
        views = "N/A"
        likes = "N/A"
        video_url = "#"
        recorded_at = ""
        
        lines = raw_md.splitlines()
        for line in lines[:10]:
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("- **Channel**:"):
                channel = line.split(":", 1)[1].strip()
                if channel != "Unknown Channel":
                    channels_set.add(channel)
            elif line.startswith("- **Views**:"):
                views = line.split(":", 1)[1].strip()
            elif line.startswith("- **Likes**:"):
                likes = line.split(":", 1)[1].strip()
            elif line.startswith("- **URL**:"):
                video_url = line.split(":", 1)[1].strip()
            elif line.startswith("- **Recorded At**:"):
                recorded_at = line.split(":", 1)[1].strip()

        if "---" in raw_md:
            script_part = raw_md.split("---", 1)[1].strip()
            if "## 🎬 Formatted Script" in script_part:
                script_part = script_part.split("## 🎬 Formatted Script")[1]
            if "## 📝 Raw Transcript" in script_part:
                script_part = script_part.split("## 📝 Raw Transcript")[0].strip()
        else:
            script_part = raw_md.strip()

        escaped_title = html.escape(title)
        escaped_channel = html.escape(channel)
        escaped_views = html.escape(views)
        escaped_likes = html.escape(likes)
        escaped_script = html.escape(script_part)
        escaped_for_copy = escaped_script.replace("`", "\\`").replace("$", "\\$")
        escaped_filename = html.escape(f.name)

        cards_html += f"""
        <article class="script-card group bg-slate-900/70 backdrop-blur-md border border-slate-800/80 hover:border-slate-700/80 rounded-2xl p-5 transition-all duration-200 shadow-lg shadow-black/20" data-search="{escaped_title.lower()} {escaped_channel.lower()} {escaped_script.lower()}">
            <header class="flex items-start justify-between gap-4 pb-4 border-b border-slate-800/60">
                <div class="space-y-1.5 flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                        <span class="inline-flex items-center gap-1 text-[11px] font-semibold tracking-wider uppercase px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20">
                            Shorts
                        </span>
                        <span class="text-xs text-slate-500 font-medium">{recorded_at}</span>
                    </div>
                    <a href="{video_url}" target="_blank" rel="noopener" class="block font-bold text-base text-slate-100 hover:text-emerald-400 transition-colors line-clamp-2 leading-snug">
                        {escaped_title} ↗
                    </a>
                    <div class="flex flex-wrap items-center gap-2 pt-1 text-xs">
                        <span class="inline-flex items-center gap-1 font-medium text-emerald-400 bg-emerald-950/40 border border-emerald-800/40 px-2.5 py-1 rounded-lg">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>
                            {escaped_channel}
                        </span>
                        <span class="inline-flex items-center gap-1 text-slate-400 bg-slate-800/60 border border-slate-700/50 px-2.5 py-1 rounded-lg">
                            <svg class="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
                            {escaped_views}
                        </span>
                        <span class="inline-flex items-center gap-1 text-slate-400 bg-slate-800/60 border border-slate-700/50 px-2.5 py-1 rounded-lg">
                            <svg class="w-3.5 h-3.5 text-rose-400" fill="currentColor" viewBox="0 0 24 24"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
                            {escaped_likes}
                        </span>
                    </div>
                </div>
                <div class="flex items-center gap-1.5 shrink-0">
                    <button onclick="copyScript(this, `{escaped_for_copy}`)" class="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-xl bg-emerald-500 hover:bg-emerald-400 active:scale-95 text-slate-950 transition-all shadow-md shadow-emerald-500/10">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"></path></svg>
                        <span>Copy</span>
                    </button>
                    <button onclick="deleteScript('{escaped_filename}')" title="Delete script" class="p-2 text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 rounded-xl transition-colors">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                    </button>
                </div>
            </header>
            <div class="pt-4">
                <p class="text-[14.5px] leading-relaxed text-slate-200 whitespace-pre-wrap font-normal select-text">{escaped_script}</p>
            </div>
        </article>
        """

    empty_state = f"""
    <div class="text-center py-20 px-4 rounded-2xl border border-dashed border-slate-800 bg-slate-900/30">
        <div class="inline-flex items-center justify-center w-12 h-12 rounded-full bg-emerald-500/10 text-emerald-400 mb-4">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path></svg>
        </div>
        <h3 class="text-base font-semibold text-slate-200 mb-1">No scripts recorded yet</h3>
        <p class="text-sm text-slate-500 max-w-sm mx-auto mb-6">Share a YouTube Short from your phone or paste a link above to record your first script.</p>
    </div>
    """

    content_html = cards_html if cards_html else empty_state

    html_page = f"""
    <!DOCTYPE html>
    <html lang="en" class="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Shorts Script Studio</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif; }}
        </style>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen pb-20 selection:bg-emerald-500 selection:text-black antialiased">
        <!-- Sticky Header -->
        <header class="sticky top-0 z-30 bg-slate-950/80 backdrop-blur-xl border-b border-slate-800/80">
            <div class="max-w-2xl mx-auto px-4 h-16 flex items-center justify-between gap-4">
                <div class="flex items-center gap-3">
                    <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-400 flex items-center justify-center text-slate-950 font-black shadow-lg shadow-emerald-500/20">
                        ⚡
                    </div>
                    <div>
                        <h1 class="text-sm font-bold text-slate-100 tracking-tight flex items-center gap-2">
                            Script Studio
                            <span class="inline-block w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                        </h1>
                        <p class="text-[11px] text-slate-400 font-medium">Shorts Transcription Hub</p>
                    </div>
                </div>
                <div class="flex items-center gap-2">
                    <a href="/scripts" class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:text-white bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-xl transition-all">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                        <span>Refresh</span>
                    </a>
                </div>
            </div>
        </header>

        <main class="max-w-2xl mx-auto px-4 pt-6 space-y-6">
            <!-- Quick Paste Input Bar -->
            <div class="bg-gradient-to-b from-slate-900 to-slate-900/60 border border-slate-800 rounded-2xl p-4 shadow-xl shadow-black/30 space-y-3">
                <div class="flex items-center justify-between">
                    <label for="url-input" class="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                        <span class="text-emerald-400">●</span> Quick Transcribe
                    </label>
                    <button onclick="pasteClipboard()" class="text-xs font-medium text-emerald-400 hover:text-emerald-300 flex items-center gap-1">
                        📋 Paste Clipboard
                    </button>
                </div>
                <div class="flex gap-2">
                    <input id="url-input" type="url" placeholder="https://youtube.com/shorts/..." class="flex-1 bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-all">
                    <button id="extract-btn" onclick="triggerExtraction()" class="px-4 py-2.5 text-xs font-bold bg-emerald-500 hover:bg-emerald-400 active:scale-95 text-slate-950 rounded-xl transition-all shadow-md shadow-emerald-500/20 whitespace-nowrap">
                        Record Script
                    </button>
                </div>
            </div>

            <!-- Stats & Live Search Bar -->
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div class="flex items-center gap-2 text-xs text-slate-400 font-medium">
                    <span class="px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800"><strong class="text-slate-200">{total_scripts}</strong> scripts</span>
                    <span class="px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800"><strong class="text-slate-200">{len(channels_set)}</strong> channels</span>
                </div>
                <div class="relative flex-1 max-w-xs">
                    <input type="text" id="search-input" onkeyup="filterScripts()" placeholder="Search scripts or creators..." class="w-full bg-slate-900/80 border border-slate-800 rounded-xl pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition-all">
                    <svg class="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                </div>
            </div>

            <!-- Script Cards List -->
            <div id="cards-container" class="space-y-4">
                {content_html}
            </div>
        </main>

        <!-- Toast Notification Container -->
        <div id="toast" class="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-slate-900 border border-emerald-500/40 text-slate-100 px-4 py-2.5 rounded-2xl text-xs font-semibold shadow-2xl shadow-black/80 flex items-center gap-2 opacity-0 pointer-events-none transition-all duration-300">
            <span class="text-emerald-400">✓</span>
            <span id="toast-msg">Copied to clipboard!</span>
        </div>

        <script>
            function showToast(msg) {{
                const toast = document.getElementById('toast');
                document.getElementById('toast-msg').innerText = msg;
                toast.classList.remove('opacity-0', 'pointer-events-none');
                toast.classList.add('opacity-100');
                setTimeout(() => {{
                    toast.classList.add('opacity-0', 'pointer-events-none');
                    toast.classList.remove('opacity-100');
                }}, 2500);
            }}

            async function copyScript(btn, text) {{
                try {{
                    await navigator.clipboard.writeText(text);
                    const originalHtml = btn.innerHTML;
                    btn.innerHTML = `<svg class="w-4 h-4 text-slate-950" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg><span>Copied!</span>`;
                    btn.classList.replace('bg-emerald-500', 'bg-emerald-300');
                    showToast('Script copied to clipboard!');
                    setTimeout(() => {{
                        btn.innerHTML = originalHtml;
                        btn.classList.replace('bg-emerald-300', 'bg-emerald-500');
                    }}, 2000);
                }} catch (e) {{
                    prompt("Copy manually:", text);
                }}
            }}

            async function deleteScript(filename) {{
                if (!confirm("Delete this script?")) return;
                try {{
                    const res = await fetch(`/api/scripts/${{filename}}`, {{ method: 'DELETE' }});
                    if (res.ok) {{
                        location.reload();
                    }}
                }} catch (e) {{
                    alert("Delete failed: " + e);
                }}
            }}

            async function pasteClipboard() {{
                try {{
                    const clip = await navigator.clipboard.readText();
                    if (clip) {{
                        document.getElementById('url-input').value = clip;
                        showToast('Link pasted from clipboard!');
                    }}
                }} catch (e) {{
                    alert('Please allow clipboard permission or paste manually.');
                }}
            }}

            async function triggerExtraction() {{
                const input = document.getElementById('url-input');
                const btn = document.getElementById('extract-btn');
                const url = input.value.trim();
                if (!url) {{
                    alert('Please enter or paste a valid video URL.');
                    return;
                }}
                btn.disabled = true;
                btn.innerText = 'Starting...';
                try {{
                    const res = await fetch('/api/extract-script', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ url: url, format_style: 'verbatim', async_mode: true }})
                    }});
                    const data = await res.json();
                    showToast(data.message || 'Processing in background!');
                    input.value = '';
                    setTimeout(() => location.reload(), 4500);
                }} catch (e) {{
                    alert('Error: ' + e);
                }} finally {{
                    btn.disabled = false;
                    btn.innerText = 'Record Script';
                }}
            }}

            function filterScripts() {{
                const query = document.getElementById('search-input').value.toLowerCase();
                const cards = document.querySelectorAll('.script-card');
                cards.forEach(card => {{
                    const searchData = card.getAttribute('data-search') || '';
                    card.style.display = searchData.includes(query) ? 'block' : 'none';
                }});
            }}
        </script>
    </body>
    </html>
    """
    return html_page

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host=host, port=port, reload=True)
