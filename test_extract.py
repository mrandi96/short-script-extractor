#!/usr/bin/env python3
"""
Quick CLI tester for the Short Script Extractor
Usage:
    python test_extract.py https://youtube.com/shorts/dQw4w9WgXcQ
"""
import sys
import json
from services.extractor import extract_video_info, get_native_youtube_captions
from services.transcriber import download_and_transcribe
from services.formatter import format_script
import os
from dotenv import load_dotenv

load_dotenv()

def test_url(url: str):
    print(f"\n======================================")
    print(f"Testing URL: {url}")
    print(f"======================================")

    platform, video_id = extract_video_info(url)
    print(f"Detected platform: {platform} (ID: {video_id})")

    raw_text = None
    source = None

    if platform == "youtube" and video_id:
        print("[1] Checking native captions...")
        raw_text = get_native_youtube_captions(video_id)
        if raw_text:
            source = "native_captions"
            print(f"-> SUCCESS! Got native captions ({len(raw_text)} characters).")

    if not raw_text:
        print("[2] Native captions not found. Testing yt-dlp + Whisper...")
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            print("-> Note: GROQ_API_KEY is not set in .env. Skipping Whisper fallback.")
        else:
            try:
                raw_text = download_and_transcribe(url, groq_api_key=groq_key)
                source = "whisper_fallback"
                print(f"-> SUCCESS! Whisper transcribed audio ({len(raw_text)} characters).")
            except Exception as e:
                print(f"-> Whisper error: {e}")

    if not raw_text:
        print("No transcript could be obtained.")
        return

    print("\n--- Raw Transcript Snippet ---")
    print(raw_text[:300] + ("..." if len(raw_text) > 300 else ""))

    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        print("\n[3] Formatting script via Gemini...")
        script = format_script(raw_text, style="structured", api_key=gemini_key)
        print("\n--- Formatted Script ---")
        print(script)
    else:
        print("\n-> Note: GEMINI_API_KEY is not set in .env. Formatted script skipped.")

if __name__ == "__main__":
    test_target = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/shorts/3i_JmO7zC4s"
    test_url(test_target)
