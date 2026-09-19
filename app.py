import os
import uvicorn
import gradio as gr
from main import app as fastapi_app, extract_script_endpoint, ExtractRequest
from fastapi import BackgroundTasks

# Define a clean Gradio interface so Hugging Face registers the Space as healthy
with gr.Blocks(title="Script Studio") as demo:
    gr.Markdown("# ⚡ Shorts Script Studio")
    gr.Markdown("Extract clean, verbatim scripts from YouTube Shorts, TikTok, and Instagram Reels.")
    
    with gr.Row():
        url_input = gr.Textbox(label="Video URL", placeholder="https://youtube.com/shorts/...", scale=4)
        submit_btn = gr.Button("Extract Script", variant="primary", scale=1)
    
    status_out = gr.Markdown("Ready. You can also view the full dashboard at `/scripts`.")
    result_out = gr.TextArea(label="Recorded Script", lines=10)
    
    def on_click_extract(url):
        if not url:
            return "Please enter a URL.", ""
        try:
            req = ExtractRequest(url=url, format_style="verbatim", async_mode=False)
            bg = BackgroundTasks()
            res = extract_script_endpoint(req, bg)
            return f"✅ Done! Extracted from {res.platform} ({res.video_id})", res.script or "No script returned."
        except Exception as e:
            return f"❌ Error: {str(e)}", ""

    submit_btn.click(fn=on_click_extract, inputs=url_input, outputs=[status_out, result_out])

# Mount Gradio onto our FastAPI app at /gradio
# This preserves all our API routes (/api/extract-script, /scripts, etc.)
combined_app = gr.mount_gradio_app(fastapi_app, demo, path="/gradio")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 7860))
    uvicorn.run(combined_app, host="0.0.0.0", port=port)
