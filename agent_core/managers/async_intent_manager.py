"""
异步意图管理器

职责：
1. 规则匹配（高频场景快速响应）
2. 异步 LLM 意图识别（兜底）
3. 意图结果缓存
4. 置信度评估

优化（2025-02-16）：
- 添加配置化规则匹配
- 高频场景 <10ms 响应
- LLM 兜底保证灵活性
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import hashlib
import logging
import time
import asyncio
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


@dataclass
class IntentResult:
    """意图识别结果"""
    skill_name: str
    skill_type: str
    confidence: float
    reason: str
    params: Dict[str, Any]
    raw_input: str
    cache_hit: bool = False  # 是否命中缓存
    
    def dict(self) -> dict:
        """转换为字典"""
        return {
            "skill_name": self.skill_name,
            "skill_type": self.skill_type,
            "confidence": self.confidence,
            "reason": self.reason,
            "params": self.params,
            "raw_input": self.raw_input,
            "cache_hit": self.cache_hit
        }


class BaseIntentRouteStrategy(ABC):
    """意图路由策略基类。"""

    @abstractmethod
    async def route(
        self,
        manager: "AsyncIntentManager",
        user_input: str,
        available_skills: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]],
        rule_result: Optional[Any],
        colloquial: bool
    ) -> IntentResult:
        """返回最终意图结果。"""


class RuleOnlyRouteStrategy(BaseIntentRouteStrategy):
    """规则优先策略：命中规则走规则，否则 LLM 兜底。"""

    async def route(
        self,
        manager: "AsyncIntentManager",
        user_input: str,
        available_skills: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]],
        rule_result: Optional[Any],
        colloquial: bool
    ) -> IntentResult:
        if rule_result:
            return manager._build_result_from_rule(rule_result, available_skills, user_input)
        return await manager._recognize_by_llm(user_input, available_skills, context)


class LLMFirstRouteStrategy(BaseIntentRouteStrategy):
    """LLM 优先策略：先走 LLM，低置信度时回退规则。"""

    async def route(
        self,
        manager: "AsyncIntentManager",
        user_input: str,
        available_skills: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]],
        rule_result: Optional[Any],
        colloquial: bool
    ) -> IntentResult:
        llm_intent = await manager._recognize_by_llm(user_input, available_skills, context)
        if rule_result and llm_intent.confidence < 0.5:
            return manager._build_result_from_rule(rule_result, available_skills, user_input)
        return llm_intent


class HybridRouteStrategy(BaseIntentRouteStrategy):
    """混合策略：口语化场景 LLM 优先，其他场景规则与 LLM 比对择优。"""

    async def route(
        self,
        manager: "AsyncIntentManager",
        user_input: str,
        available_skills: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]],
        rule_result: Optional[Any],
        colloquial: bool
    ) -> IntentResult:
        if colloquial:
            result = await manager._recognize_by_llm(user_input, available_skills, context)
            logger.info(f"口语化表达走 LLM 优先: {user_input[:40]}...")
            return result

        llm_task = asyncio.create_task(
            manager._recognize_by_llm(user_input, available_skills, context)
        )
        rule_intent = (
            manager._build_result_from_rule(rule_result, available_skills, user_input)
            if rule_result else None
        )
        llm_intent = await llm_task

        if rule_intent and rule_intent.confidence >= llm_intent.confidence:
            manager.stats["hybrid_choose_rule_count"] += 1
            result = rule_intent
        else:
            manager.stats["hybrid_choose_llm_count"] += 1
            result = llm_intent

        logger.info(
            f"混合路由选择: {result.skill_name} "
            f"(rule={rule_intent.confidence if rule_intent else 0:.2f}, "
            f"llm={llm_intent.confidence:.2f})"
        )
        return result


ROUTE_STRATEGY_REGISTRY = {
    "rule_only": RuleOnlyRouteStrategy,
    "llm_first": LLMFirstRouteStrategy,
    "hybrid": HybridRouteStrategy
}


class AsyncIntentManager:
    """异步意图管理器 - 负责意图识别和缓存"""
    
    def __init__(self, business_code: str, async_llm_client, async_intent_parser):
        """
        初始化异步意图管理器
        
        Args:
            business_code: 业务代码
            async_llm_client: 异步 LLM 客户端实例（共享）
            async_intent_parser: 异步意图解析器实例
        """
        self.business_code = business_code
        self.llm_client = async_llm_client
        self.intent_parser = async_intent_parser
        self.routing_config = self._load_routing_config()
        self.route_strategy = self._build_route_strategy()
        
        # 初始化规则匹配器（同步，因为规则匹配很快）
        self.rule_matcher = None
        try:
            from agent_core.parsers.rule_based_intent_matcher import RuleBasedIntentMatcher
            self.rule_matcher = RuleBasedIntentMatcher(business_code)
            logger.info("✓ 异步规则匹配器已启用")
        except Exception as e:
            logger.warning(f"异步规则匹配器初始化失败: {e}")
        
        # 使用全局缓存管理器
        self.cache_manager = None
        try:
            from utils.cache_manager import get_cache_manager
            self.cache_manager = get_cache_manager()
            logger.debug("✓ 异步意图缓存已启用")
        except Exception as e:
            logger.warning(f"异步意图缓存初始化失败: {e}")
        
        # 统计信息
        self.stats = {
            "rule_match_count": 0,
            "llm_match_count": 0,
            "cache_hit_count": 0,
            "hybrid_choose_rule_count": 0,
            "hybrid_choose_llm_count": 0
        }

    def _build_route_strategy(self) -> BaseIntentRouteStrategy:
        """构建路由策略插件。"""
        mode = self.routing_config.get("mode", "hybrid")
        strategy_cls = ROUTE_STRATEGY_REGISTRY.get(mode, HybridRouteStrategy)
        if mode not in ROUTE_STRATEGY_REGISTRY:
            logger.warning(f"未知意图路由模式: {mode}，回退为 hybrid")
        logger.info(f"✓ 异步意图路由策略: {strategy_cls.__name__} (mode={mode})")
        return strategy_cls()

    def _load_routing_config(self) -> Dict[str, Any]:
        """加载意图路由配置（支持灰度）。"""
        try:
            from utils.config_loader import ConfigLoader
            framework_cfg = ConfigLoader.load_framework_config("agent_config.json")
            intent_routing = framework_cfg.get("intent_routing", {})
        except Exception as e:
            logger.warning(f"加载意图路由配置失败，使用默认值: {e}")
            intent_routing = {}

        return {
            "mode": intent_routing.get("mode", "hybrid"),
            "rule_direct_threshold": float(intent_routing.get("rule_direct_threshold", 0.97)),
            "high_precision_skills": set(intent_routing.get("high_precision_skills", [])),
            "colloquial_markers": intent_routing.get(
                "colloquial_markers",
                ["帮我看看", "帮我查", "查下", "看一下", "看下", "帮忙查", "麻烦查"]
            )
        }

    def _is_colloquial(self, user_input: str) -> bool:
        user_input_lower = user_input.lower()
        return any(marker.lower() in user_input_lower for marker in self.routing_config["colloquial_markers"])

    def _is_high_precision_rule(self, rule_result) -> bool:
        if not rule_result:
            return False
        return rule_result.skill_name in self.routing_config["high_precision_skills"]

    def _build_result_from_rule(
        self,
        rule_result,
        available_skills: List[Dict[str, Any]],
        user_input: str
    ) -> IntentResult:
        skill_config = self._get_skill_config(rule_result.skill_name, available_skills)
        return IntentResult(
            skill_name=rule_result.skill_name,
            skill_type=skill_config.get("skill_type", "query") if skill_config else "query",
            confidence=rule_result.confidence,
            reason=rule_result.reason,
            params={},
            raw_input=user_input
        )

    async def _recognize_by_llm(
        self,
        user_input: str,
        available_skills: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]]
    ) -> IntentResult:
        self.stats["llm_match_count"] += 1
        intent_dict = await self.intent_parser.parse_intent(
            user_input,
            self.business_code,
            available_skills=available_skills,
            context=context
        )
        return IntentResult(
            skill_name=intent_dict.get("skill_name", "unknown"),
            skill_type=intent_dict.get("skill_type", "query"),
            confidence=intent_dict.get("confidence", 0.0),
            reason=intent_dict.get("reason", ""),
            params=intent_dict.get("params", {}),
            raw_input=user_input
        )
    
    def _generate_cache_key(self, user_input: str) -> str:
        """
        生成缓存键
        
        Args:
            user_input: 用户输入
            
        Returns:
            缓存键
        """
        input_hash = hashlib.md5(user_input.encode()).hexdigest()
        return f"async_intent:{self.business_code}:{input_hash}"
    
    async def recognize(
        self, 
        user_input: str, 
        available_skills: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        use_cache: bool = True
    ) -> IntentResult:
        """
        异步识别用户意图（规则匹配 + LLM 兜底）
        
        Args:
            user_input: 用户输入
            available_skills: 可用 Skill 列表
            context: 上下文信息
            use_cache: 是否使用缓存
            
        Returns:
            意图识别结果
        """
        start_time = time.time()
        
        # 1. 尝试从缓存获取
        if use_cache and self.cache_manager:
            cache_key = self._generate_cache_key(user_input)
            cached = self.cache_manager.get(cache_key)
            if cached:
                self.stats["cache_hit_count"] += 1
                duration_ms = (time.time() - start_time) * 1000
                logger.debug(
                    f"异步意图缓存命中: {user_input[:50]}... "
                    f"({duration_ms:.2f}ms)"
                )
                result = IntentResult(**cached)
                result.cache_hit = True  # 标记缓存命中
                return result
        
        result = None
        rule_result = None
        colloquial = self._is_colloquial(user_input)

        # 2. 规则直通（高精度模板 + 高置信度）
        if self.rule_matcher:
            rule_result = self.rule_matcher.match(user_input, available_skills)
            if rule_result:
                self.stats["rule_match_count"] += 1
                if (
                    not colloquial and
                    rule_result.confidence >= self.routing_config["rule_direct_threshold"] and
                    self._is_high_precision_rule(rule_result)
                ):
                    result = self._build_result_from_rule(rule_result, available_skills, user_input)
                    logger.info(
                        f"高精度规则直通: {result.skill_name} "
                        f"(confidence={result.confidence:.2f})"
                    )

        # 3. 策略路由决策（rule_only / llm_first / hybrid）
        if result is None:
            result = await self.route_strategy.route(
                manager=self,
                user_input=user_input,
                available_skills=available_skills,
                context=context,
                rule_result=rule_result,
                colloquial=colloquial
            )
        
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"异步意图识别完成: {result.skill_name} "
            f"(confidence={result.confidence:.2f}, {duration_ms:.2f}ms)"
        )
        
        # 5. 设置缓存
        if use_cache and self.cache_manager and result.confidence >= 0.5:
            cache_key = self._generate_cache_key(user_input)
            self.cache_manager.set(cache_key, result.dict(), ttl=3600)
            logger.debug(f"异步意图结果已缓存: {result.skill_name}")
        
        return result
    
    def _get_skill_config(
        self, 
        skill_name: str, 
        available_skills: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        获取 Skill 配置
        
        Args:
            skill_name: Skill 名称
            available_skills: 可用 Skill 列表
            
        Returns:
            Skill 配置
        """
        for skill in available_skills:
            if skill.get("skill_name") == skill_name:
                return skill
        return None
    
    # clear_cache 方法已移除，避免误操作Redis缓存
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计信息
        """
        total = (
            self.stats["rule_match_count"] + 
            self.stats["llm_match_count"]
        )
        
        stats = {
            "business_code": self.business_code,
            "route_mode": self.routing_config.get("mode", "hybrid"),
            "route_strategy": self.route_strategy.__class__.__name__,
            "total_recognitions": total,
            "rule_match_count": self.stats["rule_match_count"],
            "llm_match_count": self.stats["llm_match_count"],
            "cache_hit_count": self.stats["cache_hit_count"],
            "hybrid_choose_rule_count": self.stats["hybrid_choose_rule_count"],
            "hybrid_choose_llm_count": self.stats["hybrid_choose_llm_count"],
            "rule_match_rate": (
                self.stats["rule_match_count"] / total 
                if total > 0 else 0.0
            ),
            "cache_hit_rate": (
                self.stats["cache_hit_count"] / total 
                if total > 0 else 0.0
            )
        }
        
        # 添加规则匹配器统计
        if self.rule_matcher:
            stats["rule_matcher"] = self.rule_matcher.get_stats()
        
        return stats
    
    def reload_rules(self):
        """重新加载规则（支持热更新）"""
        if self.rule_matcher:
            self.rule_matcher.reload_rules()
            logger.info(f"✓ 异步意图匹配规则已重新加载 (business: {self.business_code})")
