from datetime import datetime
from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    url: str = Field(..., min_length=10, max_length=1024)
    target_price: float = Field(..., gt=0)


class ProductResponse(BaseModel):
    id: int
    url: str
    store: str
    title: str
    current_price: float
    target_price: float
    history: list[float]


class HistoryPointResponse(BaseModel):
    t: datetime
    price: float
