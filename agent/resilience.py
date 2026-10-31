"""弹性机制：异步重试、指数退避、熔断器。

供 llm_client / agent_loop / workflow_engine 引用，统一失败处理策略。
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class RetryPolicy:
    """重试策略配置。"""
    max_retries: int = 3
    base_delay: float = 2.0
    max_delay: float = 30.0
    jitter: float = 0.2              # 抖动比例 ±20%
    retry_exceptions: tuple = ()     # 只重试这些异常；空表示重试所有 Exception 子类（不含 CancelledError）

    def compute_delay(self, attempt: int) -> float:
        """计算第 attempt 次（从 1 开始）重试前的等待秒数。"""
        delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        if self.jitter > 0:
            delay += delay * random.uniform(-self.jitter, self.jitter)
        return max(0.0, delay)


async def retry_async(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    policy: RetryPolicy | None = None,
    retry_on: tuple = (),
    on_retry: Callable[[int, BaseException], Awaitable[None]] | None = None,
    **kwargs: Any,
) -> T:
    """异步重试包装。

    Args:
        func: 异步可调用对象
        policy: 重试策略；若 None 则用 retry_on 构造一个默认策略
        retry_on: 旧式参数，等价于 policy.retry_exceptions（policy 为 None 时生效）
        on_retry: 每次重试前的回调 (attempt, exception)
    """
    if policy is None:
        policy = RetryPolicy(retry_exceptions=retry_on)

    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_retries + 2):  # +2: 首次 + max_retries 次重试
        try:
            return await func(*args, **kwargs)
        except asyncio.CancelledError:
            raise
        except BaseException as e:  # noqa: BLE001
            last_exc = e
            if policy.retry_exceptions and not isinstance(e, policy.retry_exceptions):
                raise
            if attempt > policy.max_retries:
                raise
            delay = policy.compute_delay(attempt)
            log.warning("retry %s: attempt %d/%d after %.2fs (%s: %s)",
                        getattr(func, "__name__", "func"), attempt, policy.max_retries,
                        delay, type(e).__name__, e)
            if on_retry:
                try:
                    await on_retry(attempt, e)
                except Exception:  # noqa: BLE001
                    log.exception("on_retry callback failed")
            await asyncio.sleep(delay)
    # 理论不可达
    assert last_exc is not None
    raise last_exc


@dataclass
class CircuitBreaker:
    """简单熔断器。

    连续失败达 failure_threshold 次后进入 OPEN 状态，快速短路；
    经过 reset_timeout 秒后进入 HALF_OPEN，允许一次试探调用；
    成功则恢复 CLOSED，失败则回到 OPEN。

    用法：
        cb = CircuitBreaker(failure_threshold=5, reset_timeout=60)
        async with cb:
            await call_llm()
    """
    failure_threshold: int = 5
    reset_timeout: float = 60.0
    _failures: int = field(default=0, init=False)
    _state: str = field(default="closed", init=False)  # closed | open | half_open
    _opened_at: float = field(default=0.0, init=False)

    class CircuitOpenError(Exception):
        """熔断器开启时抛出。"""

    @property
    def state(self) -> str:
        return self._state

    async def __aenter__(self) -> "CircuitBreaker":
        if self._state == "open":
            if time.monotonic() - self._opened_at >= self.reset_timeout:
                self._state = "half_open"
                log.info("circuit breaker -> half_open")
            else:
                raise CircuitBreaker.CircuitOpenError(
                    f"熔断器开启中（连续失败 {self._failures} 次），{self.reset_timeout}s 后重试"
                )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            if self._state == "half_open":
                self._state = "closed"
                self._failures = 0
                log.info("circuit breaker -> closed (recovered)")
            elif self._failures > 0:
                self._failures = 0
        else:
            if isinstance(exc, asyncio.CancelledError):
                return False
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._state = "open"
                self._opened_at = time.monotonic()
                log.warning("circuit breaker -> open (failures=%d)", self._failures)
            elif self._state == "half_open":
                self._state = "open"
                self._opened_at = time.monotonic()
                log.warning("circuit breaker half_open -> open")
        # 不吞异常
        return False


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（偏保守）。

    实际按 `len/4 + len/8`（约 2.7 字符 ≈ 1 token）估算：中文接近 1 字 1 token，
    英文约 4 字符 1 token，混合内容取保守值，宁可早压缩也不超出上下文。
    """
    if not text:
        return 0
    return max(1, len(text) // 4 + len(text) // 8)
