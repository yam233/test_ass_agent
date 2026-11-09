"""
用户提示助手 - 生成友好的错误提示和建议
"""
from typing import Dict, Any, List, Optional
import re
from .gift_type_manager import gift_type_manager


class UserPromptHelper:
    """用户提示助手"""

    @staticmethod
    def get_default_command_templates() -> str:
        """获取统一的正确指令模板。"""
        return (
            "可参考以下指令模板：\n"
            "• 查询用户9075333的信息\n"
            "• 查询用户9075333的验证码\n"
            "• 给用户9075566发礼物20123到专属tab\n"
            "• 给直播间9075367发礼物70123到专属tab\n"
            "• 给用户9075566发礼物301到背包"
        )

    @staticmethod
    def append_command_templates(message: str) -> str:
        """在提示文案后追加统一模板，避免重复追加。"""
        if "可参考以下指令模板" in message:
            return message
        return f"{message}\n\n{UserPromptHelper.get_default_command_templates()}"
    
    @staticmethod
    def _get_capabilities_message() -> str:
        """获取系统能力清单消息"""
        return """❓ 抱歉，我没有理解您的意图。以下是我的能力清单：

【用户管理】
• 查询用户信息：查询用户9075566的信息
• 获取验证码：获取手机号15000000490的验证码

【礼物管理】
• 发放专属礼物：给用户9075566发礼物20123到专属tab
• 发放背包礼物：给用户9075566发10个礼物301到背包
• 查询礼物信息：查询礼物80103的信息
• 查询礼物记录：查询用户9075566的礼物记录
• 检查礼物类型：检查礼物20123的类型
• 列出礼物类型规则：列出所有礼物类型

【奖池管理】
• 查询奖池配置：查询礼物80103的奖池配置
• 修改礼物权重为最大：将奖池257中礼物91384的权重改为最大
• 修改大奖权重为0：将奖池257中大奖91376的权重改为0

【配置检查】
• 查询外观配置：查询外观50811的配置
• 查询奖励配置：查询奖励3的配置

【外观管理】
• 发放外观到平台：给用户9075566发放外观70244，有效期7天

【背包礼物管理】
• Grafana发放背包礼物：给用户9075566发放背包礼物301，数量10
• 清空背包礼物：清空用户9075566的背包礼物301

【后台功能查询】
• 查询后台URL：查询随机礼物后台地址
• 列出功能清单：列出所有功能

【钻石充值】
• 发放钻石：给用户9075566发500万钻石

【脚本执行】
• 执行脚本：执行脚本live/draw01.py

💡 您也可以直接问我"你有什么能力"或"你会做什么"来查看完整能力清单。"""
    
    @staticmethod
    def validate_gift_id_for_exclusive_tab(gift_id: int, user_input: str) -> Optional[str]:
        """
        验证礼物ID是否支持发放到专属tab
        
        Args:
            gift_id: 礼物ID
            user_input: 用户原始输入
            
        Returns:
            错误提示信息，如果验证通过返回None
        """
        return gift_type_manager.validate_gift_id_for_exclusive_tab(gift_id, user_input)
    
    @staticmethod
    def validate_gift_id_for_backpack(gift_id: int, user_input: str) -> Optional[str]:
        """
        验证礼物ID是否支持发放到背包
        
        Args:
            gift_id: 礼物ID
            user_input: 用户原始输入
            
        Returns:
            错误提示信息，如果验证通过返回None
        """
        # 检查用户是否想发放到背包
        if "背包" not in user_input and "backpack" not in user_input.lower():
            return None
        
        if not gift_type_manager.supports_backpack(gift_id):
            gift_type_name = gift_type_manager.get_gift_type_name(gift_id)
            # 获取所有支持背包的类型
            all_types = gift_type_manager.get_all_gift_types()
            supported_types = [
                f"{r['name']}({prefix}开头)"
                for prefix, r in all_types.items()
                if r.get("support_backpack", False)
            ]
            supported_str = "、".join(supported_types)
            return f"礼物ID {gift_id} 是{gift_type_name}，不支持发放到背包。只有 {supported_str} 才支持发放到背包。"
        
        return None
    
    @staticmethod
    def generate_missing_param_prompt(
        skill_name: str,
        missing_params: List[str],
        extracted_params: Dict[str, Any],
        user_input: str
    ) -> str:
        """
        生成参数缺失的友好提示
        
        Args:
            skill_name: 技能名称
            missing_params: 缺失的参数列表
            extracted_params: 已提取的参数
            user_input: 用户原始输入
            
        Returns:
            友好的提示信息
        """
        # 用户信息查询场景
        if "查询" in user_input and "用户" in user_input and "信息" in user_input:
            if "user_id" in missing_params or "room_id" in missing_params:
                return "❌ 缺少查询参数\n\n请提供用户ID、直播间ID、手机号或邮箱中的至少一个。例如：\n• 查询用户9075566的信息\n• 查询直播间9075367的用户信息\n• 查询手机号15000000490的用户信息\n• 查询邮箱live@missevan.cn的用户信息"
        
        # 验证码查询场景
        if "验证码" in user_input:
            return "❌ 缺少查询参数\n\n请提供用户ID、手机号或邮箱中的至少一个。例如：\n• 查询用户9075566的验证码\n• 查询手机号15000000490的验证码\n• 查询邮箱live@missevan.cn的验证码"
        
        # 检查是否有礼物ID
        has_gift_id = "gift_id" in extracted_params and extracted_params["gift_id"]
        gift_id = extracted_params.get("gift_id", "")
        
        # 检查是否缺少target_id
        if "target_id" in missing_params or extracted_params.get("target_id") is None:
            # 根据礼物ID或输入内容判断类型
            if gift_id:
                target_type = gift_type_manager.get_target_type(gift_id)
                
                if target_type == "user":
                    return f"❌ 缺少用户ID\n\n💡 示例：给用户9075566发礼物{gift_id}到专属tab"
                elif target_type == "room":
                    return f"❌ 缺少直播间ID\n\n💡 示例：给直播间9075367发礼物{gift_id}到专属tab"
                elif target_type == "user_or_room":
                    return f"❌ 缺少用户ID或直播间ID\n\n💡 示例：给用户9075566发礼物{gift_id}到专属tab"
            
            # 根据输入内容判断
            if "用户" in user_input:
                return "❌ 缺少用户ID\n\n💡 示例：给用户9075566发礼物20123到专属tab"
            elif "直播间" in user_input or "房间" in user_input:
                return "❌ 缺少直播间ID\n\n💡 示例：给直播间9075367发礼物70123到专属tab"
            elif "背包" in user_input:
                return "❌ 缺少用户ID\n\n💡 示例：给用户9075566发礼物301到背包"
            else:
                return "❌ 缺少用户ID或直播间ID\n\n💡 示例：给用户9075566发礼物20123到专属tab"
        
        # 检查是否缺少gift_id
        if "gift_id" in missing_params:
            if "背包" in user_input:
                return "❌ 缺少礼物ID\n\n💡 示例：给用户9075566发礼物301到背包"
            elif "用户" in user_input:
                return "❌ 缺少礼物ID\n\n💡 示例：给用户9075566发礼物20123到专属tab"
            elif "直播间" in user_input or "房间" in user_input:
                return "❌ 缺少礼物ID\n\n💡 示例：给直播间9075367发礼物70123到专属tab"
            else:
                return "❌ 缺少礼物ID\n\n💡 示例：给用户9075566发礼物20123到专属tab"
        
        # 其他参数缺失
        param_names = "、".join(missing_params)
        return f"❌ 缺少必要参数：{param_names}\n\n💡 请提供完整信息后重试"
    
    @staticmethod
    def generate_low_confidence_prompt(
        confidence: float,
        skill_name: str,
        user_input: str,
        reason: Optional[str] = None
    ) -> str:
        """
        生成低置信度的友好提示
        
        Args:
            confidence: 置信度
            skill_name: 识别到的技能名称
            user_input: 用户原始输入
            reason: 低置信度原因
            
        Returns:
            友好的提示信息
        """
        # 完全无法理解（置信度极低）- 返回系统能力清单
        if confidence < 0.3:
            return UserPromptHelper._get_capabilities_message()
        
        # 置信度较低（0.3-0.5）
        if confidence < 0.5:
            if "礼物" in user_input:
                # 可能是礼物相关但信息不完整
                if "发" in user_input or "发送" in user_input or "发放" in user_input:
                    return UserPromptHelper.append_command_templates(
                        "❓ 信息不完整\n\n请提供完整信息：要发送什么礼物？给谁发送？例如：给用户9075566发礼物20123到专属tab"
                    )
                elif "查" in user_input or "查询" in user_input:
                    return UserPromptHelper.append_command_templates(
                        "❓ 信息不完整\n\n请提供完整信息：要查询哪个用户或直播间的礼物？例如：查询用户9075566的专属礼物"
                    )
            
            return UserPromptHelper.append_command_templates(
                f"❓ 意图不明确\n\n我不太确定您的意图（置信度：{confidence:.2f}）。请提供更详细的信息。"
            )
        
        # 不应该到这里，但作为保险
        return UserPromptHelper.append_command_templates(
            f"⚠️ 置信度较低\n\n意图识别置信度较低（{confidence:.2f}），请提供更明确的信息。"
        )
    
    @staticmethod
    def generate_param_type_error_prompt(
        param_name: str,
        expected_type: str,
        actual_value: Any,
        user_input: str
    ) -> str:
        """
        生成参数类型错误的友好提示
        
        Args:
            param_name: 参数名称
            expected_type: 期望的类型
            actual_value: 实际值
            user_input: 用户原始输入
            
        Returns:
            友好的提示信息
        """
        # 用户信息查询场景
        if "查询" in user_input and "用户" in user_input and "信息" in user_input:
            if param_name in ["user_id", "room_id", "phone", "email"]:
                return "❌ 缺少查询参数\n\n请提供用户ID、直播间ID、手机号或邮箱中的至少一个。例如：\n• 查询用户9075566的信息\n• 查询直播间9075367的用户信息\n• 查询手机号15000000490的用户信息\n• 查询邮箱live@missevan.cn的用户信息"
        
        # 验证码查询场景
        if "验证码" in user_input:
            if param_name in ["user_id", "phone", "email"]:
                return "❌ 缺少查询参数\n\n请提供用户ID、手机号或邮箱中的至少一个。例如：\n• 查询用户9075566的验证码\n• 查询手机号15000000490的验证码\n• 查询邮箱live@missevan.cn的验证码"
        
        # 礼物发放场景
        if param_name in ["target_id", "user_id", "room_id"]:
            if actual_value is None:
                if "用户" in user_input:
                    return "❌ 缺少用户ID\n\n💡 示例：给用户9075566发送礼物20123到专属tab"
                elif "直播间" in user_input or "房间" in user_input:
                    return "❌ 缺少直播间ID\n\n💡 示例：给直播间9075367发送礼物70123到专属tab"
                else:
                    return "❌ 缺少目标ID\n\n💡 请提供用户ID或直播间ID。例如：给用户9075566发礼物20123到专属tab"
        
        if param_name == "gift_id":
            if actual_value is None:
                return "❌ 缺少礼物ID\n\n💡 示例：给用户9075566发礼物20123到专属tab"
        
        # 通用类型错误提示
        return f"参数 {param_name} 格式不正确，期望类型：{expected_type}。请检查后重试。"
    
    @staticmethod
    def generate_validation_error_prompt(
        errors: List[str],
        params: Dict[str, Any],
        user_input: str
    ) -> str:
        """
        生成参数验证错误的友好提示
        
        Args:
            errors: 错误列表
            params: 提取的参数
            user_input: 用户原始输入
            
        Returns:
            友好的提示信息
        """
        if not errors:
            return "❌ 参数验证失败\n\n💡 请检查输入信息"
        
        # 解析第一个错误（通常最重要）
        error = errors[0]
        
        # 缺少必填参数
        if "缺少必填参数" in error:
            match = re.search(r"缺少必填参数:\s*(\w+)", error)
            if match:
                param_name = match.group(1)
                return UserPromptHelper.generate_missing_param_prompt(
                    skill_name="",
                    missing_params=[param_name],
                    extracted_params=params,
                    user_input=user_input
                )
        
        # 参数类型错误
        if "类型错误" in error:
            match = re.search(r"参数\s+(\w+)\s+类型错误", error)
            if match:
                param_name = match.group(1)
                actual_value = params.get(param_name)
                return UserPromptHelper.generate_param_type_error_prompt(
                    param_name=param_name,
                    expected_type="integer",
                    actual_value=actual_value,
                    user_input=user_input
                )
        
        # 目标ID范围错误
        if "目标ID必须在" in error and "之间" in error:
            target_id = params.get("target_id")
            min_id, max_id = gift_type_manager.get_id_range()
            
            if target_id is not None and target_id <= 0:
                if "用户" in user_input:
                    return f"❌ 用户ID {target_id} 无效\n\n💡 用户ID必须是大于0的正整数"
                elif "直播间" in user_input or "房间" in user_input:
                    return f"❌ 直播间ID {target_id} 无效\n\n💡 直播间ID必须是大于0的正整数"
                else:
                    return f"❌ 目标ID {target_id} 无效\n\n💡 ID必须是大于0的正整数"
            elif target_id is not None and target_id > max_id:
                if "用户" in user_input:
                    return f"❌ 用户ID {target_id} 超出范围\n\n💡 用户ID必须在{min_id}-{max_id}之间"
                elif "直播间" in user_input or "房间" in user_input:
                    return f"❌ 直播间ID {target_id} 超出范围\n\n💡 直播间ID必须在{min_id}-{max_id}之间"
                else:
                    return f"❌ 目标ID {target_id} 超出范围\n\n💡 ID必须在{min_id}-{max_id}之间"
        
        # 默认提示 - 简化错误信息
        # 移除技术细节，只保留核心错误
        simple_error = error.split(":")[-1].strip() if ":" in error else error
        return f"❌ {simple_error}\n\n💡 请检查输入信息"

    @staticmethod
    def generate_low_confidence_execute_prompt(
        confidence: float,
        threshold: float,
        skill_name: str,
        user_input: str
    ) -> str:
        """
        生成执行类操作低置信度的智能提示
        
        Args:
            confidence: 置信度
            threshold: 阈值
            skill_name: 技能名称
            user_input: 用户输入
            
        Returns:
            友好的提示信息
        """
        # 分析缺少的信息
        has_gift_id = bool(re.search(r'\d{5,}', user_input))  # 5位以上数字可能是礼物ID
        has_user = "用户" in user_input
        has_room = "直播间" in user_input or "房间" in user_input
        has_target_id = bool(re.search(r'(用户|直播间|房间)\s*\d+', user_input))
        
        # 礼物发放场景
        if "礼物" in user_input and ("发" in user_input or "发放" in user_input or "发送" in user_input):
            if has_gift_id and not has_target_id:
                # 有礼物ID，缺少接收者
                return UserPromptHelper.append_command_templates(
                    f"❌ 缺少接收者信息\n\n"
                    f"识别置信度 {confidence:.2f} 低于执行阈值 {threshold:.2f}，"
                    f"请明确指定要发给哪个用户或直播间。"
                )
            elif not has_gift_id and has_target_id:
                # 有接收者，缺少礼物ID
                return UserPromptHelper.append_command_templates(
                    f"❌ 缺少礼物ID\n\n"
                    f"识别置信度 {confidence:.2f} 低于执行阈值 {threshold:.2f}，"
                    f"请明确指定要发放的礼物ID。"
                )
            elif not has_gift_id and not has_target_id:
                # 两者都缺
                return UserPromptHelper.append_command_templates(
                    f"❌ 信息不完整\n\n"
                    f"识别置信度 {confidence:.2f} 低于执行阈值 {threshold:.2f}，"
                    f"请提供礼物ID和接收者信息。"
                )
        
        # 钻石充值场景
        if "钻石" in user_input and ("发" in user_input or "充值" in user_input or "充" in user_input):
            if not has_target_id:
                return UserPromptHelper.append_command_templates(
                    f"❌ 缺少用户信息\n\n"
                    f"识别置信度 {confidence:.2f} 低于执行阈值 {threshold:.2f}，"
                    f"请明确指定要给哪个用户充值钻石。"
                )
        
        # 通用提示
        return UserPromptHelper.append_command_templates(
            f"❌ 当前指令识别置信度为 {confidence:.2f}，低于执行阈值 {threshold:.2f}。"
            "为避免误操作，已自动拦截执行类动作。请改为更明确的执行指令，或先进行查询确认。"
        )
