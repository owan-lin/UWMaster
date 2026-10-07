import http.client, importlib.util, json, shutil, threading
from pathlib import Path
from http.server import ThreadingHTTPServer

HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('server',HERE/'server.py');s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
def snapshot(term='fall', due='2026-11-02T09:00:00-08:00'):
 return {'schema_version':1,'term':{'id':term,'name':term,'timezone':'America/Los_Angeles'},'courses':[{'id':'c','code':'CSE','title':'Test'}],'tasks':[{'id':'t','course_id':'c','title':'Work','kind':'homework','due':due,'certainty':'verified'}]}
root=HERE/'_test_runtime';shutil.rmtree(root,ignore_errors=True);root.mkdir()
try:
 s.DATA=root/'data';s.DATA.mkdir();s.SNAPSHOT=root/'snapshot.json';s.STATE=s.DATA/'user_state.json';s.HISTORY=s.DATA/'history.json';s.SNAPSHOT.write_text(json.dumps(snapshot()),encoding='utf8')
 def start():
  h=ThreadingHTTPServer(('127.0.0.1',0),s.App);threading.Thread(target=h.serve_forever,daemon=True).start();return h
 h=start();port=h.server_port
 def request(method,path,body=None):
  con=http.client.HTTPConnection('127.0.0.1',port);headers={'Host':f'127.0.0.1:{port}','Origin':f'http://127.0.0.1:{port}','X-UW-Course-Panel':'local-ui'}
  con.request(method,path,json.dumps(body) if body else None,headers);r=con.getresponse();raw=r.read();con.close();return r.status,json.loads(raw) if 'json' in r.getheader('Content-Type','') else raw.decode()
 assert request('POST','/api/task-state',{'id':'t','completed':True,'note':'note'})[0]==200
 h.shutdown();h.server_close();h=start();port=h.server_port
 assert request('GET','/api/data')[1]['tasks'][0]['user_completed'] is True
 # Brand assets are public; snapshots, notes and arbitrary files remain private.
 for asset in ('uw-logo.svg','uw-campus.jpg','fonts.css','font-1.ttf','font-2.ttf','font-3.ttf','font-4.ttf'):
  con=http.client.HTTPConnection('127.0.0.1',port);con.request('GET','/assets/'+asset)
  response=con.getresponse();assert response.status==200,asset;assert response.read();con.close()
 for path in ('/snapshot.json','/data/user_state.json','/assets/SOURCES.md','/assets/../snapshot.json'):
  assert request('GET',path)[0]==404,path
 merged=s.merge_snapshot(snapshot(),snapshot(due='2026-11-03T09:00:00-08:00'));assert len(merged['tasks'])==1 and merged['tasks'][0]['due'].startswith('2026-11-03')
 assert s.merge_snapshot(snapshot(),snapshot('winter'))['term']['id']=='winter'
 ics=s.build_ics({'tasks':[{'id':'a','title':'A','due':'2026-11-02','certainty':'verified'},{'id':'b','title':'B','due':'2026-11-02T09:00:00-08:00','certainty':'verified'},{'id':'c','title':'C','due':None,'certainty':'verified'},{'id':'d','title':'D','due':'2026-11-02','certainty':'tentative'},{'id':'e','title':'E','due':'2026-11-02','certainty':'verified','user_completed':True}]})
 assert 'DTSTART;VALUE=DATE:20261102' in ics and 'DTSTART:20261102T170000Z' in ics and 'SUMMARY:C' not in ics and 'SUMMARY:D' not in ics and 'SUMMARY:E' not in ics
 h.shutdown();h.server_close()
finally: shutil.rmtree(root,ignore_errors=True)
print('PASS')
