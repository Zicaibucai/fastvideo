"""LLM 适配器：OpenAI / DeepSeek（OpenAI 兼容）+ Mock。

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
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> str:
        if not self.is_available():
            self._raise_unavailable("chat")

        from openai import OpenAI

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
            return resp.choices[0].message.content or ""
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


class MockLLMAdapter(LLMAdapter, MockMixin):
    """Mock LLM：返回结构化的演示解说词，保证全流程可运行。"""

    provider = "mock"

    def is_available(self) -> bool:
        return True

    def chat(
        self,
        messages: list[dict[str, str]],
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
        return _mock_narration(user_text)

    def complete(self, prompt: str, **kwargs: Any) -> str:
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
