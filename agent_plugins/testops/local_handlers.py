"""
testops 业务本地工具处理器注册表
"""
from typing import Dict, Any, Callable
from agent_core.skills.standard import BackendMetadataSkill, TestScriptSkill


def build_local_handlers() -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
    from business_logic.user.user_service import query_user_info
    from business_logic.user.verify_code_service import query_verify_code
    from business_logic.user.test_tool_diamond_service import top_up_diamond_via_test_tool
    from business_logic.gift.gift_service import (
        add_to_backpack,
        add_to_exclusive_tab,
        query_gift_records,
        check_gift_type,
        list_gift_types,
    )
    from business_logic.pool import (
        query_gifts_by_name,
        query_pool_config,
        update_pool_gift_weight_to_max,
        update_pool_ssr_weight_to_zero,
    )
    from business_logic.common import query_gift_info
    from business_logic.config_check.appearance_service import query_appearance_config, query_appearance_configs_batch
    from business_logic.config_check.reward_service import query_reward_config, query_reward_configs_batch
    from business_logic.appearance.appearance_manage_service import (
        issue_appearance_to_platform,
        validate_appearance_params,
        get_appearance_type_from_id
    )
    from business_logic.gift.backpack_gift_service import (
        issue_backpack_gift_via_grafana,
        validate_backpack_gift_params,
        is_backpack_gift,
        get_gift_type_name,
        clear_backpack_gift_via_grafana,
        validate_clear_gift_params,
        is_free_gift
    )
    from business_logic.common.backend_url_loader import BackendUrlLoader
    from business_logic.common.universal_query_executor import UniversalQueryExecutor

    def _search_features(p: Dict[str, Any]) -> Dict[str, Any]:
        keyword = (p.get("keyword", "") or "").strip()
        ambiguous_keywords = {"url", "地址", "链接", "网址", "后台地址", "查询url", "查询地址"}
        if (not keyword) or (keyword.lower() in ambiguous_keywords) or (keyword in ambiguous_keywords):
            return {
                "success": False,
                "data": {
                    "need_refine": True,
                    "examples": [
                        "查询外观配置grafana地址",
                        "查询随机礼物mongo地址",
                        "查询奖池配置URL"
                    ]
                },
                "message": "❌ 指令不够明确，请补充要查询的业务对象（如外观/礼物/奖池）和数据源（grafana/mongo）。"
            }

        entries = BackendUrlLoader.list_all_urls()
        metadata_skill = BackendMetadataSkill(entries)
        metadata_result = metadata_skill.search(keyword)
        results = metadata_result.get("data", {}).get("features", [])[:p.get("limit", 3)]
        return {
            "success": True,
            "data": {"features": results, "total": len(results)},
            "message": f"✅ 找到 {len(results)} 个最相关的后台功能"
        }

    def _list_features(_: Dict[str, Any]) -> Dict[str, Any]:
        results = BackendUrlLoader.list_all_urls()
        metadata_skill = BackendMetadataSkill(results)
        metadata_result = metadata_skill.search("")
        features = metadata_result.get("data", {}).get("features", results)
        return {
            "success": True,
            "data": {"features": features, "total": len(features)},
            "message": f"✅ 共 {len(features)} 个后台功能"
        }

    def _get_enums(p: Dict[str, Any]) -> Dict[str, Any]:
        enum_name = (p.get("enum_name") or "appearance_type").strip()
        
        # 从appearance_service导入标准的外观类型定义
        from business_logic.config_check.appearance_service import APPEARANCE_TYPES
        
        enum_map = {
            "appearance_type": [
                {"value": k, "label": v} for k, v in sorted(APPEARANCE_TYPES.items())
            ]
        }
        
        values = enum_map.get(enum_name, [])
        if not values:
            return {
                "success": False,
                "data": {},
                "message": f"❌ 不支持的枚举: {enum_name}"
            }
        
        # 格式化友好的消息
        if enum_name == "appearance_type":
            message_lines = ["✅ 外观类型清单\n"]
            for item in values:
                message_lines.append(f"• {item['value']} - {item['label']}")
            message_lines.append(f"\n📊 共 {len(values)} 种外观类型")
            message = "\n".join(message_lines)
        else:
            message = f"✅ 枚举 {enum_name} 共 {len(values)} 项"
        
        return {
            "success": True,
            "data": {},  # 不返回原始数据，避免重复显示
            "message": message
        }
    
    def _top_up_diamond(p: Dict[str, Any]) -> Dict[str, Any]:
        """钻石充值参数转换和验证"""
        params = p.copy()
        
        # 将 diamond_100w_units 转换为 total_diamond_wan
        if "diamond_100w_units" in params and params["diamond_100w_units"] is not None:
            params["total_diamond_wan"] = params.pop("diamond_100w_units") * 100
        
        # 移除内部参数
        params.pop("_user_input", None)
        
        # 调用底层服务，让它做完整的参数验证
        return top_up_diamond_via_test_tool(**params)

    def _query_appearance_configs_batch(p: Dict[str, Any]) -> Dict[str, Any]:
        """批量查询外观配置，处理字符串到列表的转换"""
        params = p.copy()
        
        # 转换 appearance_ids 字符串为列表
        if 'appearance_ids' in params and isinstance(params['appearance_ids'], str):
            params['appearance_ids'] = [int(x.strip()) for x in params['appearance_ids'].split(',') if x.strip()]
        
        results = query_appearance_configs_batch(**params)
        
        # 统计成功和失败数量
        success_count = sum(1 for r in results if r.get('success'))
        fail_count = len(results) - success_count
        
        # 构建友好的消息
        message_lines = []
        if fail_count == 0:
            message_lines.append(f"✅ 批量查询成功！\n")
        else:
            message_lines.append(f"⚠️ 批量查询完成：成功 {success_count} 个，失败 {fail_count} 个\n")
        
        # 添加每个查询结果的详细信息
        for result in results:
            if result.get('success'):
                msg = result.get('message', '')
                if msg:
                    message_lines.append(msg.strip())
            else:
                appearance_id = result.get('data', {}).get('appearance_id', '未知') if result.get('data') else '未知'
                error = result.get('message', '查询失败')
                message_lines.append(f"❌ 外观ID {appearance_id}: {error}")
        
        friendly_message = "\n\n".join(message_lines)
        
        return {
            "success": True,
            "message": friendly_message,
            "data": {"success_count": success_count, "fail_count": fail_count, "total_count": len(results)}
        }
    
    def _query_reward_configs_batch(p: Dict[str, Any]) -> Dict[str, Any]:
        """批量查询奖励配置，处理字符串到列表的转换"""
        params = p.copy()
        
        # 转换 reward_ids 字符串为列表
        if 'reward_ids' in params and isinstance(params['reward_ids'], str):
            params['reward_ids'] = [int(x.strip()) for x in params['reward_ids'].split(',') if x.strip()]
        
        # 转换 element_ids 字符串为列表
        if 'element_ids' in params and isinstance(params['element_ids'], str):
            params['element_ids'] = [int(x.strip()) for x in params['element_ids'].split(',') if x.strip()]
        
        # 提取 event_id（如果有）
        event_id = params.get('event_id')
        
        results = query_reward_configs_batch(**params)
        
        # 统计成功和失败数量
        success_count = sum(1 for r in results if r.get('success'))
        fail_count = len(results) - success_count
        
        # 构建友好的消息
        message_lines = []
        if fail_count == 0:
            title = f"✅ 批量查询成功！"
            if event_id:
                title = f"✅ 活动 {event_id} - 批量查询成功！"
            message_lines.append(title + "\n")
        else:
            title = f"⚠️ 批量查询完成：成功 {success_count} 个，失败 {fail_count} 个"
            if event_id:
                title = f"⚠️ 活动 {event_id} - 批量查询完成：成功 {success_count} 个，失败 {fail_count} 个"
            message_lines.append(title + "\n")
        
        # 添加每个查询结果的详细信息
        for result in results:
            if result.get('success'):
                msg = result.get('message', '')
                if msg:
                    message_lines.append(msg.strip())
            else:
                # 尝试从 data 中提取 ID
                data = result.get('data')
                if isinstance(data, dict):
                    element_id = data.get('element_id') or data.get('reward_id', '未知')
                else:
                    element_id = '未知'
                error = result.get('message', '查询失败')
                message_lines.append(f"❌ ID {element_id}: {error}")
        
        friendly_message = "\n\n".join(message_lines)
        
        return {
            "success": True,
            "message": friendly_message,
            "data": {"success_count": success_count, "fail_count": fail_count, "total_count": len(results), "event_id": event_id}
        }
    
    def _universal_query(p: Dict[str, Any]) -> Dict[str, Any]:
        executor = UniversalQueryExecutor("testops")
        handlers = build_local_handlers()
        safe_handlers = {k: v for k, v in handlers.items() if k != "universal_query"}
        return executor.execute(p, safe_handlers)

    def _build_test_script_skill(p: Dict[str, Any]) -> TestScriptSkill:
        from agent_core.layers import LocalConfigLayer
        local_config = LocalConfigLayer()
        gitlab_cfg = local_config.get_gitlab_config()
        repo_path = (
            p.get("repo_path")
            or gitlab_cfg.get("repo_path")
            or gitlab_cfg.get("local_repo_path")
            or "."
        )
        branch = p.get("branch") or gitlab_cfg.get("branch")
        return TestScriptSkill(repo_path=repo_path, branch=branch)

    def _scan_test_scripts(p: Dict[str, Any]) -> Dict[str, Any]:
        skill = _build_test_script_skill(p)
        sync = p.get("sync_latest", False)
        if sync:
            sync_result = skill.sync_latest()
            if not sync_result.get("success"):
                return sync_result
        return skill.scan_scripts()

    def _read_test_script(p: Dict[str, Any]) -> Dict[str, Any]:
        relative_path = p.get("relative_path") or p.get("script_path") or p.get("path")
        if not relative_path:
            return {"success": False, "message": "❌ 缺少脚本路径 relative_path"}
        return _build_test_script_skill(p).read_script(relative_path)

    def _execute_test_script(p: Dict[str, Any]) -> Dict[str, Any]:
        relative_path = p.get("relative_path") or p.get("script_path") or p.get("path")
        if not relative_path:
            return {"success": False, "message": "❌ 缺少脚本路径 relative_path"}
        args = p.get("args") or []
        if isinstance(args, str):
            args = [item for item in args.split(" ") if item]
        approved = bool(p.get("approved") or p.get("execute_confirmed"))
        return _build_test_script_skill(p).execute_script(
            relative_path=relative_path,
            args=args,
            approved=approved
        )

    def _issue_appearance_to_platform(p: Dict[str, Any]) -> Dict[str, Any]:
        """发放外观到外观中心平台"""
        params = p.copy()
        
        # 处理批量用户ID
        if 'user_ids' in params and isinstance(params['user_ids'], str):
            # 字符串转列表
            user_ids_str = params['user_ids']
            user_ids = [int(x.strip()) for x in user_ids_str.split(',') if x.strip()]
            params['user_ids'] = user_ids
        elif 'user_id' in params and params['user_id']:
            # 单个用户ID转列表
            params['user_ids'] = [params['user_id']]
        
        # 移除单个user_id参数，避免冲突
        params.pop('user_id', None)
        
        # 参数验证
        user_ids = params.get('user_ids', [])
        appearance_id = params.get('appearance_id')
        duration_days = params.get('duration_days', 7)
        
        # 验证必填参数
        if not user_ids:
            return {
                "success": False,
                "message": "❌ 缺少用户ID\n\n💡 示例：给用户9075566发放外观70244，有效期7天",
                "data": None
            }
        
        if not appearance_id:
            return {
                "success": False,
                "message": "❌ 缺少外观ID\n\n💡 示例：给用户9075566发放外观70244，有效期7天",
                "data": None
            }
        
        # 参数验证
        validation_error = validate_appearance_params(user_ids, appearance_id, duration_days)
        if validation_error:
            return {
                "success": False,
                "message": f"❌ 参数验证失败：{validation_error}",
                "data": None
            }
        
        # 自动判断外观类型
        appearance_type = params.get('appearance_type')
        if not appearance_type:
            appearance_type = get_appearance_type_from_id(appearance_id)
        
        # 调用发放服务
        return issue_appearance_to_platform(
            user_ids=user_ids,
            appearance_id=appearance_id,
            duration_days=duration_days,
            appearance_type=appearance_type
        )

    def _issue_backpack_gift_via_grafana(p: Dict[str, Any]) -> Dict[str, Any]:
        """通过 Grafana 后台发放背包礼物"""
        params = p.copy()
        
        # 处理批量用户ID
        if 'user_ids' in params and isinstance(params['user_ids'], str):
            # 字符串转列表
            user_ids_str = params['user_ids']
            user_ids = [int(x.strip()) for x in user_ids_str.split(',') if x.strip()]
            params['user_ids'] = user_ids
        elif 'user_id' in params and params['user_id']:
            # 单个用户ID转列表
            params['user_ids'] = [params['user_id']]
        
        # 移除单个user_id参数，避免冲突
        params.pop('user_id', None)
        
        # 参数验证
        user_ids = params.get('user_ids', [])
        gift_id = params.get('gift_id')
        num = params.get('num', 1)
        duration_days = params.get('duration_days', 7)
        
        # 验证必填参数
        if not user_ids:
            return {
                "success": False,
                "message": "❌ 缺少用户ID\n\n💡 示例：给用户9075566发放背包礼物301，数量10",
                "data": None
            }
        
        if not gift_id:
            return {
                "success": False,
                "message": "❌ 缺少礼物ID\n\n💡 示例：给用户9075566发放背包礼物301，数量10",
                "data": None
            }

        # 统一分流兜底：即使命中 Grafana skill，3/4开头都改走 DB 插入
        if str(gift_id).startswith("3") or str(gift_id).startswith("4"):
            if not user_ids:
                return {
                    "success": False,
                    "message": "❌ 缺少用户ID\n\n💡 示例：给用户9075566发礼物401到背包",
                    "data": None
                }

            results = []
            success_count = 0
            fail_count = 0
            for uid in user_ids:
                r = add_to_backpack(
                    gift_id=gift_id,
                    user_id=uid,
                    num=num,
                    duration_days=duration_days
                )
                results.append({"user_id": uid, "result": r})
                if r.get("success"):
                    success_count += 1
                else:
                    fail_count += 1

            if fail_count == 0:
                duration_text = "永久（1000天）" if duration_days == 1000 else f"{duration_days}天"
                user_preview = "、".join(str(uid) for uid in user_ids[:5])
                if len(user_ids) > 5:
                    user_preview += "..."
                return {
                    "success": True,
                    "message": (
                        "✅ 背包礼物发放成功\n"
                        f"用户：{user_preview}\n"
                        f"礼物ID：{gift_id}\n"
                        f"数量：{num}\n"
                        f"有效期：{duration_text}\n"
                        f"结果：成功 {success_count} / 总计 {len(user_ids)}"
                    ),
                    "data": {
                        "success_count": success_count,
                        "fail_count": fail_count,
                        "total": len(user_ids),
                        "route": "db",
                        "gift_id": gift_id,
                        "num": num,
                        "duration_days": duration_days,
                        "user_ids": user_ids,
                    }
                }

            duration_text = "永久（1000天）" if duration_days == 1000 else f"{duration_days}天"
            return {
                "success": False,
                "message": (
                    "⚠️ 背包礼物发放部分成功\n"
                    f"礼物ID：{gift_id}\n"
                    f"数量：{num}\n"
                    f"有效期：{duration_text}\n"
                    f"结果：成功 {success_count}，失败 {fail_count}"
                ),
                "data": {
                    "success_count": success_count,
                    "fail_count": fail_count,
                    "total": len(user_ids),
                    "route": "db",
                    "gift_id": gift_id,
                    "num": num,
                    "duration_days": duration_days,
                    "results": results
                }
            }
        
        # 验证礼物类型（必须是背包礼物）
        if not is_backpack_gift(gift_id):
            gift_type_name = get_gift_type_name(gift_id)
            return {
                "success": False,
                "message": f"❌ 礼物ID {gift_id} 是{gift_type_name}，不支持通过此接口发放\n\n💡 通过 Grafana 发放背包礼物仅支持免费礼物（3开头）",
                "data": None
            }
        
        # 参数验证
        validation_error = validate_backpack_gift_params(user_ids, gift_id, num, duration_days)
        if validation_error:
            return {
                "success": False,
                "message": f"❌ 参数验证失败：{validation_error}",
                "data": None
            }
        
        # 调用发放服务
        return issue_backpack_gift_via_grafana(
            user_ids=user_ids,
            gift_id=gift_id,
            num=num,
            duration_days=duration_days
        )

    def _add_gift_to_backpack_unified(p: Dict[str, Any]) -> Dict[str, Any]:
        """
        统一入口：发礼物到背包
        - 3开头免费礼物：走 MongoDB 插入
        - 4开头白给礼物：走 MongoDB 插入
        """
        params = p.copy()
        gift_id = params.get("gift_id")
        if not gift_id:
            return {
                "success": False,
                "message": "❌ 缺少礼物ID\n\n💡 示例：给用户9075566发礼物301到背包",
                "data": None
            }

        gift_prefix = str(gift_id)[0]
        if gift_prefix == "3" or gift_prefix == "4":
            result = add_to_backpack(**params)
            if result.get("success") and not (result.get("message") or "").strip():
                user_id = params.get("user_id")
                num = params.get("num", 1)
                duration_days = params.get("duration_days", 7)
                duration_text = "永久（1000天）" if duration_days == 1000 else f"{duration_days}天"
                gift_label = "免费礼物" if gift_prefix == "3" else "白给礼物"
                result["message"] = (
                    f"✅ 背包礼物发放成功（{gift_label}，DB插入）\n"
                    f"用户：{user_id}\n"
                    f"礼物ID：{gift_id}\n"
                    f"数量：{num}\n"
                    f"有效期：{duration_text}"
                )
                if not result.get("data"):
                    result["data"] = {
                        "route": "db",
                        "user_id": user_id,
                        "gift_id": gift_id,
                        "num": num,
                        "duration_days": duration_days,
                    }
            return result

        return {
            "success": False,
            "message": f"❌ 礼物ID {gift_id} 不支持发放到背包\n\n💡 仅支持免费礼物（3开头）或白给礼物（4开头）",
            "data": None
        }

    def _clear_backpack_gift_via_grafana(p: Dict[str, Any]) -> Dict[str, Any]:
        """通过 Grafana 后台清空背包礼物"""
        params = p.copy()
        
        # 处理批量用户ID
        if 'user_ids' in params and isinstance(params['user_ids'], str):
            # 字符串转列表
            user_ids_str = params['user_ids']
            user_ids = [int(x.strip()) for x in user_ids_str.split(',') if x.strip()]
            params['user_ids'] = user_ids
        elif 'user_id' in params and params['user_id']:
            # 单个用户ID转列表
            params['user_ids'] = [params['user_id']]
        
        # 移除单个user_id参数，避免冲突
        params.pop('user_id', None)
        
        # 参数验证
        user_ids = params.get('user_ids', [])
        gift_id = params.get('gift_id')
        
        # 验证必填参数
        if not user_ids:
            return {
                "success": False,
                "message": "❌ 缺少用户ID\n\n💡 示例：清空用户9075566的背包礼物301",
                "data": None
            }
        
        if not gift_id:
            return {
                "success": False,
                "message": "❌ 缺少礼物ID\n\n💡 示例：清空用户9075566的背包礼物301",
                "data": None
            }
        
        # 验证礼物类型（必须是免费礼物）
        if not is_free_gift(gift_id):
            gift_type_name = get_gift_type_name(gift_id)
            return {
                "success": False,
                "message": f"❌ 礼物ID {gift_id} 是{gift_type_name}，不支持清空操作\n\n💡 只有免费礼物（3开头）支持清空背包功能",
                "data": None
            }
        
        # 参数验证
        validation_error = validate_clear_gift_params(user_ids, gift_id)
        if validation_error:
            return {
                "success": False,
                "message": f"❌ 参数验证失败：{validation_error}",
                "data": None
            }
        
        # 调用清空服务
        return clear_backpack_gift_via_grafana(
            user_ids=user_ids,
            gift_id=gift_id
        )

    return {
        "query_user_info": lambda p: query_user_info(**p),
        "get_verify_code": lambda p: query_verify_code(**p),
        "top_up_diamond": _top_up_diamond,
        "add_gift_to_backpack": _add_gift_to_backpack_unified,
        "add_gift_to_exclusive_tab": lambda p: add_to_exclusive_tab(**p),
        "query_gift_records": lambda p: query_gift_records(**p),
        "check_gift_type": lambda p: check_gift_type(**p),
        "list_gift_types": lambda p: list_gift_types(),
        "query_gifts_by_name": lambda p: query_gifts_by_name(**p),
        "query_gift_info": lambda p: query_gift_info(**p),
        "query_pool_config": lambda p: query_pool_config(**p),
        "update_pool_gift_weight_to_max": lambda p: update_pool_gift_weight_to_max(**p),
        "update_pool_ssr_weight_to_zero": lambda p: update_pool_ssr_weight_to_zero(**p),
        "query_appearance_config": lambda p: query_appearance_config(**p),
        "query_appearance_configs_batch": _query_appearance_configs_batch,
        "query_reward_config": lambda p: query_reward_config(**p),
        "query_reward_configs_batch": _query_reward_configs_batch,
        "search_features": _search_features,
        "list_features": _list_features,
        "get_enums": _get_enums,
        "issue_appearance_to_platform": _issue_appearance_to_platform,
        "issue_backpack_gift_via_grafana": _issue_backpack_gift_via_grafana,
        "clear_backpack_gift_via_grafana": _clear_backpack_gift_via_grafana,
        "universal_query": _universal_query,
        "scan_test_scripts": _scan_test_scripts,
        "read_test_script": _read_test_script,
        "execute_test_script": _execute_test_script,
    }
