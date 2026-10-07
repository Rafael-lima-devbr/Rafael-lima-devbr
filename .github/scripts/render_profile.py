#!/usr/bin/env python3

from __future__ import annotations

import html
import json
import os
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_URL = "https://api.github.com/graphql"
TOKEN = os.environ["GH_TOKEN"]
LOGIN = os.environ.get("PROFILE_USER", "Rafael-lima-devbr")
OUT = Path("profile")
OUT.mkdir(exist_ok=True)


def graphql(query: str, variables: dict) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "profile-metrics-workflow",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.load(response)
    if body.get("errors"):
        raise RuntimeError(json.dumps(body["errors"], indent=2))
    return body["data"]


now = datetime.now(timezone.utc)
start = now - timedelta(days=364)

QUERY = r"""
query ProfileMetrics($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalIssueContributions
      totalPullRequestContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
    repositories(
      first: 100
      ownerAffiliations: OWNER
      privacy: PUBLIC
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      nodes {
        isFork
        stargazerCount
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
              color
            }
          }
        }
      }
    }
  }
}
"""

data = graphql(
    QUERY,
    {
        "login": LOGIN,
        "from": start.isoformat(),
        "to": now.isoformat(),
    },
)

user = data["user"]
if not user:
    raise SystemExit(f"GitHub user not found: {LOGIN}")

collection = user["contributionsCollection"]
calendar = collection["contributionCalendar"]
weeks = calendar["weeks"]

contributions = int(calendar["totalContributions"])
prs = int(collection["totalPullRequestContributions"])
issues = int(collection["totalIssueContributions"])

repos = [repo for repo in user["repositories"]["nodes"] if not repo["isFork"]]
stars = sum(int(repo["stargazerCount"]) for repo in repos)

counts: dict[str, int] = {}
ordered_days: list[tuple[str, int]] = []
for week in weeks:
    for day in week["contributionDays"]:
        date = day["date"]
        count = int(day["contributionCount"])
        counts[date] = count
        ordered_days.append((date, count))

ordered_days.sort(key=lambda item: item[0])
active_days = sum(1 for _, count in ordered_days if count > 0)

# Longest streak across the returned calendar.
longest_streak = 0
running = 0
for _, count in ordered_days:
    if count > 0:
        running += 1
        longest_streak = max(longest_streak, running)
    else:
        running = 0

# Keep an in-progress UTC day from prematurely breaking the visible current streak.
today = now.date()
probe = today
if counts.get(probe.isoformat(), 0) == 0:
    probe -= timedelta(days=1)

current_streak = 0
while counts.get(probe.isoformat(), 0) > 0:
    current_streak += 1
    probe -= timedelta(days=1)

language_bytes: dict[str, int] = defaultdict(int)
language_colors: dict[str, str] = {}
for repo in repos:
    for edge in repo["languages"]["edges"]:
        name = edge["node"]["name"]
        if name == "Jupyter Notebook":
            continue
        language_bytes[name] += int(edge["size"])
        if edge["node"].get("color"):
            language_colors[name] = edge["node"]["color"]

language_total = sum(language_bytes.values()) or 1
top_languages = sorted(language_bytes.items(), key=lambda item: item[1], reverse=True)[:6]

as_of = now.strftime("%Y-%m-%d")

THEMES = {
    "light": {
        "bg": "#ffffff",
        "panel": "#f6f8fa",
        "border": "#d0d7de",
        "text": "#1f2328",
        "muted": "#656d76",
        "accent": "#0969da",
        "green": "#1a7f37",
        "purple": "#8250df",
        "grid0": "#ebedf0",
        "grid1": "#9be9a8",
        "grid2": "#40c463",
        "grid3": "#30a14e",
        "grid4": "#216e39",
    },
    "dark": {
        "bg": "#0d1117",
        "panel": "#161b22",
        "border": "#30363d",
        "text": "#f0f6fc",
        "muted": "#8b949e",
        "accent": "#58a6ff",
        "green": "#3fb950",
        "purple": "#bc8cff",
        "grid0": "#161b22",
        "grid1": "#0e4429",
        "grid2": "#006d32",
        "grid3": "#26a641",
        "grid4": "#39d353",
    },
}


def svg_shell(width: int, height: int, theme: dict, body: str, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="{html.escape(label)}">'
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12" '
        f'fill="{theme["bg"]}" stroke="{theme["border"]}"/>'
        + body
        + "</svg>"
    )


def terminal_dots(theme: dict) -> str:
    return (
        '<circle cx="18" cy="18" r="4" fill="#ff5f56"/>'
        '<circle cx="31" cy="18" r="4" fill="#ffbd2e"/>'
        '<circle cx="44" cy="18" r="4" fill="#27c93f"/>'
        f'<text x="58" y="21" fill="{theme["muted"]}" '
        'font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="9">profile://github</text>'
    )


def overview_card(theme_name: str) -> str:
    t = THEMES[theme_name]
    body = terminal_dots(t)
    body += (
        f'<text x="18" y="52" fill="{t["accent"]}" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" '
        'font-size="13" font-weight="700">$ github --overview</text>'
    )
    rows = [
        ("Contributions · year", contributions, t["green"]),
        ("Pull requests · year", prs, t["text"]),
        ("Issues · year", issues, t["text"]),
        ("Stars · public repos", stars, t["purple"]),
    ]
    y = 79
    for label, value, color in rows:
        body += (
            f'<text x="18" y="{y}" fill="{t["muted"]}" font-family="system-ui,-apple-system,Segoe UI,sans-serif" font-size="11">{html.escape(label)}</text>'
            f'<text x="282" y="{y}" text-anchor="end" fill="{color}" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="13" font-weight="700">{value}</text>'
        )
        y += 21
    body += (
        f'<text x="282" y="157" text-anchor="end" fill="{t["muted"]}" '
        f'font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="7">as of {as_of} UTC</text>'
    )
    return svg_shell(300, 165, t, body, "GitHub overview")


def streak_card(theme_name: str) -> str:
    t = THEMES[theme_name]
    body = terminal_dots(t)
    body += (
        f'<text x="18" y="48" fill="{t["accent"]}" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" '
        'font-size="12" font-weight="700">$ streak --status</text>'
    )
    values = [
        (106, current_streak, "CURRENT STREAK", t["green"]),
        (320, longest_streak, "LONGEST STREAK", t["purple"]),
        (534, contributions, "CONTRIBUTIONS · YEAR", t["text"]),
    ]
    body += f'<line x1="213" y1="61" x2="213" y2="124" stroke="{t["border"]}"/>'
    body += f'<line x1="427" y1="61" x2="427" y2="124" stroke="{t["border"]}"/>'
    for x, value, label, color in values:
        body += (
            f'<text x="{x}" y="96" text-anchor="middle" fill="{color}" '
            'font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="34" font-weight="700">'
            f'{value}</text>'
            f'<text x="{x}" y="117" text-anchor="middle" fill="{t["muted"]}" '
            'font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="9" font-weight="600">'
            f'{label}</text>'
        )
    body += (
        f'<text x="18" y="140" fill="{t["muted"]}" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="8">'
        f'{active_days} active days · as of {as_of} UTC</text>'
    )
    return svg_shell(640, 150, t, body, "GitHub streak and contribution summary")


def language_card(theme_name: str) -> str:
    t = THEMES[theme_name]
    body = terminal_dots(t)
    body += (
        f'<text x="18" y="52" fill="{t["accent"]}" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" '
        'font-size="13" font-weight="700">$ languages --top</text>'
    )

    rail_x = 18
    rail_y = 65
    rail_w = 264
    cursor = rail_x
    body += f'<rect x="{rail_x}" y="{rail_y}" width="{rail_w}" height="7" rx="3.5" fill="{t["panel"]}"/>'
    for name, size in top_languages:
        width = rail_w * size / language_total
        color = language_colors.get(name) or t["accent"]
        body += f'<rect x="{cursor:.2f}" y="{rail_y}" width="{width:.2f}" height="7" fill="{color}"/>'
        cursor += width

    for index, (name, size) in enumerate(top_languages):
        col = 0 if index < 3 else 1
        row = index if index < 3 else index - 3
        x = 18 + col * 142
        y = 94 + row * 22
        pct = size * 100 / language_total
        color = language_colors.get(name) or t["accent"]
        safe_name = html.escape(name)
        body += (
            f'<circle cx="{x + 4}" cy="{y - 3}" r="4" fill="{color}"/>'
            f'<text x="{x + 14}" y="{y}" fill="{t["text"]}" font-family="system-ui,-apple-system,Segoe UI,sans-serif" font-size="9.5">'
            f'{safe_name} {pct:.1f}%</text>'
        )

    body += (
        f'<text x="282" y="157" text-anchor="end" fill="{t["muted"]}" '
        f'font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="7">Jupyter excluded · {len(repos)} repos</text>'
    )
    return svg_shell(300, 165, t, body, "Top programming languages")


def level_for(count: int) -> int:
    if count <= 0:
        return 0
    if count == 1:
        return 1
    if count <= 3:
        return 2
    if count <= 7:
        return 3
    return 4


def contribution_grid(theme_name: str) -> str:
    t = THEMES[theme_name]
    body = terminal_dots(t)
    body += (
        f'<text x="18" y="49" fill="{t["accent"]}" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" '
        'font-size="12" font-weight="700">$ contributions --year</text>'
        f'<text x="622" y="49" text-anchor="end" fill="{t["muted"]}" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="8">'
        f'{contributions} total · {active_days} active days</text>'
    )

    x0 = 49
    y0 = 66
    cell = 8
    gap = 2
    for week_index, week in enumerate(weeks[-53:]):
        for day in week["contributionDays"]:
            weekday = datetime.fromisoformat(day["date"]).weekday()
            # Convert Monday=0 to GitHub-style Sunday=0.
            row = (weekday + 1) % 7
            x = x0 + week_index * (cell + gap)
            y = y0 + row * (cell + gap)
            level = level_for(int(day["contributionCount"]))
            body += (
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="1.5" '
                f'fill="{t[f"grid{level}"]}"/>'
            )

    for label, row in [("Sun", 0), ("Tue", 2), ("Thu", 4), ("Sat", 6)]:
        y = y0 + row * (cell + gap) + 7
        body += (
            f'<text x="17" y="{y}" fill="{t["muted"]}" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="7">{label}</text>'
        )

    legend_y = 151
    body += f'<text x="495" y="{legend_y}" fill="{t["muted"]}" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="7">less</text>'
    for level in range(5):
        body += f'<rect x="{520 + level * 12}" y="143" width="8" height="8" rx="1.5" fill="{t[f"grid{level}"]}"/>'
    body += f'<text x="586" y="{legend_y}" fill="{t["muted"]}" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="7">more</text>'
    body += (
        f'<text x="18" y="170" fill="{t["muted"]}" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="7">'
        f'GitHub contribution calendar · as of {as_of} UTC</text>'
    )
    return svg_shell(640, 180, t, body, "GitHub contribution history for the past year")


for theme_name in THEMES:
    (OUT / f"overview-card-{theme_name}.svg").write_text(overview_card(theme_name), encoding="utf-8")
    (OUT / f"streak-card-{theme_name}.svg").write_text(streak_card(theme_name), encoding="utf-8")
    (OUT / f"top-langs-{theme_name}.svg").write_text(language_card(theme_name), encoding="utf-8")
    (OUT / f"contribution-grid-{theme_name}.svg").write_text(contribution_grid(theme_name), encoding="utf-8")

print(
    json.dumps(
        {
            "user": LOGIN,
            "as_of": as_of,
            "contributions": contributions,
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "pull_requests": prs,
            "issues": issues,
            "stars": stars,
            "active_days": active_days,
            "languages": [name for name, _ in top_languages],
        },
        indent=2,
    )
)
