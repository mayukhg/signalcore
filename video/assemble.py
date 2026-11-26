"""Assemble the walkthrough: timestamped screencast frames + per-scene narration -> MP4 (H.264/AAC, 1080p30).

    python3 video/assemble.py <recording dir> <out.mp4>
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(rec, out):
    rec = Path(rec)
    tl = json.loads((rec / "timeline.json").read_text())
    frames, marks = tl["frames"], tl["marks"]
    t0 = frames[0]["t"]
    end = marks[-1]["t"]
    lines = []
    for i, f in enumerate(frames):
        nxt = frames[i + 1]["t"] if i + 1 < len(frames) else end
        d = max(0.001, nxt - f["t"])
        lines += [f"file '{(rec / 'frames' / f['file']).as_posix()}'", f"duration {d:.4f}"]
    lines.append(f"file '{(rec / 'frames' / frames[-1]['file']).as_posix()}'")
    (rec / "frames.txt").write_text("\n".join(lines) + "\n")
    total = end - t0

    scenes = [m for m in marks if m["id"] != "end"]
    inputs, filters = [], []
    for k, m in enumerate(scenes):
        inputs += ["-i", str(HERE / "audio" / f"{m['id']}.wav")]
        delay = max(0, int((m["t"] - t0) * 1000))
        filters.append(f"[{k + 1}:a]adelay={delay}|{delay}[a{k}]")
    mix = "".join(f"[a{k}]" for k in range(len(scenes)))
    filters.append(f"{mix}amix=inputs={len(scenes)}:normalize=0,apad,atrim=0:{total:.3f},loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
    vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0A0D12,fps=30,format=yuv420p"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(rec / "frames.txt"), *inputs,
           "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]",
           "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-tune", "stillimage",
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", "-t", f"{total:.3f}", str(out)]
    subprocess.run(cmd, check=True)
    # chapter list for the description
    ch = [f"{int((m['t'] - t0) // 60):02d}:{int((m['t'] - t0) % 60):02d}  {m['id']}" for m in scenes]
    (Path(out).with_suffix(".chapters.txt")).write_text("\n".join(ch) + "\n")
    print(f"wrote {out}: {total / 60:.1f} min, {len(frames)} frames")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
