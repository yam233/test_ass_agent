"""
基于MCP的Skill基类
通过HTTP调用MCP服务，无侵入适配原有系统
支持自动重试机制
支持 base_url: "local" 直接调用本地业务逻辑
"""
import requests
import time
import importlib
from typing import Dict, Any, Callable
from agent_core.templates import BaseSkillTemplate
from agent_core.protocol import SkillInput, SkillOutput


class BaseMCPSkill(BaseSkillTemplate):
    """基于MCP的Skill基类"""
    
    def __init__(
        self, 
        skill_name: str, 
        skill_type: str,
        business_code: str,
        server_config: Dict[str, Any],
        tool_config: Dict[str, Any]
    ):
        super().__init__(skill_name, skill_type, business_code=business_code)
        self.server_config = server_config
        self.tool_config = tool_config
        # 兼容 baseUrl 和 base_url 两种命名
        self.base_url = server_config.get("baseUrl") or server_config.get("base_url", "")
        self.headers = server_config.get("headers", {})
        self.timeout = tool_config.get("timeout", 30000) / 1000  # 转换为秒
        
        # 检查是否为本地调用
        self.is_local = self.base_url.lower() == "local"
        
        # 重试配置
        self.max_retries = 3
        self.retry_delay = 1  # 秒
        self.retry_backoff = 2  # 指数退避倍数

    def _build_local_handlers(self) -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
        """按业务动态加载本地工具处理器注册表。"""
        module_name = f"agent_plugins.{self.business_code}.local_handlers"
        try:
            module = importlib.import_module(module_name)
            builder = getattr(module, "build_local_handlers", None)
            if callable(builder):
                return builder()
        except Exception:
            pass
        return {}
    
    def execute(self, skill_input: SkillInput) -> SkillOutput:
        """
        执行Skill - 调用MCP服务（带重试机制）或本地业务逻辑
        
        Args:
            skill_input: Skill输入协议
            
        Returns:
            Skill输出协议
        """
        # 如果是本地调用，直接调用本地业务逻辑
        if self.is_local:
            return self._execute_local(skill_input)
        
        # 否则通过 HTTP 调用远程 MCP 服务
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                return self._execute_once(skill_input)
            
            except requests.Timeout as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (self.retry_backoff ** attempt)
                    print(f"请求超时，{delay}秒后重试 (尝试 {attempt + 1}/{self.max_retries})")
                    time.sleep(delay)
                    continue
                else:
                    # 最后一次重试也失败了
                    break
                    
            except requests.ConnectionError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (self.retry_backoff ** attempt)
                    print(f"连接失败，{delay}秒后重试 (尝试 {attempt + 1}/{self.max_retries})")
                    time.sleep(delay)
                    continue
                else:
                    # 最后一次重试也失败了
                    break
                    
            except requests.HTTPError as e:
                # HTTP 错误不重试（如 4xx, 5xx）
                return SkillOutput(
                    code=500,
                    msg=f"HTTP错误: {e}",
                    data=None
                )
                
            except Exception as e:
                # 其他异常不重试
                return SkillOutput(
                    code=500,
                    msg=str(e),
                    data=None
                )
        
        # 重试次数用尽
        return SkillOutput(
            code=500,
            msg=f"重试{self.max_retries}次后失败: {last_error}",
            data=None
        )
    
    def _execute_local(self, skill_input: SkillInput) -> SkillOutput:
        """
        执行本地业务逻辑
        
        Args:
            skill_input: Skill输入协议
            
        Returns:
            Skill输出协议
        """
        try:
            # 导入本地业务逻辑模块
            tool_name = self.tool_config.get("toolName", "")
            
            # 框架自动添加的参数，需要过滤
            framework_params = {'operator', 'environment', 'issue_type', 'session_id', 'request_id'}
            
            # 过滤掉框架添加的额外参数
            params = {k: v for k, v in skill_input.params.items() 
                     if k not in framework_params}
            if skill_input.context.get("execute_confirmed"):
                params["execute_confirmed"] = True
            handlers = self._build_local_handlers()
            handler = handlers.get(tool_name)
            if not handler:
                # 工具未找到，生成友好提示
                friendly_message = f"❌ 抱歉，'{tool_name}' 工具暂不可用\n\n"
                
                # 根据 skill_name 给出建议
                if "gift" in tool_name.lower() and "name" in tool_name.lower():
                    friendly_message += "💡 您可能想要：\n"
                    friendly_message += "• 查询礼物信息：「查询礼物80103」\n"
                    friendly_message += "• 查询后台地址：「查询随机礼物配置地址」\n"
                    friendly_message += "• 列出礼物类型：「列出所有礼物类型」"
                else:
                    friendly_message += "💡 请尝试其他查询方式或联系管理员"
                
                return SkillOutput(
                    code=404,
                    msg=friendly_message,
                    data=None
                )
            result = handler(params)
            
            # 返回结果
            if result.get("success"):
                return SkillOutput(
                    code=0,
                    msg=result.get("message", "执行成功"),
                    data=result.get("data")
                )
            else:
                return SkillOutput(
                    code=500,
                    msg=result.get("message", "执行失败"),
                    data=result.get("data")
                )
                
        except Exception as e:
            return SkillOutput(
                code=500,
                msg=f"本地执行失败: {str(e)}",
                data=None
            )
        
        # 重试次数用尽
        return SkillOutput(
            code=500,
            msg=f"重试{self.max_retries}次后失败: {last_error}",
            data=None
        )
    
    def _execute_once(self, skill_input: SkillInput) -> SkillOutput:
        """
        单次执行（不重试）
        
        Args:
            skill_input: Skill输入协议
            
        Returns:
            Skill输出协议
        """
        # 构建请求URL
        method = self.tool_config.get("method", "POST")
        path = self.tool_config.get("path", "")
        url = f"{self.base_url}{path}"
        
        # 发送请求
        if method.upper() == "GET":
            response = requests.get(
                url,
                params=skill_input.params,
                headers=self.headers,
                timeout=self.timeout
            )
        else:
            response = requests.post(
                url,
                json=skill_input.params,
                headers=self.headers,
                timeout=self.timeout
            )
        
        # 检查HTTP状态码
        response.raise_for_status()
        
        # 处理响应
        if response.status_code == 200:
            result = response.json()
            return SkillOutput(
                code=0,
                msg="执行成功",
                data=result
            )
        else:
            return SkillOutput(
                code=response.status_code,
                msg=f"HTTP {response.status_code}: {response.text}",
                data=None
            )
    
    def get_param_schema(self) -> dict:
        """获取参数schema"""
        params = self.tool_config.get("params", [])
        schema = {}
        for param in params:
            schema[param["name"]] = {
                "type": param.get("type"),
                "required": param.get("required", False),
                "description": param.get("desc", ""),
                "default": param.get("default")
            }
        return schema
