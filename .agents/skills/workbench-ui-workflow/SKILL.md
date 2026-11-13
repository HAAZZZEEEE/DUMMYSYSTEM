---
name: workbench-ui-workflow
description: Design, redesign, implement, or review DUMMYSYS Workbench pages, components, and interactions. Translate informal feedback into visual alternatives or focused fixes, then implement and verify the chosen direction. Use for Workbench frontend work; exclude unrelated products and backend-only tasks.
---

# Workbench UI workflow

Lead UX analysis, design exploration, implementation, and verification. The user
provides goals, judges visible results, and chooses consequential directions.
Recommend a coherent solution; do not make the user specify typography, CSS,
information architecture, or a sequence of disconnected design details.

## Locate and load

1. Read the current workspace and repository AGENTS instructions. Resolve the
   `dummysystem` repository binding rather than assuming cwd is the source repo.
   `scripts/context.py --workspace <absolute-workspace>` prints the relevant
   locations without reading private project content or credentials.
2. Read Workbench `PRODUCT.md`, `DESIGN.md`, and the current Task summary when
   the work has a Task. Read [project context](references/project-context.md) for
   source and test entrypoints. Read only the tool adapters needed for this task
   in [tools](references/tools.md).
3. Inspect the target source and rendered baseline before changing it. A CSS
   comment or incumbent value is evidence of current behavior, not a newly
   approved preference. Preserve other work and record the starting diff.
4. Use DUMMYSYS Task/Run for sustained work and evidence under its existing
   rules. Ordinary discussion or a brief inspection does not need a new Task.

## Route by the user's intent

| Request | Behavior |
|---|---|
| New important module, navigation change, major redesign | UX brief → comparable visual alternatives → user's decision → implementation → verification |
| Ordinary new page with an established pattern | Inherit the current design system → implement → verify |
| Local spacing, alignment, visual defect, conventional state | Make the focused correction → visual check; no artificial approval round |
| “不好看”, “太挤”, “不像 Linear”, “不顺手” | Inspect, identify hierarchy/density/navigation/feedback problems, explain concrete changes; explore alternatives only if direction or structure is unsettled |
| Review only | Inspect and prioritize findings; do not silently turn a review into redesign |
| Review and improve | Fix authorized issues by impact; bring a structural change back as a visual proposal |

## Explore and choose

- State the user's task, current friction, intended improvement, and constraints.
  Use domain content: Project, Task, Run, documents, source, evidence, search,
  previews. Use synthetic or sanitized realistic data for isolated exploration.
- For consequential undecided direction, produce three materially different
  alternatives by default, plus the incumbent baseline. The user may request
  fewer, one specific direction, or direct implementation; follow that request.
- Compare the same content and functionality. Vary useful dimensions such as
  navigation, density, grouping, preview placement, or information hierarchy.
  Give each alternative a viewable screenshot or runnable prototype and a
  concise tradeoff; put your recommendation first. Text descriptions alone
  do not complete a design proposal.
- Use wireframes for unresolved task flow; build higher fidelity only where it
  helps the decision. A static mockup does not prove working interactions.
- Keep exploratory code and tool state in a Run's isolated runtime directory.
  Never use the installed application or private Vault as a design fixture.
- **Stop before promoting an unchosen direction into product source.** Capture
  which decision is pending and where the user can see the alternatives.
  No reply, a timeout, or the agent's recommendation is not user selection.
- Combine feedback precisely. Preserve accepted elements, revise only unsettled
  ones, and keep a recoverable baseline and useful rejected evidence. A choice
  means a direction is accepted, not that testing or deployment is complete.

## Implement and verify

- Implement the selected/authorized scope in the current HTML/CSS/JS stack.
  Reuse semantic tokens, existing modules, native controls and tested patterns.
  Do not add a framework, component library, or business rule for tool convenience.
- Preserve the public JSON contract and core/CLI ownership of managed writes.
  Keep authentication, CSRF, preview isolation, and platform adapters intact.
- Inspect actual rendering and operate the primary path. For nontrivial work,
  complete implement → screenshot → critique → correction → recheck. If the
  review finds no justified correction, record that instead of inventing one.
- Read [verification](references/verification.md) and select checks affected by
  the change. Run existing relevant regressions; add behavioral coverage only
  for meaningful new or changed interaction. Compiling is not UI acceptance.
- Record exact widths, themes, routes, observations, commands, exit codes, and
  unverified scope. Browser Chromium does not prove Cocoa/WebKit or Windows.
- Remove prototype overlays and stop only services created by this task.
  Deployment, replacing the installed app, and pushing are separate actions
  governed by the user's actual request.

## Persist the result

- `dummysys/apps/workbench/DESIGN.md` is the canonical, versioned technical
  design specification. Separate inherited baseline, accepted rules, and
  unresolved questions. Do not turn an unchosen proposal into a current rule.
- Its native Interface Design file is a generated projection. After an approved
  rule change, run `scripts/sync_design.py --app-root <workbench-root>`, then
  repeat with `--check`. Never independently edit the projection. If another
  tool wrote it, inspect the diff before reconciling; do not discard decisions.
- Store personal feedback, accepted/rejected decisions and their rationale in
  the owning Vault Task; source-independent rules may enter the technical spec.
  Save screenshots, logs, variants and tool state in runtime. Link from the
  Task summary and project entry. Update current state as well as the Run.
- Save confirmed decisions as part of completing the authorized task; do not
  ask again merely to record them. Distinguish “implemented”, “verified”,
  “awaiting choice”, and “external capability unavailable”.

## Natural-language entrypoints

- “为 Workbench 的这个功能启动设计流程，先给我可比较的方案。”
- “重设计这个页面，给我三个明显不同的版本，推荐一个。”
- “检查这页的 UX、视觉一致性和实现质量，修复高优先级问题。”
- “采用 B 的布局，保留 A 的信息密度，继续实现和验证。”

Explicit invocation: `$workbench-ui-workflow`. Automatic discovery remains
enabled. This workflow coordinates other skills; none must be called merely
because it is installed.
