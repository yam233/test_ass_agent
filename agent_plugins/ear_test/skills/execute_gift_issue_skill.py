"""
专属礼物发放 Skill - 参数映射适配器 + 批量发放支持
将 target_id 根据礼物类型映射到 user_id 或 room_id
支持批量发放给多个用户/直播间
"""
from typing import Dict, Any, List
from agent_core.protocol import SkillInput, SkillOutput
from agent_core.helpers.gift_type_manager import gift_type_manager
from agent_core.skills.standard import BackendGiftIssueSkill
from .base_mcp_skill import BaseMCPSkill
import logging

logger = logging.getLogger(__name__)


class ExecuteGiftIssueSkill(BaseMCPSkill):
    """专属礼物发放 Skill"""
    
    def execute(self, skill_input: SkillInput) -> SkillOutput:
        """
        执行礼物发放 - 支持单个和批量发放
        
        单个发放：将 target_id 映射到 user_id 或 room_id
        批量发放：给 user_ids 或 room_ids 列表中的每个目标发放
        """
        try:
            # 获取参数
            params = BackendGiftIssueSkill.normalize(skill_input.params, location="exclusive_tab")
            valid, error = BackendGiftIssueSkill.validate(params)
            if not valid:
                return SkillOutput(code=400, msg=f"❌ {error}")
            gift_id = params.get("gift_id")
            target_id = params.get("target_id")
            user_ids = params.get("user_ids", [])
            room_ids = params.get("room_ids", [])
            duration_days = params.get("duration_days", 7)
            
            # 判断是批量发放还是单个发放
            is_batch = len(user_ids) > 0 or len(room_ids) > 0
            
            if is_batch:
                # 批量发放
                return self._execute_batch(
                    skill_input, gift_id, user_ids, room_ids, duration_days
                )
            else:
                # 单个发放
                return self._execute_single(
                    skill_input, gift_id, target_id, params
                )
            
        except Exception as e:
            logger.error(f"礼物发放失败: {e}", exc_info=True)
            return SkillOutput(
                code=500,
                msg=f"发放失败: {str(e)}",
                success=False
            )
    
    def _execute_single(
        self, 
        skill_input: SkillInput, 
        gift_id: int, 
        target_id: int,
        params: Dict[str, Any]
    ) -> SkillOutput:
        """
        执行单个发放
        
        Args:
            skill_input: Skill输入
            gift_id: 礼物ID
            target_id: 目标ID
            params: 参数字典
            
        Returns:
            执行结果
        """
        # 验证必需参数
        if not gift_id:
            return SkillOutput(
                code=400,
                msg="❌ 缺少礼物ID\n\n💡 示例：给用户9075566发礼物20123到专属tab",
                success=False
            )
        
        if not target_id:
            return SkillOutput(
                code=400,
                msg="❌ 缺少用户ID或直播间ID\n\n💡 示例：给用户9075566发礼物20123到专属tab",
                success=False
            )
        
        # 使用配置驱动的参数映射
        target_param = gift_type_manager.get_target_param(gift_id)
        params[target_param] = target_id
        params.pop("target_id", None)
        
        logger.info(f"礼物 {gift_id} ({gift_type_manager.get_gift_type_name(gift_id)}) 映射参数: {target_param}={target_id}")
        
        # 移除不需要的参数
        params.pop("issue_type", None)
        params.pop("batch_count", None)
        params.pop("user_ids", None)
        params.pop("room_ids", None)
        
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
        gift_id: int,
        user_ids: List[int],
        room_ids: List[int],
        duration_days: int
    ) -> SkillOutput:
        """
        执行批量发放
        
        Args:
            skill_input: Skill输入
            gift_id: 礼物ID
            user_ids: 用户ID列表
            room_ids: 直播间ID列表
            duration_days: 有效期天数
            
        Returns:
            批量执行结果
        """
        # 确定目标列表和参数名
        if len(user_ids) > 0:
            target_ids = user_ids
            param_name = "user_id"
            target_type = "用户"
        else:
            target_ids = room_ids
            param_name = "room_id"
            target_type = "直播间"
        
        logger.info(f"开始批量发放礼物 {gift_id} 给 {len(target_ids)} 个{target_type}")
        
        # 批量发放
        results = []
        success_count = 0
        failed_count = 0
        
        for target_id in target_ids:
            try:
                # 构造单个发放的参数
                single_params = {
                    "gift_id": gift_id,
                    param_name: target_id,
                    "duration_days": duration_days
                }
                
                # 创建单个发放的 SkillInput
                single_input = SkillInput(
                    user_input=f"发放礼物{gift_id}给{target_type}{target_id}",
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
                        "target_id": target_id,
                        "status": "success",
                        "message": result.msg,
                        "data": result.data
                    })
                    logger.info(f"✓ 成功发放礼物 {gift_id} 给{target_type} {target_id}")
                else:
                    failed_count += 1
                    results.append({
                        "target_id": target_id,
                        "status": "failed",
                        "error": result.msg
                    })
                    logger.warning(f"✗ 发放礼物 {gift_id} 给{target_type} {target_id} 失败: {result.msg}")
                    
            except Exception as e:
                failed_count += 1
                results.append({
                    "target_id": target_id,
                    "status": "failed",
                    "error": str(e)
                })
                logger.error(f"✗ 发放礼物 {gift_id} 给{target_type} {target_id} 异常: {e}")
        
        # 构建友好的批量结果消息
        message_lines = []
        if failed_count == 0:
            message_lines.append(f"✅ 批量发放成功！\n")
            message_lines.append(f"已为 {len(target_ids)} 个{target_type}发放礼物 {gift_id} 到专属tab：\n")
        else:
            message_lines.append(f"⚠️ 批量发放完成：成功 {success_count} 个，失败 {failed_count} 个\n")
        
        # 添加每个目标的详细信息
        for record in results:
            target_id = record['target_id']
            if record['status'] == 'success':
                # 提取关键信息：发放ID和有效期
                msg = record.get('message', '')
                message_lines.append(msg.strip())
            else:
                error = record.get('error', '未知错误')
                message_lines.append(f"❌ {target_type} {target_id}: {error}")
        
        friendly_message = "\n\n".join(message_lines)
        
        # 返回批量结果（简化数据结构）
        return SkillOutput(
            code=0 if failed_count == 0 else 207,  # 207 = Multi-Status
            msg=friendly_message,
            data={
                "gift_id": gift_id,
                "target_type": target_type,
                "success_count": success_count,
                "failed_count": failed_count,
                "total_count": len(target_ids)
            },
            format="wechat_card"
        )
