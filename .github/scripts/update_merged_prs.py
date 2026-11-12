#!/usr/bin/env python3
"""Rebuild the "merged external PRs" section in README.md.

Searches merged PRs authored by the account, excludes own repos and any
private repo (private project records are never written to the public
README), and rewrites the content between the MERGED-PRS markers.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

OWNER = "hsthanb4"
REPO = "hsthanb4"
BRANCH = "main"
DAYS = 90
README_PATH = "README.md"
API = "https://api.github.com"
TOKEN = os.environ["GH_TOKEN"]

START = "<!-- MERGED-PRS:START -->"
END = "<!-- MERGED-PRS:END -->"


def api(url):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "merged-prs-updater",
    })
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def search_merged_prs():
    items, page = [], 1
    while True:
        q = f"author:{OWNER} type:pr is:merged -user:{OWNER}"
        url = (f"{API}/search/issues?q={urllib.parse.quote(q)}"
               f"&sort=updated&order=desc&per_page=100&page={page}")
        data = api(url)
        items.extend(data.get("items", []))
        if len(items) >= data.get("total_count", 0) or page >= 10:
            break
        page += 1
    return items


def is_public(full_name):
    # 查不到或请求失败的一律按不收录处理，宁缺毋滥
    try:
        return api(f"{API}/repos/{full_name}").get("private") is False
    except Exception as e:
        print(f"skip {full_name}: repo lookup failed ({e})")
        return False


def build_rows(items):
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS)
    rows = []
    seen = set()
    for it in items:
        url = it.get("html_url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        closed = it.get("closed_at") or ""
        try:
            when = datetime.fromisoformat(closed.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < cutoff:
            continue
        full_name = it.get("repository_url", "").split("repos/")[-1]
        if not full_name or full_name.split("/")[0] == OWNER:
            continue
        if not is_public(full_name):
            print(f"skip {full_name}: private or inaccessible")
            continue
        title = (it.get("title") or "").replace("|", "\\|").strip()
        rows.append((when.strftime("%Y-%m-%d"), full_name, title, url, it.get("number")))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def render(rows):
    if not rows:
        return f"_近 {DAYS} 天暂无合入的外部公开 PR。_"
    lines = ["| 合入日期 | 仓库 | PR |", "| --- | --- | --- |"]
    for date, full_name, title, url, number in rows:
        repo_url = f"https://github.com/{full_name}"
        lines.append(f"| {date} | [{full_name}]({repo_url}) | [#{number}]({url}) {title} |")
    return "\n".join(lines)


def update_readme(section):
    current = api(f"{API}/repos/{OWNER}/{REPO}/contents/{README_PATH}?ref={BRANCH}")
    body = base64_decode(current["content"])
    if START not in body or END not in body:
        raise SystemExit(f"{START}/{END} markers missing in {README_PATH}")
    head, rest = body.split(START, 1)
    _, tail = rest.split(END, 1)
    new_body = f"{head}{START}\n{section}\n{END}{tail}"
    if new_body == body:
        print("README unchanged")
        return
    payload = {
        "message": "chore: update merged external PR list\n\nAssisted-by: Cindy (https://cindy.app)",
        "content": base64_encode(new_body),
        "sha": current["sha"],
        "branch": BRANCH,
    }
    req = urllib.request.Request(
        f"{API}/repos/{OWNER}/{REPO}/contents/{README_PATH}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "merged-prs-updater",
        },
        method="PUT",
    )
    with urllib.request.urlopen(req) as r:
        print("README updated:", json.load(r)["commit"]["sha"])


def base64_decode(s):
    import base64 as b
    return b.b64decode(s).decode()


def base64_encode(s):
    import base64 as b
    return b.b64encode(s.encode()).decode()


if __name__ == "__main__":
    rows = build_rows(search_merged_prs())
    print(f"found {len(rows)} merged external public PRs in last {DAYS} days")
    update_readme(render(rows))
