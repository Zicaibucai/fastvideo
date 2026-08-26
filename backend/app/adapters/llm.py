"""LLM 适配器：Kimi / DeepSeek / OpenAI（OpenAI 兼容）+ Mock。

接口：chat(messages, ...) / complete(prompt, ...)
"""

from __future__ import annotations

import time
from typing import Any

from app.adapters.base import BaseAIAdapter, MockMixin
from app.core.exceptions import AIProviderError
from app.core.logging import get_logger

logger = get_logger(__name__)


class LLMAdapter(BaseAIAdapter):
    provider = "openai"

    def is_available(self) -> bool:
        return bool(self.config.get("api_key"))

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> str:
        if not self.is_available():
            self._raise_unavailable("chat")

        from openai import OpenAI

        # DeepSeek V4 默认开启思考模式。结构化阶段需要把 token 留给 JSON，
        # 否则模型可能只返回分析过程，或在输出 JSON 前达到长度上限。
        if self.provider == "deepseek":
            kwargs = dict(kwargs)
            extra_body = dict(kwargs.get("extra_body") or {})
            extra_body.setdefault("thinking", {"type": "disabled"})
            kwargs["extra_body"] = extra_body

        # Kimi K3 的温度约束取决于 thinking：关闭 thinking 时只接受 0.6；
        # 提示词大师不需要额外的思考轨迹，因此用 0.6 保证直接返回结构化 JSON。
        if self.provider == "kimi":
            model_name = str(self.config.get("model") or "").strip().lower()
            if model_name in {"k3", "kimi-k3", "kimi-k2.5", "kimi-k2.6"}:
                temperature = 0.6
                kwargs = dict(kwargs)
                extra_body = dict(kwargs.get("extra_body") or {})
                extra_body.setdefault("thinking", {"type": "disabled"})
                kwargs["extra_body"] = extra_body

        client = OpenAI(
            api_key=self.config.get("api_key"),
            base_url=self.config.get("base_url") or None,
            timeout=self.config.get("timeout", 120),
        )
        try:
            resp = client.chat.completions.create(
                model=self.config.get("model", "gpt-4o-mini"),
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            message = resp.choices[0].message
            content = getattr(message, "content", None)
            if isinstance(content, list):
                # 兼容部分 OpenAI 兼容服务返回的 content block 数组。
                content = "\n".join(
                    item.get("text", "") if isinstance(item, dict) else str(item)
                    for item in content
                )
            if content:
                return str(content)
            # 推理型模型可能把可用文本放在 reasoning_content 中，交给上层
            # JSON 提取器处理其中的 JSON 部分。
            reasoning = getattr(message, "reasoning_content", None)
            if reasoning:
                return str(reasoning)
            refusal = getattr(message, "refusal", None)
            return str(refusal or "")
        except Exception as exc:
            logger.exception("llm_chat_error")
            raise AIProviderError(f"LLM 调用失败: {exc}") from exc

    def complete(self, prompt: str, **kwargs: Any) -> str:
        return self.chat(
            [{"role": "user", "content": prompt}],
            **kwargs,
        )


class DeepSeekLLMAdapter(LLMAdapter):
    """DeepSeek Chat Completions 适配器。

    DeepSeek 官方接口与 OpenAI SDK 兼容，因此复用 ``LLMAdapter`` 的请求、
    超时和异常处理；Factory 负责注入 DeepSeek 专属 Key、Base URL 和模型。
    """

    provider = "deepseek"


class KimiLLMAdapter(LLMAdapter):
    """Kimi 文本与多模态模型，复用 OpenAI 兼容 Chat Completions。

    Kimi Code 与 Moonshot 开放平台共用适配器，但认证地址和模型 ID 不同：
    ``sk-kimi-`` Key 必须走 ``/coding/v1``，Kimi Code 的 ``kimi-k3`` 展示名
    对应 API 模型 ID ``k3``。在这里统一规范化，避免设置页展示名直接导致 404。
    """

    provider = "kimi"
    supports_vision = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        api_key = str(self.config.get("api_key") or "").strip()
        base_url = str(self.config.get("base_url") or "").strip().rstrip("/")
        model = str(self.config.get("model") or "").strip()
        if api_key.startswith("sk-kimi-"):
            # Kimi Code Key 与 Moonshot 平台 Key 不能跨域调用；即使用户在
            # 设置页留下了 moonshot 地址，也优先按 Key 所属通道纠正。
            if "api.kimi.com/coding" not in base_url:
                base_url = "https://api.kimi.com/coding/v1"
            elif not base_url.endswith("/v1"):
                base_url = f"{base_url}/v1"
            self.config["base_url"] = base_url
            if model.lower() == "kimi-k3":
                self.config["model"] = "k3"

    def capabilities(self) -> dict[str, bool]:
        return {"chat": True, "vision": True, "structured_output": True}


class VolcengineVisionLLMAdapter(LLMAdapter):
    """火山方舟 Doubao-Seed-Vision 多模态聊天适配器。"""

    provider = "volcengine_vision"
    supports_vision = True

    def capabilities(self) -> dict[str, bool]:
        return {"chat": True, "vision": True, "structured_output": True}

    @staticmethod
    def _response_text(response: Any) -> str:
        """从 Ark Responses API 的 message output 中提取文本。"""
        direct_text = getattr(response, "output_text", None)
        if direct_text:
            return str(direct_text).strip()
        chunks: list[str] = []
        for item in getattr(response, "output", None) or []:
            item_type = getattr(item, "type", None)
            if isinstance(item, dict):
                item_type = item.get("type")
            if item_type != "message":
                continue
            for content in (item.get("content", []) if isinstance(item, dict) else getattr(item, "content", []) or []):
                content_type = getattr(content, "type", None)
                text = getattr(content, "text", None)
                if isinstance(content, dict):
                    content_type = content.get("type")
                    text = content.get("text")
                if content_type == "output_text" and text:
                    chunks.append(str(text))
        return "\n".join(chunks).strip()

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> str:
        """使用火山方舟 Responses API，将 Chat 消息转换为 input_* 内容。"""
        if not self.is_available():
            self._raise_unavailable("responses")
        try:
            from volcenginesdkarkruntime import Ark
        except ImportError as exc:  # pragma: no cover - requirements 安装失败时才触发
            raise AIProviderError(
                "火山方舟 SDK 未安装，请安装 volcengine-python-sdk[ark]。"
            ) from exc

        input_items: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "user")
            source_content = message.get("content")
            if isinstance(source_content, str):
                content = [{"type": "input_text", "text": source_content}]
            else:
                content = []
                for part in source_content or []:
                    part_type = part.get("type") if isinstance(part, dict) else getattr(part, "type", None)
                    if part_type in {"text", "input_text"}:
                        text = part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "")
                        content.append({"type": "input_text", "text": str(text)})
                    elif part_type in {"image_url", "input_image"}:
                        image = part.get("image_url") if isinstance(part, dict) else getattr(part, "image_url", None)
                        image_url = image.get("url") if isinstance(image, dict) else image
                        if image_url:
                            content.append({"type": "input_image", "image_url": str(image_url)})
            if content:
                input_items.append({"role": role, "content": content})

        client = Ark(
            base_url=self.config.get("base_url") or "https://ark.cn-beijing.volces.com/api/v3",
            api_key=self.config.get("api_key"),
            timeout=self.config.get("timeout", 180),
        )
        try:
            response = client.responses.create(
                model=self.config.get("model", ""),
                input=input_items,
                max_output_tokens=max_tokens,
                temperature=temperature,
                # 提示词大师只需要最终文本；关闭思考可避免把输出预算耗在
                # reasoning item 上，且与火山方舟官方视觉示例的 Responses API
                # 调用方式兼容。
                thinking={"type": "disabled"},
            )
            text = self._response_text(response)
            if text:
                return text
            raise AIProviderError("火山方舟返回了空文本，请检查模型输出或接入点配置。")
        except AIProviderError:
            raise
        except Exception as exc:
            logger.exception("volcengine_vision_responses_error")
            raise AIProviderError(f"火山方舟视觉模型调用失败: {exc}") from exc


class MockLLMAdapter(LLMAdapter, MockMixin):
    """Mock LLM：返回结构化的演示解说词，保证全流程可运行。"""

    provider = "mock"

    def is_available(self) -> bool:
        return True

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> str:
        # 提取最后一条用户消息作为提示
        user_text = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "",
        )
        return _mock_stage_output(user_text)

    def complete(self, prompt: str, **kwargs: Any) -> str:
        return _mock_stage_output(prompt)


def _mock_stage_output(prompt: str) -> str:
    """让本地演示也覆盖资料取证、编排和分章写作三个阶段。"""
    import json
    import re

    if "只对现有解说词重新划分镜头" in prompt:
        try:
            source_text = prompt.split("现有分镜：", 1)[1].strip()
            source = json.loads(source_text)
            shots = [
                {
                    "sequence": index,
                    "title": item.get("title", ""),
                    "section": item.get("section", ""),
                    "narration": item.get("narration", ""),
                    "durationSeconds": item.get("durationSeconds", 1),
                    "visualType": item.get("visualType", "generated_image"),
                    "visualDescription": item.get("visualDescription", ""),
                    "sourceShotSequences": [item.get("sequence", index)],
                }
                for index, item in enumerate(source, start=1)
            ]
            return json.dumps({"shots": shots}, ensure_ascii=False)
        except (ValueError, TypeError, json.JSONDecodeError, IndexError):
            pass

    if "独立的工程投标文案终审 agent" in prompt:
        return json.dumps({"issues": [], "unsupportedFacts": [], "patches": []}, ensure_ascii=False)

    if "独立终审 agent" in prompt and "待审全文 JSON：" in prompt:
        try:
            draft_text = prompt.split("待审全文 JSON：", 1)[1].lstrip()
            draft, _ = json.JSONDecoder().raw_decode(draft_text)
            return json.dumps(draft, ensure_ascii=False)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    if "工程投标资料证据审查员" in prompt and "只分析资料，不写解说词" in prompt:
        markers = re.findall(r"【chunk:([^\s】]+)", prompt)
        source_chunk_ids = list(dict.fromkeys(markers))[:3]
        source_body = prompt.split("原文批次：", 1)[-1].split("JSON格式：", 1)[0]
        body_lines = [
            line.strip()
            for line in source_body.splitlines()
            if line.strip() and not line.startswith("【chunk:") and not line.startswith("JSON格式")
        ]
        fact = next((line for line in body_lines if not line.startswith("{")), "原文批次内容")[:180]
        body_text = " ".join(body_lines)
        params = re.findall(r"\d+(?:\.\d+)?(?:万|平方米|㎡|米|层|天|日历天|台|吨|立方米)?", body_text)
        action_words = re.findall(r"开挖|支护|降水|浇筑|吊装|安装|焊接|穿插|运输|堆放|验收|调试|回填", body_text)
        topic = "基坑土方" if re.search(r"基坑|土方|开挖", prompt) else "总体部署"
        item = {
            "topic": topic,
            "fact": fact,
            "parameters": list(dict.fromkeys(params))[:8],
            "constructionActions": list(dict.fromkeys(action_words))[:6],
            "sequenceContext": "按原文批次保留前后工序关系",
            "sourceChunkIds": source_chunk_ids,
            "sourceReference": {"documentName": "招标文件", "page": 1, "locationLabel": "P1", "quote": fact[:80]},
            "factCheckStatus": "partial",
        }
        return json.dumps({"evidenceItems": [item] if source_chunk_ids else [], "rejectedFacts": []}, ensure_ascii=False)

    if "只做资料分析，不写解说词" in prompt:
        area = re.search(r"area_building:\s*([0-9,.]+)㎡", prompt)
        duration = re.search(r"duration_total:\s*([0-9,.]+)", prompt)
        items = []
        if area:
            items.append({"topic": "项目概况", "fact": f"总建筑面积 {area.group(1)} 平方米", "parameters": [f"{area.group(1)}平方米"], "constructionActions": [], "sequenceContext": "项目整体范围", "sourceReference": {"documentName": "招标文件", "page": 1, "locationLabel": "P1", "quote": area.group(0)}, "factCheckStatus": "partial"})
        if duration:
            items.append({"topic": "工期节点", "fact": f"总工期 {duration.group(1)} 日历天", "parameters": [f"{duration.group(1)}日历天"], "constructionActions": ["穿插"], "sequenceContext": "按关键线路组织", "sourceReference": {"documentName": "招标文件", "page": 1, "locationLabel": "P1", "quote": duration.group(0)}, "factCheckStatus": "partial"})
        return json.dumps({"evidenceItems": items, "rejectedFacts": []}, ensure_ascii=False)

    if "此阶段只生成章节大纲" in prompt:
        target = int((re.search(r"目标时长：([0-9]+)", prompt) or [None, "540"])[1])
        titles = ["项目概况", "总体部署", "工期节点", "平面与垂直运输", "基础与关键工艺", "主体与专业穿插", "BIM质量安全管理", "履约收束"]
        weights = [.08, .11, .12, .12, .20, .16, .16, .05]
        chapters = [{"sequence": i, "title": title, "durationSeconds": max(15, round(target * weights[i - 1])), "targetCharacters": max(60, round(target * weights[i - 1] / 60 * 215)), "writingGoal": "围绕施工对象、顺序和控制要点组织内容", "scoringFocus": [], "visualPlan": "BIM施工推演与现场工序画面", "evidenceIndexes": []} for i, title in enumerate(titles, 1)]
        return json.dumps({"totalDurationSeconds": target, "targetCharacters": round(target / 60 * 215), "chapters": chapters}, ensure_ascii=False)

    if "请只写本章，不要写其它章节" in prompt:
        section = (re.search(r"章节：([^\n]+)", prompt) or [None, "施工组织"])[1].strip()
        start = int((re.search(r"分镜序号从\s*([0-9]+)", prompt) or [None, "1"])[1])
        count = int((re.search(r"分镜数量：\s*([0-9]+)", prompt) or [None, "2"])[1])
        duration = int((re.search(r"时长：\s*([0-9]+)", prompt) or [None, "30"])[1])
        shots = []
        for index in range(count):
            shots.append({"sequence": start + index, "title": section[:12], "section": section, "narration": f"画面展示{section}。结合已上传文件，明确作业区域、工序衔接和检查节点。相关参数以文件来源为准。", "durationSeconds": max(5, round(duration / count)), "visualType": "bim_animation", "visualDescription": f"{section}施工推演画面", "imagePrompt": f"{section} BIM施工组织示意", "videoPrompt": f"{section}工序推演动画", "keywords": [section, "施工组织"], "scoringPointIds": [], "sourceReferences": [{"documentId": "tender", "documentName": "招标文件", "page": 1, "locationLabel": "P1", "quote": section}], "factCheckStatus": "partial"})
        return json.dumps({"shots": shots, "unverifiedFacts": []}, ensure_ascii=False)

    return _mock_narration(prompt)


def _mock_narration(prompt: str) -> str:
    """根据提示词生成演示用的完整解说词 JSON（含来源引用与事实校验状态）。

    输出符合 narration_engine 的严格 Schema，每个分镜包含 title/section/narration/
    visualType/visualDescription/imagePrompt/videoPrompt/keywords/sourceReferences/
    factCheckStatus/scoringPointIds。
    """
    import json

    # 尝试从 prompt 中解析工程参数（演示数据）
    import re

    def grab(*patterns: str) -> str:
        for pattern in patterns:
            m = re.search(pattern, prompt)
            if m:
                return m.group(1).strip()
        return ""

    project_name = grab(
        r"project_name:\s*([^\n\[]+)",
        r"(?:项目名称|工程名称)[：:\s]*([^\n，。；]{2,40})",
    ) or "某公共建筑项目"
    bidder = grab(
        r"bidder_name:\s*([^\n\[]+)",
        r"招标人[：:\s]*([^\n，。；]{2,40})",
    ) or "某市住房和城乡建设局"
    area = grab(
        r"area_building:\s*([0-9][0-9,.]*)\s*㎡",
        r"(?:建筑面积|总建筑面积)[：:\s]*([0-9][0-9,.]*)\s*(?:㎡|平方米|m2)",
    ) or "52800"
    duration = grab(
        r"duration_total:\s*([0-9]{2,4})",
        r"总工期[：:\s]*([0-9]{2,4})\s*(?:日历天|天)",
    ) or "540"
    location = grab(
        r"建设地点[：:\s]*([^\n，。；]{2,40})",
        r"位于([^\n，。；]{2,40})",
    ) or "某市核心区"
    height = grab(
        r"height[^:：\n]*[：:\s]*([0-9.]+)\s*(?:m|米)",
        r"建筑高度[：:\s]*([0-9.]+)\s*(?:m|米)",
    ) or "96.5"
    floors = grab(
        r"floors[^:：\n]*[：:\s]*([0-9]{1,2})",
        r"(?:层数|地上)[：:\s]*([0-9]{1,2})\s*层",
    ) or "22"

    shots = [
        {
            "sequence": 1,
            "title": "项目片头",
            "section": "片头",
            "narration": f"尊敬的评标委员会，我们谨向各位汇报{project_name}工程的投标方案。",
            "durationSeconds": 10,
            "visualType": "title",
            "visualDescription": "项目名称主题字幕，配建筑轮廓背景",
            "imagePrompt": "现代公共建筑夜景鸟瞰，庄重大气",
            "videoPrompt": "无人机环绕建筑旋转，缓慢上升",
            "keywords": ["片头", "项目名称"],
            "scoringPointIds": [],
            "sourceReferences": [],
            "factCheckStatus": "verified",
        },
        {
            "sequence": 2,
            "title": "项目概况",
            "section": "项目概况",
            "narration": f"本工程由{bidder}投资建设，位于{location}，总建筑面积约{area}平方米，建筑高度约{height}米，地上{floors}层。",
            "durationSeconds": 30,
            "visualType": "model_image",
            "visualDescription": "BIM 模型整体展示",
            "imagePrompt": "建筑 BIM 模型整体外观，带标注",
            "videoPrompt": "BIM 模型 360 度旋转展示",
            "keywords": ["建筑面积", "建筑高度", "层数", "建设地点"],
            "scoringPointIds": [0],
            "sourceReferences": [
                {
                    "documentId": "tender",
                    "documentName": "招标文件",
                    "page": 1,
                    "locationLabel": "P1",
                    "quote": f"总建筑面积约{area}平方米",
                }
            ],
            "factCheckStatus": "verified",
        },
        {
            "sequence": 3,
            "title": "总体施工部署",
            "section": "施工部署",
            "narration": "我们将围绕总工期{time_days}天目标，组建高效项目管理团队，采用分段流水与平行穿插相结合的施工部署。".replace("{time_days}", duration),
            "durationSeconds": 30,
            "visualType": "generated_image",
            "visualDescription": "施工平面布置示意",
            "imagePrompt": "施工总平面布置图，塔吊、临建、材料堆场布局",
            "videoPrompt": "施工部署动画，资源进场时序",
            "keywords": ["施工部署", "流水施工"],
            "scoringPointIds": [0, 1],
            "sourceReferences": [
                {
                    "documentId": "tender",
                    "documentName": "招标文件",
                    "page": 2,
                    "locationLabel": "P2",
                    "quote": f"总工期{duration}日历天",
                }
            ],
            "factCheckStatus": "verified",
        },
        {
            "sequence": 4,
            "title": "施工总平面布置",
            "section": "施工部署",
            "narration": "施工总平面布置遵循紧凑高效、安全文明原则，合理划分施工作业区、材料堆放区与办公生活区。",
            "durationSeconds": 25,
            "visualType": "infographic",
            "visualDescription": "总平面布置图信息图表",
            "imagePrompt": "施工总平面布置平面图，图例清晰",
            "videoPrompt": "平面布置逐层展开动画",
            "keywords": ["总平面布置"],
            "scoringPointIds": [0],
            "sourceReferences": [],
            "factCheckStatus": "verified",
        },
        {
            "sequence": 5,
            "title": "项目特点",
            "section": "项目特点",
            "narration": f"本项目具有体量大、标准高、专业系统复杂等特点，对施工组织与协调能力提出较高要求。",
            "durationSeconds": 25,
            "visualType": "site_photo",
            "visualDescription": "现场场地条件照片",
            "imagePrompt": "施工现场现状航拍",
            "videoPrompt": "场地现状及周边环境拍摄",
            "keywords": ["项目特点"],
            "scoringPointIds": [0],
            "sourceReferences": [],
            "factCheckStatus": "partial",
        },
        {
            "sequence": 6,
            "title": "项目重难点分析",
            "section": "项目重难点",
            "narration": "针对深基坑支护、大体量混凝土浇筑、机电管线综合平衡等重难点，我们制定专项技术措施。",
            "durationSeconds": 35,
            "visualType": "generated_image",
            "visualDescription": "重难点专项技术示意",
            "imagePrompt": "深基坑支护与混凝土浇筑技术示意图",
            "videoPrompt": "重难点技术措施三维动画",
            "keywords": ["重难点", "深基坑", "混凝土"],
            "scoringPointIds": [0],
            "sourceReferences": [],
            "factCheckStatus": "unverified",
        },
        {
            "sequence": 7,
            "title": "施工阶段及工序",
            "section": "施工方案",
            "narration": "工程划分为基础、主体、装饰装修与机电安装三大施工阶段，采用网络计划关键线路法组织工序穿插。",
            "durationSeconds": 30,
            "visualType": "infographic",
            "visualDescription": "施工阶段划分与工序穿插图",
            "imagePrompt": "施工阶段横道图与工序逻辑关系图",
            "videoPrompt": "施工进度模拟动画",
            "keywords": ["施工阶段", "工序"],
            "scoringPointIds": [0, 1],
            "sourceReferences": [],
            "factCheckStatus": "verified",
        },
        {
            "sequence": 8,
            "title": "关键技术措施",
            "section": "施工方案",
            "narration": "大力推广 BIM 技术、装配式施工与智慧工地管理，以科技手段保障工程质量与安全。",
            "durationSeconds": 30,
            "visualType": "bim_animation",
            "visualDescription": "BIM 技术应用动画",
            "imagePrompt": "BIM 三维模型与智慧工地大屏",
            "videoPrompt": "BIM 管综优化与施工模拟动画",
            "keywords": ["BIM", "智慧工地", "装配式"],
            "scoringPointIds": [4],
            "sourceReferences": [],
            "factCheckStatus": "partial",
        },
        {
            "sequence": 9,
            "title": "工期质量安全保障",
            "section": "保证措施",
            "narration": "我们承诺按期交付优质工程，建立健全质量安全管理体系，确保工程一次成优、安全零事故。",
            "durationSeconds": 30,
            "visualType": "site_photo",
            "visualDescription": "质量安全标准化现场",
            "imagePrompt": "标准化施工现场与安全标语",
            "videoPrompt": "质量安全措施实景展示",
            "keywords": ["工期", "质量", "安全"],
            "scoringPointIds": [2, 3],
            "sourceReferences": [
                {
                    "documentId": "tender",
                    "documentName": "招标文件",
                    "page": 3,
                    "locationLabel": "P3",
                    "quote": "质量目标：确保省级优质工程",
                }
            ],
            "factCheckStatus": "partial",
        },
        {
            "sequence": 10,
            "title": "履约承诺与片尾",
            "section": "片尾",
            "narration": "我们郑重承诺，严格履约、诚信经营，以优质工程回报业主信任，共创城市美好未来。",
            "durationSeconds": 15,
            "visualType": "title",
            "visualDescription": "企业理念与承诺字幕",
            "imagePrompt": "企业团队形象，庄重大气",
            "videoPrompt": "企业宣传片尾收束",
            "keywords": ["承诺", "片尾"],
            "scoringPointIds": [6],
            "sourceReferences": [],
            "factCheckStatus": "verified",
        },
    ]
    return json.dumps(
        {
            "projectSummary": f"{project_name}工程施工总承包投标视频，时长约5分钟。",
            "totalDurationSeconds": 260,
            "totalNarrationCharacters": sum(len(s["narration"]) for s in shots),
            "unverifiedFacts": ["深基坑支护专项方案细节", "重难点技术措施细节"],
            "shots": shots,
        },
        ensure_ascii=False,
    )
