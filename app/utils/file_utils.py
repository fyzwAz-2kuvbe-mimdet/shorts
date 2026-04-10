import re
from pathlib import Path
from app.core.config import settings


def ensure_output_dirs() -> None:
    """출력 디렉토리 트리 생성"""
    for d in (settings.IMAGES_DIR, settings.AUDIO_DIR, settings.VIDEOS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def get_image_path(scene_number: int) -> Path:
    return settings.IMAGES_DIR / f"scene_{scene_number:02d}.png"


def get_audio_path(scene_number: int) -> Path:
    return settings.AUDIO_DIR / f"scene_{scene_number:02d}.mp3"


def get_video_path(title: str) -> Path:
    safe = re.sub(r"[^\w\s-]", "", title).strip()
    safe = re.sub(r"\s+", "_", safe)
    return settings.VIDEOS_DIR / f"{safe}.mp4"
