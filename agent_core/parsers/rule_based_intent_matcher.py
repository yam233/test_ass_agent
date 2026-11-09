"""
基于规则的意图匹配器

职责：
1. 加载意图匹配规则（配置化）
2. 关键词匹配 + 排除词过滤
3. 置信度计算
4. 快速响应高频场景

优势：
- 完全配置化，无硬编码
- 高频场景快速响应（<10ms）
- LLM 兜底保证灵活性
"""
from typing import Dict, Any, Optional, List
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RuleMatchResult:
    """规则匹配结果"""
    skill_name: str
    confidence: float
    matched_keywords: List[str]
    reason: str
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "skill_name": self.skill_name,
            "confidence": self.confidence,
            "matched_keywords": self.matched_keywords,
            "reason": self.reason
        }


class RuleBasedIntentMatcher:
    """基于规则的意图匹配器"""
    
    def __init__(self, business_code: str):
        """
        初始化规则匹配器
        
        Args:
            business_code: 业务代码
        """
        self.business_code = business_code
        self.rules = []
        self.config = {}
        self.keyword_index = {}  # 关键词索引，加速查找
        self._load_rules()
    
    def _load_rules(self):
        """加载意图匹配规则"""
        try:
            from utils.config_loader_v2 import ConfigLoaderV2
            rules_config = ConfigLoaderV2.load_business_config(
                self.business_code,
                "intent_rules.json"
            )
            
            self.rules = rules_config.get("rules", [])
            self.config = rules_config.get("config", {})
            
            # 按优先级排序（高优先级在前，可以提前返回）
            self.rules.sort(key=lambda x: x.get("priority", 0), reverse=True)
            
            # 构建关键词索引
            self._build_keyword_index()
            
            logger.info(
                f"✓ 意图匹配规则已加载: {len(self.rules)} 条规则 "
                f"(business: {self.business_code})"
            )
        except Exception as e:
            logger.warning(f"加载意图匹配规则失败: {e}")
            self.rules = []
            self.config = {}
            self.keyword_index = {}
    
    def _build_keyword_index(self):
        """构建关键词索引，加速查找"""
        self.keyword_index = {}
        
        for rule in self.rules:
            skill_name = rule["skill_name"]
            
            # 索引必填关键词
            for kw in rule.get("required_keywords", []):
                if kw not in self.keyword_index:
                    self.keyword_index[kw] = []
                self.keyword_index[kw].append(skill_name)
            
            # 索引可选关键词
            for kw in rule.get("optional_keywords", []):
                if kw not in self.keyword_index:
                    self.keyword_index[kw] = []
                if skill_name not in self.keyword_index[kw]:
                    self.keyword_index[kw].append(skill_name)
        
        logger.debug(f"关键词索引已构建: {len(self.keyword_index)} 个关键词")
    
    def match(
        self, 
        user_input: str,
        available_skills: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[RuleMatchResult]:
        """
        匹配用户输入到意图（优化版：使用关键词索引 + 提前返回）
        
        Args:
            user_input: 用户输入
            available_skills: 可用 Skill 列表（用于验证）
            
        Returns:
            匹配结果，如果没有匹配返回 None
        """
        # 检查是否启用规则匹配
        if not self.config.get("enable_rule_matching", True):
            logger.debug("规则匹配已禁用")
            return None
        
        if not self.rules:
            logger.debug("没有可用的匹配规则")
            return None
        
        # 转换为小写便于匹配
        user_input_lower = user_input.lower()
        
        # 使用关键词索引快速筛选候选规则
        candidate_skills = set()
        for kw in self.keyword_index:
            if kw in user_input_lower:
                candidate_skills.update(self.keyword_index[kw])
        
        if not candidate_skills:
            logger.debug("没有候选规则匹配")
            return None
        
        # 遍历规则（按优先级排序，高优先级在前）
        min_threshold = self.config.get("min_confidence_threshold", 0.90)
        
        for rule in self.rules:
            # 跳过不在候选集中的规则
            if rule["skill_name"] not in candidate_skills:
                continue
            
            # 1. 检查必填关键词（快速失败）
            required_keywords = rule.get("required_keywords", [])
            if not all(kw in user_input_lower for kw in required_keywords):
                continue
            
            # 2. 检查排除词（快速失败）
            exclude_keywords = rule.get("exclude_keywords", [])
            if any(kw in user_input_lower for kw in exclude_keywords):
                logger.debug(
                    f"规则 {rule['skill_name']} 被排除词过滤: "
                    f"{[kw for kw in exclude_keywords if kw in user_input_lower]}"
                )
                continue
            
            # 3. 计算置信度
            confidence = self._calculate_confidence(user_input_lower, rule)
            
            # 4. 检查置信度阈值
            if confidence < min_threshold:
                continue
            
            # 5. 验证 Skill 是否可用
            if available_skills:
                skill_names = [s.get("skill_name") for s in available_skills]
                if rule["skill_name"] not in skill_names:
                    logger.debug(
                        f"规则 {rule['skill_name']} 对应的 Skill 不可用"
                    )
                    continue
            
            # 6. 找到匹配，提前返回（因为规则已按优先级排序）
            matched_keywords = self._get_matched_keywords(user_input_lower, rule)
            result = RuleMatchResult(
                skill_name=rule["skill_name"],
                confidence=confidence,
                matched_keywords=matched_keywords,
                reason=f"规则匹配: {rule.get('description', rule['skill_name'])}"
            )
            
            logger.info(
                f"规则匹配成功: {result.skill_name} "
                f"(confidence={result.confidence:.2f}, "
                f"keywords={result.matched_keywords})"
            )
            
            return result  # 提前返回，不再遍历后续规则
        
        # 没有匹配
        return None
    
    def _calculate_confidence(self, user_input: str, rule: dict) -> float:
        """
        计算匹配置信度
        
        Args:
            user_input: 用户输入（小写）
            rule: 匹配规则
            
        Returns:
            置信度 (0.0-1.0)
        """
        # 基础置信度
        confidence = rule.get("confidence_base", 0.95)
        
        # 可选关键词加成
        optional_keywords = rule.get("optional_keywords", [])
        matched_optional = sum(1 for kw in optional_keywords if kw in user_input)
        
        boost_per_optional = rule.get("confidence_boost_per_optional", 0.01)
        max_boost = self.config.get("max_optional_boost", 0.05)
        
        boost = min(matched_optional * boost_per_optional, max_boost)
        confidence = min(confidence + boost, 1.0)
        
        return confidence
    
    def _get_matched_keywords(self, user_input: str, rule: dict) -> List[str]:
        """
        获取匹配的关键词列表
        
        Args:
            user_input: 用户输入（小写）
            rule: 匹配规则
            
        Returns:
            匹配的关键词列表
        """
        matched = []
        
        # 必填关键词
        for kw in rule.get("required_keywords", []):
            if kw in user_input:
                matched.append(kw)
        
        # 可选关键词
        for kw in rule.get("optional_keywords", []):
            if kw in user_input:
                matched.append(kw)
        
        return matched
    
    def reload_rules(self):
        """重新加载规则（支持热更新）"""
        logger.info(f"重新加载意图匹配规则 (business: {self.business_code})")
        self._load_rules()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计信息
        """
        return {
            "business_code": self.business_code,
            "total_rules": len(self.rules),
            "enabled": self.config.get("enable_rule_matching", True),
            "min_confidence_threshold": self.config.get("min_confidence_threshold", 0.90),
            "fallback_to_llm": self.config.get("fallback_to_llm", True)
        }
