import time
import random
from typing import TypeVar, Callable, Any

T = TypeVar("T")

# 429 발생 시 시도할 모델 폴백 순서
GEMINI_TEXT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]


def is_quota_error(e: Exception) -> bool:
    msg = str(e)
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()


def retry_with_backoff(
    fn: Callable[..., T],
    *args: Any,
    max_retries: int = 4,
    base_delay: float = 5.0,
    **kwargs: Any,
) -> T:
    """429 발생 시 지수 백오프로 재시도. 모든 재시도 실패 시 예외 전파."""
    last_exc: Exception = RuntimeError("retry failed")
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if not is_quota_error(e):
                raise  # 429 이외의 오류는 즉시 전파
            last_exc = e
            if attempt == max_retries - 1:
                break
            delay = base_delay * (2 ** attempt) + random.uniform(0, 2)
            time.sleep(delay)
    raise last_exc


def call_with_model_fallback(
    make_fn: Callable[[str], T],
    models: list[str] = GEMINI_TEXT_MODELS,
) -> T:
    """모델 목록을 순서대로 시도. 429면 다음 모델로 폴백."""
    last_exc: Exception = RuntimeError("all models exhausted")
    for model in models:
        try:
            return retry_with_backoff(make_fn, model, max_retries=3, base_delay=5.0)
        except Exception as e:
            if not is_quota_error(e):
                raise
            last_exc = e
    raise last_exc
