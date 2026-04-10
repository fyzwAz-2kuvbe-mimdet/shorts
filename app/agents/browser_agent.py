"""
Selenium으로 Gemini 웹 UI를 자동화하여 시나리오 생성.
API 키 없이 로그인된 Chrome 브라우저를 통해 동작합니다.
"""
import json
import re
import time
import pyperclip
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

from app.core.models import ShortsScript, SceneScript

GEMINI_URL = "https://gemini.google.com/app"

# 이 앱 전용 Chrome 프로필 (로그인 정보 저장)
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

# ── 셀렉터: 여러 Gemini 버전 대응 ────────────────────────────────────────────
_INPUT_SELECTORS_CSS = [
    "div.ql-editor[contenteditable='true']",
    ".ql-editor[contenteditable='true']",
    "rich-textarea div[contenteditable='true']",
    "div[contenteditable='true'][data-placeholder]",
]
_INPUT_SELECTORS_XPATH = [
    "//div[@contenteditable='true' and contains(@class,'ql-editor')]",
    "//rich-textarea//div[@contenteditable='true']",
    "//div[@contenteditable='true']",
]

_RESPONSE_SELECTORS = [
    "model-response .markdown.markdown-main-panel",
    "model-response .markdown",
    ".model-response-text",
    "message-content .markdown",
    "model-response",
]


class BrowserScenarioAgent:
    """Selenium + Gemini 웹 UI 기반 시나리오 생성 에이전트"""

    def __init__(self, headless: bool = False, status_fn=None):
        self._status = status_fn or (lambda msg: None)
        self.driver = self._make_driver(headless)

    # ── 드라이버 생성 ─────────────────────────────────────────────────────────
    def _make_driver(self, headless: bool) -> webdriver.Chrome:
        opts = Options()
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
        self.driver.get(GEMINI_URL)
        time.sleep(4)
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

    # ── 내부: 입력창 탐색 ─────────────────────────────────────────────────────
    def _find_input(self) -> webdriver.remote.webelement.WebElement:
        # CSS 셀렉터 시도
        for sel in _INPUT_SELECTORS_CSS:
            try:
                el = WebDriverWait(self.driver, 6).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                return el
            except Exception:
                continue

        # XPath 시도
        for xpath in _INPUT_SELECTORS_XPATH:
            try:
                el = WebDriverWait(self.driver, 6).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                return el
            except Exception:
                continue

        # 최후: 페이지의 모든 contenteditable 중 첫 번째
        els = self.driver.find_elements(By.XPATH, "//*[@contenteditable='true']")
        if els:
            return els[0]

        raise RuntimeError(
            "Gemini 입력창을 찾지 못했습니다.\n"
            f"현재 URL: {self.driver.current_url}\n"
            "Chrome에서 Gemini가 정상적으로 열려 있는지 확인하세요."
        )

    # ── 내부: 텍스트 입력 (클립보드 붙여넣기) ────────────────────────────────
    def _type_prompt(self, el, prompt: str):
        """pyperclip → Ctrl+V 방식: contenteditable React 컴포넌트에 안정적"""
        pyperclip.copy(prompt)
        el.click()
        time.sleep(0.3)

        # 기존 내용 전체 선택 후 붙여넣기
        ActionChains(self.driver) \
            .key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL) \
            .perform()
        time.sleep(0.2)
        ActionChains(self.driver) \
            .key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL) \
            .perform()
        time.sleep(0.5)

    # ── 내부: 전송 버튼 클릭 또는 Enter ──────────────────────────────────────
    def _submit(self, input_el):
        # 전송 버튼 우선
        send_selectors = [
            "button[aria-label='Send message']",
            "button[aria-label='메시지 보내기']",
            "button[aria-label='Submit']",
            "button.send-button",
            "button[data-test-id='send-button']",
        ]
        for sel in send_selectors:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_enabled():
                    btn.click()
                    return
            except NoSuchElementException:
                continue

        # fallback: Shift+Enter 대신 Enter
        input_el.send_keys(Keys.RETURN)

    # ── 내부: 생성 완료 대기 ─────────────────────────────────────────────────
    def _wait_for_response(self):
        """Stop 버튼 소멸 또는 응답 텍스트 안정화로 완료 감지"""
        stop_selectors = [
            "button[aria-label='Stop generating']",
            "button[aria-label='생성 중지']",
            "button[aria-label='Stop']",
            "button[aria-label='Cancel']",
            "[data-test-id='stop-button']",
        ]

        self._status("⏳ Gemini 응답 생성 중... (30~60초 소요)")
        time.sleep(4)  # 생성 시작 여유

        # Stop 버튼이 나타날 때까지 대기
        stop_el = None
        for sel in stop_selectors:
            try:
                stop_el = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                break
            except Exception:
                continue

        if stop_el:
            # Stop 버튼이 사라질 때까지 대기 (최대 2분)
            try:
                WebDriverWait(self.driver, 120).until(EC.staleness_of(stop_el))
            except Exception:
                pass
        else:
            # Stop 버튼 못 찾으면 응답 텍스트 안정화 대기
            prev_text = ""
            for _ in range(30):
                time.sleep(3)
                curr = self._extract_latest_response()
                if curr and curr == prev_text:
                    break
                prev_text = curr

        time.sleep(2)

    # ── 내부: 최신 응답 추출 ─────────────────────────────────────────────────
    def _extract_latest_response(self) -> str:
        for sel in _RESPONSE_SELECTORS:
            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                text = els[-1].text.strip()
                if text:
                    return text

        # 코드 블록 직접 추출
        for sel in ["pre code", "pre", "code"]:
            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                text = els[-1].text.strip()
                if text:
                    return text

        return ""

    # ── 내부: 전체 프롬프트 전송 흐름 ────────────────────────────────────────
    def _send_prompt(self, prompt: str) -> str:
        # 1. Gemini 페이지 이동
        self._status("🌐 Gemini 페이지 열기...")
        self.driver.get(GEMINI_URL)
        time.sleep(5)

        # 2. 로그인 확인
        if "accounts.google.com" in self.driver.current_url:
            raise RuntimeError(
                "Google 로그인이 필요합니다.\n"
                "사이드바 '🔑 Chrome 로그인 설정'을 먼저 실행하세요."
            )

        # 3. 입력창 탐색
        self._status("⌨️ 입력창 탐색 중...")
        input_el = self._find_input()

        # 4. 텍스트 입력 (클립보드)
        self._status("📋 프롬프트 입력 중...")
        self._type_prompt(input_el, prompt)

        # 5. 전송
        self._submit(input_el)

        # 6. 완료 대기
        self._wait_for_response()

        # 7. 응답 추출
        self._status("📥 응답 추출 중...")
        text = self._extract_latest_response()
        if not text:
            raise RuntimeError(
                "Gemini 응답을 추출하지 못했습니다.\n"
                "Chrome 창에서 응답이 생성됐는지 직접 확인해주세요."
            )
        return text

    # ── 내부: JSON 파싱 ───────────────────────────────────────────────────────
    @staticmethod
    def _parse(text: str, topic: str) -> ShortsScript:
        # ```json ... ``` 블록 우선
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not match:
            match = re.search(r"(\{[\s\S]*\})", text)
        if not match:
            raise ValueError(
                f"응답에서 JSON을 찾을 수 없습니다.\n원문:\n{text[:500]}"
            )

        data = json.loads(match.group(1))
        scenes = [SceneScript(**s) for s in data["scenes"]]
        return ShortsScript(
            title=data["title"],
            topic=topic,
            total_duration=float(data["total_duration"]),
            scenes=scenes,
        )
