"""
统一的消息格式化工具
用于生成友好、一致的用户提示消息
"""
from typing import List, Dict, Any, Optional
import re


class MessageFormatter:
    """统一的消息格式化工具"""
    
    @staticmethod
    def sanitize_error_message(message: str) -> str:
        """
        清理错误消息中的敏感信息
        
        Args:
            message: 原始错误消息
            
        Returns:
            清理后的错误消息
        """
        if not message:
            return message
            
        # 移除接口地址
        message = re.sub(r'接口：[^\n]*', '', message)
        message = re.sub(r'接口地址：[^\n]*', '', message)
        message = re.sub(r'URL：[^\n]*', '', message)
        
        # 移除具体的HTTP地址
        message = re.sub(r'https?://[^\s\n]*', '', message)
        
        # 移除操作详情中的敏感信息，但保留操作描述
        message = re.sub(r'操作：([^（\n]*)[（][^）]*[）]', r'操作：\1', message)
        
        # 清理多余的空行和空格
        message = re.sub(r'\n\s*\n', '\n', message)
        message = message.strip()
        
        return message
    
    @staticmethod
    def error_with_examples(
        error_reason: str,
        examples: Optional[List[str]] = None,
        help_text: Optional[str] = None
    ) -> str:
        """
        生成带示例的错误消息
        
        Args:
            error_reason: 错误原因
            examples: 示例列表（可选）
            help_text: 帮助文本（可选）
            
        Returns:
            格式化的错误消息
        """
        lines = [f"❌ {error_reason}"]
        
        if examples:
            lines.append("")
            lines.append("💡 正确示例：")
            for example in examples:
                lines.append(f"  • {example}")
        
        if help_text:
            lines.append("")
            lines.append(f"📖 {help_text}")
        
        return "\n".join(lines)
    
    @staticmethod
    def success_with_details(
        success_message: str,
        details: Optional[Dict[str, Any]] = None,
        suggestions: Optional[List[str]] = None
    ) -> str:
        """
        生成带详情和建议的成功消息
        
        Args:
            success_message: 成功消息
            details: 详细信息字典（可选）
            suggestions: 建议操作列表（可选）
            
        Returns:
            格式化的成功消息
        """
        lines = [f"✅ {success_message}"]
        
        if details:
            lines.append("")
            for key, value in details.items():
                lines.append(f"  {key}: {value}")
        
        if suggestions:
            lines.append("")
            lines.append("💡 您可能还想：")
            for suggestion in suggestions:
                lines.append(f"  • {suggestion}")
        
        return "\n".join(lines)
    
    @staticmethod
    def missing_param_error(
        param_name: str,
        param_description: str,
        examples: List[str]
    ) -> str:
        """
        生成缺少参数的错误消息
        
        Args:
            param_name: 参数名称
            param_description: 参数描述
            examples: 示例列表
            
        Returns:
            格式化的错误消息
        """
        return MessageFormatter.error_with_examples(
            error_reason=f"缺少{param_description}",
            examples=examples
        )
    
    @staticmethod
    def not_found_error(
        resource_type: str,
        resource_id: Any,
        examples: Optional[List[str]] = None
    ) -> str:
        """
        生成资源未找到的错误消息
        
        Args:
            resource_type: 资源类型（如"外观"、"用户"、"礼物"）
            resource_id: 资源ID
            examples: 示例列表（可选）
            
        Returns:
            格式化的错误消息
        """
        error_reason = f"未找到{resource_type}ID {resource_id} 的配置"
        help_text = f"请确认{resource_type}ID是否正确"
        
        return MessageFormatter.error_with_examples(
            error_reason=error_reason,
            examples=examples,
            help_text=help_text
        )
    
    @staticmethod
    def validation_error(
        field_name: str,
        error_detail: str,
        correct_format: Optional[str] = None
    ) -> str:
        """
        生成验证错误消息
        
        Args:
            field_name: 字段名称
            error_detail: 错误详情
            correct_format: 正确格式说明（可选）
            
        Returns:
            格式化的错误消息
        """
        lines = [f"❌ {field_name}验证失败：{error_detail}"]
        
        if correct_format:
            lines.append("")
            lines.append(f"💡 正确格式：{correct_format}")
        
        return "\n".join(lines)
    
    @staticmethod
    def operation_result(
        operation_name: str,
        success_count: int,
        fail_count: int,
        details: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        生成操作结果消息
        
        Args:
            operation_name: 操作名称
            success_count: 成功数量
            fail_count: 失败数量
            details: 详细信息（可选）
            
        Returns:
            格式化的结果消息
        """
        if fail_count == 0:
            message = f"✅ {operation_name}完成：成功{success_count}次"
        else:
            message = f"⚠️ {operation_name}部分失败：成功{success_count}次，失败{fail_count}次"
        
        lines = [message]
        
        if details:
            lines.append("")
            for key, value in details.items():
                lines.append(f"  {key}: {value}")
        
        return "\n".join(lines)
