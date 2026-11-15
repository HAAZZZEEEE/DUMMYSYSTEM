"""多仓库和长名称的根选项卡布局与可达性。"""
import json

from browser_fixture import A, B, BrowserCase, expect
from tests.helpers import write_json


class RootTabsTests(BrowserCase):
    def prepare(self, count=16, long_names=True):
        self.repo_ids = [('repository-with-a-very-long-name-' + str(i) * 12) if long_names else f'repo-{i}' for i in range(count)]
        checkouts = {}
        for repo_id in self.repo_ids:
            path = self.ws.parent / repo_id
            path.mkdir()
            checkouts[repo_id] = {'path': str(path)}
        write_json(self.ws / 'runtime/state/workspace/repositories.json', {'checkouts': checkouts})
        path = self.ws / 'runtime/project_src/项目 A/project.json'
        binding = json.loads(path.read_text(encoding='utf-8'))
        binding['repositories'] = [{'repo_id': repo_id, 'paths': ['.']} for repo_id in self.repo_ids]
        if long_names:
            binding['repositories'].append({'path': str(path.parent), 'role': '中文超长仓库名称测试' * 8})
        write_json(path, binding)
        self.page.locator('#btn-project-refresh').click()
        self.project()
        expect(self.page.locator('#root-tabs').get_by_role('tab')).to_have_count(3)

    def open_repositories(self):
        self.page.get_by_role('tab', name='代码仓库', exact=True).click()
        expect(self.page.get_by_role('menu', name='代码仓库', exact=True)).to_be_visible()

    def test_selection_animation_does_not_replay_after_loading(self):
        self.project()
        self.page.evaluate('''async () => {
            const host = document.getElementById('root-tabs');
            await Promise.all(host.getAnimations({subtree: true})
                .filter(animation => animation.animationName === 'tabpop')
                .map(animation => animation.finished.catch(() => {})));
            window.__tabAnimations = [];
            for (const type of ['animationstart', 'animationend']) {
                host.addEventListener(type, event => {
                    if (event.animationName === 'tabpop') window.__tabAnimations.push({
                        type, root: event.target.dataset.rootId, pseudo: event.pseudoElement});
                });
            }
        }''')
        self.delay('list', project=A, relative='')
        self.page.get_by_role('tab', name='根目录：项目资源', exact=True).click()
        self.delay_ready()
        self.page.wait_for_function("window.__tabAnimations.some(event => event.type === 'animationend' && event.root === 'resources')")
        self.release()
        self.ready(root='resources')
        self.page.evaluate('''async () => {
            await Promise.all(document.getElementById('root-tabs').getAnimations({subtree: true})
                .filter(animation => animation.animationName === 'tabpop')
                .map(animation => animation.finished.catch(() => {})));
        }''')
        starts = self.page.evaluate("window.__tabAnimations.filter(event => event.type === 'animationstart' && event.root === 'resources' && event.pseudo === '::after')")
        self.assertEqual(len(starts), 1, starts)
        self.page.locator('#btn-refresh').click()
        self.ready(root='resources')
        self.page.get_by_role('tab', name='根目录：项目资源', exact=True).click()
        self.ready(root='resources')
        self.page.evaluate('''async () => {
            await Promise.all(document.getElementById('root-tabs').getAnimations({subtree: true})
                .filter(animation => animation.animationName === 'tabpop')
                .map(animation => animation.finished.catch(() => {})));
        }''')
        self.assertEqual(self.page.evaluate("window.__tabAnimations.filter(event => event.type === 'animationstart').length"), 1)
        self.delay('list', project=A, relative='')
        self.page.get_by_role('tab', name='根目录：文档', exact=True).click()
        self.delay_ready()
        self.page.wait_for_function("window.__tabAnimations.some(event => event.type === 'animationend' && event.root === 'docs')")
        self.release()
        self.ready()
        self.page.evaluate('''async () => {
            await Promise.all(document.getElementById('root-tabs').getAnimations({subtree: true})
                .filter(animation => animation.animationName === 'tabpop')
                .map(animation => animation.finished.catch(() => {})));
        }''')
        self.assertEqual(self.page.evaluate("window.__tabAnimations.filter(event => event.type === 'animationstart' && event.root === 'docs').length"), 1)

    def test_many_long_names_in_bounded_dropdown(self):
        self.prepare()
        expect(self.page.locator('#repo-root-menu')).to_be_hidden()
        for width in (1440, 960, 760):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 1000})
                self.open_repositories()
                expect(self.page.get_by_role('menuitemradio')).to_have_count(17)
                metrics = self.page.locator('#repo-root-menu').evaluate('''host => ({
                    pageWidth: document.documentElement.scrollWidth, viewport: innerWidth,
                    left: host.getBoundingClientRect().left, right: host.getBoundingClientRect().right,
                    height: host.clientHeight, contentHeight: host.scrollHeight,
                    widths: [...host.children].map(item => item.scrollWidth <= item.clientWidth),
                    wrapping: [...host.querySelectorAll('span')].every(item => getComputedStyle(item).whiteSpace === 'normal')
                })''')
                self.assertLessEqual(metrics['pageWidth'], metrics['viewport'])
                self.assertGreaterEqual(metrics['left'], 0)
                self.assertLessEqual(metrics['right'], metrics['viewport'])
                self.assertGreater(metrics['contentHeight'], metrics['height'])
                self.assertTrue(all(metrics['widths']), metrics)
                self.assertTrue(metrics['wrapping'])
                self.page.keyboard.press('End')
                expect(self.page.get_by_role('menuitemradio').last).to_be_focused()
                self.assertGreater(self.page.locator('#repo-root-menu').evaluate('host => host.scrollTop'), 0)
                self.page.screenshot(path=str(self.output / f'repo-dropdown-{width}.png'))
                self.page.keyboard.press('Escape')

    def test_choose_repository_and_current_selection(self):
        self.prepare()
        self.open_repositories()
        self.target_locator('repo-root-option', root='repo:' + self.repo_ids[-1]).click()
        self.ready(root='repo:' + self.repo_ids[-1])
        trigger = self.page.get_by_role('tab', name='代码仓库', exact=True)
        expect(trigger).to_have_attribute('aria-selected', 'true')
        expect(trigger).to_have_attribute('aria-expanded', 'false')
        expect(trigger).to_have_attribute('title', '代码仓库：' + self.repo_ids[-1])
        self.open_repositories()
        selected = self.target_locator('repo-root-option', root='repo:' + self.repo_ids[-1])
        expect(selected).to_have_attribute('aria-checked', 'true')
        expect(selected).to_be_focused()
        self.page.keyboard.press('Escape')
        self.page.go_back()
        self.ready()
        expect(trigger).to_have_attribute('aria-selected', 'false')
        self.page.go_forward()
        self.ready(root='repo:' + self.repo_ids[-1])
        self.page.reload()
        self.ready(root='repo:' + self.repo_ids[-1])
        expect(trigger).to_have_attribute('aria-selected', 'true')

    def test_keyboard_dismiss_and_project_change(self):
        self.prepare()
        trigger = self.page.get_by_role('tab', name='代码仓库', exact=True)
        trigger.focus()
        self.page.keyboard.press('ArrowDown')
        expect(self.page.get_by_role('menuitemradio').first).to_be_focused()
        self.page.keyboard.press('End')
        expect(self.page.get_by_role('menuitemradio').last).to_be_focused()
        self.page.keyboard.press('Home')
        self.page.keyboard.press('ArrowDown')
        self.page.keyboard.press('ArrowUp')
        self.page.keyboard.press('Enter')
        self.ready(root='repo:' + self.repo_ids[0])
        expect(trigger).to_be_focused()
        self.open_repositories()
        trigger.click()
        expect(self.page.locator('#repo-root-menu')).to_be_hidden()
        self.open_repositories()
        self.page.keyboard.press('Escape')
        expect(trigger).to_be_focused()
        expect(trigger).to_have_attribute('aria-expanded', 'false')
        self.open_repositories()
        self.page.keyboard.press('Tab')
        expect(self.page.locator('#repo-root-menu')).to_be_hidden()
        self.open_repositories()
        self.page.locator('#project-title').click()
        expect(trigger).to_have_attribute('aria-expanded', 'false')
        self.open_repositories()
        self.project(B)
        expect(self.page.locator('#repo-root-trigger')).to_have_count(0)
        expect(self.page.locator('#repo-root-menu')).to_be_hidden()
        self.project(A)
        self.open_repositories()
        self.page.emulate_media(color_scheme='dark', reduced_motion='reduce')
        self.page.screenshot(path=str(self.output / 'repo-dropdown-dark.png'))

    def test_single_repository_still_uses_dropdown(self):
        self.prepare(count=1, long_names=False)
        self.open_repositories()
        expect(self.page.get_by_role('menuitemradio')).to_have_count(1)
        self.page.get_by_role('menuitemradio').click()
        self.ready(root='repo:' + self.repo_ids[0])
