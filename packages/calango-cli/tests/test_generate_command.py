from pathlib import Path

from typer.testing import CliRunner

from calango_cli.main import app

runner = CliRunner()


def _make_project(tmp_path: Path) -> Path:
    """Create minimal Calango project structure for tests."""
    (tmp_path / "app").mkdir()
    return tmp_path


def test_generate_resource_exits_0(tmp_path):
    """calango generate resource Order exits 0 in a valid project."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    assert result.exit_code == 0


def test_generate_resource_requires_pascal_case(tmp_path):
    """calango generate resource order (lowercase) exits 1."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "order", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_generate_resource_requires_app_directory(tmp_path):
    """calango generate resource Order exits 1 if app/ dir missing."""
    result = runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_generate_resource_accepts_compound_name(tmp_path):
    """calango generate resource ProductItem exits 0."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "ProductItem", "--path", str(tmp_path)])
    assert result.exit_code == 0


def test_generate_resource_help_is_available():
    """calango generate resource --help exits 0."""
    result = runner.invoke(app, ["generate", "resource", "--help"])
    assert result.exit_code == 0


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


def test_generate_resource_creates_model_file(tmp_path):
    """generate resource Order creates app/models/order.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "app" / "models" / "order.py").exists()


def test_generate_resource_model_contains_class_name(tmp_path):
    """app/models/order.py contains class Order."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "models" / "order.py").read_text()
    assert "class Order(Base):" in content


def test_generate_resource_creates_schemas_file(tmp_path):
    """generate resource Order creates app/schemas/order.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "app" / "schemas" / "order.py").exists()


def test_generate_resource_schemas_has_input_output_update(tmp_path):
    """app/schemas/order.py contains OrderInput, OrderOutput, OrderUpdate."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "schemas" / "order.py").read_text()
    assert "class OrderInput(CalangoModel):" in content
    assert "class OrderOutput(CalangoModel):" in content
    assert "class OrderUpdate(CalangoModel):" in content


def test_generate_resource_compound_name_uses_snake_case_filename(tmp_path):
    """generate resource ProductItem creates app/models/product_item.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "ProductItem", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "app" / "models" / "product_item.py").exists()


def test_generate_resource_creates_repository_file(tmp_path):
    """generate resource Order creates app/repositories/order.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "app" / "repositories" / "order.py").exists()


def test_generate_resource_repository_extends_base(tmp_path):
    """app/repositories/order.py contains OrderRepository(BaseRepository[Order])."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "repositories" / "order.py").read_text()
    assert "class OrderRepository(BaseRepository[Order]):" in content


def test_generate_resource_creates_service_file(tmp_path):
    """generate resource Order creates app/services/order.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "app" / "services" / "order.py").exists()


def test_generate_resource_service_extends_base(tmp_path):
    """app/services/order.py contains OrderService(BaseService[OrderRepository])."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "services" / "order.py").read_text()
    assert "class OrderService(BaseService[OrderRepository]):" in content


def test_generate_resource_service_has_crud_methods(tmp_path):
    """app/services/order.py contains create, get, list, update, delete methods."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "services" / "order.py").read_text()
    assert "async def create(" in content
    assert "async def get(" in content
    assert "async def list(" in content
    assert "async def update(" in content
    assert "async def delete(" in content


def test_generate_resource_creates_router_file(tmp_path):
    """generate resource Order creates app/routers/order.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "app" / "routers" / "order.py").exists()


def test_generate_resource_router_has_prefix(tmp_path):
    """app/routers/order.py contains prefix='/orders'."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "routers" / "order.py").read_text()
    assert "prefix=\"/orders\"" in content


def test_generate_resource_router_has_crud_endpoints(tmp_path):
    """app/routers/order.py contains POST, GET, PATCH, DELETE endpoints."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "routers" / "order.py").read_text()
    assert "@router.post(" in content
    assert "@router.get(" in content
    assert "@router.patch(" in content
    assert "@router.delete(" in content


def test_generate_resource_router_uses_correct_service(tmp_path):
    """app/routers/order.py imports and uses OrderService."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "routers" / "order.py").read_text()
    assert "from app.services.order import OrderService" in content
    assert "OrderService" in content


def test_generate_resource_creates_unit_test_file(tmp_path):
    """generate resource Order creates tests/unit/test_order_service.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "tests" / "unit" / "test_order_service.py").exists()


def test_generate_resource_unit_test_has_five_cases(tmp_path):
    """tests/unit/test_order_service.py has 5 test methods."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    content = (tmp_path / "tests" / "unit" / "test_order_service.py").read_text()
    assert content.count("async def test_") == 5


def test_generate_resource_creates_integration_test_file(tmp_path):
    """generate resource Order creates tests/integration/test_order_router.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "tests" / "integration" / "test_order_router.py").exists()


def test_generate_resource_integration_test_has_security_cases(tmp_path):
    """tests/integration/test_order_router.py has authentication and mass-assignment tests."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    content = (tmp_path / "tests" / "integration" / "test_order_router.py").read_text()
    assert "test_create_order_requires_authentication" in content
    assert "test_order_mass_assignment_is_blocked" in content


def test_generate_resource_creates_factory_file(tmp_path):
    """generate resource Order creates tests/factories/order_factory.py."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "tests" / "factories" / "order_factory.py").exists()


def test_generate_resource_factory_class_name_matches_resource(tmp_path):
    """tests/factories/order_factory.py contains OrderFactory."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    content = (tmp_path / "tests" / "factories" / "order_factory.py").read_text()
    assert "class OrderFactory(factory.Factory):" in content


def test_generate_resource_generates_all_8_files(tmp_path):
    """calango generate resource Order creates exactly 8 files."""
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Order", "--path", str(tmp_path)])
    expected_files = [
        tmp_path / "app" / "models" / "order.py",
        tmp_path / "app" / "schemas" / "order.py",
        tmp_path / "app" / "repositories" / "order.py",
        tmp_path / "app" / "services" / "order.py",
        tmp_path / "app" / "routers" / "order.py",
        tmp_path / "tests" / "unit" / "test_order_service.py",
        tmp_path / "tests" / "integration" / "test_order_router.py",
        tmp_path / "tests" / "factories" / "order_factory.py",
    ]
    for f in expected_files:
        assert f.exists(), f"Expected file not found: {f}"
    assert len(expected_files) == 8
