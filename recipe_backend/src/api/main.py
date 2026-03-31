"""FastAPI application entrypoint for the Recipe Hub backend."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from src.core.config import get_settings
from src.core.database import get_db, init_db
from src.core.security import create_access_token, decode_access_token, hash_password, verify_password
from src.models import Favorite, ModerationReport, Recipe, ShoppingListItem, User
from src.schemas import (
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthResponse,
    CategorySummary,
    FavoriteRecipe,
    MessageResponse,
    ModerationActionRequest,
    ModerationQueueItem,
    RecipeCreate,
    RecipeDetail,
    RecipeSummary,
    RecipeUpdate,
    ShoppingListGenerateRequest,
    ShoppingListItemCreate,
    ShoppingListItemResponse,
    UserProfile,
    UserProfileUpdate,
)
from src.services import (
    attach_recipe_tags,
    create_recipe_from_payload,
    ensure_category,
    get_or_create_default_shopping_list,
    list_categories_with_counts,
    recipe_query,
    seed_database,
    to_favorite_response,
    to_moderation_queue_item,
    to_profile,
    to_recipe_detail,
    to_recipe_summary,
)

settings = get_settings()

openapi_tags = [
    {"name": "System", "description": "Health and documentation helper endpoints."},
    {"name": "Auth", "description": "User signup and login endpoints."},
    {"name": "Recipes", "description": "Recipe listing, detail, creation, update, and deletion APIs."},
    {"name": "Favorites", "description": "Endpoints for saving and unsaving recipes."},
    {"name": "Shopping List", "description": "Shopping list retrieval, generation, and item management."},
    {"name": "Catalog", "description": "Category and tag discovery endpoints."},
    {"name": "Profile", "description": "Current user profile endpoints."},
    {"name": "Moderation", "description": "Admin moderation queue and moderation action endpoints."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize the database and seed demo content on startup."""
    init_db()
    db = next(get_db())
    try:
        seed_database(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title=settings.app_name,
    description=settings.app_description,
    version=settings.app_version,
    openapi_tags=openapi_tags,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DbSession = Annotated[Session, Depends(get_db)]


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Extract a bearer token from the Authorization header."""
    if not authorization:
        return None
    prefix = "bearer "
    if authorization.lower().startswith(prefix):
        return authorization[len(prefix):].strip()
    return None


def _get_optional_user(
    db: DbSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User | None:
    """Resolve the current user if a valid bearer token is present."""
    token = _extract_bearer_token(authorization)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except Exception:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return db.scalar(select(User).where(User.id == user_id))


def _get_current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User:
    """Require and return the authenticated user."""
    user = _get_optional_user(db, authorization)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return user


def _get_admin_user(current_user: Annotated[User, Depends(_get_current_user)]) -> User:
    """Require an authenticated admin user."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return current_user


def _recipe_lookup_statement() -> select:
    """Build the standard recipe lookup statement with eager loading."""
    return recipe_query().options(selectinload(Recipe.tag_links))


def _get_recipe_or_404(db: DbSession, recipe_id: str) -> Recipe:
    """Load a recipe by id or slug and raise a 404 if not found."""
    recipe = db.scalar(
        recipe_query().where(
            or_(Recipe.id == recipe_id, Recipe.slug == recipe_id)
        )
    )
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found.")
    return recipe


def _build_auth_response(user: User) -> AuthResponse:
    """Create the auth response payload for a user."""
    token = create_access_token(user.id, {"role": user.role, "email": user.email})
    return AuthResponse(accessToken=token, profile=to_profile(user))


# PUBLIC_INTERFACE
@app.get(
    "/",
    response_model=MessageResponse,
    tags=["System"],
    summary="Health check",
    description="Basic health check endpoint for the Recipe Hub API.",
)
def health_check() -> MessageResponse:
    """Return a health status message for infrastructure and preview checks."""
    return MessageResponse(message="Healthy")


# PUBLIC_INTERFACE
@app.get(
    "/docs/help",
    response_model=MessageResponse,
    tags=["System"],
    summary="API usage help",
    description="Provides a concise message about using the REST API and the interactive Swagger docs.",
)
def docs_help() -> MessageResponse:
    """Return a simple usage note for frontend and developer consumers."""
    return MessageResponse(message="Use /docs for Swagger UI and /openapi.json for the API schema.")


# PUBLIC_INTERFACE
@app.post(
    "/auth/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Auth"],
    summary="Register a new user",
    description="Create a new Recipe Hub user account and immediately return a bearer token plus profile.",
    responses={409: {"description": "Email or username already exists."}},
)
def register_user(payload: AuthRegisterRequest, db: DbSession) -> AuthResponse:
    """Register a new user account.

    Args:
        payload: Registration form including email, username, password, and display name.
        db: Active database session.

    Returns:
        The authentication token and normalized frontend profile for the created user.
    """
    existing_user = db.scalar(
        select(User).where(or_(User.email == payload.email, User.username == payload.username))
    )
    if existing_user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email or username already exists.")

    user = User(
        email=payload.email,
        username=payload.username,
        password_hash=hash_password(payload.password),
        full_name=payload.name,
        bio="",
        role="member",
        avatar_label="🍽️",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _build_auth_response(user)


# PUBLIC_INTERFACE
@app.post(
    "/auth/login",
    response_model=AuthResponse,
    tags=["Auth"],
    summary="Log in a user",
    description="Authenticate a user with email and password and return a bearer token and profile.",
    responses={401: {"description": "Invalid credentials."}},
)
def login_user(payload: AuthLoginRequest, db: DbSession) -> AuthResponse:
    """Authenticate a user and return a bearer token.

    Args:
        payload: Login form with email and password.
        db: Active database session.

    Returns:
        The authentication token and normalized frontend profile for the authenticated user.
    """
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
    return _build_auth_response(user)


# PUBLIC_INTERFACE
@app.get(
    "/profile",
    response_model=UserProfile,
    tags=["Profile"],
    summary="Get current profile",
    description="Return the authenticated user's profile in the shape expected by the frontend.",
    responses={401: {"description": "Authentication required."}},
)
def get_profile(current_user: Annotated[User, Depends(_get_current_user)]) -> UserProfile:
    """Return the current authenticated user's profile."""
    return to_profile(current_user)


# PUBLIC_INTERFACE
@app.put(
    "/profile",
    response_model=UserProfile,
    tags=["Profile"],
    summary="Update current profile",
    description="Update editable profile fields for the authenticated user.",
    responses={401: {"description": "Authentication required."}},
)
def update_profile(
    payload: UserProfileUpdate,
    db: DbSession,
    current_user: Annotated[User, Depends(_get_current_user)],
) -> UserProfile:
    """Update the current authenticated user's profile."""
    if payload.name is not None:
        current_user.full_name = payload.name
    if payload.bio is not None:
        current_user.bio = payload.bio
    if payload.avatarLabel is not None:
        current_user.avatar_label = payload.avatarLabel

    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return to_profile(current_user)


# PUBLIC_INTERFACE
@app.get(
    "/recipes",
    response_model=list[RecipeSummary],
    tags=["Recipes"],
    summary="List recipes",
    description=(
        "Return recipe summaries with optional search, category, tag, favorites-only, and moderation-status filters. "
        "The response shape matches the frontend recipe summary contract."
    ),
)
def list_recipes(
    db: DbSession,
    current_user: Annotated[User | None, Depends(_get_optional_user)],
    search: Annotated[str | None, Query(description="Search by title, description, or author name.")] = None,
    category: Annotated[str | None, Query(description="Filter by category label or slug.")] = None,
    tag: Annotated[str | None, Query(description="Filter by tag label or slug.")] = None,
    favoritesOnly: Annotated[bool, Query(description="Return only recipes favorited by the current user.")] = False,
    moderationStatus: Annotated[str | None, Query(description="Filter by moderation status.")] = None,
) -> list[RecipeSummary]:
    """List recipes with search and filter support."""
    statement = recipe_query()

    if search:
        like_term = f"%{search.lower()}%"
        statement = statement.join(Recipe.author).where(
            or_(
                func.lower(Recipe.title).like(like_term),
                func.lower(Recipe.description).like(like_term),
                func.lower(User.full_name).like(like_term),
            )
        )

    if category:
        statement = statement.join(Recipe.category).where(
            or_(
                func.lower(Recipe.category.has().comparator.property.entity.class_.label) == category.lower(),  # noqa: E501
                func.lower(Recipe.category.has().comparator.property.entity.class_.slug) == category.lower(),  # noqa: E501
            )
        )

    if moderationStatus:
        statement = statement.where(func.lower(Recipe.moderation_status) == moderationStatus.lower())

    recipes = list(db.scalars(statement.order_by(Recipe.created_at.desc())).unique().all())

    if tag:
        filtered: list[Recipe] = []
        target = tag.lower()
        for recipe in recipes:
            labels = {link.tag.label.lower() for link in recipe.tag_links}
            slugs = {link.tag.slug.lower() for link in recipe.tag_links}
            if target in labels or target in slugs:
                filtered.append(recipe)
        recipes = filtered

    if favoritesOnly:
        if not current_user:
            return []
        favorite_ids = {favorite.recipe_id for favorite in current_user.favorites}
        recipes = [recipe for recipe in recipes if recipe.id in favorite_ids]

    return [to_recipe_summary(recipe, current_user_id=current_user.id if current_user else None) for recipe in recipes]


# PUBLIC_INTERFACE
@app.get(
    "/recipes/{recipe_id}",
    response_model=RecipeDetail,
    tags=["Recipes"],
    summary="Get a recipe by id or slug",
    description="Return the complete recipe detail payload expected by the frontend recipe detail view.",
    responses={404: {"description": "Recipe not found."}},
)
def get_recipe(
    recipe_id: str,
    db: DbSession,
    current_user: Annotated[User | None, Depends(_get_optional_user)],
) -> RecipeDetail:
    """Return a single recipe detail record."""
    recipe = _get_recipe_or_404(db, recipe_id)
    return to_recipe_detail(recipe, current_user_id=current_user.id if current_user else None)


# PUBLIC_INTERFACE
@app.post(
    "/recipes",
    response_model=RecipeDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["Recipes"],
    summary="Create a recipe",
    description="Create a new recipe belonging to the authenticated user.",
    responses={401: {"description": "Authentication required."}},
)
def create_recipe(
    payload: RecipeCreate,
    db: DbSession,
    current_user: Annotated[User, Depends(_get_current_user)],
) -> RecipeDetail:
    """Create a recipe for the current user."""
    recipe = create_recipe_from_payload(db, payload, current_user)
    if payload.moderationStatus != "approved":
        db.add(
            ModerationReport(
                recipe_id=recipe.id,
                submitted_by_name=current_user.full_name,
                reason="New recipe submitted for moderation review.",
                status="pending",
            )
        )
    db.commit()
    db.refresh(recipe)
    recipe = _get_recipe_or_404(db, recipe.id)
    return to_recipe_detail(recipe, current_user_id=current_user.id)


# PUBLIC_INTERFACE
@app.put(
    "/recipes/{recipe_id}",
    response_model=RecipeDetail,
    tags=["Recipes"],
    summary="Update a recipe",
    description="Update an existing recipe that belongs to the authenticated user, or any recipe for admins.",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Not allowed."}},
)
def update_recipe(
    recipe_id: str,
    payload: RecipeUpdate,
    db: DbSession,
    current_user: Annotated[User, Depends(_get_current_user)],
) -> RecipeDetail:
    """Update a recipe if the current user owns it or is an admin."""
    recipe = _get_recipe_or_404(db, recipe_id)
    if current_user.role != "admin" and recipe.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to edit this recipe.")

    update_data = payload.model_dump(exclude_unset=True)
    if "title" in update_data:
        recipe.title = update_data["title"]
    if "description" in update_data:
        recipe.description = update_data["description"]
    if "image" in update_data:
        recipe.image = update_data["image"]
    if "cookTimeMinutes" in update_data:
        recipe.cook_time_minutes = update_data["cookTimeMinutes"]
    if "prepTimeMinutes" in update_data:
        recipe.prep_time_minutes = update_data["prepTimeMinutes"]
    if "servings" in update_data:
        recipe.servings = update_data["servings"]
    if "difficulty" in update_data:
        recipe.difficulty = update_data["difficulty"]
    if "notes" in update_data:
        recipe.notes = update_data["notes"]
    if "ingredients" in update_data:
        recipe.ingredients_blob = json.dumps(update_data["ingredients"])
    if "steps" in update_data:
        recipe.steps_blob = json.dumps(update_data["steps"])
    if "nutrition" in update_data and update_data["nutrition"] is not None:
        recipe.calories = update_data["nutrition"].calories
        recipe.protein = update_data["nutrition"].protein
        recipe.carbs = update_data["nutrition"].carbs
        recipe.fat = update_data["nutrition"].fat
    if "moderationStatus" in update_data and update_data["moderationStatus"] is not None:
        recipe.moderation_status = update_data["moderationStatus"]
    if "category" in update_data and update_data["category"]:
        recipe.category_id = ensure_category(db, update_data["category"]).id
    if "tags" in update_data and update_data["tags"] is not None:
        attach_recipe_tags(db, recipe, update_data["tags"])

    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    recipe = _get_recipe_or_404(db, recipe.id)
    return to_recipe_detail(recipe, current_user_id=current_user.id)


# PUBLIC_INTERFACE
@app.delete(
    "/recipes/{recipe_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Recipes"],
    summary="Delete a recipe",
    description="Delete a recipe owned by the authenticated user, or any recipe for admins.",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Not allowed."}},
)
def delete_recipe(
    recipe_id: str,
    db: DbSession,
    current_user: Annotated[User, Depends(_get_current_user)],
) -> Response:
    """Delete a recipe if the current user owns it or is an admin."""
    recipe = _get_recipe_or_404(db, recipe_id)
    if current_user.role != "admin" and recipe.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to delete this recipe.")

    db.execute(delete(Favorite).where(Favorite.recipe_id == recipe.id))
    db.execute(delete(ModerationReport).where(ModerationReport.recipe_id == recipe.id))
    db.delete(recipe)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# PUBLIC_INTERFACE
@app.get(
    "/favorites",
    response_model=list[FavoriteRecipe],
    tags=["Favorites"],
    summary="List favorite recipes",
    description="Return the current user's favorite recipes in the shape used by the frontend.",
    responses={401: {"description": "Authentication required."}},
)
def list_favorites(
    db: DbSession,
    current_user: Annotated[User, Depends(_get_current_user)],
) -> list[FavoriteRecipe]:
    """Return the current user's favorite recipes."""
    favorites = db.scalars(
        select(Favorite)
        .where(Favorite.user_id == current_user.id)
        .options(selectinload(Favorite.recipe).selectinload(Recipe.category))
        .order_by(Favorite.created_at.desc())
    ).all()
    return [to_favorite_response(favorite) for favorite in favorites]


# PUBLIC_INTERFACE
@app.post(
    "/favorites/{recipe_id}",
    response_model=FavoriteRecipe,
    status_code=status.HTTP_201_CREATED,
    tags=["Favorites"],
    summary="Favorite a recipe",
    description="Add a recipe to the current user's saved favorites.",
    responses={401: {"description": "Authentication required."}, 404: {"description": "Recipe not found."}},
)
def add_favorite(
    recipe_id: str,
    db: DbSession,
    current_user: Annotated[User, Depends(_get_current_user)],
) -> FavoriteRecipe:
    """Favorite a recipe for the current user."""
    recipe = _get_recipe_or_404(db, recipe_id)
    favorite = db.scalar(
        select(Favorite)
        .where(Favorite.user_id == current_user.id, Favorite.recipe_id == recipe.id)
        .options(selectinload(Favorite.recipe).selectinload(Recipe.category))
    )
    if favorite:
        return to_favorite_response(favorite)

    favorite = Favorite(user_id=current_user.id, recipe_id=recipe.id)
    db.add(favorite)
    db.commit()
    favorite = db.scalar(
        select(Favorite)
        .where(Favorite.user_id == current_user.id, Favorite.recipe_id == recipe.id)
        .options(selectinload(Favorite.recipe).selectinload(Recipe.category))
    )
    return to_favorite_response(favorite)


# PUBLIC_INTERFACE
@app.delete(
    "/favorites/{recipe_id}",
    response_model=MessageResponse,
    tags=["Favorites"],
    summary="Remove a favorite",
    description="Remove a recipe from the current user's saved favorites.",
    responses={401: {"description": "Authentication required."}},
)
def remove_favorite(
    recipe_id: str,
    db: DbSession,
    current_user: Annotated[User, Depends(_get_current_user)],
) -> MessageResponse:
    """Remove a favorite from the current user."""
    recipe = _get_recipe_or_404(db, recipe_id)
    favorite = db.scalar(select(Favorite).where(Favorite.user_id == current_user.id, Favorite.recipe_id == recipe.id))
    if favorite:
        db.delete(favorite)
        db.commit()
    return MessageResponse(message="Favorite removed.")


# PUBLIC_INTERFACE
@app.get(
    "/shopping-list",
    response_model=list[ShoppingListItemResponse],
    tags=["Shopping List"],
    summary="Get shopping list items",
    description="Return the authenticated user's shopping list items.",
    responses={401: {"description": "Authentication required."}},
)
def get_shopping_list(
    db: DbSession,
    current_user: Annotated[User, Depends(_get_current_user)],
) -> list[ShoppingListItemResponse]:
    """Return the current user's shopping list items."""
    shopping_list = get_or_create_default_shopping_list(db, current_user)
    items = db.scalars(
        select(ShoppingListItem)
        .where(ShoppingListItem.shopping_list_id == shopping_list.id)
        .options(selectinload(ShoppingListItem.recipe))
        .order_by(ShoppingListItem.sort_order.asc(), ShoppingListItem.created_at.asc())
    ).all()
    return [
        ShoppingListItemResponse(
            id=item.id,
            label=item.label,
            quantity=item.quantity,
            checked=item.checked,
            recipeTitle=item.recipe.title if item.recipe else "Manual item",
        )
        for item in items
    ]


# PUBLIC_INTERFACE
@app.post(
    "/shopping-list/generate",
    response_model=list[ShoppingListItemResponse],
    tags=["Shopping List"],
    summary="Generate shopping list from recipes",
    description="Replace the current user's shopping list using the ingredients from the selected recipes.",
    responses={401: {"description": "Authentication required."}},
)
def generate_shopping_list(
    payload: ShoppingListGenerateRequest,
    db: DbSession,
    current_user: Annotated[User, Depends(_get_current_user)],
) -> list[ShoppingListItemResponse]:
    """Generate a shopping list from selected recipe ids."""
    shopping_list = get_or_create_default_shopping_list(db, current_user)
    existing_items = db.scalars(select(ShoppingListItem).where(ShoppingListItem.shopping_list_id == shopping_list.id)).all()
    for item in existing_items:
        db.delete(item)
    db.flush()

    recipes = db.scalars(recipe_query().where(Recipe.id.in_(payload.recipeIds))).all()
    items_to_create: list[ShoppingListItem] = []
    index = 1
    for recipe in recipes:
        for ingredient in json.loads(recipe.ingredients_blob or "[]"):
            parts = ingredient.split(" ", 2)
            quantity = " ".join(parts[:2]).strip() if len(parts) > 1 else ""
            label = parts[2] if len(parts) > 2 else ingredient
            items_to_create.append(
                ShoppingListItem(
                    shopping_list_id=shopping_list.id,
                    recipe_id=recipe.id,
                    label=label,
                    quantity=quantity,
                    checked=False,
                    sort_order=index,
                )
            )
            index += 1

    db.add_all(items_to_create)
    db.commit()
    return get_shopping_list(db, current_user)


# PUBLIC_INTERFACE
@app.post(
    "/shopping-list/items",
    response_model=ShoppingListItemResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Shopping List"],
    summary="Add shopping list item",
    description="Add a manual shopping list item for the authenticated user.",
    responses={401: {"description": "Authentication required."}},
)
def add_shopping_list_item(
    payload: ShoppingListItemCreate,
    db: DbSession,
    current_user: Annotated[User, Depends(_get_current_user)],
) -> ShoppingListItemResponse:
    """Add a manual or recipe-linked shopping list item."""
    shopping_list = get_or_create_default_shopping_list(db, current_user)
    max_sort_order = db.scalar(
        select(func.max(ShoppingListItem.sort_order)).where(ShoppingListItem.shopping_list_id == shopping_list.id)
    ) or 0
    recipe = _get_recipe_or_404(db, payload.recipeId) if payload.recipeId else None
    item = ShoppingListItem(
        shopping_list_id=shopping_list.id,
        recipe_id=recipe.id if recipe else None,
        label=payload.label,
        quantity=payload.quantity,
        checked=False,
        sort_order=max_sort_order + 1,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    item = db.scalar(
        select(ShoppingListItem)
        .where(ShoppingListItem.id == item.id)
        .options(selectinload(ShoppingListItem.recipe))
    )
    return ShoppingListItemResponse(
        id=item.id,
        label=item.label,
        quantity=item.quantity,
        checked=item.checked,
        recipeTitle=item.recipe.title if item.recipe else "Manual item",
    )


# PUBLIC_INTERFACE
@app.patch(
    "/shopping-list/items/{item_id}",
    response_model=ShoppingListItemResponse,
    tags=["Shopping List"],
    summary="Toggle shopping list item",
    description="Toggle a shopping list item's checked state for the authenticated user.",
    responses={401: {"description": "Authentication required."}, 404: {"description": "Item not found."}},
)
def toggle_shopping_list_item(
    item_id: str,
    db: DbSession,
    current_user: Annotated[User, Depends(_get_current_user)],
) -> ShoppingListItemResponse:
    """Toggle the checked status of a shopping list item."""
    shopping_list = get_or_create_default_shopping_list(db, current_user)
    item = db.scalar(
        select(ShoppingListItem)
        .where(ShoppingListItem.id == item_id, ShoppingListItem.shopping_list_id == shopping_list.id)
        .options(selectinload(ShoppingListItem.recipe))
    )
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shopping list item not found.")
    item.checked = not item.checked
    db.add(item)
    db.commit()
    db.refresh(item)
    return ShoppingListItemResponse(
        id=item.id,
        label=item.label,
        quantity=item.quantity,
        checked=item.checked,
        recipeTitle=item.recipe.title if item.recipe else "Manual item",
    )


# PUBLIC_INTERFACE
@app.delete(
    "/shopping-list/items/{item_id}",
    response_model=MessageResponse,
    tags=["Shopping List"],
    summary="Delete shopping list item",
    description="Delete a shopping list item owned by the authenticated user.",
    responses={401: {"description": "Authentication required."}, 404: {"description": "Item not found."}},
)
def delete_shopping_list_item(
    item_id: str,
    db: DbSession,
    current_user: Annotated[User, Depends(_get_current_user)],
) -> MessageResponse:
    """Delete a shopping list item."""
    shopping_list = get_or_create_default_shopping_list(db, current_user)
    item = db.scalar(
        select(ShoppingListItem).where(
            ShoppingListItem.id == item_id,
            ShoppingListItem.shopping_list_id == shopping_list.id,
        )
    )
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shopping list item not found.")
    db.delete(item)
    db.commit()
    return MessageResponse(message="Shopping list item deleted.")


# PUBLIC_INTERFACE
@app.get(
    "/categories",
    response_model=list[CategorySummary],
    tags=["Catalog"],
    summary="List categories",
    description="Return categories with recipe counts for frontend sidebar filters.",
)
def get_categories(db: DbSession) -> list[CategorySummary]:
    """Return recipe categories with counts."""
    return list_categories_with_counts(db)


# PUBLIC_INTERFACE
@app.get(
    "/tags",
    response_model=list[str],
    tags=["Catalog"],
    summary="List tags",
    description="Return all available recipe tag labels sorted alphabetically.",
)
def get_tags(db: DbSession) -> list[str]:
    """Return all tag labels."""
    from src.models import Tag

    tags = db.scalars(select(Tag).order_by(Tag.label.asc())).all()
    return [tag.label for tag in tags]


# PUBLIC_INTERFACE
@app.get(
    "/moderation",
    response_model=list[ModerationQueueItem],
    tags=["Moderation"],
    summary="List moderation queue",
    description="Return moderation queue items. Admins see all items; other users only see pending/public-style data.",
)
def get_moderation_queue(
    db: DbSession,
    current_user: Annotated[User | None, Depends(_get_optional_user)],
) -> list[ModerationQueueItem]:
    """Return moderation queue items."""
    reports = db.scalars(
        select(ModerationReport)
        .options(selectinload(ModerationReport.recipe))
        .order_by(ModerationReport.created_at.desc())
    ).all()

    queue = [to_moderation_queue_item(report) for report in reports]
    if current_user and current_user.role == "admin":
        return queue
    return [item for item in queue if item.status == "pending"]


# PUBLIC_INTERFACE
@app.patch(
    "/moderation/{report_id}",
    response_model=ModerationQueueItem,
    tags=["Moderation"],
    summary="Moderate a recipe",
    description="Approve or reject a moderation queue item. Admin access required.",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Admin access required."}},
)
def moderate_recipe(
    report_id: str,
    payload: ModerationActionRequest,
    db: DbSession,
    _: Annotated[User, Depends(_get_admin_user)],
) -> ModerationQueueItem:
    """Approve or reject a moderation queue entry."""
    report = db.scalar(
        select(ModerationReport)
        .where(ModerationReport.id == report_id)
        .options(selectinload(ModerationReport.recipe))
    )
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation item not found.")

    report.status = payload.status
    report.reason = payload.reason or report.reason
    report.recipe.moderation_status = "approved" if payload.status == "approved" else "flagged"

    db.add(report)
    db.add(report.recipe)
    db.commit()
    db.refresh(report)
    return to_moderation_queue_item(report)
