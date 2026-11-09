"""
实体验证助手 - 在执行操作前验证用户/直播间/礼物是否存在
"""
from typing import Dict, Any, Optional, Tuple
import logging
from agent_core.protocol import SkillInput

logger = logging.getLogger(__name__)


class EntityValidator:
    """实体验证助手"""
    
    def __init__(self, business_code: str, skill_core):
        """
        初始化实体验证器
        
        Args:
            business_code: 业务代码
            skill_core: SkillCore实例，用于调用查询工具
        """
        self.business_code = business_code
        self.skill_core = skill_core
    
    def validate_user(self, user_id: int) -> Tuple[bool, Optional[str]]:
        """
        验证用户是否存在
        
        Args:
            user_id: 用户ID
            
        Returns:
            (是否存在, 错误信息)
        """
        try:
            # 调用 query_user_info 查询用户
            skill_input = SkillInput(
                user_input=f"查询用户{user_id}",
                business_code=self.business_code,
                skill_name="query_user_info",
                params={"user_id": user_id},
                context={"skip_validation": True}
            )
            
            result = self.skill_core.execute_skill(skill_input)
            
            if result.success and result.data:
                logger.info(f"✓ 用户 {user_id} 存在")
                return True, None
            else:
                error_msg = f"用户ID {user_id} 不存在，请检查用户ID是否正确。"
                logger.warning(f"✗ 用户 {user_id} 不存在")
                return False, error_msg
                
        except Exception as e:
            logger.error(f"验证用户 {user_id} 时出错: {e}")
            # 验证失败时，为了安全起见，返回错误
            return False, f"无法验证用户ID {user_id}，请稍后重试。"
    
    def validate_room(self, room_id: int) -> Tuple[bool, Optional[str]]:
        """
        验证直播间是否存在
        
        Args:
            room_id: 直播间ID
            
        Returns:
            (是否存在, 错误信息)
        """
        try:
            # 通过直播间ID查询用户信息（直播间ID对应主播用户）
            skill_input = SkillInput(
                user_input=f"查询直播间{room_id}",
                business_code=self.business_code,
                skill_name="query_user_info",
                params={"room_id": room_id},
                context={"skip_validation": True}
            )
            
            result = self.skill_core.execute_skill(skill_input)
            
            if result.success and result.data:
                logger.info(f"✓ 直播间 {room_id} 存在")
                return True, None
            else:
                error_msg = f"直播间ID {room_id} 不存在，请检查直播间ID是否正确。"
                logger.warning(f"✗ 直播间 {room_id} 不存在")
                return False, error_msg
                
        except Exception as e:
            logger.error(f"验证直播间 {room_id} 时出错: {e}")
            return False, f"无法验证直播间ID {room_id}，请稍后重试。"
    
    def validate_gift(self, gift_id: int) -> Tuple[bool, Optional[str]]:
        """
        验证礼物是否存在
        
        Args:
            gift_id: 礼物ID
            
        Returns:
            (是否存在, 错误信息)
        """
        try:
            # 调用 check_gift_type 查询礼物
            skill_input = SkillInput(
                user_input=f"检查礼物{gift_id}",
                business_code=self.business_code,
                skill_name="check_gift_type",
                params={"gift_id": gift_id},
                context={"skip_validation": True}
            )
            
            result = self.skill_core.execute_skill(skill_input)
            
            if result.success and result.data:
                logger.info(f"✓ 礼物 {gift_id} 存在")
                return True, None
            else:
                error_msg = f"礼物ID {gift_id} 不存在，请检查礼物ID是否正确。"
                logger.warning(f"✗ 礼物 {gift_id} 不存在")
                return False, error_msg
                
        except Exception as e:
            logger.error(f"验证礼物 {gift_id} 时出错: {e}")
            return False, f"无法验证礼物ID {gift_id}，请稍后重试。"
    
    def validate_gift_issue_params(
        self, 
        params: Dict[str, Any],
        user_input: str
    ) -> Tuple[bool, Optional[str]]:
        """
        验证礼物发放参数（用户/直播间/礼物是否存在）

        Args:
            params: 参数字典
            user_input: 用户原始输入

        Returns:
            (是否通过验证, 错误信息)
        """
        gift_id = params.get("gift_id")
        target_id = params.get("target_id")
        user_id = params.get("user_id")
        room_id = params.get("room_id")
        user_ids = params.get("user_ids", [])
        room_ids = params.get("room_ids", [])
        issue_type = params.get("issue_type", "user")

        # 1. 验证礼物是否存在
        if gift_id:
            gift_valid, gift_error = self.validate_gift(gift_id)
            if not gift_valid:
                return False, gift_error

        # 2. 背包礼物特殊校验：不支持发放白给/免费礼物到直播间
        if "背包" in user_input or "backpack" in user_input.lower():
            # 判断是否是发放到直播间（优先检查用户输入文本）
            is_room_target = False

            # 优先检查用户输入中是否明确提到"直播间"
            if "直播间" in user_input or "room" in user_input.lower():
                is_room_target = True
            # 其次检查参数中的标识
            elif room_id or room_ids or issue_type == "room":
                is_room_target = True

            # 如果是发放到直播间，检查礼物类型
            if is_room_target and gift_id:
                gift_type_prefix = str(gift_id)[0] if gift_id else ""
                # 3=免费礼物, 4=白给礼物
                if gift_type_prefix in ["3", "4"]:
                    from agent_core.helpers.gift_type_manager import gift_type_manager
                    gift_type_name = gift_type_manager.get_gift_type_name(gift_id)
                    return False, f"礼物 {gift_id} 是{gift_type_name}，不支持发放到直播间背包。{gift_type_name}只能发放到用户背包。"
                
                logger.info(f"✓ 礼物 {gift_id} 可以发放到直播间背包")

        # 3. 验证目标（用户或直播间）是否存在
        # 3.1 批量用户验证
        if user_ids and len(user_ids) > 0:
            for uid in user_ids:
                user_valid, user_error = self.validate_user(uid)
                if not user_valid:
                    return False, user_error

        # 3.2 批量直播间验证
        elif room_ids and len(room_ids) > 0:
            for rid in room_ids:
                room_valid, room_error = self.validate_room(rid)
                if not room_valid:
                    return False, room_error

        # 3.3 单个用户验证
        elif user_id:
            user_valid, user_error = self.validate_user(user_id)
            if not user_valid:
                return False, user_error

        # 3.4 单个直播间验证
        elif room_id:
            room_valid, room_error = self.validate_room(room_id)
            if not room_valid:
                return False, room_error

        # 3.5 target_id 验证（根据 issue_type 判断）
        elif target_id:
            if issue_type == "room":
                room_valid, room_error = self.validate_room(target_id)
                if not room_valid:
                    return False, room_error
            else:  # user 或 random
                user_valid, user_error = self.validate_user(target_id)
                if not user_valid:
                    return False, user_error

        # 所有验证通过
        return True, None
