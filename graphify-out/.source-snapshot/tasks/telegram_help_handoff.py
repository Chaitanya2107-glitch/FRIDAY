"""Reuse the Telegram verification/reload workflow for the /h addition."""
import sys
import telegram_upgrade_handoff as handoff

handoff.RECEIPT = handoff.ROOT / "tasks/telegram-help-verification.json"
handoff.SNAPSHOT = handoff.ROOT / "tasks/telegram-help-sources.json"
handoff.TESTS = handoff.ROOT / "tasks/telegram-help-tests.xml"

if __name__ == "__main__":
    {"snapshot": handoff.snapshot, "receipt": handoff.receipt, "activate": handoff.activate}[sys.argv[1]]()
