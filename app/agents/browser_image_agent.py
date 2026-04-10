"""
Selenium으로 Gemini 웹 UI에서 이미지를 생성하고 저장합니다.
gemini.google.com 채팅에서 이미지 생성 요청 → 생성된 이미지 다운로드.
"""
import re
import time
import urllib.request
from pathlib import Path

import pyperclip
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from app.agents.browser_agent import BrowserScenarioAgent, GEMINI_URL
from app.utils.file_utils import get_image_path

_IMAGE_PROMPT_TEMPLATE = (
    "Create an image: {prompt}. "
    "Style: cinematic, vertical 9:16 format, high quality, vivid colors."
)

# Gemini 응답 내 이미지 셀렉터
_IMG_SELECTORS = [
    "model-response img[src*='blob']",
    "model-response img[src^='data:image']",
    "model-response img[src*='googleusercontent']",
    "message-content img",
    ".response-image-container img",
    "img[jsname]",
    "model-response img",
]

# 생성 완료 감지: 이미지가 응답에 등장했는지 확인
_STOP_BTN_SELECTORS = [
    "button[aria-label='Stop generating']",
    "button[aria-label='생성 중지']",
    "button[aria-label='Stop']",
    "[data-test-id='stop-button']",
]


class BrowserImageAgent(BrowserScenarioAgent):
    """Gemini 웹 채팅으로 이미지 생성 후 PNG로 저장"""

    def generate_all_images(
        self,
        prompts: list[str],
        scene_numbers: list[int],
        status_fn=None,
    ) -> list[Path]:
        """모든 장면 이미지를 순서대로 생성 후 경로 리스트 반환"""
        _status = status_fn or self._status
        saved_paths: list[Path] = []

        try:
            # 1. Gemini 페이지 이동 (한 번만)
            _status("🌐 Gemini 페이지 열기...")
            self.driver.get(GEMINI_URL)
            time.sleep(5)

            if "accounts.google.com" in self.driver.current_url:
                raise RuntimeError(
                    "Google 로그인이 필요합니다.\n"
                    "사이드바 '🔑 Chrome 로그인 설정'을 먼저 실행하세요."
                )

            for idx, (prompt, scene_num) in enumerate(zip(prompts, scene_numbers)):
                _status(f"🎨 장면 {scene_num} 이미지 생성 중... ({idx+1}/{len(prompts)})")
                out_path = get_image_path(scene_num)

                try:
                    img_path = self._generate_one_image(prompt, out_path, idx)
                    saved_paths.append(img_path)
                    _status(f"✅ 장면 {scene_num} 저장 완료")
                except Exception as e:
                    _status(f"⚠️ 장면 {scene_num} 실패: {e}")
                    # 실패해도 나머지 계속 진행
                    saved_paths.append(None)

                # 장면 간 딜레이 (연속 요청 방지)
                if idx < len(prompts) - 1:
                    time.sleep(3)

        finally:
            self.driver.quit()

        # None 제거 후 반환
        return [p for p in saved_paths if p is not None]

    def generate_one(self, prompt: str, scene_number: int) -> Path:
        """단일 이미지 생성 (개별 재생성용)"""
        try:
            self.driver.get(GEMINI_URL)
            time.sleep(5)
            if "accounts.google.com" in self.driver.current_url:
                raise RuntimeError("Google 로그인이 필요합니다.")
            out_path = get_image_path(scene_number)
            return self._generate_one_image(prompt, out_path, scene_number)
        finally:
            self.driver.quit()

    # ── 내부: 단일 이미지 생성 ────────────────────────────────────────────────
    def _generate_one_image(self, prompt: str, out_path: Path, seq: int) -> Path:
        full_prompt = _IMAGE_PROMPT_TEMPLATE.format(prompt=prompt)

        # 입력창 탐색
        input_el = self._find_input()

        # 클립보드로 입력
        pyperclip.copy(full_prompt)
        input_el.click()
        time.sleep(0.3)
        ActionChains(self.driver) \
            .key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL) \
            .perform()
        time.sleep(0.2)
        ActionChains(self.driver) \
            .key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL) \
            .perform()
        time.sleep(0.5)

        # 전송
        self._submit(input_el)

        # 이미지 생성 완료 대기
        img_el = self._wait_for_image(timeout=90)

        # 이미지 저장
        return self._save_image(img_el, out_path)

    # ── 내부: 이미지 요소 대기 ────────────────────────────────────────────────
    def _wait_for_image(self, timeout: int = 90):
        """응답에 이미지 요소가 나타날 때까지 대기"""
        time.sleep(4)

        # Stop 버튼 소멸 대기
        stop_el = None
        for sel in _STOP_BTN_SELECTORS:
            try:
                stop_el = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                break
            except Exception:
                continue

        if stop_el:
            try:
                WebDriverWait(self.driver, timeout).until(EC.staleness_of(stop_el))
            except Exception:
                pass

        time.sleep(2)

        # 이미지 요소 탐색
        for sel in _IMG_SELECTORS:
            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                # 가장 마지막(최신) 이미지
                return els[-1]

        raise RuntimeError(
            "Gemini가 이미지를 생성하지 못했습니다.\n"
            "Gemini에서 이미지 생성이 지원되는 계정인지 확인하세요.\n"
            "(Google One AI Premium 또는 Workspace 계정 필요)"
        )

    # ── 내부: 이미지 저장 ────────────────────────────────────────────────────
    def _save_image(self, img_el, out_path: Path) -> Path:
        src = img_el.get_attribute("src") or ""

        if src.startswith("data:image"):
            # base64 인코딩된 이미지
            import base64
            header, data = src.split(",", 1)
            out_path.write_bytes(base64.b64decode(data))

        elif src.startswith("blob:"):
            # blob URL → JavaScript로 ArrayBuffer 추출
            script = """
            async function getBlob(url) {
                const r = await fetch(url);
                const buf = await r.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }
            return await getBlob(arguments[0]);
            """
            byte_list = self.driver.execute_async_script(
                "var cb=arguments[arguments.length-1];"
                "fetch(arguments[0]).then(r=>r.arrayBuffer())"
                ".then(b=>cb(Array.from(new Uint8Array(b))));",
                src,
            )
            out_path.write_bytes(bytes(byte_list))

        elif src.startswith("http"):
            # 외부 URL → 쿠키 포함 다운로드
            cookies = {
                c["name"]: c["value"]
                for c in self.driver.get_cookies()
            }
            import requests
            resp = requests.get(src, cookies=cookies, timeout=30)
            resp.raise_for_status()
            out_path.write_bytes(resp.content)

        else:
            raise RuntimeError(f"알 수 없는 이미지 src 형식: {src[:80]}")

        return out_path
