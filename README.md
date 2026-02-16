# CI Workflows 共享模板

Forgejo Actions CI/CD 共享 workflow 模板，供 feicode.com 上的仓库使用。

## 包含的 Workflow

### 1. gitleaks 密钥泄露扫描 (`gitleaks.yml`)
- 每次 push 和 PR 自动扫描代码中的 API key、密码、token 等敏感信息
- 使用 [gitleaks](https://github.com/gitleaks/gitleaks) 引擎

### 2. Trivy 依赖漏洞扫描 (`trivy.yml`)
- 扫描 `composer.lock`、`package-lock.json` 等锁文件中的已知漏洞
- 仅报告 HIGH 和 CRITICAL 级别
- 支持 `.trivyignore` 文件忽略特定 CVE
- 每周一定时扫描 + lockfile 变更时触发

### 3. WordPress 插件 CI (`wp-plugin-ci.yml`)
- Push/PR 到 main/master 时自动触发
- PHP Parallel Lint 语法检查
- PHPCS 代码规范检查（支持自定义配置）
- Gitleaks 密钥泄露扫描

### 4. Go 项目 CI (`go-ci.yml`)
- Push/PR 到 main/master 时自动触发
- `go vet` 静态检查
- `golangci-lint` 代码规范检查（支持自定义配置，未安装时自动安装）
- `go test -race` 单元测试 + 覆盖率
- Gitleaks 密钥泄露扫描

### 5. TypeScript/JS 项目 CI (`ts-ci.yml`)
- Push/PR 到 main/master 时自动触发
- 自动检测包管理器（npm/yarn/pnpm）
- `tsc --noEmit` TypeScript 类型检查
- ESLint 代码规范检查（支持 flat config）
- Gitleaks 密钥泄露扫描

### 6. WordPress 插件自动发布 (`wp-release.yml`)
- 打 tag 时自动触发：`v*` 或 `x.y.z` 格式
- 流程：安装依赖 → PHPCS 检查 → i18n 生成 → 构建 ZIP → 创建 Release
- 需要在仓库 Settings → Secrets 中配置 `RELEASE_TOKEN`

### 7. 综合安全扫描 (`security-scan.yml`)
- Push/PR 到 main/master 时自动触发（依赖文件或 Dockerfile 变更）
- 每周一定时扫描
- Hadolint Dockerfile 规范检查
- Composer / npm / Go 依赖安全审计
- Trivy 容器镜像漏洞扫描
- 高危漏洞阻断合并

### 8. Renovate 依赖更新 (`renovate.yml`)
- 每周一、四凌晨 4 点自动运行
- 自动发现 WenPai-org 下所有仓库
- 检测 composer.json / package.json / go.mod 依赖更新
- patch 更新自动合并，minor/major 需审核
- 安全漏洞更新优先处理
- 需要配置 Secrets：`FORGEJO_URL`、`RENOVATE_TOKEN`
- 各仓库可放置 `renovate.json` 自定义策略（参考 `renovate-default.json`）

### 9. Stale Issue/PR 清理 (`stale-cleanup.yml`)
- 每周一凌晨 5 点自动运行
- Issue: 60 天无活动标记 stale，74 天自动关闭
- PR: 30 天无活动标记 stale，44 天自动关闭
- 排除 pinned / help-wanted / bug / security 标签
- 需要配置 Secret：`RELEASE_TOKEN`

### 10. Auto Label (`auto-label.yml`)
- PR 创建/更新时自动触发
- 根据文件类型打标签：php / frontend / go / ci/cd / dependencies / documentation / docker / style
- 根据 PR 变更量打大小标签：size/S / size/M / size/L / size/XL
- 标签不存在时自动创建（含预设颜色）
- 需要配置 Secret：`RELEASE_TOKEN`

## 使用方法

将需要的 `.yml` 文件复制到你的仓库的 `.forgejo/workflows/` 目录下即可。

```bash
# 示例：为你的仓库添加 gitleaks 扫描
mkdir -p .forgejo/workflows
curl -o .forgejo/workflows/gitleaks.yml \
  https://feicode.com/WenPai-org/ci-workflows/raw/branch/main/.forgejo/workflows/gitleaks.yml
git add .forgejo/workflows/gitleaks.yml
git commit -m "ci: 添加 gitleaks 密钥泄露扫描"
```
