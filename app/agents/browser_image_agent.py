"""
Selenium으로 Gemini 웹에서 이미지 생성 (Imagen 2 기반).
- Pro 모드 선택
- 스타일 참조 이미지 첨부 지원
- 생성된 이미지 자동 저장
"""
import base64
import time
from pathlib import Path
from typing import Optional

import pyperclip
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from app.agents.browser_agent import BrowserScenarioAgent, GEMINI_URL
from app.utils.file_utils import get_image_path

# 스타일 참조 이미지가 있을 때 프롬프트
_IMG_PROMPT_WITH_REF = (
    "Generate an image in the EXACT same visual style as the attached reference photo. "
    "Scene: {prompt}. "
    "Keep the same color palette, lighting mood, and artistic style as the reference. "
    "Vertical 9:16 format, high quality."
)

# 스타일 참조 이미지가 없을 때 프롬프트
_IMG_PROMPT_NO_REF = (
    "Generate an image: {prompt}. "
    "Style: cinematic, high quality, vivid colors, vertical 9:16 format."
)

_IMG_SELECTORS = [
    "model-response img[src*='blob']",
    "model-response img[src^='data:image']",
    "model-response img[src*='googleusercontent']",
    "message-content img",
    ".response-image-container img",
    "model-response img",
]
_STOP_BTN_SELECTORS = [
    "button[aria-label='Stop generating']",
    "button[aria-label='생성 중지']",
    "button[aria-label='Stop']",
    "[data-test-id='stop-button']",
]

# 파일 첨부 버튼 셀렉터
_ATTACH_BTN_SELECTORS = [
    "button[aria-label='Add image']",
    "button[aria-label='이미지 추가']",
    "button[aria-label='Attach']",
    "button[aria-label='첨부']",
    "button[aria-label='Upload file']",
    "input[type='file']",
    ".upload-button",
    "button[data-test-id='attach-button']",
]


class BrowserImageAgent(BrowserScenarioAgent):
    """Gemini 웹으로 이미지 생성 + 스타일 참조 이미지 첨부"""

    def generate_all_images(
        self,
        prompts: list[str],
        scene_numbers: list[int],
        style_ref_path: Optional[str] = None,
        status_fn=None,
    ) -> list[Path]:
        """모든 장면 이미지를 순서대로 생성"""
        _status = status_fn or self._status
        saved_paths: list[Path] = []

        try:
            self._status = _status

            # 1. 로그인 + Pro 모드
            self.ensure_logged_in()
            self.select_pro_mode()

            for idx, (prompt, scene_num) in enumerate(zip(prompts, scene_numbers)):
                _status(f"🎨 장면 {scene_num} 이미지 생성 중... ({idx+1}/{len(prompts)})")
                out_path = get_image_path(scene_num)

                try:
                    # 첫 번째 장면에만 스타일 참조 이미지 첨부
                    # (이후 장면은 같은 대화 컨텍스트에서 스타일 유지됨)
                    attach_ref = style_ref_path if idx == 0 else None
                    img_path = self._generate_one_image(prompt, out_path, style_ref_path=attach_ref)
                    saved_paths.append(img_path)
                    _status(f"✅ 장면 {scene_num} 저장 완료")
                except Exception as e:
                    _status(f"⚠️ 장면 {scene_num} 실패: {e}")
                    saved_paths.append(None)

                if idx < len(prompts) - 1:
                    time.sleep(3)

        finally:
            self.driver.quit()

        return [p for p in saved_paths if p is not None]

    def generate_one(
        self,
        prompt: str,
        scene_number: int,
        style_ref_path: Optional[str] = None,
    ) -> Path:
        """단일 이미지 생성 (개별 재생성용)"""
        try:
            self.ensure_logged_in()
            self.select_pro_mode()
            out_path = get_image_path(scene_number)
            return self._generate_one_image(prompt, out_path, style_ref_path=style_ref_path)
        finally:
            self.driver.quit()

    # ── 단일 이미지 생성 ──────────────────────────────────────────────────────
    def _generate_one_image(
        self,
        prompt: str,
        out_path: Path,
        style_ref_path: Optional[str] = None,
    ) -> Path:
        driver = self.driver

        # 스타일 참조 이미지 첨부
        if style_ref_path and Path(style_ref_path).exists():
            self._status("📎 스타일 참조 이미지 첨부 중...")
            self._attach_image_file(style_ref_path)
            full_prompt = _IMG_PROMPT_WITH_REF.format(prompt=prompt)
        else:
            full_prompt = _IMG_PROMPT_NO_REF.format(prompt=prompt)

        # 입력창 탐색 + 텍스트 입력
        input_el = self._find_input()
        self._type_prompt(input_el, full_prompt)
        self._submit(input_el)

        # 이미지 생성 완료 대기
        img_el = self._wait_for_image(timeout=120)

        # 이미지 저장
        return self._save_image(img_el, out_path)

    # ── 파일 첨부 ────────────────────────────────────────────────────────────
    def _attach_image_file(self, file_path: str):
        """Gemini 채팅에 이미지 파일 첨부"""
        abs_path = str(Path(file_path).resolve())
        driver = self.driver

        # 숨겨진 file input이 있으면 직접 경로 주입 (가장 안정적)
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        if file_inputs:
            try:
                driver.execute_script(
                    "arguments[0].style.display='block'; arguments[0].style.opacity='1';",
                    file_inputs[0],
                )
                file_inputs[0].send_keys(abs_path)
                time.sleep(2)
                return
            except Exception:
                pass

        # 첨부 버튼 클릭 후 파일 선택
        for sel in _ATTACH_BTN_SELECTORS:
            if sel == "input[type='file']":
                continue
            try:
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                btn.click()
                time.sleep(1.5)

                # 클릭 후 나타나는 file input
                file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                if file_inputs:
                    file_inputs[-1].send_keys(abs_path)
                    time.sleep(2)
                    return
            except Exception:
                continue

        # 첨부 버튼을 못 찾으면 경고만 (생성은 계속)
        self._status("⚠️ 파일 첨부 버튼을 찾지 못했습니다. 스타일 참조 없이 생성합니다.")

    # ── 이미지 응답 대기 ──────────────────────────────────────────────────────
    def _wait_for_image(self, timeout: int = 120):
        time.sleep(5)

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

        time.sleep(3)

        for sel in _IMG_SELECTORS:
            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                return els[-1]

        raise RuntimeError(
            "Gemini가 이미지를 생성하지 못했습니다.\n"
            "Google One AI Premium 계정에서 이미지 생성이 지원됩니다."
        )

    # ── 이미지 저장 (blob / base64 / http) ────────────────────────────────────
    def _save_image(self, img_el, out_path: Path) -> Path:
        src = img_el.get_attribute("src") or ""

        if src.startswith("data:image"):
            _, data = src.split(",", 1)
            out_path.write_bytes(base64.b64decode(data))

        elif src.startswith("blob:"):
            byte_list = self.driver.execute_async_script(
                "var cb=arguments[arguments.length-1];"
                "fetch(arguments[0]).then(r=>r.arrayBuffer())"
                ".then(b=>cb(Array.from(new Uint8Array(b))));",
                src,
            )
            out_path.write_bytes(bytes(byte_list))

        elif src.startswith("http"):
            cookies = {c["name"]: c["value"] for c in self.driver.get_cookies()}
            resp = requests.get(src, cookies=cookies, timeout=30)
            resp.raise_for_status()
            out_path.write_bytes(resp.content)

        else:
            raise RuntimeError(f"알 수 없는 이미지 src: {src[:80]}")

        return out_path
