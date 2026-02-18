# WordPress 插件 CI 修复设计

## 背景
wp-plugin-ci.yml 已部署到 4 个 WP 插件仓库，wpslug CI 绿，其他 3 个因 phpcs 错误失败。

## 问题
- wenpai-updater: 202 errors (1 file)
- wp-woocommerce-pay: 3764 errors (19 files)
- wpbridge: 18097 errors (90 files)

## 方案
phpcbf 自动修复格式 + phpcs.xml 排除不适用规则，参考 wpslug 成功模式。

## 每个仓库的修复步骤
1. clone 到本地
2. phpcbf 自动修复（缩进、空格、换行等）
3. 分析剩余错误，创建 phpcs.xml
4. 确认 phpcs 零 error + parallel-lint 通过
5. commit + push

## phpcs.xml 模板
基于 WordPress-Extra，warning-severity=0，排除 vendor/node_modules/tests/lib，按项目排除不适用规则。

## 顺序
1. wenpai-updater（最小）→ 2. wp-woocommerce-pay → 3. wpbridge（最大）
