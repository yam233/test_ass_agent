"""
Skill工厂 - 根据配置动态创建Skill实例
"""
from typing import Dict, Any
from .base_mcp_skill import BaseMCPSkill
from .execute_gift_issue_skill import ExecuteGiftIssueSkill
from .add_backpack_gift_skill import AddBackpackGiftSkill
from .query_capabilities_skill import QueryCapabilitiesSkill


class SkillFactory:
    """Skill工厂"""
    
    @staticmethod
    def create_skill(
        skill_config: Dict[str, Any],
        mcp_registry: Dict[str, Any],
        business_code: str
    ) -> BaseMCPSkill:
        """
        根据配置创建Skill实例
        
        Args:
            skill_config: Skill配置
            mcp_registry: MCP服务注册表
            
        Returns:
            Skill实例
        """
        skill_name = skill_config["skill_name"]
        skill_type = skill_config["skill_type"]
        server_name = skill_config["server_name"]
        tool_name = skill_config["tool_name"]
        
        # 特殊处理：query_capabilities 不需要真正的 MCP server
        if skill_name == "query_capabilities":
            # 创建一个虚拟的 server_config 和 tool_config
            server_config = {
                "id": "local_capabilities",
                "name": "本地能力查询",
                "type": "local",
                "baseUrl": "local"
            }
            tool_config = {
                "toolName": "get_capabilities",
                "toolDesc": "查询系统能力",
                "method": "GET",
                "path": "/capabilities"
            }
            
            return QueryCapabilitiesSkill(
                skill_name=skill_name,
                skill_type=skill_type,
                business_code=business_code,
                server_config=server_config,
                tool_config=tool_config
            )
        
        # 获取服务器配置
        servers = mcp_registry.get("mcpServers", {})
        server_config = servers.get(server_name)
        
        if not server_config:
            raise ValueError(f"MCP服务器未找到: {server_name}")
        
        # 获取工具配置
        tools = server_config.get("tools", [])
        tool_config = None
        for tool in tools:
            if tool.get("toolName") == tool_name:
                tool_config = tool
                break
        
        if not tool_config:
            raise ValueError(f"工具未找到: {tool_name}")
        
        # 根据 skill_name 创建特定的 Skill 实例
        if skill_name == "execute_gift_issue":
            return ExecuteGiftIssueSkill(
                skill_name=skill_name,
                skill_type=skill_type,
                business_code=business_code,
                server_config=server_config,
                tool_config=tool_config
            )
        
        if skill_name == "add_backpack_gift":
            return AddBackpackGiftSkill(
                skill_name=skill_name,
                skill_type=skill_type,
                business_code=business_code,
                server_config=server_config,
                tool_config=tool_config
            )
        
        if skill_name == "query_capabilities":
            return QueryCapabilitiesSkill(
                skill_name=skill_name,
                skill_type=skill_type,
                business_code=business_code,
                server_config=server_config,
                tool_config=tool_config
            )
        
        # 默认创建 BaseMCPSkill 实例
        return BaseMCPSkill(
            skill_name=skill_name,
            skill_type=skill_type,
            business_code=business_code,
            server_config=server_config,
            tool_config=tool_config
        )
