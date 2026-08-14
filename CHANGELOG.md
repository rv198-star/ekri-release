# EKRI Changelog

本文件记录 EKRI 对外产品能力、兼容性边界和公开分发方式的主要变化。

底层 schema / runtime 级完整历史仍可参考 `EKRI/CHANGELOG.md`；这里以中文为主，面向使用者说明每个公开版本“增加了什么、解决了什么、边界在哪里”。

---

## v1.1.0 — 2026-08-14

### 版本主题

**Adaptive Knowledge Acquisition：让 Agent 不再默认从零扫描项目，而是先判断已有工程知识是否足够，只补真正缺失、过期或冲突的部分。**

### 新增

- **Mission Context**：把当前任务、目标 Git source identity、已有 Project Knowledge、预算和探索约束绑定到同一个上下文。
- **Knowledge Sufficiency Assessment**：在开始读更多源码前，先判断已有知识是否已经足以回答当前问题。
- **Mission Exploration Plan**：由 Agent 根据任务、已有知识和项目环境动态生成一次性探索计划，而不是维护 Java / Go / Python 等长期技术栈 Profile。
- **通用 Exploration Operators**：使用 entrypoint、contract、state/data、flow、freshness、ownership 等工程级操作符表达探索目标。
- **Evidence Receipt**：新增 source-bound acquisition evidence receipt，探索结果继续绑定 exact Git source。
- **Bounded WAE Loop**：支持 assess → acquire → challenge → reconcile → re-assess 的有限迭代，并要求显式 stop / return / blocked 条件。
- **Candidate Knowledge Delta**：探索结果先形成非权威候选增量，再路由到已有 family authority，不允许探索计划直接写 semantic truth。
- **异构 Conformance**：同一套 Constitution / Plan / WAE contract 在 service、interaction-client、data-pipeline 三类不同项目形态上通过验证，没有引入技术栈 Profile 目录。
- **Project Knowledge Asset v2**：支持部分 family、producer/target/source-contract identity、stable semantic namespace，以及 family availability / authority posture。

### 实际收益验证

在同一个已知 target、同一组 7 个工程知识问题上：

```text
从零开始：7 个问题 → 7 个 exploration gaps → 7 个 planned slices
复用已有 Project Knowledge：6 个问题直接复用，仅 1 个 Architecture gap 继续探索
```

对应的计划上限：

```text
planned slices             7 → 1
planned tool-call ceiling  7 → 1
planned source expansions 28 → 4
```

这里证明的是 **planned exploration economy**，不宣称真实 token、耗时或金额节省。

### 保持不变

v1.1 没有重写 v1.0 已冻结的 Engineering Knowledge System：

- major semantic writer paths 仍为 **6**；
- primary semantic families 仍为 **7**；
- Capability 的单一 authority 与旧 writer retirement 保持不变；
- Flow 仍然没有 peer truth store；
- `unknown` / `conflicting` / evidence / authority 边界保持不变；
- Project Knowledge Asset v1 继续兼容。

### 重要边界

v1.1 不提供：

- 技术栈 Profile 矩阵；
- 对任意项目“一条命令重建全部工程知识”的万能扫描器；
- Human Projection 产品；
- 自动 safe-delete / merge / refactor 决策；
- autonomous semantic authority；
- UAT / production readiness / owner approval。

### Skills / Agent 接入现状

v1.1.0 **尚未提供官方通用 `SKILL.md` 安装包**。

当前推荐方式是 **Tool-backed Skill**：Agent / Skill 保持自己的任务触发与交互逻辑，通过 EKRI CLI / Python API 查询和刷新工程知识；EKRI 自身作为独立 scanner-control repository 使用，不复制进业务项目。

### 发布方式变化

从 v1.1.0 开始，EKRI 正式拥有独立公开分发仓库：

```text
rv198-star/ekri-release
```

source identity 与 public distribution identity 分离：

```text
source tag:  software-lifecycle-skills / ekri/v1.1.0
public tag:  ekri-release / v1.1.0
Release:     ZIP + EKRI_RELEASE_PACK_MANIFEST.json + SHA256SUMS
```

v1.1.0 正式 Release pack：

```text
ZIP size:    451,147 bytes
ZIP SHA-256: 317ccbd13db697b6f87f4be92cb0c050aaacdf44a20feeb790e221476debb00e
```

---

## v1.0.0 — 2026-08-13

### 版本主题

**建立第一版稳定的 Engineering Knowledge System，并把“项目知识”从临时扫描结果提升为有身份、有证据、有 authority 边界的工程资产。**

### 主要能力

- rich-but-shallow Engineering Knowledge Model；
- Architecture View 与 source/evidence/claim-ceiling 绑定；
- Capability Semantic Authority；
- Capability Named Queries：`find_capability`、`get_realizations`、`explain_authority`、`get_evidence`；
- bounded Flow / Handoff query；
- Repository Asset Identity；
- Ownership Boundary；
- Lifecycle Observation；
- Evolution / Impact Intelligence；
- Portable Project Knowledge；
- 显式 `conflicting` knowledge posture；
- non-WFF conformance，用于证明模型不依赖单一宿主项目语义。

### 核心治理变化

- Capability semantic authority 从旧 Catalog writer 切换到 ontology-authoritative Capability slice；
- Query Index / legacy Catalog 等降级为 derived compatibility surface；
- 禁止 peer dual-write、双向 semantic synchronization 和 silent authority fallback。

### 版本边界

v1.0 不声称：

- 通用 ontology 已穷尽所有工程知识类型；
- 可以自动判断删除、退休、所有权或生产审批；
- 所有 Flow / Decision / Claim / runtime trace 都已经产品化。

---

## v0.9.0 — 2026-08-12

### 版本主题

**把 EKRI 从宿主项目中的内部工程能力，正式整理为独立版本化、独立 release governance 的产品线。**

### 主要变化

- 独立 EKRI product version；
- 独立 `ekri/vX.Y.Z` source tag namespace；
- 独立 Changelog / Release Gate / claim ceiling；
- Portable Project Knowledge；
- Repository Asset Identity / Ownership / Lifecycle 的早期稳定能力；
- 明确 product version、schema version、scanner implementation version、target project version 是不同身份。

v0.9 是独立产品治理的起点，v1.0 才完成 Engineering Knowledge System 的第一版稳定语义架构。
