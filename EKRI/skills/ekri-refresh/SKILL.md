---
name: ekri-refresh
description: Use when a project already has EKRI knowledge but the target Git version changed, knowledge may be stale, or a current task exposes missing or conflicting knowledge that should be refreshed without rescanning the whole repository.
---

# EKRI Refresh

## 作用

`ekri-refresh` 面向 AI Agent，用于**让已有 EKRI 项目知识重新对齐当前代码版本**。默认对目标项目只读，不修改源码、配置、测试或其他业务文件。

它不是“重新扫描一次项目”。默认策略是：

> 先确认哪些旧知识还能继续使用，只刷新已经变化、过期、缺失或冲突的部分。

## 什么时候使用

- 项目已经有 `.EKRI/project/**`；
- 当前 Git commit / tree 与已有知识绑定的版本不同；
- `ekri-query` 发现所需知识已经过期；
- 当前任务需要的信息在已有知识里缺失；
- 不同证据对同一工程结论产生冲突；
- 大范围重构、迁移或版本升级后，需要重新确认受影响区域。

第一次接入项目时使用 `ekri-init`。

## 运行时前置

先确认 `EKRI_HOME` 指向独立安装的 EKRI 发布根目录。如果无法定位 EKRI 运行时，停止并要求提供安装位置，不要把 EKRI 复制进目标业务项目。

如果已有知识资产来自不同 EKRI 产品版本，先用版本兼容清单判断是否属于同一资产结构兼容代；不同兼容代不直接声明完整兼容。

## 执行步骤

### 1. 确认当前目标版本

先运行观察边界验证，拿到当前 commit / tree：

```bash
python3 "$EKRI_HOME/EKRI/scripts/validate_observation_boundary.py" \
  --repository-root <project-root> \
  --target-ref <ref> \
  --no-write
```

### 2. 验证已有知识

找到候选项目知识资产并验证：

```bash
python3 "$EKRI_HOME/EKRI/scripts/manage_project_assets.py" verify \
  --repository-root <project-root> \
  --asset-id <asset-id>
```

不要仅根据目录名或文件存在就认为知识有效。

### 3. 比较旧版本与当前版本

确定：

- 哪些知识仍绑定相同且有效的证据；
- 哪些相关源码、配置、接口或资源发生变化；
- 哪些知识需要重新确认；
- 当前任务是否暴露新的缺口或冲突。

优先使用 Git 变化范围缩小刷新边界，不默认全库重建。

### 4. 只刷新需要刷新的部分

按当前任务的重要性和知识缺口选择有限探索范围。

可以使用现有 EKRI 的项目资产、能力查询、资产关系、流程和变化分析入口；如果某类知识没有安全的写入/提升路径，就保留为缺口或候选，不要自行创建第二套事实来源。

### 5. 重新验证

刷新后重新检查目标身份、知识来源和仍未解决的问题。只有经过对应知识边界验证的结果才可以成为后续查询的项目知识。

## 知识资产持久化

默认只返回哪些知识仍可复用、哪些已经过期、需要补充什么证据，不写入目标项目。

如果用户明确授权保存刷新后的 EKRI 知识资产，唯一允许的项目内写入范围是：

```text
<project-root>/.EKRI/project/**
```

保存后应建议用户把该目录作为项目工程资产纳入 Git 版本管理。Skill 不自行提交 Git，也不修改 `.EKRI/project/**` 之外的项目内容。

## 完成条件

- 当前 commit / tree 已明确；
- 已有知识中可复用与需刷新部分已经区分；
- 当前任务所依赖的过期/缺失/冲突知识得到处理，或被明确保留为未解决；
- 未发生无必要的全库重新扫描；
- 没有因为刷新动作扩大语义结论的可信范围。

## 后续路由

刷新完成后回到 `ekri-query`。

## 边界

`ekri-refresh` 不自动证明：

- 改动影响已经穷尽；
- 未变化文件的业务语义一定没有变化；
- 某资产可以安全删除或退休；
- 某项重构已经安全完成；
- 未经用户授权写入 `.EKRI/project/**`；
- 修改目标项目源码、配置、测试或其他业务文件。
