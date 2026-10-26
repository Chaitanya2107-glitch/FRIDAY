"""Run beside FRIDAY: python train_friday.py (or --help for scripted commands).

Reviewing teaches local memory and produces an optional dataset; it does not
fine-tune language-model weights. No provider or Telegram calls are made.
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from services.mind.reviews import reviews


def list_items(state="pending", kind="learning", grouped=True):
    items = reviews.queue(state, kind=kind, grouped=grouped)
    for row in items:
        when = datetime.fromtimestamp(row["at"]).strftime("%d %b %H:%M")
        text = row["question"].replace("\n", " ")[:100]
        repeats = f" | {row['count']} captures, showing latest" if row.get("count", 1) > 1 else ""
        print(f"#{row['id']} [{row['state']}] {row['kind']} | {when} | {text}{repeats}")
    if not items:
        print(f"No {state} {kind} items. Use list --kind nudge for optional notification feedback.")
    elif len(items) == 100:
        print("Showing the first 100; use show <id> to open an item.")


def show(item, context=False):
    row = reviews.get(item)
    shown = row if context else {k: row[k] for k in ("id", "kind", "question", "state", "answer", "live_answer", "teaching", "preferred", "notes", "delivery")}
    print(json.dumps(shown, indent=2, ensure_ascii=False))
    print(reviews.effect(item))
    return row


def yes(prompt):
    return input(prompt + " [y/N]: ").strip().lower() in {"y", "yes"}


def field(prompt, default=""):
    if default:
        print(f"Current: {default}")
    value = input(prompt + " (Enter keeps current; '-' clears): ").strip()
    return "" if value == "-" else value or default


def review(item, quick=False):
    row = show(item)
    print("Raw context and live answers stay local. Only the text you approve below can teach FRIDAY.")
    answer = field("Your reviewed answer/explanation", row["answer"] or row["live_answer"])
    teaching = field("What should she remember? Write a complete fact or preference",
                     row["teaching"] or (answer if quick and row["kind"] == "question" else ""))
    preferred = field("Optional preferred FRIDAY response", row["preferred"])
    if quick:
        approve = yes("Approve and apply this reviewed lesson now? (Dataset export stays off)")
        reviews.review(item, answer=answer, teaching=teaching, preferred=preferred, notes=row["notes"], approve=approve)
        if approve:
            reviews.train(item)
            print(reviews.effect(item))
        else:
            print("Draft saved; no learning applied.")
        return
    notes = field("Your review notes (kept local)", row["notes"])
    approve = yes("Approve this example?")
    exportable = approve and yes("Allow the original question/nudge and approved output in a local dataset export?")
    reviews.review(item, answer=answer, teaching=teaching, preferred=preferred, notes=notes,
                   approve=approve, exportable=exportable)
    print("Approved." if approve else "Draft saved; no learning applied.")
    if approve and yes("Apply it to FRIDAY's local learning now?"):
        reviews.train(item)
        print(reviews.effect(item))


def train_all():
    # Take a finite snapshot: new live questions are never swept into training.
    approved = reviews.list("approved", limit=10000)
    count = 0
    for row in approved:
        try:
            reviews.train(row["id"])
            count += 1
        except ValueError:
            print(f"Skipped #{row['id']}: approval changed.")
    print(f"Applied {count} approved local lessons. Model weights were not changed.")


def default_export():
    return reviews.path.parent / "exports" / f"friday-reviewed-{datetime.now():%Y%m%d-%H%M%S-%f}.jsonl"


def export(target):
    count = reviews.export(Path(target))
    print(f"Exported {count} approved examples to {target}" if count else
          "Nothing exported. Approve an example and allow dataset export during review first.")


def add(question, response):
    item = reviews.capture("example", question, {"origin": "manual"}, channel="manual")
    reviews.review(item, preferred=response)
    print(f"Saved example #{item} as a draft. Use review {item} to approve it.")
    return item


def interview_questions(topic="all"):
    """A local snapshot of her unasked questions, observations and today's check-in."""
    from services.activity.log import activity_log
    from services.mind import evening, thoughts, wonder, wording, talk
    from services.mind.lessons import key

    if topic not in {"all", "personal", "day"}:
        raise ValueError("Choose all, personal or day")
    now = datetime.now()
    day = now.date().isoformat()
    personal = set(wonder.next_questions(None, unasked_only=True))
    curiosity = set(wonder.load().get("questions", []))
    # Saved drafts should be reviewed, rather than asking for the same answer again.
    with reviews.db() as conn:
        answered = conn.execute(
            "SELECT question, context, at FROM reviews WHERE kind='question' AND state != 'rejected' "
            "AND (live_answer != '' OR answer != '')").fetchall()
    covered = {key(r["question"]) for r in answered
               if json.loads(r["context"]).get("day", datetime.fromtimestamp(r["at"]).date().isoformat()) == day}
    pending = talk.load().get("pending") or {}
    covered.add(key(pending.get("question", "")))
    rows, seen = [], set()
    for item in evening.collect(activity_log, now, extended=True, unlimited=True):
        category = "personal" if item.get("wondered") else "day"
        if topic != "all" and category != topic:
            continue
        if item.get("wondered") and item["wondered"] not in personal:
            continue
        question = wording.plain(item["raw"])
        identity = key(question)
        if identity in covered or identity in seen:
            continue
        seen.add(identity)
        thought = thoughts.get(item["thought"]) if item.get("thought") else None
        rows.append({**item, "question": question, "topic": category, "day": day,
                     "source": "curiosity" if item.get("wondered") in curiosity else
                               "starter" if item.get("wondered") else "observation" if thought else "day",
                     "observed_on": thought.at.date().isoformat() if thought else day,
                     "pattern": thought.data.get("pattern", "") if thought else "",
                     "subject": thought.subject if thought and thought.kind in {"unknown", "new"} else ""})
    return rows


def list_questions(topic="all"):
    rows = interview_questions(topic)
    for row in rows:
        print(f"[{row['source']}] {row['question']}")
    print(f"{len(rows)} available questions. Start with: session --topic {topic}")


def session(count=None, topic="all"):
    """A separate interview with no default count limit. Live pending state stays intact."""
    from services.mind import thoughts, wonder
    if count is not None and count < 1:
        raise ValueError("Choose a positive question count, or omit --count for no limit")
    questions = interview_questions(topic)[:count]
    if not questions:
        print("No unasked questions in this topic. Review saved answers in the learning queue.")
        return
    print("Local learning session. Enter skips; /stop finishes. Answers stay drafts until you approve them.")
    captured = []
    for row in questions:
        question = row["question"]
        label = f"[Observed {row['observed_on']}] " if row.get("thought") else ""
        answer = input(label + question + "\n> ").strip()
        if answer.lower() == "/stop":
            break
        if not answer:
            continue
        context = {"origin": "learning_session", "raw": row["raw"], "topic": row["topic"],
                   "day": row["day"], "thought_id": row.get("thought"),
                   "observed_on": row["observed_on"], "source": row["source"],
                   "pattern": row["pattern"], "subject": row["subject"]}
        item = reviews.capture("question", question, context, channel="manual")
        reviews.answer(item, answer, "answered")
        teaching = answer if row["topic"] == "personal" else (
            f"On {row['observed_on']}, Friday asked: {question} The Boss answered: {answer}")
        # Keep day-specific evidence dated; long replies can be distilled during review.
        reviews.review(item, answer=answer, teaching=teaching if len(teaching) <= 1000 else "")
        if row.get("wondered"):
            wonder.mark_asked(row["wondered"])
        if row.get("thought"):
            thoughts.mark_said(row["thought"])
        captured.append((item, row, answer))
        print(f"Saved answer #{item}.")
    if not captured:
        print("No new answers saved.")
        return
    print("\nAnswers to apply:")
    for item, row, answer in captured:
        print(f"#{item} {row['question']}\n  {answer}")
    applicable = [(item, row, answer) for item, row, answer in captured if reviews.get(item)["teaching"]]
    if len(applicable) < len(captured):
        print("Long answers are saved in full as drafts; review them to choose concise facts to remember.")
    if not applicable:
        return
    if yes("Approve and apply these answers to local memory? (Dataset export remains off)"):
        for item, row, answer in applicable:
            reviews.review(item, answer=answer, teaching=reviews.get(item)["teaching"], approve=True)
            reviews.train(item)
            if row.get("wondered"):
                wonder.mark_answered(row["wondered"], answer)
        print(f"Applied {len(applicable)} local answers. No model calls or weight changes.")
    else:
        print("Drafts saved; review them later to apply learning.")


def interactive():
    print("FRIDAY manual training | local learning + optional dataset export")
    print(f"Queue: {reviews.path}")
    print("Keep FRIDAY running in her tray. This tool never consumes her pending live question.")
    while True:
        print("\n[l] Learning queue  [i] Unasked questions  [g] Day/personal interview  [n] Grouped nudges  [v] All  [s] Show  [r] Review  [f] Nudge feedback  [a] Add example  [t] Train approved  [e] Export  [q] Quit")
        choice = input("> ").strip().lower()
        try:
            if choice in {"q", "quit", "exit"}:
                return
            if choice in {"l", "list", ""}:
                list_items()
            elif choice == "v":
                list_items("all", kind="all")
            elif choice == "n":
                list_items(kind="nudge")
            elif choice == "g":
                session(topic=input("Topic: all / day / personal (Enter = all): ").strip().lower() or "all")
            elif choice == "i":
                list_questions()
            elif choice == "f":
                item = int(input("Nudge ID: ").strip().lstrip("#"))
                rating = input("useful / badly_timed / too_frequent / incorrect: ").strip()
                minutes = int(input("Snooze/minimum interval in minutes (Enter = 60): ").strip() or "60")
                print(reviews.feedback(item, rating, minutes))
            elif choice in {"s", "r"}:
                item = int(input("Item ID: ").strip().lstrip("#"))
                show(item) if choice == "s" else review(item, quick=True)
            elif choice == "a":
                question = input("User question: ").strip()
                response = input("Desired FRIDAY answer: ").strip()
                if not question or not response:
                    raise ValueError("Both question and desired answer are required")
                review(add(question, response), quick=True)
            elif choice == "t":
                train_all()
            elif choice == "e":
                export(field("New dataset path", str(default_export())))
            else:
                print("Choose one of the menu letters.")
        except (ValueError, OSError, sqlite3.Error) as error:
            print(f"Could not complete that operation: {error}")


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command")
    listing = commands.add_parser("list", help="List queued examples")
    listing.add_argument("--state", choices=["pending", "approved", "trained", "rejected", "all"], default="pending")
    listing.add_argument("--kind", choices=["learning", "all", "question", "nudge", "example"], default="learning")
    listing.add_argument("--ungrouped", action="store_true", help="Show every nudge capture instead of grouped repeats")
    for name in ("show", "review", "reject", "withdraw"):
        command = commands.add_parser(name)
        command.add_argument("id", type=int)
        if name == "show":
            command.add_argument("--context", action="store_true", help="Include the full captured context")
        if name == "review":
            command.add_argument("--quick", action="store_true", help="Review and apply with one approval; leave dataset export off")
    approval = commands.add_parser("approve", help="Approve reviewed text without applying it")
    approval.add_argument("id", type=int)
    for name in ("answer", "teaching", "preferred", "notes"):
        approval.add_argument("--" + name)
    approval.add_argument("--exportable", action="store_true", help="Permit question and approved output in dataset")
    approval.add_argument("--apply", action="store_true", help="Apply the reviewed lesson immediately after approval")
    feedback = commands.add_parser("feedback", help="Change a nudge's local delivery behavior")
    feedback.add_argument("id", type=int)
    feedback.add_argument("rating", choices=["useful", "badly_timed", "too_frequent", "incorrect"])
    feedback.add_argument("--minutes", type=int, default=60)
    inbox = commands.add_parser("questions", help="Show her unasked questions and day observations")
    inbox.add_argument("--topic", choices=["all", "day", "personal"], default="all")
    interview = commands.add_parser("session", help="Local day/personal interview; no question limit by default")
    interview.add_argument("--count", type=int, help="Optional positive session size; omit for every available question")
    interview.add_argument("--topic", choices=["all", "day", "personal"], default="all")
    train = commands.add_parser("train", help="Apply approved lessons to local memory")
    selection = train.add_mutually_exclusive_group(required=True)
    selection.add_argument("--id", type=int)
    selection.add_argument("--all-approved", action="store_true")
    exporting = commands.add_parser("export", help="Write opted-in approved examples as chat JSONL")
    exporting.add_argument("path", type=Path, nargs="?")
    adding = commands.add_parser("add", help="Add a manual question/desired answer as a draft")
    adding.add_argument("--question", required=True)
    adding.add_argument("--response", required=True)
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command is None:
            interactive()
        elif args.command == "list":
            list_items(args.state, args.kind, not args.ungrouped)
        elif args.command == "show":
            show(args.id, args.context)
        elif args.command == "review":
            review(args.id, args.quick)
        elif args.command == "approve":
            row = reviews.get(args.id)
            fields = {name: getattr(args, name) if getattr(args, name) is not None else row[name]
                      for name in ("answer", "teaching", "preferred", "notes")}
            reviews.review(args.id, **fields, approve=True, exportable=args.exportable)
            if args.apply:
                reviews.train(args.id)
                print(reviews.effect(args.id))
            else:
                print(f"Approved #{args.id}; use train --id {args.id} to apply it.")
        elif args.command == "feedback":
            print(reviews.feedback(args.id, args.rating, args.minutes))
        elif args.command == "session":
            session(args.count, args.topic)
        elif args.command == "questions":
            list_questions(args.topic)
        elif args.command == "reject":
            reviews.reject(args.id)
            print(f"Rejected #{args.id}; excluded from learning and export.")
        elif args.command == "withdraw":
            row = reviews.get(args.id)
            reviews.review(args.id, **{name: row[name] for name in ("answer", "teaching", "preferred", "notes")})
            print(f"Withdrew #{args.id}; returned to pending and removed from active lessons.")
        elif args.command == "train":
            if args.all_approved:
                train_all()
            else:
                reviews.train(args.id)
                print(reviews.effect(args.id))
        elif args.command == "export":
            export(args.path or default_export())
        elif args.command == "add":
            add(args.question, args.response)
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f"Could not complete that operation: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nReview tool closed. FRIDAY keeps running.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
