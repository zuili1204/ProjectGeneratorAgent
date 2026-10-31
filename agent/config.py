"""配置模块：路径、LLM 设置、工作流参数。

配置优先级（从高到低）：
1. 环境变量
2. ~/.project_generator/config.json（或降级到项目目录 local_config.json）
3. 代码内默认值
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("pga.config")

# === 路径常量 ===
def _resolve_project_root() -> Path:
    """定位包含 skills/ templates/ web/ 的项目根目录。

    解析顺序：
    1. 环境变量 PGA_HOME（wheel 安装或自定义部署时指向资源目录）
    2. 包所在目录的上一级（源码 / `pip install -e .` 场景）
    3. 当前工作目录（从项目根目录运行 `pga` 的场景）
    """
    env = os.environ.get("PGA_HOME", "").strip()
    if env:
        return Path(env).expanduser().resolve()

    root = Path(__file__).resolve().parent.parent
    if (root / "skills").is_dir() or (root / "templates").is_dir():
        return root

    cwd = Path.cwd()
    if (cwd / "skills").is_dir() or (cwd / "templates").is_dir():
        return cwd
    return root


PROJECT_ROOT = _resolve_project_root()
SKILLS_DIR = PROJECT_ROOT / "skills"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
WORKSPACES_DIR = PROJECT_ROOT / "workspaces"

# 确保 workspaces 目录存在
WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)


# === 统一的项目类型枚举 ===
# 此前 _CODE_REQUIRED_BY_TYPE / grad_project.yaml / dev-requirement SKILL 各自定义，
# 现集中在此，供 health_check / workspace / cli / server 引用，避免漂移。
VALID_PROJECT_TYPES: tuple[str, ...] = (
    "fullstack", "frontend_only", "backend_only", "cli", "script",
)

# 检查点超时后的动作
VALID_CHECKPOINT_TIMEOUT_ACTIONS: tuple[str, ...] = (
    "auto_approve", "auto_reject", "wait_forever",
)

# 验证门禁模式（dev-selfcheck）
#   strict: 测试目录/测试文件/测试执行/运行时 四项全过
#   tests:  只硬性要求测试通过，不启动生成的项目（默认，避免副作用）
#   off:    不执行验证门禁
VALID_VERIFICATION_GATES: tuple[str, ...] = ("strict", "tests", "off")

# 静态 UI 质量门模式（dev-selfcheck，仅前端项目）
#   block: 客观问题（裸 hex / 低对比度 / 缺 alt 等）阻断并驱动重试
#   warn:  只告警不阻断
#   off:   不执行
VALID_UI_GATES: tuple[str, ...] = ("block", "warn", "off")


# === 默认 LLM 配置 ===
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_LLM_MODEL = "deepseek-chat"
DEFAULT_LLM_TIMEOUT = 600
DEFAULT_AGENT_MAX_ITER = 50
DEFAULT_INACTIVITY_TIMEOUT = 300   # 无输出超时（原 2400 未启用，现启用并收紧到 300s）
DEFAULT_CHECKPOINT_TIMEOUT = 600

# 重试默认值
DEFAULT_LLM_MAX_RETRIES = 3
DEFAULT_LLM_RETRY_BASE_DELAY = 2.0
DEFAULT_LLM_RETRY_MAX_DELAY = 30.0

# 全局 / 步骤级超时
DEFAULT_GLOBAL_TIMEOUT = 3600   # 单个工作流整体上限
DEFAULT_STEP_TIMEOUT = 1200     # 单步上限
DEFAULT_HEALTH_RETRY = 2        # 健康检查失败重试次数
DEFAULT_DEBUG_MAX_ROUNDS = 1    # 自动调试最多轮次（dev-debug）

# 默认上下文窗口（token），用于预算估算
DEFAULT_MODEL_CONTEXT_WINDOW = 32768


# === 模型价目表（USD per 1M tokens，即每百万 token 美元） ===
# 数据来源：各厂商公开定价页（2026 年）。key 为模型名子串匹配。
# input = prompt tokens，output = completion tokens。
# 用户可通过 llm_price_input_per_1m / llm_price_output_per_1m 覆盖。
MODEL_PRICING: dict[str, dict[str, float]] = {
    # DeepSeek
    "deepseek-chat":      {"input": 0.14,  "output": 0.28},
    "deepseek-reasoner":  {"input": 0.55,  "output": 2.19},
    # OpenAI
    "gpt-4o":             {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":        {"input": 0.15,  "output": 0.60},
    "gpt-4.1":            {"input": 2.00,  "output": 8.00},
    "gpt-4.1-mini":       {"input": 0.40,  "output": 1.60},
    "o1":                 {"input": 15.00, "output": 60.00},
    "o3-mini":            {"input": 3.00,  "output": 12.00},
    # Anthropic
    "claude-sonnet":      {"input": 3.00,  "output": 15.00},
    "claude-opus":        {"input": 15.00, "output": 75.00},
    "claude-haiku":       {"input": 0.80,  "output": 4.00},
    # 通义千问
    "qwen-max":           {"input": 2.50,  "output": 10.00},
    "qwen-plus":          {"input": 0.40,  "output": 1.20},
    "qwen-turbo":         {"input": 0.05,  "output": 0.20},
    # Moonshot
    "moonshot-v1":        {"input": 12.00, "output": 12.00},
}


def lookup_model_pricing(model: str) -> tuple[float, float]:
    """按模型名查找价目表，返回 (input_per_1m, output_per_1m)。

    匹配规则：模型名包含价目表 key（大小写不敏感）即命中。
    未命中返回 (0.0, 0.0)，成本记为 0（用户可手动配置覆盖）。
    """
    model_lower = (model or "").lower()
    for key, price in MODEL_PRICING.items():
        if key in model_lower:
            return (price["input"], price["output"])
    return (0.0, 0.0)


@dataclass
class LLMConfig:
    """LLM 客户端配置。"""
    base_url: str = ""
    api_key: str = ""
    model: str = DEFAULT_LLM_MODEL
    timeout: int = DEFAULT_LLM_TIMEOUT
    temperature: float = 0.7
    max_tokens: int = 8192
    # 重试与退避
    max_retries: int = DEFAULT_LLM_MAX_RETRIES
    retry_base_delay: float = DEFAULT_LLM_RETRY_BASE_DELAY
    retry_max_delay: float = DEFAULT_LLM_RETRY_MAX_DELAY
    # 模型上下文窗口（token），用于预算估算；0 表示未知不限制
    context_window: int = DEFAULT_MODEL_CONTEXT_WINDOW
    # 成本折算（USD per 1M tokens）；< 0 表示从 MODEL_PRICING 自动查表
    price_input_per_1m: float = -1.0
    price_output_per_1m: float = -1.0

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """从环境变量加载配置。

        支持的环境变量：
            LLM_BASE_URL / OPENAI_BASE_URL   — API 地址
            LLM_API_KEY / OPENAI_API_KEY     — API Key
            LLM_MODEL / OPENAI_MODEL         — 模型名
            LLM_TIMEOUT                      — 超时秒数
            LLM_TEMPERATURE                  — 温度
            LLM_MAX_TOKENS                   — 最大输出 tokens
            LLM_MAX_RETRIES                  — 业务层最大重试次数
            LLM_RETRY_BASE_DELAY             — 重试基础退避秒数
            LLM_RETRY_MAX_DELAY              — 重试最大退避秒数
            LLM_CONTEXT_WINDOW               — 模型上下文窗口 token 数
        """
        cfg = _load_user_config()
        # 价目：优先用户配置，否则 -1 触发 __post_init__ 自动查表
        price_in = float(os.environ.get("LLM_PRICE_INPUT_PER_1M", cfg.get("llm_price_input_per_1m", -1.0)))
        price_out = float(os.environ.get("LLM_PRICE_OUTPUT_PER_1M", cfg.get("llm_price_output_per_1m", -1.0)))
        return cls(
            base_url=(
                os.environ.get("LLM_BASE_URL")
                or os.environ.get("OPENAI_BASE_URL")
                or cfg.get("llm_base_url", DEFAULT_LLM_BASE_URL)
            ),
            api_key=(
                os.environ.get("LLM_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
                or cfg.get("llm_api_key", "")
            ),
            model=(
                os.environ.get("LLM_MODEL")
                or os.environ.get("OPENAI_MODEL")
                or cfg.get("llm_model", DEFAULT_LLM_MODEL)
            ),
            timeout=int(os.environ.get("LLM_TIMEOUT", DEFAULT_LLM_TIMEOUT)),
            temperature=float(os.environ.get("LLM_TEMPERATURE", 0.7)),
            max_tokens=int(os.environ.get("LLM_MAX_TOKENS", 8192)),
            max_retries=int(os.environ.get("LLM_MAX_RETRIES", cfg.get("llm_max_retries", DEFAULT_LLM_MAX_RETRIES))),
            retry_base_delay=float(os.environ.get("LLM_RETRY_BASE_DELAY", cfg.get("llm_retry_base_delay", DEFAULT_LLM_RETRY_BASE_DELAY))),
            retry_max_delay=float(os.environ.get("LLM_RETRY_MAX_DELAY", cfg.get("llm_retry_max_delay", DEFAULT_LLM_RETRY_MAX_DELAY))),
            context_window=int(os.environ.get("LLM_CONTEXT_WINDOW", cfg.get("llm_context_window", DEFAULT_MODEL_CONTEXT_WINDOW))),
            price_input_per_1m=price_in,
            price_output_per_1m=price_out,
        )

    def __post_init__(self) -> None:
        if not self.base_url:
            self.base_url = DEFAULT_LLM_BASE_URL
        # 自动补全 /v1 路径
        if not self.base_url.rstrip("/").endswith("/v1"):
            if "/v1/" not in self.base_url:
                self.base_url = self.base_url.rstrip("/") + "/v1"
        # 价目自动查表：仅当用户未显式配置（< 0）时从 MODEL_PRICING 匹配
        if self.price_input_per_1m < 0 or self.price_output_per_1m < 0:
            auto_in, auto_out = lookup_model_pricing(self.model)
            if self.price_input_per_1m < 0:
                self.price_input_per_1m = auto_in
            if self.price_output_per_1m < 0:
                self.price_output_per_1m = auto_out

    def validate(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "LLM API Key 未配置。请设置环境变量 LLM_API_KEY 或 OPENAI_API_KEY，"
                "或运行 `pga config set llm_api_key <your-key>` 写入用户配置文件。"
            )

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """估算单次调用的 USD 成本。

        cost = prompt_tokens/1e6 * price_input + completion_tokens/1e6 * price_output
        价目为 0（未配置且查表未命中）时返回 0.0，不报错。
        """
        cost = (
            prompt_tokens / 1_000_000.0 * self.price_input_per_1m
            + completion_tokens / 1_000_000.0 * self.price_output_per_1m
        )
        return round(cost, 6)


def _config_path() -> Path:
    """配置文件路径。

    优先使用 ~/.project_generator/config.json（如果可写）。
    否则使用项目目录下的 local_config.json。
    """
    user_path = Path.home() / ".project_generator" / "config.json"
    # 检测用户目录是否可写（尝试创建父目录和写入空内容）
    try:
        user_path.parent.mkdir(parents=True, exist_ok=True)
        # 触发权限检测：尝试创建空文件
        if not user_path.exists():
            user_path.write_text("{}", encoding="utf-8")
        return user_path
    except PermissionError:
        log.warning("user config path not writable, using project directory")
        return PROJECT_ROOT / "local_config.json"


# 向后兼容别名：cli.py 早期版本导入 _user_config_path，统一指向 _config_path
_user_config_path = _config_path


def _load_user_config() -> dict:
    """加载用户配置文件（不存在则返回空 dict）。"""
    p = _config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_user_config(data: dict) -> None:
    """保存用户配置文件。"""
    p = _config_path()
    content = json.dumps(data, indent=2, ensure_ascii=False)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def set_user_config(key: str, value: str) -> None:
    """设置单个配置项。"""
    cfg = _load_user_config()
    cfg[key] = value
    save_user_config(cfg)


@dataclass
class WorkflowConfig:
    """工作流运行时配置。"""
    agent_max_iter: int = DEFAULT_AGENT_MAX_ITER
    inactivity_timeout: int = DEFAULT_INACTIVITY_TIMEOUT
    checkpoint_timeout: int = DEFAULT_CHECKPOINT_TIMEOUT
    enable_checkpoints: bool = True
    auto_proceed: bool = False
    project_type: str = "fullstack"
    # 检查点超时动作: auto_approve / auto_reject / wait_forever
    checkpoint_timeout_action: str = "auto_reject"
    # 健康检查失败重试次数
    health_retry: int = DEFAULT_HEALTH_RETRY
    # 自动调试（dev-debug）：健康检查重试耗尽后，先跑一轮根因调试再判失败
    auto_debug: bool = True
    debug_max_rounds: int = DEFAULT_DEBUG_MAX_ROUNDS
    # 全局 / 步骤级超时
    global_timeout: int = DEFAULT_GLOBAL_TIMEOUT
    step_timeout: int = DEFAULT_STEP_TIMEOUT
    # 验证门禁（dev-selfcheck）：strict / tests / off
    #   strict — 测试 + 运行时全过；tests — 只硬性要求测试通过；off — 关闭
    verification_gate: str = "tests"
    # 静态 UI 质量门（前端项目）：block / warn / off
    ui_gate: str = "block"
    # Git 集成（P3-1）：create_workflow 时 git init，每步 commit，rerun 新建分支。
    # git 不可用时优雅降级，不影响主流程。可通过参数关闭。
    enable_git: bool = True

    def __post_init__(self) -> None:
        if self.project_type not in VALID_PROJECT_TYPES:
            log.warning("unknown project_type %r, fallback to fullstack", self.project_type)
            self.project_type = "fullstack"
        if self.checkpoint_timeout_action not in VALID_CHECKPOINT_TIMEOUT_ACTIONS:
            self.checkpoint_timeout_action = "auto_reject"
        if self.verification_gate not in VALID_VERIFICATION_GATES:
            log.warning("unknown verification_gate %r, fallback to tests", self.verification_gate)
            self.verification_gate = "tests"
        if self.ui_gate not in VALID_UI_GATES:
            log.warning("unknown ui_gate %r, fallback to block", self.ui_gate)
            self.ui_gate = "block"

    @classmethod
    def from_dict(cls, d: dict | None = None) -> "WorkflowConfig":
        d = d or {}
        return cls(
            agent_max_iter=int(d.get("agent_max_iter", DEFAULT_AGENT_MAX_ITER)),
            inactivity_timeout=int(d.get("inactivity_timeout", DEFAULT_INACTIVITY_TIMEOUT)),
            checkpoint_timeout=int(d.get("checkpoint_timeout", DEFAULT_CHECKPOINT_TIMEOUT)),
            enable_checkpoints=bool(d.get("enable_checkpoints", True)),
            auto_proceed=bool(d.get("auto_proceed", False)),
            project_type=str(d.get("project_type", "fullstack")),
            checkpoint_timeout_action=str(d.get("checkpoint_timeout_action", "auto_reject")),
            health_retry=int(d.get("health_retry", DEFAULT_HEALTH_RETRY)),
            auto_debug=bool(d.get("auto_debug", True)),
            debug_max_rounds=int(d.get("debug_max_rounds", DEFAULT_DEBUG_MAX_ROUNDS)),
            global_timeout=int(d.get("global_timeout", DEFAULT_GLOBAL_TIMEOUT)),
            step_timeout=int(d.get("step_timeout", DEFAULT_STEP_TIMEOUT)),
            verification_gate=str(d.get("verification_gate", "tests")),
            ui_gate=str(d.get("ui_gate", "block")),
            enable_git=bool(d.get("enable_git", True)),
        )
