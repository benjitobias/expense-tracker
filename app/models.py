from datetime import date as date_type
from typing import Literal

from pydantic import BaseModel, Field

# Categories every account starts with. Users can add more of their own
# (stored in the custom_categories table) via POST /api/categories.
CATEGORIES = [
    "Food",
    "Transport",
    "Shopping",
    "Entertainment",
    "Health",
    "Housing",
    "Utilities",
    "Other",
]


class ExpenseIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    description: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=40)
    location: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)
    date: date_type


class PhotoOut(BaseModel):
    id: int


class ExpenseOut(ExpenseIn):
    id: int
    created_at: str
    photos: list[PhotoOut] = []


class BudgetIn(BaseModel):
    monthly_limit: float = Field(ge=0, le=1_000_000)


class BudgetOut(BudgetIn):
    category: str


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


class ThemeIn(BaseModel):
    theme: Literal["light", "dark", "system"]


class FeedbackIn(BaseModel):
    kind: Literal["bug", "feature"]
    text: str = Field(min_length=1, max_length=1000)


class FeedbackStatusIn(BaseModel):
    status: Literal["open", "done"]


class FeedbackOut(BaseModel):
    id: int
    kind: Literal["bug", "feature"]
    text: str
    status: Literal["open", "done"]
    created_at: str
    username: str | None = None
