"""Configurable OpenAI-compatible access and explicit offline intent parsing."""
import json
import re
import hashlib
import uuid
from typing import Any, Dict, Optional

from agent_core.layers import LocalConfigLayer


class DeepSeekLLM:
    """Compatibility name retained; transport supports configurable providers."""

    FEW_SHOT_PROMPT = """你是测试 Agent 的意图解析器。
将用户输入解析为 JSON: {"intent": "...", "tool_name": "...", "params": {}, "is_chat": false}
示例:
用户: 扫描测试脚本 -> {"intent":"script_scan","tool_name":"script_scan","params":{},"is_chat":false}
用户: 帮我找礼物后台地址 -> {"intent":"backend_feature","tool_name":"backend_feature","params":{"keyword":"礼物"},"is_chat":false}
用户: 你好 -> {"intent":"chat","tool_name":"native_chat","params":{},"is_chat":true}
"""

    def __init__(self, config: Optional[LocalConfigLayer] = None, transport=None):
        self.config = config or LocalConfigLayer()
        self.mode = self.config.get_secret("llm_mode", "LLM_MODE", "offline")
        if self.mode not in {"offline", "remote"}:
            raise ValueError("LLM_MODE must be offline or remote")
        self.transport = transport
        self.tool_catalog = []
        self._session_id = str(uuid.uuid4())

    def _setting(self, name, default=None):
        return self.config.get_secret("llm_" + name, "LLM_" + name.upper()) or self.config.get_secret("opencode_" + name, "OPENCODE_" + name.upper(), default)

    async def _completion(self, messages, structured=False, context=None, **options):
        import httpx
        key, base, model = self._setting("api_key"), self._setting("base_url"), self._setting("model")
        if not all((key, base, model)):
            raise ValueError("Remote LLM requires API key, base URL and model")
        from urllib.parse import urlparse
        parsed = urlparse(base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid LLM base URL")
        body = {"model": model, "messages": messages, "max_tokens": 512}
        if structured:
            body["response_format"] = {"type": "json_object"}
        body.update(options)
        context = context or {}
        session_key = json.dumps([context.get("operator", "local"), context.get("session_id", self._session_id)])
        headers = {"Authorization": "Bearer " + key, "User-Agent": "testops-agent/2.0"}
        if parsed.hostname == "opencode.ai":
            headers["x-opencode-session"] = hashlib.sha256(session_key.encode()).hexdigest()
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            response = await client.post(base.rstrip("/") + "/chat/completions", headers=headers, json=body)
            response.raise_for_status()
            return response.json()

    async def _request(self, messages, structured=False, context=None):
        response = await self._completion(messages, structured=structured, context=context)
        content = response["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Empty LLM response")
        return content

    async def classify_intent(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self.mode == "offline":
            return self.rule_based_intent(user_input)
        prompt = self.FEW_SHOT_PROMPT + "\n缺参保留为空，不猜测；只使用可用工具。所有 ID、quantity、num、count、duration_days 必须是 JSON 整数，不是字符串。quantity=背包数量；num=每次数量；count=执行次数；event_to_time=目标时间字符串。不要输出工具不需要的参数。"
        if self.tool_catalog:
            prompt += "\n可用工具：" + json.dumps(self.tool_catalog, ensure_ascii=False)
        content = await self._request([{"role": "system", "content": prompt}, {"role": "user", "content": user_input}], structured=True, context=context)
        return self._parse_json_response(content)

    async def chat(self, user_input: str, context=None) -> str:
        if self.mode == "offline":
            return "当前为离线规则模式，可以查询模拟礼物、调整活动时间，或在确认后模拟送礼。"
        return await self._request([{"role": "user", "content": user_input}], context=context)

    @staticmethod
    def _parse_json_response(content: str) -> Dict[str, Any]:
        text = content.strip()
        if text.startswith("```json") and text.endswith("```"):
            text = text[7:-3].strip()
        payload = json.loads(text)
        if not isinstance(payload, dict) or not isinstance(payload.get("params", {}), dict):
            raise ValueError("Invalid intent JSON")
        payload.setdefault("params", {})
        payload.setdefault("tool_name", payload.get("intent", ""))
        payload.setdefault("is_chat", payload.get("intent") == "chat")
        return payload

    @staticmethod
    def rule_based_intent(user_input: str) -> Dict[str, Any]:
        text = (user_input or "").strip()
        lower = text.lower()
        if "查询" in text and "脚本" in text and "记录" in text:
            return {"intent": "query_script_runs", "params": {}, "is_chat": False}
        if lower in {"hi", "hello"} or text in {"你好", "你是谁", "谢谢"}:
            return {"intent": "chat", "tool_name": "native_chat", "params": {}, "is_chat": True}
        if "脚本" in text and any(word in text for word in ("扫描", "列表", "有哪些")):
            return {"intent": "script_scan", "tool_name": "script_scan", "params": {}, "is_chat": False}
        if "脚本" in text and any(word in text for word in ("读取", "源码", "内容", "查看")):
            return {
                "intent": "script_read",
                "tool_name": "script_read",
                "params": {"script_path": DeepSeekLLM._extract_script_path(text)},
                "is_chat": False,
            }
        if "脚本" in text and any(word in text for word in ("执行", "运行")):
            return {
                "intent": "script_run",
                "tool_name": "script_run",
                "params": {"script_path": DeepSeekLLM._extract_script_path(text), "args": []},
                "is_chat": False,
            }
        if "查询" in text and "礼物" in text:
            user_id = DeepSeekLLM.extract_named_value(text, "user_id")
            return {"intent": "query_gift_records", "params": {"user_id": user_id} if user_id else {}, "is_chat": False}
        if "查询" in text and "活动" in text:
            return {"intent": "query_event", "params": {"event_id": DeepSeekLLM.extract_named_value(text, "event_id")}, "is_chat": False}
        if "背包" in text and "礼物" in text:
            return {"intent": "add_gift_to_backpack", "params": {
                "user_id": DeepSeekLLM.extract_named_value(text, "user_id"),
                "gift_id": DeepSeekLLM.extract_named_value(text, "gift_id"),
                "quantity": DeepSeekLLM.extract_named_value(text, "quantity"),
            }, "is_chat": False}
        if "专属礼物" in text or "专属tab" in text or "专属 tab" in lower:
            return {
                "intent": "execute_gift_issue",
                "tool_name": "add_gift_to_exclusive_tab",
                "params": {
                    "gift_id": DeepSeekLLM.extract_named_value(text, "gift_id"),
                    "user_id": DeepSeekLLM.extract_named_value(text, "user_id"),
                    "room_id": DeepSeekLLM.extract_named_value(text, "room_id"),
                    "duration_days": DeepSeekLLM.extract_named_value(text, "duration_days") or 7,
                },
                "is_chat": False,
            }
        if "活动" in text and any(word in text for word in ("偏移", "修改时间", "调整时间", "改时间")):
            return {
                "intent": "event_time_shift",
                "tool_name": "shift_event_time",
                "params": {
                    "event_id": DeepSeekLLM.extract_named_value(text, "event_id"),
                    "event_to_time": DeepSeekLLM.extract_named_value(text, "event_to_time"),
                },
                "is_chat": False,
            }
        if any(word in text for word in ("送礼物", "发送礼物", "刷礼物", "连送礼物")):
            return {
                "intent": "send_gifts",
                "tool_name": "send_gifts_to_one_room",
                "params": {
                    "gift_id": DeepSeekLLM.extract_named_value(text, "gift_id"),
                    "user_id": DeepSeekLLM.extract_named_value(text, "user_id"),
                    "room_id": DeepSeekLLM.extract_named_value(text, "room_id"),
                    "num": DeepSeekLLM.extract_named_value(text, "num") or 1,
                    "count": DeepSeekLLM.extract_named_value(text, "count"),
                },
                "is_chat": False,
            }
        if "后台" in text or "地址" in text or "入口" in text:
            keyword = text.replace("后台", "").replace("地址", "").replace("入口", "").strip() or text
            return {"intent": "backend_feature", "tool_name": "backend_feature", "params": {"keyword": keyword}, "is_chat": False}
        if any(word in text for word in ("select", "查询数据库", "查库")):
            return {"intent": "db_query", "tool_name": "db_query", "params": {"sql": text}, "is_chat": False}
        return {"intent": "unclear", "tool_name": "", "params": {}, "is_chat": False}

    @staticmethod
    def _extract_script_path(text: str) -> str:
        for token in re.findall(r"[\w./-]+\.py", text):
            return token
        return ""

    @staticmethod
    def extract_named_value(text: str, field: str):
        text = text or ""
        patterns = {
            "gift_id": [r"礼物\s*(?:id|ID)?\s*[:：= ]\s*(\d+)", r"礼物\s*(\d+)"],
            "user_id": [r"用户\s*(?:id|ID)?\s*[:：= ]\s*(\d+)", r"用户\s*(\d+)"],
            "room_id": [r"(?:直播间|房间)\s*(?:id|ID)?\s*[:：= ]\s*(\d+)", r"(?:直播间|房间)\s*(\d+)"],
            "event_id": [r"活动\s*(?:id|ID)?\s*[:：= ]\s*(\d+)", r"活动\s*(\d+)"],
            "duration_days": [r"有效期\s*(\d+)\s*天", r"(\d+)\s*天"],
            "num": [r"每次\s*(\d+)\s*个?", r"数量\s*[:：= ]\s*(\d+)"],
            "quantity": [r"(\d+)\s*个", r"数量\s*[:：= ]\s*(\d+)"],
            "count": [r"(\d+)\s*次", r"执行\s*(\d+)\s*次"],
        }
        if field == "event_to_time":
            match = re.search(r"(?:偏移到|改到|调整到|时间到)\s*([^，,。]+)", text)
            if match:
                return match.group(1).strip()
            if "明天" in text:
                return "明天"
            if "今天" in text:
                return "今天"
            return ""
        for pattern in patterns.get(field, []):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    return match.group(1)
        return None
