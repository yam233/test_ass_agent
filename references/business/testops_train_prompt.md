# 业务专属训练 Prompt（AI 测试助手）

## 业务场景强化训练

### 场景 1：专属礼物发放（execute_gift_issue）

#### 正例示例 1：用户专属礼物
**用户输入**：给用户 9075336 发放专属礼物 20001，有效期 7 天

**期望输出**：
```json
{
  "skill_name": "execute_gift_issue",
  "skill_type": "execute",
  "params": {
    "gift_id": 20001,
    "target_id": 9075336,
    "duration_days": 7
  },
  "confidence": 0.99,
  "reason": "识别到发放用户专属礼物意图，礼物 ID 以 2 开头"
}
```

#### 正例示例 2：直播间专属礼物
**用户输入**：给直播间 123456 发放专属礼物 70001

**期望输出**：
```json
{
  "skill_name": "execute_gift_issue",
  "skill_type": "execute",
  "params": {
    "gift_id": 70001,
    "target_id": 123456,
    "issue_type": "room"
  },
  "confidence": 0.99,
  "reason": "识别到发放直播间专属礼物意图，礼物 ID 以 7 开头"
}
```

#### 正例示例 3：随机礼物
**用户输入**：给用户 9075336 发放随机礼物 80001

**期望输出**：
```json
{
  "skill_name": "execute_gift_issue",
  "skill_type": "execute",
  "params": {
    "gift_id": 80001,
    "target_id": 9075336,
    "issue_type": "random"
  },
  "confidence": 0.99,
  "reason": "识别到发放随机礼物意图，礼物 ID 以 8 开头"
}
```

#### 正例示例 4：批量发放
**用户输入**：批量发放 10 个礼物 20001 给用户 9075336，永久有效

**期望输出**：
```json
{
  "skill_name": "execute_gift_issue",
  "skill_type": "execute",
  "params": {
    "gift_id": 20001,
    "target_id": 9075336,
    "batch_count": 10,
    "duration_days": 1000
  },
  "confidence": 0.95,
  "reason": "识别到批量发放意图，永久有效映射为 1000 天"
}
```

#### 负例示例
**用户输入**：查询礼物 20001 的发放记录

**期望输出**：
```json
{
  "skill_name": "query_gift_records",
  "skill_type": "query",
  "params": {
    "element_id": 20001
  },
  "confidence": 0.95,
  "reason": "识别到查询记录意图，不是发放礼物"
}
```

---

### 场景 2：背包礼物发放（add_backpack_gift）

#### 正例示例 1：基础发放
**用户输入**：给用户 9075336 发放背包礼物 30001，数量 5 个

**期望输出**：
```json
{
  "skill_name": "add_backpack_gift",
  "skill_type": "execute",
  "params": {
    "gift_id": 30001,
    "user_id": 9075336,
    "num": 5
  },
  "confidence": 0.99,
  "reason": "识别到发放背包礼物意图，礼物 ID 以 3 开头"
}
```

#### 正例示例 2：指定有效期
**用户输入**：发放背包礼物 40001 给用户 9075336，有效期一个月

**期望输出**：
```json
{
  "skill_name": "add_backpack_gift",
  "skill_type": "execute",
  "params": {
    "gift_id": 40001,
    "user_id": 9075336,
    "duration_days": 30
  },
  "confidence": 0.95,
  "reason": "识别到发放背包礼物意图，一个月映射为 30 天"
}
```

---

### 场景 3：钻石发放（top_up_diamond）

#### 正例示例 1：通过用户 ID
**用户输入**：给用户 9075336 发放 1 个单位的钻石

**期望输出**：
```json
{
  "skill_name": "top_up_diamond",
  "skill_type": "execute",
  "params": {
    "user_id": 9075336,
    "diamond_100w_units": 1
  },
  "confidence": 0.99,
  "reason": "识别到发放钻石意图，1 个单位 = 100 万钻石"
}
```

#### 正例示例 2：通过手机号
**用户输入**：给手机号 13800138000 充值 2 个单位钻石

**期望输出**：
```json
{
  "skill_name": "top_up_diamond",
  "skill_type": "execute",
  "params": {
    "phone": "13800138000",
    "diamond_100w_units": 2
  },
  "confidence": 0.99,
  "reason": "识别到充值钻石意图，通过手机号充值"
}
```

---

### 场景 4：用户信息查询（query_user_info）

#### 正例示例 1：通过用户 ID
**用户输入**：查询用户 9075336 的信息

**期望输出**：
```json
{
  "skill_name": "query_user_info",
  "skill_type": "query",
  "params": {
    "user_id": 9075336
  },
  "confidence": 0.98,
  "reason": "识别到查询用户信息意图"
}
```

#### 正例示例 2：通过手机号
**用户输入**：查询手机号 13800138000 的用户信息

**期望输出**：
```json
{
  "skill_name": "query_user_info",
  "skill_type": "query",
  "params": {
    "phone": "13800138000"
  },
  "confidence": 0.98,
  "reason": "识别到通过手机号查询用户信息"
}
```

#### 正例示例 3：通过直播间 ID
**用户输入**：查询直播间 123456 的用户信息

**期望输出**：
```json
{
  "skill_name": "query_user_info",
  "skill_type": "query",
  "params": {
    "room_id": 123456
  },
  "confidence": 0.95,
  "reason": "识别到通过直播间 ID 查询用户信息"
}
```

---

### 场景 5：验证码获取（get_verify_code）

#### 正例示例 1：通过手机号
**用户输入**：获取手机号 13800138000 的验证码

**期望输出**：
```json
{
  "skill_name": "get_verify_code",
  "skill_type": "query",
  "params": {
    "phone": "13800138000"
  },
  "confidence": 0.99,
  "reason": "识别到获取验证码意图"
}
```

#### 正例示例 2：通过用户 ID
**用户输入**：查询用户 9075336 的验证码

**期望输出**：
```json
{
  "skill_name": "get_verify_code",
  "skill_type": "query",
  "params": {
    "user_id": 9075336
  },
  "confidence": 0.95,
  "reason": "识别到通过用户 ID 获取验证码"
}
```

---

### 场景 6：礼物类型查询（check_gift_type）

#### 正例示例
**用户输入**：查询礼物 20001 的类型

**期望输出**：
```json
{
  "skill_name": "check_gift_type",
  "skill_type": "query",
  "params": {
    "gift_id": 20001
  },
  "confidence": 0.99,
  "reason": "识别到查询礼物类型意图"
}
```

---

### 场景 7：外观配置查询（check_appearance_config）

#### 正例示例
**用户输入**：查询外观 40667 的配置

**期望输出**：
```json
{
  "skill_name": "check_appearance_config",
  "skill_type": "query",
  "params": {
    "appearance_id": 40667
  },
  "confidence": 0.99,
  "reason": "识别到查询外观配置意图"
}
```

---

### 场景 8：奖池配置查询（query_pool_config）

#### 正例示例
**用户输入**：查询礼物 80001 的奖池配置

**期望输出**：
```json
{
  "skill_name": "query_pool_config",
  "skill_type": "query",
  "params": {
    "gift_id": 80001
  },
  "confidence": 0.99,
  "reason": "识别到查询奖池配置意图"
}
```

---

### 场景 9：奖池权重修改（update_pool_gift_weight_to_max）

#### 正例示例
**用户输入**：将奖池 20 的礼物 91384 权重改为最大

**期望输出**：
```json
{
  "skill_name": "update_pool_gift_weight_to_max",
  "skill_type": "execute",
  "params": {
    "pool_id": 20,
    "gift_id": 91384
  },
  "confidence": 0.99,
  "reason": "识别到修改奖池礼物权重为最大的意图"
}
```

---

### 场景 10：后台功能 URL 查询（query_feature_url）

#### 正例示例
**用户输入**：查询外观配置的后台 URL

**期望输出**：
```json
{
  "skill_name": "query_feature_url",
  "skill_type": "query",
  "params": {
    "keyword": "外观配置"
  },
  "confidence": 0.95,
  "reason": "识别到查询后台 URL 意图"
}
```

---

## 训练强化规则

### 1. 执行类操作
- 必须提取 operator 参数（默认 test01）
- 必须提取 env 参数（默认 uat）
- 生产环境（env=prod）禁止执行类操作

### 2. 查询类操作
- 优先提取精准参数（如礼物 ID > 礼物名称）
- 支持模糊查询（如礼物名称）

### 3. 批量操作
- 必须提取 batch_count 参数
- 默认值为 1
- 最大值为 100

### 4. 有效期处理
- "永久"、"永久有效" → 1000
- "一周" → 7
- "一个月" → 30

### 5. 礼物类型自动识别
- 2 开头 → 用户专属（issue_type=user）
- 7 开头 → 直播间专属（issue_type=room）
- 8 开头 → 随机礼物（issue_type=random）
- 3/4 开头 → 背包礼物

---

## 常见错误纠正

### 错误 1：混淆查询和发放
❌ **错误**：将"查询礼物发放记录"识别为"发放礼物"
✅ **正确**：识别为 query_gift_records

### 错误 2：参数格式错误
❌ **错误**：礼物 ID 提取为 "GIFT-001"
✅ **正确**：礼物 ID 提取为 20001（纯数字）

### 错误 3：缺少必填参数
❌ **错误**：发放礼物时缺少 target_id
✅ **正确**：必须提取 target_id（用户 ID 或直播间 ID）

### 错误 4：有效期映射错误
❌ **错误**："永久有效"映射为 0
✅ **正确**："永久有效"映射为 1000

---

## 测试用例

### 测试用例 1
**输入**：批量发放 5 个礼物 20001 给用户 9075336，有效期 7 天
**预期 Skill**：execute_gift_issue
**预期参数**：gift_id=20001, target_id=9075336, batch_count=5, duration_days=7

### 测试用例 2
**输入**：查询用户 9075336 的信息
**预期 Skill**：query_user_info
**预期参数**：user_id=9075336

### 测试用例 3
**输入**：给用户 9075336 发放背包礼物 30001，数量 10 个
**预期 Skill**：add_backpack_gift
**预期参数**：gift_id=30001, user_id=9075336, num=10

### 测试用例 4
**输入**：给手机号 13800138000 充值 2 个单位钻石
**预期 Skill**：top_up_diamond
**预期参数**：phone="13800138000", diamond_100w_units=2

### 测试用例 5
**输入**：查询礼物 20001 的类型
**预期 Skill**：check_gift_type
**预期参数**：gift_id=20001
