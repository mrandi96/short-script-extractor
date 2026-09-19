import os
from typing import Optional, Dict, Any
import httpx

def send_ntfy_notification(
    title: str,
    channel: str,
    script_text: str,
    video_url: str,
    metadata: Optional[Dict[str, Any]] = None,
    topic: Optional[str] = None
) -> bool:
    """
    Sends a push notification to ntfy.sh with a concise 5-word summary.
    Tapping the notification opens the Script Extractor dashboard directly.
    """
    topic = topic or os.getenv("NTFY_TOPIC")
    if not topic:
        return False

    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    
    # Destination when tapping the notification: opens the Script Extractor web app
    base_url = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
    dashboard_url = f"{base_url}/scripts"

    # Format exactly 5 words + ellipsis
    words = script_text.strip().split()
    if len(words) > 5:
        five_word_summary = " ".join(words[:5]) + "..."
    else:
        five_word_summary = " ".join(words)

    meta = metadata or {}
    views = meta.get("views_formatted", "N/A")
    channel_name = channel or meta.get("channel", "Unknown Creator")

    payload = {
        "topic": topic,
        "title": f"🎬 {title}",
        "message": f"👤 {channel_name} • 👁️ {views}\n\n💬 \"{five_word_summary}\"",
        "tags": ["clapper", "sparkles"],
        "click": dashboard_url,
        "actions": [
            {
                "action": "copy",
                "label": "📋 Copy Full Script",
                "value": script_text.strip()
            },
            {
                "action": "view",
                "label": "▶️ Open Video",
                "url": video_url
            }
        ]
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.post(server, json=payload)
            if res.status_code == 200:
                print(f"[Notifier] 🔔 Push notification sent to ntfy topic: '{topic}'")
                return True
            else:
                print(f"[Notifier] ⚠️ ntfy returned status {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[Notifier] ❌ Failed to send ntfy notification: {e}")

    return False
