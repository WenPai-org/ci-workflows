# Renovate Bot 自托管设计

## 方案
ci-workflows 仓库单个 cron workflow + autodiscover，自动覆盖所有原创仓库。

## 架构
- Workflow: `.forgejo/workflows/renovate.yml`，每周一凌晨 3 点
- 全局配置: `renovate-global.json`（self-hosted 配置）
- 仓库默认配置: `renovate-default.json`（已有）
- 运行方式: npx renovate，Runner host 模式

## 配置
- platform: forgejo, endpoint: feicode.com
- autodiscover + filter: WenPai-org/*, Windfonts/*, feibisi/*
- 镜像仓库自动跳过
- patch 自动合并，minor/major 需审核
- fetchChangeLogs: off（VM 无法直连 GitHub）

## 覆盖范围
24 个原创仓库：PHP(composer) / Go(gomod) / JS/TS(npm) / Python(pip)

## 注意事项
- 首次运行创建 onboarding PR
- 各仓库可放 renovate.json 覆盖或禁用
- Runner 需要 Node.js
