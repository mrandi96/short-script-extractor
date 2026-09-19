# Short Script Extractor (Backend + Android Integration)

Extract and generate clean, structured video scripts from **YouTube Shorts**, **TikTok**, and **Instagram Reels** directly from your Android device.

---

## ⚡ How It Works
```
[YouTube / TikTok Short] 
      │
      ▼ (Tap Share -> "Generate Script" OR Tap Home Widget from Clipboard)
[Android HTTP Shortcuts]
      │
      ▼ (POST /api/extract-script)
[Short Script Extractor Backend]
      │
      ├── 1. Check native platform captions (Fastest & Free)
      └── 2. Fallback: Download audio (yt-dlp) -> Transcribe (Groq Whisper)
      │
      ▼
[Gemini 2.5 Flash Script Cleaner & Formatter]
      │
      ▼
[Pop-up Dialog on Android + Auto-copied to Clipboard]
```

---

## 🚀 1. Setup Backend Locally

### Prerequisites
- Python 3.10+
- `ffmpeg` (installed via `brew install ffmpeg` on macOS, or `apt install ffmpeg` on Linux)
- [Groq API Key](https://console.groq.com/) (free tier available, for instant Whisper audio transcription)
- [Google Gemini API Key](https://aistudio.google.com/) (free tier available, for script cleaning)

### Installation
```bash
cd short_script_extractor

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Open .env and add your GROQ_API_KEY and GEMINI_API_KEY
```

### Run Server
```bash
python main.py
```
Server runs at `http://localhost:8000`. Test health: `http://localhost:8000/health`.

---

## 🌐 2. Connect Your Phone to Your Local Backend

To let your Android phone reach your computer, you can expose port 8000 using **localtunnel** (zero signup / no auth token required):

```bash
# Start localtunnel on port 8000
lt --port 8000
```
It will output:
```
your url is: https://funny-otter-42.localtunnel.me
```

> [!TIP]
> **Important for Localtunnel**: In your Android HTTP Shortcuts app, add this header so localtunnel doesn't block the API with its anti-abuse reminder page:
> - **Header Name**: `Bypass-Tunnel-Reminder`
> - **Header Value**: `true`

*(You can also use custom subdomains with `lt --port 8000 --subdomain my-unique-extractor` if available).*


---

## 📱 3. Configure Android "HTTP Shortcuts" App

1. Download **[HTTP Shortcuts](https://http-shortcuts.rmen.ch/)** from Google Play Store or F-Droid.
2. Tap **`+`** (Create Shortcut).

### Basic Configuration
- **Shortcut Name**: `Extract Script`
- **Method**: `POST`
- **URL**: `https://your-server-url/api/extract-script`

### Share Sheet & Clipboard Integration
1. In the shortcut settings, scroll to **"Share / External apps"**:
   - Enable **Accept shared content**.
   - Check **Text (`text/plain`)**.
2. Open the **Scripting** tab:
   - Under **Run before request (Prepare script)**, paste:
   ```javascript
   // 1. Try to get URL from Android Share Sheet
   let rawInput = getVariable("shared_text");

   // 2. Fallback: Read from clipboard if not shared directly
   if (!rawInput || rawInput.trim() === "") {
       rawInput = getClipboard();
   }

   // 3. Extract the clean URL (handles YouTube's extra share title text)
   const urlMatch = rawInput.match(/https?:\/\/[^\s]+/);
   if (!urlMatch) {
       abort("No valid video link found in clipboard or share!");
   }

   setVariable("target_url", urlMatch[0]);
   ```

### Request Body
1. Go to **Request Body**:
   - Type: **JSON**
   - Content:
   ```json
   {
     "url": "{{target_url}}",
     "format_style": "structured"
   }
   ```

### Response Handling
1. Under **Response Handling**:
   - **Show response as**: `Dialog`
   - **Dialog title**: `Video Script`
2. Under **Run after request (Process script)**, paste:
   ```javascript
   const res = JSON.parse(response.body);
   if (res.script) {
       // Automatically copies the script to your clipboard
       setClipboard(res.script);
       showToast("Script copied to clipboard!");
   }
   ```

---

## 🎯 How to Use on Android

### Method A: From the Share Button
1. Open any **YouTube Short** or **TikTok**.
2. Tap **Share**.
3. Select **Extract Script** from the Android Share menu.
4. The dialog appears with the structured script, already copied to your clipboard!

### Method B: From Clipboard
1. Tap **Copy Link** on any video.
2. Tap the **Extract Script** widget on your home screen or quick settings.
3. Done!
