# Workbench design specification

## Authority and status

This is the canonical technical design specification. Its initial values below
describe the existing implementation; they are **inherited baseline**, not a
new user approval of every aesthetic choice. No redesign was selected while
establishing this workflow.

Preserve this baseline for ordinary additions and focused fixes. A user-chosen
new direction updates only the affected rules. Record the decision and reason
in the owning Vault Task, then update this file and its generated projection.
Unchosen proposals never become current design rules.

## Product surfaces

Workbench is an operational tool and reading environment. Project navigation
serves the active workspace; primary content is the project/task information,
directory or document being inspected. Controls communicate current location
and operation scope. Prefer task clarity over decorative differentiation.

## Inherited visual baseline

Sources: workbench/static/styles.css, overview.css, theme.js and the rendered
target. CSS has later overrides and runtime theme/preferences; inspect computed
styles before treating an early declaration as the effective value.

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

Existing tokens include radius 8px/11px/pill and spacing 8px/12px/17px; a later
desktop rule sets --sp-lg to 22px, --control-h to 32px, --sidebar-w to 22rem,
--nav-h to 52px and --tab-h to 39px. Some components have their own measured
geometry. Directory rows are 44px in normal density and 32px in compact density.
These are recorded facts, not a mandate to retain irregular values forever.

Surfaces currently combine solid reading areas, lightly translucent navigation,
borders and layered floating menus. Existing gradients, shadows and rounded
corners should be judged in context; installing a detector does not authorize
removing them or changing the palette.

## Layout and interaction baseline

- Project navigation at left; workspace header, root tabs and location context
  above the main area; directory list and optional preview share the content.
- Sidebar and preview have adjustable widths. Preserve keyboard-operable
  separators, preview toggling, focus mode and selection persistence when touched.
- Main actions belong to their current project/location. Do not visually imply
  a broader or narrower scope than the actual API operation.
- Search and quick jump retain keyboard navigation, clear selected results,
  Escape dismissal and reliable destination context.
- Prefer existing native button/input/dialog/popover semantics and tested
  modules. A new dependency requires a concrete benefit to the requested task.
- Managed action feedback must cover loading, success, error and recovery.
  Actual domain status comes from core/CLI, not visual invention.

## Adaptation, themes and motion

Preserve light, dark, system theme, configurable accent and density settings.
At narrow widths the current implementation wraps controls and hides the
preview below 760px. Inspect actual overflow at the target sizes; this is not
evidence of full mobile support.

Use visible keyboard focus and readable contrast. Match existing behavior
first, then fix demonstrated deficiencies within scope. Reduced-motion settings
disable animation/transition; preserve this. Avoid motion that delays repeated
navigation or makes layout unstable.

## Confirmed workflow constraints

- Significant unresolved structure/visual direction is shown as real comparable
  alternatives with a recommendation before the user chooses.
- Routine spacing/alignment/state fixes do not need repeated design approval.
- Accepted elements survive iteration; arbitrary style resets and cosmetic-only
  “alternatives” do not satisfy a request for meaningful exploration.
- Keep business content and function equivalent between proposals. Do not add
  marketing copy, decorative dashboards or fabricated metrics to fill a layout.
- Record meaningful user feedback and decisions; a synthetic test verdict must
  never become a real preference.

## Synchronization

`.interface-design/system.md` is generated from this entire file and includes
its SHA-256. From the repository root, run:

```sh
python3 .agents/skills/workbench-ui-workflow/scripts/sync_design.py --app-root dummysys/apps/workbench
python3 .agents/skills/workbench-ui-workflow/scripts/sync_design.py --app-root dummysys/apps/workbench --check
```

Inspect an independently modified projection before regenerating it. Impeccable
reads this canonical file from the app root.
