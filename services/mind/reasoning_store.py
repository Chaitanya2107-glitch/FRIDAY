"""Durable owner evidence and revisable conclusions. Inferences never become facts."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from core.config import config
from core.logger import logger
from services.mind.cognition import cognition, redact


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class ReasoningStore:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def _db(self):
        with self.store._lock, self.store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS reasoning_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, quote TEXT NOT NULL, certainty TEXT NOT NULL,
                noted TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)""")
            db.execute("""CREATE TABLE IF NOT EXISTS reasoning_conclusions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL, refs TEXT NOT NULL,
                noted TEXT NOT NULL, status TEXT NOT NULL, outcome TEXT NOT NULL DEFAULT '')""")
            yield db

    def facts(self):
        with self._db() as db:
            rows = db.execute("SELECT * FROM reasoning_facts WHERE active = 1 ORDER BY id DESC").fetchall()
        return [{"id": f"reasoning_fact:{row['id']}", "quote": redact(row["quote"]),
                 "certainty": row["certainty"], "noted": row["noted"]} for row in rows]

    def evidence(self):
        from services.mind.workspace import Workspace
        from services.memory.semantic import semantic_memory
        from services.proactive import timetable
        known = {f["id"]: {"kind": "owner_fact", **f} for f in self.facts()}
        path = Path(semantic_memory.db_path)
        if path.exists():
            with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table, prefix in (("memories", "memory"), ("schedule_facts", "schedule")):
                    if table not in tables: continue
                    source = "source" if table == "memories" else "'told'"
                    for ident, text, noted, origin in db.execute(
                            f"SELECT id, text, created_at, {source} FROM {table} ORDER BY id DESC LIMIT 20"):
                        if origin == "episode": continue
                        known[f"{prefix}:{ident}"] = {"kind": "owner_fact" if origin == "told" else "learned_guess",
                                                       "quote": redact(text[:1200]), "noted": noted,
                                                       "certainty": "confirmed" if origin == "told" else "uncertain"}
        work = Workspace(self.store)
        for kind, rows in (("goal", work.goals()), ("task", work.tasks())):
            for row in rows[:5]:
                known[f"{kind}:{row['id']}"] = json.loads(redact(json.dumps({"kind": kind, **row})))
        # Explicit attention must not disappear behind the five newest records.
        with work._db() as conn:
            for focus in conn.execute("SELECT kind,target FROM workspace_focus WHERE scope='local' AND kind IN ('task','goal')"):
                kind, ident = focus["kind"], focus["target"]
                table = {"task": "workspace_tasks", "goal": "workspace_goals"}[kind]
                selected = conn.execute(f"SELECT * FROM {table} WHERE id=?", (ident,)).fetchone()
                if selected and f"{kind}:{ident}" not in known:
                    value = work._task(conn, ident) if kind == "task" else dict(selected)
                    known[f"{kind}:{ident}"] = json.loads(redact(json.dumps({"kind": kind, **value})))
        reminder_path = Path(config.MEMORY_DB_PATH)
        if reminder_path.exists():
            with sqlite3.connect(reminder_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='reminders'").fetchone():
                    for ident, text, due in db.execute("SELECT id, text, due_at FROM reminders WHERE delivered_at IS NULL ORDER BY due_at LIMIT 10"):
                        known[f"reminder:{ident}"] = {"kind": "reminder", "text": redact(text[:500]), "due_at": due}
        known["timetable"] = {"kind": "weekly_template", "classes": timetable.load()[:40]}
        from services.proactive.deadline_changes import current
        for deadline in current():
            if deadline.get("id"):
                known[f"deadline:{deadline['id']}"] = {"kind": "deadline", "source": "owner_report", **deadline}
        for event in self.store.recent(20):
            if event["public"] and event["kind"] in {"observation", "notification", "reaction", "action"}:
                known[f"event:{event['id']}"] = {"kind": event["kind"], "status": event["status"],
                                               "text": event["text"][:500]}
        from services.mind.executive import execution_evidence
        from services.mind.brain_memory import BrainMemory
        from services.mind.cognition_context import operational_state
        known['runtime:current'] = operational_state()
        from services.mind import thoughts
        for thought in thoughts.unsaid_on(None)[:5]:
            known[f'thought:{thought.id}'] = {'kind': 'observation', 'thought_id': thought.id,
                'source': 'observed_pattern_or_hypothesis', 'thought_kind': thought.kind,
                'subject': thought.subject, 'data': thought.data, 'noted': thought.at.isoformat()}
        from services.mind.temporal_memory import TemporalMemory
        known.update(TemporalMemory(self.store).evidence())
        recent_episodes = BrainMemory(self.store).evidence()
        known.update(recent_episodes)
        from services.mind.consolidation import Consolidation
        memory = Consolidation(self.store)
        for ref, source in memory.source_evidence().items():
            if ref not in known:
                known[ref] = source
            elif source.get('memory_replacements'):
                known[ref]['memory_replacements'] = source['memory_replacements']
        TemporalMemory(self.store).annotate_history(known)
        known.update(execution_evidence(self.store))
        from services.mind.outcome_learning import OutcomeLearning
        known.update(OutcomeLearning(self.store).evidence())
        from services.mind.inquiry import Inquiry
        known.update(Inquiry(self.store).evidence())
        known.update(memory.evidence(limit=2))
        from services.mind.recall import focused
        recalled = {}
        for row in focused(BrainMemory(self.store), known):
            ref = row['id']
            recalled[ref] = {**known.get(ref, {}), **row,
                             **({'historical_recall': True} if ref not in recent_episodes else {})}
        # Current facts/priorities stay first; relevant originals precede recent chatter.
        episodes = {ref: value for ref, value in known.items() if value.get('kind') in {'owner_message', 'owner_answer'}}
        return {**{ref: value for ref, value in known.items() if ref not in episodes},
                **recalled, **{ref: value for ref, value in episodes.items() if ref not in recalled}}

    def save(self, report, now, known, *, guard=None, finalize=None):
        mapping = {}
        claims = []
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if guard:
                guard(db)
            from services.mind.temporal_memory import TemporalMemory
            TemporalMemory(self.store).save(db, report.situations, now, known)
            from services.mind.consolidation import Consolidation
            Consolidation(self.store).save(db, report.memories, now, known)
            for fact in report.facts:
                for old in fact.supersedes:
                    db.execute("UPDATE reasoning_facts SET active = 0 WHERE id = ?", (int(old.split(":")[1]),))
                ident = db.execute("INSERT INTO reasoning_facts (quote, certainty, noted) VALUES (?, ?, ?)",
                                   (redact(fact.quote), fact.certainty, now.isoformat())).lastrowid
                mapping[fact.id] = f"reasoning_fact:{ident}"
                known[mapping[fact.id]] = {"kind": "owner_fact", "id": mapping[fact.id], "quote": redact(fact.quote),
                                          "certainty": fact.certainty, "noted": now.isoformat()}
            for claim in report.conclusions:
                body = claim.model_dump()
                body["evidence"] = [mapping.get(ref, ref) for ref in claim.evidence]
                refs = {key: fingerprint(known[key]) for key in body["evidence"]}
                status = "inferred" if body["effect"]["type"] == "guidance" else "proposed"
                ident = db.execute("INSERT INTO reasoning_conclusions (body, refs, noted, status) VALUES (?, ?, ?, ?)",
                                   (redact(json.dumps(body)), json.dumps(refs), now.isoformat(), status)).lastrowid
                claims.append(ident)
            # Bound derived history; owner facts are retained until correction/forgetting.
            db.execute("DELETE FROM reasoning_conclusions WHERE status <> 'applied' AND id IN "
                       "(SELECT id FROM reasoning_conclusions ORDER BY id DESC LIMIT -1 OFFSET 200)")
            if finalize:
                finalize(db)
        return claims

    def conclusions(self, now, known=None, include_future=False, include_expired=False):
        known = self.evidence() if known is None else known
        with self._db() as db:
            rows = db.execute("SELECT * FROM reasoning_conclusions WHERE status = 'applied' OR id IN "
                              "(SELECT id FROM reasoning_conclusions ORDER BY id DESC LIMIT 200) ORDER BY id DESC").fetchall()
        active = []
        for row in rows:
            body, refs = json.loads(row["body"]), json.loads(row["refs"])
            if row["status"] in {"rejected", "failed", "applying"}: continue
            if body["start"] and ((not include_expired and body["end"] < now.date().isoformat()) or
                                  (not include_future and body["start"] > now.date().isoformat())): continue
            if any(key not in known or fingerprint(known[key]) != stamp for key, stamp in refs.items()): continue
            active.append({**body, "id": row["id"], "noted": row["noted"], "status": row["status"],
                           "outcome": row["outcome"], "source_fingerprints": refs})
        return active

    def get(self, ident, now):
        return next((c for c in self.conclusions(now, include_future=True) if c["id"] == ident), None)

    def claim(self, ident):
        """Consume one approval across processes; interrupted work cannot replay."""
        with self._db() as db:
            return db.execute("UPDATE reasoning_conclusions SET status = 'applying' WHERE id = ? AND status = 'proposed'",
                              (ident,)).rowcount == 1

    def finish(self, ident, status, outcome=""):
        with self._db() as db:
            db.execute("UPDATE reasoning_conclusions SET status = ?, outcome = ? WHERE id = ?",
                       (status, redact(outcome), ident))

    def context(self, now=None):
        now = now or datetime.now()
        try:
            from services.mind.temporal_memory import TemporalMemory
            from services.mind.outcome_learning import OutcomeLearning
            from services.mind.consolidation import Consolidation
            known = self.evidence()
            return {"facts": self.facts()[:15], "conclusions": self.conclusions(now, known=known, include_future=True)[:8],
                    'situation': TemporalMemory(self.store).snapshot(now, limit=4),
                    'action_outcomes': OutcomeLearning(self.store).context(),
                    'memories': list(Consolidation(self.store).evidence(limit=2).values()),
                    'historical_recall': [row for row in known.values() if row.get('historical_recall')]}
        except (OSError, sqlite3.Error, ValueError) as error:
            logger.warning("Reasoning context unavailable: %s", type(error).__name__)
            return {"status": "unavailable", "facts": [], "conclusions": []}

    def remembered(self):
        return [(f["quote"], f["noted"][:10]) for f in self.facts()]

    def forget(self, description):
        if len(description.strip()) < 3: return None
        with self._db() as db:
            found = [dict(row) for row in db.execute("SELECT id, quote FROM reasoning_facts")
                     if description.casefold() in row["quote"].casefold()]
            for fact in found:
                db.execute("DELETE FROM reasoning_facts WHERE id = ?", (fact["id"],))
            if found:
                from services.mind.executive import clear_derived
                clear_derived(db)
        if not found: return None
        # Explicit remember commands may also have saved the same owner quote in
        # semantic memory. Remove literal matches there without an embedding call.
        from services.memory.semantic import semantic_memory
        path = Path(semantic_memory.db_path)
        if path.exists():
            with sqlite3.connect(path, timeout=1) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='memories'").fetchone():
                    for ident, text in db.execute("SELECT id, text FROM memories WHERE source = 'told'").fetchall():
                        if description.casefold() in text.casefold():
                            db.execute("DELETE FROM memories WHERE id = ?", (ident,))
            semantic_memory._cache = None
        return found[0]["quote"]

    def forget_all(self):
        with self._db() as db:
            count = db.execute("DELETE FROM reasoning_facts").rowcount
            db.execute("DELETE FROM reasoning_conclusions")
            from services.mind.executive import clear_derived
            clear_derived(db)
        return count


reasoning_store = ReasoningStore(cognition)
