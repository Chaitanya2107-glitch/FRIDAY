"""Readable plain-text reports without Telegram Markdown escaping."""

import re


def section(title: str, body: str | list[str]) -> str:
    lines = body.splitlines() if isinstance(body, str) else body
    items = [f"• {line.strip()}" for line in lines if line.strip()]
    return title + "\n" + "\n".join(items) if items else ""


def activity_lines(text: str) -> list[str]:
    # Split only the known boundaries in ActivityLog.day_summary, not periods
    # or commas in app/project names and user content.
    return re.split(r"(?<=\.) (?=By kind: |Projects: |You gave me )", text)


def weekly_text(report: str) -> str:
    headings = {"Time": "⏱️ Time by activity", "Study": "📚 Study", "Shipped": "✅ Shipped",
                "Projects": "🛠️ Projects", "Sessions": "🎯 Sessions", "Days": "📆 Day by day",
                "Rhythm": "🔁 Routine", "Predictions": "🔮 Predictions"}
    lines, current = [], ""
    for line in report.splitlines():
        if line.startswith("# "):
            lines.append("📅 " + line[2:])
        elif line.startswith("## "):
            current = line[3:]
            lines.extend(["", headings.get(current, current)])
        elif line.startswith("- "):
            items = line[2:].split(", ") if current == "Days" else [line[2:]]
            lines.extend("• " + item.replace("**", "") for item in items)
        else:
            lines.append(line.replace("**", "").strip("_"))
    if re.search(r"[+−]\d", report):
        lines.extend(["", "ℹ️ Changes in brackets compare with the previous week."])
    return "\n".join(lines).strip()
