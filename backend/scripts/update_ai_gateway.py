file_path = r'C:\creategame\AI学\backend\app\services\ai_gateway.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. _get_channel_config 添加 user_key 参数
old_get_config = '''def _get_channel_config(db: Session, *, model: str | None = None) -> tuple[dict, int | None]:
    """获取调用配置：优先多渠道，回退旧单渠道。

    Returns:
        (config_dict, channel_id_or_None)
        config_dict 含 base_url, api_key, model, temperature
    """
    channel = channel_service.select_channel(db, model=model)'''
new_get_config = '''def _get_channel_config(db: Session, *, model: str | None = None, user_key: str | None = None) -> tuple[dict, int | None]:
    """获取调用配置：优先多渠道，回退旧单渠道。

    Args:
        user_key: 用户标识，优先使用用户私有通道，降级到全局通道

    Returns:
        (config_dict, channel_id_or_None)
        config_dict 含 base_url, api_key, model, temperature
    """
    channel = channel_service.select_channel(db, model=model, user_key=user_key)'''
content = content.replace(old_get_config, new_get_config)

# 2. _get_channel_config_with_exclusion 添加 user_key 参数
old_exclusion = '''def _get_channel_config_with_exclusion(
    db: Session, *, model: str | None = None, exclude_ids: set[int] | None = None
) -> tuple[dict, int | None]:
    """选择渠道时排除指定 ID（故障转移用）。"""
    from ..models import AiChannel
    from sqlalchemy import select

    if not exclude_ids:
        return _get_channel_config(db, model=model)

    # 手动选择：排除指定渠道 + 排除 status=error 的渠道
    channels = channel_service.list_channels(db, only_enabled=True)'''
new_exclusion = '''def _get_channel_config_with_exclusion(
    db: Session, *, model: str | None = None, exclude_ids: set[int] | None = None, user_key: str | None = None
) -> tuple[dict, int | None]:
    """选择渠道时排除指定 ID（故障转移用）。"""
    from ..models import AiChannel
    from sqlalchemy import select

    if not exclude_ids:
        return _get_channel_config(db, model=model, user_key=user_key)

    # 手动选择：排除指定渠道 + 排除 status=error 的渠道
    # 用户隔离：优先用户私有通道 + 全局通道
    channels = channel_service.list_channels(db, only_enabled=True, user_key=user_key, scope="all")'''
content = content.replace(old_exclusion, new_exclusion)

# 3. chat_stream 添加 user_key 参数
old_chat_stream_sig = '''async def chat_stream(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
    usage_collector: list | None = None,
    info_collector: dict | None = None,
    tool_calls_collector: list | None = None,
    db: Session | None = None,
):'''
new_chat_stream_sig = '''async def chat_stream(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
    usage_collector: list | None = None,
    info_collector: dict | None = None,
    tool_calls_collector: list | None = None,
    db: Session | None = None,
    user_key: str | None = None,
):'''
content = content.replace(old_chat_stream_sig, new_chat_stream_sig)

# 4. chat_stream 中调用 _get_channel_config_with_exclusion 时传入 user_key
old_call = '''                cfg, channel_id = _get_channel_config_with_exclusion(
                    db, model=model, exclude_ids=tried_channel_ids
                )'''
new_call = '''                cfg, channel_id = _get_channel_config_with_exclusion(
                    db, model=model, exclude_ids=tried_channel_ids, user_key=user_key
                )'''
content = content.replace(old_call, new_call)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('ai_gateway.py 修改完成')
print('  ✓ _get_channel_config 添加 user_key 参数')
print('  ✓ _get_channel_config_with_exclusion 添加 user_key 参数')
print('  ✓ chat_stream 添加 user_key 参数')
print('  ✓ chat_stream 调用时传入 user_key')
