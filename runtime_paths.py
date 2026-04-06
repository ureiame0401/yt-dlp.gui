import shutil
import sys
from pathlib import Path


def get_app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _candidate_files(base_dir: Path, names: list[str]) -> list[Path]:
    candidates: list[Path] = []
    search_dirs = [
        base_dir,
        base_dir / "tools",
        base_dir / "bin",
        base_dir / "ffmpeg",
        base_dir / "yt-dlp",
    ]
    for folder in search_dirs:
        for name in names:
            candidates.append(folder / name)
    return candidates


def detect_bundled_ytdlp() -> str | None:
    base_dir = get_app_base_dir()
    names = ["yt-dlp.exe", "yt-dlp"] if sys.platform == "win32" else ["yt-dlp"]
    for path in _candidate_files(base_dir, names):
        if path.exists() and path.is_file():
            return str(path)
    found = shutil.which("yt-dlp")
    return found


def detect_bundled_ffmpeg_dir() -> str | None:
    base_dir = get_app_base_dir()
    ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    ffprobe_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"

    search_dirs = [
        base_dir,
        base_dir / "tools",
        base_dir / "bin",
        base_dir / "ffmpeg",
    ]

    for folder in search_dirs:
        ffmpeg_path = folder / ffmpeg_name
        ffprobe_path = folder / ffprobe_name
        if ffmpeg_path.exists() and ffprobe_path.exists():
            return str(folder)
        if ffmpeg_path.exists():
            return str(folder)

    found = shutil.which("ffmpeg")
    if found:
        return str(Path(found).resolve().parent)
    return None


def detect_runtime_tools() -> dict:
    return {
        "base_dir": str(get_app_base_dir()),
        "ytdlp": detect_bundled_ytdlp(),
        "ffmpeg_dir": detect_bundled_ffmpeg_dir(),
    }
