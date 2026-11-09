"""
多操作拆分器 - 检测并拆分包含多个独立操作的用户输入
"""
import re
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class MultiOperationSplitter:
    """多操作拆分器"""
    
    # 多操作分隔符模式
    SPLIT_PATTERNS = [
        r'，给',      # 中文逗号 + 给
        r'，向',      # 中文逗号 + 向
        r'；给',      # 中文分号 + 给
        r'；向',      # 中文分号 + 向
    ]

    # 通用动作词（用于识别“分隔符后是新指令”的场景）
    ACTION_PREFIX_PATTERN = (
        r'给|向|查询|查|发放|发|充值|执行|运行|修改|校验|验证|列出|获取|检查'
    )
    
    @staticmethod
    def detect_multi_operations(user_input: str) -> bool:
        """
        检测用户输入是否包含多个独立操作
        
        Args:
            user_input: 用户输入
            
        Returns:
            是否包含多个操作
        """
        # 方式1: 检查是否包含多个"给用户X"或"给直播间X"（明确分隔）
        user_count = len(re.findall(r'给\s*用户\s*\d+', user_input))
        room_count = len(re.findall(r'给\s*直播间\s*\d+', user_input))
        
        total_count = user_count + room_count
        
        if total_count > 1:
            # 检查是否是批量操作模式（给用户A，B发相同内容）
            # 如果是，则不应该拆分为多操作
            multi_target_pattern = r'给\s*(用户|直播间)\s*[\d，、和\s]+(?:发|充值)'
            if re.search(multi_target_pattern, user_input):
                logger.info(f"检测到批量操作输入（非多操作）: 给多个目标发放相同内容")
                return False
            
            logger.info(f"检测到多操作输入（方式1）: {total_count} 个操作")
            return True
        
        # 方式2: 已移除（批量操作不应该被识别为多操作）

        # 方式3: 通用拆分检测（如：给A发B、查询url、发放钻石）
        generic_ops = MultiOperationSplitter._split_generic_operations(user_input)
        if len(generic_ops) > 1:
            logger.info(f"检测到多操作输入（方式3）: {len(generic_ops)} 个操作")
            return True
        
        return False
    
    @staticmethod
    def split_operations(user_input: str) -> List[str]:
        """
        拆分多操作输入为独立的操作列表
        
        Args:
            user_input: 用户输入
            
        Returns:
            操作列表
        """
        if not MultiOperationSplitter.detect_multi_operations(user_input):
            return [user_input]
        
        # 方式1: 使用分隔符拆分
        operations = []
        
        # 使用正则表达式拆分
        # 匹配模式：，给用户/直播间
        parts = re.split(r'(，给|；给)', user_input)
        
        if len(parts) > 1:
            # 重组拆分结果
            current = parts[0]
            for i in range(1, len(parts), 2):
                if i + 1 < len(parts):
                    # 添加当前操作
                    operations.append(current.strip())
                    # 开始新操作（去掉分隔符中的逗号/分号）
                    current = parts[i][1:] + parts[i + 1]  # parts[i] = "，给" -> "给"
            # 添加最后一个操作
            if current.strip():
                operations.append(current.strip())
        else:
            # 如果拆分失败，尝试其他方法
            # 查找所有"给用户X"或"给直播间X"的位置
            matches = list(re.finditer(r'给\s*(用户|直播间)\s*\d+', user_input))
            
            if len(matches) > 1:
                for i, match in enumerate(matches):
                    start = match.start()
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(user_input)
                    operation = user_input[start:end].strip()
                    # 移除末尾的逗号或分号
                    operation = re.sub(r'[，；]+$', '', operation)
                    operations.append(operation)
            else:
                operations = [user_input]
        
        # 方式2: 通用拆分兜底
        if len(operations) <= 1:
            generic_ops = MultiOperationSplitter._split_generic_operations(user_input)
            if len(generic_ops) > 1:
                operations = generic_ops

        logger.info(f"拆分为 {len(operations)} 个操作: {operations}")
        return operations

    @staticmethod
    def _split_generic_operations(user_input: str) -> List[str]:
        """
        通用多指令拆分：
        - 支持：； ; 换行 、并且/然后/同时
        - 对逗号只在“后面看起来是新指令”时拆分，避免误拆ID列表
        """
        normalized = re.sub(r'\s+', ' ', user_input.strip())
        if not normalized:
            return []

        # 先按强分隔符拆分
        parts = re.split(r'[；;\n]+', normalized)
        temp_ops: List[str] = []
        for part in parts:
            fragment = part.strip()
            if not fragment:
                continue
            # 再按连接词拆分
            sub_parts = re.split(r'\s*(?:并且|然后|同时)\s*', fragment)
            for sub_part in sub_parts:
                piece = sub_part.strip(" ，,。")
                if piece:
                    temp_ops.append(piece)

        # 最后按逗号拆分，但仅当后半段以动作词起始
        operations: List[str] = []
        for op in temp_ops:
            chunks = re.split(
                rf'[，,]\s*(?=(?:{MultiOperationSplitter.ACTION_PREFIX_PATTERN}))',
                op
            )
            for chunk in chunks:
                item = chunk.strip(" ，,。")
                if item:
                    operations.append(item)

        return operations
    
    @staticmethod
    def extract_context_from_first_operation(operations: List[str]) -> Dict[str, Any]:
        """
        从第一个操作中提取共享上下文（如"到背包"、"到专属tab"等）
        
        Args:
            operations: 操作列表
            
        Returns:
            共享上下文
        """
        if not operations:
            return {}
        
        first_op = operations[0]
        context = {}
        
        # 检测目标位置
        if "背包" in first_op:
            context["target_location"] = "背包"
        elif "专属" in first_op or "专属tab" in first_op:
            context["target_location"] = "专属tab"
        
        # 检测有效期
        duration_match = re.search(r'有效期\s*(\d+)\s*天', first_op)
        if duration_match:
            context["duration_days"] = int(duration_match.group(1))
        elif "永久" in first_op:
            context["duration_days"] = 1000
        
        return context
    
    @staticmethod
    def enrich_operation_with_context(
        operation: str, 
        context: Dict[str, Any]
    ) -> str:
        """
        用共享上下文丰富操作描述
        
        Args:
            operation: 操作描述
            context: 共享上下文
            
        Returns:
            丰富后的操作描述
        """
        enriched = operation
        
        # 添加目标位置
        if "target_location" in context:
            location = context["target_location"]
            if location not in enriched:
                enriched += f"到{location}"
        
        # 添加有效期
        if "duration_days" in context:
            days = context["duration_days"]
            if "有效期" not in enriched and "永久" not in enriched:
                if days == 1000:
                    enriched += "，永久有效"
                else:
                    enriched += f"，有效期{days}天"
        
        return enriched
