"""
背包礼物发放 Skill - 支持单个和批量礼物发放
"""
from typing import Dict, Any, List
from agent_core.protocol import SkillInput, SkillOutput
from agent_core.helpers.gift_type_manager import gift_type_manager
from agent_core.skills.standard import BackendGiftIssueSkill
from .base_mcp_skill import BaseMCPSkill
import logging

logger = logging.getLogger(__name__)


class AddBackpackGiftSkill(BaseMCPSkill):
    """背包礼物发放 Skill - 支持批量礼物"""
    
    def execute(self, skill_input: SkillInput) -> SkillOutput:
        """
        执行背包礼物发放 - 支持单个和批量发放
        
        单个发放：gift_id + num
        批量发放：gift_ids 或 gift_nums
        """
        try:
            params = BackendGiftIssueSkill.normalize(skill_input.params, location="backpack")
            valid, error = BackendGiftIssueSkill.validate(params)
            if not valid:
                return SkillOutput(code=400, msg=f"❌ {error}")
            gift_id = params.get("gift_id")
            gift_ids = params.get("gift_ids", [])
            gift_nums = params.get("gift_nums", {})
            user_id = params.get("user_id")
            duration_days = params.get("duration_days", 7)
            
            # 判断是批量发放还是单个发放
            is_batch = len(gift_ids) > 0 or len(gift_nums) > 0
            
            if is_batch:
                # 批量发放多个礼物
                return self._execute_batch(
                    skill_input, gift_ids, gift_nums, user_id, duration_days
                )
            else:
                # 单个礼物发放
                return self._execute_single(skill_input, params)
            
        except Exception as e:
            logger.error(f"背包礼物发放失败: {e}", exc_info=True)
            return SkillOutput(
                code=500,
                msg=f"发放失败: {str(e)}",
                success=False
            )
    
    def _execute_single(
        self, 
        skill_input: SkillInput,
        params: Dict[str, Any]
    ) -> SkillOutput:
        """
        执行单个礼物发放
        
        Args:
            skill_input: Skill输入
            params: 参数字典
            
        Returns:
            执行结果
        """
        # 验证必需参数
        gift_id = params.get("gift_id")
        if not gift_id:
            return SkillOutput(
                code=400,
                msg="❌ 缺少礼物ID\n\n💡 示例：给用户9075566发礼物301到背包",
                success=False
            )
        
        # 移除批量参数
        params.pop("gift_ids", None)
        params.pop("gift_nums", None)
        
        # 创建新的 SkillInput
        adapted_input = SkillInput(
            user_input=skill_input.user_input,
            business_code=skill_input.business_code,
            session_id=skill_input.session_id,
            params=params,
            operator=skill_input.operator,
            env=skill_input.env,
            context=skill_input.context,
            skill_name=skill_input.skill_name,
            skill_type=skill_input.skill_type
        )
        
        # 调用父类执行
        return super().execute(adapted_input)
    
    def _execute_batch(
        self,
        skill_input: SkillInput,
        gift_ids: List[int],
        gift_nums: Dict[str, int],
        user_id: int,
        duration_days: int
    ) -> SkillOutput:
        """
        执行批量礼物发放
        
        Args:
            skill_input: Skill输入
            gift_ids: 礼物ID列表
            gift_nums: 礼物ID到数量的映射
            user_id: 用户ID
            duration_days: 有效期天数
            
        Returns:
            批量执行结果
        """
        # 构建礼物发放列表
        gift_list = []
        
        if gift_nums:
            # 使用 gift_nums 映射（礼物ID -> 数量）
            for gift_id_str, num in gift_nums.items():
                gift_id = int(gift_id_str) if isinstance(gift_id_str, str) else gift_id_str
                gift_list.append({"gift_id": gift_id, "num": num})
        elif gift_ids:
            # 使用 gift_ids 列表（默认数量为1）
            for gift_id in gift_ids:
                gift_list.append({"gift_id": gift_id, "num": 1})
        
        if not gift_list:
            return SkillOutput(
                code=400,
                msg="没有找到要发放的礼物",
                success=False
            )
        
        logger.info(f"开始批量发放 {len(gift_list)} 个礼物到背包，用户: {user_id}")
        
        # 批量发放
        results = []
        success_count = 0
        failed_count = 0
        
        for item in gift_list:
            gift_id = item["gift_id"]
            num = item["num"]
            
            try:
                # 验证礼物类型
                if not gift_type_manager.supports_backpack(gift_id):
                    gift_type_name = gift_type_manager.get_gift_type_name(gift_id)
                    failed_count += 1
                    results.append({
                        "gift_id": gift_id,
                        "num": num,
                        "status": "failed",
                        "error": f"礼物 {gift_id} 是{gift_type_name}，不支持发放到背包"
                    })
                    logger.warning(f"✗ 礼物 {gift_id} 不支持背包发放")
                    continue
                
                # 构造单个发放的参数
                single_params = {
                    "gift_id": gift_id,
                    "user_id": user_id,
                    "num": num,
                    "duration_days": duration_days
                }
                
                # 创建单个发放的 SkillInput
                single_input = SkillInput(
                    user_input=f"发放礼物{gift_id}({num}个)到用户{user_id}背包",
                    business_code=skill_input.business_code,
                    session_id=skill_input.session_id,
                    params=single_params,
                    operator=skill_input.operator,
                    env=skill_input.env,
                    context=skill_input.context,
                    skill_name=skill_input.skill_name,
                    skill_type=skill_input.skill_type
                )
                
                # 调用父类执行单个发放
                result = super().execute(single_input)
                
                if result.success:
                    success_count += 1
                    results.append({
                        "gift_id": gift_id,
                        "num": num,
                        "status": "success",
                        "message": result.msg,
                        "data": result.data
                    })
                    logger.info(f"✓ 成功发放礼物 {gift_id}({num}个) 到用户 {user_id} 背包")
                else:
                    failed_count += 1
                    results.append({
                        "gift_id": gift_id,
                        "num": num,
                        "status": "failed",
                        "error": result.msg
                    })
                    logger.warning(f"✗ 发放礼物 {gift_id} 失败: {result.msg}")
                    
            except Exception as e:
                failed_count += 1
                results.append({
                    "gift_id": gift_id,
                    "num": num,
                    "status": "failed",
                    "error": str(e)
                })
                logger.error(f"✗ 发放礼物 {gift_id} 异常: {e}")
        
        # 构建友好的批量结果消息
        message_lines = []
        if failed_count == 0:
            message_lines.append(f"✅ 批量发放成功！\n")
            message_lines.append(f"已为用户 {user_id} 发放 {len(gift_list)} 个礼物到背包：\n")
        else:
            message_lines.append(f"⚠️ 批量发放完成：成功 {success_count} 个，失败 {failed_count} 个\n")
        
        # 添加每个礼物的详细信息
        for record in results:
            gift_id = record['gift_id']
            num = record['num']
            if record['status'] == 'success':
                msg = record.get('message', '')
                message_lines.append(msg.strip())
            else:
                error = record.get('error', '未知错误')
                message_lines.append(f"❌ 礼物 {gift_id}({num}个): {error}")
        
        friendly_message = "\n\n".join(message_lines)
        
        # 返回批量结果（简化数据结构）
        return SkillOutput(
            code=0 if failed_count == 0 else 207,  # 207 = Multi-Status
            msg=friendly_message,
            data={
                "user_id": user_id,
                "success_count": success_count,
                "failed_count": failed_count,
                "total_count": len(gift_list)
            },
            format="wechat_card"
        )
