"""首页默认入口、页面包资源、隔离、历史和配置恢复。"""
from browser_fixture import A, B, SPECIAL, BrowserCase, expect
from tests.helpers import write_json


class HomepageBrowserTests(BrowserCase):
    def test_original_reference_and_package_resources_work_together(self):
        self.prepare()
        originals = self.resources / '原件 [1]#&'
        (originals / 'pages').mkdir(parents=True)
        (originals / 'data.json').write_text('{"title":"原件初版"}', encoding='utf-8')
        (originals / 'icon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"><rect width="12" height="12" fill="green"/></svg>', encoding='utf-8')
        report = originals / 'pages/report.html'
        original_text = '''<!doctype html><html><head><meta charset="utf-8"></head><body>
<h1>加载中</h1><p id="package-script"></p><img alt="引用图片" src="../icon.svg">
<a href="report.html">重读原件</a><a href="../../../首页.html">返回包内首页</a><script>fetch('../data.json').then(r=>r.json()).then(d=>document.querySelector('h1').textContent=d.title)</script></body></html>'''
        report.write_text(original_text, encoding='utf-8')
        (self.pages / 'reading.js').write_text("document.addEventListener('DOMContentLoaded',()=>document.querySelector('#package-script').textContent='包内脚本已加载')", encoding='utf-8')
        home = self.pages / '首页.html'
        home.write_text(home.read_text(encoding='utf-8').replace('</html>', '<a href="_refs/reports/pages/report.html">引用报告</a></html>'), encoding='utf-8')
        write_json(self.resources / 'workbench.json', {'schema_version':1,'homepage':{
            'root_id':'resources','path':self.pages.name+'/首页.html','references':{
                'reports':{'root_id':'resources','path':originals.name,
                           'styles':['style.css'],'scripts':['reading.js']}}}})
        self.select_home()
        self.frame.get_by_role('link', name='引用报告', exact=True).click()
        expect(self.frame.locator('h1')).to_have_text('原件初版')
        expect(self.frame.locator('#package-script')).to_have_text('包内脚本已加载')
        expect(self.frame.locator('h1')).to_have_css('color','rgb(20, 80, 140)')
        expect(self.frame.get_by_role('img', name='引用图片')).to_have_js_property('naturalWidth', 12)
        (originals / 'data.json').write_text('{"title":"原件实时更新"}', encoding='utf-8')
        self.frame.get_by_role('link', name='重读原件').click()
        expect(self.frame.locator('h1')).to_have_text('原件实时更新')
        self.assertEqual(report.read_text(encoding='utf-8'), original_text)
        self.assertEqual(len(list(originals.rglob('report.html'))), 1)
        self.frame.get_by_role('link', name='返回包内首页').click()
        self.home_ready()
        expect(self.frame.locator('#data')).to_have_text('相对资源加载成功')

    def test_homepage_pins_bridge_persists_and_scopes_to_active_project(self):
        self.prepare()
        script = self.pages / 'main.js'
        script.write_text(script.read_text(encoding='utf-8') + """
const output=document.createElement('p'); output.id='pins'; document.body.append(output);
let keys=[];
window.addEventListener('message',event=>{
  if(event.source!==parent || event.data?.type!=='dmy:homepage-pins-result')return;
  if(event.data.error){output.textContent=event.data.error;return;}
  keys=event.data.pins; output.textContent=JSON.stringify(keys);
});
const send=(action,extra={})=>parent.postMessage({type:'dmy:homepage-pins',requestId:crypto.randomUUID(),action,projectId:'forged-project',...extra},'*');
const button=document.createElement('button'); button.textContent='切换收藏';
button.onclick=()=>send('set',{key:'stable-report',pinned:!keys.includes('stable-report')});
document.body.append(button); send('read');
""", encoding='utf-8')
        # 嵌套页不能借用顶层页面的收藏桥接。
        (self.pages / 'next.html').write_text("""<h1>嵌套页</h1><script>
top.postMessage({type:'dmy:homepage-pins',requestId:'nested',action:'set',key:'forged',pinned:true},'*');
</script>""", encoding='utf-8')
        self.select_home()
        expect(self.frame.locator('#pins')).to_have_text('[]')
        self.frame.get_by_role('button', name='切换收藏').click()
        expect(self.frame.locator('#pins')).to_have_text('["stable-report"]')
        self.page.reload()
        self.home_ready()
        expect(self.frame.locator('#pins')).to_have_text('["stable-report"]')
        prefs = self.application.load_preferences()
        self.assertEqual(prefs['homepage_pins'], {A: ['stable-report']})
        self.frame.get_by_role('button', name='切换收藏').click()
        expect(self.frame.locator('#pins')).to_have_text('[]')

    def prepare(self):
        self.resources = self.ws / 'runtime/project_src/项目 A'
        self.pages = self.resources / '页面 包#&'
        self.pages.mkdir(parents=True)
        write_json(self.resources / 'workbench.json', {
            'schema_version': 1,
            'homepage': {'root_id': 'resources', 'path': '页面 包#&/首页.html'}})
        write_json(self.pages / 'data.json', {'title': '相对资源加载成功'})
        (self.pages / '首页.html').write_text('''<!doctype html><html lang="zh-CN">
<meta charset="utf-8"><link rel="stylesheet" href="style.css"><h1>项目首页示例</h1>
<p id="data">加载中</p><p id="isolation"></p><a href="next.html">下一页</a>
<iframe title="项目嵌入子页" src="next.html"></iframe>
<script src="main.js"></script></html>''', encoding='utf-8')
        (self.pages / 'style.css').write_text('h1 { color: rgb(20, 80, 140); }', encoding='utf-8')
        (self.pages / 'main.js').write_text('''fetch('./data.json').then(r => r.json()).then(data => {
document.querySelector('#data').textContent = data.title;
});
try { parent.document.body; document.querySelector('#isolation').textContent = '隔离失败'; }
catch { document.querySelector('#isolation').textContent = '隔离成功'; }
''', encoding='utf-8')
        (self.pages / 'next.html').write_text('<h1>项目自己的子页面</h1>', encoding='utf-8')

    def select_home(self):
        self.page.locator(f'[data-testid="project-link"][data-id="{A}"]').click()
        self.home_ready()

    def home_ready(self):
        expect(self.page.get_by_role('tab', name='项目首页', exact=True)).to_have_attribute('aria-selected', 'true')
        expect(self.page.get_by_test_id('homepage-frame')).to_be_visible()
        self.frame = self.page.frame_locator('[data-testid="homepage-frame"]')
        expect(self.frame.locator('#data')).to_have_text('相对资源加载成功')

    def test_default_home_relative_assets_isolation_and_child_page(self):
        self.prepare()
        self.select_home()
        expect(self.frame.locator('#isolation')).to_have_text('隔离成功')
        expect(self.frame.locator('h1')).to_have_css('color', 'rgb(20, 80, 140)')
        expect(self.frame.frame_locator('iframe').locator('h1')).to_have_text('项目自己的子页面')
        expect(self.page.get_by_test_id('directory-filter')).to_be_hidden()
        expect(self.page.locator('#directory-tools')).to_be_hidden()
        expect(self.page.locator('#main-split')).to_be_hidden()
        box = self.page.get_by_test_id('homepage-frame').bounding_box()
        self.assertGreater(box['height'], 400)
        self.page.screenshot(path=str(self.output / 'homepage.png'))
        self.frame.get_by_role('link', name='下一页').click()
        expect(self.frame.locator('h1')).to_have_text('项目自己的子页面')
        self.assertIn('root_id=homepage', self.page.url)

    def test_tabs_preserve_directory_and_history_and_reload(self):
        self.prepare()
        self.select_home()
        expect(self.page.locator('#root-tabs')).to_be_hidden()
        self.page.get_by_role('tab', name='项目内容', exact=True).click()
        self.ready()
        self.enter(SPECIAL)
        self.page.get_by_role('tab', name='项目首页', exact=True).click()
        self.home_ready()
        collapse = self.page.locator('#btn-showcase-toggle')
        collapse.click()
        expect(collapse).to_have_attribute('aria-expanded', 'false')
        expect(self.page.locator('#sidebar')).to_be_hidden()
        collapse.click()
        expect(self.page.locator('#sidebar')).to_be_visible()
        collapse.click()
        self.page.get_by_role('tab', name='项目内容', exact=True).click()
        self.ready(SPECIAL)
        expect(self.page.locator('#sidebar')).to_be_visible()
        self.page.go_back()
        self.home_ready()
        self.page.go_back()
        self.ready(SPECIAL)
        self.page.go_forward()
        self.home_ready()
        self.page.get_by_role('tab', name='项目内容', exact=True).click()
        self.ready(SPECIAL)
        self.page.get_by_role('tab', name='根目录：项目资源', exact=True).click()
        expect(self.page.get_by_test_id('homepage-frame')).to_have_count(0)
        # paired 位置延续；示例中资源侧不存在这个目录，仍按原契约显示错误。
        expect(self.page.locator('#error-view')).to_be_visible()
        self.page.get_by_role('tab', name='根目录：文档', exact=True).click()
        self.ready(SPECIAL)
        self.page.get_by_role('tab', name='项目首页', exact=True).click()
        self.home_ready()
        self.page.reload()
        self.home_ready()
        self.page.get_by_role('tab', name='项目内容', exact=True).click()
        self.ready()

    def test_invalid_home_keeps_tabs_and_refresh_recovers(self):
        self.prepare()
        (self.resources / 'workbench.json').write_text('{broken', encoding='utf-8')
        self.page.locator(f'[data-testid="project-link"][data-id="{A}"]').click()
        expect(self.page.locator('#error-view')).to_be_visible()
        expect(self.page.locator('#error-message')).to_contain_text('workbench.json')
        self.page.get_by_role('tab', name='项目内容', exact=True).click()
        self.ready()
        write_json(self.resources / 'workbench.json', {'schema_version': 1,
            'homepage': {'root_id': 'resources', 'path': '页面 包#&/首页.html'}})
        self.page.get_by_test_id('directory-refresh').click()
        self.ready()
        self.page.get_by_role('tab', name='项目首页', exact=True).click()
        self.home_ready()
        self.page.get_by_test_id('directory-refresh').click()
        self.home_ready()

    def test_project_without_home_and_late_response(self):
        self.prepare()
        self.delay('homepage')
        self.page.locator(f'[data-testid="project-link"][data-id="{A}"]').click()
        self.delay_ready()
        self.project(B)
        self.release()
        expect(self.page.get_by_role('tab', name='项目首页', exact=True)).to_have_count(0)
        expect(self.page.get_by_test_id('homepage-frame')).to_have_count(0)
        self.ready(project=B)

    def test_start_prefers_home_but_explicit_directory_url_is_preserved(self):
        self.prepare()
        self.select_home()
        self.page.get_by_role('tab', name='项目内容', exact=True).click()
        self.ready()
        self.enter(SPECIAL)
        self.page.wait_for_function("""async () => {
          const response = await fetch('/api/v1/preferences');
          return (await response.json()).data.last_location?.relative_path === '中文 空格[目录]#&';
        }""")
        self.page.reload()
        self.ready(SPECIAL)
        self.page.goto(self.origin + '/')
        self.home_ready()
        self.page.wait_for_function("""async () => {
          const response = await fetch('/api/v1/preferences');
          return (await response.json()).data.last_location?.root_id === 'homepage';
        }""")
        (self.resources / 'workbench.json').unlink()
        self.page.goto(self.origin + '/')
        self.ready()
        expect(self.page.get_by_role('tab', name='项目首页', exact=True)).to_have_count(0)
