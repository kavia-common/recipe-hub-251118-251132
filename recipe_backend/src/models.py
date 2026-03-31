"""SQLAlchemy models for the Recipe Hub backend."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


def _uuid() -> str:
    """Generate a string UUID primary key."""
    return str(uuid4())


class TimestampMixin:
    """Reusable timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class User(TimestampMixin, Base):
    """Application user."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    bio: Mapped[str] = mapped_column(Text, default="", nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)
    avatar_label: Mapped[str] = mapped_column(String(20), default="🍳", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    recipes: Mapped[list["Recipe"]] = relationship("Recipe", back_populates="author")
    favorites: Mapped[list["Favorite"]] = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    shopping_lists: Mapped[list["ShoppingList"]] = relationship(
        "ShoppingList", back_populates="user", cascade="all, delete-orphan"
    )


class Category(TimestampMixin, Base):
    """Recipe category."""

    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)

    recipes: Mapped[list["Recipe"]] = relationship("Recipe", back_populates="category")


class Tag(TimestampMixin, Base):
    """Recipe tag."""

    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)

    recipe_links: Mapped[list["RecipeTag"]] = relationship(
        "RecipeTag", back_populates="tag", cascade="all, delete-orphan"
    )


class Recipe(TimestampMixin, Base):
    """Recipe record."""

    __tablename__ = "recipes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    prep_time_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cook_time_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    servings: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), default="Easy", nullable=False)
    rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    moderation_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ingredients_blob: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    steps_blob: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    calories: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    protein: Mapped[str] = mapped_column(String(20), default="0g", nullable=False)
    carbs: Mapped[str] = mapped_column(String(20), default="0g", nullable=False)
    fat: Mapped[str] = mapped_column(String(20), default="0g", nullable=False)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True)

    author: Mapped["User"] = relationship("User", back_populates="recipes")
    category: Mapped["Category | None"] = relationship("Category", back_populates="recipes")
    tag_links: Mapped[list["RecipeTag"]] = relationship(
        "RecipeTag", back_populates="recipe", cascade="all, delete-orphan"
    )
    favorites: Mapped[list["Favorite"]] = relationship(
        "Favorite", back_populates="recipe", cascade="all, delete-orphan"
    )


class RecipeTag(Base):
    """Join table linking recipes to tags."""

    __tablename__ = "recipe_tags"
    __table_args__ = (UniqueConstraint("recipe_id", "tag_id", name="uq_recipe_tag"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), nullable=False)
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id"), nullable=False)

    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="tag_links")
    tag: Mapped["Tag"] = relationship("Tag", back_populates="recipe_links")


class Favorite(TimestampMixin, Base):
    """User favorite mapping."""

    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "recipe_id", name="uq_favorite_user_recipe"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="favorites")
    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="favorites")


class ShoppingList(TimestampMixin, Base):
    """Shopping list belonging to a user."""

    __tablename__ = "shopping_lists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), default="My Shopping List", nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="shopping_lists")
    items: Mapped[list["ShoppingListItem"]] = relationship(
        "ShoppingListItem",
        back_populates="shopping_list",
        cascade="all, delete-orphan",
        order_by="ShoppingListItem.sort_order",
    )


class ShoppingListItem(TimestampMixin, Base):
    """A single shopping list item."""

    __tablename__ = "shopping_list_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    shopping_list_id: Mapped[str] = mapped_column(ForeignKey("shopping_lists.id"), nullable=False)
    recipe_id: Mapped[str | None] = mapped_column(ForeignKey("recipes.id"), nullable=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    checked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    shopping_list: Mapped["ShoppingList"] = relationship("ShoppingList", back_populates="items")
    recipe: Mapped["Recipe | None"] = relationship("Recipe")


class ModerationReport(TimestampMixin, Base):
    """Moderation queue item for submitted or flagged recipes."""

    __tablename__ = "moderation_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), nullable=False)
    submitted_by_name: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    recipe: Mapped["Recipe"] = relationship("Recipe")
