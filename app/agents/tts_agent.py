from pathlib import Path
from gtts import gTTS
from app.utils.file_utils import get_audio_path


class TTSAgent:
    """TTS 에이전트 (현재: gTTS — API 키 불필요)
    Google Cloud TTS로 전환 시 tts_agent_cloud.py 참고
    """

    def synthesize(self, text: str, scene_number: int) -> Path:
        """나레이션 텍스트 → MP3 파일"""
        tts = gTTS(text=text, lang="ko", slow=False)
        out_path = get_audio_path(scene_number)
        tts.save(str(out_path))
        return out_path
