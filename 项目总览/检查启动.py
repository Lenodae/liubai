"""Verify both local entrypoints without creating accounts or changing task data."""
import http.cookiejar
import json
import urllib.error
import urllib.request
from pathlib import Path

results=[]
for port,csrf in [(8000,'csrftoken'),(8001,'taskflow2_csrf')]:
    jar=http.cookiejar.CookieJar()
    opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base=f'http://127.0.0.1:{port}'
    with opener.open(base,timeout=5) as response:
        assert response.status==200
    token=next(c.value for c in jar if c.name==csrf)
    request=urllib.request.Request(base+'/api/auth/login',data=json.dumps({'username':'startup_smoke_nonexistent','password':'not-a-real-password'}).encode(),headers={'Content-Type':'application/json','X-CSRFToken':token})
    try:
        opener.open(request,timeout=5)
        raise AssertionError('Unexpected authentication')
    except urllib.error.HTTPError as error:
        assert error.code==401,(port,error.code,'Repeated probes may hit the normal login rate limit.')
    results.append({'port':port,'homepage':200,'database_backed_login':401,'csrf_cookie':csrf})
Path(__file__).with_name('启动验收.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps(results,ensure_ascii=False))
