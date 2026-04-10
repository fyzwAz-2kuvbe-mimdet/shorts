from typing import Callable, Optional
from app.core.models import GeneratedAssets
from app.agents.scenario_agent import ScenarioAgent
from app.agents.image_agent import ImageAgent
from app.agents.tts_agent import TTSAgent
from app.agents.video_agent import VideoAgent
from app.utils.file_utils import ensure_output_dirs

ProgressCallback = Optional[Callable[[str, int], None]]


class ShortsPipeline:
    """4단계 파이프라인: 시나리오 → 이미지 → TTS → 영상"""

    def __init__(self):
        self.scenario_agent = ScenarioAgent()
        self.image_agent = ImageAgent()
        self.tts_agent = TTSAgent()
        self.video_agent = VideoAgent()

    def run(
        self,
        topic: str,
        num_scenes: int = 5,
        style: str = "교육적",
        on_progress: ProgressCallback = None,
    ) -> GeneratedAssets:
        ensure_output_dirs()

        def progress(msg: str, pct: int) -> None:
            if on_progress:
                on_progress(msg, pct)

        # ── 1단계: 시나리오 ──────────────────────────────────────────────────
        progress("📝 시나리오 생성 중...", 5)
        script = self.scenario_agent.generate_script(topic, num_scenes, style)

        # ── 2단계: 이미지 ────────────────────────────────────────────────────
        image_paths: list[str] = []
        for i, scene in enumerate(script.scenes):
            pct = 15 + int(35 * i / num_scenes)
            progress(f"🖼️  이미지 생성 중... ({i + 1}/{num_scenes})", pct)
            path = self.image_agent.generate_image(scene.image_prompt, scene.scene_number)
            image_paths.append(str(path))

        # ── 3단계: TTS ───────────────────────────────────────────────────────
        audio_paths: list[str] = []
        for i, scene in enumerate(script.scenes):
            pct = 50 + int(25 * i / num_scenes)
            progress(f"🔊 음성 생성 중... ({i + 1}/{num_scenes})", pct)
            path = self.tts_agent.synthesize(scene.narration, scene.scene_number)
            audio_paths.append(str(path))

        # ── 4단계: 영상 합성 ─────────────────────────────────────────────────
        progress("🎬 영상 합성 중...", 80)
        assets = GeneratedAssets(
            script=script,
            image_paths=image_paths,
            audio_paths=audio_paths,
        )
        video_path = self.video_agent.synthesize(assets)
        assets.video_path = str(video_path)

        progress("✅ 완료!", 100)
        return assets
