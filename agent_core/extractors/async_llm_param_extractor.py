"""
异步 LLM 参数提取器

能力项：参数抽取（异步版本）
输入：用户 query + 意图 + 参数定义
输出：结构化参数字典
实现：基于 Prompt 工程 + 结构化输出 + 异步调用

使用专业训练 Prompt 提高准确率
"""
from typing import Dict, Any, Optional
import json
import os
import logging

logger = logging.getLogger(__name__)


class AsyncLLMParamExtractor:
    """异步参数提取器"""
    
    def __init__(self, async_llm_client):
        """
        初始化异步参数提取器
        
        Args:
            async_llm_client: 异步 LLM 客户端实例
        """
        self.llm_client = async_llm_client
        # 加载通用训练 Prompt
        self.common_prompt = self._load_prompt("references/framework/common_train_prompt.md")
        # 加载业务专属 Prompt
        self.business_prompts = {}
        # 缓存礼物类型规则Prompt
        self._gift_type_rules_cache = {}
    
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
    
    def _build_gift_type_rules_prompt(self, business_code: str) -> str:
        """
        从配置文件构建礼物类型规则说明（动态生成）
        
        Args:
            business_code: 业务代码
            
        Returns:
            礼物类型规则说明文本
        """
        # 检查缓存
        if business_code in self._gift_type_rules_cache:
            return self._gift_type_rules_cache[business_code]
        
        try:
            from business_logic.common.gift_type_config_loader import GiftTypeConfigLoader
            
            # 加载礼物类型规则
            gift_types = GiftTypeConfigLoader.get_gift_types(business_code)
            
            # 动态生成规则说明
            rules = []
            for prefix, config in sorted(gift_types.items()):
                rule_text = f"   - {prefix} 开头 → {config.get('name')}"
                
                # 添加issue_type信息（仅对支持专属tab的类型）
                if config.get("support_exclusive_tab"):
                    target_type = config.get("target_type", "user")
                    if target_type == "user":
                        rule_text += "（issue_type=user）"
                    elif target_type == "room":
                        rule_text += "（issue_type=room）"
                    elif target_type == "user_or_room":
                        rule_text += "（issue_type=random）"
                
                # 添加背包支持信息
                if config.get("support_backpack"):
                    rule_text += " - 可发放到背包"
                
                rules.append(rule_text)
            
            rules_text = "\n".join(rules)
            
            # 缓存结果
            self._gift_type_rules_cache[business_code] = rules_text
            
            logger.debug(f"✓ 礼物类型规则Prompt已生成 (business: {business_code})")
            return rules_text
            
        except Exception as e:
            logger.error(f"构建礼物类型规则Prompt失败: {e}")
            # 使用配置加载器的默认配置（保持向后兼容）
            try:
                # 尝试使用默认配置
                default_gift_types = GiftTypeConfigLoader._get_default_config().get("gift_types", {})
                rules = []
                for prefix, config in sorted(default_gift_types.items()):
                    rule_text = f"   - {prefix} 开头 → {config.get('name')}"
                    if config.get("support_exclusive_tab"):
                        target_type = config.get("target_type", "user")
                        if target_type == "user":
                            rule_text += "（issue_type=user）"
                        elif target_type == "room":
                            rule_text += "（issue_type=room）"
                        elif target_type == "user_or_room":
                            rule_text += "（issue_type=random）"
                    if config.get("support_backpack"):
                        rule_text += " - 可发放到背包"
                    rules.append(rule_text)
                return "\n".join(rules)
            except Exception as e2:
                logger.error(f"加载默认配置也失败: {e2}")
                # 最后的fallback：返回空字符串
                return ""
    
    async def extract_params(
        self, 
        user_input: str, 
        skill_name: str,
        param_schema: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        异步参数抽取：从用户输入中提取结构化参数
        
        输入：
            user_input: 用户 query，如 "给用户123456发放礼物40001"
            skill_name: 意图（Skill名称），如 "add_backpack_gift"
            param_schema: 参数定义，定义需要提取的参数及类型
            context: 上下文信息
            
        输出：
            结构化参数字典，如：
            {
                "user_id": 123456,
                "gift_id": 40001,
                "num": 1
            }
            
        实现：基于专业训练 Prompt + DeepSeek 结构化输出 + 异步调用
        """
        # 获取业务代码
        business_code = context.get("business_code") if context else None
        if not business_code:
            return {}
        
        # 加载业务专属 Prompt
        self._load_business_prompt(business_code)
        business_prompt = self.business_prompts.get(business_code, "")
        
        # 动态生成礼物类型规则说明
        gift_type_rules = self._build_gift_type_rules_prompt(business_code)
        
        # 构建完整的 Prompt
        prompt = f"""{self.common_prompt}

---

{business_prompt}

---

## 当前任务：参数提取

**用户输入**：{user_input}

**Skill 名称**：{skill_name}

**参数 Schema**：
{json.dumps(param_schema, ensure_ascii=False, indent=2)}

**上下文**：{json.dumps(context or {}, ensure_ascii=False)}

---

## 输出要求

请严格按照上述参数格式规范从用户输入中提取参数，返回 JSON 格式：

```json
{{
  "参数名1": "参数值（严格匹配格式要求）",
  "参数名2": "参数值"
}}
```

**注意**：
1. 参数格式必须严格遵守规范（如礼物 ID 必须是纯数字）
2. 礼物 ID 根据开头数字自动识别类型：
{gift_type_rules}
3. 多个礼物发放：
   - 如果用户输入包含多个礼物ID（如"301，30140，40109"），提取为 gift_ids 数组：[301, 30140, 40109]
   - 如果指定了不同数量（如"10个301，20个30140"），提取为 gift_nums 对象：{{"301": 10, "30140": 20}}
   - 单个礼物使用 gift_id（整数）
4. 有效期特殊值映射：
   - "永久"、"永久有效" → 1000
   - "一周" → 7
   - "一个月" → 30
5. 批量数量默认为 1，最大为 100
6. 缺少的参数不要填充默认值，让系统自动处理
7. 只返回 JSON，不要其他说明
"""
        
        messages = [{"role": "user", "content": prompt}]
        
        # 异步调用 LLM
        response = await self.llm_client.chat(messages, temperature=0.1)  # 降低温度提高稳定性
        
        try:
            # 提取 JSON
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                params = json.loads(response[json_start:json_end])
                
                # 自动识别礼物类型（如果有 gift_id 但没有 issue_type）
                if "gift_id" in params and "issue_type" not in params:
                    gift_id_str = str(params["gift_id"])
                    if gift_id_str.startswith("2"):
                        params["issue_type"] = "user"
                    elif gift_id_str.startswith("7"):
                        params["issue_type"] = "room"
                    elif gift_id_str.startswith("8"):
                        params["issue_type"] = "random"
                
                return params
        except Exception as e:
            logger.error(f"参数提取失败: {e}")
            logger.debug(f"LLM 响应: {response}")
        
        return {}
    
    def reload_gift_type_rules(self, business_code: str):
        """
        重新加载礼物类型规则（支持热更新）
        
        Args:
            business_code: 业务代码
        """
        if business_code in self._gift_type_rules_cache:
            del self._gift_type_rules_cache[business_code]
        
        # 重新生成规则
        self._build_gift_type_rules_prompt(business_code)
        logger.info(f"✓ 礼物类型规则Prompt已重新加载 (business: {business_code})")
