# EKRI — Engineering Knowledge Reconstruction and Intelligence

**让 AI 不必每次重新“读懂整个项目”，而是基于一份可信、精简、持续更新的工程知识资产工作。**

EKRI（Engineering Knowledge Reconstruction and Intelligence）面向大型、长期演化的软件项目，将代码库中的工程事实、结构关系、已有能力、资产身份、所有权、生命周期、流程和变化信息，重建为一份可复用、可验证、可渐进展开的 **Project Engineering Knowledge Asset**。

它的目标不是保存“更多代码信息”，而是让 AI 在面对一个已有项目时，能够更快回答：

> 项目已经有什么？在哪里？为什么可信？当前版本还成立吗？为了这次任务还缺什么知识？

当前公开版本：**EKRI v1.1.0**。

---

## EKRI 解决什么问题

大型存量项目里，AI 很容易陷入一种高成本模式：每个新任务都重新搜索入口、顺调用链、猜模块职责、重新判断已有能力，再把大量源码塞进上下文。

EKRI 主要针对这些问题：

- **重复理解项目**：不同会话、不同 Agent 一遍遍重新摸索同一套结构和能力；
- **上下文浪费**：真正影响工程决策的信息很少，却需要读取大量无关实现细节；
- **知识漂移**：旧结论随着移动、重构、拆分和版本演化逐渐失效；
- **重复造轮子**：Agent 不知道项目已经存在某项 Capability，于是生成平行实现；
- **重构风险不可见**：只看到结构相似，却看不到消费者、owner、兼容面、生命周期和证据边界；
- **虚假确定性**：把 import、调用关系、测试、文档或搜索 miss 错误升级成业务或架构真相；
- **项目接手成本高**：在真正开始改代码之前，需要花大量时间建立基本工程认知。

EKRI 希望把这种一次性的认知成本，转化为长期可复用的工程知识基础设施。

---

## EKRI 是什么

EKRI 可以理解为 AI 软件工程中的一个 **Engineering Knowledge Substrate（工程知识底座）**。

它维护的不是完整源码副本，也不是一张永久 Code Graph，而是一份精简的、带证据和来源身份的工程知识资产。

这份知识资产具有几个核心特征：

- **精简**：长期保存高复用知识、稳定身份、证据指针和可信边界，而不是所有扫描中间结果；
- **渐进披露**：先回答“有没有、在哪里、归谁、有什么约束”，需要时再展开到实现、消费者和源码证据；
- **证据绑定**：知识绑定精确 Git commit / tree / blob 和可验证 evidence；
- **可感知新鲜度**：能够区分 exact、stale、unknown、conflicting、blocked，而不是假装旧知识永远有效；
- **技术栈无关**：核心知识模型不以 Java、Spring、Go、Python、React 等技术栈作为语义前提；
- **面向 Agent 消费**：优先服务 AI 查询、变更前判断、项目接手和工程分析，而不是把内部模型直接做成人类架构文档。

### EKRI 维护哪些工程知识

| Knowledge Family | 主要回答的问题 |
|---|---|
| **Architecture** | 系统的重要边界、职责与结构如何组织？ |
| **Capability** | 项目已经具备哪些能力？这些能力由什么实现？ |
| **Asset Identity** | 一个工程资产是谁，而不仅仅是“当前在哪个路径”？ |
| **Ownership Boundary** | owner / responsibility 有什么证据？哪些仍未确定？ |
| **Lifecycle Observation** | 资产当前被如何使用、维护、分发或兼容？ |
| **Evolution / Impact** | 什么发生了变化？哪些区域可能受影响？ |
| **Flow / Handoff** | 关键流程和交接关系如何发生？ |
| **Evidence / Authority** | 结论来自哪里？可信到什么程度？ |

EKRI 不把所有知识强行压成“事实”。它会显式保留 `observed`、`inferred`、`unknown`、`conflicting`、`stale` 等状态。

---

# 如何在一个已有项目里使用 EKRI

EKRI 推荐作为一个**独立的 scanner-control repository** 使用，不需要把 EKRI 源码复制进你的业务项目。

假设你的已有项目位于：

```text
/workspace/my-project
```

## 1. 安装 EKRI

推荐直接克隆公开发行仓库并固定到一个正式版本：

```bash
git clone https://github.com/rv198-star/ekri-release.git ~/.local/share/ekri
cd ~/.local/share/ekri
git checkout v1.1.0
```

`vX.Y.Z` tag 对应经过审计的精确分发版本。

也可以从 GitHub Release 下载 ZIP。若使用 ZIP，Formal Scanner 要求其 `EKRI/` implementation surface 处于一个已提交的 Git scanner-control repository 中，因此解压后需要初始化并提交：

```bash
git init
git add .
git commit -m "install EKRI v1.1.0"
```

当前验证环境以 **Python 3.12** 为准。

---

## 2. 先建立项目的可信 observation boundary

对任何已有 Git 项目，第一步都应先绑定精确源码身份，而不是直接开始大范围读代码：

```bash
python3 ~/.local/share/ekri/EKRI/scripts/validate_observation_boundary.py \
  --repository-root /workspace/my-project \
  --target-ref HEAD
```

这一步会：

- 解析目标项目的 exact commit / tree；
- 固定 EKRI scanner 自身的 Git provenance；
- 在正式 observation corpus 中排除 `EKRI/**` 和 `.EKRI/**`；
- 建立后续知识、证据和刷新操作的 source identity 基线。

如果只想检查而不写入项目本地 runtime state：

```bash
python3 ~/.local/share/ekri/EKRI/scripts/validate_observation_boundary.py \
  --repository-root /workspace/my-project \
  --target-ref HEAD \
  --no-write
```

EKRI 的本地运行状态默认放在目标项目的 `.EKRI/` 下；这与业务源码本身分离。

---

## 3. 如果项目已经有 EKRI Project Knowledge，优先复用，不要重新扫描

当目标项目已经存在 portable Project Knowledge，例如：

```text
/workspace/my-project/.EKRI/project/<asset-id>/
```

先验证它：

```bash
python3 ~/.local/share/ekri/EKRI/scripts/manage_project_assets.py verify \
  --repository-root /workspace/my-project \
  --asset-id <asset-id>
```

EKRI 会重新检查 source identity、artifact digest、evidence binding 和兼容性，而不是因为目录存在就信任它。

已有知识满足当前问题时，应直接复用；只有缺失、过期、冲突或被阻塞的部分才继续回源探索。

---

## 4. 按问题逐步查询，而不是一次性加载整个项目

当项目已经有对应 Capability knowledge 时，可以使用 Named Query：

```bash
python3 ~/.local/share/ekri/EKRI/scripts/query_capability.py \
  --repository-root /workspace/my-project \
  --source-tree <target-tree> \
  --query-kind find-capability \
  --query "path normalization"
```

找到能力后，可以继续查询 realization、authority 和 evidence，而不是重新从源码全文搜索：

```text
find-capability
→ get-realizations
→ explain-authority
→ get-evidence
```

Query miss **不代表不存在**。如果当前 Project Knowledge 不足，应该进入有边界的补充探索，而不是直接制造 absence 结论。

---

## 5. 对还没有完整 Project Knowledge 的项目怎么办

EKRI v1.1.0 已经提供：

- exact observation trust boundary；
- Project Knowledge v1/v2 verification；
- Architecture / Capability / Asset / Ownership / Lifecycle / Evolution / Flow 等知识契约与查询面；
- 面向 Agent 的 adaptive acquisition contracts，用于识别已有知识、知识缺口、预算和 bounded exploration。

但当前版本**没有提供一个“对任意项目执行一次命令，就自动重建全部工程知识”的万能扫描命令**。

推荐方式是由 Agent 根据当前任务，先查询已有知识，再只对 missing / stale / conflicting frontier 做有边界的探索，并将通过证据与 authority 校验的结果沉淀为 Project Knowledge。

这也是 EKRI 与传统“全库扫描生成报告”工具的重要区别。

---

# 在 Skills / Agent 环境中使用

很多 AI 编程环境使用 Skills、Agent instructions 或工具调用机制来组织能力。

**EKRI v1.1.0 当前没有发布一个可直接复制到 `~/.*/skills/` 的官方通用 `SKILL.md`。**

因此当前推荐的是 **Tool-backed Skill** 模式：

```text
你的 Agent / Skill
      │
      │ 调用 EKRI CLI / Python API
      ▼
独立 ekri-release scanner-control repo
      │
      │ source-bound observation / query / evidence
      ▼
你的已有项目
```

不要为了“安装 Skill”而把 EKRI 源码复制到业务项目里。

## 一个最小的 Skill / Agent 接入规则

你可以让自己的项目 Skill 或 Agent instruction 遵守下面的约定：

```text
处理已有项目时：

1. 先确定 target repository root 和 target ref。
2. 在大范围读取源码前，先运行 EKRI observation boundary。
3. 如果项目存在 .EKRI/project 资产，先 verify，再决定是否复用。
4. 优先查询已有 Capability / Architecture / Asset knowledge。
5. 只有 missing、stale、unknown 或 conflicting 的部分才继续回源。
6. 搜索 miss、import/call edge、测试或文档都不能自动升级成 semantic truth。
7. 新获得的知识必须保留 exact source identity、evidence 和 authority posture。
8. 当前任务已经 knowledge-sufficient 时停止探索，不做无边界全库扫描。
```

这类 Skill 负责**什么时候调用 EKRI**；EKRI 负责**什么知识已经存在、证据是什么、当前能相信到什么程度**。

未来如果提供正式的通用 EKRI Skill 安装包，它应当保持这一边界，而不是在 Skill 中维护另一套项目真相。

---

## 典型使用场景

### 接手一个陌生项目

先建立 exact source context，检查是否已有 Project Knowledge，然后优先了解关键 Capability、边界、owner、Flow 和 known unknowns，再根据任务逐步展开源码。

### 开发新功能前避免重复实现

先查询项目是否已经存在相同或相近 Capability，再查看 realization、evidence 和约束。只有确认现有能力不能满足需求后，才进入新增实现。

### 做存量代码重构

结合 Asset Identity、Ownership、Lifecycle、结构依赖和 evidence，先判断候选代码的真实职责与消费者，再决定是否值得进一步合并或拆分。

### 项目持续演化后的增量更新

新 commit 到来后，先判断已有知识是否仍绑定当前 target；只重建 stale / missing / changed frontier，不必重新扫描整个项目。

---

## 当前边界

EKRI 当前不声称：

- 已经穷尽整个项目的所有工程知识；
- 搜索 miss 可以证明某能力不存在；
- import / call / Git history 可以直接决定 semantic ownership；
- 可以自动批准 safe delete、merge 或 refactor；
- 可以替代业务 owner、架构评审或生产审批；
- 已提供一个对任意技术栈都能自动完成全项目语义重建的一键扫描器。

EKRI 更基础也更重要的目标是：

> **让 AI 面对一个长期演化的软件项目时，先复用一份可信工程知识资产，再只探索真正不知道的部分。**

---

## 下载与版本

公开发行仓库：

- `https://github.com/rv198-star/ekri-release`

当前版本：

- **EKRI v1.1.0**
- GitHub Release：`https://github.com/rv198-star/ekri-release/releases/tag/v1.1.0`

每个正式 Release 提供：

```text
ekri-vX.Y.Z-release-pack.zip
EKRI_RELEASE_PACK_MANIFEST.json
SHA256SUMS
```

`vX.Y.Z` public tag 固定该版本经过审计的精确分发内容；`main` 可以继续改进产品 README、Changelog 等展示层，不会移动已经发布的版本 tag。

版本变化请看：[CHANGELOG.md](./CHANGELOG.md)

更底层的产品/runtime文档保留在 `EKRI/` 目录中。
