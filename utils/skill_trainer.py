"""
猫耳 AI 测试助手 Skill 训练数据生成工具

功能：
1. 读取 Skill 元数据生成训练样本
2. 生成 LLM 训练兼容的 JSONL 文件
3. 验证训练数据格式
4. 支持正例和负例样本生成
"""
import json
import os
from typing import List, Dict, Any
from pathlib import Path


class SkillTrainer:
    """Skill 训练数据生成器"""
    
    def __init__(self, business_code: str = "ear_test"):
        self.business_code = business_code
        
        # 配置路径
        self.skills_registry_path = f"config/business/{business_code}/skills_registry.json"
        self.manifest_dir = f"config/business/{business_code}/manifest"
        
        # Prompt 路径
        self.common_prompt_path = "references/framework/common_train_prompt.md"
        self.business_prompt_path = f"references/business/{business_code}_train_prompt.md"
        
        # 输出路径
        self.train_data_dir = f"training_data/{business_code}"
        self.train_data_path = f"{self.train_data_dir}/skill_train_data.jsonl"
        
        # 创建输出目录
        Path(self.train_data_dir).mkdir(parents=True, exist_ok=True)
        
        # 加载配置
        self.skills_registry = self._load_skills_registry()
        self.common_prompt = self._load_prompt(self.common_prompt_path)
        self.business_prompt = self._load_prompt(self.business_prompt_path)
    
    def _load_skills_registry(self) -> Dict[str, Any]:
        """加载 Skills 注册表"""
        if not os.path.exists(self.skills_registry_path):
            raise FileNotFoundError(f"Skills 注册表不存在：{self.skills_registry_path}")
        
        with open(self.skills_registry_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _load_prompt(self, path: str) -> str:
        """加载 Prompt 文件"""
        if not os.path.exists(path):
            print(f"警告：Prompt 文件不存在：{path}")
            return ""
        
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def _load_skill_manifest(self, skill_name: str) -> Dict[str, Any]:
        """加载单个 Skill 的元数据（如果存在）"""
        manifest_path = os.path.join(self.manifest_dir, f"{skill_name}.json")
        
        if not os.path.exists(manifest_path):
            return {}
        
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def generate_positive_samples(self, skill_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成正例样本"""
        samples = []
        skill_name = skill_config["skill_name"]
        skill_type = skill_config["skill_type"]
        
        # 从 match_keywords 生成正例
        match_keywords = skill_config.get("match_keywords", [])
        param_schema = skill_config.get("param_schema", {})
        
        # 为每个关键词生成样本
        for keyword in match_keywords[:5]:  # 限制每个 Skill 最多 5 个正例
            # 构造用户输入
            user_input = self._generate_user_input(keyword, param_schema)
            
            # 构造期望输出
            expected_params = self._generate_expected_params(param_schema)
            expected_output = {
                "skill_name": skill_name,
                "skill_type": skill_type,
                "params": expected_params,
                "confidence": 0.95,
                "reason": f"识别到{skill_config['display_name']}意图"
            }
            
            # 构造训练样本
            sample = {
                "messages": [
                    {
                        "role": "system",
                        "content": f"{self.common_prompt}\n\n{self.business_prompt}"
                    },
                    {
                        "role": "user",
                        "content": user_input
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(expected_output, ensure_ascii=False, indent=2)
                    }
                ],
                "skill_name": skill_name,
                "type": "positive"
            }
            samples.append(sample)
        
        return samples
    
    def generate_negative_samples(self, skill_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成负例样本"""
        samples = []
        skill_name = skill_config["skill_name"]
        
        # 加载 manifest 中的负例
        manifest = self._load_skill_manifest(skill_name)
        negative_examples = manifest.get("negative_examples", [])
        
        for user_input in negative_examples[:3]:  # 限制每个 Skill 最多 3 个负例
            expected_output = {
                "skill_name": "unknown",
                "skill_type": "unknown",
                "params": {},
                "confidence": 0.0,
                "reason": "无法识别意图或意图不匹配"
            }
            
            sample = {
                "messages": [
                    {
                        "role": "system",
                        "content": f"{self.common_prompt}\n\n{self.business_prompt}"
                    },
                    {
                        "role": "user",
                        "content": user_input
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(expected_output, ensure_ascii=False, indent=2)
                    }
                ],
                "skill_name": skill_name,
                "type": "negative"
            }
            samples.append(sample)
        
        return samples
    
    def _generate_user_input(self, keyword: str, param_schema: Dict[str, Any]) -> str:
        """根据关键词和参数 schema 生成用户输入"""
        # 简单实现：使用关键词 + 示例参数
        user_input = keyword
        
        # 添加参数示例
        for param_name, param_def in param_schema.items():
            if param_def.get("required"):
                # 使用示例值
                if param_name == "gift_id":
                    user_input += " 20001"
                elif param_name == "user_id":
                    user_input += " 9075336"
                elif param_name == "target_id":
                    user_input += " 9075336"
                elif param_name == "phone":
                    user_input += " 13800138000"
                elif param_name == "room_id":
                    user_input += " 123456"
        
        return user_input
    
    def _generate_expected_params(self, param_schema: Dict[str, Any]) -> Dict[str, Any]:
        """生成期望的参数输出"""
        params = {}
        
        for param_name, param_def in param_schema.items():
            # 使用默认值或示例值
            if "default" in param_def:
                params[param_name] = param_def["default"]
            elif param_name == "gift_id":
                params[param_name] = 20001
            elif param_name == "user_id":
                params[param_name] = 9075336
            elif param_name == "target_id":
                params[param_name] = 9075336
            elif param_name == "phone":
                params[param_name] = "13800138000"
            elif param_name == "room_id":
                params[param_name] = 123456
            elif param_name == "duration_days":
                params[param_name] = 7
        
        return params
    
    def generate_all_train_data(self) -> None:
        """生成所有 Skill 的训练数据"""
        skills = self.skills_registry.get("skills", [])
        all_samples = []
        
        print(f"开始生成训练数据，共 {len(skills)} 个 Skills...")
        
        for skill_config in skills:
            skill_name = skill_config["skill_name"]
            
            try:
                # 生成正例
                positive_samples = self.generate_positive_samples(skill_config)
                all_samples.extend(positive_samples)
                
                # 生成负例
                negative_samples = self.generate_negative_samples(skill_config)
                all_samples.extend(negative_samples)
                
                print(f"✓ {skill_name}: {len(positive_samples)} 正例 + {len(negative_samples)} 负例")
            
            except Exception as e:
                print(f"✗ {skill_name}: 生成失败 - {str(e)}")
        
        # 写入 JSONL 文件
        with open(self.train_data_path, 'w', encoding='utf-8') as f:
            for sample in all_samples:
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')
        
        print(f"\n训练数据生成完成！")
        print(f"路径：{self.train_data_path}")
        print(f"共生成 {len(all_samples)} 条训练样本")
        
        # 生成统计信息
        self._generate_statistics(all_samples)
    
    def _generate_statistics(self, samples: List[Dict[str, Any]]) -> None:
        """生成训练数据统计信息"""
        stats = {
            "total": len(samples),
            "positive": sum(1 for s in samples if s["type"] == "positive"),
            "negative": sum(1 for s in samples if s["type"] == "negative"),
            "by_skill": {}
        }
        
        for sample in samples:
            skill_name = sample["skill_name"]
            if skill_name not in stats["by_skill"]:
                stats["by_skill"][skill_name] = {"positive": 0, "negative": 0}
            stats["by_skill"][skill_name][sample["type"]] += 1
        
        # 保存统计信息
        stats_path = f"{self.train_data_dir}/statistics.json"
        with open(stats_path, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        
        print(f"\n统计信息：")
        print(f"  总样本数：{stats['total']}")
        print(f"  正例样本：{stats['positive']}")
        print(f"  负例样本：{stats['negative']}")
        print(f"  统计文件：{stats_path}")
    
    def validate_train_data(self) -> bool:
        """验证训练数据格式"""
        if not os.path.exists(self.train_data_path):
            print(f"训练数据文件不存在：{self.train_data_path}")
            return False
        
        print("\n开始验证训练数据格式...")
        
        valid_count = 0
        invalid_count = 0
        errors = []
        
        with open(self.train_data_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    sample = json.loads(line)
                    
                    # 校验核心字段
                    assert "messages" in sample, "缺少 messages 字段"
                    assert len(sample["messages"]) == 3, "messages 长度必须为 3"
                    assert sample["messages"][0]["role"] == "system", "第一条消息必须是 system"
                    assert sample["messages"][1]["role"] == "user", "第二条消息必须是 user"
                    assert sample["messages"][2]["role"] == "assistant", "第三条消息必须是 assistant"
                    
                    # 校验 assistant 输出格式
                    assistant_content = json.loads(sample["messages"][2]["content"])
                    assert "skill_name" in assistant_content, "assistant 输出缺少 skill_name 字段"
                    assert "params" in assistant_content, "assistant 输出缺少 params 字段"
                    assert "confidence" in assistant_content, "assistant 输出缺少 confidence 字段"
                    
                    valid_count += 1
                
                except Exception as e:
                    invalid_count += 1
                    error_msg = f"第 {line_num} 行：{str(e)}"
                    errors.append(error_msg)
                    if invalid_count <= 5:  # 只显示前 5 个错误
                        print(f"  ✗ {error_msg}")
        
        print(f"\n验证完成：")
        print(f"  有效样本：{valid_count}")
        print(f"  无效样本：{invalid_count}")
        
        if invalid_count > 0:
            print(f"\n请检查并修复错误后重新生成")
            return False
        
        print(f"\n✓ 所有样本格式正确！")
        return True
    
    def export_for_finetuning(self, output_path: str = None) -> None:
        """导出用于微调的数据格式"""
        if output_path is None:
            output_path = f"{self.train_data_dir}/finetuning_data.jsonl"
        
        if not os.path.exists(self.train_data_path):
            print(f"训练数据文件不存在：{self.train_data_path}")
            return
        
        print(f"\n导出微调数据...")
        
        with open(self.train_data_path, 'r', encoding='utf-8') as f_in:
            with open(output_path, 'w', encoding='utf-8') as f_out:
                for line in f_in:
                    sample = json.loads(line)
                    # 只保留 messages 字段
                    finetuning_sample = {
                        "messages": sample["messages"]
                    }
                    f_out.write(json.dumps(finetuning_sample, ensure_ascii=False) + '\n')
        
        print(f"✓ 微调数据导出完成：{output_path}")


if __name__ == "__main__":
    # 初始化训练器
    trainer = SkillTrainer(business_code="ear_test")
    
    # 生成训练数据
    trainer.generate_all_train_data()
    
    # 验证训练数据
    trainer.validate_train_data()
    
    # 导出微调数据
    trainer.export_for_finetuning()
