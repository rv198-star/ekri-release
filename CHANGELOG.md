# EKRI Changelog

本文件记录 EKRI 对外产品能力、兼容性边界和公开分发方式的主要变化。

底层 schema / runtime 级完整历史仍可参考 `EKRI/CHANGELOG.md`；这里以中文为主，面向使用者说明每个公开版本“增加了什么、解决了什么、边界在哪里”。

---

## v1.1.1 — 2026-08-14

### 版本主题

**补齐官方 AI Agent Skills 入口，并把只读权限和项目知识兼容规则正式纳入发布边界。**

v1.1.0 已经具备 EKRI runtime、CLI、Python API 和自适应知识获取能力，但没有把面向 AI Agent 的 Skills 作为正式发布面。这意味着用户虽然拿到了 EKRI，本身却缺少标准的 Agent 使用入口。

v1.1.1 修复这个发布级缺口。

### 新增 4 个官方 Skills

```text
using-ekri
  总入口：判断当前应该 init / refresh / query

ekri-init
  第一次把已有项目接入 EKRI

ekri-refresh
  项目发生变化后，只刷新需要重新确认的知识

ekri-query
  按 L0 → L3 渐进查询已有工程知识
```

Skills 的职责按用户动作划分，而不是把 EKRI 内部模块或知识类型逐个映射成 Skill。

### Skills 主要面向 AI Agent

这 4 个 Skills 是 AI Agent 的使用入口，不是给人手工执行的一套固定工程流程。

Agent 通过 Skills 判断什么时候应该使用 EKRI、查询到什么层级，以及什么时候应该停止继续扩大源码探索范围。

### 目标项目默认只读

v1.1.1 正式冻结 Skills 对业务项目的权限边界：

```text
默认：read-only
```

Skills 不允许：

- 修改业务源码；
- 修改配置；
- 修改测试；
- 自动执行重构；
- 自行提交 Git。

唯一允许的项目内写入例外是：

> 用户明确授权持久化 EKRI 项目知识资产。

此时 `ekri-init` / `ekri-refresh` 只允许写入：

```text
<project-root>/.EKRI/project/**
```

并建议将该目录作为项目工程资产纳入 Git 版本管理。

`ekri-query` 始终保持严格只读。

### Skill 安装器

新增：

```text
EKRI/scripts/install_ekri_skills.py
```

支持：

- `--check`：验证发布包里的 4 个官方 Skills；
- `--list`：列出 Skills；
- `--target-dir`：把完整 Skill 目录安装到调用方指定的 Agent Skills 根目录；
- `--force`：明确要求时替换已有 EKRI Skill 目录。

安装单位是**完整 Skill 目录**，不是只复制单个 `SKILL.md`。

### 独立运行时定位

安装后的 Skills 通过 `EKRI_HOME` 定位独立 EKRI runtime：

```text
EKRI_HOME=/path/to/ekri-release
```

如果无法确定 EKRI 安装位置，Skill 应停止并要求提供路径，而不是把 EKRI runtime 复制进业务项目来凑目录结构。

### 版本兼容列表

新增机器可读兼容表：

```text
EKRI/specs/version-compatibility.json
```

兼容判断以 **Project Knowledge 资产结构代** 为主要边界：

- 资产结构未发生不兼容变化 → 保持同一兼容代；
- 资产结构发生不兼容变化 → 必须开启新的兼容代；
- 新版本可以保留对旧资产的向后读取，但这不等于跨兼容代“完全兼容”。

当前兼容关系：

```text
project-knowledge-layout-g1
  v0.9.0
  v1.0.0
  current asset schema: ekri.project-knowledge-asset.v1

project-knowledge-layout-g2
  v1.1.0
  v1.1.1
  current asset schema: ekri.project-knowledge-asset.v2
  backward readable: ekri.project-knowledge-asset.v1
```

因此：

```text
v1.1.0 ↔ v1.1.1：完全兼容
v1.0.0 ↔ v1.1.1：不声明完全兼容
```

### 保持不变

v1.1.1 是使用入口和发布面的 hotfix，不改变 EKRI 已冻结的工程知识语义：

- major semantic writer paths 仍为 **6**；
- primary semantic families 仍为 **7**；
- Project Knowledge v2 资产结构不变；
- v1.1 Adaptive Knowledge Acquisition 的 authority 边界不变；
- No Active Self-Scan 不变；
- `unknown` / `conflicting` / evidence 边界不变。

### 发布验证

v1.1.1 经过：

- Python 3.12.13 EKRI tests：**362 / 362 PASS**；
- Phase3 bootstrap：**4 / 4 PASS**；
- v1.1.1 Release Gate：PASS；
- official Skills：**4 / 4 valid**；
- tracked secret scan：PASS；
- release-pack audit：PASS；
- extracted distribution Gate：PASS；
- `v1.1.0 ↔ v1.1.1` compatibility：fully compatible。

正式 release pack：

```text
ZIP size:    478,933 bytes
ZIP SHA-256: 7751d53da409bf43675fd947a259fdc1bb640b52c06fa9d6bffb7a4c1506aa30
```

---

## v1.1.0 — 2026-08-14

### 版本主题

**让 Agent 不再默认从零扫描项目，而是先判断已有工程知识是否足够，只补真正缺失、过期或冲突的部分。**

### 主要变化

- 增加面向任务的知识充分性判断；
- 根据当前任务和已有知识动态生成有限探索计划；
- 探索只形成候选知识，不直接获得语义权威；
- 支持有限的 assess → acquire → challenge → reconcile → re-assess 循环；
- Project Knowledge Asset v2 支持部分知识族、稳定 identity、source-contract provenance 与 family availability / authority posture；
- 同一套探索原则在 service、interaction-client、data-pipeline 三类不同项目形态上通过验证，没有引入技术栈 Profile 目录。

### 计划级复用收益验证

同一个 target、同一组 7 个工程知识问题：

```text
从零开始：7 个问题 → 7 个探索缺口 → 7 个计划片段
复用已有 Project Knowledge：6 个问题直接复用，仅 1 个缺口继续探索
```

计划上限：

```text
planned slices             7 → 1
planned tool-call ceiling  7 → 1
planned source expansions 28 → 4
```

这里证明的是计划级探索收敛，不宣称真实 token、耗时或金额节省。

### 保持不变

- major semantic writer paths：**6**；
- primary semantic families：**7**；
- Capability 单一 authority 不变；
- Flow 没有 peer truth store；
- `unknown` / `conflicting` / evidence 边界保持不变；
- Project Knowledge Asset v1 继续支持。

### 重要边界

v1.1.0 不提供：

- 技术栈 Profile 矩阵；
- 一条命令读懂任意项目的万能扫描器；
- 自动 safe-delete / merge / refactor 决策；
- autonomous semantic authority；
- UAT / production readiness / owner approval。

### 发布方式变化

从 v1.1.0 开始，EKRI 使用独立公开分发仓库：

```text
rv198-star/ekri-release
```

source identity 与 public distribution identity 分离。

v1.1.0 正式 release pack：

```text
ZIP size:    451,147 bytes
ZIP SHA-256: 317ccbd13db697b6f87f4be92cb0c050aaacdf44a20feeb790e221476debb00e
```

---

## v1.0.0 — 2026-08-13

### 版本主题

**建立第一版稳定的 Engineering Knowledge System，并把项目知识从临时扫描结果提升为有身份、有证据、有权威边界的工程资产。**

### 主要能力

- 分级的工程知识模型；
- Architecture View 与 source / evidence / claim ceiling 绑定；
- Capability Semantic Authority；
- L0–L3 Capability 查询；
- bounded Flow / Handoff query；
- Repository Asset Identity；
- Ownership Boundary；
- Lifecycle Observation；
- Evolution / Impact Intelligence；
- Portable Project Knowledge；
- 显式 `conflicting` 状态；
- non-WFF conformance。

### 核心治理变化

- Capability semantic authority 从旧 Catalog writer 切换到 ontology-authoritative Capability slice；
- Query Index / legacy Catalog 降为派生兼容面；
- 禁止 peer dual-write、双向 semantic synchronization 和 silent authority fallback。

---

## v0.9.0 — 2026-08-12

### 版本主题

**把 EKRI 从内部工程能力整理为独立版本化、独立发布治理的产品线。**

### 主要变化

- 独立 EKRI product version；
- 独立 `ekri/vX.Y.Z` source tag namespace；
- 独立 Changelog / Release Gate / claim ceiling；
- Portable Project Knowledge；
- Repository Asset Identity / Ownership / Lifecycle 的早期稳定能力；
- 明确产品版本、资产结构版本、scanner implementation version、target project version 是不同身份。
