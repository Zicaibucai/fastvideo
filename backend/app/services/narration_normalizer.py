"""中文朗读规范化（NarrationNormalizer）。

把解说词中的数字、单位、日期、时间、百分数、金额、工期、
工程缩写、企业名称等转换为"可准确朗读的文本"。

原则：
- 只改变朗读文本，绝不修改分镜原始解说词。
- 工程数字、日期、单位、企业名称必须准确朗读。
- 解说词事实来源与工程参数不得在配音阶段被改写。
- 无法确定的缩写保留原读法并提示人工确认。
- 相同输入 + 相同规则 → 相同输出（确定性）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 中文字符映射
_CN_NUM = "零一二三四五六七八九"
_CN_UNIT_SMALL = ["", "十", "百", "千"]
_CN_UNIT_BIG = ["", "万", "亿", "万亿"]

# 已知工程缩写（保留原读法）
KNOWN_ABBREVIATIONS = {
    "BIM": "BIM",
    "EPC": "EPC",
    "PC": "PC",
    "MEP": "MEP",
    "CAD": "CAD",
    "GIS": "GIS",
    "GPS": "GPS",
    "VR": "VR",
    "AR": "AR",
    "TBM": "TBM",
    "BMS": "BMS",
    "HVAC": "HVAC",
    "LED": "LED",
    "PVC": "PVC",
    "PE": "PE",
    "HDPE": "HDPE",
    "CPVC": "CPVC",
}

# 常见混凝土强度等级（C 后接数字，如 C40混凝土）
_CONCRETE_GRADE = re.compile(r"\bC\s*(\d{1,3})混凝土", re.IGNORECASE)


@dataclass
class NormalizationResult:
    original_text: str
    normalized_text: str
    normalization_rules: list[dict[str, Any]] = field(default_factory=list)
    pronunciation_snapshot: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------- 数字转中文 ----------------

def _int_group_to_cn(n: int) -> str:
    """0-9999 转中文。"""
    if n == 0:
        return "零"
    if 10 <= n <= 19:
        # 10-19 读作"十X"而非"一十X"
        return "十" + (_CN_NUM[n % 10] if n % 10 else "")
    digits = [int(d) for d in str(n)]
    result = ""
    zero_pending = False
    length = len(digits)
    for i, d in enumerate(digits):
        pos = length - i - 1  # 0 为个位
        if d == 0:
            if pos != 0:
                zero_pending = True
            continue
        if zero_pending:
            result += "零"
            zero_pending = False
        result += _CN_NUM[d]
        result += _CN_UNIT_SMALL[pos]
    return result or "零"


def _int_to_cn_with_zero(n: int) -> str:
    """转中文，并在高组与低组之间补充零（如 10005 -> 一万零五）。"""
    if n == 0:
        return "零"
    if n < 0:
        return "负" + _int_to_cn_with_zero(-n)
    s = str(n)
    if len(s) <= 4:
        return _int_group_to_cn(n)
    result = ""
    # 从高位开始分段
    while len(s) > 4:
        head = s[:-4]
        tail = s[-4:]
        head_int = int(head)
        tail_int = int(tail)
        unit = _CN_UNIT_BIG[len(s) // 4]
        if head_int == 0:
            return result + _int_group_to_cn(tail_int)
        result += _int_group_to_cn(head_int) + unit
        if tail_int == 0:
            break
        if tail_int < 1000:
            result += "零"
        result += _int_group_to_cn(tail_int)
        break
    return result


def _decimal_to_cn(s: str) -> str:
    """小数部分逐位转中文（如 '14' -> 一四）。"""
    return "".join(_CN_NUM[int(d)] for d in s if d.isdigit())


def _number_to_cn(num_str: str) -> str:
    """把 '123' / '3.14' / '0.5' 转中文。"""
    if "." in num_str:
        int_part, dec_part = num_str.split(".", 1)
        int_cn = _int_to_cn_with_zero(int(int_part)) if int_part else "零"
        if dec_part:
            dec_cn = _decimal_to_cn(dec_part)
            return f"{int_cn}点{dec_cn}"
        return int_cn
    return _int_to_cn_with_zero(int(num_str))


def _format_number(value: float | int) -> str:
    """去掉多余小数位。"""
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return str(value)
    return str(value)


# ---------------- 内置规则 ----------------

# 每个内置规则: (pattern, repl, type, note)
# 注意顺序：先处理带单位/后缀的复合，再处理纯数字。

_BUILTIN_PATTERNS: list[tuple[str, str, str]] = [
    # 日期 2026年3月1日
    (
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        lambda m: f"{_number_to_cn(m.group(1))}年{_number_to_cn(m.group(2))}月{_number_to_cn(m.group(3))}日",
    ),
    (
        r"(\d{4})\s*年\s*(\d{1,2})\s*月",
        lambda m: f"{_number_to_cn(m.group(1))}年{_number_to_cn(m.group(2))}月",
    ),
    # 时间 14:30 / 14点30分
    (
        r"(\d{1,2}):(\d{2})(?![:\d])",
        lambda m: f"{_number_to_cn(m.group(1))}点{_number_to_cn(m.group(2))}分",
    ),
    (
        r"(\d{1,2})\s*点\s*(\d{1,2})\s*分",
        lambda m: f"{_number_to_cn(m.group(1))}点{_number_to_cn(m.group(2))}分",
    ),
    # 工期天数：365日历天 / 365天
    (
        r"(\d+(?:\.\d+)?)\s*日历天",
        lambda m: f"{_number_to_cn(m.group(1))}日历天",
    ),
    (
        r"(\d+(?:\.\d+)?)\s*个?\s*(工作日|天)",
        lambda m: f"{_number_to_cn(m.group(1))}个{m.group(2)}",
    ),
    # 面积：120000㎡ / 120000m² / 平方米
    (
        r"(\d+(?:\.\d+)?)\s*(?:㎡|m²|平方米)",
        lambda m: f"{_number_to_cn(m.group(1))}平方米",
    ),
    (
        r"(\d+(?:\.\d+)?)\s*(?:m³|立方米)",
        lambda m: f"{_number_to_cn(m.group(1))}立方米",
    ),
    # 米 / 毫米 / 千米 / 厘米
    (
        r"(\d+(?:\.\d+)?)\s*(?:km|千米)",
        lambda m: f"{_number_to_cn(m.group(1))}千米",
    ),
    (
        r"(\d+(?:\.\d+)?)\s*(?:mm|毫米)",
        lambda m: f"{_number_to_cn(m.group(1))}毫米",
    ),
    (
        r"(\d+(?:\.\d+)?)\s*(?:cm|厘米)",
        lambda m: f"{_number_to_cn(m.group(1))}厘米",
    ),
    (
        r"(\d+(?:\.\d+)?)\s*(?:m|米)(?![A-Za-z0-9])",
        lambda m: f"{_number_to_cn(m.group(1))}米",
    ),
    # 千牛 kN / 千牛
    (
        r"(\d+(?:\.\d+)?)\s*(?:kN|千牛)",
        lambda m: f"{_number_to_cn(m.group(1))}千牛",
    ),
    # 兆帕 MPa / 兆帕
    (
        r"(\d+(?:\.\d+)?)\s*(?:MPa|兆帕)",
        lambda m: f"{_number_to_cn(m.group(1))}兆帕",
    ),
    # 摄氏度 ℃
    (
        r"(\d+(?:\.\d+)?)\s*(?:℃|°C|摄氏度)",
        lambda m: f"{_number_to_cn(m.group(1))}摄氏度",
    ),
    # 百分数 99.5%
    (
        r"(\d+(?:\.\d+)?)\s*%",
        lambda m: f"百分之{_number_to_cn(m.group(1))}",
    ),
    # 楼层 32层
    (
        r"(\d{1,3})\s*层",
        lambda m: f"{_number_to_cn(m.group(1))}层",
    ),
    # 标段 第2标段 / 二标段
    (
        r"第\s*(\d{1,2})\s*标段",
        lambda m: f"第{_number_to_cn(m.group(1))}标段",
    ),
    (
        r"(\d{1,2})\s*标段",
        lambda m: f"{_number_to_cn(m.group(1))}标段",
    ),
    # 序号 第1名 / 第一名
    (
        r"第\s*(\d{1,2})\s*名",
        lambda m: f"第{_number_to_cn(m.group(1))}名",
    ),
    (
        r"第\s*(\d{1,3})",
        lambda m: f"第{_number_to_cn(m.group(1))}",
    ),
    # 金额 万元/亿元（万元常用语投标文件）
    (
        r"(\d+(?:\.\d+)?)\s*亿元",
        lambda m: f"{_number_to_cn(m.group(1))}亿元",
    ),
    (
        r"(\d+(?:\.\d+)?)\s*万元",
        lambda m: f"{_number_to_cn(m.group(1))}万元",
    ),
    (
        r"(\d+(?:\.\d+)?)\s*元",
        lambda m: f"{_number_to_cn(m.group(1))}元",
    ),
]


class NarrationNormalizer:
    """中文朗读规范化器。"""

    def __init__(self) -> None:
        self._builtin_compiled: list[tuple[re.Pattern, str | Any, str]] = []

    # ---------- 数字规则（含字母单位） ----------

    def _apply_builtin(self, text: str) -> tuple[str, list[dict]]:
        applied: list[dict] = []
        for pattern, repl in _BUILTIN_PATTERNS:
            compiled = re.compile(pattern)
            new_text = compiled.sub(repl, text)
            if new_text != text:
                applied.append(
                    {
                        "source": pattern,
                        "type": "builtin",
                        "scope": "system",
                    }
                )
                text = new_text
        return text, applied

    def _apply_concrete_grade(self, text: str) -> tuple[str, list[dict]]:
        """C40混凝土 → C四零混凝土（混凝土强度等级）。"""
        applied: list[dict] = []

        def _repl(m: re.Match) -> str:
            num = m.group(1)
            if num:
                digits_cn = "".join(_CN_NUM[int(d)] for d in num)
                applied.append({"source": m.group(0), "type": "concrete_grade", "scope": "system"})
                return f"C{digits_cn}混凝土"
            return m.group(0)

        new_text = _CONCRETE_GRADE.sub(_repl, text)
        return new_text, applied

    def _apply_abbreviations(self, text: str) -> tuple[str, list[dict], list[str]]:
        """已知工程缩写保留原读法（记录）；未知大写缩写提示人工确认。"""
        applied: list[dict] = []
        warnings: list[str] = []
        for abbr in sorted(KNOWN_ABBREVIATIONS, key=len, reverse=True):
            pattern = re.compile(rf"(?<![A-Za-z]){re.escape(abbr)}(?![A-Za-z])")
            if pattern.search(text):
                applied.append({"source": abbr, "type": "abbreviation", "scope": "system"})
        # 未知的连续大写缩写（3 个以上大写字母，非已知）
        for m in re.finditer(r"(?<![A-Za-z])([A-Z]{3,})(?![A-Za-z])", text):
            token = m.group(1)
            if token not in KNOWN_ABBREVIATIONS:
                warnings.append(f"缩写「{token}」未收录，保留原读法，请人工确认读音。")
        return text, applied, warnings

    def _apply_space_normalization(self, text: str) -> tuple[str, list[dict]]:
        """连续空格与异常换行归一化（保留段落停顿语义）。"""
        before = text
        # 合并连续空格；句末换行替换为分隔；多余空行压缩
        text = re.sub(r"[ \t　]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ ]*\n[ ]*", "\n", text)
        text = re.sub(r"[ \t　]+$", "", text, flags=re.M)
        applied = [] if text == before else [
            {"source": "space", "type": "space_normalize", "scope": "system"}
        ]
        return text, applied

    def _apply_custom_rules(
        self,
        text: str,
        rules: list[Any] | None,
    ) -> tuple[str, list[dict], list[str]]:
        """应用发音词典规则（项目/企业/系统，优先级从高到低）。

        rules 元素需具备：source_text, spoken_text, is_regex, priority, scope, id。
        返回规范化文本 + 快照 + 冲突提示。
        """
        if not rules:
            return text, [], []
        applied: list[dict] = []
        warnings: list[str] = []
        # 按优先级从高到低（数值大者优先），同优先级 project > enterprise > system
        scope_order = {"project": 0, "enterprise": 1, "system": 2}
        sorted_rules = sorted(
            rules,
            key=lambda r: (-r.priority, scope_order.get(r.scope, 9)),
        )
        seen_sources: set[str] = set()
        for rule in sorted_rules:
            source = rule.source_text
            spoken = rule.spoken_text
            if not source or not spoken:
                continue
            if rule.is_regex:
                try:
                    compiled = re.compile(source)
                except re.error:
                    warnings.append(f"正则表达式无效：{source}")
                    continue
                matched = compiled.search(text)
                if matched:
                    new_text = compiled.sub(lambda m: spoken, text)
                    if new_text != text:
                        applied.append(
                            {
                                "source": source,
                                "spoken": spoken,
                                "type": rule.rule_type,
                                "scope": rule.scope,
                                "rule_id": rule.id,
                                "is_regex": True,
                            }
                        )
                        text = new_text
            else:
                if source in text and source not in seen_sources:
                    text = text.replace(source, spoken)
                    applied.append(
                        {
                            "source": source,
                            "spoken": spoken,
                            "type": rule.rule_type,
                            "scope": rule.scope,
                            "rule_id": rule.id,
                            "is_regex": False,
                        }
                    )
                    seen_sources.add(source)
        return text, applied, warnings

    def normalize(
        self,
        text: str,
        rules: list[Any] | None = None,
    ) -> NormalizationResult:
        """对解说词做朗读规范化，返回结果与快照。"""
        original = text or ""
        warnings: list[str] = []
        rules_applied: list[dict] = []

        current = original
        # 1) 空间规范化
        current, r_applied = self._apply_space_normalization(current)
        rules_applied.extend(r_applied)

        # 2) 数字/单位/日期等内置规则
        current, r_applied = self._apply_builtin(current)
        rules_applied.extend(r_applied)

        # 3) 混凝土强度等级
        current, r_applied = self._apply_concrete_grade(current)
        rules_applied.extend(r_applied)

        # 4) 缩写
        current, r_applied, abbr_warnings = self._apply_abbreviations(current)
        rules_applied.extend(r_applied)
        warnings.extend(abbr_warnings)

        # 5) 自定义发音词典
        current, r_applied, dict_warnings = self._apply_custom_rules(current, rules)
        rules_applied.extend(r_applied)
        warnings.extend(dict_warnings)

        # 6) 兜底：残余的阿拉伯数字（未被规则覆盖的）转中文
        def _num_repl(m: re.Match) -> str:
            try:
                return _number_to_cn(m.group(0))
            except Exception:
                return m.group(0)

        new_current = re.sub(r"\d+(?:\.\d+)?", _num_repl, current)
        if new_current != current:
            rules_applied.append({"source": "remaining_digits", "type": "number", "scope": "system"})
            current = new_current

        return NormalizationResult(
            original_text=original,
            normalized_text=current,
            normalization_rules=rules_applied,
            pronunciation_snapshot=rules_applied,
            warnings=warnings,
        )


# 模块级单例
_normalizer: NarrationNormalizer | None = None


def get_normalizer() -> NarrationNormalizer:
    global _normalizer
    if _normalizer is None:
        _normalizer = NarrationNormalizer()
    return _normalizer


def normalize_narration(text: str, rules: list[Any] | None = None) -> NormalizationResult:
    return get_normalizer().normalize(text, rules)
