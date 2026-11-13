# Workbench UI design and development

Use the repository's `workbench-ui-workflow` skill for Workbench frontend
design, implementation and review. Its entrypoint is
[`SKILL.md`](../../../../.agents/skills/workbench-ui-workflow/SKILL.md).
Read the skill for workflow rules; this page is the product-side entry.

## Daily entrypoints

- “为这个 Workbench 功能启动设计流程，先分析 UX，再给我三个可视化方案。”
- “检查当前页面，提出明显不同的改进版本，让我选择或组合。”
- “检查这页的 UX、视觉一致性和实现质量，修复高优先级问题。”
- “采用 B，保留 A 的信息密度，继续实现并验证。”

Small corrections proceed directly. Important unresolved layout/navigation
choices wait for a real user decision. The agent provides analysis, concrete
visuals, tradeoffs and a recommendation.

## Context and tools

- [PRODUCT.md](../PRODUCT.md): durable product goals and constraints.
- [DESIGN.md](../DESIGN.md): canonical technical design specification.
- [.interface-design/system.md](../.interface-design/system.md): generated tool
  projection; use the skill's sync helper, not independent edits.
- [verification.md](verification.md): repository validation entrypoints.

The workspace's runtime/design-tools installation provides Interface Design,
Impeccable, Variate and Agent Browser. The local manifest
records pinned revisions and adaptations. Their installers/Hooks do not run
automatically during ordinary UI tasks.

The current workspace and checkout may differ. Resolve the bound repository,
load the skill through the host's discovery path, and read the installed
capabilities. If a tool is missing, report it and use a compatible local path.

## Records

Personal design decisions and proposal summaries belong to the owning Vault
Task. Screenshot evidence, interactive comparison state and test output belong
to its runtime Run. Reusable implementation, tests and technical rules belong
to source. Keep one current rule and link to it; do not duplicate the full
workflow into AGENTS or a second WORKFLOW.md.

## Delivery

Report the chosen/implemented result, visual and interaction checks, relevant
regressions, evidence location and unverified scope. Stop task-owned preview
services and remove overlays after the session. Replacing the installed
Workbench app is a separate deployment action.
