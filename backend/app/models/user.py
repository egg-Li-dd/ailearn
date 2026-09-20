"""用户与设置。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 登录用户名（同设备多用户的关键标识）
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # 显示昵称
    nickname: Mapped[str] = mapped_column(String(32), default="")
    # 角色：admin / user
    role: Mapped[str] = mapped_column(String(16), default="user")
    # 用户库文件名标识（如 eggli / dangdang），物理分库的路由键
    db_key: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # 设备标识（不再 unique，同设备可注册多用户）
    device_id: Mapped[str | None] = mapped_column(String(64), index=True)
    pin_hash: Mapped[str] = mapped_column(String(128))
    token_hash: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class UserSetting(Base):
    __tablename__ = "user_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
