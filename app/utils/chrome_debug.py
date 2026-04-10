"""
기존 Chrome을 건드리지 않고, 별도 Chrome 창을 디버그 모드로 실행.
전용 프로필(~/.ai_shorts_chrome)을 사용하므로 기존 Chrome과 충돌 없음.
"""
import subprocess
import time
import socket
from pathlib import Path

DEBUG_PORT = 9222
CHROME_PROFILE_DIR = str(Path.home() / ".ai_shorts_chrome")

_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
]


def is_debug_port_open(port: int = DEBUG_PORT) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=1):
            return True
    except OSError:
        return False


def find_chrome_exe() -> str:
    for path in _CHROME_PATHS:
        if Path(path).exists():
            return path
    raise FileNotFoundError(
        "Chrome 실행 파일을 찾지 못했습니다.\n"
        "Chrome이 설치되어 있는지 확인하세요."
    )


def launch_chrome_with_debugging() -> bool:
    """
    기존 Chrome은 그대로 두고, 전용 프로필로 새 Chrome 창을 디버그 모드로 실행.
    처음 실행 시 구글 로그인 필요 (이후 세션 유지).
    """
    if is_debug_port_open():
        return True  # 이미 실행 중

    chrome_exe = find_chrome_exe()

    # 기존 Chrome과 완전히 별개의 프로세스로 실행
    subprocess.Popen(
        [
            chrome_exe,
            f"--remote-debugging-port={DEBUG_PORT}",
            f"--user-data-dir={CHROME_PROFILE_DIR}",
            "--no-first-run",
            "--disable-default-apps",
            "--no-sandbox",
            "https://gemini.google.com/app",
        ],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,  # 독립 프로세스
    )

    # 포트가 열릴 때까지 대기 (최대 15초)
    for _ in range(15):
        time.sleep(1)
        if is_debug_port_open():
            return True

    raise RuntimeError(
        "Chrome이 디버그 모드로 시작되지 않았습니다.\n"
        "잠시 후 다시 시도해주세요."
    )


def is_first_time() -> bool:
    """전용 프로필이 없으면 첫 실행 (로그인 필요)"""
    profile_path = Path(CHROME_PROFILE_DIR) / "Default" / "Cookies"
    return not profile_path.exists()
