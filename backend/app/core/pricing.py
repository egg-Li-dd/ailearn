"""AI 模型定价引擎：根据模型名匹配定价，计算预估费用（元人民币）。

定价数据来源：各服务商公开价格，统一换算为元/1K tokens。
未匹配到的模型使用默认价格估算。
"""
import logging
import re

logger = logging.getLogger("ailearn.pricing")

# 定价表：模型名关键词 -> (输入价格元/1K, 输出价格元/1K)
# 按优先级从高到低匹配（更具体的模式在前）
PRICING_TABLE = [
    # === DeepSeek ===
    (r"deepseek-v4-pro", (0.002, 0.008)),
    (r"deepseek-v4-flash", (0.0005, 0.002)),
    (r"deepseek-reasoner", (0.002, 0.008)),
    (r"deepseek-chat", (0.001, 0.002)),
    (r"deepseek-coder", (0.001, 0.002)),

    # === OpenAI ===
    (r"gpt-4o", (0.0175, 0.07)),
    (r"gpt-4o-mini", (0.00105, 0.0042)),
    (r"gpt-4-turbo", (0.007, 0.021)),
    (r"gpt-4", (0.021, 0.063)),
    (r"gpt-3.5-turbo", (0.0035, 0.0105)),
    (r"o1", (0.0105, 0.042)),
    (r"o3", (0.0105, 0.042)),

    # === Anthropic Claude ===
    (r"claude-opus", (0.105, 0.42)),
    (r"claude-sonnet", (0.021, 0.105)),
    (r"claude-haiku", (0.0035, 0.0175)),
    (r"claude-3-5", (0.021, 0.105)),
    (r"claude-3", (0.021, 0.105)),

    # === Google Gemini ===
    (r"gemini-2\.5-pro", (0.014, 0.042)),
    (r"gemini-2\.5-flash", (0.0021, 0.0084)),
    (r"gemini-1\.5-pro", (0.0125, 0.0375)),
    (r"gemini-1\.5-flash", (0.0025, 0.01)),

    # === 通义千问 / 阿里云百炼 ===
    (r"qwen-max", (0.008, 0.02)),
    (r"qwen-plus", (0.0016, 0.004)),
    (r"qwen-turbo", (0.0008, 0.002)),
    (r"qwen3", (0.0016, 0.004)),
    (r"qwen2\.5", (0.0016, 0.004)),
    (r"qwen2", (0.0016, 0.004)),
    (r"qwen-long", (0.0005, 0.002)),
    (r"qwen-vl", (0.008, 0.02)),

    # === 智谱清言 ===
    (r"glm-4-plus", (0.05, 0.05)),
    (r"glm-4-0520", (0.029, 0.029)),
    (r"glm-4-air", (0.001, 0.001)),
    (r"glm-4-flash", (0.0005, 0.0005)),
    (r"glm-4-long", (0.001, 0.001)),
    (r"glm-4v", (0.05, 0.05)),
    (r"glm-3", (0.012, 0.012)),

    # === 月之暗面 Kimi ===
    (r"kimi-k2", (0.004, 0.016)),
    (r"kimi-k1", (0.004, 0.016)),
    (r"moonshot-v1-128k", (0.024, 0.096)),
    (r"moonshot-v1-32k", (0.016, 0.064)),
    (r"moonshot-v1-8k", (0.012, 0.048)),

    # === MiniMax ===
    (r"minimax-m3", (0.003, 0.012)),
    (r"minimax-m2", (0.003, 0.012)),
    (r"abab6", (0.01, 0.04)),
    (r"abab5", (0.005, 0.02)),

    # === 零一万物 ===
    (r"yi-large", (0.02, 0.02)),
    (r"yi-medium", (0.012, 0.012)),
    (r"yi-spark", (0.001, 0.001)),
    (r"yi-lightning", (0.0005, 0.0005)),

    # === 阶跃星辰 ===
    (r"step-2", (0.005, 0.02)),
    (r"step-1", (0.014, 0.028)),

    # === 百川 ===
    (r"baichuan4", (0.03, 0.03)),
    (r"baichuan3", (0.012, 0.012)),
    (r"baichuan2", (0.008, 0.008)),

    # === 360 智脑 ===
    (r"360gpt", (0.012, 0.012)),
    (r"360kv", (0.012, 0.012)),

    # === 腾讯混元 ===
    (r"hunyuan-large", (0.012, 0.012)),
    (r"hunyuan-pro", (0.008, 0.008)),
    (r"hunyuan-standard", (0.004, 0.004)),
    (r"hunyuan-lite", (0.001, 0.001)),

    # === 硅基流动（开源模型，价格较低）===
    (r"Qwen/Qwen2\.5", (0.0007, 0.0014)),
    (r"deepseek-ai/DeepSeek", (0.0014, 0.0028)),
    (r"meta-llama/Llama", (0.0007, 0.0014)),

    # === MiMo ===
    (r"mimo-v2", (0.001, 0.004)),
]

# 默认价格（未匹配时使用）
DEFAULT_PRICE = (0.005, 0.02)  # 输入 0.005元/1K, 输出 0.02元/1K

# 输入/输出截断长度（避免数据库过大）
MAX_INPUT_LENGTH = 8000
MAX_OUTPUT_LENGTH = 8000


def get_pricing(model: str) -> tuple[float, float]:
    """根据模型名获取定价（输入元/1K, 输出元/1K）。

    匹配规则：
    1. 模型名转小写
    2. 按 PRICING_TABLE 顺序正则匹配
    3. 未匹配返回默认价格
    """
    if not model:
        return DEFAULT_PRICE
    model_lower = model.lower()
    for pattern, price in PRICING_TABLE:
        if re.search(pattern, model_lower):
            return price
    return DEFAULT_PRICE


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """预估费用（元人民币）。

    Args:
        model: 模型名
        prompt_tokens: 输入 token 数
        completion_tokens: 输出 token 数

    Returns:
        预估费用，保留 6 位小数
    """
    input_price, output_price = get_pricing(model)
    cost = (prompt_tokens / 1000) * input_price + (completion_tokens / 1000) * output_price
    return round(cost, 6)


def truncate_text(text: str, max_length: int = MAX_INPUT_LENGTH) -> str:
    """截断文本，避免存储过大。"""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length] + f"... [截断，原长 {len(text)} 字符]"


def format_cost(cost: float) -> str:
    """格式化费用显示。"""
    if cost <= 0:
        return "¥0.000000"
    if cost < 0.001:
        return f"¥{cost:.6f}"
    if cost < 0.01:
        return f"¥{cost:.4f}"
    return f"¥{cost:.2f}"
