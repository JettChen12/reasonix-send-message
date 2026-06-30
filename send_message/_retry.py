"""HTTP 请求重试工具 — 指数退避 + 可配置重试。

供各 sender 模块内部使用，不对外暴露。
"""

import time
import logging
from typing import Callable, Tuple, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry(
    fn: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    retryable_exceptions: Tuple[type, ...] = (OSError,),
    label: str = "",
) -> T:
    """带指数退避的通用重试。

    Args:
        fn: 要执行的函数。
        max_retries: 最大重试次数（0 表示不重试）。
        base_delay: 首次重试前的等待秒数。
        backoff: 每次重试的延迟倍率。
        retryable_exceptions: 触发重试的异常类型。
        label: 日志标签。

    Returns:
        fn 的返回值。

    Raises:
        超出重试次数后抛出最后一次异常。
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except retryable_exceptions as e:
            last_exc = e
            if attempt < max_retries:
                delay = base_delay * (backoff**attempt)
                logger.warning(
                    "%s 失败（第 %d/%d 次）: %s，%.1fs 后重试",
                    label or "操作",
                    attempt + 1,
                    max_retries + 1,
                    e,
                    delay,
                )
                time.sleep(delay)
    logger.error("%s 已重试 %d 次仍失败: %s", label or "操作", max_retries, last_exc)
    raise last_exc  # type: ignore[misc]
