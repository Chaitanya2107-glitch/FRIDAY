"""Bounded real Explorer trial with temporary sources; never touches saved owner projects."""
import json
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.logger import logger
for handler in list(logger.handlers):
    if isinstance(handler, logging.FileHandler):
        logger.removeHandler(handler)
        handler.close()

import comtypes
import comtypes.client
from services.activity import projects
from services.memory import notes
from services.proactive import deadlines
from services.mind.cognition import Cognition, cognition
from services.mind.workspace import Workspace
from services.mind.project_execution import ExplorerDesktop, ProjectExecutionEngine

with tempfile.TemporaryDirectory(prefix="friday-execution-trial-") as temporary:
    root = Path(temporary)
    cognition.path = root / "cognition.db"
    folder = root / "trial-project"
    folder.mkdir()
    (folder / "README.md").write_text("Temporary execution trial.", encoding="utf-8")
    projects.path, notes.path, deadlines.path = root / "projects.json", root / "notes.json", root / "deadlines.json"
    projects.path.write_text(json.dumps({"execution trial": {"path": str(folder)}}), encoding="utf-8")
    engine = ProjectExecutionEngine(Workspace(Cognition(root / "cognition.db")), root / "briefs")
    try:
        row = engine.run(engine.create("execution trial"))
        result = {"state": row["state"], "verified": row["verified"], "steps": row["cursor"],
                  "evidence_count": len(row["evidence"]), "error": row["error"],
                  "folder_observed": bool(ExplorerDesktop.find_folder(folder)),
                  "assessment_recorded": "Last assessment: proceed" in engine.executive.describe(),
                  "outcome_recorded": "verified: True" in engine.executive.describe()}
        print(json.dumps(result))
        assert result["verified"] and result["steps"] == 5, result
    finally:
        # Only the window showing this unique temporary directory belongs to the probe.
        comtypes.CoInitialize()
        try:
            for window in comtypes.client.CreateObject("Shell.Application", dynamic=True).Windows():
                try:
                    if Path(window.Document.Folder.Self.Path).resolve() == folder.resolve():
                        window.Quit()
                except (AttributeError, OSError, ValueError, comtypes.COMError):
                    pass
        finally:
            comtypes.CoUninitialize()
