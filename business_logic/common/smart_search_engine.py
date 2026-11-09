"""
智能搜索引擎 - 基于语义相似度的配置搜索
使用可配置的同义词映射和智能评分算法，避免硬编码
"""
import json
import os
import logging
import re
from typing import Dict, List, Any, Set, Tuple
from collections import defaultdict, Counter
import math

logger = logging.getLogger(__name__)


class SmartSearchEngine:
    """智能搜索引擎"""
    
    def __init__(self, config_path: str = None, synonym_path: str = None):
        """
        初始化搜索引擎
        
        Args:
            config_path: 配置文件路径
            synonym_path: 同义词配置路径
        """
        self.config_path = config_path or self._get_default_config_path()
        self.synonym_path = synonym_path or self._get_default_synonym_path()
        
        self.documents = {}  # 文档集合
        self.synonym_map = {}  # 同义词映射
        self.idf_scores = {}  # IDF分数
        self.field_weights = {  # 字段权重（可配置）
            'name': 10.0,
            'tags': 5.0,
            'description': 2.0,
            'category': 1.0
        }
        
        self._load_synonyms()
        self._load_documents()
        self._build_idf_index()
    
    def _get_default_config_path(self) -> str:
        """获取默认配置文件路径"""
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config",
            "backend_urls.json"
        )
    
    def _get_default_synonym_path(self) -> str:
        """获取默认同义词配置路径"""
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config",
            "search_synonyms.json"
        )
    
    def _load_synonyms(self):
        """加载同义词配置"""
        try:
            if os.path.exists(self.synonym_path):
                with open(self.synonym_path, 'r', encoding='utf-8') as f:
                    synonym_config = json.load(f)
                    
                # 构建双向映射
                for canonical, synonyms in synonym_config.get('synonyms', {}).items():
                    canonical_lower = canonical.lower()
                    # 标准词映射到自己
                    self.synonym_map[canonical_lower] = canonical_lower
                    # 同义词映射到标准词
                    for syn in synonyms:
                        self.synonym_map[syn.lower()] = canonical_lower
                
                logger.info(f"加载同义词配置成功，共 {len(synonym_config.get('synonyms', {}))} 组")
            else:
                logger.warning(f"同义词配置文件不存在: {self.synonym_path}，使用默认配置")
                self._create_default_synonyms()
        except Exception as e:
            logger.error(f"加载同义词配置失败: {e}")
            self._create_default_synonyms()
    
    def _create_default_synonyms(self):
        """创建默认同义词配置"""
        default_synonyms = {
            "synonyms": {
                "超能魔方": ["魔方", "超能魔方配置", "魔方配置"],
                "随机礼物": ["随机礼物配置", "随机礼物奖池"],
                "奖池": ["奖池配置", "抽奖池"],
                "外观": ["外观配置", "外观资源"],
                "礼物": ["礼物配置", "礼物信息"],
                "用户": ["用户信息", "用户数据"],
                "直播间": ["房间", "直播间信息"],
                "背包": ["背包礼物", "背包配置"],
                "mongo": ["mongodb", "数据库"],
                "grafana": ["报表", "仪表板", "监控"],
                "mysql": ["数据库"]
            },
            "stopwords": ["地址", "url", "链接", "网址", "在哪", "查询", "的", "配置"]
        }
        
        # 保存默认配置
        try:
            os.makedirs(os.path.dirname(self.synonym_path), exist_ok=True)
            with open(self.synonym_path, 'w', encoding='utf-8') as f:
                json.dump(default_synonyms, f, ensure_ascii=False, indent=2)
            logger.info(f"创建默认同义词配置: {self.synonym_path}")
        except Exception as e:
            logger.error(f"创建默认同义词配置失败: {e}")
        
        # 加载到内存
        for canonical, synonyms in default_synonyms['synonyms'].items():
            canonical_lower = canonical.lower()
            self.synonym_map[canonical_lower] = canonical_lower
            for syn in synonyms:
                self.synonym_map[syn.lower()] = canonical_lower
    
    def _load_documents(self):
        """加载文档集合"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            for doc_id, doc_data in config.items():
                self.documents[doc_id] = {
                    'id': doc_id,
                    'name': doc_data.get('name', ''),
                    'url': doc_data.get('url', ''),
                    'source': doc_data.get('source', ''),
                    'description': doc_data.get('description', ''),
                    'tags': doc_data.get('tags', []),
                    'category': doc_data.get('category', ''),
                    'raw': doc_data
                }
            
            logger.info(f"加载文档成功，共 {len(self.documents)} 个")
        except Exception as e:
            logger.error(f"加载文档失败: {e}")
            self.documents = {}
    
    def _tokenize(self, text: str) -> List[str]:
        """
        分词和标准化
        
        Args:
            text: 输入文本
            
        Returns:
            词列表
        """
        if not text:
            return []
        
        # 转小写
        text = text.lower()
        
        # 简单分词（中文按字符，英文按单词）
        tokens = []
        
        # 定义常见的完整词（优先匹配）
        complete_words = [
            '超能魔方', '魔方', '随机礼物', '幸运礼物', '专属礼物',
            '外观配置', '外观', '礼物配置', '礼物', '奖池配置', '奖池',
            '用户信息', '用户', '直播间', '背包', '座驾', '头像框',
            '宝箱', '活动', '任务', '奖励', '报警', '监控'
        ]
        
        # 先提取完整词
        found_words = set()
        for word in complete_words:
            if word in text:
                tokens.append(word)
                found_words.add(word)
        
        # 提取中文词组（2-4字）
        chinese_pattern = re.compile(r'[\u4e00-\u9fff]+')
        for match in chinese_pattern.finditer(text):
            word = match.group()
            # 添加完整词
            if word not in found_words:
                tokens.append(word)
            
            # 只添加2-3字的子串（减少噪音）
            for length in range(2, min(4, len(word) + 1)):
                for i in range(len(word) - length + 1):
                    substring = word[i:i+length]
                    # 跳过已经作为完整词添加的
                    if substring not in found_words:
                        tokens.append(substring)
        
        # 提取英文单词和数字
        word_pattern = re.compile(r'[a-z0-9]+')
        tokens.extend(word_pattern.findall(text))
        
        return tokens
    
    def _normalize_query(self, query: str) -> List[str]:
        """
        标准化查询（应用同义词映射和停用词过滤）
        
        Args:
            query: 查询字符串
            
        Returns:
            标准化后的词列表
        """
        # 分词
        tokens = self._tokenize(query)
        
        # 应用同义词映射
        normalized = []
        for token in tokens:
            # 查找同义词映射
            canonical = self.synonym_map.get(token, token)
            if canonical not in normalized:
                normalized.append(canonical)
        
        return normalized
    
    def _build_idf_index(self):
        """构建IDF索引"""
        # 统计每个词在多少文档中出现
        doc_freq = defaultdict(int)
        total_docs = len(self.documents)
        
        for doc in self.documents.values():
            # 收集文档中的所有词
            doc_tokens = set()
            
            # 名称
            doc_tokens.update(self._tokenize(doc['name']))
            # 标签
            for tag in doc['tags']:
                doc_tokens.update(self._tokenize(tag))
            # 描述
            doc_tokens.update(self._tokenize(doc['description']))
            # 分类
            doc_tokens.update(self._tokenize(doc['category']))
            
            # 更新文档频率
            for token in doc_tokens:
                doc_freq[token] += 1
        
        # 计算IDF
        for token, freq in doc_freq.items():
            self.idf_scores[token] = math.log((total_docs + 1) / (freq + 1)) + 1
    
    def _calculate_bm25_score(
        self,
        query_tokens: List[str],
        doc: Dict[str, Any],
        k1: float = 1.5,
        b: float = 0.75
    ) -> float:
        """
        计算BM25分数
        
        Args:
            query_tokens: 查询词列表
            doc: 文档
            k1: BM25参数
            b: BM25参数
            
        Returns:
            BM25分数
        """
        score = 0.0
        
        # 计算每个字段的分数
        for field, weight in self.field_weights.items():
            if field == 'tags':
                # 标签是列表
                field_text = ' '.join(doc.get(field, []))
            else:
                field_text = doc.get(field, '')
            
            if not field_text:
                continue
            
            # 分词
            field_tokens = self._tokenize(field_text)
            field_length = len(field_tokens)
            
            if field_length == 0:
                continue
            
            # 计算词频
            term_freq = Counter(field_tokens)
            
            # 计算字段的BM25分数
            field_score = 0.0
            for query_token in query_tokens:
                if query_token in term_freq:
                    tf = term_freq[query_token]
                    idf = self.idf_scores.get(query_token, 1.0)
                    
                    # BM25公式
                    numerator = tf * (k1 + 1)
                    denominator = tf + k1 * (1 - b + b * field_length / 10)  # 假设平均长度为10
                    
                    field_score += idf * (numerator / denominator)
            
            # 应用字段权重
            score += field_score * weight
        
        return score
    
    def _apply_filters(self, query: str, doc: Dict[str, Any]) -> Tuple[bool, float]:
        """
        应用过滤器和特殊规则
        
        Args:
            query: 原始查询
            doc: 文档
            
        Returns:
            (是否通过过滤, 额外分数)
        """
        query_lower = query.lower()
        extra_score = 0.0
        
        # 过滤线上环境（排除生产环境）
        name_lower = doc['name'].lower()
        description_lower = doc.get('description', '').lower()
        
        # 排除包含"线上"、"生产"、"prod"、"production"的配置
        exclude_keywords = ['线上', '生产', 'prod', 'production', '[线上]', '【线上】']
        for keyword in exclude_keywords:
            if keyword in name_lower or keyword in description_lower:
                return False, 0.0
        
        # 数据源过滤
        source_filters = {
            'mongo': ['mongo', 'mongodb'],
            'grafana': ['grafana'],
            'mysql': ['mysql']
        }
        
        detected_source = None
        for source, keywords in source_filters.items():
            if any(kw in query_lower for kw in keywords):
                detected_source = source
                break
        
        # 如果指定了数据源，只返回匹配的
        if detected_source:
            if doc['source'] != detected_source:
                return False, 0.0
            else:
                extra_score += 100.0  # 数据源匹配加分
        
        # MongoDB优先级（如果没有指定数据源）
        if not detected_source and doc['source'] == 'mongo':
            extra_score += 20.0
        
        return True, extra_score
    
    def search(
        self,
        query: str,
        limit: int = None,
        min_score: float = 0.1,
        ensure_diverse_sources: bool = True
    ) -> List[Dict[str, Any]]:
        """
        搜索文档
        
        Args:
            query: 查询字符串
            limit: 返回结果数量限制
            min_score: 最小分数阈值
            ensure_diverse_sources: 确保返回不同数据源的结果
            
        Returns:
            搜索结果列表
        """
        if not query or not query.strip():
            return []
        
        # 标准化查询
        query_tokens = self._normalize_query(query)
        
        if not query_tokens:
            return []
        
        logger.info(f"搜索查询: '{query}' -> 标准化: {query_tokens}")
        
        # 计算每个文档的分数
        results = []
        for doc_id, doc in self.documents.items():
            # 应用过滤器
            passed, extra_score = self._apply_filters(query, doc)
            if not passed:
                continue
            
            # 计算BM25分数
            bm25_score = self._calculate_bm25_score(query_tokens, doc)
            
            # 总分数
            total_score = bm25_score + extra_score
            
            # 过滤低分结果
            if total_score >= min_score:
                results.append({
                    'key': doc_id,
                    'title': doc['name'],
                    'url': doc['url'],
                    'source': doc['source'],
                    'description': doc['description'],
                    'category': doc['category'],
                    'tags': doc['tags'],
                    'relevance_score': total_score
                })
        
        # 按分数排序
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        # 如果需要确保数据源多样性，优化结果
        if ensure_diverse_sources and limit and len(results) > 0:
            results = self._ensure_diverse_sources(results, limit)
        elif limit:
            results = results[:limit]
        
        logger.info(f"搜索完成，返回 {len(results)} 个结果")
        
        return results
    
    def _ensure_diverse_sources(self, results: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        """
        确保返回结果包含不同数据源的最佳匹配
        
        策略：
        1. 优先返回每个数据源的最佳结果（相关性阈值40%）
        2. 第二轮只添加高质量结果（相关性阈值70%）
        3. 确保Grafana和MongoDB都有代表（如果存在相关结果）
        
        Args:
            results: 排序后的结果列表
            limit: 返回数量限制（最大值）
            
        Returns:
            优化后的结果列表
        """
        if not results:
            return []
        
        # 计算相关性阈值
        max_score = results[0]['relevance_score']
        min_quality_score = max_score * 0.5  # 第一轮：50%
        high_quality_threshold = max_score * 0.8  # 第二轮：80%（更严格）
        
        # 按数据源分组，只保留有一定相关性的结果
        by_source = {}
        for result in results:
            # 只保留有一定相关性的结果
            if result['relevance_score'] >= min_quality_score:
                source = result['source']
                if source not in by_source:
                    by_source[source] = []
                by_source[source].append(result)
        
        # 如果没有相关结果，返回空
        if not by_source:
            return []
        
        # 优先选择每个数据源的最佳结果
        diverse_results = []
        source_order = ['grafana', 'mongo', 'mysql']  # 优先级顺序
        
        # 第一轮：每个数据源选择最佳结果
        for source in source_order:
            if source in by_source and len(by_source[source]) > 0:
                diverse_results.append(by_source[source][0])
                by_source[source] = by_source[source][1:]  # 移除已选择的
        
        # 处理其他数据源
        for source, items in by_source.items():
            if source not in source_order and len(items) > 0:
                diverse_results.append(items[0])
                by_source[source] = items[1:]
        
        # 第二轮：只添加高质量结果
        if len(diverse_results) < limit:
            remaining = []
            for source_items in by_source.values():
                for item in source_items:
                    if item['relevance_score'] >= high_quality_threshold:
                        remaining.append(item)
            
            # 按分数排序
            remaining.sort(key=lambda x: x['relevance_score'], reverse=True)
            
            # 只添加高质量结果
            diverse_results.extend(remaining[:limit - len(diverse_results)])
        
        # 限制到指定数量
        return diverse_results[:limit]
    
    def reload(self):
        """重新加载配置"""
        self.documents = {}
        self.synonym_map = {}
        self.idf_scores = {}
        
        self._load_synonyms()
        self._load_documents()
        self._build_idf_index()
        
        logger.info("搜索引擎重新加载完成")
