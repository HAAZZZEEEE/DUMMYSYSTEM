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
- The project list, Task/Run navigation, directory list and file preview fade
  at the bottom of their own scroll viewport while content continues below.
  The fade clears at the end, for visible keyboard focus and in forced colors.
  Panel headers and directory totals remain outside the fade.
- The project browser owns homepage/content switching. A project supplies its
  own customizable homepage. Every project retains the Home/Content switch.
  Without a custom page, Home shows a built-in dashboard using the current
  project navigation records: non-archived task counts, execution counts,
  three newest tasks and registered roots. Below it, editable Agent prompt
  examples explain customization and can be copied with project identity and
  configuration instructions. Empty projects retain the dashboard and guide.
  Invalid custom configuration remains an error with refresh recovery.
  The homepage can expand by hiding the project
  display. Returning to content restores the project's latest content location
  in the session. Content mode has visible root tabs and a file list beside
  an adjustable preview. The repository tab retains the registered-repository
  selector. Root tabs share a shallow track with a pill-shaped selection.
- The directory toolbar groups the source tabs, current path and location
  actions on one line. At browser-pane widths of 660px or less, source tabs
  take the first row and the path and actions share the second. A shallow
  inset field contains the breadcrumb and its copy control, with the latter
  at the trailing edge. Long paths scroll within the field, keeping the
  current directory visible on navigation and resize. Fine dividers separate
  source navigation from the address on wide panes and directory actions
  from the preview switch at every width.
- Keep task and reading surfaces opaque. Use translucent glass, backdrop blur,
  restrained background halos and bright edges on navigation and outer panels.
  Main panels retain broad neutral shadows; internal rows and small controls
  use much lighter elevation. Provide opaque fallbacks when transparency is
  reduced or unsupported. Keep the visible keyboard focus ring.
- Use pill shapes for quick jump, global search, header actions and the project
  browser's mode switch. With both modes available, the selected segment sits
  inside the track. Both modes remain available even before a custom homepage is configured.
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
shared control tokens for inputs, buttons and dialogs. Ordinary files and
folders have 35px and 32px minimum row heights in comfortable and compact
density. Recognized Task and Run folders use 44px and 40px minimums, with
subdued metadata on a separate line below the name at every list width.
File and directory names use regular 12.5px text on one line with an ellipsis
when needed. Hover shows the original name, and keyboard focus wraps the row's
name to reveal it.
The directory table defaults to Name. Its header settings expose Type,
Modified, Size and File Count. Name stays first. In the column settings,
moving an optional column changes its left-to-right position, including when
it is hidden. Visibility and order survive reloads.
File Count covers direct regular files of a listed directory. Size reports
individual file sizes. The sticky table header places the filename search on
the Name column's row and the settings control at the trailing edge. Search
compresses in tight panes. Directory Settings contains type filtering and
sorting above the column visibility and order controls. The column reset
restores only column visibility and order. The header blends into the file
list without a drawn bottom edge.

Settings use a glass outer panel and opaque groups for Appearance, Workspace,
and Runtime. The title and close control stay above the scroll area, and
save feedback and appearance reset stay below it. Theme uses three native
radio options in a shallow pill track. Shortcut reference opens on demand.

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
