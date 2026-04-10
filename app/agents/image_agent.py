from pathlib import Path
from google import genai
from google.genai import types
from app.core.config import settings
from app.utils.file_utils import get_image_path


class ImageAgent:
    MODEL = "imagen-3.0-generate-002"

    def __init__(self):
        self.client = genai.Client(api_key=settings.GOOGLE_AI_API_KEY)

    def generate_image(self, prompt: str, scene_number: int) -> Path:
        """Imagen 3으로 장면 이미지 생성 후 PNG로 저장"""
        response = self.client.models.generate_images(
            model=self.MODEL,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="9:16",          # 세로형 숏츠
                safety_filter_level="BLOCK_ONLY_HIGH",
                person_generation="ALLOW_ADULT",
            ),
        )

        image_bytes = response.generated_images[0].image.image_bytes
        out_path = get_image_path(scene_number)
        out_path.write_bytes(image_bytes)
        return out_path
