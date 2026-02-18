#!/usr/bin/env python3
"""Auto-Label Bot - 遍历所有原创仓库，给未标记的 PR 自动打标签"""

import json
import os
import sys
import urllib.request

API_BASE = "https://feicode.com/api/v1"
TOKEN = os.environ.get("FORGEJO_TOKEN", "")
DRY_RUN = "--dry-run" in sys.argv

# 文件路径 → 标签映射
FILE_LABELS = [
    (r".php$", "php", "#4F5D95"),
    (r".(js|ts|tsx|jsx)$", "frontend", "#f1e05a"),
    (r".(css|scss|less)$", "style", "#e34c26"),
    (r".go$", "go", "#00ADD8"),
    (r".(yml|yaml)$", "ci/cd", "#0075ca"),
    (r"(composer.|package.json|go.mod)", "dependencies", "#0366d6"),
    (r".(md|txt|rst)$", "documentation", "#0075ca"),
    (r"(Dockerfile|docker-compose)", "docker", "#0db7ed"),
    (r".py$", "python", "#3572A5"),
]

SIZE_LABELS = [
    (10, "size/S", "#009900"),
    (100, "size/M", "#FFCC00"),
    (500, "size/L", "#FF6600"),
    (float("inf"), "size/XL", "#CC0000"),
]


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


def ensure_label(repo, name, color, label_cache):
    if name in label_cache:
        return label_cache[name]
    result = api("POST", f"repos/{repo}/labels",
                 {"name": name, "color": color})
    if result and "id" in result:
        label_cache[name] = result["id"]
        return result["id"]
    return None


def get_label_cache(repo):
    labels = api("GET", f"repos/{repo}/labels?limit=50")
    if not labels:
        return {}
    return {l["name"]: l["id"] for l in labels}


def determine_labels(files, changes):
    import re
    labels = set()
    for f in files:
        filename = f.get("filename", "")
        for pattern, label, _ in FILE_LABELS:
            if re.search(pattern, filename):
                labels.add(label)

    for threshold, label, _ in SIZE_LABELS:
        if changes < threshold:
            labels.add(label)
            break

    return labels


def process_repo(repo):
    # 获取最近 7 天内的 open PR
    prs = api("GET", f"repos/{repo}/pulls?state=open&sort=updated&limit=20")
    if not prs:
        return

    label_cache = get_label_cache(repo)
    has_work = False

    for pr in prs:
        number = pr["number"]
        existing = {l["name"] for l in pr.get("labels", [])}

        # 跳过已有文件类型标签或 size 标签的 PR
        has_file_label = any(l in existing for _, l, _ in FILE_LABELS)
        has_size_label = any(l in existing for _, l, _ in SIZE_LABELS)
        if has_file_label and has_size_label:
            continue

        # 获取 PR 文件列表
        files = api("GET", f"repos/{repo}/pulls/{number}/files")
        if not files:
            continue

        changes = pr.get("additions", 0) + pr.get("deletions", 0)
        needed = determine_labels(files, changes)
        new_labels = needed - existing

        if not new_labels:
            continue

        has_work = True
        label_ids = []
        for name in new_labels:
            color = "#ededed"
            for _, ln, lc in FILE_LABELS + SIZE_LABELS:
                if ln == name:
                    color = lc
                    break
            lid = label_cache.get(name) or ensure_label(repo, name, color, label_cache)
            if lid:
                label_ids.append(lid)

        if label_ids:
            print(f"  {repo}#{number}: +{','.join(new_labels)}")
            if not DRY_RUN:
                api("POST", f"repos/{repo}/issues/{number}/labels",
                    {"labels": label_ids})

    if not has_work:
        pass  # 无需标记的 PR


def main():
    if not TOKEN:
        print("ERROR: FORGEJO_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    print("=== Auto-Label 开始 ===")
    if DRY_RUN:
        print("(dry-run 模式)")

    repos = get_original_repos()
    print(f"发现 {len(repos)} 个原创仓库")

    for repo in repos:
        print(f"处理 {repo} ...")
        process_repo(repo)

    print("=== Auto-Label 完成 ===")


if __name__ == "__main__":
    main()
