# 设计文档索引

| 文档 | 定位 | 何时读 |
|---|---|---|
| [decision-registry.md](decision-registry.md) | 编号决策唯一注册点（D/B/T/L）、规则引擎生命周期，永不删档 | 查任何编号决策；做新决策登记时 |
| [core-beliefs.md](core-beliefs.md) | 代理优先操作原则（怎么干活） | 接手项目、做技术选型、起争议时 |
| [competition-rules.md](competition-rules.md) | 大挑规则要点（带条款号）、参赛定位、类别选择、合规清单 | 写申报材料、排优先级、判断工作是否对题之前 |
| [../../ARCHITECTURE.md](../../ARCHITECTURE.md) | 分层、数据流、契约、能力分级 | 任何设计与实现之前 |
| [../09-project-application.md](../09-project-application.md) | 申报书底稿：三项创新、H1–H4、实验与标签设计（待团队按 competition-rules 的定位重写） | 对外介绍、比赛材料 |
| [../08-system-solution.md](../08-system-solution.md) | 目标系统方案：硬件分工、巡检包 v2、边缘推理、部署 | 硬件联调、协议升级、部署 |
| [../01-reference-research.md](../01-reference-research.md) | 立项调研：同类案例与论文精读 | 答辩时对比已有方案 |

## 文档规则

1. 参赛定位以 competition-rules.md 为准；创新点与硬件口径以 docs/09、docs/08 为准；README、AGENTS、ARCHITECTURE 与之保持一致
2. 编号文档可以删除，但删除前要把仍被代码或其他文档引用的内容迁到活文档、改掉引用，
   并在 `docs/exec-plans/README.md` 记下原文所在 commit
3. 新设计文档放本目录，描述性命名（如 `annotation-loop.md`），并在上表登记一行
4. 决策类内容不新开文档，追加进 [decision-registry.md](decision-registry.md)
5. 文档校验由 `backend/tests/test_docs.py` 机械执行：内部链接必须可解析
