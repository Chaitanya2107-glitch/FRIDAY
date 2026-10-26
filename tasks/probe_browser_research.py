"""Real local-model + browser + Scrapling + report pipeline on controlled sources."""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import config
from services.browser import research, service
from services.browser.commands import Command
from services.browser.models import Observation
from services.browser.runtime import BrowserControls
from services.browser.worker import ProcessRuntime
from services.search.web_search import SearchResult

PAGES = {
    "pid": "<title>PID control fixture</title><main><h1>PID control</h1><p>PID uses proportional, integral and derivative feedback. "
           "Its gains are tuned to the controlled system. A known reference and measured error guide the controller. "
           "Performance depends on tuning and system dynamics. These are controlled development test statements.</p></main>",
    "rl": "<title>Learning control fixture</title><main><h1>Reinforcement learning</h1><p>Reinforcement learning learns a policy from rewards. "
          "Training requires interaction data and a defined reward. Simulation can reduce real-world exploration. "
          "Policies still require safety validation. These are controlled development test statements.</p></main>",
}


class ResearchFixture(BrowserControls):
    def start(self, headless):
        result = super().start(headless)
        self.context.route("https://example.com/friday-research/*", lambda route: route.fulfill(
            status=200, content_type="text/html", body=PAGES[route.request.url.rsplit("/", 1)[-1]]))
        return result


class FixtureRuntime(ProcessRuntime):
    def __init__(self, stopped, downloads):
        super().__init__(ResearchFixture, (downloads,), stopped, browser_tree=True, timeout=35)


async def main():
    config.MEMORY_DIR = ROOT / "tasks" / "browser-research-probe"
    config.AI_LANGUAGE_ENABLED = config.BROWSER_AUTOMATION_ENABLED = True
    service.BrowserRuntime = FixtureRuntime
    research._search = lambda query: [SearchResult(name, "https://example.com/friday-research/" + name, "") for name in PAGES]
    manager = service.AutomationService()
    reply = await manager.handle("research headless compare PID control and reinforcement learning", "ollama")
    assert reply.success
    await manager.task
    job = manager.job
    assert job.report_path and job.report_path.is_file(), manager.status().message
    assert job.source_count == 2
    report = job.report_path.read_text(encoding="utf-8")
    assert "## Sources" in report and "https://example.com/friday-research/pid" in report
    assert "## Findings" in report, report
    # Also exercise the real installed model's supervised action interpretation.
    proposal_job = service.Job(Command("browser", "Type exactly robot control into the Search field."), "ollama")
    proposal_job.observation = Observation("https://example.com", "Fixture", "Search field available.",
        [{"id": 1, "kind": "input", "name": "Search", "type": "text", "value": "", "protected": False}])
    step = await manager._plan(proposal_job)
    assert step.action == "fill" and step.target == 1 and step.value == "robot control"
    result = {"state": job.state, "sources": job.source_count, "local_synthesis_grounded": True,
              "local_action_proposal_validated": True, "report": str(job.report_path.relative_to(ROOT)),
              "network": "controlled browser fixtures; Ollama only"}
    (ROOT / "tasks" / "browser-automation-research.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
