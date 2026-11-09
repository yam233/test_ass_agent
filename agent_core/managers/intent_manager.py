"""
意图管理器

职责：
1. 规则匹配（高频场景快速响应）
2. LLM 意图识别（兜底）
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


class IntentManager:
    """意图管理器 - 负责意图识别和缓存"""
    
    def __init__(self, business_code: str, llm_client, intent_parser):
        """
        初始化意图管理器
        
        Args:
            business_code: 业务代码
            llm_client: LLM 客户端实例（共享）
            intent_parser: 意图解析器实例
        """
        self.business_code = business_code
        self.llm_client = llm_client
        self.intent_parser = intent_parser
        
        # 初始化规则匹配器
        self.rule_matcher = None
        try:
            from agent_core.parsers.rule_based_intent_matcher import RuleBasedIntentMatcher
            self.rule_matcher = RuleBasedIntentMatcher(business_code)
            logger.info("✓ 规则匹配器已启用")
        except Exception as e:
            logger.warning(f"规则匹配器初始化失败: {e}")
        
        # 使用全局缓存管理器
        self.cache_manager = None
        try:
            from utils.cache_manager import get_cache_manager
            self.cache_manager = get_cache_manager()
            logger.debug("✓ 意图缓存已启用")
        except Exception as e:
            logger.warning(f"意图缓存初始化失败: {e}")
        
        # 统计信息
        self.stats = {
            "rule_match_count": 0,
            "llm_match_count": 0,
            "cache_hit_count": 0
        }
    
    def _generate_cache_key(self, user_input: str) -> str:
        """
        生成缓存键
        
        Args:
            user_input: 用户输入
            
        Returns:
            缓存键
        """
        input_hash = hashlib.md5(user_input.encode()).hexdigest()
        return f"intent:{self.business_code}:{input_hash}"
    
    def recognize(
        self, 
        user_input: str, 
        available_skills: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        use_cache: bool = True
    ) -> IntentResult:
        """
        识别用户意图（规则匹配 + LLM 兜底）
        
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
                    f"意图缓存命中: {user_input[:50]}... "
                    f"({duration_ms:.2f}ms)"
                )
                return IntentResult(**cached)
        
        # 2. 尝试规则匹配（高频场景快速响应）
        if self.rule_matcher:
            rule_result = self.rule_matcher.match(user_input, available_skills)
            if rule_result:
                self.stats["rule_match_count"] += 1
                duration_ms = (time.time() - start_time) * 1000
                
                # 获取 Skill 配置
                skill_config = self._get_skill_config(
                    rule_result.skill_name, 
                    available_skills
                )
                
                result = IntentResult(
                    skill_name=rule_result.skill_name,
                    skill_type=skill_config.get("skill_type", "query") if skill_config else "query",
                    confidence=rule_result.confidence,
                    reason=rule_result.reason,
                    params={},
                    raw_input=user_input
                )
                
                logger.info(
                    f"规则匹配成功: {result.skill_name} "
                    f"(confidence={result.confidence:.2f}, {duration_ms:.2f}ms)"
                )
                
                # 设置缓存
                if use_cache and self.cache_manager:
                    cache_key = self._generate_cache_key(user_input)
                    self.cache_manager.set(cache_key, result.dict(), ttl=3600)
                
                return result
        
        # 3. LLM 识别兜底
        self.stats["llm_match_count"] += 1
        logger.debug("规则匹配失败，使用 LLM 识别")
        
        intent_dict = self.intent_parser.parse_intent(
            user_input,
            self.business_code,
            available_skills=available_skills,
            context=context
        )
        
        # 4. 构造结果对象
        result = IntentResult(
            skill_name=intent_dict.get("skill_name", "unknown"),
            skill_type=intent_dict.get("skill_type", "query"),
            confidence=intent_dict.get("confidence", 0.0),
            reason=intent_dict.get("reason", ""),
            params=intent_dict.get("params", {}),
            raw_input=user_input
        )
        
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"LLM 识别完成: {result.skill_name} "
            f"(confidence={result.confidence:.2f}, {duration_ms:.2f}ms)"
        )
        
        # 5. 设置缓存
        if use_cache and self.cache_manager and result.confidence >= 0.5:
            cache_key = self._generate_cache_key(user_input)
            self.cache_manager.set(cache_key, result.dict(), ttl=3600)
            logger.debug(f"意图结果已缓存: {result.skill_name}")
        
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
            "total_recognitions": total,
            "rule_match_count": self.stats["rule_match_count"],
            "llm_match_count": self.stats["llm_match_count"],
            "cache_hit_count": self.stats["cache_hit_count"],
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
            logger.info(f"✓ 意图匹配规则已重新加载 (business: {self.business_code})")
