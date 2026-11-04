"""首页 Explorer 桥：真实消息、后端路径校验与隔离导航。"""
import json
from pathlib import Path

from browser_fixture import A, B, SPECIAL, SAME, BrowserCase, expect
from tests.helpers import write_json


class HomepageExplorerTests(BrowserCase):
    def prepare(self):
        pages = self.ws / 'runtime/project_src/项目 A/homepage'
        pages.mkdir(parents=True)
        write_json(pages.parent / 'workbench.json', {'schema_version':1,
            'homepage':{'root_id':'resources','path':'homepage/index.html'}})
        (pages / 'index.html').write_text('''<h1>Explorer桥测试</h1><p id="result"></p>
<a href="reference.html#file">查看路径</a><iframe src="nested.html"></iframe><script>
window.sendOpen=(target,requestId=crypto.randomUUID())=>parent.postMessage({type:'dmy:homepage-explorer',requestId,target},'*');
window.addEventListener('message',event=>{if(event.source===parent&&event.data?.type==='dmy:homepage-explorer-result')document.querySelector('#result').textContent=JSON.stringify(event.data)});
</script>''', encoding='utf-8')
        (pages / 'nested.html').write_text('''<p>嵌套页</p><script>
top.postMessage({type:'dmy:homepage-explorer',requestId:'nested',target:{root_id:'docs',relative_path:''}},'*');
</script>''', encoding='utf-8')
        self.page.locator(f'[data-testid="project-link"][data-id="{A}"]').click()
        expect(self.page.get_by_test_id('homepage-frame')).to_be_visible()
        self.frame = self.page.frame_locator('[data-testid="homepage-frame"]')
        expect(self.frame.locator('h1')).to_have_text('Explorer桥测试')
        return pages

    def send(self, target, request='test'):
        self.frame.locator('body').evaluate('(el,arg)=>{document.querySelector("#result").textContent="";window.sendOpen(arg.target,arg.request)}', {'target':target,'request':request})
        expect(self.frame.locator('#result')).not_to_be_empty()
        return json.loads(self.frame.locator('#result').inner_text())

    def test_directory_file_dedup_and_rejected_targets(self):
        self.prepare()
        result = self.send({'root_id':'docs','relative_path':SPECIAL}, 'directory')
        self.assertEqual(result['action'], 'explorer_open')
        result = self.send({'root_id':'docs','relative_path':SPECIAL+'/'+SAME}, 'file')
        self.assertEqual(result['action'], 'explorer_reveal')
        self.assertEqual([e['action'] for e in self.opener.events()], ['explorer_open','explorer_reveal'])
        self.assertEqual(Path(self.opener.events()[-1]['target']), self.docs[A]/SPECIAL/SAME)
        self.send({'root_id':'docs','relative_path':SPECIAL+'/'+SAME}, 'file')
        self.assertEqual(len(self.opener.events()), 2)
        self.assertIn('error', self.send({'root_id':'docs','relative_path':''}, 'file'))
        for index, target in enumerate((
                {'root_id':'docs','relative_path':'../private'},
                {'root_id':'docs','relative_path':'C:/Windows'},
                {'root_id':'repo:unregistered','relative_path':''},
                {'root_id':'docs','relative_path':'missing'},
                {'project_id':B,'root_id':'docs','relative_path':''})):
            with self.subTest(target=target):
                self.assertIn('error', self.send(target, 'reject-'+str(index)))
        self.assertEqual(len(self.opener.events()), 2)

    def test_navigation_cancels_open_before_dispatch(self):
        self.prepare()
        self.delay('actions', project=A)
        self.frame.locator('body').evaluate("()=>window.sendOpen({root_id:'docs',relative_path:''})")
        self.delay_ready()
        self.project(B)
        self.release()
        self.assertEqual(self.opener.events(), [])
        expect(self.page.get_by_test_id('homepage-frame')).to_have_count(0)

