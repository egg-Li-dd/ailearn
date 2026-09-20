file_path = r'C:\creategame\AI学\backend\app\routers\ai.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. ChannelCreate 添加 user_key 字段
old_create_schema = '''class ChannelCreate(BaseModel):
    name: str = Field(default="未命名渠道", max_length=64)
    type: str = Field(default="openai", max_length=32)
    base_url: str = Field(default="", max_length=256)
    api_key: str = Field(default="", max_length=512)
    models: list[str] = Field(default_factory=list)
    default_model: str = Field(default="", max_length=128)
    vision_model: str = Field(default="", max_length=128)
    weight: int = Field(default=1, ge=1, le=100)
    priority: int = Field(default=5, ge=1, le=10)
    enabled: bool = Field(default=True)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)'''
new_create_schema = '''class ChannelCreate(BaseModel):
    name: str = Field(default="未命名渠道", max_length=64)
    type: str = Field(default="openai", max_length=32)
    base_url: str = Field(default="", max_length=256)
    api_key: str = Field(default="", max_length=512)
    models: list[str] = Field(default_factory=list)
    default_model: str = Field(default="", max_length=128)
    vision_model: str = Field(default="", max_length=128)
    weight: int = Field(default=1, ge=1, le=100)
    priority: int = Field(default=5, ge=1, le=10)
    enabled: bool = Field(default=True)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    user_key: str | None = Field(default=None, max_length=32, description="NULL=全局通道，非NULL=用户私有通道")'''
content = content.replace(old_create_schema, new_create_schema)

# 2. GET /channels 添加 scope 和 user_key 参数
old_list_api = '''@router.get("/channels")
def list_channels(db: Session = Depends(get_db)):
    """列出所有渠道（不含 api_key 明文）。"""
    channels = channel_service.list_channels(db)
    return {
        "channels": [channel_service.serialize_channel(ch) for ch in channels],
        "types": channel_service.CHANNEL_TYPES,
    }'''
new_list_api = '''@router.get("/channels")
def list_channels(
    db: Session = Depends(get_db),
    scope: str = Query(default="all", pattern="^(all|global|private)$"),
    user_key: str | None = Query(default=None),
):
    """列出渠道（不含 api_key 明文）。

    Args:
        scope: all=全局+用户私有, global=仅全局, private=仅指定用户私有
        user_key: 用户标识，scope=private 或 all 时生效
    """
    channels = channel_service.list_channels(db, user_key=user_key, scope=scope)
    return {
        "channels": [channel_service.serialize_channel(ch) for ch in channels],
        "types": channel_service.CHANNEL_TYPES,
    }'''
content = content.replace(old_list_api, new_list_api)

# 3. POST /channels 创建时传入 user_key
old_create_api = '''@router.post("/channels")
def create_channel(payload: ChannelCreate, db: Session = Depends(get_db)):
    """创建新渠道。"""
    data = payload.model_dump()
    channel = channel_service.create_channel(db, data)
    return channel_service.serialize_channel(channel)'''
new_create_api = '''@router.post("/channels")
def create_channel(payload: ChannelCreate, db: Session = Depends(get_db)):
    """创建新渠道。user_key=NULL 创建全局通道，非NULL创建用户私有通道。"""
    data = payload.model_dump()
    user_key = data.pop("user_key", None)
    channel = channel_service.create_channel(db, data, user_key=user_key)
    return channel_service.serialize_channel(channel)'''
content = content.replace(old_create_api, new_create_api)

# 4. 确保导入了 Query
if 'from fastapi import' in content:
    # 检查是否已导入 Query
    if 'Query' not in content.split('from fastapi import')[1].split('\n')[0]:
        content = content.replace(
            'from fastapi import ',
            'from fastapi import Query, '
        )
        print('  ✓ 已添加 Query 导入')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('ai.py 修改完成')
print('  ✓ ChannelCreate 添加 user_key 字段')
print('  ✓ GET /channels 添加 scope/user_key 参数')
print('  ✓ POST /channels 传入 user_key')
