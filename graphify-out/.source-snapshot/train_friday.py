"""Review Friday's saved predictions. Your verification automatically teaches future guesses.

Run beside FRIDAY: python train_friday.py. No provider calls or manual training step.
"""
import argparse
import sqlite3
import sys

from services.mind import prediction_review as predictions, wording


def show(item):
    row = predictions.get(item)
    print(f"\n#{row['id']} | {row['at']} | {row['verdict'] or ('previously answered' if row['state'] == 'answered' else 'pending')}")
    print(wording.plain({**row["data"], "kind": "prediction"}))
    if row["actual_app"]:
        print(f"Your actual next app: {row['actual_app']}")
    if row["notes"]:
        print(f"Your notes: {row['notes']}")
    return row


def list_items(state="pending"):
    rows = predictions.queue(state)
    for row in rows:
        print(f"#{row['id']} | {row['at']} | {row['verdict'] or row['state']} | "
              + wording.plain({**row["data"], "kind": "prediction"}))
    if not rows:
        print(f"No {state} predictions. Keep FRIDAY running so she can observe your activity and make predictions.")
    return rows


def apply(item, verdict, actual_app="", notes=""):
    changed = predictions.verify(item, verdict, actual_app=actual_app, notes=notes)
    print("Verification saved. Future guesses learn automatically; the nightly model uses eligible feedback."
          if changed else "Left pending. Unsure does not train Friday.")


def review(item):
    row = show(item)
    if row["verdict"] or row["state"] == "answered":
        print("Already verified; no training repeated.")
        return
    while True:
        choice = input("Correct / wrong / unsure (c/w/u, Enter skips, /stop finishes): ").strip().lower()
        if choice == "/stop":
            return "stop"
        verdict = {"c": "correct", "w": "wrong", "u": "unsure", "": "unsure"}.get(choice, choice)
        if verdict in {"correct", "wrong", "unsure"}:
            break
        print("Choose correct, wrong or unsure.")
    actual_app = ""
    if verdict == "wrong" and row["data"].get("context", {}).get("thing", "").startswith("app:"):
        actual_app = input("Actual next app, e.g. spotify (optional; Enter leaves unknown): ").strip()
    apply(item, verdict, actual_app)


def session(count=None):
    if count is not None and count < 1:
        raise ValueError("Choose a positive prediction count")
    rows = predictions.queue()[:count]
    if not rows:
        list_items()
        return
    print("Review saved predictions. Each definite verification teaches Friday immediately; Enter skips.")
    for row in rows:
        try:
            if review(row["id"]) == "stop":
                break
        except ValueError as error:
            print(f"Could not verify #{row['id']}: {error}")


def interactive():
    print("TRAIN FRIDAY | prediction verification")
    print("Verify what Friday predicted. No separate approve or train step.")
    list_items()
    while True:
        print("\n[l] Pending predictions  [r] Review session  [s] Show prediction  [h] History  [q] Quit")
        choice = input("> ").strip().lower()
        try:
            if choice in {"q", "quit", "exit"}:
                return
            if choice in {"l", "list"}:
                list_items()
            elif choice in {"r", "review", ""}:
                session()
            elif choice == "h":
                list_items("verified")
            elif choice == "s":
                show(int(input("Prediction ID: ").strip().lstrip("#")))
            else:
                print("Choose one of the menu letters.")
        except (ValueError, OSError, sqlite3.Error) as error:
            print(f"Could not complete that operation: {error}")


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command")
    listing = commands.add_parser("list", help="List saved predictions only")
    listing.add_argument("--state", choices=["pending", "verified", "all"], default="pending")
    showing = commands.add_parser("show", help="Show the original prediction and verification")
    showing.add_argument("id", type=int)
    reviewing = commands.add_parser("review", help="Verify a saved prediction; learning applies automatically")
    reviewing.add_argument("id", type=int)
    reviewing.add_argument("--verdict", choices=["correct", "wrong", "unsure"])
    reviewing.add_argument("--actual-app", default="", help="Optional actual next app for a wrong app prediction")
    reviewing.add_argument("--notes", default="", help="Optional local verification notes")
    reviewing = commands.add_parser("session", help="Review pending predictions one at a time")
    reviewing.add_argument("--count", type=int, help="Optional positive session size")
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command is None:
            interactive()
        elif args.command == "list":
            list_items(args.state)
        elif args.command == "show":
            show(args.id)
        elif args.command == "review":
            if args.verdict:
                apply(args.id, args.verdict, args.actual_app, args.notes)
            elif args.actual_app or args.notes:
                raise ValueError("Use --verdict when supplying --actual-app or --notes")
            else:
                review(args.id)
        elif args.command == "session":
            session(args.count)
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f"Could not complete that operation: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nReview tool closed. Saved verifications are retained; FRIDAY keeps running.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
