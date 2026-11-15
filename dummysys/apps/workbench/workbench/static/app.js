// 原生 ES modules 入口：只组装模块，保持离线、无需构建。
import { createSession } from './session.js';
import { createNavigation } from './navigation.js';
import { createDirectory } from './directory.js';
import { createActions } from './actions.js';
import { createTree } from './tree.js';
import { createPreview } from './preview.js';
import { createHomepage } from './homepage.js';
import { createTaskView } from './taskview.js';
import { createNavPanel } from './navpanel.js';
import { createPtrForms } from './ptrforms.js';
import { createTheme } from './theme.js';
import { createQuickAccess } from './quickaccess.js';
import { createSearch } from './search.js';
import { createView, flash, fatal } from './view.js';
import { createDeleted } from './deleted.js';
import { mountNavSort } from './navsort.js';
import { createOverview } from './overview.js';

const session = createSession();
mountNavSort(session, flash);
const navigation = createNavigation();
const actions = createActions(navigation, flash);
const preview = createPreview(navigation, session, actions, flash);
const directory = createDirectory(navigation, session, actions, flash, preview);
const tree = createTree(navigation, actions, flash, preview);
// ptrForms 依赖 navPanel.reloadNav 与 taskView.tasks，navPanel 又依赖 taskView 里的 ptr 菜单；用间接调用解环。
let reloadNav = () => {};
let taskList = () => [];
const ptr = createPtrForms({ nav: navigation, session, flash, reloadNav: () => reloadNav(), taskList: () => taskList() });
const deleted = createDeleted(navigation, ptr, flash, session);
const taskView = createTaskView(navigation, actions, flash, ptr);
const navPanel = createNavPanel(navigation, session, actions, tree, taskView, flash);
reloadNav = () => navigation.reload(true);
taskList = () => taskView.tasks;
// 创建入口由当前项目的工具栏承载。
ptr.mountToolbar();
const view = createView(navigation, session, actions, tree, navPanel, preview);
const theme = createTheme(session, flash);
const quickAccess = createQuickAccess(navigation, session, flash);
const search = createSearch(navigation, session, flash, quickAccess, preview);
const homepage = createHomepage(navigation, session, flash);
const overview = createOverview(navigation);
navigation.setLoader((ctx, append) => ctx.target.root_id === 'homepage' ? homepage.load(ctx) : directory.load(ctx, append));
navigation.onCatalog = async (catalog) => {
  view.catalog(catalog);
  quickAccess.catalog(catalog);
  overview.catalog();
  await Promise.all([navPanel.reloadNav(), deleted.reload()]);
};

session.bootstrap().then(async (catalog) => {
  await ptr.loadSurface().catch((error) => flash(`操作能力加载失败：${error.message}`));
  theme.init();
  view.catalog(catalog);
  quickAccess.catalog(catalog);
  view.wire();
  quickAccess.wire();
  search.wire();
  const initial = navigation.start(session.preferences.last_location);
  view.show();
  void deleted.reload();
  await initial;
}).catch(fatal);
