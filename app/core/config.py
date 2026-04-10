import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _get_secret(key: str) -> str:
    """st.secrets (Streamlit Cloud / 로컬 secrets.toml) 우선, 없으면 환경변수"""
    try:
        import streamlit as st
        val = st.secrets.get(key, "")
        if val:
            return str(val)
    except Exception:
        pass
    return os.getenv(key, "")


class Settings:
    GOOGLE_AI_API_KEY: str = _get_secret("GOOGLE_AI_API_KEY")

    # Streamlit Cloud는 프로젝트 디렉토리가 읽기 전용 → /tmp 사용
    _output_dir = Path(
        os.getenv("OUTPUT_DIR", str(Path(tempfile.gettempdir()) / "ai_shorts_output"))
    )

    @property
    def OUTPUT_DIR(self) -> Path:
        return self._output_dir

    @property
    def IMAGES_DIR(self) -> Path:
        return self._output_dir / "images"

    @property
    def AUDIO_DIR(self) -> Path:
        return self._output_dir / "audio"

    @property
    def VIDEOS_DIR(self) -> Path:
        return self._output_dir / "videos"

    def validate(self) -> None:
        if not self.GOOGLE_AI_API_KEY:
            raise EnvironmentError(
                "GOOGLE_AI_API_KEY가 설정되지 않았습니다.\n"
                "• Streamlit Cloud: App settings → Secrets\n"
                "• 로컬: .streamlit/secrets.toml 또는 .env"
            )


settings = Settings()
