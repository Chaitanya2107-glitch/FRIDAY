"""Verified project setup using existing brief checkpoints and an observed Explorer folder."""

import os
import sqlite3
import time
from pathlib import Path

import comtypes
import comtypes.client

from core.config import config
from core.logger import logger
from services.automation.results import ActionResult
from services.mind.execution import ExecutionEngine
from services.mind.project_session import ProjectSessionEngine
from services.mind.workspace import workspace


class ExplorerDesktop:
    @staticmethod
    def find_folder(folder):
        # Shell.Windows/FolderItem.Path provide the actual location, not a title guess.
        comtypes.CoInitialize()
        try:
            for window in comtypes.client.CreateObject("Shell.Application", dynamic=True).Windows():
                try:
                    location = Path(window.Document.Folder.Self.Path)
                    if location.is_absolute() and location.resolve() == Path(folder).resolve():
                        return {"path": str(location.resolve()), "hwnd": int(window.HWND)}
                except (OSError, ValueError, AttributeError, comtypes.COMError):
                    continue
        except (OSError, comtypes.COMError) as error:
            raise ValueError("Explorer could not be inspected. Completion was not verified.") from error
        finally:
            comtypes.CoUninitialize()
        return None

    def open_folder(self, folder, *, active):
        if not active():
            raise ValueError("The execution stopped before opening the project folder.")
        os.startfile(str(folder), "explore")
        deadline = time.monotonic() + 8
        while active() and time.monotonic() < deadline:
            if found := self.find_folder(folder):
                return found
            time.sleep(.2)
        return None


class ProjectExecutionEngine(ProjectSessionEngine):
    workflow = "project_execution"
    phases = ProjectSessionEngine.phases + ("Open and verify project folder",)
    external_phases = frozenset({4})

    def __init__(self, task_workspace, output_dir, *, desktop=None):
        super().__init__(task_workspace, output_dir)
        self.desktop = desktop or ExplorerDesktop()
        from services.mind.executive import ExecutiveControl
        self.executive = ExecutiveControl(task_workspace.store)

    def _brief_verified(self, row):
        # The brief is published before the desktop phase completes the execution.
        return ExecutionEngine._verified(self, {**row, "state": "completed"})

    def _validate_source(self, conn, row):
        super()._validate_source(conn, row)
        if row["cursor"] >= 4 and not self._brief_verified(row):
            raise ValueError("The prepared brief is missing or changed. Start a new project session.")

    def _perform_external(self, row, *, recovering, active):
        from services.automation.intent import remote_request
        self.executive.assess_project(self, row, active=active, remote=remote_request.get())
        def permitted():
            if remote_request.get() or not active():
                return False
            try:
                with self.workspace._db() as conn:
                    self._validate_source(conn, row)
                return True
            except (ValueError, OSError):
                return False
        folder = row["payload"]["project"]["path"]
        found = self.desktop.find_folder(folder)
        if not found:
            if recovering:
                raise ValueError("The previous folder-open outcome is uncertain. Nothing was repeated. "
                                 "Open the saved project folder and resume, or start a new project session.")
            found = self.desktop.open_folder(folder, active=permitted)
        # A launch return alone cannot establish completion; observe independently.
        observed = self.desktop.find_folder(folder)
        if not found or not observed or not observed.get("hwnd") or Path(observed["path"]).resolve() != Path(folder).resolve():
            raise ValueError("The project folder was not observed in Explorer. Completion was not verified.")
        return {"folder_window": observed}

    def _verified(self, row):
        # Pure local verification can also be used inside a transaction. Desktop
        # observation belongs in get(), after the database connection is released.
        return bool(super()._verified(row) and row["payload"].get("folder_window"))

    def get(self, ident):
        row = super().get(ident)
        if not row["verified"]:
            return row
        try:
            row["verified"] = bool(self.desktop.find_folder(row["payload"]["project"]["path"]))
        except (ValueError, OSError):
            row["verified"] = False
        return row

    def run(self, ident, *, resume=False):
        try:
            row = self.get(ident)
            if row["state"] == "completed":
                return row  # historical completion never authorizes a new desktop action
            return super().run(ident, resume=resume)
        finally:
            self._record_outcome(ident)

    def cancel(self, ident):
        row = super().cancel(ident)
        self._record_outcome(ident)
        return row

    def _record_outcome(self, ident):
        try:
            self.executive.outcome(self.get(ident))
        except (OSError, ValueError, sqlite3.Error) as error:
            # Canonical checkpoint receipts survive a secondary working-memory failure.
            logger.warning("Executive execution feedback unavailable: %s", type(error).__name__)


executions = ProjectExecutionEngine(workspace, config.MEMORY_DIR / "project-executions")


def run_command(parsed, *, remote=False):
    if remote:
        return ActionResult(False, "Project execution is available at the laptop only.", repeatable=False)
    try:
        engine, action = executions, parsed["action"]
        if action == "start":
            ident = engine.create(parsed["reference"])
            engine.workspace.focus("project_execution", ident)
            row = engine.run(ident)
        else:
            ident = engine.workspace.resolve("project_execution", parsed.get("reference", "current"))["id"]
            engine.workspace.focus("project_execution", ident)
            if action == "cancel":
                row = engine.cancel(ident)
            elif action == "resume":
                row = engine.run(ident, resume=True)
            else:
                row = engine.get(ident)
        text = f'Project session for "{row["payload"]["project"]["name"]}": {row["state"]} ({row["cursor"]}/{len(engine.phases)} steps).'
        if row["verified"]:
            text += f' Verified brief and project folder. Brief: {row["artifact"]}'
        elif row["state"] == "completed":
            text += " Completed earlier; the brief or open folder is no longer currently verified. Start a new session to reopen."
        elif row["state"] in {"pending", "blocked"}:
            text += " " + (row["error"] or "An execution step is pending or owned by another worker.")
            text += " Say 'resume project session' to check and continue."
        success = row["verified"] or (action in {"status", "cancel"} and row["state"] in {"pending", "cancelled"})
        return ActionResult(success, text, memory_message=f'Local project execution: {row["state"]}.', repeatable=False)
    except (ValueError, OSError, sqlite3.Error) as error:
        logger.warning("Project execution unavailable: %s", type(error).__name__)
        text = str(error) if isinstance(error, ValueError) else "The local execution store is unavailable. Completion was not verified."
        return ActionResult(False, text, repeatable=False)
