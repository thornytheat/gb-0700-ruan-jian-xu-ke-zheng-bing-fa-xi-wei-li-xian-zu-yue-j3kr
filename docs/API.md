# 接口

`POST /api/run`：{"text":"CSV内容"}。同规则版本与输入摘要只产生一条批次。

`GET/POST /api/1` 至 `/api/7`：独立样例或自定义文件计算。各模块返回 report、quarantine、balance。

`POST /api/review`：id、整数revision、decision取通过或退回。旧版本409；阻断项不能通过。

`GET /api/export/{id}`：唯一证据CSV。manifest行含切换合并摘要与真实/名义峰值；failover_window、failover_merge行给出与工作台一致的切换裁决结论，merge行sources含双侧原始行号。`GET /health`：存活检查。

错误：结构/数值422，版本冲突409，不存在404，文件过大413，写入失败500（保留旧版）。逐行异常进入quarantine。
