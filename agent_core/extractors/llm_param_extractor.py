"""
LLM 参数提取器

能力项：参数抽取
输入：用户 query + 意图 + 参数定义
输出：结构化参数字典
实现：基于 Prompt 工程 + 结构化输出

使用专业训练 Prompt 提高准确率
"""
from typing import Dict, Any, Optional
import json
import os


class LLMParamExtractor:
    """通用参数提取器"""
    
    def __init__(self, llm_client):
        self.llm_client = llm_client
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
            print(f"加载 Prompt 失败 ({path}): {e}")
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
    
    def extract_params(
        self, 
        user_input: str, 
        skill_name: str,
        param_schema: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        参数抽取：从用户输入中提取结构化参数
        
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
            
        实现：基于专业训练 Prompt + DeepSeek 结构化输出
        """
        # 获取业务代码
        business_code = context.get("business_code") if context else None
        if not business_code:
            return {}
        
        # 加载业务专属 Prompt
        self._load_business_prompt(business_code)
        business_prompt = self.business_prompts.get(business_code, "")
        
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
   - 2 开头 → 用户专属（issue_type=user）
   - 7 开头 → 直播间专属（issue_type=room）
   - 8 开头 → 随机礼物（issue_type=random）
   - 3/4 开头 → 背包礼物
3. 有效期特殊值映射：
   - "永久"、"永久有效" → 1000
   - "一周" → 7
   - "一个月" → 30
4. 批量数量默认为 1，最大为 100
5. 缺少的参数不要填充默认值，让系统自动处理
6. 只返回 JSON，不要其他说明
"""
        
        messages = [{"role": "user", "content": prompt}]
        response = self.llm_client.chat(messages, temperature=0.1)  # 降低温度提高稳定性
        
        try:
            # 提取JSON
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
            print(f"参数提取失败: {e}")
            print(f"LLM 响应: {response}")
        
        return {}
