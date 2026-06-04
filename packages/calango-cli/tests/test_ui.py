from unittest.mock import patch

import pytest


def test_is_interactive_false_without_tty():
    from calango_cli import ui
    assert ui.is_interactive() is False


def test_print_banner_does_not_raise():
    from calango_cli import ui
    ui.print_banner()


def test_print_banner_with_subtitle_does_not_raise():
    from calango_cli import ui
    ui.print_banner("new project")


def test_print_success_does_not_raise():
    from calango_cli import ui
    ui.print_success("Operation complete")


def test_print_success_with_detail_does_not_raise():
    from calango_cli import ui
    ui.print_success("Operation complete", detail="Next: do something")


def test_print_error_does_not_raise():
    from calango_cli import ui
    ui.print_error("Something went wrong")


def test_print_error_with_hint_does_not_raise():
    from calango_cli import ui
    ui.print_error("Something went wrong", hint="Try: calango new")


def test_print_info_does_not_raise():
    from calango_cli import ui
    ui.print_info("Creating project — my-api", {"db": "postgres", "ci": "github"})


def test_print_file_tree_does_not_raise():
    from calango_cli import ui
    ui.print_file_tree("my-project", ["app/main.py", "compose.yml"])


def test_print_file_tree_single_file_does_not_raise():
    from calango_cli import ui
    ui.print_file_tree("my-project", ["app/main.py"])
