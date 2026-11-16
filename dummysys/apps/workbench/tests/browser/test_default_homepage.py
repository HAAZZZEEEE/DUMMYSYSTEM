"""未配置首页时的看板、引导、真实导航与响应隔离。"""
from browser_fixture import A, B, BrowserCase, expect
from tests.helpers import write_json
import re


class DefaultHomepageTests(BrowserCase):
    def home(self, project=A):
        self.page.locator(f'[data-testid="project-link"][data-id="{project}"]').click()
        expect(self.page.get_by_test_id('default-homepage')).to_be_visible()
        return self.page.get_by_test_id('default-homepage')

    def seed(self):
        tasks = [('[task 1][20261114]已结束的任务', 'completed'),
                 ('[task 2][20261115]正在推进的任务', 'active'),
                 ('[task 3][20261116]等候外部资料的任务', 'blocked')]
        for number, (name, status) in enumerate(tasks):
            root = self.docs[A] / name
            root.mkdir()
            (root / 'README.md').write_text(f'---\ntitle: {name.split("]")[-1]}\nstatus: {status}\n---\n', encoding='utf-8')
            write_json(self.ws / 'runtime/project_src/项目 A' / name / 'runs/[20261116-120000]执行验证/run.json',
                       dict(run_id=f'default-run-{number}', title='执行验证', status='running' if number == 1 else 'completed'))
        return tasks

    def test_empty_project_and_prompt_examples_copy_and_failure(self):
        panel = self.home()
        expect(panel.get_by_label('全部任务', exact=True).locator('strong')).to_have_text('0')
        expect(panel).to_contain_text('还没有任务')
        self.page.wait_for_function("""async () => (await (await fetch('/api/v1/preferences')).json()).data.last_location?.root_id === 'homepage'""")
        self.clipboard()
        panel.get_by_role('button', name='实验与数据', exact=True).click()
        prompt = panel.get_by_role('textbox')
        expect(prompt).to_have_value(re.compile('.*实验对比.*'))
        panel.get_by_role('button', name='复制提示词', exact=True).click()
        expect(panel.get_by_role('status')).to_contain_text('已复制')
        copied = self.page.evaluate('window.__clipboardWrites[0]')
        self.assertIn(A, copied)
        self.assertIn('workbench.json', copied)
        self.assertIn('项目 A', copied)
        self.clipboard(reject=True)
        panel.get_by_role('button', name='资料与成果', exact=True).click()
        panel.get_by_role('button', name='复制提示词', exact=True).click()
        expect(panel.get_by_role('status')).to_contain_text('请复制已选中')
        expect(prompt).to_be_focused()
        self.assertIn('workbench.json', prompt.input_value())

    def test_metrics_recent_tasks_roots_and_content_history(self):
        tasks = self.seed()
        panel = self.home()
        for label, value in [('全部任务','3'),('进行中','1'),('已完成','1'),('执行记录','3')]:
            expect(panel.get_by_label(label, exact=True).locator('strong')).to_have_text(value)
        recent = panel.get_by_role('region', name='最近任务', exact=True)
        expect(recent.get_by_role('button').first).to_contain_text('等候外部资料')
        recent.get_by_role('button').first.click()
        self.ready(tasks[2][0])
        self.page.get_by_role('tab', name='项目首页', exact=True).click()
        expect(panel).to_be_visible()
        self.page.get_by_role('tab', name='项目内容', exact=True).click()
        self.ready(tasks[2][0])
        self.page.go_back()
        expect(panel).to_be_visible()
        panel.get_by_role('button', name=re.compile('项目资源')).click()
        self.ready(root='resources')
        self.page.get_by_role('tab', name='项目首页', exact=True).click()
        expect(panel).to_be_visible()
        self.page.reload()
        expect(panel).to_be_visible()

    def test_default_to_custom_on_refresh_and_late_default_response(self):
        self.project(A)
        self.delay('nav')
        self.page.get_by_role('tab', name='项目首页', exact=True).click()
        self.delay_ready()
        panel = self.home(B)
        self.release()
        expect(panel).to_contain_text('项目 B')
        resources = self.ws / 'runtime/project_src/项目 B'
        (resources / 'homepage').mkdir()
        (resources / 'homepage/index.html').write_text('<h1>新建自定义首页</h1>', encoding='utf-8')
        write_json(resources / 'workbench.json', dict(schema_version=1, homepage=dict(root_id='resources',path='homepage/index.html')))
        self.page.get_by_test_id('directory-refresh').click()
        expect(self.page.get_by_test_id('homepage-frame')).to_be_visible()
        expect(self.page.frame_locator('[data-testid="homepage-frame"]').locator('h1')).to_have_text('新建自定义首页')
        expect(panel).to_have_count(0)

    def test_layout_themes_and_keyboard(self):
        self.seed()
        panel = self.home()
        for width, height in [(1440,1000),(900,700),(390,844)]:
            self.page.set_viewport_size(dict(width=width,height=height))
            expect(panel).to_be_visible()
            self.assertTrue(panel.evaluate('(e)=>e.scrollWidth <= e.clientWidth + 1'))
            self.page.screenshot(path=str(self.output / f'default-home-{width}.png'))
            panel.get_by_role('button', name='复制提示词', exact=True).scroll_into_view_if_needed()
            expect(panel.get_by_role('button', name='复制提示词', exact=True)).to_be_visible()
            self.page.screenshot(path=str(self.output / f'default-home-guide-{width}.png'))
            panel.evaluate('(e)=>e.scrollTop=0')
        self.page.emulate_media(color_scheme='dark', reduced_motion='reduce')
        self.page.screenshot(path=str(self.output / 'default-home-dark.png'))
        tab = self.page.get_by_role('tab', name='项目首页', exact=True)
        tab.focus(); self.page.keyboard.press('ArrowRight')
        content = self.page.get_by_role('tab', name='项目内容', exact=True)
        expect(content).to_be_focused()
        self.page.keyboard.press('Enter')
        self.ready()
