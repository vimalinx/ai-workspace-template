# Assets

这里记录“有哪些资产、由谁负责、如何连接、凭据存放在哪里”，不记录 secret 值、cookie、token 或账号数据。

机器可读的位置、责任、跟踪和移动边界统一登记到 [`catalog.toml`](catalog.toml)。允许的种类：

- `secret-location`：只记凭据位置，不记内容；通常 `tracked=false`、`movable=false`。
- `private-runtime`：不可提交的本地运行数据。
- `rebuildable-runtime`：可重建缓存或输出。
- `managed-asset`：工作区正式管理的素材或数据。
- `external-pointer`：外部系统中的资产指针。

运行状态属于治理 catalog，真实探针属于证据；不要在资产台账里复制动态状态。
