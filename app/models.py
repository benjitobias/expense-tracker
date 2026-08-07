from datetime import date as date_type
from typing import Literal

from pydantic import BaseModel, Field

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

Category = Literal[
    "Food", "Transport", "Shopping", "Entertainment",
    "Health", "Housing", "Utilities", "Other",
]


class ExpenseIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    description: str = Field(min_length=1, max_length=200)
    category: Category
    date: date_type


class ExpenseOut(ExpenseIn):
    id: int
    created_at: str


class BudgetIn(BaseModel):
    monthly_limit: float = Field(ge=0, le=1_000_000)


class BudgetOut(BudgetIn):
    category: str


class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


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
