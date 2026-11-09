"""通用LLM客户端（支持缓存和异步）"""
from typing import Dict, Any, Optional, List
from openai import OpenAI
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


class LLMClient:
    """通用LLM客户端，支持OpenAI兼容API（包括DeepSeek）"""
    
    def __init__(
        self, 
        api_key: str, 
        model: str,
        base_url: Optional[str] = None,
        client_type: str = "openai",
        enable_cache: bool = True,
        cache_ttl: int = 3600,
        **kwargs
    ):
        """
        初始化LLM客户端
        
        Args:
            api_key: API密钥
            model: 模型名称
            base_url: API基础URL（用于兼容API）
            client_type: 客户端类型（openai等）
            enable_cache: 是否启用缓存
            cache_ttl: 缓存过期时间（秒）
            **kwargs: 其他参数（会被忽略，用于兼容性）
        """
        self.api_key = api_key
        if not model:
            raise ValueError("LLM model is required")
        self.model = model
        self.base_url = base_url
        self.client_type = client_type
        self.enable_cache = enable_cache
        self.cache_ttl = cache_ttl
        
        # 初始化OpenAI客户端（兼容DeepSeek）
        if client_type == "openai":
            # 只传递OpenAI客户端支持的参数
            client_kwargs = {
                "api_key": api_key
            }
            if base_url:
                client_kwargs["base_url"] = base_url
            
            self.client = OpenAI(**client_kwargs)
        
        # 初始化缓存管理器
        self.cache_manager = None
        if enable_cache:
            try:
                from utils.cache_manager import get_cache_manager
                self.cache_manager = get_cache_manager()
                logger.info("✓ LLM 缓存已启用")
            except Exception as e:
                logger.warning(f"LLM 缓存初始化失败: {e}")
    
    def _generate_cache_key(self, messages: List[Dict[str, str]], temperature: float) -> str:
        """
        生成缓存键
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            
        Returns:
            缓存键
        """
        # 将消息和参数序列化为字符串
        key_data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature
        }
        key_str = json.dumps(key_data, sort_keys=True)
        key_hash = hashlib.md5(key_str.encode()).hexdigest()
        return f"llm:{self.model}:{key_hash}"
    
    def chat(
        self, 
        messages: List[Dict[str, str]], 
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        use_cache: bool = True
    ) -> str:
        """
        聊天接口（支持缓存）
        
        Args:
            messages: 消息列表，格式：[{"role": "user", "content": "..."}]
            temperature: 温度参数
            max_tokens: 最大token数
            use_cache: 是否使用缓存
            
        Returns:
            LLM响应内容
        """
        # 1. 尝试从缓存获取
        if use_cache and self.enable_cache and self.cache_manager:
            cache_key = self._generate_cache_key(messages, temperature)
            cached_response = self.cache_manager.get(cache_key)
            if cached_response:
                logger.debug(f"LLM 缓存命中: {cache_key[:32]}...")
                return cached_response
        
        # 2. 调用 LLM API
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            content = response.choices[0].message.content
            
            # 3. 设置缓存
            if use_cache and self.enable_cache and self.cache_manager:
                cache_key = self._generate_cache_key(messages, temperature)
                self.cache_manager.set(cache_key, content, self.cache_ttl)
                logger.debug(f"LLM 响应已缓存: {cache_key[:32]}...")
            
            return content
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            return ""
    
    def extract_json(
        self, 
        text: str, 
        schema: Dict[str, Any],
        temperature: float = 0.3,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        提取JSON（支持缓存）
        
        Args:
            text: 输入文本
            schema: JSON schema描述
            temperature: 温度参数（提取任务使用较低温度）
            use_cache: 是否使用缓存
            
        Returns:
            提取的JSON对象
        """
        prompt = f"""请从以下文本中提取信息，并按照指定的schema返回JSON格式。

文本：
{text}

Schema：
{schema}

请直接返回JSON，不要包含其他说明文字。"""
        
        messages = [{"role": "user", "content": prompt}]
        response = self.chat(messages, temperature=temperature, use_cache=use_cache)
        
        try:
            # 尝试提取JSON
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
            return {}
        except Exception as e:
            logger.error(f"JSON解析失败: {e}")
            return {}
    
    # clear_cache 方法已移除，避免误操作Redis缓存
    
    def get_cache_stats(self) -> dict:
        """获取缓存统计"""
        if self.cache_manager:
            return self.cache_manager.get_stats()
        return {}
