"""认证与用户相关 Pydantic 模型。"""
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=32, description="登录用户名，唯一")
    nickname: str = Field(min_length=1, max_length=32, description="显示昵称")
    pin: str = Field(min_length=4, max_length=6, description="4-6位数字PIN")
    device_id: str | None = Field(default=None, max_length=64, description="设备标识（可选）")


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    pin: str = Field(min_length=4, max_length=6)


class AuthResponse(BaseModel):
    user_id: int
    username: str
    nickname: str
    role: str
    token: str


class MeResponse(BaseModel):
    user_id: int
    username: str
    nickname: str
    role: str
    db_key: str
    device_id: str | None
    created_at: str
    last_login_at: str | None


class UserOut(BaseModel):
    """管理台用户列表用。"""
    id: int
    username: str
    nickname: str
    role: str
    db_key: str
    device_id: str | None
    is_active: bool
    created_at: str
    last_login_at: str | None


class UserCreate(BaseModel):
    """管理台创建用户。"""
    username: str = Field(min_length=2, max_length=32)
    nickname: str = Field(min_length=1, max_length=32)
    pin: str = Field(min_length=4, max_length=6)
    role: str = Field(default="user", description="admin / user")
    device_id: str | None = None


class UserUpdate(BaseModel):
    """管理台修改用户。"""
    nickname: str | None = Field(default=None, max_length=32)
    role: str | None = None
    is_active: bool | None = None


class ResetPinRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=6)
