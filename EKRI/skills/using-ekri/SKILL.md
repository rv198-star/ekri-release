---
name: using-ekri
description: Use when working with an existing codebase and deciding whether to initialize EKRI, refresh stale project knowledge, or query existing engineering knowledge before reading or changing more source code.
---

# Using EKRI

## 作用

`using-ekri` 是面向 AI Agent 的 EKRI 总入口。它只负责判断当前应该走哪个动作，不直接扫描整个项目，也不修改目标项目源码、配置、测试或其他业务文件。

可路由到三个动作：

- `ekri-init`：项目第一次接入 EKRI；
- `ekri-refresh`：项目已有 EKRI 知识，但代码版本已经变化，或已有知识可能过期；
- `ekri-query`：项目已有可用知识，需要回答当前工程问题。

## 什么时候使用

适合已有代码库、旧系统接手、持续维护、重构、迁移、较大范围修改，以及生成新实现前需要确认项目是否已有类似能力的场景。

对于一个很小、范围已经完全明确、无需理解项目其他部分的局部修改，可以直接进行普通工程工作，不必强制使用 EKRI。

## 路由规则

| 当前情况 | 动作 |
|---|---|
| 第一次在该项目使用 EKRI，或还没有可确认的 EKRI 项目状态 | `ekri-init` |
| 已有 EKRI 项目知识，但目标 Git 版本发生变化、知识被标记为过期，或当前问题依赖缺失/冲突知识 | `ekri-refresh` |
| 已有与当前 Git 版本匹配且可验证的项目知识，只需要回答工程问题 | `ekri-query` |
| 不确定已有知识是否仍然可用 | 先验证；如果版本或知识状态不匹配，转 `ekri-refresh` |

## 运行时位置

EKRI Skills 只提供 AI Agent 使用入口，EKRI 运行时仍保持独立安装。优先从环境变量 `EKRI_HOME` 解析 EKRI 发布根目录：

```text
EKRI_HOME=/path/to/ekri-release
```

如果 `EKRI_HOME` 不可用，也无法从 Agent 环境明确定位 EKRI 发布根目录，停止并要求提供安装位置。不要把 EKRI 运行时复制进目标业务项目来凑路径。

## 基本原则

1. 先确认目标仓库和 Git 版本，再消费项目知识。
2. 已有知识可复用时，不重新做大范围扫描。
3. 查询从 L0 开始，只有当前任务需要时才展开到 L1、L2、L3。
4. 没有搜索到结果，不等于项目里不存在对应能力。
5. 文件关系、调用关系、测试和配置都是证据，不会自动成为工程语义结论。
6. 发现知识缺失、过期或冲突时，转 `ekri-refresh`，不要在查询过程中偷偷制造新事实。
7. 当前任务所需信息已经足够时停止继续扩大探索范围。
8. 默认对目标项目只读；只有用户明确授权持久化 EKRI 知识资产时，才允许写入 `.EKRI/project/**`，并建议作为项目仓库资产提交。

## 输出

给出简短路由结果：

```text
动作：ekri-init | ekri-refresh | ekri-query | 普通工程工作
原因：为什么走这个动作
目标：本次要解决的工程问题
边界：当前不能据此证明什么
```

## 边界

`using-ekri` 不负责：

- 自动决定删除、合并或重构是否安全；
- 把检索结果升级成语义事实；
- 一次性建立完整项目模型；
- 替代当前工程任务本身的设计、实现或验证判断；
- 修改目标项目源码、配置、测试或其他业务文件；
- 未经用户明确授权写入任何 EKRI 项目知识资产。
