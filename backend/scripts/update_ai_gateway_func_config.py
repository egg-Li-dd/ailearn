file_path = r'C:\creategame\AI学\backend\app\services\ai_gateway.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 添加导入：user_db_manager, UserSetting, call_logger
old_import = '''from ..core.db import SessionLocal
from ..core.user_context import get_current_user_key'''
new_import = '''from ..core.db import SessionLocal, user_db_manager
from ..core.user_context import get_current_user_key
from . import call_logger'''
content = content.replace(old_import, new_import)

# 2. 在 chat_stream 中，user_key 读取后，添加功能配置读取
old_user_key = '''    # 未显式传入 user_key 时，从 contextvar 读取当前登录用户
    if user_key is None:
        user_key = get_current_user_key()

    # 调用记录相关状态'''
new_user_key = '''    # 未显式传入 user_key 时，从 contextvar 读取当前登录用户
    if user_key is None:
        user_key = get_current_user_key()

    # 读取功能级配置（ai.func.{function_type}.*），覆盖默认通道/模型/温度
    func_channel_id: int | None = None
    func_model: str | None = None
    func_temperature: float | None = None
    func_type = call_logger.get_function_type()
    if func_type and func_type != "other" and user_key:
        try:
            user_db = user_db_manager.get_session(user_key)
            from ..models import UserSetting
            from sqlalchemy import select
            rows = user_db.execute(
                select(UserSetting.key, UserSetting.value).where(
                    UserSetting.key.like(f"ai.func.{func_type}.%")
                )
            ).all()
            for k, v in rows:
                field = k[len(f"ai.func.{func_type}."):]
                if field == "channel_id" and v:
                    func_channel_id = int(v)
                elif field == "model" and v:
                    func_model = v
                elif field == "temperature" and v:
                    func_temperature = float(v)
            user_db.close()
        except Exception as e:
            logger.debug("读取功能配置失败 func=%s: %s", func_type, e)

    # 功能配置覆盖默认值
    if func_model and model is None:
        model = func_model
    if func_temperature and temperature is None:
        temperature = func_temperature

    # 调用记录相关状态'''
content = content.replace(old_user_key, new_user_key)

# 3. 修改 _get_channel_config_with_exclusion 调用，传入 preferred_channel_id
# 先看看当前的调用方式
old_call = '''            try:
                cfg, channel_id = _get_channel_config_with_exclusion(
                    db, model=model, exclude_ids=tried_channel_ids, user_key=user_key
                )'''
new_call = '''            try:
                cfg, channel_id = _get_channel_config_with_exclusion(
                    db, model=model, exclude_ids=tried_channel_ids, user_key=user_key,
                    preferred_channel_id=func_channel_id,
                )'''
content = content.replace(old_call, new_call)

# 4. 修改 _get_channel_config_with_exclusion 函数签名，添加 preferred_channel_id
old_sig = '''def _get_channel_config_with_exclusion(
    db: Session,
    *,
    model: str | None = None,
    exclude_ids: set[int],
    user_key: str | None = None,
) -> tuple[dict, int | None]:'''
new_sig = '''def _get_channel_config_with_exclusion(
    db: Session,
    *,
    model: str | None = None,
    exclude_ids: set[int],
    user_key: str | None = None,
    preferred_channel_id: int | None = None,
) -> tuple[dict, int | None]:'''
content = content.replace(old_sig, new_sig)

# 5. 在 _get_channel_config_with_exclusion 中，优先使用 preferred_channel_id
old_body = '''    channel = channel_service.select_channel(db, model=model, user_key=user_key)
    if channel and channel.api_key:'''
new_body = '''    # 优先使用功能配置指定的通道
    channel = None
    if preferred_channel_id is not None and preferred_channel_id not in exclude_ids:
        channel = channel_service.get_channel(db, preferred_channel_id)
        if channel and (not channel.enabled or not channel.api_key):
            channel = None
    if channel is None:
        channel = channel_service.select_channel(db, model=model, user_key=user_key, exclude_ids=exclude_ids)
    if channel and channel.api_key:'''
content = content.replace(old_body, new_body)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('✓ ai_gateway.py 已添加功能级通道配置支持')
print('  - 读取 ai.func.{function_type}.channel_id/model/temperature')
print('  - 优先使用功能配置指定的通道')
print('  - 功能配置的 model/temperature 覆盖默认值')
