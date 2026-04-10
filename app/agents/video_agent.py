from pathlib import Path
from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips
from app.core.models import GeneratedAssets
from app.utils.file_utils import get_video_path

# 세로형 숏츠 해상도 (9:16)
TARGET_W, TARGET_H = 1080, 1920


class VideoAgent:
    """이미지 + 오디오 클립을 합성해 MP4로 출력"""

    def synthesize(self, assets: GeneratedAssets) -> Path:
        clips = []

        for i, scene in enumerate(assets.script.scenes):
            audio = AudioFileClip(assets.audio_paths[i])

            img_clip = (
                ImageClip(assets.image_paths[i])
                .set_duration(audio.duration)
                .resize((TARGET_W, TARGET_H))
                .set_audio(audio)
            )
            clips.append(img_clip)

        final = concatenate_videoclips(clips, method="compose")
        out_path = get_video_path(assets.script.title)

        final.write_videofile(
            str(out_path),
            fps=30,
            codec="libx264",
            audio_codec="aac",
            threads=4,
            logger=None,   # moviepy 진행 로그 억제 (Streamlit과 충돌 방지)
        )
        final.close()
        return out_path
