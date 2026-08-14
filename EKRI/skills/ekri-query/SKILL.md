---
name: ekri-query
description: Use when a project already has usable EKRI knowledge and the current engineering task needs a progressive L0-L3 answer about existing capabilities, implementation locations, relationships, constraints, flow, or exact evidence before reading more source code.
---

# EKRI Query

## 作用

`ekri-query` 面向 AI Agent，用于**查询已经建立的项目工程知识**。它对目标项目严格只读，不修改源码、配置、测试或 EKRI 项目知识资产。

默认从最小信息开始，只有当前任务真正需要时才继续展开：

```text
L0  定位：有没有？是什么？
L1  实现：在哪里？由哪些实现承载？
L2  关系与约束：谁负责？有哪些依赖、边界和限制？
L3  证据：为什么这样判断？精确来源在哪里？
```

## 什么时候使用

- 开发新功能前确认项目是否已有类似能力；
- 接手模块时定位已有实现和相关工程边界；
- 修问题时确认能力、流程和实现位置；
- 重构前查看使用方、依赖、责任和约束；
- 需要核实某条项目结论的证据来源；
- 希望避免为了一个局部问题读取大量无关源码。

如果项目还没有 EKRI 起点，使用 `ekri-init`。如果知识与当前 Git 版本不匹配、过期、缺失或冲突，转 `ekri-refresh`。

## 运行时前置

先确认 `EKRI_HOME` 指向独立安装的 EKRI 发布根目录。如果无法定位 EKRI 运行时，停止并要求提供安装位置，不要把 EKRI 复制进目标业务项目。

## 查询原则

1. 查询前确认项目知识对应当前目标 Git 版本。
2. 从 L0 开始，不默认展开完整实现和证据。
3. 命中后按当前任务需要逐层展开。
4. 查询未命中只表示“当前知识没有确认”，不能证明项目里不存在。
5. 对过期或冲突知识不继续向上做确定性推论，转 `ekri-refresh`。
6. 查询不直接写入新的语义事实。
7. `ekri-query` 永远不写目标项目；如果发现知识需要更新，转 `ekri-refresh`，并由后者在取得用户明确授权后决定是否持久化 EKRI 知识资产。

## Capability 查询

### L0：定位已有能力

```bash
python3 "$EKRI_HOME/EKRI/scripts/query_capability.py" \
  --repository-root <project-root> \
  --source-tree <git-tree> \
  --query-kind find-capability \
  --query "<要查找的能力>"
```

### L1：查看实现落点

```bash
python3 "$EKRI_HOME/EKRI/scripts/query_capability.py" \
  --repository-root <project-root> \
  --source-tree <git-tree> \
  --query-kind get-realizations \
  --capability-id <capability-id>
```

### L2：查看责任、边界和约束

```bash
python3 "$EKRI_HOME/EKRI/scripts/query_capability.py" \
  --repository-root <project-root> \
  --source-tree <git-tree> \
  --query-kind explain-authority \
  --capability-id <capability-id>
```

### L3：查看精确证据

```bash
python3 "$EKRI_HOME/EKRI/scripts/query_capability.py" \
  --repository-root <project-root> \
  --source-tree <git-tree> \
  --query-kind get-evidence \
  --capability-id <capability-id>
```

## Flow 查询

当问题涉及流程、交接或执行路径时，可以使用 `trace_flow.py`，并同样从较低披露层级开始：

```bash
python3 "$EKRI_HOME/EKRI/scripts/trace_flow.py" --help
```

只在需要确认具体来源时展开到 L3。

## 推荐回答格式

向用户或上层 Agent 返回：

```text
结论：当前项目知识能确认什么
层级：L0 | L1 | L2 | L3
来源版本：commit / tree
仍未知或冲突：有哪些
是否需要继续展开：是 / 否；若是，为什么
```

## 边界

`ekri-query` 不负责：

- 因为查询 miss 就宣布能力不存在；
- 根据调用关系自动决定 semantic owner；
- 在查询过程中静默刷新过期知识；
- 自动决定是否删除、合并、迁移或重构；
- 用 L0/L1 的简要结果冒充 L3 证据结论；
- 修改目标项目源码、配置、测试或 `.EKRI/project/**`。
