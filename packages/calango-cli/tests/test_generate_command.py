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
