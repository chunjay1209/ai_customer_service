"""按租户配置调用 LLM 拆分关键词。

核心优化（2026-06-10）：
1) LLM 调用改为"有 key 才调用，没有就走本地规则"；
2) 本地规则：先按空格切分为「段」，段内再识别「容量」「型号整体词」「颜色」；
3) 容量组合：把「12 256」「12+256」「256G」统一产出"12+256"、"12+256G"、"256G"；
4) 匹配策略：至少命中 threshold 个关键词（默认 2），减少"单数字命中 iPad 12.9"的误匹配。

2026-06-22：增加 DeepSeek 支持（OpenAI 兼容格式）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import List

_logger = logging.getLogger("llm_service")

try:
    import google.generativeai as genai  # type: ignore
    _GEMINI_OK = True
except Exception:  # noqa: BLE001
    _GEMINI_OK = False

try:
    from openai import OpenAI  # type: ignore
    _OPENAI_OK = True
except Exception:  # noqa: BLE001
    _OPENAI_OK = False

# DeepSeek API 兼容 OpenAI 格式
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


# ============================================================
# 模块级编译正则（性能优化：避免每次调用重复编译）
# ============================================================
# fine_tokenize 主模式：型号+后缀（pro+/max+等）优先于容量
_FINE_TOKENIZE_PATTERN = re.compile(
    r'(?:pro|max|plus|lite|ultra|turbo|neo)\+'           # 型号+后缀: pro+/max+/turbo+ (优先于容量)
    r"|"
    r"[A-Za-z][A-Za-z0-9]*\+"                              # 型号编号+号: A6i+/A6v+ 等（保留 + 号，要求至少一个字母避免匹配容量）
    r"|"
    r"[A-Za-z0-9]*\d+[A-Za-z]*[+＋\-/]\d+[A-Za-z]*[A-Za-z0-9]*|"  # 容量: 12+256 / 12GB+512GB / 12-256
    r"(?:[A-Za-z][A-Za-z0-9]*)+|"                       # 英文/型号: Turbo4 / note13Pro / A3i / K12S / K80
    r"[0-9]+[A-Za-z][A-Za-z0-9]*|"                      # 数字+字母混合(数字开头): 14plus256 / 5G
    r"[\u4e00-\u9fff]+|"                                 # 中文块
    r"[0-9]+",                                           # 纯数字型号: 12 / 16 / 256
    re.VERBOSE,
)

# fine_tokenize 二次容量拆分
_CAPACITY_RE = re.compile(
    r"(\d+(?:[gG](?:[bB])?|[tT][bB])[+＋\-/]\d+(?:[gG](?:[bB])?|[tT][bB]))"   # 12GB+512GB / 12G-512G / 16GB+1TB
    r"|(\d+[+＋\-/]\d+(?:[gG](?:[bB])?|[tT][bB]))"                              # 12+512GB / 12-512G / 12+1TB
    r"|(\d+(?:[gG](?:[bB])?|[tT][bB])[+＋\-/]\d+)"                               # 12GB+512 / 12G/512 / 16GB+1
    r"|(\d+[+＋\-/]\d+G?)",                                                       # 12+512 / 12-512 / 12/512G
    re.IGNORECASE,
)

# 型号+后缀粘连拆分：A5Pro → A5, Pro; Y60Turbo → Y60, Turbo; Z10TurboPro → Z10, TurboPro
# 复合后缀（如 TurboPro）会进一步由 _COMPOUND_SUFFIX_SPLIT_RE 拆分
_MODEL_SUFFIX_SPLIT_RE = re.compile(
    r'^([A-Za-z]*\d+)((?:pro|turbo|ultra|neo|note|mate)(?:pro|max|\+|ultra|turbo)?|promax|pro\+|pro|max|plus|lite|ultra|turbo|neo|se|mini|note|nova|mate|mix|fold|flip|edge)$',
    re.IGNORECASE,
)

# 复合后缀拆分：ProMax → Pro, Max; TurboPro → Turbo, Pro
# 注意：不拆分 Pro+ / Turbo+，因为 + 不是独立后缀
_COMPOUND_SUFFIX_SPLIT_RE = re.compile(
    r'^(turbo|pro|ultra|neo|note|mate)(pro|max|ultra|turbo)$',
    re.IGNORECASE,
)

# fine_tokenize 字母/数字边界拆分
_SPLIT_RE = re.compile(r"[A-Za-z]+|\d+")

# fallback_extract 型号后缀+补丁
_SUFFIX_PLUS_RX = re.compile(r'(?:pro|max|plus|lite|ultra|turbo|neo)\+', re.IGNORECASE)

# 通用停用词
# 注意："版" 不在停用词中，因为 "活力版"/"至尊版" 是合法的型号后缀
_STOPWORDS = {
    "台", "部", "个", "件", "套", "条", "要", "买", "求", "需", "的",
    "和", "与", "及", "一个", "一台", "两台", "三台", "几台",
    "一", "二", "两", "三", "四", "五", "六", "七", "八", "九", "十",
    "国行", "港版", "美版", "原封", "原装", "全新", "色", "寸",
}

# 常用颜色词（覆盖主流手机颜色）
_COLORS = {
    # 黑色系
    "黑", "黑色", "纯黑", "亮黑", "磨砂黑", "曜石黑", "暗黑", "深黑",
    "星空黑", "幻夜黑", "墨黑", "碳黑", "暗影黑", "午夜黑", "极夜黑",
    # 白色系
    "白", "白色", "纯白", "亮白", "磨砂白", "珍珠白", "皓玉白", "陶瓷白",
    "凝脂白", "雪白", "月光白", "冰瓷白", "霜白", "乳白",
    # 灰色系
    "灰", "灰色", "深灰", "浅灰", "银灰", "烟灰", "碳灰", "钛灰",
    "星云灰", "岩石灰", "水泥灰", "太空灰", "暗灰",
    # 银色系
    "银", "银色", "银白", "亮银", "磨砂银", "星光银", "星辉银",
    "冰银", "晶银",
    # 蓝色系
    "蓝", "蓝色", "深蓝", "浅蓝", "天蓝", "海蓝", "宝石蓝", "星空蓝",
    "梦幻蓝", "极光蓝", "蔚蓝", "湖蓝", "雾蓝", "冰蓝", "午夜蓝",
    "克莱因蓝", "星云蓝", "晶钻蓝", "远峰蓝", "苍岭蓝", "深海蓝",
    # 紫色系
    "紫", "紫色", "深紫", "浅紫", "粉紫", "香芋紫", "薰衣草紫",
    "梦幻紫", "星云紫", "极光紫", "紫霞",
    # 粉色系
    "粉", "粉色", "粉红", "樱花粉", "玫瑰粉", "桃粉", "淡粉",
    "星云粉", "梦幻粉", "珊瑚粉",
    # 红色系
    "红", "红色", "大红", "深红", "亮红", "中国红", "烈焰红",
    "朱红", "酒红", "嫣红", "赤红", "星云红",
    # 金色系
    "金", "金色", "香槟金", "玫瑰金", "亮金", "磨砂金", "流光金",
    "星光金", "琥珀金", "钛金",
    # 绿色系
    "绿", "绿色", "深绿", "浅绿", "翠绿", "墨绿", "薄荷绿",
    "青绿", "豆绿", "草绿", "军绿", "星云绿", "极光绿", "森林绿",
    # 青色/蓝色混合
    "青", "青色", "深青", "浅青", "青铜",
    "钛", "钛色", "原钛", "钛金属",
    # 棕色/咖啡色
    "棕", "棕色", "咖啡", "咖啡色", "卡其", "卡其色", "茶色",
    "古铜", "古铜色", "驼色",
    # 黄色
    "黄", "黄色", "暖黄", "明黄", "淡黄",
    # 橙色
    "橙", "橙色", "橘色", "活力橙", "燃",
    # 其他常见色
    "透明", "半透明", "渐变", "渐变色", "幻彩",
    "彩色", "五彩", "霓虹", "炫彩",
    "素皮", "真皮", "科技皮",
}

# 颜色分组映射
_COLOR_TO_GROUP = {
    "黑": "black", "黑色": "black", "纯黑": "black", "亮黑": "black", "磨砂黑": "black",
    "曜石黑": "black", "暗黑": "black", "深黑": "black", "星空黑": "black", "幻夜黑": "black",
    "墨黑": "black", "碳黑": "black", "暗影黑": "black", "午夜黑": "black", "极夜黑": "black",
    "白": "white", "白色": "white", "纯白": "white", "亮白": "white", "磨砂白": "white",
    "珍珠白": "white", "皓玉白": "white", "陶瓷白": "white", "凝脂白": "white", "雪白": "white",
    "月光白": "white", "冰瓷白": "white", "霜白": "white", "乳白": "white",
    "灰": "gray", "灰色": "gray", "深灰": "gray", "浅灰": "gray", "银灰": "gray",
    "烟灰": "gray", "碳灰": "gray", "钛灰": "gray", "星云灰": "gray", "岩石灰": "gray",
    "水泥灰": "gray", "太空灰": "gray", "暗灰": "gray",
    "银": "silver", "银色": "silver", "银白": "silver", "亮银": "silver", "磨砂银": "silver",
    "星光银": "silver", "星辉银": "silver", "冰银": "silver", "晶银": "silver",
    "蓝": "blue", "蓝色": "blue", "深蓝": "blue", "浅蓝": "blue", "天蓝": "blue",
    "海蓝": "blue", "宝石蓝": "blue", "星空蓝": "blue", "梦幻蓝": "blue", "极光蓝": "blue",
    "蔚蓝": "blue", "湖蓝": "blue", "雾蓝": "blue", "冰蓝": "blue", "午夜蓝": "blue",
    "克莱因蓝": "blue", "星云蓝": "blue", "晶钻蓝": "blue", "远峰蓝": "blue", "苍岭蓝": "blue",
    "深海蓝": "blue",
    "紫": "purple", "紫色": "purple", "深紫": "purple", "浅紫": "purple", "粉紫": "purple",
    "香芋紫": "purple", "薰衣草紫": "purple", "梦幻紫": "purple", "星云紫": "purple",
    "极光紫": "purple", "紫霞": "purple",
    "粉": "pink", "粉色": "pink", "粉红": "pink", "樱花粉": "pink", "玫瑰粉": "pink",
    "桃粉": "pink", "淡粉": "pink", "星云粉": "pink", "梦幻粉": "pink", "珊瑚粉": "pink",
    "红": "red", "红色": "red", "大红": "red", "深红": "red", "亮红": "red", "中国红": "red",
    "烈焰红": "red", "朱红": "red", "酒红": "red", "嫣红": "red", "赤红": "red", "星云红": "red",
    "金": "gold", "金色": "gold", "香槟金": "gold", "玫瑰金": "gold", "亮金": "gold",
    "磨砂金": "gold", "流光金": "gold", "星光金": "gold", "琥珀金": "gold", "钛金": "gold",
    "绿": "green", "绿色": "green", "深绿": "green", "浅绿": "green", "翠绿": "green",
    "墨绿": "green", "薄荷绿": "green", "青绿": "green", "豆绿": "green", "草绿": "green",
    "军绿": "green", "星云绿": "green", "极光绿": "green", "森林绿": "green",
    "青": "cyan", "青色": "cyan", "深青": "cyan", "浅青": "cyan", "青铜": "cyan",
    "钛": "titanium", "钛色": "titanium", "原钛": "titanium", "钛金属": "titanium",
    "棕": "brown", "棕色": "brown", "咖啡": "brown", "咖啡色": "brown", "卡其": "brown",
    "卡其色": "brown", "茶色": "brown", "古铜": "brown", "古铜色": "brown", "驼色": "brown",
    "黄": "yellow", "黄色": "yellow", "暖黄": "yellow", "明黄": "yellow", "淡黄": "yellow",
    "橙": "orange", "橙色": "orange", "橘色": "orange", "活力橙": "orange", "燃": "orange",
    "透明": "transparent", "半透明": "transparent", "渐变": "gradient", "渐变色": "gradient",
    "幻彩": "gradient",
    "彩色": "colorful", "五彩": "colorful", "霓虹": "colorful", "炫彩": "colorful",
    "素皮": "leather", "真皮": "leather", "科技皮": "leather",
}

# 颜色分组显示名
_COLOR_GROUP_NAMES = {
    "black": "黑色",
    "white": "白色",
    "gray": "灰色",
    "silver": "银色",
    "blue": "蓝色",
    "purple": "紫色",
    "pink": "粉色",
    "red": "红色",
    "gold": "金色",
    "green": "绿色",
    "cyan": "青色",
    "titanium": "钛色",
    "brown": "棕色",
    "yellow": "黄色",
    "orange": "橙色",
    "transparent": "透明",
    "gradient": "渐变",
    "colorful": "彩色",
    "leather": "素皮",
}

# 颜色近义词映射（把变体映射到标准色）
_COLOR_SYNONYMS = {
    "纯黑": "黑",
    "亮黑": "黑",
    "磨砂黑": "黑",
    "曜石黑": "黑",
    "纯白": "白",
    "亮白": "白",
    "磨砂白": "白",
    "珍珠白": "白",
    "银灰": "灰",
    "深空灰": "灰",
    "星空灰": "灰",
    "星光色": "银",
    "星光银": "银",
    "玫瑰金": "金",
    "香槟金": "金",
    "远峰蓝": "蓝",
    "苍岭绿": "绿",
}


def _strip_quantity_suffix(text: str) -> str:
    """去掉数量前缀和数量后缀，保留纯商品描述。
    
    * 去掉 "1台"、"两台"、"三台"、"一个"、"两个" 等数量前缀
    * 去掉句末的 "一台"、"一个"、"一部" 等数量后缀
    """
    # 去掉前缀数量词（如 "1台", "两台", "一个"）
    text = re.sub(
        r'^[\d零一二两三四五六七八九十百千万]+[台部个件套条款]?\s*',
        '',
        text,
    )
    # 去掉后缀数量词（如句末的 "一台", "一个", "一部" 但不包括 "256G一台"）
    text = re.sub(
        r'\s*[一两]?[台部个件套条款](?:\s*[一两]?[台部个件套条款])?$',
        '',
        text,
    )
    return text.strip()


def _fine_tokenize(text: str) -> list[str]:
    """内部精细切分：识别容量/型号/颜色/中文，返回紧凑 token 列表。
    
    二次拆分：处理型号+后缀粘连，如 A5Pro → A5, Pro; Y60Turbo → Y60, Turbo。
    """
    parts = re.findall(_FINE_TOKENIZE_PATTERN, text)
    if not parts:
        return [text]

    tokens: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 如果是容量组合，拆分为多种表示
        if re.match(r'^[\d]+[+＋\-/][\d]+', part):
            m_cap = re.match(r'^(\d+)[+＋\-/](\d+)([gG][bB]?|[tT][bB])?$', part)
            if m_cap:
                a, b, suffix = m_cap.group(1), m_cap.group(2), (m_cap.group(3) or '')
                suffix_norm = suffix.upper() if suffix else ''
                # 统一分隔符为 +
                variations = [f'{a}+{b}{suffix_norm}', f'{a}+{b}']
                # 如果 b 没有单位，补 G
                if not suffix_norm:
                    variations.insert(0, f'{a}+{b}G')
                tokens.extend(variations)
                continue
            tokens.append(part)
        elif re.fullmatch(_CAPACITY_RE, part):
            tokens.append(part)
        else:
            tokens.append(part)

    # 二次拆分：型号+后缀粘连（如 A5Pro → A5, Pro; Y60Turbo → Y60, Turbo）
    split_tokens: list[str] = []
    for token in tokens:
        m = _MODEL_SUFFIX_SPLIT_RE.match(token)
        if m:
            split_tokens.append(m.group(1))
            suffix = m.group(2)
            # 复合后缀再拆分：ProMax → Pro, Max; Pro+ → Pro, +
            cm = _COMPOUND_SUFFIX_SPLIT_RE.match(suffix)
            if cm:
                split_tokens.append(cm.group(1))
                split_tokens.append(cm.group(2))
            else:
                split_tokens.append(suffix)
        else:
            split_tokens.append(token)

    # 三次拆分：去除重复的型号模式（如 Z10XZ10X → Z10X）
    deduped_tokens: list[str] = []
    for token in split_tokens:
        if token.isascii() and len(token) >= 4 and len(token) % 2 == 0:
            half = len(token) // 2
            if token[:half] == token[half:]:
                # 重复模式检测成功，拆为单个
                deduped_tokens.append(token[:half])
                continue
        # 也检测三段重复（如 ABCABCABC → ABC）
        if token.isascii() and len(token) >= 6 and len(token) % 3 == 0:
            third = len(token) // 3
            if token[:third] == token[third:2*third] == token[2*third:]:
                deduped_tokens.append(token[:third])
                continue
        deduped_tokens.append(token)

    return deduped_tokens


def _fallback_extract(text: str) -> list[str]:
    """纯本地规则提取关键词（无 LLM key 时的保底方案）。

    流程：
    1. 停用词过滤
    2. 按空白/标点切段
    3. 段内 fine_tokenize
    4. 颜色归一化 → dedup
    """
    if not text or not text.strip():
        return []

    # 停用词清洗
    for w in sorted(_STOPWORDS, key=len, reverse=True):
        text = text.replace(w, '')
    text = text.strip()
    if not text:
        return []

    # 按空白/常见标点切段
    segments = re.split(r'[\s,，、；;。.！!？?]+', text)

    result: list[str] = []
    seen: set[str] = set()
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        if len(seg) == 1 and seg not in _COLORS:
            continue
        # 数字+单位（128G, 512GB, 1TB）直接保留，且保留变体
        unit_match = re.match(r'^(\d+)\s*(G|GB|g|gb|T|TB|tb)$', seg)
        if unit_match:
            num = unit_match.group(1)
            unit = unit_match.group(2).upper()
            for v in (f'{num}{unit}', f'{num}{unit[0]}', num):
                if v not in seen:
                    result.append(v)
                    seen.add(v)
            continue

        tokens = _fine_tokenize(seg)
        for token in tokens:
            if token in seen:
                continue
            # 颜色归一化
            norm_color = _COLOR_SYNONYMS.get(token)
            if norm_color:
                if norm_color not in seen:
                    result.append(norm_color)
                    seen.add(norm_color)
                continue
            # 颜色分组映射：保留原始颜色词，不做组名替换（如「燃」保留为「燃」，不替换为「橙色」）
            if token in _COLOR_TO_GROUP:
                if token not in seen:
                    result.append(token)
                    seen.add(token)
                continue
            result.append(token)
            seen.add(token)

    # 二次去重 —— 去掉被其他 token 完全包含的
    deduped: list[str] = []
    for token in result:
        # 如果 token 被别的 token 完全包含（如 "256G" 包含 "256"），跳过
        if any(token != other and token in other for other in result):
            continue
        deduped.append(token)

    return deduped


# ============================================================
# LLM Prompt 模板
# ============================================================
_PROMPT_TEMPLATE = """提取商品关键词（型号、容量、颜色），逗号分隔，只输出关键词。重要：颜色必须严格使用输入文本中出现的原始颜色词，不要替换、翻译或改写颜色词：

{text}"""

_PROMPT_TEMPLATE_BATCH = """提取每行商品关键词（型号、容量、颜色），返回JSON数组，每行一个数组。重要：颜色必须严格使用输入文本中出现的原始颜色词，不要替换、翻译或改写颜色词：

{batch_text}"""


# ============================================================
# LLM 调用函数
# ============================================================

def _call_deepseek(messages: list[dict], model: str = "deepseek-chat", max_tokens: int = 256, temperature: float = 0.1, api_key: str = "", timeout: float = 8.0) -> str | None:
    """调用 DeepSeek API（OpenAI 兼容格式）。
    
    model: DeepSeek 要求的模型名是全小写（如 deepseek-v4-flash），
           传入时会自动转为小写以兼容配置中的大小写混写。
    返回响应文本，失败返回 None。
    timeout: HTTP 请求超时秒数（默认 8s）
    """
    if not _OPENAI_OK:
        return None
    try:
        # DeepSeek API 模型名必须全小写
        model_lower = model.lower().strip()
        client = OpenAI(api_key=api_key, base_url=_DEEPSEEK_BASE_URL, timeout=timeout, max_retries=0)
        resp = client.chat.completions.create(
            model=model_lower,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content
    except Exception as e:
        _logger.warning(f"_call_deepseek failed: {type(e).__name__}: {str(e)[:200]}")
        return None


def _call_gemini(messages: list[dict], model: str = "gemini-2.0-flash", api_key: str = "") -> str | None:
    """调用 Gemini API。
    
    将消息列表转换为 Gemini 格式后调用，返回响应文本，失败返回 None。
    """
    if not _GEMINI_OK:
        return None
    try:
        genai.configure(api_key=api_key)
        model_inst = genai.GenerativeModel(model)
        # 将消息列表转换为 Gemini 期望的格式
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                prompt_parts.append(f"【系统指令】{content}")
            else:
                prompt_parts.append(content)
        full_prompt = "\n".join(prompt_parts)
        resp = model_inst.generate_content(full_prompt)
        return resp.text
    except Exception:
        return None


def _correct_llm_color_keywords(keywords: list[str], original_text: str) -> list[str]:
    """修正 LLM 返回的颜色关键词，防止 LLM 将颜色词替换为组名（如「燃」→「橙色」）。

    策略：如果 LLM 返回了一个颜色组名（如「橙色」），检查原始输入文本中是否有
    同组但更具体的颜色词（如「燃」），有则替换为原始颜色词。
    """
    if not keywords or not original_text:
        return keywords

    # 先从原始文本中提取所有颜色词
    original_colors: list[str] = []
    # 使用 _fallback_extract 的颜色提取逻辑来获取原始文本中的颜色词
    # 但我们只需要颜色部分，所以简化为直接扫描原始文本中的已知颜色词
    text_normalized = original_text
    for w in sorted(_STOPWORDS, key=len, reverse=True):
        text_normalized = text_normalized.replace(w, '')
    text_normalized = text_normalized.strip()

    for color_name in _COLOR_TO_GROUP:
        if color_name in text_normalized:
            original_colors.append(color_name)

    if not original_colors:
        return keywords

    # 构建原始文本中颜色词到组的映射
    original_color_groups: dict[str, str] = {}
    for oc in original_colors:
        group = _COLOR_TO_GROUP.get(oc)
        if group:
            original_color_groups[group] = oc

    # 修正 LLM 返回的颜色关键词
    corrected: list[str] = []
    for kw in keywords:
        # 只处理纯中文关键词（颜色词）
        if kw and re.match(r'^[\u4e00-\u9fff]+$', kw):
            kw_group = _COLOR_TO_GROUP.get(kw)
            if kw_group and kw_group in original_color_groups:
                original_color = original_color_groups[kw_group]
                if original_color != kw:
                    corrected.append(original_color)
                    continue
        corrected.append(kw)

    return corrected


def _split_composite_tokens(tokens: list[str]) -> list[str]:
    """对 LLM 返回的关键词进行后处理：拆分复合 token。

    将 LLM 可能返回的粘连 token 拆分为独立关键词：
    - Z10TurboPro → Z10, Turbo, Pro
    - Y300Pro+ → Y300, Pro+
    - A6i+ → A6i+ (不变)
    容量和颜色 token 不受影响。
    """
    result: list[str] = []
    for token in tokens:
        if not token or not token.strip():
            continue
        # 跳过容量类 token
        if re.match(r'^\d+[+＋\-/]\d+', token):
            result.append(token)
            continue
        # 跳过纯中文 token（颜色词）
        if re.match(r'^[\u4e00-\u9fff]+$', token):
            result.append(token)
            continue
        # 尝试拆分型号+后缀粘连
        m = _MODEL_SUFFIX_SPLIT_RE.match(token)
        if m:
            result.append(m.group(1))
            suffix = m.group(2)
            cm = _COMPOUND_SUFFIX_SPLIT_RE.match(suffix)
            if cm:
                result.append(cm.group(1))
                result.append(cm.group(2))
            else:
                result.append(suffix)
        else:
            result.append(token)
    return result


def _parse_llm_response(llm_text: str | None) -> list[str]:
    """解析 LLM 单条响应文本为关键词列表。
    
    支持格式：
    - 逗号分隔："关键词1, 关键词2, 关键词3"
    - 换行分隔
    - JSON 数组：["关键词1", "关键词2"]
    - 混合格式
    """
    if not llm_text:
        return []
    
    # 尝试解析 JSON 数组
    text = llm_text.strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(k).strip() for k in parsed if str(k).strip()]
        except (json.JSONDecodeError, TypeError):
            pass
    
    # 按逗号、中文逗号、换行拆分
    keywords = re.split(r'[,，\n]+', text)
    # 过滤空格和空字符串
    keywords = [k.strip() for k in keywords if k.strip()]
    # 去掉可能的前缀如 "关键词："
    cleaned = []
    for k in keywords:
        k = re.sub(r'^[：:\-—]\s*', '', k)
        k = re.sub(r'^关键词[：:\s]*', '', k, flags=re.IGNORECASE)
        if k:
            cleaned.append(k)
    
    return cleaned


def _parse_llm_batch_response(llm_text: str | None, num_inputs: int) -> list[list[str]]:
    """解析 LLM 批量响应文本为关键词列表的列表。
    
    期望 LLM 返回 JSON 数组格式：[[...], [...], ...]
    如果解析失败，尝试按行拆分。
    """
    if not llm_text:
        return [[] for _ in range(num_inputs)]
    
    text = llm_text.strip()
    # 尝试解析 JSON
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and len(parsed) == num_inputs:
            return [
                [str(k).strip() for k in item if isinstance(k, str) and k.strip()]
                for item in parsed
            ]
    except (json.JSONDecodeError, TypeError):
        pass
    
    # JSON 解析失败，尝试按行拆分
    lines = text.strip().split('\n')
    result = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 去掉行号前缀如 "1. " 或 "1: "
        line = re.sub(r'^\d+[.、:：\)\]]?\s*', '', line)
        kw = _parse_llm_response(line)
        if kw:
            result.append(kw)
        else:
            result.append([])
    
    # 补齐
    while len(result) < num_inputs:
        result.append([])
    return result[:num_inputs]


# ============================================================
# 公开 API
# ============================================================

def extract_keywords_for_tenant(text: str, tenant_id: str = "") -> list[str]:
    """对单条文本提取关键词（支持传入 config 对象作为 tenant_id）。

    核心逻辑：
    - 如果配置了 LLM（gemini 或 deepseek）且有 key → 调用 LLM
    - 否则走本地规则 _fallback_extract
    """
    if not text or not text.strip():
        return []

    # 兼容：tenant_id 可能是 config 对象或字符串
    if isinstance(tenant_id, str):
        provider = ""
        api_key = ""
        model_name = "deepseek-chat"
    else:
        cfg = tenant_id
        provider = (getattr(cfg, "llm_provider", "") or "").strip().lower()
        api_key = (getattr(cfg, "llm_api_key", "") or "").strip()
        model_name = (getattr(cfg, "llm_model", "") or "deepseek-chat").strip()

    # DeepSeek
    if provider == "deepseek" and api_key:
        messages = [
            {"role": "system", "content": "你是一个电商商品关键词提取助手。"},
            {"role": "user", "content": _PROMPT_TEMPLATE.format(text=text)},
        ]
        llm_text = _call_deepseek(messages, model=model_name, api_key=api_key)
        if llm_text:
            raw = _parse_llm_response(llm_text)
            result = _split_composite_tokens(raw)
            return _correct_llm_color_keywords(result, text)
        return _fallback_extract(text)

    # Gemini
    if provider == "gemini" and api_key and _GEMINI_OK:
        prompt = _PROMPT_TEMPLATE.format(text=text)
        messages = [
            {"role": "user", "content": prompt},
        ]
        llm_text = _call_gemini(messages, model=model_name, api_key=api_key)
        if llm_text:
            result = _parse_llm_response(llm_text)
            return _correct_llm_color_keywords(result, text)
        return _fallback_extract(text)

    # 默认：本地规则
    return _fallback_extract(text)


def extract_keywords_batch(texts: list[str], tenant_id: str = "") -> list[list[str]]:
    """批量提取关键词，返回与输入对应的关键词列表。

    核心逻辑：
    - 如果配置了 LLM（gemini 或 deepseek）且有 key → 调用 LLM 批量处理
    - 否则逐条走本地规则
    """
    if not texts:
        return []

    # 兼容：tenant_id 可能是 config 对象或字符串
    if isinstance(tenant_id, str):
        provider = ""
        api_key = ""
        model_name = "deepseek-chat"
    else:
        cfg = tenant_id
        provider = (getattr(cfg, "llm_provider", "") or "").strip().lower()
        api_key = (getattr(cfg, "llm_api_key", "") or "").strip()
        model_name = (getattr(cfg, "llm_model", "") or "deepseek-chat").strip()

    # DeepSeek
    if provider == "deepseek" and api_key:
        _llm_log_used = True
        _logger.info("Using DeepSeek for keyword extraction (batch=%d lines)", len(texts))
        batch_text = "\n".join(texts)
        messages = [
            {"role": "system", "content": "你是一个电商商品关键词提取助手。"},
            {"role": "user", "content": _PROMPT_TEMPLATE_BATCH.format(batch_text=batch_text)},
        ]
        llm_text = _call_deepseek(messages, model=model_name, api_key=api_key)
        if llm_text:
            _logger.info("DeepSeek call succeeded")
            parsed = _parse_llm_batch_response(llm_text, len(texts))
            # 对每个 LLM 返回为空的结果降级到本地规则，对非空结果进行 token 拆分
            results = []
            for i, kw in enumerate(parsed):
                if not kw:
                    _logger.warning("line %d: LLM returned empty, fallback to local", i)
                    results.append(_fallback_extract(texts[i]))
                else:
                    result = _split_composite_tokens(kw)
                    results.append(_correct_llm_color_keywords(result, texts[i]))
            return results
        # LLM 调用失败，全部降级
        _logger.warning("DeepSeek failed/timeout, falling back to local rules for ALL lines")
        return [_fallback_extract(t) for t in texts]

    # Gemini
    if provider == "gemini" and api_key and _GEMINI_OK:
        batch_text = "\n".join(texts)
        prompt = _PROMPT_TEMPLATE_BATCH.format(batch_text=batch_text)
        messages = [
            {"role": "user", "content": prompt},
        ]
        llm_text = _call_gemini(messages, model=model_name, api_key=api_key)
        if llm_text:
            parsed = _parse_llm_batch_response(llm_text, len(texts))
            results = []
            for i, kw in enumerate(parsed):
                if not kw:
                    results.append(_fallback_extract(texts[i]))
                else:
                    result = _split_composite_tokens(kw)
                    results.append(_correct_llm_color_keywords(result, texts[i]))
            return results
        return [_fallback_extract(t) for t in texts]

    # 默认：本地规则
    return [_fallback_extract(t) for t in texts]
