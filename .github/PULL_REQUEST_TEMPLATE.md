## 摘要

<!-- 改了什么、为什么改。协议/Gold/split 变更必须写明。 -->

## 验证

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
```

其它命令（如有）：

## 检查

- [ ] 没有提交 `outputs/`、`tmp-*/`、`*.duckdb`、`.env`、hidden pack 或 Gold 私有报告
- [ ] 没有关闭或绕过 SQL Guard、权限检查、脱敏或行数上限
- [ ] 没有把 `C360_0001–0020` 改标为 hidden/private
- [ ] 没有把 TemplateAgent 标成官方 Baseline
- [ ] 若改了契约/CLI/口径，已同步文档和测试
- [ ] 若改了 Gold 或评分规则，已更新版本并说明原因
