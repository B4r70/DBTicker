# ==========================================================================
#  Projektname · src/cli/formatters.py
#  ----------------------------------------------------
#  Formatting-Helfer für die CLI-Ausgabe.
#
#  Autor:  Bartosz Stryjewski
#  Datum:  06.05.2026
# ==========================================================================
#
"""
Verwendet `rich` für Tabellen — kommt mit questionary mit, also keine
zusätzliche Dependency.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from src.config_defaults import ROUTE_DEFAULTS, is_default

_console = Console()


# ------------------------------------------------------------------------------
#  Routes-Liste
# ------------------------------------------------------------------------------

def print_routes_table(routes: list[dict]) -> None:
    """Druckt eine Übersicht aller Routen als Tabelle."""
    if not routes:
        _console.print("[yellow]Keine Routen konfiguriert.[/yellow]")
        _console.print("Lege eine an mit:  [cyan]dbticker-routes add[/cyan]")
        return

    table = Table(
        title=f"DBTicker — {len(routes)} Route(n)",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("ID", style="bold")
    table.add_column("Strecke")
    table.add_column("Abfahrt")
    table.add_column("Linie")
    table.add_column("Tage")
    table.add_column("Custom?", justify="center")

    for r in routes:
        days = ",".join(r.get("active_days", []))
        custom = "•" if _has_custom_fields(r) else ""

        table.add_row(
            r.get("id", "?"),
            f"{r.get('from_station', '?')} → {r.get('to_station', '?')}",
            r.get("scheduled_departure", "?"),
            r.get("line", "?"),
            days,
            custom,
        )

    _console.print(table)
    _console.print(
        "\n[dim]• = Route überschreibt mind. einen Default. Details:  "
        "[/dim][cyan]dbticker-routes show <id>[/cyan]"
    )


def print_route_detail(route: dict) -> None:
    """Druckt eine einzelne Route mit allen effektiven Werten.

    Werte, die aus den Defaults kommen, werden grau dargestellt;
    überschriebene Werte normal.
    """
    route_id = route.get("id", "?")
    _console.print(f"\n[bold cyan]Route '{route_id}'[/bold cyan]\n")

    # Pflichtfelder
    _console.print("[bold]Strecke:[/bold]")
    _print_field(route, "from_station", required=True)
    _print_field(route, "to_station", required=True)
    _print_field(route, "via_station", required=True)

    _console.print("\n[bold]Fahrplan:[/bold]")
    _print_field(route, "scheduled_departure", required=True)
    _print_field(route, "line", required=True)
    _print_field(route, "active_days", required=True)

    _console.print("\n[bold]Check-Mechanik:[/bold]")
    for field in ("check_window_before_min", "check_window_after_min",
                  "alert_threshold_min", "max_delay_tracking_min"):
        _print_field(route, field)

    _console.print("\n[bold]All-Clear-Fenster:[/bold]")
    for field in ("all_clear_window_start_min", "all_clear_window_end_min"):
        _print_field(route, field)

    if any(k in route for k in ("my_departure_time", "arrival_destination")):
        _console.print("\n[bold]Tagesablauf:[/bold]")
        for field in ("my_departure_time", "my_departure_label",
                      "delay_shifts_my_time", "arrival_destination",
                      "arrival_offset_min"):
            if field in route or field in ROUTE_DEFAULTS:
                _print_field(route, field)


def _print_field(route: dict, field: str, required: bool = False) -> None:
    """Druckt ein einzelnes Feld. Default-Werte werden grau, überschriebene
    Werte normal angezeigt.
    """
    if field in route:
        value = route[field]
        # Prüfen ob explizit gesetzt == Default
        if not required and is_default(field, value):
            _console.print(f"  {field:32} = {value!r}  [dim](= Default)[/dim]")
        else:
            _console.print(f"  {field:32} = [bold]{value!r}[/bold]")
    elif field in ROUTE_DEFAULTS:
        # Nicht in TOML → kommt aus Defaults
        value = ROUTE_DEFAULTS[field]
        _console.print(f"  {field:32} = [dim]{value!r}  (Default)[/dim]")
    elif required:
        _console.print(f"  {field:32} = [red]FEHLT[/red]")


# ------------------------------------------------------------------------------
#  Migration-Diff
# ------------------------------------------------------------------------------

def print_migration_diff(diffs: list[dict]) -> None:
    """Druckt den Diff der Migration: was wird entfernt, was bleibt drin."""
    if not diffs:
        _console.print(
            "[green]✓[/green] Alle Routen sind bereits sauber — keine Migration nötig."
        )
        return

    _console.print(
        "[bold]Folgende Felder können entfernt werden, weil sie dem Default "
        "entsprechen:[/bold]\n"
    )

    for entry in diffs:
        route_id = entry["id"]
        removable = entry["removable"]
        kept = entry["kept_with_diff"]

        _console.print(f"  [bold cyan]{route_id}:[/bold cyan]")

        for field, value in removable:
            _console.print(
                f"    [green]−[/green] {field:32} = {value!r}  [dim](Default)[/dim]"
            )

        for field, value, default in kept:
            _console.print(
                f"    [yellow]·[/yellow] {field:32} = {value!r}  "
                f"[yellow]⚠ Abweichung (Default: {default!r}) — bleibt[/yellow]"
            )

        _console.print("")


def _has_custom_fields(route: dict) -> bool:
    """True, wenn die Route mind. ein Feld mit Nicht-Default-Wert hat."""
    for field in ROUTE_DEFAULTS:
        if field in route and route[field] != ROUTE_DEFAULTS[field]:
            return True
    return False