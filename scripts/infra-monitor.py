#!/usr/bin/env python3
"""feiCode 基础设施监控脚本

检查项：
- Forgejo 服务健康
- Forgejo Runner 状态
- VPS 磁盘空间
- 备份新鲜度
- 镜像同步状态
- NAS 可达性

告警渠道：
- 共享上下文 /mnt/shared-context/alerts/
- Forgejo Issue（持久化追踪）
- 控制台输出
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path


FORGEJO_URL = os.environ.get("FORGEJO_URL", "https://feicode.com")
FORGEJO_TOKEN = os.environ.get("FORGEJO_TOKEN", "")
ALERT_DIR = Path("/mnt/shared-context/alerts")
ALERT_REPO = "WenPai-org/ci-workflows"

# 阈值
VPS_DISK_WARN_PCT = 80
BACKUP_MAX_AGE_HOURS = 30
MIRROR_STALE_DAYS = 3


class Check:
    def __init__(self, name):
        self.name = name
        self.ok = True
        self.message = ""
        self.details = ""

    def fail(self, message, details=""):
        self.ok = False
        self.message = message
        self.details = details
        return self

    def success(self, message=""):
        self.ok = True
        self.message = message
        return self


def api_get(path):
    """Forgejo API GET"""
    url = f"{FORGEJO_URL}/api/v1/{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"token {FORGEJO_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def run_cmd(cmd, timeout=10):
    """运行命令并返回输出"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


# === 检查函数 ===

def check_forgejo_health():
    """检查 Forgejo 服务是否响应"""
    c = Check("Forgejo 服务")
    data = api_get("version")
    if data and "version" in data:
        return c.success(f"v{data['version']}")
    return c.fail("Forgejo API 无响应")


def check_runner():
    """检查 Forgejo Runner 服务状态"""
    c = Check("Forgejo Runner")
    code, out = run_cmd("systemctl --user is-active forgejo-runner")
    if code == 0 and out == "active":
        return c.success("active")
    return c.fail(f"Runner 状态: {out}")


def check_vps_disk():
    """检查 VPS 磁盘空间"""
    c = Check("VPS 磁盘")
    code, out = run_cmd("ssh -o ConnectTimeout=5 myserver 'df -h / | tail -1'", timeout=15)
    if code != 0:
        return c.fail("无法连接 VPS", out)
    parts = out.split()
    if len(parts) >= 5:
        usage_pct = int(parts[4].rstrip("%"))
        total = parts[1]
        used = parts[2]
        if usage_pct >= VPS_DISK_WARN_PCT:
            return c.fail(f"磁盘使用 {usage_pct}% ({used}/{total})")
        return c.success(f"{usage_pct}% ({used}/{total})")
    return c.fail("无法解析磁盘信息", out)


def check_backup():
    """检查 Forgejo 备份新鲜度"""
    c = Check("Forgejo 备份")
    code, out = run_cmd(
        "ssh -o ConnectTimeout=5 nas 'ls -lh /volume1/Download/backups/forgejo/latest/forgejo-dump-*.zip 2>/dev/null | tail -1'",
        timeout=15
    )
    if code != 0:
        return c.fail("无法检查 NAS 备份", out)
    if not out.strip():
        return c.fail("NAS 上无备份文件")

    lines = out.strip().split("\n")
    for line in lines:
        if ".zip" in line:
            parts = line.split()
            # -rw------- 1 user group 181M Feb 19 10:02 forgejo-dump-20260219.zip
            if len(parts) >= 9:
                size = parts[4]
                date_str = f"{parts[5]} {parts[6]} {parts[7]}"
                fname = parts[8]
                return c.success(f"{fname} ({size}, {date_str})")
    return c.success("有备份文件")


def check_mirror_sync():
    """检查镜像同步状态"""
    c = Check("镜像同步")
    data = api_get("repos/search?mirror=true&limit=50&sort=updated&order=asc")
    if not data:
        return c.fail("无法获取镜像列表")

    repos = data.get("data", data) if isinstance(data, dict) else data
    cutoff = datetime.now() - timedelta(days=MIRROR_STALE_DAYS)
    stale = []

    for r in repos:
        updated = r.get("mirror_updated", "")
        if updated == "0001-01-01T00:00:00Z":
            stale.append(f"{r['full_name']}(从未同步)")
        elif updated:
            try:
                t = datetime.strptime(updated[:19], "%Y-%m-%dT%H:%M:%S")
                if t < cutoff:
                    stale.append(r["full_name"])
            except ValueError:
                pass

    if stale:
        return c.fail(f"{len(stale)} 个镜像超过 {MIRROR_STALE_DAYS} 天未同步",
                       "\n".join(stale[:10]))
    return c.success(f"全部正常（检查了 {len(repos)} 个）")


def check_nas():
    """检查 NAS 可达性和磁盘"""
    c = Check("NAS 存储")
    code, out = run_cmd("ssh -o ConnectTimeout=5 nas 'df -h /volume1 | tail -1'", timeout=15)
    if code != 0:
        return c.fail("NAS 不可达", out)
    parts = out.split()
    if len(parts) >= 5:
        return c.success(f"{parts[4]} ({parts[2]}/{parts[1]})")
    return c.success("可达")


# === 告警输出 ===

def write_alert(checks):
    """写入告警到共享上下文"""
    failures = [c for c in checks if not c.ok]
    if not failures:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ALERT_DIR.mkdir(parents=True, exist_ok=True)
    alert_file = ALERT_DIR / f"{datetime.now().strftime('%Y-%m-%d')}-infra.md"

    content = f"# 基础设施告警 {now}\n\n"
    for c in failures:
        content += f"## {c.name}\n{c.message}\n"
        if c.details:
            content += f"```\n{c.details}\n```\n"
        content += "\n"

    alert_file.write_text(content)
    print(f"告警已写入 {alert_file}")


def create_alert_issue(checks):
    """在 Forgejo 上创建告警 Issue"""
    failures = [c for c in checks if not c.ok]
    if not failures or not FORGEJO_TOKEN:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"基础设施告警: {', '.join(c.name for c in failures)} ({now})"
    body = "| 状态 | 检查项 | 详情 |\n|------|--------|------|\n"
    for c in checks:
        icon = "✅" if c.ok else "❌"
        body += f"| {icon} | {c.name} | {c.message} |\n"
    body += "\n"
    for c in failures:
        if c.details:
            body += f"### {c.name}\n```\n{c.details}\n```\n\n"

    payload = json.dumps({"title": title, "body": body}).encode()
    url = f"{FORGEJO_URL}/api/v1/repos/{ALERT_REPO}/issues"
    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"token {FORGEJO_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            print(f"告警 Issue #{data.get('number')} 已创建")
    except Exception as e:
        print(f"创建告警 Issue 失败: {e}")


def main():
    print(f"=== feiCode 基础设施监控 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    checks = [
        check_forgejo_health(),
        check_runner(),
        check_vps_disk(),
        check_backup(),
        check_mirror_sync(),
        check_nas(),
    ]

    for c in checks:
        icon = "✅" if c.ok else "❌"
        print(f"  {icon} {c.name}: {c.message}")
        if not c.ok and c.details:
            for line in c.details.split("\n")[:5]:
                print(f"      {line}")

    failures = [c for c in checks if not c.ok]
    print(f"\n结果: {len(checks) - len(failures)}/{len(checks)} 通过")

    if failures:
        write_alert(checks)
        create_alert_issue(checks)
        sys.exit(1)
    else:
        # 清理 7 天前的旧告警
        if ALERT_DIR.exists():
            for f in ALERT_DIR.glob("*-infra.md"):
                try:
                    age = datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)
                    if age.days > 7:
                        f.unlink()
                except Exception:
                    pass
        print("全部正常。")


if __name__ == "__main__":
    main()
