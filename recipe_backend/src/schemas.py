"""Pydantic schemas for API requests and responses."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RecipeNutrition(BaseModel):
    """Nutrition information for a recipe."""

    calories: int = Field(..., description="Calories per serving.")
    protein: str = Field(..., description="Protein amount display string.")
    carbs: str = Field(..., description="Carbohydrate amount display string.")
    fat: str = Field(..., description="Fat amount display string.")


class RecipeSummary(BaseModel):
    """Compact recipe response used in lists."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Recipe identifier.")
    title: str = Field(..., description="Recipe title.")
    slug: str = Field(..., description="URL-friendly recipe slug.")
    description: str = Field(..., description="Short description of the recipe.")
    image: str = Field(..., description="Primary recipe image URL.")
    category: str = Field(..., description="Primary category label.")
    tags: list[str] = Field(..., description="Recipe tag labels.")
    cookTimeMinutes: int = Field(..., description="Cooking time in minutes.")
    prepTimeMinutes: int = Field(..., description="Preparation time in minutes.")
    servings: int = Field(..., description="Number of servings.")
    difficulty: Literal["Easy", "Medium", "Hard"] = Field(..., description="Recipe difficulty level.")
    rating: float = Field(..., description="Average rating.")
    favoriteCount: int = Field(..., description="Number of users who favorited the recipe.")
    isFavorite: bool = Field(..., description="Whether the current user has favorited the recipe.")
    authorName: str = Field(..., description="Display name of the recipe author.")
    moderationStatus: Literal["approved", "pending", "flagged"] = Field(
        ..., description="Moderation status for the recipe."
    )


class RecipeDetail(RecipeSummary):
    """Full recipe response used in recipe detail views."""

    ingredients: list[str] = Field(..., description="Ingredient display lines.")
    steps: list[str] = Field(..., description="Ordered cooking steps.")
    nutrition: RecipeNutrition = Field(..., description="Nutrition summary.")
    notes: str = Field(..., description="Author notes or additional recipe notes.")


class RecipeCreate(BaseModel):
    """Request payload for creating a recipe."""

    title: str = Field(..., min_length=2, max_length=200, description="Recipe title.")
    description: str = Field(..., min_length=3, description="Recipe description.")
    image: str = Field(default="", description="Primary image URL.")
    category: str = Field(..., description="Category label.")
    tags: list[str] = Field(default_factory=list, description="Tag labels.")
    cookTimeMinutes: int = Field(default=0, ge=0, description="Cooking time in minutes.")
    prepTimeMinutes: int = Field(default=0, ge=0, description="Prep time in minutes.")
    servings: int = Field(default=1, ge=1, description="Number of servings.")
    difficulty: Literal["Easy", "Medium", "Hard"] = Field(default="Easy", description="Difficulty level.")
    ingredients: list[str] = Field(default_factory=list, description="Ingredient list.")
    steps: list[str] = Field(default_factory=list, description="Ordered instruction steps.")
    notes: str = Field(default="", description="Optional recipe notes.")
    nutrition: RecipeNutrition = Field(..., description="Nutrition summary.")
    moderationStatus: Literal["approved", "pending", "flagged"] = Field(
        default="pending", description="Initial moderation state."
    )


class RecipeUpdate(BaseModel):
    """Request payload for updating a recipe."""

    title: str | None = Field(default=None, min_length=2, max_length=200, description="Recipe title.")
    description: str | None = Field(default=None, min_length=3, description="Recipe description.")
    image: str | None = Field(default=None, description="Primary image URL.")
    category: str | None = Field(default=None, description="Category label.")
    tags: list[str] | None = Field(default=None, description="Tag labels.")
    cookTimeMinutes: int | None = Field(default=None, ge=0, description="Cooking time in minutes.")
    prepTimeMinutes: int | None = Field(default=None, ge=0, description="Preparation time in minutes.")
    servings: int | None = Field(default=None, ge=1, description="Number of servings.")
    difficulty: Literal["Easy", "Medium", "Hard"] | None = Field(default=None, description="Difficulty level.")
    ingredients: list[str] | None = Field(default=None, description="Ingredient list.")
    steps: list[str] | None = Field(default=None, description="Instruction steps.")
    notes: str | None = Field(default=None, description="Optional notes.")
    nutrition: RecipeNutrition | None = Field(default=None, description="Nutrition summary.")
    moderationStatus: Literal["approved", "pending", "flagged"] | None = Field(
        default=None, description="Moderation state."
    )


class CategorySummary(BaseModel):
    """Category list item."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Category identifier.")
    label: str = Field(..., description="Display label.")
    count: int = Field(..., description="Number of matching recipes.")


class FavoriteRecipe(BaseModel):
    """Favorite recipe response item."""

    id: str = Field(..., description="Favorite identifier.")
    recipeId: str = Field(..., description="Favorited recipe identifier.")
    recipeTitle: str = Field(..., description="Recipe title.")
    category: str = Field(..., description="Recipe category label.")


class ShoppingListItemResponse(BaseModel):
    """Shopping list item response."""

    id: str = Field(..., description="Shopping list item identifier.")
    label: str = Field(..., description="Display label.")
    quantity: str = Field(..., description="Quantity display string.")
    checked: bool = Field(..., description="Whether the item is completed.")
    recipeTitle: str = Field(..., description="Recipe title source or manual marker.")


class ShoppingListItemCreate(BaseModel):
    """Request payload for manually adding a shopping list item."""

    label: str = Field(..., min_length=1, max_length=200, description="Item label.")
    quantity: str = Field(default="", description="Quantity display string.")
    recipeId: str | None = Field(default=None, description="Optional source recipe identifier.")


class ShoppingListGenerateRequest(BaseModel):
    """Request payload for generating a shopping list from recipes."""

    recipeIds: list[str] = Field(..., min_length=1, description="Recipe identifiers to aggregate.")


class UserProfile(BaseModel):
    """Current user profile response."""

    id: str = Field(..., description="User identifier.")
    name: str = Field(..., description="Full display name.")
    email: EmailStr = Field(..., description="User email address.")
    role: Literal["member", "admin"] = Field(..., description="Frontend-supported role.")
    bio: str = Field(..., description="Profile biography.")
    avatarLabel: str = Field(..., description="Short avatar label or emoji.")


class UserProfileUpdate(BaseModel):
    """Request payload for updating the current user's profile."""

    name: str | None = Field(default=None, min_length=1, max_length=120, description="Full name.")
    bio: str | None = Field(default=None, description="Profile biography.")
    avatarLabel: str | None = Field(default=None, max_length=20, description="Avatar label or emoji.")


class ModerationQueueItem(BaseModel):
    """Moderation queue item response."""

    id: str = Field(..., description="Moderation queue item identifier.")
    title: str = Field(..., description="Recipe title.")
    submittedBy: str = Field(..., description="Recipe submitter display name.")
    reason: str = Field(..., description="Reason for moderation.")
    status: Literal["pending", "approved", "rejected"] = Field(..., description="Queue item status.")


class ModerationActionRequest(BaseModel):
    """Request payload for approving or rejecting a recipe moderation entry."""

    status: Literal["approved", "rejected"] = Field(..., description="Final moderation decision.")
    reason: str = Field(default="", description="Optional moderator note.")


class AuthRegisterRequest(BaseModel):
    """Request payload for registering a new user."""

    email: EmailStr = Field(..., description="Account email.")
    username: str = Field(..., min_length=3, max_length=50, description="Unique username.")
    password: str = Field(..., min_length=8, description="Plaintext password.")
    name: str = Field(..., min_length=1, max_length=120, description="Display name.")


class AuthLoginRequest(BaseModel):
    """Request payload for user login."""

    email: EmailStr = Field(..., description="Account email.")
    password: str = Field(..., min_length=8, description="Plaintext password.")


class AuthResponse(BaseModel):
    """Authentication response carrying the bearer token and user profile."""

    accessToken: str = Field(..., description="JWT access token.")
    tokenType: str = Field(default="bearer", description="Token type.")
    profile: UserProfile = Field(..., description="Authenticated user profile.")


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str = Field(..., description="Human-readable status message.")
