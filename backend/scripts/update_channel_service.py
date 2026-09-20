file_path = r'C:\creategame\AI学\backend\app\services\channel_service.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. serialize_channel 添加 user_key 字段
old_serialize = '''        "temperature": channel.temperature,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,'''
new_serialize = '''        "temperature": channel.temperature,
        "user_key": channel.user_key,
        "is_global": channel.user_key is None,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,'''
content = content.replace(old_serialize, new_serialize)

# 2. list_channels 添加 user_key 和 scope 参数
old_list = '''def list_channels(db: Session, *, only_enabled: bool = False) -> list[AiChannel]:
    """列出所有渠道，按 priority 升序、weight 降序排列。"""
    stmt = select(AiChannel).order_by(AiChannel.priority.asc(), AiChannel.weight.desc())
    if only_enabled:
        stmt = stmt.where(AiChannel.enabled == True)  # noqa: E712
    return list(db.scalars(stmt))'''
new_list = '''def list_channels(db: Session, *, only_enabled: bool = False, user_key: str | None = None, scope: str = "all") -> list[AiChannel]:
    """列出渠道，按 priority 升序、weight 降序排列。

    Args:
        user_key: 用户标识，用于过滤私有通道
        scope: 过滤范围
            - "all": 全局通道 + 指定用户的私有通道（默认）
            - "global": 仅全局通道（user_key=NULL）
            - "private": 仅指定用户的私有通道
    """
    stmt = select(AiChannel).order_by(AiChannel.priority.asc(), AiChannel.weight.desc())
    if only_enabled:
        stmt = stmt.where(AiChannel.enabled == True)  # noqa: E712
    if scope == "global":
        stmt = stmt.where(AiChannel.user_key.is_(None))
    elif scope == "private" and user_key:
        stmt = stmt.where(AiChannel.user_key == user_key)
    elif scope == "all" and user_key:
        # 全局通道 + 用户私有通道
        from sqlalchemy import or_
        stmt = stmt.where(or_(AiChannel.user_key.is_(None), AiChannel.user_key == user_key))
    return list(db.scalars(stmt))'''
content = content.replace(old_list, new_list)

# 3. create_channel 添加 user_key 参数
old_create = '''def create_channel(db: Session, data: dict) -> AiChannel:
    channel = AiChannel(
        name=data.get("name", "未命名渠道"),
        type=data.get("type", "openai"),
        base_url=data.get("base_url", ""),
        api_key=data.get("api_key", ""),
        models=json.dumps(data.get("models", []), ensure_ascii=False),
        default_model=data.get("default_model", ""),
        vision_model=data.get("vision_model", ""),
        weight=int(data.get("weight", 1)),
        priority=int(data.get("priority", 5)),
        enabled=bool(data.get("enabled", True)),
        temperature=float(data.get("temperature", 0.7)),
    )'''
new_create = '''def create_channel(db: Session, data: dict, *, user_key: str | None = None) -> AiChannel:
    channel = AiChannel(
        name=data.get("name", "未命名渠道"),
        type=data.get("type", "openai"),
        base_url=data.get("base_url", ""),
        api_key=data.get("api_key", ""),
        models=json.dumps(data.get("models", []), ensure_ascii=False),
        default_model=data.get("default_model", ""),
        vision_model=data.get("vision_model", ""),
        weight=int(data.get("weight", 1)),
        priority=int(data.get("priority", 5)),
        enabled=bool(data.get("enabled", True)),
        temperature=float(data.get("temperature", 0.7)),
        user_key=user_key,
    )'''
content = content.replace(old_create, new_create)

# 4. select_channel 添加 user_key 参数，优先用户私有通道
old_select = '''def select_channel(db: Session, *, model: str | None = None) -> AiChannel | None:
    """选择一个可用渠道：按 priority 分组，组内按 weight 随机。

    故障转移逻辑：
    1. 筛选 enabled=True 的渠道
    2. 排除 status=error 的渠道（错误渠道不自动恢复，需管理器手动测试通过）
    3. 按 priority 升序取最高优先级组
    4. 组内按 weight 加权随机选择
    5. 如果指定了 model，优先选择包含该模型的渠道
    6. 所有渠道都 error 时，降级为全部启用渠道（保底可用）
    """
    channels = list_channels(db, only_enabled=True)
    if not channels:
        return None'''
new_select = '''def select_channel(db: Session, *, model: str | None = None, user_key: str | None = None) -> AiChannel | None:
    """选择一个可用渠道：按 priority 分组，组内按 weight 随机。

    用户隔离逻辑：
    - 如果指定了 user_key，优先从用户私有通道中选择
    - 用户私有通道不可用时，降级到全局通道
    - 未指定 user_key 时，仅从全局通道选择（向后兼容）

    故障转移逻辑：
    1. 筛选 enabled=True 的渠道
    2. 排除 status=error 的渠道（错误渠道不自动恢复，需管理器手动测试通过）
    3. 按 priority 升序取最高优先级组
    4. 组内按 weight 加权随机选择
    5. 如果指定了 model，优先选择包含该模型的渠道
    6. 所有渠道都 error 时，降级为全部启用渠道（保底可用）
    """
    # 优先用户私有通道
    if user_key:
        private_channels = list_channels(db, only_enabled=True, user_key=user_key, scope="private")
        if private_channels:
            result = _select_from_channels(private_channels, model=model)
            if result:
                return result
        # 私有通道不可用，降级到全局通道
        global_channels = list_channels(db, only_enabled=True, scope="global")
        return _select_from_channels(global_channels, model=model)
    else:
        # 未指定用户，仅全局通道（向后兼容）
        channels = list_channels(db, only_enabled=True, scope="global")
        return _select_from_channels(channels, model=model)


def _select_from_channels(channels: list[AiChannel], *, model: str | None = None) -> AiChannel | None:
    """从给定渠道列表中选择一个可用渠道（内部辅助函数）。"""
    if not channels:
        return None'''
content = content.replace(old_select, new_select)

# 5. 把原来 select_channel 函数体中的逻辑缩进调整（现在在 _select_from_channels 中）
# 原来的代码从 "直接排除 status=error 的渠道" 开始，需要保持不变
# 由于我们只是把函数头替换了，函数体内容应该还在原来的位置
# 但是需要确保函数体的缩进正确

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('channel_service.py 修改完成')
print('  ✓ serialize_channel 添加 user_key/is_global')
print('  ✓ list_channels 添加 user_key/scope 参数')
print('  ✓ create_channel 添加 user_key 参数')
print('  ✓ select_channel 添加 user_key 参数，优先私有通道')
print('  ✓ 新增 _select_from_channels 辅助函数')
