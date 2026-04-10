"""
Selenium으로 Gemini 웹 UI를 자동화하여 시나리오 생성.
저장된 Google 계정으로 자동 로그인합니다.
"""
import json
import re
import time
import random
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
from app.utils.credentials import load_credentials

GEMINI_URL = "https://gemini.google.com/app"
GOOGLE_LOGIN_URL = "https://accounts.google.com/signin"

# 이 앱 전용 Chrome 프로필 (로그인 세션 저장)
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


def _human_type(el, text: str, delay: float = 0.07):
    """자동화 감지 우회를 위해 사람처럼 한 글자씩 입력"""
    for ch in text:
        el.send_keys(ch)
        time.sleep(delay + random.uniform(0, 0.05))


class BrowserScenarioAgent:
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
        # 자동화 감지 추가 우회
        opts.add_argument("--disable-extensions")
        opts.add_argument("--no-first-run")
        opts.add_argument("--disable-default-apps")
        if headless:
            opts.add_argument("--headless=new")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)

        # navigator.webdriver 속성 제거
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
        )
        return driver

    # ── 로그인 ───────────────────────────────────────────────────────────────
    def ensure_logged_in(self) -> bool:
        """
        Gemini 접속 → 로그인 여부 확인 → 필요 시 저장된 계정으로 자동 로그인.
        반환값: 로그인 성공 여부
        """
        self._status("🌐 Gemini 접속 중...")
        self.driver.get(GEMINI_URL)
        time.sleep(4)

        if "accounts.google.com" not in self.driver.current_url:
            self._status("✅ 이미 로그인되어 있습니다.")
            return True

        # 로그인 필요 → 저장된 자격증명 사용
        email, password = load_credentials()
        if not email or not password:
            raise RuntimeError(
                "로그인이 필요하지만 저장된 계정 정보가 없습니다.\n"
                "사이드바에서 Google 계정 이메일과 비밀번호를 입력 후 저장하세요."
            )

        self._status("🔑 Google 계정으로 자동 로그인 중...")
        return self._do_login(email, password)

    def _do_login(self, email: str, password: str) -> bool:
        driver = self.driver

        # ── 이메일 입력 ───────────────────────────────────────────────────
        try:
            email_el = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='email']"))
            )
        except TimeoutException:
            raise RuntimeError("Google 로그인 이메일 입력창을 찾지 못했습니다.")

        email_el.click()
        time.sleep(0.3)
        _human_type(email_el, email)
        time.sleep(0.5)

        # Next 클릭
        self._click_next(driver)
        time.sleep(2)

        # ── 비밀번호 입력 ─────────────────────────────────────────────────
        try:
            pw_el = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='password']"))
            )
        except TimeoutException:
            raise RuntimeError(
                "비밀번호 입력창을 찾지 못했습니다.\n"
                "2단계 인증(2FA)이 설정된 경우 Chrome 창에서 직접 완료해주세요."
            )

        pw_el.click()
        time.sleep(0.3)
        _human_type(pw_el, password)
        time.sleep(0.5)

        # Next 클릭
        self._click_next(driver)

        # ── 로그인 완료 대기 (최대 30초 — 2FA 등 대기) ───────────────────
        self._status("⏳ 로그인 완료 대기 중... (2FA가 있다면 Chrome에서 완료해주세요)")
        try:
            WebDriverWait(driver, 30).until(
                lambda d: "accounts.google.com" not in d.current_url
            )
        except TimeoutException:
            raise RuntimeError(
                "로그인 시간 초과.\n"
                "2FA가 설정된 경우 Chrome 창에서 인증을 완료해주세요.\n"
                "완료 후 다시 시도하면 세션이 유지됩니다."
            )

        # ── Gemini로 리다이렉트 ───────────────────────────────────────────
        if "gemini.google.com" not in driver.current_url:
            driver.get(GEMINI_URL)
            time.sleep(4)

        self._status("✅ 로그인 성공!")
        return True

    def _click_next(self, driver):
        """Next / 다음 버튼 클릭"""
        next_selectors = [
            "button[jsname='LgbsSe']",   # 구글 로그인 Next
            "div[jsname='Njthtb']",
            "#identifierNext",
            "#passwordNext",
            "button:has(span)",
        ]
        for sel in next_selectors:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, sel)
                btn.click()
                return
            except Exception:
                continue
        # fallback: Enter
        ActionChains(driver).send_keys(Keys.RETURN).perform()

    # ── is_logged_in (로그인 설정 버튼용) ────────────────────────────────────
    def is_logged_in(self) -> bool:
        self.driver.get(GEMINI_URL)
        time.sleep(4)
        return "accounts.google.com" not in self.driver.current_url

    # ── 시나리오 생성 ─────────────────────────────────────────────────────────
    def generate_script(self, topic: str, num_scenes: int = 5, style: str = "교육적") -> ShortsScript:
        prompt = _PROMPT_TEMPLATE.format(
            topic=topic, num_scenes=num_scenes, style=style,
            min_dur=num_scenes * 5, max_dur=num_scenes * 7,
        )
        try:
            self.ensure_logged_in()
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

    # ── 입력창 탐색 ───────────────────────────────────────────────────────────
    def _find_input(self):
        for sel in _INPUT_SELECTORS_CSS:
            try:
                return WebDriverWait(self.driver, 8).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
            except Exception:
                continue
        for xpath in _INPUT_SELECTORS_XPATH:
            try:
                return WebDriverWait(self.driver, 6).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
            except Exception:
                continue
        els = self.driver.find_elements(By.XPATH, "//*[@contenteditable='true']")
        if els:
            return els[0]
        raise RuntimeError(
            f"Gemini 입력창을 찾지 못했습니다.\n현재 URL: {self.driver.current_url}"
        )

    # ── 클립보드로 텍스트 입력 ────────────────────────────────────────────────
    def _type_prompt(self, el, prompt: str):
        pyperclip.copy(prompt)
        el.click()
        time.sleep(0.3)
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()
        time.sleep(0.2)
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL).perform()
        time.sleep(0.5)

    # ── 전송 버튼 ────────────────────────────────────────────────────────────
    def _submit(self, input_el):
        send_selectors = [
            "button[aria-label='Send message']",
            "button[aria-label='메시지 보내기']",
            "button[aria-label='Submit']",
            "button.send-button",
        ]
        for sel in send_selectors:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_enabled():
                    btn.click()
                    return
            except NoSuchElementException:
                continue
        input_el.send_keys(Keys.RETURN)

    # ── 응답 완료 대기 ────────────────────────────────────────────────────────
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

    # ── 응답 텍스트 추출 ──────────────────────────────────────────────────────
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

    # ── 전체 전송 흐름 ────────────────────────────────────────────────────────
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

    # ── JSON 파싱 ─────────────────────────────────────────────────────────────
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
