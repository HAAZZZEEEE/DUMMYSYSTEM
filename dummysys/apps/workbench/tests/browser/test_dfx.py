"""前端请求与渲染计时、结构化失败与有限采样。"""
import json
from unittest.mock import patch
from tests.browser.browser_fixture import BrowserCase, expect


class DfxBrowserTests(BrowserCase):
    def test_request_render_samples_and_error_correlation(self):
        with patch.object(self.application,'_ptr_read',return_value=dict(total_calls=0,commands=[])):
            self.page.get_by_role('button',name='回到首页',exact=True).click()
            expect(self.page.locator('.ov-project')).to_have_count(2)
            for _ in range(30):
                self.page.get_by_role('button',name='↻ 刷新沙盘',exact=True).click()
                expect(self.page.locator('#overview')).to_have_attribute('aria-busy','false')
        samples=self.page.evaluate("async () => (await import('/diagnostics.js')).snapshot()")
        render=[r['elapsedMs'] for r in samples if r['phase']=='render' and r['operation']=='overview']
        requests=[r for r in samples if r['phase']=='request' and r['operation']=='overview']
        self.assertGreaterEqual(len(render),30);self.assertGreaterEqual(len(requests),30)
        self.assertTrue(all(r.get('diagnosticId') for r in requests));self.assertLessEqual(len(samples),100)
        (self.output/'frontend-timing.json').write_text(json.dumps(dict(render_ms=render,requests=requests),ensure_ascii=False,indent=2),encoding='utf-8')
        self.page.route('**/api/v1/failure',lambda route:route.fulfill(status=409,headers={'X-Diagnostic-ID':'trace-id'},
            content_type='application/json',body=json.dumps(dict(error=dict(code='VERSION_CONFLICT',message='版本变化',next_action='重新查询')))))
        error=self.page.evaluate("""async () => {
          const {api}=await import('/api.js');
          try {await api('failure');} catch(e) {return {code:e.code,id:e.diagnostic_id,next:e.next_action};}
        }""")
        self.assertEqual(error,dict(code='VERSION_CONFLICT',id='trace-id',next='重新查询'))
