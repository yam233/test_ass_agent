"""
异步 LLM 客户端

支持异步调用 LLM API，提升并发处理能力
"""
import aiohttp
import asyncio
import hashlib
import json
import logging
from urllib.parse import urlparse
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class AsyncLLMClient:
    """异步 LLM 客户端，支持 OpenAI 兼容 API（包括 DeepSeek）"""
    
    def __init__(
        self, 
        api_key: str, 
        model: str,
        base_url: Optional[str] = None,
        enable_cache: bool = True,
        cache_ttl: int = 3600,
        timeout: int = 30,
        max_retries: int = 3,
        **kwargs
    ):
        """
        初始化异步 LLM 客户端
        
        Args:
            api_key: API 密钥
            model: 模型名称
            base_url: API 基础 URL
            enable_cache: 是否启用缓存
            cache_ttl: 缓存过期时间（秒）
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            **kwargs: 其他参数（用于兼容性）
        """
        self.api_key = api_key
        if not model:
            raise ValueError("LLM model is required")
        if not base_url:
            raise ValueError("LLM base_url is required")
        self.model = model
        self.base_url = self._normalize_base_url(base_url)
        self.enable_cache = enable_cache
        self.cache_ttl = cache_ttl
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        
        # 初始化缓存管理器
        self.cache_manager = None
        if enable_cache:
            try:
                from utils.cache_manager import get_cache_manager
                self.cache_manager = get_cache_manager()
                logger.info("✓ 异步 LLM 缓存已启用")
            except Exception as e:
                logger.warning(f"异步 LLM 缓存初始化失败: {e}")

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """
        标准化 base_url，确保最终指向 OpenAI 兼容前缀（.../v1）
        """
        normalized = base_url.rstrip("/")
        parsed = urlparse(normalized)
        path = (parsed.path or "").rstrip("/")

        # 已经是版本路径（如 /v1）则直接使用
        if path.endswith("/v1"):
            return normalized

        # 其他情况统一补齐 /v1
        return f"{normalized}/v1"
    
    def _generate_cache_key(self, messages: List[Dict[str, str]], temperature: float) -> str:
        """
        生成缓存键
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            
        Returns:
            缓存键
        """
        key_data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature
        }
        key_str = json.dumps(key_data, sort_keys=True)
        key_hash = hashlib.md5(key_str.encode()).hexdigest()
        return f"async_llm:{self.model}:{key_hash}"
    
    async def chat(
        self, 
        messages: List[Dict[str, str]], 
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        use_cache: bool = True
    ) -> str:
        """
        异步聊天接口（支持缓存）
        
        Args:
            messages: 消息列表，格式：[{"role": "user", "content": "..."}]
            temperature: 温度参数
            max_tokens: 最大 token 数
            use_cache: 是否使用缓存
            
        Returns:
            LLM 响应内容
        """
        # 1. 尝试从缓存获取
        if use_cache and self.enable_cache and self.cache_manager:
            cache_key = self._generate_cache_key(messages, temperature)
            cached_response = self.cache_manager.get(cache_key)
            if cached_response:
                logger.debug(f"异步 LLM 缓存命中: {cache_key[:32]}...")
                return cached_response
        
        # 2. 异步调用 LLM API（带重试）
        content = await self._call_api_with_retry(messages, temperature, max_tokens)
        
        # 3. 设置缓存
        if use_cache and self.enable_cache and self.cache_manager and content:
            cache_key = self._generate_cache_key(messages, temperature)
            self.cache_manager.set(cache_key, content, self.cache_ttl)
            logger.debug(f"异步 LLM 响应已缓存: {cache_key[:32]}...")
        
        return content
    
    async def _call_api_with_retry(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: Optional[int]
    ) -> str:
        """
        调用 API（带重试机制和总超时限制）
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数
            
        Returns:
            LLM 响应内容
        """
        last_error = None
        start_time = asyncio.get_event_loop().time()
        total_timeout = 30.0  # 总超时时间 30 秒
        
        for attempt in range(self.max_retries):
            try:
                # 检查总超时
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= total_timeout:
                    logger.error(f"异步 LLM 调用超时: 已耗时 {elapsed:.2f}s")
                    raise asyncio.TimeoutError(f"LLM 调用总超时（{total_timeout}s）")
                
                return await self._call_api(messages, temperature, max_tokens)
            except aiohttp.ClientError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    # 计算等待时间，但不超过剩余时间
                    wait_time = min(2 ** attempt, 8)  # 最大等待 8 秒
                    elapsed = asyncio.get_event_loop().time() - start_time
                    remaining = total_timeout - elapsed
                    
                    if remaining <= 0:
                        logger.error(f"异步 LLM 调用超时: 已耗时 {elapsed:.2f}s")
                        raise asyncio.TimeoutError(f"LLM 调用总超时（{total_timeout}s）")
                    
                    wait_time = min(wait_time, remaining - 1)  # 保留 1 秒用于最后一次尝试
                    
                    logger.warning(
                        f"异步 LLM 调用失败 (尝试 {attempt + 1}/{self.max_retries}): {e}, "
                        f"等待 {wait_time:.1f}s 后重试"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"异步 LLM 调用失败，已达最大重试次数: {e}")
            except asyncio.TimeoutError:
                raise
            except Exception as e:
                logger.error(f"异步 LLM 调用异常: {e}", exc_info=True)
                raise
        
        raise Exception(f"异步 LLM 调用失败: {last_error}")
    
    async def _call_api(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: Optional[int]
    ) -> str:
        """
        调用 LLM API
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数
            
        Returns:
            LLM 响应内容
        """
        # 构造请求体
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        # 构造请求头
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 异步调用 API
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers
            ) as response:
                # 检查响应状态
                if response.status != 200:
                    error_text = await response.text()
                    raise aiohttp.ClientError(
                        f"API 返回错误状态码 {response.status}: {error_text}"
                    )
                
                # 解析响应
                result = await response.json()
                
                # 提取内容
                if "choices" not in result or len(result["choices"]) == 0:
                    raise ValueError(f"API 响应格式错误: {result}")
                
                content = result["choices"][0]["message"]["content"]
                return content
    
    async def extract_json(
        self, 
        text: str, 
        schema: Dict[str, Any],
        temperature: float = 0.3,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        异步提取 JSON（支持缓存）
        
        Args:
            text: 输入文本
            schema: JSON schema 描述
            temperature: 温度参数（提取任务使用较低温度）
            use_cache: 是否使用缓存
            
        Returns:
            提取的 JSON 对象
        """
        prompt = f"""请从以下文本中提取信息，并按照指定的 schema 返回 JSON 格式。

文本：
{text}

Schema：
{schema}

请直接返回 JSON，不要包含其他说明文字。"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self.chat(messages, temperature=temperature, use_cache=use_cache)
        
        try:
            # 尝试提取 JSON
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
            return {}
        except Exception as e:
            logger.error(f"JSON 解析失败: {e}")
            return {}
    
    # clear_cache 方法已移除，避免误操作Redis缓存
    
    def get_cache_stats(self) -> dict:
        """获取缓存统计"""
        if self.cache_manager:
            return self.cache_manager.get_stats()
        return {}


# 便捷函数：创建异步 LLM 客户端
def create_async_llm_client(
    api_key: str,
    model: str,
    base_url: Optional[str] = None,
    **kwargs
) -> AsyncLLMClient:
    """
    创建异步 LLM 客户端
    
    Args:
        api_key: API 密钥
        model: 模型名称
        base_url: API 基础 URL
        **kwargs: 其他参数
        
    Returns:
        异步 LLM 客户端实例
    """
    return AsyncLLMClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        **kwargs
    )
