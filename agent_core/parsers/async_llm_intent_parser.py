"""
异步 LLM 意图识别解析器

能力项：意图识别（异步版本）
输入：用户 query + business_code + 专业训练 Prompt
输出：意图标签 + 置信度
实现：基于 Prompt 工程 + 结构化输出 + 异步调用

使用专业训练 Prompt 提高准确率
"""
from typing import Dict, Any, Optional
import json
import os
import logging

logger = logging.getLogger(__name__)


class AsyncLLMIntentParser:
    """异步意图解析器"""
    
    def __init__(self, async_llm_client):
        """
        初始化异步意图解析器
        
        Args:
            async_llm_client: 异步 LLM 客户端实例
        """
        self.llm_client = async_llm_client
        # 加载通用训练 Prompt
        self.common_prompt = self._load_prompt("references/framework/common_train_prompt.md")
        # 加载业务专属 Prompt
        self.business_prompts = {}
    
    def _load_prompt(self, path: str) -> str:
        """
        加载 Prompt 文件
        
        Args:
            path: Prompt 文件路径
            
        Returns:
            Prompt 内容
        """
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
        except Exception as e:
            logger.warning(f"加载 Prompt 失败 ({path}): {e}")
        return ""
    
    def _load_business_prompt(self, business_code: str):
        """
        加载业务专属 Prompt
        
        Args:
            business_code: 业务代码
        """
        if business_code not in self.business_prompts:
            path = f"references/business/{business_code}_train_prompt.md"
            self.business_prompts[business_code] = self._load_prompt(path)
    
    async def parse_intent(
        self, 
        user_input: str, 
        business_code: str, 
        available_skills: list = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        异步意图识别：识别用户指令的核心意图（查询/执行）
        
        输入：
            user_input: 用户 query，如 "给用户123456发放礼物40001"
            business_code: 业务代码，如 "testops"
            available_skills: 可用的 Skill 列表
            context: 上下文信息
            
        输出：
            {
                "skill_name": str,      # 意图标签（Skill名称）
                "skill_type": str,      # "query" | "execute"
                "confidence": float,    # 置信度 0.0-1.0
                "reason": str,         # 识别理由
                "params": dict         # 提取的参数
            }
            
        实现：基于专业训练 Prompt + DeepSeek 结构化输出 + 异步调用
        """
        # 加载业务专属 Prompt
        self._load_business_prompt(business_code)
        business_prompt = self.business_prompts.get(business_code, "")
        
        # 构建完整的 Prompt
        prompt = f"""{self.common_prompt}

---

{business_prompt}

---

## 当前任务

**用户输入**：{user_input}

**可用 Skills**：
{self._format_skills(available_skills)}

**上下文**：{json.dumps(context or {}, ensure_ascii=False)}

---

## 输出要求

请严格按照上述规范分析用户意图，返回 JSON 格式：

```json
{{
  "skill_name": "识别的 Skill 名称（必须从上述 Skill 列表中选择）",
  "skill_type": "query 或 execute",
  "params": {{
    "参数名1": "参数值（严格匹配格式要求）",
    "参数名2": "参数值"
  }},
  "confidence": 0.99,
  "reason": "识别理由"
}}
```

**注意**：
1. skill_name 必须从可用 Skills 列表中选择
2. 参数格式必须严格遵守规范（如礼物 ID 必须是纯数字）
3. 置信度要准确反映识别的确定性
4. 如果无法识别，skill_name 填 "unknown"，confidence 填 0.0
"""
        
        messages = [{"role": "user", "content": prompt}]
        
        # 异步调用 LLM
        response = await self.llm_client.chat(messages, temperature=0.1)  # 降低温度提高稳定性
        
        try:
            # 提取 JSON
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(response[json_start:json_end])
                result["raw_input"] = user_input
                return result
        except Exception as e:
            logger.error(f"意图解析失败: {e}")
            logger.debug(f"LLM 响应: {response}")
        
        return {
            "skill_name": "unknown",
            "skill_type": "query",
            "confidence": 0.0,
            "params": {},
            "reason": "解析失败",
            "raw_input": user_input
        }
    
    def _format_skills(self, available_skills: list) -> str:
        """
        格式化 Skills 列表
        
        Args:
            available_skills: Skills 列表
            
        Returns:
            格式化后的字符串
        """
        if not available_skills:
            return "无"
        
        formatted = []
        for skill in available_skills:
            formatted.append(
                f"- {skill.get('skill_name')}: {skill.get('description')} "
                f"[{skill.get('skill_type')}]"
            )
        
        return "\n".join(formatted)
