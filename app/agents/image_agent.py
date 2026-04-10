import time
from pathlib import Path
from google import genai
from google.genai import types
from app.core.config import settings
from app.utils.file_utils import get_image_path
from app.utils.retry import retry_with_backoff

_IMAGEN_MODELS = [
    "imagen-3.0-generate-002",
    "imagen-3.0-fast-generate-001",  # 빠른 버전으로 폴백
]


class ImageAgent:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GOOGLE_AI_API_KEY)

    def generate_image(self, prompt: str, scene_number: int) -> Path:
        """Imagen 3으로 이미지 생성. 429 시 재시도 후 fast 모델로 폴백."""
        out_path = get_image_path(scene_number)

        for model in _IMAGEN_MODELS:
            try:
                def _call(m: str) -> bytes:
                    resp = self.client.models.generate_images(
                        model=m,
                        prompt=prompt,
                        config=types.GenerateImagesConfig(
                            number_of_images=1,
                            aspect_ratio="9:16",
                            safety_filter_level="BLOCK_ONLY_HIGH",
                            person_generation="ALLOW_ADULT",
                        ),
                    )
                    return resp.generated_images[0].image.image_bytes

                image_bytes = retry_with_backoff(_call, model, max_retries=4, base_delay=8.0)
                out_path.write_bytes(image_bytes)

                # 연속 요청 간 간격 (Imagen 분당 제한 회피)
                time.sleep(2)
                return out_path

            except Exception as e:
                from app.utils.retry import is_quota_error
                if is_quota_error(e) and model != _IMAGEN_MODELS[-1]:
                    continue  # 다음 모델로 폴백
                raise

        raise RuntimeError("모든 Imagen 모델 할당량 초과")
