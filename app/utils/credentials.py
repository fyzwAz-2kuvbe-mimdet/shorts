"""
Google 계정 자격증명을 OS 키체인(Windows Credential Manager)에 저장/불러오기.
코드나 파일에 평문으로 저장되지 않습니다.
"""
import keyring

_SERVICE = "ai-shorts-agent"
_EMAIL_KEY = "google_email"
_PW_KEY = "google_password"


def save_credentials(email: str, password: str) -> None:
    keyring.set_password(_SERVICE, _EMAIL_KEY, email)
    keyring.set_password(_SERVICE, _PW_KEY, password)


def load_credentials() -> tuple[str, str]:
    """저장된 (email, password) 반환. 없으면 ('', '')"""
    email = keyring.get_password(_SERVICE, _EMAIL_KEY) or ""
    pw = keyring.get_password(_SERVICE, _PW_KEY) or ""
    return email, pw


def has_credentials() -> bool:
    email, pw = load_credentials()
    return bool(email and pw)


def clear_credentials() -> None:
    try:
        keyring.delete_password(_SERVICE, _EMAIL_KEY)
    except Exception:
        pass
    try:
        keyring.delete_password(_SERVICE, _PW_KEY)
    except Exception:
        pass
