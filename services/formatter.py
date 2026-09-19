import os
from typing import Optional

def format_script(raw_transcript: str, style: str = "verbatim", api_key: Optional[str] = None, model_name: str = "gemini-2.5-flash") -> str:
    """
    Cleans and formats raw transcript into a natural, readable verbatim script.
    Preserves all original spoken words without summarizing or adding artificial sections.
    """
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return raw_transcript

    prompt = f"""
You are a transcript editor. Clean up this raw video transcript so it reads as a clean, natural script:
- Keep the speaker's EXACT spoken words and full message intact.
- DO NOT summarize. DO NOT delete content.
- DO NOT add section headers or labels (NO "[Hook]", NO "[Core Content]", NO "[CTA]").
- Fix punctuation, capitalization, sentence boundaries, and obvious auto-caption misspellings.
- Organize into natural, readable paragraphs.
- Output ONLY the clean script text.

Raw Transcript:
{raw_transcript}
"""

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={'thinking_config': {'thinking_budget': 0}}
        )
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"[Formatter] Error: {e}")

    return raw_transcript
