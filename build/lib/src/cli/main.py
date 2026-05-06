# ==========================================================================
#  Projektname · src/cli/main.py
#  ----------------------------------------------------
#  DBTicker Route-Management CLI.
#
#  Autor:  Bartosz Stryjewski
#  Datum:  06.05.2026
# ==========================================================================
#
"""DBTicker Route-Management CLI.

Verwendung:
    dbticker-routes add              # Wizard für neue Route
    dbticker-routes list             # Übersicht
    dbticker-routes show <id>        # Details einer Route
    dbticker-routes edit <id>        # Wizard mit aktuellen Werten als Default
    dbticker-routes remove <id>      # Mit Bestätigung
    dbticker-routes migrate          # Default-Werte aus TOML rauswerfen

Alle schreibenden Befehle legen vor dem Schreiben ein Backup an
(routes.toml.bak.<timestamp>).
"""

from __future__ import annotations

import sys

import typer
from rich.console import Console

from src.config_defaults import ROUTE_DEFAULTS
from src.cli.config_io import (
    load_routes_doc,
    write_routes_doc,
    backup_routes_file,
    add_route_to_doc,
    replace_route_in_doc,
    remove_route_from_doc,
    find_route_by_id,
)
from src.cli.wizard import prompt_route
from src.cli.formatters import (
    print_routes_table,
    print_route_detail,
    print_migration_diff,
)


app = typer.Typer(
    help="DBTicker — Routen verwalten (add/list/show/edit/remove/migrate).",
    no_args_is_help=True,
)

console = Console()


# ------------------------------------------------------------------------------
#  route add
# ------------------------------------------------------------------------------

@app.command("add")
def cmd_add() -> None:
    """Neue Route per Wizard anlegen."""
    route_data = prompt_route(initial=None)
    if route_data is None:
        console.print("[yellow]Abgebrochen.[/yellow]")
        raise typer.Exit(code=1)

    # Backup + Schreiben
    backup_path = backup_routes_file()
    try:
        doc = load_routes_doc()
    except FileNotFoundError:
        # Erstanlage — leeres Document
        import tomlkit
        doc = tomlkit.document()

    add_route_to_doc(doc, route_data)
    write_routes_doc(doc)

    console.print(
        f"\n[green]✓[/green] Route [bold]{route_data['id']}[/bold] angelegt."
    )
    if backup_path:
        console.print(f"[dim]  Backup: {backup_path.name}[/dim]")
    console.print(
        f"\nTrockenlauf:  [cyan]dbticker --route {route_data['id']}[/cyan]"
    )


# ------------------------------------------------------------------------------
#  route list
# ------------------------------------------------------------------------------

@app.command("list")
def cmd_list() -> None:
    """Alle konfigurierten Routen anzeigen."""
    try:
        doc = load_routes_doc()
    except FileNotFoundError:
        console.print("[yellow]Noch keine routes.toml vorhanden.[/yellow]")
        console.print("Lege eine Route an mit:  [cyan]dbticker-routes add[/cyan]")
        raise typer.Exit(code=0)

    routes = list(doc.get("routes", []))
    print_routes_table([dict(r) for r in routes])


# ------------------------------------------------------------------------------
#  route show
# ------------------------------------------------------------------------------

@app.command("show")
def cmd_show(route_id: str = typer.Argument(..., help="Route-ID")) -> None:
    """Details einer Route inkl. effektiver Default-Werte anzeigen."""
    route = find_route_by_id(route_id)
    if route is None:
        console.print(f"[red]✗[/red] Route '{route_id}' nicht gefunden.")
        raise typer.Exit(code=1)

    print_route_detail(route)


# ------------------------------------------------------------------------------
#  route edit
# ------------------------------------------------------------------------------

@app.command("edit")
def cmd_edit(route_id: str = typer.Argument(..., help="Route-ID")) -> None:
    """Bestehende Route per Wizard bearbeiten (vorbelegt mit aktuellen Werten)."""
    existing = find_route_by_id(route_id)
    if existing is None:
        console.print(f"[red]✗[/red] Route '{route_id}' nicht gefunden.")
        raise typer.Exit(code=1)

    new_data = prompt_route(initial=existing)
    if new_data is None:
        console.print("[yellow]Abgebrochen — keine Änderungen.[/yellow]")
        raise typer.Exit(code=1)

    backup_path = backup_routes_file()
    doc = load_routes_doc()

    # Falls die ID geändert wurde, alte ID zum Ersetzen verwenden
    success = replace_route_in_doc(doc, route_id, new_data)
    if not success:
        console.print(f"[red]✗[/red] Konnte Route '{route_id}' nicht ersetzen.")
        raise typer.Exit(code=2)

    write_routes_doc(doc)

    console.print(f"\n[green]✓[/green] Route [bold]{new_data['id']}[/bold] aktualisiert.")
    if backup_path:
        console.print(f"[dim]  Backup: {backup_path.name}[/dim]")


# ------------------------------------------------------------------------------
#  route remove
# ------------------------------------------------------------------------------

@app.command("remove")
def cmd_remove(
    route_id: str = typer.Argument(..., help="Route-ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Ohne Rückfrage löschen."),
) -> None:
    """Eine Route löschen."""
    existing = find_route_by_id(route_id)
    if existing is None:
        console.print(f"[red]✗[/red] Route '{route_id}' nicht gefunden.")
        raise typer.Exit(code=1)

    console.print(
        f"Route [bold]{route_id}[/bold]: "
        f"{existing.get('label', '')}\n"
        f"  {existing.get('from_station')} → {existing.get('to_station')}, "
        f"{existing.get('scheduled_departure')}"
    )

    if not yes:
        confirmed = typer.confirm("Wirklich löschen?", default=False)
        if not confirmed:
            console.print("[yellow]Abgebrochen.[/yellow]")
            raise typer.Exit(code=1)

    backup_path = backup_routes_file()
    doc = load_routes_doc()
    remove_route_from_doc(doc, route_id)
    write_routes_doc(doc)

    console.print(f"[green]✓[/green] Route '{route_id}' gelöscht.")
    if backup_path:
        console.print(f"[dim]  Backup: {backup_path.name}[/dim]")


# ------------------------------------------------------------------------------
#  route migrate
# ------------------------------------------------------------------------------

@app.command("migrate")
def cmd_migrate(
    apply: bool = typer.Option(
        False, "--apply", help="Änderungen wirklich schreiben (sonst nur Dry-Run)."
    ),
) -> None:
    """Felder, die dem Default entsprechen, aus routes.toml entfernen.

    Default-Verhalten ist Dry-Run: Es wird nur angezeigt, was passieren würde.
    Mit --apply wird die Datei tatsächlich geschrieben (inkl. Backup).
    """
    try:
        doc = load_routes_doc()
    except FileNotFoundError:
        console.print("[yellow]Keine routes.toml vorhanden.[/yellow]")
        raise typer.Exit(code=0)

    routes_aot = doc.get("routes", [])
    diffs = []

    for route in routes_aot:
        route_id = route.get("id", "?")
        removable: list[tuple[str, object]] = []
        kept: list[tuple[str, object, object]] = []

        for field, default_value in ROUTE_DEFAULTS.items():
            if field in route:
                current = route[field]
                if current == default_value:
                    removable.append((field, current))
                else:
                    kept.append((field, current, default_value))

        if removable or kept:
            diffs.append({
                "id": route_id,
                "removable": removable,
                "kept_with_diff": kept,
            })

    print_migration_diff(diffs)

    if not any(d["removable"] for d in diffs):
        return

    if not apply:
        console.print(
            "\n[bold]Dry-Run.[/bold] Mit [cyan]--apply[/cyan] werden die "
            "Änderungen geschrieben."
        )
        return

    # Tatsächlich schreiben
    backup_path = backup_routes_file()
    for entry in diffs:
        route_id = entry["id"]
        for field, _ in entry["removable"]:
            for r in routes_aot:
                if r.get("id") == route_id and field in r:
                    del r[field]

    write_routes_doc(doc)

    total_removed = sum(len(d["removable"]) for d in diffs)
    console.print(
        f"\n[green]✓[/green] {total_removed} Default-Felder aus "
        f"{len(diffs)} Routen entfernt."
    )
    if backup_path:
        console.print(f"[dim]  Backup: {backup_path.name}[/dim]")


# ------------------------------------------------------------------------------
#  Entry-Point
# ------------------------------------------------------------------------------

def main() -> int:
    """Wird vom pyproject.toml-Entry-Point aufgerufen."""
    try:
        app()
        return 0
    except typer.Exit as e:
        return e.exit_code or 0


if __name__ == "__main__":
    sys.exit(main())