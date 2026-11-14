# Workbench product context

## Platform

web

## Purpose and audience

DUMMYSYS Workbench is a local, desktop-first browser and optional native-window
interface for an individual developer working with coding agents.

The product is a **browse-and-search-first personal workbench**
（陈列／搜索优先的个人工作台）. Its primary purpose is to organize projects,
files, Tasks and Runs so the user can find things and revisit past records.
Detailed reading of an individual file is a supporting activity.

The interface should make project context and available actions understandable
without requiring knowledge of the underlying storage or execution machinery.

## Core tasks

1. Browse organized project, document, resource and repository locations, with
   enough context to recognize the item being sought.
2. Search for a project, Task, Run or file, distinguish similar results, and
   navigate to the correct owning location.
3. Revisit past Tasks, Runs, outcomes and evidence. Keep recent visits distinct
   from execution history: opening an item is not an execution event.
4. Inspect a selected item's context or preview when needed, preserving the
   current listing, filters and location when returning.
5. Perform supported managed operations with clear scope, state and recoverable
   feedback; open external applications when the relevant capability exists.

## Experience priorities

- Give organized listings, search and historical context priority in the main
  workspace. Browsing and keyword lookup are complementary ways to find things.
- Make result identity clear through useful names, types, owning project/Task,
  relative location, and relevant time or status; avoid requiring an item to be
  opened merely to identify it.
- Make historical outcomes and evidence easy to trace to their Task and Run.
- Keep previews and extended reading available on demand, secondary to finding
  and revisiting items.
- Clear location and scope, efficient scanning, readable Chinese/mixed-language
  names, keyboard support, predictable feedback and error recovery.
- Preserve learned interaction patterns during focused refinements. Make major
  navigation or density changes visible for comparison before implementation.

This priority does not select a specific sidebar, search layout, default entry
page or preview placement. Those remain design decisions to evaluate against
the primary finding and history-review tasks.

## Implementation and boundaries

Flask serves static HTML/CSS and modular plain JavaScript. Core/CLI owns
Project/Task/Run rules and managed writes through public JSON contracts.
Authentication and preview isolation remain functional requirements.

Desktop browser and optional macOS/Windows native shells have distinct
verification requirements. Narrow-window behavior is supported according to
the actual implementation; no complete phone-native experience is promised.

Personal content, machine binding, tokens and execution evidence remain outside
the source repository. Use isolated synthetic data for design exploration.
Do not replace the framework, deployment, synchronization model, or installed
application as an incidental part of a visual change.

## Context ownership

This file is the reusable product brief. DESIGN.md owns the technical design
specification. Update this brief when the target audience, core tasks, product priorities, or
supported scope changes. Keep implementation details in the relevant technical
documentation.
