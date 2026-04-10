from pydantic import BaseModel, Field
from typing import List, Optional


class SceneScript(BaseModel):
    """단일 장면의 시나리오"""
    scene_number: int
    narration: str           # TTS로 읽힐 한국어 나레이션
    image_prompt: str        # Imagen에 넘길 영어 이미지 프롬프트
    duration: float = 5.0   # 장면 길이 (초) — TTS 길이로 덮어씀


class ShortsScript(BaseModel):
    """전체 숏츠 시나리오"""
    title: str
    topic: str
    total_duration: float
    scenes: List[SceneScript]


class GeneratedAssets(BaseModel):
    """파이프라인 실행 결과물 경로 묶음"""
    script: ShortsScript
    image_paths: List[str] = Field(default_factory=list)
    audio_paths: List[str] = Field(default_factory=list)
    video_path: Optional[str] = None
