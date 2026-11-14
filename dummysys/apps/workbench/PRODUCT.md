# Workbench product context

## Platform

web

## Purpose and audience

DUMMYSYS Workbench is a local, desktop-first browser and optional native-window
interface for an individual developer working with coding agents. It helps the
user find a project's current context, inspect documents and resources, follow
Task/Run evidence, and continue work across sessions.

The interface should make project context and available actions understandable
without requiring knowledge of the underlying storage or execution machinery.

## Core tasks

1. Find and switch projects through navigation, pinned/recent items or search.
2. Read the project homepage and current Task context; inspect Runs and evidence.
3. Navigate document/resource/repository roots and preview files without losing
   the current location.
4. Search for a task, run or file and navigate to its owning context.
5. Perform supported managed operations with clear scope, state and recoverable
   feedback; open external applications when the relevant capability exists.

## Experience priorities

- Efficient navigation, lists, controls and managed actions.
- Comfortable reading of previews and current project/task explanations.
- Clear location and scope, efficient scanning, readable Chinese/mixed-language
  names, keyboard support, predictable feedback and error recovery.
- Preserve learned interaction patterns during focused refinements. Make major
  navigation or density changes visible for comparison before implementation.

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
