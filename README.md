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

### 3. WordPress 插件自动发布 (`wp-release.yml`)
- 打 tag 时自动触发：`v*` 或 `x.y.z` 格式
- 流程：安装依赖 → PHPCS 检查 → i18n 生成 → 构建 ZIP → 创建 Release
- 需要在仓库 Settings → Secrets 中配置 `RELEASE_TOKEN`

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
