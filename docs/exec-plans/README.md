# 执行计划（Execution Plans）

执行计划是仓库的一等工件：跨会话工作的记忆载体。全部提交进 git。

## 什么时候需要执行计划

- **需要**：跨多次会话、多文件、有外部依赖（训练/下载/硬件）、或做过方案取舍的工作
- **不需要**：单文件小修、文案调整——commit message 说清即可

## 生命周期

```
docs/exec-plans/active/<编号>-<主题>.md   ← 开工时创建，随进展更新「进度」节
完成后                                    ← 编号决策登记 decision-registry.md，对外结论写进 README，
                                             未完事项转 tech-debt-tracker.md，然后删除计划文件（原文留在 git）
```

编号顺延，不复用已删除计划的编号。

## 模板（三节必有，机械校验）

```markdown
# <编号> · <主题>

## 状态
<一句话当前状态 + 最后更新日期>

## 背景
<为什么做；方案取舍（问题→选项→权衡→结论）>

## 决策记录
<过程中拍板的决策，逐条追加；编号决策另登记 decision-registry.md>

## 进度
- [x] 已完成步骤
- [ ] 待办步骤（含下一步从哪继续）
```

## 在档计划

- active：见目录（当前为 0007、0013、0016、0017；0007 只剩与作物无关的项；0013 是温室方向软件线总览，0016、0017 是可分头交给代理执行的子计划）
- 技术债与可选打磨统一记 `tech-debt-tracker.md`，不单独开计划

## 已删除的历史文档（2026-09-29 清理）

代码注释和决策注册表里仍会出现「计划 00NN」「审查第 N 项」等编号。原文的最后版本在下表所列 commit，用
`git show <commit>:<路径>` 查看：

| 文档 | commit | 路径 |
|---|---|---|
| 执行计划 0001–0006、0008–0011（M0–M6 回填、YOLO 管线、rover、软件闭环、审查修复、模拟季与离线重放、risk-lr-v1、rust-cls-v1、H3 真实数据） | `5ab7309` | `docs/exec-plans/completed/<编号>-<主题>.md` |
| 执行计划 0012（登录与角色权限） | `ae22fb6` | `docs/exec-plans/completed/0012-user-auth.md` |
| 执行计划 0014（按株建档、协议 v2 最小子集、单株时间线；含执行中的决策记录） | 「docs: 计划 0014 完成」commit（`git log --grep "计划 0014 完成"` 查哈希） | `docs/exec-plans/active/0014-plant-identity-protocol-v2.md` |
| 执行计划 0015（棚内环境、每株状态、风险驱动巡检计划、旧复巡下沉；含执行中的决策记录） | 「docs: 计划 0015 完成」commit（`git log --grep "计划 0015 完成"` 查哈希） | `docs/exec-plans/active/0015-env-risk-patrol-planner.md` |
| 执行计划 0018（前端重做：设计系统、外壳、各页面；含两个阶段的决策记录、色板与色盲检查数据） | 「docs: 计划 0018 完成」commit（`git log --grep "计划 0018 完成"` 查哈希） | `docs/exec-plans/active/0018-frontend-redesign.md` |
| 代码审查记录（三轮）、申报书方案评审 | `5ab7309` | `docs/reviews/2026-09-25-code-review.md`、`docs/reviews/2026-09-25-application-review.md` |
| 主计划 v1.0、讨论决策日志、嵌入式学习路线、项目介绍 v1.0、产品规格索引 | `5ab7309` | `docs/04-master-plan.md`、`docs/05-discussion-decisions.md`、`docs/06-embedded-learning-roadmap.txt`、`docs/07-project-introduction.md`、`docs/product-specs/index.md` |

仍有效的内容已迁出：未修的审查项 → `tech-debt-tracker.md`；方案评审的 P0–P2 与时间线 → 计划 0007；
基线、规则生命周期与分级 → 决策注册表与 ARCHITECTURE.md；计划 0012 → 决策 D15、README（运行与登录说明）、
技术债台账（照片目录公开、署名由前端提交、登录限流、只读账号写按钮、设备级凭据）。
计划 0014 → ARCHITECTURE「契约」（v2 子集、重传幂等、株号关联）、README「当前能力」、计划 0013「进度」、
技术债台账（坐标不可为空、rover 重传遇 409）。
计划 0015 → 决策 D17、D18，ARCHITECTURE「数据流」「契约」，README「当前能力」与已知边界，rover/README，计划 0013「进度」，
技术债台账（计划任务唯一约束、计划不单独成表、设备领任务不分类型、确认任务不随人工确认完成、多记录仪平均）。
计划 0018 → 决策 D19、D20，ARCHITECTURE「frontend 结构」，README「当前能力」「当前状态」，AGENTS 代码地图，计划 0013「进度」，
技术债台账（确认两步非原子、工作台逐棚请求、待确认逐株拉时间线、展示屏低分辨率裁切；清掉只读账号写按钮、确认任务不随确认完成）。
