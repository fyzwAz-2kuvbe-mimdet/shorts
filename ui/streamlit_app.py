import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from app.pipeline import ShortsPipeline
from app.core.config import settings

st.set_page_config(
    page_title="AI Shorts 자동화 에이전트",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 AI Shorts 자동화 에이전트")
st.caption("Gemini Imagen · Google TTS · FFmpeg 으로 숏츠를 자동 생성합니다.")

# ── 사이드바 ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 생성 설정")

    num_scenes = st.slider("장면 수", min_value=3, max_value=10, value=5, step=1)

    style = st.selectbox(
        "영상 스타일",
        ["교육적", "엔터테인먼트", "뉴스/정보", "감성적", "유머러스"],
    )

    st.divider()
    api_ok = bool(settings.GOOGLE_AI_API_KEY)
    st.markdown(f"{'🟢' if api_ok else '🔴'} Google AI API")
    if not api_ok:
        st.warning("API 키가 없습니다.\nApp settings → Secrets에 추가하세요.")
        # 디버그: secrets에 어떤 키가 보이는지 확인
        try:
            st.caption(f"secrets 키 목록: {list(st.secrets.keys())}")
        except Exception as e:
            st.caption(f"secrets 접근 오류: {e}")

# ── 메인 입력 ────────────────────────────────────────────────────────────────
topic = st.text_input(
    "영상 주제",
    placeholder="예: 블랙홀의 신비 / 커피가 뇌에 미치는 영향 / 파이썬을 배워야 하는 이유",
    help="구체적일수록 더 좋은 시나리오가 생성됩니다.",
)

generate_btn = st.button("🚀 영상 생성 시작", type="primary", use_container_width=True)

# ── 파이프라인 실행 ───────────────────────────────────────────────────────────
if generate_btn:
    if not topic.strip():
        st.warning("주제를 입력해주세요.")
        st.stop()

    try:
        settings.validate()
    except EnvironmentError as e:
        st.error(str(e))
        st.stop()

    progress_bar = st.progress(0)
    status_text = st.empty()

    def on_progress(msg: str, pct: int) -> None:
        status_text.info(msg)
        progress_bar.progress(pct)

    try:
        pipeline = ShortsPipeline()
        assets = pipeline.run(
            topic=topic.strip(),
            num_scenes=num_scenes,
            style=style,
            on_progress=on_progress,
        )

        progress_bar.progress(100)
        status_text.success("✅ 영상 생성 완료!")

        # ── 시나리오 미리보기 ─────────────────────────────────────────────
        with st.expander("📋 생성된 시나리오", expanded=False):
            st.subheader(assets.script.title)
            st.caption(f"총 길이: {assets.script.total_duration:.0f}초")
            for scene in assets.script.scenes:
                st.markdown(f"**장면 {scene.scene_number}** — {scene.duration}초")
                st.write(scene.narration)
                st.caption(f"이미지 프롬프트: {scene.image_prompt}")
                st.divider()

        # ── 생성된 이미지 그리드 ──────────────────────────────────────────
        with st.expander("🖼️ 생성된 이미지", expanded=False):
            cols = st.columns(min(num_scenes, 5))
            for i, img_path in enumerate(assets.image_paths):
                with cols[i % 5]:
                    st.image(img_path, caption=f"장면 {i + 1}", use_container_width=True)

        # ── 최종 영상 ─────────────────────────────────────────────────────
        st.subheader("🎥 완성된 영상")
        st.video(assets.video_path)

        with open(assets.video_path, "rb") as f:
            st.download_button(
                label="⬇️ 영상 다운로드 (MP4)",
                data=f,
                file_name=Path(assets.video_path).name,
                mime="video/mp4",
                use_container_width=True,
            )

    except Exception as e:
        status_text.error(f"오류 발생: {e}")
        st.exception(e)
