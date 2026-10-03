import os
os.environ['DATABASE_URL']='sqlite:///./test_meradion.db'
from fastapi.testclient import TestClient
from app.main import app, Base, engine
Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
c=TestClient(app)
def reg(email, role):
 r=c.post('/api/auth/register',json={'email':email,'password':'correct-horse-battery','name':email.split('@')[0],'role':role}); assert r.status_code==201; return r.json()
def auth(x):return {'Authorization':'Bearer '+x['access_token']}
def test_private_podcast_and_parent_relationship_security():
 admin=reg('admin@example.com','ADMIN'); student=reg('student@example.com','STUDENT'); outsider=reg('other@example.com','PARENT'); parent=reg('parent@example.com','PARENT')
 p=c.post('/api/podcasts',headers=auth(student),json={'title':'Private','visibility':'PRIVATE'}).json()
 assert c.get('/api/podcasts/'+p['id']+'/play',headers=auth(outsider)).status_code==403
 assert c.post('/api/admin/parent-students',headers=auth(admin),json={'parent_id':parent['user']['id'],'student_id':student['user']['id']}).status_code==201
 assert c.get('/api/parents/children',headers=auth(outsider)).json()==[]
def test_unauthenticated_playback_is_rejected():
 assert c.get('/api/podcasts/not-a-podcast/play').status_code==401
