import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _get_secret(key: str) -> str:
    """st.secrets (Streamlit Cloud / 로컬 secrets.toml) 우선, 없으면 환경변수"""
    # 1순위: 환경변수 (Streamlit Cloud는 Secrets를 환경변수로도 주입함)
    env_val = os.getenv(key, "")
    if env_val:
        return env_val
    # 2순위: st.secrets 직접 접근
    try:
        import streamlit as st
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return ""


class Settings:
    @property
    def GOOGLE_AI_API_KEY(self) -> str:
        return _get_secret("GOOGLE_AI_API_KEY")

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
