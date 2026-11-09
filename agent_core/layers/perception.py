"""Perception layer: chat routing, business hints, and native replies."""
from typing import Any, Dict, List, Optional


class PerceptionLayer:
    """Route business commands to skills and casual chat to the model."""

    CHAT_MARKERS = {
        "你好", "hi", "hello", "你是谁", "你能做什么", "谢谢", "辛苦了",
        "讲个笑话", "随便聊聊"
    }

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def is_chat_request(self, user_input: str, available_skills: List[Dict[str, Any]]) -> bool:
        text = (user_input or "").strip().lower()
        if not text:
            return False

        if text in {item.lower() for item in self.CHAT_MARKERS}:
            return True

        business_words = set()
        for skill in available_skills or []:
            business_words.update(str(w).lower() for w in skill.get("match_keywords", []))
            business_words.update(str(w).lower() for w in skill.get("match_entities", []))

        # If it contains a known business token, keep it on the skill path.
        if any(word and word in text for word in business_words):
            return False

        # Short non-business utterances are treated as chat.
        return len(text) <= 24 and not any(ch.isdigit() for ch in text)

    async def native_chat(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        system_prompt = (
            "你是一个测试 Agent 助手。闲聊时简洁回答；如果用户询问业务能力，"
            "提示可以查询用户、礼物、奖池、配置、后台链接，也可以执行受控测试操作。"
        )
        if not self.llm_client:
            return {
                "success": True,
                "status": "success",
                "message": "我在，可以帮你查询测试数据、准备测试资产或查后台入口。",
                "skill_name": "native_chat",
                "data": {}
            }

        try:
            reply = await self.llm_client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input}
                ],
                temperature=0.3,
                use_cache=False
            )
        except Exception:
            reply = "我在，可以帮你查询测试数据、准备测试资产或查后台入口。"

        return {
            "success": True,
            "status": "success",
            "message": reply,
            "skill_name": "native_chat",
            "data": {}
        }
