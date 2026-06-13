from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


Platform = Literal["hyperliquid", "polymarket"]
WalletStatus = Literal["active", "disabled", "deleted"]


class WalletBase(BaseModel):
    address: str = Field(min_length=4, max_length=128)
    platform: Platform = "hyperliquid"
    name: str = Field(min_length=1, max_length=120)
    tags: str = ""
    manual_score: int = Field(default=50, ge=1, le=100)
    status: WalletStatus = "active"
    notes: str = ""


class WalletCreate(WalletBase):
    pass


class WalletUpdate(BaseModel):
    address: Optional[str] = Field(default=None, min_length=4, max_length=128)
    platform: Optional[Platform] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    tags: Optional[str] = None
    manual_score: Optional[int] = Field(default=None, ge=1, le=100)
    status: Optional[WalletStatus] = None
    notes: Optional[str] = None


class WalletRead(WalletBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
