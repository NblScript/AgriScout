# 设计文档索引

| 文档 | 定位 | 何时读 |
|---|---|---|
| [decision-registry.md](decision-registry.md) | 编号决策唯一注册点（D/B/T/L），永不删档 | 查任何编号决策；做新决策登记时 |
| [core-beliefs.md](core-beliefs.md) | 代理优先操作原则（怎么干活） | 接手项目、做技术选型、起争议时 |
| ../01-reference-research.md | 立项调研：3 案例精读 + 论文要点 + 设计启示 | 写申报书/PPT、讲故事时 |
| ../04-master-plan.md | **唯一权威计划**：架构/契约/分级/里程碑 | 任何设计与实现之前（§7 契约、§8 分级） |
| ../05-discussion-decisions.md | 决策讨论全文：问题→选项→权衡→结论 | 追溯某个决策为什么这么定 |
| ../06-embedded-learning-roadmap.txt | 成员 A 嵌入式学习路线（P0/P1） | 硬件线相关分工 |
| ../07-project-introduction.md | 项目详细介绍（申报书/PPT 底稿） | 对外介绍、比赛材料 |

## 新增文档规则

1. 编号文档（01-07）**不改号不删除**——代码注释引用 §7.2/§8.1 等小节号作为契约锚点
2. 新设计文档放本目录，描述性命名（如 `annotation-loop.md`），并在上表登记一行
3. 决策类内容不新开文档，追加进 [decision-registry.md](decision-registry.md)
4. 文档校验由 `backend/tests/test_docs.py` 机械执行：内部链接必须可解析
