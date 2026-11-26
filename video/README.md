# Walkthrough video

An 8–9 minute narrated, end-to-end walkthrough of the SignalCore app, recorded from the real UI (replay mode, so every model output is the one Claude produced in the recorded live run).

| File | Purpose |
|---|---|
| `narration.json` | Voiceover script, one entry per scene |
| `durations.json` | Length of each narration clip; paces the recording |
| `record.js` | Drives the app with Playwright (scripted cursor, smooth scrolling) and captures frames through the Chrome DevTools screencast |
| `assemble.py` | Builds a 1080p30 H.264/AAC MP4: frames on their real timestamps, each narration clip placed at its scene's start, loudness-normalised |

## Rebuild

```bash
# 1. Voice (local, open-weights Kokoro TTS; nothing leaves the machine)
python3 -m venv ~/tts && ~/tts/bin/pip install kokoro-onnx soundfile
#    model files: kokoro-v1.0.onnx and voices-v1.0.bin from the kokoro-onnx GitHub releases (model-files-v1.0)
#    then synthesise each scene of narration.json to audio/<id>.wav (voice af_heart) and write durations.json

# 2. App in replay mode, with demo pacing so the pipeline run is readable on screen
SIGNALCORE_MODE=replay SIGNALCORE_STEP_DELAY=3.1 .venv/bin/uvicorn signalcore.api:app --port 8000

# 3. Record, then assemble
node video/record.js /tmp/rec
python3 video/assemble.py /tmp/rec signalcore-walkthrough.mp4
```

Recording kicks off a replay run and applies one PM estimate override, so back up `data/signalcore.db` first if you want to keep its state.

`SIGNALCORE_STEP_DELAY` only pauses between steps for demos. It does not change results or the step timings that are logged.
