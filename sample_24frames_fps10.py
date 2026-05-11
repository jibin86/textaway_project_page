#!/usr/bin/env python3
"""Recursively sample 24 frames from videos and save them at 10 fps.

The script walks under the given root directory, finds video files, and writes
processed copies into an output directory while preserving the relative path.

For each video:
  - the source is probed with ffprobe to determine frame count
  - 24 frame indices are chosen with linear spacing across the full clip
  - ffmpeg extracts only those frames, retimes them, and encodes them at 10 fps

Requirements:
  - ffmpeg
  - ffprobe
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".m4v",
}


def run_cmd(cmd: list[str]) -> str:
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.stdout.strip()


def probe_frame_count(video_path: Path) -> int:
    """Return the number of frames in the first video stream."""
    queries = [
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_frames",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
    ]

    for cmd in queries:
        try:
            out = run_cmd(cmd)
        except subprocess.CalledProcessError:
            continue

        if out and out != "N/A":
            try:
                return int(float(out))
            except ValueError:
                pass

    raise RuntimeError(f"Could not determine frame count for {video_path}")


def linear_indices(total_frames: int, target_frames: int) -> list[int]:
    if total_frames <= 0:
        raise ValueError("total_frames must be positive")

    if total_frames <= target_frames:
        return list(range(total_frames))

    if target_frames == 1:
        return [0]

    # Evenly spread indices from first to last frame.
    return [round(i * (total_frames - 1) / (target_frames - 1)) for i in range(target_frames)]


def build_select_expr(indices: list[int]) -> str:
    return "+".join(f"eq(n\\,{idx})" for idx in indices)


def sample_video(src: Path, dst: Path, target_frames: int, target_fps: int, crf: int = 18) -> None:
    frame_count = probe_frame_count(src)
    indices = linear_indices(frame_count, target_frames)
    select_expr = build_select_expr(indices)

    dst.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = dst.with_suffix(dst.suffix + ".tmp.mp4")
    if tmp_path.exists():
        tmp_path.unlink()

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-vf",
        f"select='{select_expr}',setpts=N/({target_fps}*TB),fps={target_fps}",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        str(tmp_path),
    ]

    subprocess.run(cmd, check=True)
    shutil.move(str(tmp_path), str(dst))


def should_skip(path: Path) -> bool:
    name = path.name.lower()
    return (
        name.endswith(".bak")
        or name.endswith(".tmp.mp4")
        or name.endswith(".fps.mp4")
        or name.endswith(".resample.tmp.mp4")
        or name.endswith(".mp4.mp4")
    )


def iter_videos(root: Path, output_dir: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if should_skip(path):
            continue
        if output_dir in path.parents:
            continue
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            yield path


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample 24 frames from videos and save them at 10 fps.")
    parser.add_argument(
        "root",
        nargs="?",
        default="/mnt/CINELINGO_BACKUP/jibin/html_web",
        help="Root directory to scan",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Where to save processed files. Default: <root>/sampled_24f_fps10",
    )
    parser.add_argument("--frames", type=int, default=24, help="Target frame count per clip")
    parser.add_argument("--fps", type=int, default=10, help="Target output fps")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output files")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else root / "sampled_24f_fps10"

    if not root.exists():
        print(f"Root does not exist: {root}", file=sys.stderr)
        return 1

    videos = list(iter_videos(root, output_dir))
    if not videos:
        print("No videos found.")
        return 0

    processed = 0
    failed = 0

    for src in videos:
        rel = src.relative_to(root)
        dst = output_dir / rel

        if dst.exists() and not args.overwrite:
            print(f"SKIP  {rel} (already exists)")
            continue

        try:
            sample_video(src, dst, target_frames=args.frames, target_fps=args.fps)
            print(f"OK    {rel} -> {dst.relative_to(output_dir)}")
            processed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {rel}: {exc}", file=sys.stderr)
            failed += 1

    summary = {
        "root": str(root),
        "output_dir": str(output_dir),
        "processed": processed,
        "failed": failed,
        "frames": args.frames,
        "fps": args.fps,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())