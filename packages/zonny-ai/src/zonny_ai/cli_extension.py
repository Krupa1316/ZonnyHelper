"""zonny-ai CLI extension.

When zonny-ai is installed, this module is loaded by zonny-core's entry-point
hook and attaches AI-powered sub-commands to the existing core Typer app.
No code in zonny-ai imports from zonny-core internals â€” communication happens
exclusively through the .zonny/ shared-state directory.
"""
from __future__ import annotations

import typer


def attach(app: typer.Typer) -> None:
    """Called by zonny-core at startup if zonny-ai is installed.

    Adds AI-powered commands to the existing deploy, git, and tree groups.
    """
    from zonny_ai.git.commands import app as ai_git_app
    from zonny_ai.deploy.commands import app as ai_deploy_app
    from zonny_ai.tree.commands import app as ai_tree_app

    # Attach as nested sub-apps (e.g. `zonny git commit` becomes available)
    app.add_typer(ai_git_app,    name="git-ai",    hidden=True)
    app.add_typer(ai_deploy_app, name="deploy-ai", hidden=True)
    app.add_typer(ai_tree_app,   name="tree-ai",   hidden=True)

    # Merge AI commands directly into the existing groups for clean UX
    # The merge is done by registering the commands on the parent groups
    _merge_into_existing(app, "git",    ai_git_app)
    _merge_into_existing(app, "deploy", ai_deploy_app)
    _merge_into_existing(app, "tree",   ai_tree_app)


def _merge_into_existing(root: typer.Typer, group_name: str, extension: typer.Typer) -> None:
    """Add commands from ``extension`` into the named sub-typer of ``root``."""
    for group in root.registered_groups:
        if group.typer_instance and group.name == group_name:
            for cmd in extension.registered_commands:
                group.typer_instance.registered_commands.append(cmd)
            return
