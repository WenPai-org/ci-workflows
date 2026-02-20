#!/usr/bin/env python3
"""基础设施监控脚本

检查项：
- Forgejo 服务健康
- Forgejo Runner 状态
- VPS 磁盘空间（全部生产服务器）
- 备份新鲜度
- 镜像同步状态
- NAS 可达性
- 生产网站真实可用性（内容校验，非仅状态码）
- SSL 证书到期预警
- Docker 容器健康
- WordPress 安全检查

告警渠道：
- 共享上下文 /mnt/shared-context/alerts/
- Forgejo Issue（持久化追踪）
- 控制台输出
"""

import json
import os
import re
import ssl
import socket
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
DISK_WARN_PCT = 80
BACKUP_MAX_AGE_HOURS = 30
MIRROR_STALE_DAYS = 3
SSL_WARN_DAYS = 14


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


# === 生产服务器配置 ===

PROD_SERVERS = {
    "weixiaoduo-prod": {
        "host": "weixiaoduo-prod",
        "sites": [
            {"url": "https://www.weixiaoduo.com", "expect": "weixiaoduo", "name": "薇晓朵主站"},
            {"url": "https://www.feibisi.com", "expect": "feibisi", "name": "飞比斯"},
            {"url": "https://tongji.feibisi.com", "expect": "matomo", "name": "Matomo统计"},
        ],
        "containers": ["matomo-app", "matomo-mysql", "postgresql_an4p-postgresql_an4p-1"],
        "disks": ["/", "/www"],
    },
    "feicode-prod": {
        "host": "feicode-prod",
        "sites": [
            {"url": "https://feicode.com", "expect": "feicode", "name": "feiCode"},
        ],
        "containers": ["forgejo_FeiCode-1", "wenpai-bridge", "forgejo-runner-01"],
        "disks": ["/"],
    },
    "wptea-prod": {
        "host": "wptea-prod",
        "sites": [
            {"url": "https://wptea.com", "expect": "wptea", "name": "WP茶馆"},
        ],
        "containers": [],
        "disks": ["/"],
    },
    "cravatar-prod": {
        "host": "cravatar-prod",
        "sites": [
            {"url": "https://cravatar.com", "expect": "cravatar", "name": "Cravatar"},
            {"url": "https://cn.cravatar.com", "expect": "cravatar", "name": "Cravatar CN"},
        ],
        "containers": [],
        "disks": ["/"],
    },
}

# SSL 证书检查列表（关键域名）
SSL_DOMAINS = [
    "www.weixiaoduo.com", "www.feibisi.com", "tongji.feibisi.com",
    "feicode.com", "wptea.com",
    "cravatar.com", "cn.cravatar.com",
]


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


def check_disk(server_name, server_cfg):
    """检查服务器磁盘空间"""
    c = Check(f"磁盘 {server_name}")
    host = server_cfg["host"]
    problems = []
    details = []

    for mount in server_cfg["disks"]:
        code, out = run_cmd(
            f"ssh -o ConnectTimeout=5 {host} 'df -h {mount} | tail -1'", timeout=15
        )
        if code != 0:
            problems.append(f"{mount}: 无法检查")
            continue
        parts = out.split()
        if len(parts) >= 5:
            usage_pct = int(parts[4].rstrip("%"))
            if usage_pct >= DISK_WARN_PCT:
                problems.append(f"{mount} {usage_pct}% ({parts[2]}/{parts[1]})")
            else:
                details.append(f"{mount} {usage_pct}%")

    if problems:
        return c.fail("; ".join(problems), "\n".join(details))
    return c.success("; ".join(details))


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


def check_website(site_cfg):
    """检查网站真实可用性（不只是状态码）"""
    c = Check(f"网站 {site_cfg['name']}")
    url = site_cfg["url"]
    expect = site_cfg["expect"].lower()

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "InfraMonitor/1.0",
            "Accept": "text/html",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            body = resp.read(50000).decode("utf-8", errors="replace").lower()

            # 检查 HTTP 状态码
            if status >= 500:
                return c.fail(f"HTTP {status}", url)

            # 检查页面是否包含预期内容
            if expect not in body:
                return c.fail(f"页面无预期内容 '{site_cfg['expect']}'", f"HTTP {status}, {url}")

            # 检查常见错误标志
            error_patterns = [
                ("fatal error", "PHP Fatal Error"),
                ("database connection", "数据库连接失败"),
                ("error establishing", "数据库连接失败"),
                ("502 bad gateway", "502 网关错误"),
                ("503 service", "503 服务不可用"),
                ("maintenance mode", "维护模式"),
                ("parse error", "PHP Parse Error"),
                ("warning:</b>", "PHP Warning"),
            ]
            for pattern, desc in error_patterns:
                if pattern in body:
                    return c.fail(f"页面包含错误: {desc}", url)

            return c.success(f"HTTP {status}")

    except urllib.error.HTTPError as e:
        return c.fail(f"HTTP {e.code}", url)
    except urllib.error.URLError as e:
        return c.fail(f"连接失败: {e.reason}", url)
    except Exception as e:
        return c.fail(f"异常: {str(e)[:80]}", url)


def check_ssl_cert(domain):
    """检查 SSL 证书到期时间"""
    c = Check(f"SSL {domain}")
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                expire_str = cert["notAfter"]  # 'Nov 12 13:35:49 2026 GMT'
                expire_date = datetime.strptime(expire_str, "%b %d %H:%M:%S %Y %Z")
                days_left = (expire_date - datetime.now()).days

                if days_left < 0:
                    return c.fail(f"已过期 {abs(days_left)} 天")
                if days_left < SSL_WARN_DAYS:
                    return c.fail(f"{days_left} 天后过期 ({expire_date.strftime('%Y-%m-%d')})")
                return c.success(f"{days_left} 天 ({expire_date.strftime('%Y-%m-%d')})")
    except ssl.SSLCertVerificationError as e:
        return c.fail(f"证书验证失败: {str(e)[:60]}")
    except Exception as e:
        return c.fail(f"检查失败: {str(e)[:60]}")


def check_containers(server_name, server_cfg):
    """检查 Docker 容器运行状态"""
    c = Check(f"容器 {server_name}")
    host = server_cfg["host"]
    expected = server_cfg["containers"]

    if not expected:
        return c.success("无容器配置，跳过")

    code, out = run_cmd(
        f"ssh -o ConnectTimeout=5 {host} 'docker ps --format \"{{{{.Names}}}}:{{{{.Status}}}}\"'",
        timeout=15,
    )
    if code != 0:
        return c.fail("无法检查容器状态", out)

    running = {}
    for line in out.strip().split("\n"):
        if ":" in line:
            name, status = line.split(":", 1)
            running[name] = status

    down = [name for name in expected if name not in running]
    if down:
        return c.fail(f"容器未运行: {', '.join(down)}")
    return c.success(f"{len(expected)} 个容器正常")


def check_wp_security():
    """检查 WordPress 安全指标（webshell 快速扫描）"""
    c = Check("WP 安全")
    # 检查上传目录是否有可疑 PHP 文件（排除 index.php 和已知插件目录）
    code, out = run_cmd(
        "ssh -o ConnectTimeout=5 weixiaoduo-prod "
        "'find /www/wwwroot/www.weixiaoduo.com/wp-content/uploads/ "
        "-name \"*.php\" ! -name \"index.php\" "
        "! -path \"*/wpallimport/*\" ! -path \"*/cravatar/*\" ! -path \"*/learndash/*\" "
        "-type f 2>/dev/null | head -5'",
        timeout=20,
    )
    if code != 0:
        return c.fail("无法扫描", out)

    if out.strip():
        files = out.strip().split("\n")
        return c.fail(
            f"上传目录发现 {len(files)} 个可疑 PHP 文件",
            "\n".join(files[:5]),
        )
    return c.success("上传目录无可疑 PHP 文件")


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
    print(f"=== 基础设施监控 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    checks = []

    # --- feiCode 平台 ---
    print("  [feiCode 平台]")
    checks.append(check_forgejo_health())
    checks.append(check_runner())
    checks.append(check_backup())
    checks.append(check_mirror_sync())
    checks.append(check_nas())

    # --- 生产服务器磁盘 ---
    print("  [生产服务器]")
    for name, cfg in PROD_SERVERS.items():
        checks.append(check_disk(name, cfg))

    # --- Docker 容器 ---
    for name, cfg in PROD_SERVERS.items():
        checks.append(check_containers(name, cfg))

    # --- 网站可用性 ---
    print("  [网站可用性]")
    for cfg in PROD_SERVERS.values():
        for site in cfg["sites"]:
            checks.append(check_website(site))

    # --- SSL 证书 ---
    print("  [SSL 证书]")
    for domain in SSL_DOMAINS:
        checks.append(check_ssl_cert(domain))

    # --- WordPress 安全 ---
    print("  [安全检查]")
    checks.append(check_wp_security())

    # --- 输出结果 ---
    print()
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
