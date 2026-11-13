# Tool adapters

Load each installed tool's SKILL.md before using it. This adapter captures the
user-approved Workbench scope where generic upstream defaults differ.

## Locations and precedence

`context.py --workspace <workspace>` reports `tools_root`. Tools are installed
under its `skills/`, with fixed entrypoints in `bin/`. Read
`installed.json` for revisions and local adaptations. Skills are linked into
workspace and checkout discovery directories; the custom workflow source is
versioned, while machine-specific dependency links are locally excluded.

Current user scope and the confirmed Workbench design specification take
precedence over generic tool taste. Do not automatically replace system fonts,
spacing, borders, sidebar surfaces, or native controls to satisfy a generic
anti-pattern detector. Interpret findings against actual users and rendering.
Do not install Hooks, weaken permissions, or spawn an external CLI agent as a
side effect. Existing authorization to do a task remains sufficient for routine
work and recording confirmed decisions.

## Interface Design

Use for hierarchy, density, components and consistency. Set cwd to Workbench
app root so `.interface-design/system.md` resolves correctly. That file is
generated from `DESIGN.md`; write approved rules to the canonical spec, then
run the workflow's sync helper. The current baseline is not blanket approval
of every existing design value. Do not repeat its optional “save patterns?”
question after the user has already authorized persistence.

## Impeccable

Use Operate for controls and navigation, Read for document previews. Run the
installed launcher's `context` once from the app root. Use only the current
skill's actual playbooks: shape, critique, audit, polish, harden, etc.
`critique` and `audit` are agent playbooks, not assumed CLI subcommands.

The engine may report `hasVisualImplementation: false` because the static entry
is nested under `workbench/static`. Inspect that entry directly; this flag does
not make Workbench a greenfield project. Supply the concrete target when a
command accepts one.

The installed launcher forces `IMPECCABLE_LIVE_COPY_AGENT=off` and keeps its
engine cache in runtime. No design Hook is registered. Prefer ordinary local
editing and Variate. Use live/generate only for a demonstrated benefit, within
an isolated runtime checkout, after reading their current references. Never
follow a generic request to disable approvals/sandboxing or relax product CSP.
Run rendered detection when useful; detector warnings are evidence, not an
instruction to alter a confirmed identity. Missing engine has the upstream
documented direct-reading fallback.

## Variate

Use `bin/variate` with explicit `--root <isolated-runtime-prototype>`.
It replaces a single target file while switching. Four positions are the
incumbent plus three alternatives; new empty prototypes can use three positions.
Cross-file redesign needs a self-contained exploratory page or coherent copies,
then deliberate integration into product modules after selection.

Read the plan/craft contract, preserve position 1 for existing content, and
inspect every position. Plain HTML reload is supported. If an overlay cannot
attach to the authenticated Flask app, keep isolated local comparison or
terminal switching rather than weakening authentication/CSP.

No idle-wake Hooks are installed. During an open comparison, poll in short
bounded slices as appropriate; after the turn ends, a card click may require
the user to send a message. Do not claim background attention. Save meaningful
proposal evidence before `end`, which cleans variants. Unrelated tasks should
not be hijacked by a stale design queue.

## Agent Browser and Playwright

Use `bin/agent-browser skills get core` to load version-matched instructions.
Use a named isolated session for local UI observation, interaction, screenshots,
console errors, and viewport changes. Existing project Playwright tests remain
the repeatable regression mechanism. Do not attach to personal browser profiles
or reuse private session exports to test a synthetic workspace.

The local wrapper puts sockets under `<tools_root>/ab`; pass a unique session
on every call. Put any explicit profile, test output and TMPDIR in the Run's
runtime. Visual verification requested by this workflow includes screenshots:
use DOM/locators for behavior and screenshots for spacing, wrapping and layout.
The isolated Python interpreter is `<tools_root>/python/bin/python`.
Installed Playwright Chromium uses `PLAYWRIGHT_BROWSERS_PATH=<tools_root>/browsers`;
keep this variable when running existing browser fixtures.

Workbench needs a one-time bootstrap token before its authenticated API works.
Reuse `tests/browser/browser_fixture.py` or the managed launch contract; a bare
localhost URL is not proof of a broken UI. Never record bootstrap URLs,
cookies, HAR, or traces containing credentials in evidence. Mocked system
openers do not verify Finder, Obsidian, or native window behavior.
