from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from calango_cli.main import app

runner = CliRunner()


def _make_project(tmp_path: Path) -> Path:
    """Create minimal Calango project structure for tests."""
    (tmp_path / "app").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Basic exit-code and validation tests
# ---------------------------------------------------------------------------


def test_generate_resource_exits_0(tmp_path):
    """calango generate resource Shop.Order exits 0 in a valid project."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    assert result.exit_code == 0


def test_generate_resource_without_context_exits_1(tmp_path):
    """calango generate resource Order (no dot) exits 1."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_generate_resource_lowercase_context_exits_1(tmp_path):
    """calango generate resource shop.Order (lowercase context) exits 1."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "shop.Order", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_generate_resource_requires_pascal_case_resource(tmp_path):
    """calango generate resource Shop.order (lowercase resource) exits 1."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Shop.order", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_generate_resource_requires_app_directory(tmp_path):
    """calango generate resource Shop.Order exits 1 if app/ dir missing."""
    result = runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_generate_resource_accepts_compound_name(tmp_path):
    """calango generate resource Shop.ProductItem exits 0."""
    _make_project(tmp_path)
    result = runner.invoke(
        app, ["generate", "resource", "Shop.ProductItem", "--path", str(tmp_path)]
    )
    assert result.exit_code == 0


def test_generate_resource_help_is_available():
    """calango generate resource --help exits 0."""
    result = runner.invoke(app, ["generate", "resource", "--help"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Helper-function unit tests (no change needed)
# ---------------------------------------------------------------------------


def test_to_snake_case_simple():
    """_to_snake_case('Order') returns 'order'."""
    from calango_cli.commands.generate import _to_snake_case

    assert _to_snake_case("Order") == "order"


def test_to_snake_case_compound():
    """_to_snake_case('ProductItem') returns 'product_item'."""
    from calango_cli.commands.generate import _to_snake_case

    assert _to_snake_case("ProductItem") == "product_item"


def test_to_plural_simple():
    """_to_plural('order') returns 'orders'."""
    from calango_cli.commands.generate import _to_plural

    assert _to_plural("order") == "orders"


def test_to_plural_y_ending():
    """_to_plural('category') returns 'categories'."""
    from calango_cli.commands.generate import _to_plural

    assert _to_plural("category") == "categories"


# ---------------------------------------------------------------------------
# Context directory and __init__.py management
# ---------------------------------------------------------------------------


def test_generate_resource_creates_context_dir(tmp_path):
    """generate resource Shop.Order creates app/contexts/shop/ directory."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    assert (tmp_path / "app" / "contexts" / "shop").is_dir()


def test_generate_resource_creates_context_init(tmp_path):
    """generate resource Shop.Order creates app/contexts/shop/__init__.py with correct imports."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    init = tmp_path / "app" / "contexts" / "shop" / "__init__.py"
    assert init.exists()
    content = init.read_text()
    assert "OrderService" in content
    assert "OrderRepository" in content
    assert "OrderInput" in content


def test_generate_resource_second_resource_updates_context_init(tmp_path):
    """Generating a second resource in the same context appends to __init__.py."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    runner.invoke(app, ["generate", "resource", "Shop.Product", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "contexts" / "shop" / "__init__.py").read_text()
    assert "OrderService" in content
    assert "ProductService" in content


def test_generate_resource_no_duplication_in_context_init(tmp_path):
    """Regenerating the same resource does not duplicate entries in __init__.py."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    once_content = (tmp_path / "app" / "contexts" / "shop" / "__init__.py").read_text()
    once_count = once_content.count("OrderService")
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "contexts" / "shop" / "__init__.py").read_text()
    # After regenerating, the count must not increase (no duplicate entries added)
    assert content.count("OrderService") == once_count


# ---------------------------------------------------------------------------
# Model file
# ---------------------------------------------------------------------------


def test_generate_resource_creates_model_file(tmp_path):
    """generate resource Shop.Order creates app/contexts/shop/models/order.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "app" / "contexts" / "shop" / "models" / "order.py").exists()


def test_generate_resource_model_contains_class_name(tmp_path):
    """app/contexts/shop/models/order.py contains class Order."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "contexts" / "shop" / "models" / "order.py").read_text()
    assert "class Order(Base):" in content


# ---------------------------------------------------------------------------
# Schemas file
# ---------------------------------------------------------------------------


def test_generate_resource_creates_schemas_file(tmp_path):
    """generate resource Shop.Order creates app/contexts/shop/schemas/order.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "app" / "contexts" / "shop" / "schemas" / "order.py").exists()


def test_generate_resource_schemas_has_input_output_update(tmp_path):
    """app/contexts/shop/schemas/order.py contains OrderInput, OrderOutput, OrderUpdate."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "contexts" / "shop" / "schemas" / "order.py").read_text()
    assert "class OrderInput(CalangoModel):" in content
    assert "class OrderOutput(CalangoModel):" in content
    assert "class OrderUpdate(CalangoModel):" in content


# ---------------------------------------------------------------------------
# Repository file
# ---------------------------------------------------------------------------


def test_generate_resource_creates_repository_file(tmp_path):
    """generate resource Shop.Order creates app/contexts/shop/repositories/order.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "app" / "contexts" / "shop" / "repositories" / "order.py").exists()


def test_generate_resource_repository_extends_base(tmp_path):
    """app/contexts/shop/repositories/order.py contains OrderRepository(BaseRepository[Order])."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "contexts" / "shop" / "repositories" / "order.py").read_text()
    assert "class OrderRepository(BaseRepository[Order]):" in content


# ---------------------------------------------------------------------------
# Service file
# ---------------------------------------------------------------------------


def test_generate_resource_creates_service_file(tmp_path):
    """generate resource Shop.Order creates app/contexts/shop/services/order.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "app" / "contexts" / "shop" / "services" / "order.py").exists()


def test_generate_resource_service_extends_base(tmp_path):
    """app/contexts/shop/services/order.py contains OrderService(BaseService[OrderRepository])."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "contexts" / "shop" / "services" / "order.py").read_text()
    assert "class OrderService(BaseService[OrderRepository]):" in content


def test_generate_resource_service_has_crud_methods(tmp_path):
    """app/contexts/shop/services/order.py contains create, get, list, update, delete methods."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "contexts" / "shop" / "services" / "order.py").read_text()
    assert "async def create(" in content
    assert "async def get(" in content
    assert "async def list(" in content
    assert "async def update(" in content
    assert "async def delete(" in content


# ---------------------------------------------------------------------------
# Router file (stays in app/routers/ — outside context)
# ---------------------------------------------------------------------------


def test_generate_resource_creates_router_file(tmp_path):
    """generate resource Shop.Order creates app/routers/order.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "app" / "routers" / "order.py").exists()


def test_generate_resource_router_has_prefix(tmp_path):
    """app/routers/order.py contains prefix='/orders'."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "routers" / "order.py").read_text()
    assert 'prefix="/orders"' in content


def test_generate_resource_router_has_crud_endpoints(tmp_path):
    """app/routers/order.py contains POST, GET, PATCH, DELETE endpoints."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "routers" / "order.py").read_text()
    assert "@router.post(" in content
    assert "@router.get(" in content
    assert "@router.patch(" in content
    assert "@router.delete(" in content


def test_generate_resource_router_imports_from_context(tmp_path):
    """app/routers/order.py imports from app.contexts.shop public API."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "routers" / "order.py").read_text()
    assert "from app.contexts.shop import" in content


def test_generate_resource_router_uses_correct_service(tmp_path):
    """app/routers/order.py imports OrderService from context public API."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "routers" / "order.py").read_text()
    assert "from app.contexts." in content
    assert "OrderService" in content


# ---------------------------------------------------------------------------
# Test files
# ---------------------------------------------------------------------------


def test_generate_resource_creates_unit_test_file(tmp_path):
    """generate resource Shop.Order creates tests/unit/shop/test_order_service.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "tests" / "unit" / "shop" / "test_order_service.py").exists()


def test_generate_resource_unit_test_has_five_cases(tmp_path):
    """tests/unit/shop/test_order_service.py has 5 test methods."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "tests" / "unit" / "shop" / "test_order_service.py").read_text()
    assert content.count("async def test_") == 5


def test_generate_resource_creates_integration_test_file(tmp_path):
    """generate resource Shop.Order creates tests/integration/shop/test_order_router.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "tests" / "integration" / "shop" / "test_order_router.py").exists()


def test_generate_resource_integration_test_has_security_cases(tmp_path):
    """tests/integration/shop/test_order_router.py has authentication and mass-assignment tests."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "tests" / "integration" / "shop" / "test_order_router.py").read_text()
    assert "test_create_order_requires_authentication" in content
    assert "test_order_mass_assignment_is_blocked" in content


# ---------------------------------------------------------------------------
# Factory file
# ---------------------------------------------------------------------------


def test_generate_resource_creates_factory_file(tmp_path):
    """generate resource Shop.Order creates tests/factories/order_factory.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "tests" / "factories" / "order_factory.py").exists()


def test_generate_resource_factory_class_name_matches_resource(tmp_path):
    """tests/factories/order_factory.py contains OrderFactory."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "tests" / "factories" / "order_factory.py").read_text()
    assert "class OrderFactory(factory.Factory):" in content


# ---------------------------------------------------------------------------
# Compound resource name
# ---------------------------------------------------------------------------


def test_generate_resource_compound_name_uses_snake_case_filename(tmp_path):
    """generate resource Shop.ProductItem creates app/contexts/shop/models/product_item.py."""
    _make_project(tmp_path)
    result = runner.invoke(
        app, ["generate", "resource", "Shop.ProductItem", "--path", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert (tmp_path / "app" / "contexts" / "shop" / "models" / "product_item.py").exists()


def test_generate_resource_compound_context_name_uses_snake_case_dir(tmp_path):
    """calango generate resource OnlineShop.Order creates app/contexts/online_shop/..."""
    _make_project(tmp_path)
    result = runner.invoke(
        app, ["generate", "resource", "OnlineShop.Order", "--path", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert (tmp_path / "app" / "contexts" / "online_shop" / "models" / "order.py").exists()


# ---------------------------------------------------------------------------
# 10-file generation test
# ---------------------------------------------------------------------------


def test_generate_resource_generates_9_files(tmp_path):
    """generate resource Shop.Order creates 9 files: 8 resource files + context __init__.py."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    expected = [
        tmp_path / "app" / "contexts" / "shop" / "models" / "order.py",
        tmp_path / "app" / "contexts" / "shop" / "schemas" / "order.py",
        tmp_path / "app" / "contexts" / "shop" / "repositories" / "order.py",
        tmp_path / "app" / "contexts" / "shop" / "services" / "order.py",
        tmp_path / "app" / "contexts" / "shop" / "__init__.py",
        tmp_path / "app" / "routers" / "order.py",
        tmp_path / "tests" / "unit" / "shop" / "test_order_service.py",
        tmp_path / "tests" / "integration" / "shop" / "test_order_router.py",
        tmp_path / "tests" / "factories" / "order_factory.py",
    ]
    for f in expected:
        assert f.exists(), f"Expected file not found: {f}"


# ---------------------------------------------------------------------------
# Non-interactive and wizard tests
# ---------------------------------------------------------------------------


def test_generate_resource_without_name_in_non_interactive_exits_1(tmp_path):
    """calango generate resource with no name in non-TTY exits 1."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_generate_resource_wizard_creates_all_files(tmp_path):
    """Interactive wizard creates all resource files."""
    _make_project(tmp_path)
    with (
        patch("calango_cli.commands.generate.is_interactive", return_value=True),
        patch("calango_cli.commands.generate.ask", return_value="Shop.Order"),
    ):
        result = runner.invoke(app, ["generate", "resource", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "app" / "contexts" / "shop" / "models" / "order.py").exists()


def test_generate_resource_wizard_validates_format(tmp_path):
    """Wizard rejects a resource name without Context.Resource format."""
    _make_project(tmp_path)
    with (
        patch("calango_cli.commands.generate.is_interactive", return_value=True),
        patch("calango_cli.commands.generate.ask", return_value="order"),
    ):
        result = runner.invoke(app, ["generate", "resource", "--path", str(tmp_path)])
    assert result.exit_code == 1
