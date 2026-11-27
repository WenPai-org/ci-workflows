# CI Workflows 共享模板库（FeiCode Software Factory v2）

FeiCode（`https://feicode.com`）统一 Forgejo Actions CI/CD 共享工作流模板库。

自 **v2** 起，推荐所有业务仓直接通过 **`on: workflow_call` 一行 `uses:` 复用**，无需再把数百行 YAML 复制到各仓库，统一享受 Runner 多语言镜像、Actions 缓存、安全加固与发版制品入仓能力。

---

## 一、可用 Runner 标签与基础 Action

- **基础 Action（已由 `feicode.com/actions/*` 镜像，且 `[actions] DEFAULT_ACTIONS_URL = self`）**：
  `actions/checkout@v4`、`actions/setup-go`、`actions/setup-node`、`actions/setup-python`、`actions/cache@v4`、`actions/upload-artifact`、`actions/download-artifact`
- **常用 Runner 标签（`forgejo-runner-01`，4 并发 + Actions Cache）**：
  `ubuntu-latest`、`ubuntu-22.04`、`php-7.4`、`php-8.3`、`go-1.24`、`node-22`、`python-3.12`

---

## 二、v2 可复用模板一览（推荐 · `workflow_call`）

| 模板文件 | 默认 Runner | 核心能力 |
| --- | --- | --- |
| `reusable-gitleaks.yml` | `ubuntu-latest` | `gitleaks` 密钥与私钥泄露扫描（镜像无二进制时自动降级为内置正则红线扫描） |
| `reusable-wp-plugin-ci.yml` | `php-8.3` | 全量 PHP 语法检查、可选 Composer 安装、可选单测命令、`wenpai-admin-lint`、公开文档门禁 |
| `reusable-wp-plugin-release.yml` | `php-8.3` | 仅限 `v*` Tag 触发（禁止 PR 越权）；版本一致性校验 + PHP lint + 单测 + 白名单 ZIP + SHA-256 + Forgejo Release + Generic Packages 入仓 + 可选 `wenpai-bridge` 签名 Webhook / Mattermost 通知 |
| `reusable-go-ci.yml` | `go-1.24` | `actions/cache` 缓存模块、`go vet ./...`、`go test -race ./...`、可选跨平台构建 `build_cmd` |
| `reusable-docker-oci.yml` | `ubuntu-latest` | 多阶段构建 OCI 镜像并推送至 `feicode.com/<owner>/<image>:<tag>`，输出 `image_ref` 与 `digest`（PR 事件自动只构建不推送） |

---

## 三、复制即用示例（10 行接入）

> **重要**：FeiCode 同实例调用 `workflow_call` 必须使用短路径 `WenPai-org/ci-workflows/.forgejo/workflows/reusable-*.yml@main`（**不要**加 `https://feicode.com/` 前缀），Forgejo 服务端才会自动展开子 Job 并正确匹配 `runs-on` 标签。

### 1. 密钥泄露扫描（所有仓库必接）

```yaml
name: Secret Scan
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  gitleaks:
    uses: WenPai-org/ci-workflows/.forgejo/workflows/reusable-gitleaks.yml@main
```

### 2. WordPress 插件 CI

```yaml
name: WP Plugin CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  ci:
    uses: WenPai-org/ci-workflows/.forgejo/workflows/reusable-wp-plugin-ci.yml@main
    with:
      runs_on: php-8.3
      test_command: "php tests/php/run.php"
      admin_lint: true
      public_docs_gate: true
```

### 3. WordPress 插件自动发版（`v*` Tag）

```yaml
name: WP Plugin Release
on:
  push:
    tags: ["v*"]

jobs:
  release:
    uses: WenPai-org/ci-workflows/.forgejo/workflows/reusable-wp-plugin-release.yml@main
    with:
      test_command: "php tests/php/run.php"
      publish_package: true
    secrets:
      RELEASE_TOKEN: ${{ secrets.RELEASE_TOKEN }}
      BRIDGE_WEBHOOK_URL: ${{ secrets.BRIDGE_WEBHOOK_URL }}
      BRIDGE_WEBHOOK_SECRET: ${{ secrets.BRIDGE_WEBHOOK_SECRET }}
      MM_WEBHOOK_URL: ${{ secrets.MM_WEBHOOK_URL }}
```

> 安全说明：仓库若存在自定义确定性打包脚本（例如 `scripts/build-candidate.py`），可通过 `build_command` 传入，脚本内可直接读取 `$VERSION`、`$SLUG`、`$RELEASE_DIR`、`$ZIP_NAME` 环境变量。`reusable-wp-plugin-release.yml` 强制拦截 `pull_request` 事件，防止 Fork PR 触达发版 Secrets。

### 4. Go 服务 CI 与交叉编译

```yaml
name: Go CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  go:
    uses: WenPai-org/ci-workflows/.forgejo/workflows/reusable-go-ci.yml@main
    with:
      runs_on: go-1.24
      test_flags: "-race ./..."
      build_cmd: "CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o dist/app ./cmd/app"
```

### 5. Docker / OCI 镜像构建与推送

```yaml
name: OCI Image
on:
  push:
    branches: [main]
    tags: ["v*"]
  pull_request:
    branches: [main]

jobs:
  oci:
    uses: WenPai-org/ci-workflows/.forgejo/workflows/reusable-docker-oci.yml@main
    with:
      dockerfile: Dockerfile
      context: .
    secrets:
      REGISTRY_TOKEN: ${{ secrets.PACKAGE_TOKEN }}
```

---

## 四、历史兼容：复制式模板（v1，保持原样兼容）

以下原有模板继续保留在 `.forgejo/workflows/` 中，确保已复制引用的仓库不受影响：

- `gitleaks.yml`：传统复制式密钥泄露扫描
- `trivy.yml`：依赖锁文件漏洞扫描（HIGH/CRITICAL）
- `wp-plugin-ci.yml`：传统复制式 WordPress 插件 CI
- `wp-release.yml`：传统复制式 WordPress 插件发布流程
- `go-ci.yml`：传统复制式 Go 项目 CI
- `ts-ci.yml`：TypeScript/JS 项目 CI
- `security-scan.yml`：Hadolint + 依赖审计 + Trivy 综合安全扫描
- `renovate.yml`：每周一、四自动依赖更新（策略参考 `renovate-default.json`）
- `stale-cleanup.yml`：Issue/PR 过期清理
- `auto-label.yml`：按变更路径与变更量自动打 PR 标签
- `infra-monitor.yml` / `test-gz-runner.yml`：基础设施巡检与 Runner 测试模板
