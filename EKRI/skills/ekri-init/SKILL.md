---
name: ekri-init
description: Use when an existing codebase is being connected to EKRI for the first time and needs an exact Git-bound starting point, existing-knowledge discovery, and a bounded first exploration plan without trying to understand the whole project at once.
---

# EKRI Init

## 作用

`ekri-init` 面向 AI Agent，用于**第一次把一个已有项目接入 EKRI**。默认对目标项目只读，不修改源码、配置、测试或其他业务文件。

它的目标不是“一次扫完整个项目”，而是建立一个可信的起点：

1. 明确当前项目和 Git 版本；
2. 建立 EKRI 的观察边界；
3. 检查项目是否已经存在可复用的 EKRI 知识；
4. 根据当前任务判断还缺哪些知识；
5. 只为第一轮真正需要的缺口安排有限探索。

## 什么时候使用

- 第一次在一个已有项目中使用 EKRI；
- 接手一个陌生或长期维护的项目，准备先建立可靠项目认知；
- 项目里没有可确认的 `.EKRI/project/**` 知识资产；
- 不确定之前留下的 EKRI 状态是否属于当前仓库或当前版本。

如果项目已有可验证知识，只是代码版本已经变化，使用 `ekri-refresh`。

## 运行时前置

先确认 `EKRI_HOME` 指向独立安装的 EKRI 发布根目录。如果无法定位 EKRI 运行时，停止并要求提供安装位置，不要把 EKRI 复制进目标业务项目。

## 执行步骤

### 1. 确认目标仓库

确认目标路径是 Git 仓库根目录，并确定本次目标 ref，默认使用 `HEAD`。

### 2. 建立可信观察边界

运行：

```bash
python3 "$EKRI_HOME/EKRI/scripts/validate_observation_boundary.py" \
  --repository-root <project-root> \
  --target-ref <ref> \
  --no-write
```

必须保留解析出的 commit / tree。若观察边界失败，停止，不继续建立项目知识。

### 3. 发现已有知识

检查 `<project-root>/.EKRI/project/`。

- 如果存在候选资产，不要直接相信目录内容；先验证其 source identity 和资产完整性。
- 如果资产与当前目标精确匹配，可以转为复用，而不是重新初始化。
- 如果资产存在但目标版本已经变化，转 `ekri-refresh`。

### 4. 明确第一次要解决的问题

首次接入不以“覆盖整个项目”为完成标准。根据当前使用目的提出少量工程问题，例如：

- 项目主要边界是什么？
- 当前任务涉及哪些已有能力？
- 相关实现和关键入口在哪里？
- 哪些知识目前仍未知或证据冲突？

### 5. 建立第一轮有限探索

优先获取能够约束后续理解、复用价值高、与当前任务直接相关的知识。

探索可以使用 Git、搜索、符号关系、配置、测试等证据，但这些机械结果不能直接成为语义事实。

当第一轮问题已经足够支持当前任务时停止，不为了“初始化完成”继续扩大扫描。

## 知识资产持久化

默认只返回分析结果、知识缺口和建议，不写入目标项目。

如果用户明确授权保存 EKRI 知识资产，唯一允许的项目内写入范围是：

```text
<project-root>/.EKRI/project/**
```

保存后应建议用户将该目录作为项目工程资产纳入 Git 版本管理。Skill 不自行提交 Git，也不修改 `.EKRI/project/**` 之外的项目内容。

## 完成条件

至少满足：

- 目标 commit / tree 已确认；
- EKRI 自身没有进入目标观察语料；
- 已发现并处理已有项目知识；
- 当前任务需要的知识缺口已经显式；
- 没有把未覆盖区域伪装成“已经理解”。

## 后续路由

- 日常查询：`ekri-query`
- 项目代码变化或知识过期：`ekri-refresh`

## 边界

`ekri-init` 不承诺：

- 一次性读懂整个项目；
- 建立所有 Knowledge Family；
- 证明“没有发现”的能力一定不存在；
- 自动完成架构、所有权、删除或重构决策；
- 未经用户授权写入 `.EKRI/project/**`；
- 修改目标项目源码、配置、测试或其他业务文件。
