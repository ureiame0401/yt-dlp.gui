import json
from pathlib import Path


PRESET_FILE = Path(__file__).with_name("yt_dlp_gui_presets.json")


def load_presets_from_disk() -> dict:
    if not PRESET_FILE.exists():
        return {}

    try:
        with PRESET_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_presets_to_disk(presets: dict) -> None:
    with PRESET_FILE.open("w", encoding="utf-8") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)
