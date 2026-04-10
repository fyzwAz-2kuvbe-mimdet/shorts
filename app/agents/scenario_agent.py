import json
from google import genai
from google.genai import types
from app.core.config import settings
from app.core.models import ShortsScript, SceneScript

_SYSTEM_PROMPT = """당신은 SNS 숏폼 영상(YouTube Shorts / Reels / TikTok) 전문 시나리오 작가입니다.
주어진 주제로 몰입감 있는 숏츠 대본을 작성하고, 반드시 아래 JSON 형식으로만 응답하세요.

{
  "title": "영상 제목",
  "total_duration": 전체_길이(초, 숫자),
  "scenes": [
    {
      "scene_number": 1,
      "narration": "한국어 나레이션 (TTS로 읽힐 텍스트)",
      "image_prompt": "Detailed English image prompt for Imagen (style, subject, lighting, mood)",
      "duration": 장면_길이(초, 숫자)
    }
  ]
}

규칙:
- narration은 자연스러운 한국어로, 한 장면에 1~2문장
- image_prompt는 구체적인 영어 설명 (예: cinematic, vibrant colors, 9:16 vertical)
- 절대 JSON 외의 텍스트를 포함하지 마세요"""


class ScenarioAgent:
    # gemini-1.5-flash: 무료 티어 제공 / 2.0-flash 할당 초과 시 대안
    MODEL = "gemini-1.5-flash"

    def __init__(self):
        self.client = genai.Client(api_key=settings.GOOGLE_AI_API_KEY)

    def generate_script(
        self,
        topic: str,
        num_scenes: int = 5,
        style: str = "교육적",
    ) -> ShortsScript:
        prompt = (
            f"주제: {topic}\n"
            f"장면 수: {num_scenes}개\n"
            f"스타일: {style}\n"
            f"목표 길이: {num_scenes * 5}~{num_scenes * 7}초\n\n"
            "위 조건에 맞는 숏츠 시나리오를 JSON으로 작성해주세요."
        )

        response = self.client.models.generate_content(
            model=self.MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.9,
            ),
        )

        data = json.loads(response.text)
        scenes = [SceneScript(**s) for s in data["scenes"]]
        return ShortsScript(
            title=data["title"],
            topic=topic,
            total_duration=float(data["total_duration"]),
            scenes=scenes,
        )
