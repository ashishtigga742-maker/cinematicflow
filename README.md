# CinematicFlow
Independent AI-assisted video clipping MVP. Not connected to Cliphi's API.

Features: video upload, direct HTTPS video-file URL import, Faster-Whisper transcription, transcript-scored highlights, FFmpeg MP4 exports in 9:16 / 1:1 / 4:5 / 16:9, progress and downloads.

Local run: install FFmpeg, Python 3.11+, then `pip install -r requirements.txt` and `uvicorn main:app --reload`. Open http://127.0.0.1:8000.

Deploy: push to GitHub and create a Render Blueprint using render.yaml. It specifies a free service; CPU transcription may be slow or exceed free resource limits. Review costs before upgrading.

MVP limitations: in-memory jobs reset on restart; no persistent DB/queue; centered crop only (no face tracking); URL import supports direct HTTPS file URLs, not platform watch pages. Add authentication, rate limiting, storage lifecycle and stronger URL isolation before public production use. Upload only content you own or are licensed to process.
