"""
Selenium으로 Gemini 웹 UI를 자동화하여 시나리오 생성.
API 키 없이 로그인된 Chrome 브라우저를 통해 동작합니다.
"""
import json
import re
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

from app.core.models import ShortsScript, SceneScript

GEMINI_URL = "https://gemini.google.com/app"

# 이 앱 전용 Chrome 프로필 (로그인 정보 저장 — 사용자 기본 Chrome과 충돌 없음)
CHROME_PROFILE_DIR = str(Path.home() / ".ai_shorts_chrome")

_PROMPT_TEMPLATE = """\
아래 조건에 맞는 숏츠 시나리오를 작성하고, JSON 형식으로만 응답해주세요.
JSON 외의 설명이나 텍스트는 절대 포함하지 마세요.

조건:
- 주제: {topic}
- 장면 수: {num_scenes}개
- 스타일: {style}
- 목표 길이: {min_dur}~{max_dur}초

응답 형식 (이 JSON만 출력):
{{
  "title": "영상 제목",
  "total_duration": 전체길이(숫자),
  "scenes": [
    {{
      "scene_number": 1,
      "narration": "한국어 나레이션 1~2문장",
      "image_prompt": "Detailed English image prompt, cinematic, 9:16 vertical",
      "duration": 장면길이(숫자)
    }}
  ]
}}"""

# ── Gemini 웹 CSS 셀렉터 (여러 버전 대응) ─────────────────────────────────────
_INPUT_SELECTORS = [
    "rich-textarea .ql-editor",
    "rich-textarea [contenteditable='true']",
    "[data-placeholder] [contenteditable='true']",
    "div[contenteditable='true']",
]
_STOP_BTN_SELECTORS = [
    "button[aria-label='Stop generating']",
    "button[aria-label='생성 중지']",
    "button[aria-label='Stop']",
    ".stop-button",
    "button svg[data-icon='stop']",
]
_RESPONSE_SELECTORS = [
    "model-response .markdown.markdown-main-panel",
    "model-response .markdown",
    "model-response",
    ".response-content",
    "message-content",
]


class BrowserScenarioAgent:
    """Selenium + Gemini 웹 UI 기반 시나리오 생성 에이전트"""

    def __init__(self, headless: bool = False, status_fn=None):
        """
        status_fn: 진행 상태를 전달받는 콜백 (str) → 선택
        """
        self._status = status_fn or (lambda msg: None)
        self.driver = self._make_driver(headless)

    # ── 드라이버 생성 ─────────────────────────────────────────────────────────
    def _make_driver(self, headless: bool) -> webdriver.Chrome:
        opts = Options()
        # 전용 프로필: 로그인 세션을 저장하므로 매번 로그인 불필요
        opts.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
        opts.add_argument("--profile-directory=Default")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument("--start-maximized")
        if headless:
            opts.add_argument("--headless=new")

        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=opts)

    # ── 공개 메서드 ───────────────────────────────────────────────────────────
    def is_logged_in(self) -> bool:
        """Gemini 로그인 여부 확인 (드라이버는 열린 상태 유지)"""
        self.driver.get(GEMINI_URL)
        time.sleep(3)
        return "accounts.google.com" not in self.driver.current_url

    def generate_script(
        self,
        topic: str,
        num_scenes: int = 5,
        style: str = "교육적",
    ) -> ShortsScript:
        prompt = _PROMPT_TEMPLATE.format(
            topic=topic,
            num_scenes=num_scenes,
            style=style,
            min_dur=num_scenes * 5,
            max_dur=num_scenes * 7,
        )
        try:
            self._status("🌐 Gemini 페이지 열기...")
            raw = self._send_prompt(prompt)
            self._status("📄 응답 파싱 중...")
            return self._parse(raw, topic)
        finally:
            self.driver.quit()

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass

    # ── 내부: 프롬프트 전송 & 응답 수집 ──────────────────────────────────────
    def _send_prompt(self, prompt: str) -> str:
        wait = WebDriverWait(self.driver, 40)

        # ── 로그인 확인 ───────────────────────────────────────────────────
        if "accounts.google.com" in self.driver.current_url:
            raise RuntimeError(
                "Google 로그인이 필요합니다.\n"
                "사이드바 '🔑 Chrome 로그인 설정'을 먼저 실행하세요."
            )

        # ── 입력창 탐색 ───────────────────────────────────────────────────
        self._status("⌨️ 입력창 탐색 중...")
        input_el = None
        for sel in _INPUT_SELECTORS:
            try:
                input_el = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                break
            except TimeoutException:
                continue

        if input_el is None:
            raise RuntimeError(
                "Gemini 입력창을 찾지 못했습니다.\n"
                "Chrome이 Gemini 페이지를 올바르게 열었는지 확인하세요."
            )

        # ── 프롬프트 붙여넣기 (클립보드 경유 — 개행 보존) ─────────────────
        self._status("📋 프롬프트 입력 중...")
        input_el.click()
        time.sleep(0.3)

        # JavaScript로 텍스트 설정 (가장 안정적)
        self.driver.execute_script(
            "arguments[0].textContent = arguments[1];"
            "arguments[0].dispatchEvent(new InputEvent('input', {bubbles:true}));",
            input_el,
            prompt,
        )
        time.sleep(0.5)

        # Enter로 전송
        input_el.send_keys(Keys.RETURN)
        self._status("⏳ Gemini 응답 대기 중...")

        # ── 생성 완료 대기 ────────────────────────────────────────────────
        time.sleep(3)  # 생성 시작 여유

        # Stop 버튼 나타나면 → 사라질 때까지 대기
        stop_found = False
        for sel in _STOP_BTN_SELECTORS:
            try:
                stop_btn = WebDriverWait(self.driver, 8).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                WebDriverWait(self.driver, 120).until(EC.staleness_of(stop_btn))
                stop_found = True
                break
            except Exception:
                continue

        if not stop_found:
            # fallback: 단순 대기
            time.sleep(20)

        time.sleep(2)  # 렌더링 여유

        # ── 응답 텍스트 추출 ──────────────────────────────────────────────
        self._status("📥 응답 추출 중...")
        for sel in _RESPONSE_SELECTORS:
            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                text = els[-1].text.strip()
                if text:
                    return text

        # 최후 수단: 코드 블록
        for sel in ["pre", "code"]:
            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                return els[-1].text.strip()

        raise RuntimeError(
            "Gemini 응답을 추출하지 못했습니다.\n"
            "Gemini 창을 확인하고 다시 시도해주세요."
        )

    # ── 내부: JSON 파싱 ───────────────────────────────────────────────────────
    @staticmethod
    def _parse(text: str, topic: str) -> ShortsScript:
        # ```json ... ``` 블록 우선 추출
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not match:
            # 날 JSON 탐색
            match = re.search(r"(\{[\s\S]*\})", text)
        if not match:
            raise ValueError(
                f"응답에서 JSON을 찾을 수 없습니다.\n원문 일부:\n{text[:400]}"
            )

        data = json.loads(match.group(1))
        scenes = [SceneScript(**s) for s in data["scenes"]]
        return ShortsScript(
            title=data["title"],
            topic=topic,
            total_duration=float(data["total_duration"]),
            scenes=scenes,
        )
