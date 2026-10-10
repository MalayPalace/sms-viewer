"""
CLI entry point for SMS Viewer.

Provides the ``sms-viewer`` command registered in pyproject.toml under
``[project.scripts]``.

Usage examples::

    sms-viewer                           # defaults
    sms-viewer --host 0.0.0.0 --port 8080
    sms-viewer --db-path /data/sms.db
    sms-viewer --no-browser              # do not auto-open browser tab
    sms-viewer --debug                   # Flask debug / reloader mode
"""

import webbrowser
from threading import Timer

import click

from sms_viewer.app import create_app
from sms_viewer.database import resolve_db_path


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    envvar="SMS_VIEWER_HOST",
    help="Host address to bind the HTTP server to.",
)
@click.option(
    "-p",
    "--port",
    default=5000,
    type=int,
    show_default=True,
    envvar="SMS_VIEWER_PORT",
    help="Port number to listen on.",
)
@click.option(
    "-d",
    "--db-path",
    "db_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    envvar="SMS_VIEWER_DB",
    help="Path to SQLite database file [default: ~/.sms-viewer/sms.db].",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable Flask debug / reloader mode (do not use in production).",
)
@click.option(
    "--open-browser/--no-browser",
    default=False,
    show_default=True,
    help="Automatically open the system browser on startup.",
)
def main(
    host: str,
    port: int,
    db_path: str | None,
    debug: bool,
    open_browser: bool,
) -> None:
    """SMS Viewer — Browse your SMS backup in a threaded web UI."""
    resolved_db = resolve_db_path(db_path)

    click.secho("─" * 50, fg="bright_black")
    click.secho("  SMS Viewer", fg="bright_cyan", bold=True)
    click.secho("─" * 50, fg="bright_black")
    click.secho(f"  Database : {resolved_db}", fg="cyan")
    click.secho(f"  URL      : http://{host}:{port}", fg="green", bold=True)
    if debug:
        click.secho("  Mode     : DEBUG (reloader active)", fg="yellow")
    click.secho("─" * 50, fg="bright_black")
    click.secho("  Press Ctrl+C to stop.", fg="bright_black")

    app = create_app(db_path=str(resolved_db))
    url = f"http://{host}:{port}"

    # Open browser after a short delay so the server has time to bind
    if open_browser and not debug:
        Timer(1.2, lambda: webbrowser.open(url)).start()

    app.run(host=host, port=port, debug=debug, use_reloader=debug)


if __name__ == "__main__":
    main()
