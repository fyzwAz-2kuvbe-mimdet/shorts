import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
import streamlit as st
from app.core.config import settings
from app.core.models import ShortsScript, SceneScript
from app.agents.scenario_agent import ScenarioAgent

# 브라우저 모드는 로컬 전용 — Streamlit Cloud 감지
IS_CLOUD = (
    os.getenv("HOME", "") == "/home/appuser"          # Streamlit Cloud
    or os.path.exists("/mount/src")                    # Streamlit Cloud 마운트 경로
    or os.getenv("STREAMLIT_SHARING_MODE") == "true"  # 공식 env
)

if not IS_CLOUD:
    from app.agents.browser_agent import BrowserScenarioAgent
    from app.agents.browser_image_agent import BrowserImageAgent
    from app.utils.credentials import save_credentials, load_credentials, has_credentials, clear_credentials
from app.agents.image_agent import ImageAgent
from app.agents.tts_agent import TTSAgent
from app.agents.video_agent import VideoAgent
from app.core.models import GeneratedAssets
from app.utils.file_utils import ensure_output_dirs

# ── 페이지 설정 ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Shorts 에이전트",
    page_icon="🎬",
    layout="wide",
)

# ── 에이전트 페르소나 정의 ────────────────────────────────────────────────────
PERSONAS = {
    "scenario": {
        "emoji": "✍️",
        "name": "극작가 제이",
        "role": "시나리오 작가",
        "desc": "주제를 받아 장면별 대사와 이미지 프롬프트를 작성합니다.",
        "color": "#FF6B6B",
        "bg": "#fff0f0",
    },
    "image": {
        "emoji": "🎨",
        "name": "화가 루나",
        "role": "이미지 생성",
        "desc": "각 장면을 9:16 세로형 이미지로 그립니다.",
        "color": "#845EC2",
        "bg": "#f5f0ff",
    },
    "tts": {
        "emoji": "🎤",
        "name": "성우 아리",
        "role": "나레이터",
        "desc": "대사를 자연스러운 음성으로 변환합니다.",
        "color": "#0081CF",
        "bg": "#f0f6ff",
    },
    "video": {
        "emoji": "🎬",
        "name": "편집장 맥스",
        "role": "영상 편집",
        "desc": "이미지와 음성을 합쳐 최종 영상을 완성합니다.",
        "color": "#00897B",
        "bg": "#f0faf8",
    },
}

# ── 세션 상태 초기화 ──────────────────────────────────────────────────────────
def init_state():
    defaults = {
        "script": None,
        "image_paths": [],
        "audio_paths": [],
        "video_path": None,
        "browser_mode": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ── 헤더 ─────────────────────────────────────────────────────────────────────
st.title("🎬 AI Shorts 자동화 에이전트")
st.caption("각 에이전트를 개별 실행하거나 전체를 한번에 생성할 수 있습니다.")

# ── 사이드바 ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 기본 설정")

    topic = st.text_input(
        "영상 주제",
        placeholder="예: 블랙홀의 신비 / 커피가 뇌에 미치는 영향",
        key="topic_input",
    )
    num_scenes = st.slider("장면 수", 3, 10, 5)
    style = st.selectbox("스타일", ["교육적", "엔터테인먼트", "뉴스/정보", "감성적", "유머러스"])

    st.divider()

    # ── Google 계정 설정 (로컬 전용) ─────────────────────────────────────────
    if not IS_CLOUD:
        st.markdown("**🔑 Google 계정**")
        saved_email, _ = load_credentials()
        cred_ok = has_credentials()

        if cred_ok:
            st.success(f"저장됨: {saved_email}")
            if st.button("계정 변경 / 삭제", use_container_width=True):
                st.session_state["show_login_form"] = True

        if not cred_ok or st.session_state.get("show_login_form", False):
            with st.form("login_form"):
                st.caption("입력한 정보는 Windows Credential Manager에만 저장됩니다.")
                input_email = st.text_input("Google 이메일", placeholder="example@gmail.com")
                input_pw = st.text_input("비밀번호", type="password")
                col1, col2 = st.columns(2)
                with col1:
                    save_btn = st.form_submit_button("💾 저장", use_container_width=True)
                with col2:
                    del_btn = st.form_submit_button("🗑️ 삭제", use_container_width=True)

                if save_btn:
                    if input_email and input_pw:
                        save_credentials(input_email, input_pw)
                        st.session_state["show_login_form"] = False
                        st.success("저장 완료!")
                        st.rerun()
                    else:
                        st.warning("이메일과 비밀번호를 모두 입력해주세요.")
                if del_btn:
                    clear_credentials()
                    st.session_state["show_login_form"] = False
                    st.info("계정 정보가 삭제됐습니다.")
                    st.rerun()

    st.divider()

    # ── 시나리오 생성 모드 선택 ───────────────────────────────────────────────
    st.markdown("**시나리오 생성 모드**")

    if IS_CLOUD:
        st.toggle("🌐 브라우저 모드 (API 없이)", value=False, disabled=True,
                  help="브라우저 모드는 로컬 PC 실행 전용입니다.")
        st.caption("☁️ Cloud 환경 — API 모드만 사용 가능")
        browser_mode = False
        st.session_state.browser_mode = False
    else:
        browser_mode = st.toggle(
            "🌐 브라우저 모드 (API 없이)",
            value=st.session_state.browser_mode,
            help="Chrome을 열어 Gemini 웹에 직접 입력합니다. API 할당량 없음.",
        )
        st.session_state.browser_mode = browser_mode
        if browser_mode:
            if not has_credentials():
                st.warning("⚠️ 위에서 Google 계정을 먼저 저장하세요.")
            else:
                st.info("Chrome이 열리면 자동으로 로그인됩니다.")

    st.divider()

    # 전체 실행 버튼
    run_all = st.button("🚀 전체 자동 생성", type="primary", use_container_width=True)

    st.divider()

    # API 상태
    api_ok = bool(settings.GOOGLE_AI_API_KEY)
    if browser_mode:
        st.markdown("🌐 브라우저 모드 활성")
    else:
        st.markdown(f"{'🟢' if api_ok else '🔴'} Google AI API")
        if not api_ok:
            st.error("API 키 없음\nApp settings → Secrets")

    # 진행 상태 요약
    st.divider()
    st.markdown("**진행 상태**")
    st.markdown(f"{'✅' if st.session_state.script else '⬜'} 시나리오")
    st.markdown(f"{'✅' if st.session_state.image_paths else '⬜'} 이미지")
    st.markdown(f"{'✅' if st.session_state.audio_paths else '⬜'} 음성")
    st.markdown(f"{'✅' if st.session_state.video_path else '⬜'} 영상")

    if st.button("🗑️ 초기화", use_container_width=True):
        for k in ["script", "image_paths", "audio_paths", "video_path"]:
            st.session_state[k] = None if k != "image_paths" and k != "audio_paths" else []
        st.rerun()

# ── 에러 표시 헬퍼 ───────────────────────────────────────────────────────────
def show_quota_error(e: Exception):
    msg = str(e)
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        st.error(
            "**API 할당량 초과 (429)**\n\n"
            "모든 모델(2.5→2.0→1.5-flash) 재시도 후에도 실패했습니다.\n\n"
            "**해결 방법:**\n"
            "1. 잠시 후 다시 시도 (분당 한도 초기화)\n"
            "2. 일일 한도 초기화: 매일 자정 PST (한국시간 오후 4시)\n"
            "3. [Google AI Studio](https://aistudio.google.com) → 결제 수단 등록으로 한도 해제"
        )
    else:
        st.error(f"오류: {e}")

# ── 페르소나 카드 렌더링 ──────────────────────────────────────────────────────
def persona_header(key: str):
    p = PERSONAS[key]
    st.markdown(
        f"""<div style="background:{p['bg']};border-left:4px solid {p['color']};
        padding:12px 16px;border-radius:8px;margin-bottom:12px">
        <span style="font-size:2rem">{p['emoji']}</span>
        <strong style="font-size:1.1rem;color:{p['color']}"> {p['name']}</strong>
        <span style="color:#666"> · {p['role']}</span><br>
        <span style="color:#888;font-size:0.9rem">{p['desc']}</span>
        </div>""",
        unsafe_allow_html=True,
    )

# ── 탭 레이아웃 ───────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(
    ["✍️ 극작가 제이", "🎨 화가 루나", "🎤 성우 아리", "🎬 편집장 맥스"]
)

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — 극작가 제이 (시나리오)
# ════════════════════════════════════════════════════════════════════════════
with tab1:
    persona_header("scenario")

    mode_label = "🌐 브라우저로 시나리오 생성" if st.session_state.browser_mode else "✍️ 시나리오 생성"
    if st.session_state.browser_mode:
        st.info("Chrome이 자동으로 열려 Gemini에 프롬프트를 입력합니다.")

    if st.button(mode_label, key="run_scenario", type="primary"):
        if not topic.strip():
            st.warning("사이드바에서 영상 주제를 입력해주세요.")
        else:
            ensure_output_dirs()
            status_box = st.empty()
            try:
                if st.session_state.browser_mode:
                    def _status(msg):
                        status_box.info(msg)

                    agent = BrowserScenarioAgent(status_fn=_status)
                    _status("🌐 Chrome 실행 중... (Gemini에 로그인되어 있어야 합니다)")
                    st.session_state.script = agent.generate_script(topic, num_scenes, style)
                else:
                    status_box.info("극작가 제이가 대본을 쓰고 있습니다...")
                    agent = ScenarioAgent()
                    st.session_state.script = agent.generate_script(topic, num_scenes, style)

                st.session_state.image_paths = []
                st.session_state.audio_paths = []
                st.session_state.video_path = None
                status_box.success("시나리오 완성!")
            except Exception as e:
                if st.session_state.browser_mode:
                    status_box.error(f"브라우저 오류: {e}")
                else:
                    status_box.empty()
                    show_quota_error(e)

    # 시나리오 표시 & 편집
    if st.session_state.script:
        script: ShortsScript = st.session_state.script
        st.markdown(f"### 📋 {script.title}")
        st.caption(f"총 길이: {script.total_duration:.0f}초 · {len(script.scenes)}장면")
        st.divider()

        edited_scenes = []
        for i, scene in enumerate(script.scenes):
            with st.expander(f"장면 {scene.scene_number}", expanded=True):
                col_a, col_b = st.columns(2)
                with col_a:
                    narration = st.text_area(
                        "💬 나레이션",
                        value=scene.narration,
                        key=f"narration_{i}",
                        height=100,
                    )
                with col_b:
                    img_prompt = st.text_area(
                        "🖼️ 이미지 프롬프트",
                        value=scene.image_prompt,
                        key=f"img_prompt_{i}",
                        height=100,
                    )
                edited_scenes.append(
                    SceneScript(
                        scene_number=scene.scene_number,
                        narration=narration,
                        image_prompt=img_prompt,
                        duration=scene.duration,
                    )
                )

        if st.button("💾 수정 내용 저장", key="save_script"):
            st.session_state.script = ShortsScript(
                title=script.title,
                topic=script.topic,
                total_duration=script.total_duration,
                scenes=edited_scenes,
            )
            st.session_state.image_paths = []
            st.session_state.audio_paths = []
            st.session_state.video_path = None
            st.success("저장됨! 이미지·음성·영상은 다시 생성해주세요.")
    else:
        st.info("주제를 입력하고 '시나리오 생성' 버튼을 눌러주세요.")

# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — 화가 루나 (이미지)
# ════════════════════════════════════════════════════════════════════════════
with tab2:
    persona_header("image")

    if not st.session_state.script:
        st.info("먼저 **극작가 제이**에서 시나리오를 생성해주세요.")
    else:
        script = st.session_state.script

        # 이미지 생성 모드 선택
        if IS_CLOUD:
            img_mode = "api"
            st.caption("☁️ Cloud 환경 — API 모드 (현재 Imagen API 오류 상태)")
        else:
            img_mode = st.radio(
                "이미지 생성 방법",
                ["🌐 브라우저 (Gemini 웹)", "⚙️ API (Imagen)"],
                horizontal=True,
                key="img_mode_radio",
            )
            img_mode = "browser" if "브라우저" in img_mode else "api"

        st.divider()

        # ── 전체 생성 버튼 ───────────────────────────────────────────────
        btn_label = "🌐 브라우저로 전체 이미지 생성" if img_mode == "browser" else "🎨 전체 이미지 생성 (API)"
        if st.button(btn_label, key="run_images", type="primary"):
            ensure_output_dirs()
            status_area = st.empty()
            prog = st.progress(0)

            if img_mode == "browser":
                status_area.info("🌐 Chrome 실행 중...")
                try:
                    def _img_status(msg):
                        status_area.info(msg)

                    agent = BrowserImageAgent(status_fn=_img_status)
                    prompts = [s.image_prompt for s in script.scenes]
                    scene_nums = [s.scene_number for s in script.scenes]
                    result_paths = agent.generate_all_images(prompts, scene_nums, _img_status)

                    st.session_state.image_paths = [str(p) for p in result_paths]
                    st.session_state.video_path = None

                    ok = len(result_paths)
                    total = len(script.scenes)
                    if ok == total:
                        status_area.success(f"✅ 전체 {ok}개 이미지 저장 완료!")
                    else:
                        status_area.warning(f"⚠️ {total}개 중 {ok}개 저장됨 (일부 실패)")

                except Exception as e:
                    status_area.error(f"브라우저 오류: {e}")

            else:
                # API 모드 (오류 시 장면별 표시, 나머지 계속 진행)
                paths = []
                errors = []
                try:
                    agent = ImageAgent()
                    for i, scene in enumerate(script.scenes):
                        status_area.info(f"🎨 장면 {scene.scene_number} 생성 중... ({i+1}/{len(script.scenes)})")
                        try:
                            p = agent.generate_image(scene.image_prompt, scene.scene_number)
                            paths.append(str(p))
                        except Exception as e:
                            errors.append(f"장면 {scene.scene_number}: {e}")
                            paths.append(None)
                        prog.progress((i + 1) / len(script.scenes))
                except Exception as e:
                    status_area.error(f"이미지 에이전트 초기화 오류: {e}")

                valid = [p for p in paths if p]
                st.session_state.image_paths = valid
                st.session_state.video_path = None

                if valid:
                    status_area.success(f"✅ {len(valid)}/{len(script.scenes)}개 완료")
                if errors:
                    with st.expander(f"⚠️ {len(errors)}개 장면 오류 (클릭해서 확인)"):
                        for err in errors:
                            st.error(err)
                        st.info("💡 Imagen API 오류가 계속되면 **브라우저 모드**로 전환하세요.")

        # ── 이미지 그리드 + 개별 재생성 ──────────────────────────────────
        if st.session_state.image_paths:
            st.divider()
            st.markdown(f"**생성된 이미지 ({len(st.session_state.image_paths)}개)**")
            cols = st.columns(min(len(script.scenes), 3))
            for i, scene in enumerate(script.scenes):
                with cols[i % 3]:
                    if i < len(st.session_state.image_paths):
                        img_path = st.session_state.image_paths[i]
                        if img_path and Path(img_path).exists():
                            st.image(img_path, caption=f"장면 {scene.scene_number}", use_container_width=True)
                        else:
                            st.warning(f"장면 {scene.scene_number} 이미지 없음")

                    custom_prompt = st.text_input(
                        "프롬프트 수정 후 재생성",
                        value=scene.image_prompt,
                        key=f"reprompt_{i}",
                        label_visibility="collapsed",
                    )
                    regen_mode = "browser" if (not IS_CLOUD and img_mode == "browser") else "api"
                    if st.button(f"🔄 재생성", key=f"regen_img_{i}"):
                        ensure_output_dirs()
                        with st.spinner(f"장면 {scene.scene_number} 재생성 중..."):
                            try:
                                if regen_mode == "browser":
                                    agent = BrowserImageAgent()
                                    p = agent.generate_one(custom_prompt, scene.scene_number)
                                else:
                                    agent = ImageAgent()
                                    p = agent.generate_image(custom_prompt, scene.scene_number)
                                cur = list(st.session_state.image_paths)
                                if i < len(cur):
                                    cur[i] = str(p)
                                else:
                                    cur.append(str(p))
                                st.session_state.image_paths = cur
                                st.session_state.video_path = None
                                st.rerun()
                            except Exception as e:
                                st.error(f"재생성 오류: {e}")

# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — 성우 아리 (TTS)
# ════════════════════════════════════════════════════════════════════════════
with tab3:
    persona_header("tts")

    if not st.session_state.script:
        st.info("먼저 **극작가 제이**에서 시나리오를 생성해주세요.")
    else:
        script = st.session_state.script

        if st.button("🎤 전체 음성 생성", key="run_tts", type="primary"):
            ensure_output_dirs()
            agent = TTSAgent()
            paths = []
            prog = st.progress(0)
            for i, scene in enumerate(script.scenes):
                with st.spinner(f"장면 {scene.scene_number} 녹음 중..."):
                    try:
                        p = agent.synthesize(scene.narration, scene.scene_number)
                        paths.append(str(p))
                    except Exception as e:
                        st.error(f"TTS 오류: {e}")
                        break
                prog.progress((i + 1) / len(script.scenes))
            if paths:
                st.session_state.audio_paths = paths
                st.session_state.video_path = None
                st.success(f"{len(paths)}개 음성 생성 완료!")

        # 음성 플레이어 + 개별 재녹음
        if st.session_state.audio_paths:
            st.divider()
            for i, scene in enumerate(script.scenes):
                with st.expander(f"장면 {scene.scene_number} — {scene.narration[:30]}...", expanded=False):
                    if i < len(st.session_state.audio_paths):
                        st.audio(st.session_state.audio_paths[i])

                    edit_text = st.text_area(
                        "나레이션 수정",
                        value=scene.narration,
                        key=f"tts_edit_{i}",
                        height=80,
                    )
                    if st.button("🔄 이 장면 재녹음", key=f"regen_tts_{i}"):
                        ensure_output_dirs()
                        with st.spinner("재녹음 중..."):
                            try:
                                agent = TTSAgent()
                                p = agent.synthesize(edit_text, scene.scene_number)
                                paths = list(st.session_state.audio_paths)
                                if i < len(paths):
                                    paths[i] = str(p)
                                else:
                                    paths.append(str(p))
                                st.session_state.audio_paths = paths
                                st.session_state.video_path = None
                                st.rerun()
                            except Exception as e:
                                st.error(f"TTS 오류: {e}")

# ════════════════════════════════════════════════════════════════════════════
# TAB 4 — 편집장 맥스 (영상)
# ════════════════════════════════════════════════════════════════════════════
with tab4:
    persona_header("video")

    has_images = bool(st.session_state.image_paths)
    has_audio = bool(st.session_state.audio_paths)

    if not st.session_state.script:
        st.info("시나리오가 없습니다. 극작가 제이부터 시작하세요.")
    elif not has_images:
        st.warning("이미지가 없습니다. 화가 루나에서 이미지를 생성해주세요.")
    elif not has_audio:
        st.warning("음성이 없습니다. 성우 아리에서 음성을 생성해주세요.")
    else:
        st.info(
            f"✅ 이미지 {len(st.session_state.image_paths)}개 · "
            f"음성 {len(st.session_state.audio_paths)}개 준비 완료"
        )

        if st.button("🎬 영상 합성", key="run_video", type="primary"):
            ensure_output_dirs()
            with st.spinner("편집장 맥스가 영상을 조립하고 있습니다..."):
                try:
                    agent = VideoAgent()
                    assets = GeneratedAssets(
                        script=st.session_state.script,
                        image_paths=st.session_state.image_paths,
                        audio_paths=st.session_state.audio_paths,
                    )
                    out = agent.synthesize(assets)
                    st.session_state.video_path = str(out)
                    st.success("영상 완성!")
                except Exception as e:
                    st.error(f"영상 합성 오류: {e}")

    if st.session_state.video_path and Path(st.session_state.video_path).exists():
        st.divider()
        st.subheader("🎥 완성된 영상")
        st.video(st.session_state.video_path)
        with open(st.session_state.video_path, "rb") as f:
            st.download_button(
                "⬇️ MP4 다운로드",
                data=f,
                file_name=Path(st.session_state.video_path).name,
                mime="video/mp4",
                use_container_width=True,
            )

# ════════════════════════════════════════════════════════════════════════════
# 전체 자동 생성
# ════════════════════════════════════════════════════════════════════════════
if run_all:
    if not topic.strip():
        st.warning("사이드바에서 영상 주제를 입력해주세요.")
    else:
        ensure_output_dirs()
        prog = st.progress(0)
        status = st.empty()

        try:
            status.info("✍️ 극작가 제이: 시나리오 작성 중...")
            prog.progress(5)
            st.session_state.script = ScenarioAgent().generate_script(topic, num_scenes, style)

            image_agent = ImageAgent()
            paths = []
            for i, scene in enumerate(st.session_state.script.scenes):
                status.info(f"🎨 화가 루나: 장면 {i+1}/{num_scenes} 그리는 중...")
                prog.progress(10 + int(35 * i / num_scenes))
                p = image_agent.generate_image(scene.image_prompt, scene.scene_number)
                paths.append(str(p))
            st.session_state.image_paths = paths

            tts_agent = TTSAgent()
            audio_paths = []
            for i, scene in enumerate(st.session_state.script.scenes):
                status.info(f"🎤 성우 아리: 장면 {i+1}/{num_scenes} 녹음 중...")
                prog.progress(50 + int(25 * i / num_scenes))
                p = tts_agent.synthesize(scene.narration, scene.scene_number)
                audio_paths.append(str(p))
            st.session_state.audio_paths = audio_paths

            status.info("🎬 편집장 맥스: 영상 합성 중...")
            prog.progress(80)
            assets = GeneratedAssets(
                script=st.session_state.script,
                image_paths=st.session_state.image_paths,
                audio_paths=st.session_state.audio_paths,
            )
            out = VideoAgent().synthesize(assets)
            st.session_state.video_path = str(out)

            prog.progress(100)
            status.success("✅ 전체 완성! '편집장 맥스' 탭에서 영상을 확인하세요.")

        except Exception as e:
            show_quota_error(e)
