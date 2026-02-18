#!/usr/bin/env python3
"""Stale Issue/PR 清理 Bot - 遍历所有原创仓库，标记/关闭过期 Issue 和 PR"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

API_BASE = "https://feicode.com/api/v1"
TOKEN = os.environ.get("FORGEJO_TOKEN", "")
DRY_RUN = "--dry-run" in sys.argv

ISSUE_STALE_DAYS = 60
ISSUE_CLOSE_DAYS = 74
PR_STALE_DAYS = 30
PR_CLOSE_DAYS = 44
PROTECTED_LABELS = {"pinned", "help-wanted", "bug", "security", "wontfix"}


def api(method, path, data=None):
    url = f"{API_BASE}/{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"token {TOKEN}")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  API error: {method} {path}: {e}", file=sys.stderr)
        return None


def get_original_repos():
    data = api("GET", "repos/search?limit=50&sort=updated&order=desc")
    if not data:
        return []
    return [r["full_name"] for r in data.get("data", [])
            if not r.get("mirror") and not r.get("fork") and not r.get("archived")]


def ensure_stale_label(repo):
    labels = api("GET", f"repos/{repo}/labels?limit=50")
    if labels:
        for l in labels:
            if l["name"] == "stale":
                return l["id"]
    result = api("POST", f"repos/{repo}/labels",
                 {"name": "stale", "color": "#ededed", "description": "长期无活动"})
    if result and "id" in result:
        print(f"  创建 stale 标签: ID={result['id']}")
        return result["id"]
    return None


def process_repo(repo):
    label_id = ensure_stale_label(repo)
    now = datetime.now(timezone.utc)

    for item_type, stale_days, close_days in [
        ("issues", ISSUE_STALE_DAYS, ISSUE_CLOSE_DAYS),
        ("pulls", PR_STALE_DAYS, PR_CLOSE_DAYS),
    ]:
        page = 1
        while True:
            items = api("GET", f"repos/{repo}/issues?state=open&type={item_type}&page={page}&limit=50")
            if not items:
                break

            for item in items:
                labels = {l["name"] for l in item.get("labels", [])}
                if PROTECTED_LABELS & labels:
                    continue

                updated = datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00"))
                age_days = (now - updated).days
                number = item["number"]
                title = item["title"][:60]
                kind = "issue" if item_type == "issues" else "PR"

                if age_days > close_days:
                    print(f"  关闭 {repo}#{number} ({age_days}天): {title}")
                    if not DRY_RUN:
                        api("PATCH", f"repos/{repo}/issues/{number}", {"state": "closed"})
                        api("POST", f"repos/{repo}/issues/{number}/comments",
                            {"body": f"此 {kind} 因长期无活动已自动关闭。如需继续讨论请重新打开。"})
                elif age_days > stale_days and "stale" not in labels and label_id:
                    print(f"  标记 {repo}#{number} 为 stale ({age_days}天): {title}")
                    if not DRY_RUN:
                        api("POST", f"repos/{repo}/issues/{number}/labels", {"labels": [label_id]})
                        api("POST", f"repos/{repo}/issues/{number}/comments",
                            {"body": f"此 {kind} 已超过 {stale_days} 天无活动，已标记为 stale。如果 14 天内无新活动将自动关闭。"})

            if len(items) < 50:
                break
            page += 1


def main():
    if not TOKEN:
        print("ERROR: FORGEJO_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    print("=== Stale 清理开始 ===")
    if DRY_RUN:
        print("(dry-run 模式，不会实际修改)")

    repos = get_original_repos()
    print(f"发现 {len(repos)} 个原创仓库")

    for repo in repos:
        print(f"处理 {repo} ...")
        process_repo(repo)

    print("=== 清理完成 ===")


if __name__ == "__main__":
    main()
