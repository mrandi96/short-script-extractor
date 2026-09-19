import os
import re
import requests
from typing import Optional, Tuple, Dict, Any
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp


def format_count(num: Optional[int]) -> str:
    if num is None:
        return "N/A"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    if num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return f"{num:,}"

def get_video_metadata(url: str) -> Dict[str, Any]:
    """
    Extracts metadata: title, channel name, views, and likes without downloading media.
    """
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios']
            }
        },
    }
    cookie_file = os.getenv("YOUTUBE_COOKIES_FILE", "cookies.txt")
    if os.path.exists(cookie_file):
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title") or "Untitled Video"
            channel = info.get("channel") or info.get("uploader") or "Unknown Channel"
            views = info.get("view_count")
            likes = info.get("like_count")
            return {
                "title": title,
                "channel": channel,
                "views": views,
                "likes": likes,
                "views_formatted": format_count(views),
                "likes_formatted": format_count(likes),
                "video_id": str(info.get("id")) if info.get("id") else None,
            }
    except Exception as e:
        print(f"[Metadata] Failed to fetch metadata via yt-dlp: {e}")

        # YouTube oEmbed fallback for metadata
        if "youtube.com" in url or "youtu.be" in url:
            try:
                import requests
                r = requests.get(f"https://www.youtube.com/oembed?url={url}&format=json", timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "title": data.get("title") or "Untitled YouTube Video",
                        "channel": data.get("author_name") or "Unknown Channel",
                        "views": None,
                        "likes": None,
                        "views_formatted": "N/A",
                        "likes_formatted": "N/A",
                        "video_id": None,
                    }
            except Exception as ye:
                print(f"[Metadata] YouTube oEmbed fallback error: {ye}")

        # TikTok oEmbed fallback for metadata
        if "tiktok.com" in url:
            try:
                import requests
                r = requests.get(f"https://www.tiktok.com/oembed?url={url}", timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "title": data.get("title") or "Untitled TikTok",
                        "channel": data.get("author_name") or "Unknown TikToker",
                        "views": None,
                        "likes": None,
                        "views_formatted": "N/A",
                        "likes_formatted": "N/A",
                        "video_id": str(data.get("embed_product_id")) if data.get("embed_product_id") else None,
                    }
            except Exception as oe:
                print(f"[Metadata] TikTok oEmbed fallback error: {oe}")

        return {
            "title": "Untitled Video",
            "channel": "Unknown Channel",
            "views": None,
            "likes": None,
            "views_formatted": "N/A",
            "likes_formatted": "N/A",
            "video_id": None,
        }

def extract_video_info(url: str) -> Tuple[str, Optional[str]]:
    """
    Identifies the platform and extracts the video ID if available.
    Returns: (platform, video_id)
    platform: 'youtube' | 'tiktok' | 'unknown'
    """
    clean_url = url.strip()

    # YouTube patterns (shorts, watch, youtu.be, embed)
    yt_patterns = [
        r"(?:v=|\/shorts\/|youtu\.be\/|\/embed\/|\/v\/)([a-zA-Z0-9_-]{11})"
    ]
    for pattern in yt_patterns:
        match = re.search(pattern, clean_url)
        if match:
            return "youtube", match.group(1)

    # TikTok patterns
    if "tiktok.com" in clean_url:
        match = re.search(r"\/video\/(\d+)", clean_url)
        video_id = match.group(1) if match else None
        return "tiktok", video_id

    return "unknown", None


def get_native_youtube_captions(video_id: str) -> Optional[str]:
    """
    Fetches native or auto-generated YouTube captions without downloading media.
    Supports both youtube-transcript-api v1.x (instance methods) and v0.x (class methods).
    """
    try:
        session = None
        cookie_file = os.getenv("YOUTUBE_COOKIES_FILE", "cookies.txt")
        if os.path.exists(cookie_file):
            import http.cookiejar
            import requests
            try:
                cj = http.cookiejar.MozillaCookieJar(cookie_file)
                cj.load(ignore_discard=True, ignore_expires=True)
                session = requests.Session()
                session.cookies = cj
            except Exception as ce:
                print(f"[Extractor] Error loading cookie file: {ce}")

        api = YouTubeTranscriptApi(http_client=session) if callable(YouTubeTranscriptApi) else YouTubeTranscriptApi

        # 1. Try listing transcripts
        transcript_list = None
        if hasattr(api, "list"):
            try:
                transcript_list = api.list(video_id)
            except Exception:
                pass
        elif hasattr(api, "list_transcripts"):
            try:
                transcript_list = api.list_transcripts(video_id)
            except Exception:
                pass

        transcript = None
        if transcript_list:
            preferred_langs = ['en', 'id', 'es', 'fr', 'de', 'ja', 'ko', 'pt']
            # Try manual transcript
            try:
                transcript = transcript_list.find_manually_created_transcript(preferred_langs)
            except Exception:
                pass

            # Try auto-generated transcript
            if not transcript:
                try:
                    transcript = transcript_list.find_generated_transcript(preferred_langs)
                except Exception:
                    pass

            # Fallback to any transcript in the list
            if not transcript:
                for t in transcript_list:
                    transcript = t
                    break

        # 2. Fetch the snippets
        entries = None
        if transcript and hasattr(transcript, "fetch"):
            entries = transcript.fetch()
        elif hasattr(api, "fetch"):
            try:
                entries = api.fetch(video_id)
            except Exception:
                pass
        elif hasattr(api, "get_transcript"):
            try:
                entries = api.get_transcript(video_id)
            except Exception:
                pass

        if entries:
            text_snippets = []
            for entry in entries:
                text = getattr(entry, "text", None)
                if text is None and isinstance(entry, dict):
                    text = entry.get("text")
                if text:
                    text_clean = str(text).replace("\n", " ").strip()
                    if text_clean:
                        text_snippets.append(text_clean)
            if text_snippets:
                return " ".join(text_snippets)

    except Exception as e:
        print(f"[Extractor] Native caption extraction encountered error: {e}")
        return None

    return None
