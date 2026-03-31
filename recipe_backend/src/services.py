"""Domain services for Recipe Hub."""

from __future__ import annotations

import json
import re
from typing import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from src.core.config import get_settings
from src.core.security import hash_password
from src.models import (
    Category,
    Favorite,
    ModerationReport,
    Recipe,
    RecipeTag,
    ShoppingList,
    ShoppingListItem,
    Tag,
    User,
)
from src.schemas import (
    CategorySummary,
    FavoriteRecipe,
    ModerationQueueItem,
    RecipeCreate,
    RecipeDetail,
    RecipeNutrition,
    RecipeSummary,
    ShoppingListItemResponse,
    UserProfile,
)

settings = get_settings()


def slugify(value: str) -> str:
    """Create a URL-safe slug from the provided text."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return normalized.strip("-") or "recipe"


def ensure_category(db: Session, label: str) -> Category:
    """Find or create a category by label."""
    slug = slugify(label)
    category = db.scalar(select(Category).where(or_(Category.slug == slug, Category.label == label)))
    if category:
        return category

    category = Category(label=label, slug=slug)
    db.add(category)
    db.flush()
    return category


def ensure_tags(db: Session, labels: Iterable[str]) -> list[Tag]:
    """Find or create tags by label."""
    tags: list[Tag] = []
    for label in labels:
        clean_label = label.strip()
        if not clean_label:
            continue
        slug = slugify(clean_label)
        tag = db.scalar(select(Tag).where(or_(Tag.slug == slug, Tag.label == clean_label)))
        if not tag:
            tag = Tag(label=clean_label, slug=slug)
            db.add(tag)
            db.flush()
        tags.append(tag)
    return tags


def get_or_create_default_shopping_list(db: Session, user: User) -> ShoppingList:
    """Return the user's default shopping list."""
    shopping_list = db.scalar(select(ShoppingList).where(ShoppingList.user_id == user.id))
    if shopping_list:
        return shopping_list

    shopping_list = ShoppingList(user_id=user.id, name="My Shopping List")
    db.add(shopping_list)
    db.flush()
    return shopping_list


def to_profile(user: User) -> UserProfile:
    """Convert a user model into the frontend profile shape."""
    return UserProfile(
        id=user.id,
        name=user.full_name,
        email=user.email,
        role="admin" if user.role == "admin" else "member",
        bio=user.bio,
        avatarLabel=user.avatar_label,
    )


def _difficulty_value(value: str) -> str:
    """Normalize stored difficulty values to frontend enum casing."""
    normalized = (value or "Easy").capitalize()
    return normalized if normalized in {"Easy", "Medium", "Hard"} else "Easy"


def _moderation_value(value: str) -> str:
    """Normalize moderation status to the frontend-supported values."""
    lowered = (value or "pending").lower()
    if lowered in {"approved", "pending", "flagged"}:
        return lowered
    if lowered in {"rejected", "pending_review"}:
        return "pending"
    return "pending"


def to_recipe_summary(recipe: Recipe, current_user_id: str | None = None) -> RecipeSummary:
    """Convert a recipe model into the frontend recipe summary shape."""
    tag_labels = [link.tag.label for link in recipe.tag_links]
    favorite_user_ids = {favorite.user_id for favorite in recipe.favorites}
    return RecipeSummary(
        id=recipe.id,
        title=recipe.title,
        slug=recipe.slug,
        description=recipe.description,
        image=recipe.image,
        category=recipe.category.label if recipe.category else "Uncategorized",
        tags=tag_labels,
        cookTimeMinutes=recipe.cook_time_minutes,
        prepTimeMinutes=recipe.prep_time_minutes,
        servings=recipe.servings,
        difficulty=_difficulty_value(recipe.difficulty),
        rating=round(recipe.rating, 1),
        favoriteCount=len(recipe.favorites),
        isFavorite=current_user_id in favorite_user_ids if current_user_id else False,
        authorName=recipe.author.full_name,
        moderationStatus=_moderation_value(recipe.moderation_status),
    )


def to_recipe_detail(recipe: Recipe, current_user_id: str | None = None) -> RecipeDetail:
    """Convert a recipe model into the frontend recipe detail shape."""
    summary = to_recipe_summary(recipe, current_user_id=current_user_id)
    ingredients = json.loads(recipe.ingredients_blob or "[]")
    steps = json.loads(recipe.steps_blob or "[]")
    return RecipeDetail(
        **summary.model_dump(),
        ingredients=ingredients,
        steps=steps,
        nutrition=RecipeNutrition(
            calories=recipe.calories,
            protein=recipe.protein,
            carbs=recipe.carbs,
            fat=recipe.fat,
        ),
        notes=recipe.notes,
    )


def to_favorite_response(favorite: Favorite) -> FavoriteRecipe:
    """Convert a favorite model into the frontend favorite response shape."""
    return FavoriteRecipe(
        id=favorite.id,
        recipeId=favorite.recipe.id,
        recipeTitle=favorite.recipe.title,
        category=favorite.recipe.category.label if favorite.recipe.category else "Uncategorized",
    )


def to_shopping_item_response(item: ShoppingListItem) -> ShoppingListItemResponse:
    """Convert a shopping list item into the frontend response shape."""
    return ShoppingListItemResponse(
        id=item.id,
        label=item.label,
        quantity=item.quantity,
        checked=item.checked,
        recipeTitle=item.recipe.title if item.recipe else "Manual item",
    )


def to_moderation_queue_item(report: ModerationReport) -> ModerationQueueItem:
    """Convert a moderation report into the frontend moderation queue shape."""
    return ModerationQueueItem(
        id=report.id,
        title=report.recipe.title,
        submittedBy=report.submitted_by_name,
        reason=report.reason,
        status=report.status if report.status in {"pending", "approved", "rejected"} else "pending",
    )


def list_categories_with_counts(db: Session) -> list[CategorySummary]:
    """Return category counts for frontend sidebar usage."""
    rows = db.execute(
        select(Category, func.count(Recipe.id))
        .outerjoin(Recipe, Recipe.category_id == Category.id)
        .group_by(Category.id)
        .order_by(Category.label.asc())
    ).all()
    return [
        CategorySummary(id=category.id, label=category.label, count=count)
        for category, count in rows
    ]


def attach_recipe_tags(db: Session, recipe: Recipe, tag_labels: list[str]) -> None:
    """Replace the tag links for a recipe."""
    recipe.tag_links.clear()
    db.flush()
    for tag in ensure_tags(db, tag_labels):
        db.add(RecipeTag(recipe_id=recipe.id, tag_id=tag.id))


def create_recipe_from_payload(db: Session, payload: RecipeCreate, author: User) -> Recipe:
    """Create a recipe and its tag relationships from an API payload."""
    category = ensure_category(db, payload.category)
    base_slug = slugify(payload.title)
    slug = base_slug
    suffix = 1
    while db.scalar(select(Recipe).where(Recipe.slug == slug)):
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    recipe = Recipe(
        title=payload.title,
        slug=slug,
        description=payload.description,
        image=payload.image,
        prep_time_minutes=payload.prepTimeMinutes,
        cook_time_minutes=payload.cookTimeMinutes,
        servings=payload.servings,
        difficulty=payload.difficulty,
        rating=0.0,
        moderation_status=payload.moderationStatus,
        notes=payload.notes,
        ingredients_blob=json.dumps(payload.ingredients),
        steps_blob=json.dumps(payload.steps),
        calories=payload.nutrition.calories,
        protein=payload.nutrition.protein,
        carbs=payload.nutrition.carbs,
        fat=payload.nutrition.fat,
        author_id=author.id,
        category_id=category.id,
    )
    db.add(recipe)
    db.flush()
    attach_recipe_tags(db, recipe, payload.tags)
    return recipe


def seed_database(db: Session) -> None:
    """Seed the database with enough data for the frontend and auth flows."""
    existing_user = db.scalar(select(User).limit(1))
    if existing_user:
        return

    admin = User(
        email=settings.default_admin_email,
        username="adminchef",
        password_hash=hash_password(settings.default_admin_password),
        full_name="Recipe Hub Admin",
        bio="Platform administrator and content reviewer.",
        role="admin",
        avatar_label="👩‍🍳",
    )
    mia = User(
        email="mia@recipehub.dev",
        username="mia",
        password_hash=hash_password("Password123!"),
        full_name="Mia Summers",
        bio="Home cook sharing bright weekday recipes.",
        role="member",
        avatar_label="🥣",
    )
    leo = User(
        email="leo@recipehub.dev",
        username="leo",
        password_hash=hash_password("Password123!"),
        full_name="Leo Carter",
        bio="Weekend meal prep enthusiast.",
        role="member",
        avatar_label="🍝",
    )
    db.add_all([admin, mia, leo])
    db.flush()

    breakfast = ensure_category(db, "Breakfast")
    dinner = ensure_category(db, "Dinner")
    meal_prep = ensure_category(db, "Meal Prep")
    vegetarian = ensure_category(db, "Vegetarian")

    recipe_one = Recipe(
        title="Citrus Sunrise Oats",
        slug="citrus-sunrise-oats",
        description="Creamy overnight oats with orange zest, yogurt, and berries.",
        image="https://images.unsplash.com/photo-1517673400267-0251440c45dc",
        prep_time_minutes=10,
        cook_time_minutes=0,
        servings=2,
        difficulty="Easy",
        rating=4.8,
        moderation_status="approved",
        notes="Best chilled overnight for the brightest citrus flavor.",
        ingredients_blob=json.dumps(
            [
                "1 cup rolled oats",
                "3/4 cup Greek yogurt",
                "3/4 cup milk",
                "1 tbsp orange zest",
                "1 tbsp honey",
                "1/2 cup mixed berries",
            ]
        ),
        steps_blob=json.dumps(
            [
                "Whisk oats, yogurt, milk, orange zest, and honey in a jar.",
                "Cover and chill overnight or at least 4 hours.",
                "Top with berries before serving.",
            ]
        ),
        calories=320,
        protein="18g",
        carbs="42g",
        fat="9g",
        author_id=mia.id,
        category_id=breakfast.id,
    )
    recipe_two = Recipe(
        title="Weeknight Tomato Basil Pasta",
        slug="weeknight-tomato-basil-pasta",
        description="A pantry-friendly pasta with rich tomato sauce, basil, and parmesan.",
        image="https://images.unsplash.com/photo-1621996346565-e3dbc646d9a9",
        prep_time_minutes=15,
        cook_time_minutes=20,
        servings=4,
        difficulty="Easy",
        rating=4.6,
        moderation_status="approved",
        notes="Finish with extra basil and parmesan just before serving.",
        ingredients_blob=json.dumps(
            [
                "12 oz pasta",
                "2 tbsp olive oil",
                "3 garlic cloves, minced",
                "28 oz crushed tomatoes",
                "1/2 cup fresh basil",
                "1/2 cup parmesan",
            ]
        ),
        steps_blob=json.dumps(
            [
                "Cook pasta in salted water until al dente.",
                "Saute garlic in olive oil until fragrant.",
                "Add tomatoes and simmer until slightly thickened.",
                "Toss pasta with sauce, basil, and parmesan.",
            ]
        ),
        calories=480,
        protein="16g",
        carbs="62g",
        fat="17g",
        author_id=leo.id,
        category_id=dinner.id,
    )
    recipe_three = Recipe(
        title="Hidden Veggie Mac Bake",
        slug="hidden-veggie-mac-bake",
        description="Comforting baked pasta packed with blended vegetables for picky eaters.",
        image="https://images.unsplash.com/photo-1543339494-b4cd4f7ba686",
        prep_time_minutes=25,
        cook_time_minutes=30,
        servings=6,
        difficulty="Medium",
        rating=4.2,
        moderation_status="pending",
        notes="Pending moderator review due to incomplete bake temperature notes.",
        ingredients_blob=json.dumps(
            [
                "16 oz elbow macaroni",
                "2 cups cauliflower florets",
                "1 carrot, chopped",
                "2 cups milk",
                "2 cups cheddar cheese",
                "1/2 cup breadcrumbs",
            ]
        ),
        steps_blob=json.dumps(
            [
                "Cook macaroni just under package directions.",
                "Blend cauliflower, carrot, and milk until smooth.",
                "Stir puree into macaroni with cheddar cheese.",
                "Top with breadcrumbs and bake until golden.",
            ]
        ),
        calories=510,
        protein="22g",
        carbs="49g",
        fat="24g",
        author_id=mia.id,
        category_id=meal_prep.id,
    )
    db.add_all([recipe_one, recipe_two, recipe_three])
    db.flush()

    attach_recipe_tags(db, recipe_one, ["Quick", "Family Friendly"])
    attach_recipe_tags(db, recipe_two, ["Family Friendly", "Retro Favorite"])
    attach_recipe_tags(db, recipe_three, ["High Protein", "Vegetarian"])

    db.add_all(
        [
            Favorite(user_id=leo.id, recipe_id=recipe_one.id),
            Favorite(user_id=leo.id, recipe_id=recipe_two.id),
        ]
    )
    db.flush()

    shopping_list = ShoppingList(user_id=leo.id, name="Weekend Prep List")
    db.add(shopping_list)
    db.flush()
    db.add_all(
        [
            ShoppingListItem(
                shopping_list_id=shopping_list.id,
                recipe_id=recipe_two.id,
                label="Pasta",
                quantity="12 oz",
                checked=False,
                sort_order=1,
            ),
            ShoppingListItem(
                shopping_list_id=shopping_list.id,
                recipe_id=recipe_two.id,
                label="Crushed tomatoes",
                quantity="28 oz",
                checked=False,
                sort_order=2,
            ),
            ShoppingListItem(
                shopping_list_id=shopping_list.id,
                recipe_id=recipe_one.id,
                label="Mixed berries",
                quantity="1/2 cup",
                checked=False,
                sort_order=3,
            ),
        ]
    )

    db.add(
        ModerationReport(
            recipe_id=recipe_three.id,
            submitted_by_name=mia.full_name,
            reason="Need a clearer bake temperature before publication.",
            status="pending",
        )
    )

    # Add one more category for sidebar richness.
    ensure_category(db, "Dessert")
    ensure_category(db, "Vegetarian")
    db.commit()


def recipe_query():
    """Return a standard recipe query with eager loading."""
    return (
        select(Recipe)
        .options(
            selectinload(Recipe.author),
            selectinload(Recipe.category),
            selectinload(Recipe.tag_links).selectinload(RecipeTag.tag),
            selectinload(Recipe.favorites),
        )
    )
