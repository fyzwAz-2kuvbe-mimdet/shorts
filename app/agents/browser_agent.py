"""
현재 실행 중인 Chrome(Remote Debugging)에 연결하여 Gemini 웹 자동화.
- Chrome은 미리 열려 있고 로그인된 상태여야 함
- 새 탭을 열어 Gemini 접속 → 로그인 없이 바로 사용
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
from app.utils.chrome_debug import DEBUG_PORT, is_debug_port_open

GEMINI_URL = "https://gemini.google.com/app"

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

_INPUT_SELECTORS_CSS = [
    "div.ql-editor[contenteditable='true']",
    ".ql-editor[contenteditable='true']",
    "rich-textarea div[contenteditable='true']",
    "div[contenteditable='true'][data-placeholder]",
    "p[data-placeholder]",
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
_MODEL_BTN_SELECTORS = [
    "button[data-test-id='bard-mode-menu-button']",
    "bard-mode-switcher button",
    ".model-switcher button",
    "button[aria-label*='Gemini']",
    "button[aria-label*='모델']",
    "model-switcher",
]
_PRO_OPTION_XPATHS = [
    "//*[contains(text(),'2.5 Pro')]",
    "//*[contains(text(),'Gemini 2.5 Pro')]",
    "//mat-option[contains(.,'Pro')]",
    "//li[contains(.,'Pro')]",
    "//*[contains(@class,'model-option') and contains(.,'Pro')]",
]


class BrowserScenarioAgent:
    def __init__(self, headless: bool = False, status_fn=None):
        self._status = status_fn or (lambda msg: None)
        self.driver = self._make_driver(headless)

    # ── 드라이버: 기존 Chrome에 연결 ─────────────────────────────────────────
    def _make_driver(self, headless: bool) -> webdriver.Chrome:
        if not is_debug_port_open():
            raise RuntimeError(
                f"Chrome 디버그 포트({DEBUG_PORT})가 열려 있지 않습니다.\n"
                "사이드바의 '🔌 Chrome 연결 준비' 버튼을 먼저 클릭하세요."
            )

        opts = Options()
        opts.add_experimental_option("debuggerAddress", f"localhost:{DEBUG_PORT}")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        self._status("✅ 기존 Chrome에 연결됨")
        return driver

    # ── 새 탭으로 Gemini 접속 ────────────────────────────────────────────────
    def ensure_logged_in(self) -> bool:
        """기존 Chrome의 새 탭에서 Gemini 접속 — 이미 로그인된 세션 사용"""
        self._status("🌐 새 탭에서 Gemini 접속 중...")

        # 새 탭 열기
        self.driver.execute_script("window.open('');")
        time.sleep(0.5)
        self.driver.switch_to.window(self.driver.window_handles[-1])

        # Gemini 이동
        self.driver.get(GEMINI_URL)
        self._status("⏳ Gemini 페이지 로딩 대기 중...")

        # 1단계: 로그인 리다이렉트 여부 확인 (최대 10초)
        try:
            WebDriverWait(self.driver, 10).until(
                lambda d: d.current_url != "about:blank"
            )
        except Exception:
            pass

        if "accounts.google.com" in self.driver.current_url:
            raise RuntimeError(
                "Gemini에 로그인되어 있지 않습니다.\n"
                "Chrome에서 gemini.google.com 에 로그인 후 다시 시도하세요."
            )

        # 2단계: Gemini 입력창이 실제로 나타날 때까지 대기 (최대 20초)
        self._status("⏳ Gemini 입력창 로딩 대기 중...")
        input_ready = False
        for sel in _INPUT_SELECTORS_CSS + ["//*[@contenteditable='true']"]:
            try:
                by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((by, sel))
                )
                input_ready = True
                break
            except Exception:
                continue

        if not input_ready:
            # 그래도 없으면 추가 5초 대기 후 진행
            self._status("⚠️ 입력창 감지 실패 — 5초 추가 대기 후 진행")
            time.sleep(5)

        self._status("✅ Gemini 접속 완료")
        return True

    # ── Pro 모드 선택 ─────────────────────────────────────────────────────────
    def select_pro_mode(self) -> bool:
        self._status("⚙️ Gemini 2.5 Pro 모드 선택 중...")
        driver = self.driver

        for sel in _MODEL_BTN_SELECTORS:
            try:
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                btn.click()
                time.sleep(1.5)
                break
            except Exception:
                continue

        for xpath in _PRO_OPTION_XPATHS:
            try:
                opt = WebDriverWait(driver, 4).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                opt.click()
                time.sleep(1)
                self._status("✅ Pro 모드 선택 완료!")
                return True
            except Exception:
                continue

        self._status("⚠️ Pro 모드 자동 선택 실패 — 기본 모드로 계속 진행")
        return False

    # ── 탭 닫기 (드라이버는 유지) ─────────────────────────────────────────────
    def close_tab(self):
        """작업이 끝난 탭만 닫고 Chrome은 그대로 유지"""
        try:
            if len(self.driver.window_handles) > 1:
                self.driver.close()
                self.driver.switch_to.window(self.driver.window_handles[-1])
        except Exception:
            pass

    def close(self):
        """Chrome 자체는 닫지 않음 — 탭만 정리"""
        self.close_tab()

    # ── 시나리오 생성 ─────────────────────────────────────────────────────────
    def generate_script(self, topic: str, num_scenes: int = 5, style: str = "교육적") -> ShortsScript:
        prompt = _PROMPT_TEMPLATE.format(
            topic=topic, num_scenes=num_scenes, style=style,
            min_dur=num_scenes * 5, max_dur=num_scenes * 7,
        )
        try:
            self.ensure_logged_in()
            self.select_pro_mode()
            raw = self._send_prompt(prompt)
            self._status("📄 응답 파싱 중...")
            return self._parse(raw, topic)
        finally:
            self.close_tab()

    # ── 입력창 탐색 ───────────────────────────────────────────────────────────
    def _find_input(self):
        self._status("⌨️ 입력창 탐색 중...")

        # CSS 셀렉터 시도 (타임아웃 15초)
        for sel in _INPUT_SELECTORS_CSS:
            try:
                el = WebDriverWait(self.driver, 15).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                self._status(f"✅ 입력창 발견 (CSS: {sel[:40]})")
                return el
            except Exception:
                continue

        # XPath 시도 (타임아웃 10초)
        for xpath in _INPUT_SELECTORS_XPATH:
            try:
                el = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                self._status("✅ 입력창 발견 (XPath)")
                return el
            except Exception:
                continue

        # 마지막 수단: 페이지 내 모든 contenteditable
        els = self.driver.find_elements(By.XPATH, "//*[@contenteditable='true']")
        if els:
            self._status(f"✅ 입력창 발견 (contenteditable fallback, {len(els)}개 중 첫 번째)")
            return els[0]

        # 디버그 정보 수집
        page_title = self.driver.title
        current_url = self.driver.current_url
        all_inputs = self.driver.find_elements(By.TAG_NAME, "input")
        all_textareas = self.driver.find_elements(By.TAG_NAME, "textarea")
        raise RuntimeError(
            f"Gemini 입력창을 찾지 못했습니다.\n"
            f"URL: {current_url}\n"
            f"Title: {page_title}\n"
            f"input 요소: {len(all_inputs)}개, textarea 요소: {len(all_textareas)}개\n"
            "Chrome에서 Gemini 페이지가 완전히 로딩됐는지 확인하세요."
        )

    def _type_prompt(self, el, prompt: str):
        pyperclip.copy(prompt)
        el.click()
        time.sleep(0.3)
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()
        time.sleep(0.2)
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL).perform()
        time.sleep(0.5)

    def _submit(self, input_el):
        for sel in [
            "button[aria-label='Send message']",
            "button[aria-label='메시지 보내기']",
            "button[aria-label='Submit']",
            "button.send-button",
        ]:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_enabled():
                    btn.click()
                    return
            except NoSuchElementException:
                continue
        input_el.send_keys(Keys.RETURN)

    def _wait_for_response(self):
        stop_selectors = [
            "button[aria-label='Stop generating']",
            "button[aria-label='생성 중지']",
            "button[aria-label='Stop']",
        ]
        self._status("⏳ Gemini 응답 생성 중...")
        time.sleep(4)
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
            try:
                WebDriverWait(self.driver, 120).until(EC.staleness_of(stop_el))
            except Exception:
                pass
        else:
            prev = ""
            for _ in range(30):
                time.sleep(3)
                curr = self._extract_latest_response()
                if curr and curr == prev:
                    break
                prev = curr
        time.sleep(2)

    def _extract_latest_response(self) -> str:
        for sel in _RESPONSE_SELECTORS:
            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                text = els[-1].text.strip()
                if text:
                    return text
        for sel in ["pre code", "pre", "code"]:
            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                text = els[-1].text.strip()
                if text:
                    return text
        return ""

    def _send_prompt(self, prompt: str) -> str:
        self._status("⌨️ 입력창 탐색 중...")
        input_el = self._find_input()
        self._status("📋 프롬프트 입력 중...")
        self._type_prompt(input_el, prompt)
        self._submit(input_el)
        self._wait_for_response()
        self._status("📥 응답 추출 중...")
        text = self._extract_latest_response()
        if not text:
            raise RuntimeError("Gemini 응답을 추출하지 못했습니다.")
        return text

    @staticmethod
    def _parse(text: str, topic: str) -> ShortsScript:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not match:
            match = re.search(r"(\{[\s\S]*\})", text)
        if not match:
            raise ValueError(f"응답에서 JSON을 찾을 수 없습니다.\n{text[:500]}")
        data = json.loads(match.group(1))
        scenes = [SceneScript(**s) for s in data["scenes"]]
        return ShortsScript(
            title=data["title"], topic=topic,
            total_duration=float(data["total_duration"]), scenes=scenes,
        )
