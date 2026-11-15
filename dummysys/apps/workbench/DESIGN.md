# Workbench design specification

## Authority and status

This is the canonical technical design specification. Preserve the implemented
layout and interaction rules for ordinary additions and focused fixes.
Record a confirmed decision and its rationale with the relevant change.

## Product surfaces

Workbench prioritizes finding project material and revisiting work. Search and
quick jump are available above the project display and browser. Controls
communicate current location and operation scope.

## Layout: floating panels with glass navigation

- Keep two adjustable areas: project display and project browser. The project
  list and current project's Task/Run records have separate scroll areas.
  Task groups contain their Runs and carry their status and date as metadata.
- The project browser owns homepage/content switching. A project supplies its
  own customizable homepage. The homepage can expand by hiding the project
  display. Returning to content restores the project's latest content location
  in the session. Content mode has visible root tabs and a file list beside
  an adjustable preview. The repository tab retains the registered-repository
  selector.
- Keep task and reading surfaces opaque. Use translucent glass, backdrop blur,
  restrained background halos and bright edges on navigation and outer panels.
  Main panels retain broad neutral shadows; internal rows and small controls
  use much lighter elevation. Provide opaque fallbacks when transparency is
  reduced or unsupported. Keep the visible keyboard focus ring.
- Use pill shapes for quick jump, global search, header actions and the project
  browser's mode switch. With both modes available, the selected segment sits
  inside the track. With content alone, show one raised pill.
- Selected projects use lightly raised surfaces. Task groups use a neutral
  boundary. Selected Runs use a shallow tinted surface within their parent.
  Hover and keyboard focus on history headings stay inside their group border.
  Keep the corresponding project/task/run context visible in the browser.
  Use consistent line icons for project identity instead of initial-letter tiles.
- Prioritize readable names and secondary metadata. Recognize canonical Task
  numbers/dates and Run timestamps for separate, subdued presentation while
  preserving the full original name and path. Unrecognized names remain intact.
- Make the workspace display name configurable, separate from the Workbench
  product name. Preserve search, contextual actions, resizing and focus behavior.
- Use system fonts with Chinese and Windows fallbacks. Keep light/dark themes,
  readable contrast, long-name wrapping and reduced-motion support. Surface
  hierarchy is shared across platforms; native platform behavior still needs
  platform-specific verification.

The workspace name is stored in Workbench preferences. Theme, navigation
sorting, directory density and both Task view styles are also configurable.

## Appearance tokens

Sources: workbench/static/workspace.css, styles.css, overview.css and theme.js.
Check computed styles in the rendered application for theme-dependent values.

| Role | Current baseline |
|---|---|
| Light action accent | #0066cc by default; user-configurable via theme.js |
| Light text / secondary / muted | #1d1d1f / #333333 / #7a7a7a |
| Light reading / navigation / secondary surface | #ffffff / #f5f5f7 / #fafafc |
| Light border / danger | #e0e0e0 / #b91c1c |
| Dark reading / navigation / secondary surface | #1c1c20 / #242429 / #2b2b32 |
| Dark primary / secondary / muted text | #f2f2f4 / #d0d0d8 / #a3a3af |
| Dark border / danger | #45454f / #ff9797 |
| Dark default accent | #70b7ff; theme.js computes effective palette |

Use existing semantic CSS variables such as --accent, --ink, --ink-muted-80,
--canvas, --parchment, --hairline, --danger, --focus-ring and --menu-surface.
Do not copy a light-only color into new dark-aware UI.

Typography uses the existing system-oriented stack: SF Pro Text, Segoe UI,
Microsoft YaHei, system-ui, -apple-system, sans-serif. Body baseline is 15px;
compact controls and metadata use smaller sizes, with hierarchy also conveyed
by weight and semantic text color. Keep Chinese fallbacks and long-text reading.

Use the shell's surface, edge and shadow tokens for the two panels. Use the
shared control tokens for inputs, buttons and dialogs. Directory rows have
44px and 32px minimums in comfortable and compact density and grow for long
names. Narrow lists display type and modification time under the file name.

## Navigation and actions

- Preserve keyboard-operable separators, file-list and preview toggling, focus
  mode and selection persistence when changing the layout.
- Main actions belong to their current project/location. Do not visually imply
  a broader or narrower scope than the actual API operation.
- Search and quick jump retain keyboard navigation, clear selected results,
  Escape dismissal and reliable destination context.
- Prefer existing native button/input/dialog/popover semantics and tested
  modules. A new dependency requires a concrete benefit to the requested task.
- Managed action feedback must cover loading, success, error and recovery.
  Actual domain status comes from core/CLI, not visual invention.

## Adaptation, themes and motion

Preserve light, dark and system themes and the configurable accent. Narrow
windows can switch between project display and browser. At 760px or less,
opening a preview gives it the browser width, and the file navigation control
returns to the directory list.

Use visible keyboard focus and readable contrast. Match existing behavior
first, then fix demonstrated deficiencies within scope. Reduced-motion settings
disable animation/transition; preserve this. Avoid motion that delays repeated
navigation or makes layout unstable.

## Maintaining this specification

Update the affected rules when a product design decision is confirmed. Keep
inherited behavior distinct from newly accepted rules and unresolved proposals.
Check the implementation and rendered result when documenting a rule; unselected
proposals do not replace the current specification.
