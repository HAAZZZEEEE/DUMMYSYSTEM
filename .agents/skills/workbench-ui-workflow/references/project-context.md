# Workbench context

Resolve the current checkout through the workspace repository registry. In that
checkout, the application root is `dummysys/apps/workbench`.

## Product and source

- A local desktop-first workbench for Agent-assisted Project/Task/Run work.
  Primary success is finding the right context and continuing work.
- Flask serves `workbench/static/index.html`, `styles.css`, `overview.css`
  and plain JavaScript modules. No npm production frontend build is present.
- `navigation.js`, `navpanel.js`, `tree.js`, `directory.js`: location and lists.
- `overview.js`: workspace overview; `taskview.js`: Task/Run views.
- `homepage.js`: the project-homepage iframe host and its interaction bridge.
  The actual project page is a separate HTML package resolved by `homepage.py`
  from that project's registered resources `workbench.json` → homepage
  `root_id` + `path`. Inspect this mapping before treating “项目首页” as
  Workbench shell source. Shell/bridge changes belong here; project-page layout
  belongs in the owning project's registered page package, outside Vault prose.
- `search.js`, `quickaccess.js`: discovery; `preview.js`: reading.
- `ptrforms.js`, `actions.js`, `api.js`: UI actions and JSON boundary.
- `theme.js`, `settings.js`, `platform-ui.js`: themes and OS presentation.
- `web.py` owns sessions and HTTP dispatch; core/CLI owns managed records.
  Native windows and external application opening live behind platform adapters.

Read the target module, its direct callers and affected tests instead of loading
every frontend file. Keep existing IDs used for behavior/testing unless the
change includes their callers. Visual layout alone does not justify changing
domain or persistence contracts.

## Placement

| Artifact | Owner |
|---|---|
| Reusable skill, technical product/design rules, implementation and tests | Source repository |
| User feedback, proposal reasoning, decisions, current Task summary | Vault's owning DUMMYSYSTEM Task |
| Screenshots, logs, local tool packages, credentials, fixtures, prototype state | Explicit workspace runtime |

For a project-page change, resolve its existing registered root and read that
owner's instructions before choosing the destination. An unregistered new page
package requires the project's established resource-registration workflow.

The workspace manifest controls Vault/runtime paths. Do not hardcode this
machine's checkout in repository files. Runtime tool installation uses
`<runtime>/design-tools`; its `installed.json` and package lock identify the
actual locally installed versions. Never auto-upgrade tools during UI work.

## Resuming

Read the latest Task summary before historical Run evidence. Check the current
source and installed tool capability, since an old successful check can drift.
For structural governance changes, use the DUMMYSYS CLI with explicit workspace,
actor, request ID and current version as required by its capabilities.
