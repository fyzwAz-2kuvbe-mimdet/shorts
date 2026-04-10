"""
현재 실행 중인 Chrome에 Remote Debugging으로 연결하는 유틸리티.
Chrome을 --remote-debugging-port=9222 옵션으로 재시작하는 기능 포함.
"""
import subprocess
import time
import socket
from pathlib import Path

DEBUG_PORT = 9222
# Windows 기본 Chrome 실행 경로 후보
_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
]
# 실제 Chrome 프로필 경로 (이미 로그인된 세션 사용)
REAL_PROFILE_DIR = str(Path.home() / r"AppData\Local\Google\Chrome\User Data")


def is_debug_port_open(port: int = DEBUG_PORT) -> bool:
    """Chrome 디버그 포트가 열려 있는지 확인"""
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


def launch_chrome_with_debugging() -> None:
    """
    실행 중인 Chrome을 종료하고 Remote Debugging 포트로 재시작.
    재시작 시 기존 Chrome 프로필(로그인 세션)을 그대로 사용.
    """
    # 기존 Chrome 종료
    subprocess.run(["taskkill", "/f", "/im", "chrome.exe"], capture_output=True)
    time.sleep(2)

    chrome_exe = find_chrome_exe()
    subprocess.Popen([
        chrome_exe,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={REAL_PROFILE_DIR}",
        "--no-first-run",
        "--disable-default-apps",
        "https://gemini.google.com/app",  # 바로 Gemini 열기
    ])
    # Chrome이 뜰 때까지 대기
    for _ in range(20):
        time.sleep(1)
        if is_debug_port_open():
            return
    raise RuntimeError(
        f"Chrome이 {DEBUG_PORT} 포트로 시작되지 않았습니다.\n"
        "수동으로 Chrome을 닫고 다시 시도해주세요."
    )
