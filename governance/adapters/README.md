# Domain adapters

这里放领域自己的只读探针；核心审计不硬编码业务名词。适配器不得修复、部署、迁移或写外部系统，只向标准输出写一个 JSON 对象：

```json
{
  "schema_version": 1,
  "issues": [
    {
      "severity": "WARN",
      "code": "DOMAIN_FACT_DRIFT",
      "subject": "stable-domain-key",
      "message": "观察到的事实与领域目录不一致",
      "remediation": "核对事实源并更新对应目录",
      "accountable": true
    }
  ]
}
```

命令按 argv 数组直接执行，不经过 shell；超时范围为 1–300 秒。完整字段见 [`docs/SCHEMAS.md`](../../docs/SCHEMAS.md)。
