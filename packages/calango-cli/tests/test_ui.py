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


def test_ask_delegates_to_questionary_text():
    import questionary as _questionary
    from calango_cli import ui
    with patch("calango_cli.ui.questionary") as mock_q:
        mock_q.text.return_value.unsafe_ask.return_value = "my-answer"
        mock_q.Style = _questionary.Style  # keep real Style constructor
        result = ui.ask("Project name")
    assert result == "my-answer"
    mock_q.text.assert_called_once()


def test_ask_choice_delegates_to_questionary_select():
    from calango_cli import ui
    with patch("calango_cli.ui.questionary") as mock_q:
        mock_q.Choice.side_effect = lambda title, value, **kw: value
        mock_q.select.return_value.unsafe_ask.return_value = "postgres"
        result = ui.ask_choice("Database", ["postgres", "mongo"], default="postgres")
    assert result == "postgres"
    mock_q.select.assert_called_once()


def test_ask_choice_marks_disabled_entries():
    from calango_cli import ui
    with patch("calango_cli.ui.questionary") as mock_q:
        mock_q.Choice.side_effect = lambda title, value, **kw: value
        mock_q.select.return_value.unsafe_ask.return_value = "postgres"
        ui.ask_choice(
            "Database",
            ["postgres", "mongo"],
            default="postgres",
            disabled={"mongo": "coming soon"},
        )
    calls = mock_q.Choice.call_args_list
    disabled_calls = [c for c in calls if c.kwargs.get("disabled")]
    assert len(disabled_calls) == 1
    assert "mongo" in str(disabled_calls[0])


def test_ask_confirm_delegates_to_questionary_confirm():
    from calango_cli import ui
    with patch("calango_cli.ui.questionary") as mock_q:
        mock_q.confirm.return_value.unsafe_ask.return_value = True
        result = ui.ask_confirm("Enable agents?", default=False)
    assert result is True
    mock_q.confirm.assert_called_once()
