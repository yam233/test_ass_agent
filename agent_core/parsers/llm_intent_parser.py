"""
LLM 意图识别解析器

能力项：意图识别
输入：用户 query + business_code + 专业训练 Prompt
输出：意图标签 + 置信度
实现：基于 Prompt 工程 + 结构化输出

优化（2025-02-16）：
- 加载 llm_prompts.json 配置
- 添加负例说明
- 添加相似意图区分规则
- 提升准确率
"""
from typing import Dict, Any, Optional
import json
import os
import logging

logger = logging.getLogger(__name__)


class LLMIntentParser:
    """通用意图解析器"""
    
    def __init__(self, llm_client):
        self.llm_client = llm_client
        # 加载通用训练 Prompt
        self.common_prompt = self._load_prompt("references/framework/common_train_prompt.md")
        # 加载业务专属 Prompt
        self.business_prompts = {}
        # 加载 LLM Prompts 配置
        self.prompt_configs = {}
    
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
    
    def _load_prompt_config(self, business_code: str):
        """
        加载 LLM Prompts 配置
        
        Args:
            business_code: 业务代码
        """
        if business_code not in self.prompt_configs:
            try:
                from utils.config_loader import ConfigLoader
                config = ConfigLoader.load_business_config(
                    business_code,
                    "llm_prompts.json"
                )
                self.prompt_configs[business_code] = config
                logger.info(f"✓ LLM Prompts 配置已加载 (business: {business_code})")
            except Exception as e:
                logger.warning(f"加载 LLM Prompts 配置失败: {e}")
                self.prompt_configs[business_code] = {}
    
    def parse_intent(
        self, 
        user_input: str, 
        business_code: str, 
        available_skills: list = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        意图识别：识别用户指令的核心意图（查询/执行）
        
        输入：
            user_input: 用户 query，如 "给用户123456发放礼物40001"
            business_code: 业务代码，如 "ear_test"
            available_skills: 可用的Skill列表
            context: 上下文信息
            
        输出：
            {
                "skill_name": str,      # 意图标签（Skill名称）
                "skill_type": str,      # "query" | "execute"
                "confidence": float,    # 置信度 0.0-1.0
                "reason": str,         # 识别理由
                "params": dict         # 提取的参数
            }
            
        实现：基于专业训练 Prompt + 负例 + 区分规则 + DeepSeek 结构化输出
        """
        # 加载业务专属 Prompt
        self._load_business_prompt(business_code)
        business_prompt = self.business_prompts.get(business_code, "")
        
        # 加载 LLM Prompts 配置
        self._load_prompt_config(business_code)
        prompt_config = self.prompt_configs.get(business_code, {})
        intent_config = prompt_config.get("intent_recognition", {})
        
        # 构建增强的 Prompt
        prompt = self._build_enhanced_prompt(
            user_input,
            available_skills,
            context,
            business_prompt,
            intent_config
        )
        
        # 获取温度参数
        temperature = prompt_config.get("config", {}).get("temperature", 0.1)
        
        messages = [{"role": "user", "content": prompt}]
        response = self.llm_client.chat(messages, temperature=temperature)
        
        try:
            # 提取JSON
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
    
    def _build_enhanced_prompt(
        self,
        user_input: str,
        available_skills: list,
        context: Optional[Dict[str, Any]],
        business_prompt: str,
        intent_config: Dict[str, Any]
    ) -> str:
        """
        构建增强的 Prompt（包含负例和区分规则）
        
        Args:
            user_input: 用户输入
            available_skills: 可用 Skills
            context: 上下文
            business_prompt: 业务 Prompt
            intent_config: 意图识别配置
            
        Returns:
            增强的 Prompt
        """
        # 基础 Prompt
        prompt_parts = []
        
        # 系统 Prompt
        system_prompt = intent_config.get("system_prompt", "")
        if system_prompt:
            prompt_parts.append(f"## 系统角色\n\n{system_prompt}\n")
        
        # 通用训练 Prompt
        if self.common_prompt:
            prompt_parts.append(f"{self.common_prompt}\n")
        
        # 业务专属 Prompt
        if business_prompt:
            prompt_parts.append(f"{business_prompt}\n")
        
        # 负例说明
        if intent_config.get("negative_examples") and \
           intent_config.get("enable_negative_examples", True):
            prompt_parts.append(self._format_negative_examples(
                intent_config["negative_examples"]
            ))
        
        # 相似意图区分规则
        if intent_config.get("disambiguation_rules") and \
           intent_config.get("enable_disambiguation_rules", True):
            prompt_parts.append(self._format_disambiguation_rules(
                intent_config["disambiguation_rules"]
            ))
        
        # Skill 类型规则
        if intent_config.get("skill_type_rules"):
            prompt_parts.append(self._format_skill_type_rules(
                intent_config["skill_type_rules"]
            ))
        
        # 置信度调整规则
        if intent_config.get("confidence_adjustment"):
            prompt_parts.append(self._format_confidence_adjustment(
                intent_config["confidence_adjustment"]
            ))
        
        # 当前任务
        prompt_parts.append(f"""
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
  "params": {{}},
  "confidence": 0.99,
  "reason": "识别理由（说明为什么选择这个 Skill）"
}}
```

**注意**：
1. skill_name 必须从可用 Skills 列表中选择
2. 参考负例说明，避免常见错误
3. 参考区分规则，准确区分相似意图
4. 置信度要准确反映识别的确定性
5. 如果无法识别，skill_name 填 "unknown"，confidence 填 0.0
""")
        
        return "\n".join(prompt_parts)
    
    def _format_negative_examples(self, negative_examples: list) -> str:
        """格式化负例说明"""
        if not negative_examples:
            return ""
        
        lines = ["\n---\n", "## ⚠️ 负例说明（避免常见错误）\n"]
        for i, example in enumerate(negative_examples, 1):
            lines.append(f"\n**负例 {i}**:")
            lines.append(f"- 用户输入：{example['user_input']}")
            lines.append(f"- ❌ 错误识别：{example['wrong_skill']}")
            lines.append(f"- ✅ 正确识别：{example['correct_skill']}")
            lines.append(f"- 原因：{example['reason']}")
        
        return "\n".join(lines)
    
    def _format_disambiguation_rules(self, disambiguation_rules: list) -> str:
        """格式化相似意图区分规则"""
        if not disambiguation_rules:
            return ""
        
        lines = ["\n---\n", "## 🔍 相似意图区分规则\n"]
        for i, rule in enumerate(disambiguation_rules, 1):
            lines.append(f"\n**规则 {i}**: {rule['key_differentiator']}")
            lines.append(f"- 相似 Skills：{', '.join(rule['similar_skills'])}")
            lines.append("- 区分规则：")
            for r in rule.get("rules", []):
                lines.append(f"  - {r}")
            if rule.get("examples"):
                lines.append("- 示例：")
                for ex in rule["examples"]:
                    lines.append(f"  - {ex}")
        
        return "\n".join(lines)
    
    def _format_skill_type_rules(self, skill_type_rules: Dict[str, Any]) -> str:
        """格式化 Skill 类型规则"""
        if not skill_type_rules:
            return ""
        
        lines = ["\n---\n", "## 📋 Skill 类型规则\n"]
        for skill_type, rule in skill_type_rules.items():
            lines.append(f"\n**{skill_type.upper()}** ({rule['description']}):")
            lines.append(f"- 关键词：{', '.join(rule['keywords'])}")
        
        return "\n".join(lines)
    
    def _format_confidence_adjustment(self, confidence_adjustment: Dict[str, Any]) -> str:
        """格式化置信度调整规则"""
        if not confidence_adjustment:
            return ""
        
        lines = ["\n---\n", "## 📊 置信度评估指南\n"]
        
        if confidence_adjustment.get("high_confidence_indicators"):
            lines.append("\n**高置信度指标**（confidence >= 0.9）:")
            for indicator in confidence_adjustment["high_confidence_indicators"]:
                lines.append(f"- {indicator}")
        
        if confidence_adjustment.get("low_confidence_indicators"):
            lines.append("\n**低置信度指标**（confidence < 0.7）:")
            for indicator in confidence_adjustment["low_confidence_indicators"]:
                lines.append(f"- {indicator}")
        
        return "\n".join(lines)
    
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

