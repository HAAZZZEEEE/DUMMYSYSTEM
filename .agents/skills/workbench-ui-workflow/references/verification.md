# Verification by impact

Every change needs evidence appropriate to the actual scope. A focused spacing
fix needs a rendered before/after and overflow check, not the whole test suite.

## Nontrivial UI acceptance

- Inspect the target at a normal desktop size (for example 1440×1000), a narrow
  desktop window (900×700), and 390px for graceful narrow-screen behavior when
  affected. Record actual sizes. Desktop-first does not mean mobile-complete.
- Check applicable light/dark/system theme, text hierarchy, long Chinese and
  mixed-language names, overflow, zoom, empty/loading/error/retry states.
- Operate the primary flow; validate keyboard focus, Escape, enter/space,
  focus return, semantic labels, selected/disabled states and reduced motion.
- Check browser page errors and failing requests. Use baseline comparison for
  performance claims, not a visual impression.
- Critique usability and visual consistency; audit affected accessibility,
  theming and responsive behavior. Fix high-impact issues and recheck.

## Existing tests

Read `dummysys/apps/workbench/docs/verification.md`. Use an isolated installed
environment and record imported package locations. Set `WORKBENCH_TEST_OUTPUT`
and temporary directories explicitly outside source.

| Changed surface | Useful existing browser tests |
|---|---|
| Navigation and directory | test_workbench_browser, test_root_context, test_root_tabs, test_narrow_directory |
| Homepage | test_homepage, test_homepage_explorer, test_overview |
| Search/quick jump | test_search_interactions, test_quickaccess |
| Preview and resizing | test_nav_preview, test_preview_toggle, test_experience |
| Task/Run actions | test_ptr_buttons, test_archived_tasks, test_dfx |

Choose actual test classes/methods after reading them. These are entrypoints,
not a command that assumes all are always needed.

Browser regression and source-package consistency are separate from desktop
validation. Native opening, window close/reopen, Cmd+Q and Windows-specific APIs
must be reported as unverified unless exercised on their actual platform.

## Workflow installation checks

- Validate the custom skill manifest, references and helper behavior.
- Check actual host discovery from both workspace and checkout.
- Exercise a small fix in a synthetic page and inspect its rendered result.
- Exercise a multi-option proposal with no user verdict: alternatives and
  recommendation exist; product files remain unchanged and decision is pending.
- Simulate a later choice only in the fixture; retain the chosen version and
  verify cleanup. Do not record the simulated choice as a real user preference.
- Verify design projection consistency, explicit unavailable-tool reporting,
  and that no Hooks/background agent or private upload was introduced.
