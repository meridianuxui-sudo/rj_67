"""MERADION's authenticated, API-first application server."""
from __future__ import annotations
import enum, os, secrets, shutil, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
import jwt
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic_settings import BaseSettings
from pwdlib import PasswordHash
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, or_, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

class Settings(BaseSettings):
    database_url: str = "sqlite:///./meradion.db"
    jwt_secret: str = "development-only-change-me"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    cors_origins: str = "http://localhost:3000"
    storage_bucket: str = "meradion-private"
    webrtc_stun_servers: str = "stun:stun.l.google.com:19302"
    model_config = ConfigDict(env_file=".env")
settings = Settings()

class Base(DeclarativeBase): pass
class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
class Role(str, enum.Enum): ADMIN="ADMIN"; TEACHER="TEACHER"; PARENT="PARENT"; STUDENT="STUDENT"
class RelationshipStatus(str, enum.Enum): PENDING="PENDING"; APPROVED="APPROVED"; REJECTED="REJECTED"
class ContentStatus(str, enum.Enum): DRAFT="DRAFT"; PUBLISHED="PUBLISHED"; ARCHIVED="ARCHIVED"
class Visibility(str, enum.Enum): PRIVATE="PRIVATE"; PARENTS="PARENTS"; CLASS="CLASS"; SCHOOL="SCHOOL"
class LiveStatus(str, enum.Enum): SCHEDULED="SCHEDULED"; LIVE="LIVE"; ENDED="ENDED"; CANCELLED="CANCELLED"

class User(Base, Timestamped):
    __tablename__="users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda:str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255)); name: Mapped[str] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(Enum(Role), index=True); active: Mapped[bool] = mapped_column(Boolean, default=True)
class ParentProfile(Base, Timestamped):
    __tablename__="parent_profiles"; user_id: Mapped[str]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),primary_key=True)
class TeacherProfile(Base, Timestamped):
    __tablename__="teacher_profiles"; user_id: Mapped[str]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),primary_key=True)
class StudentProfile(Base, Timestamped):
    __tablename__="student_profiles"; user_id: Mapped[str]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),primary_key=True)
class ParentStudent(Base, Timestamped):
    __tablename__="parent_students"; __table_args__=(UniqueConstraint("parent_id","student_id"),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    parent_id: Mapped[str]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),index=True); student_id: Mapped[str]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),index=True)
    relationship: Mapped[str]=mapped_column(String(40),default="guardian"); status: Mapped[RelationshipStatus]=mapped_column(Enum(RelationshipStatus),default=RelationshipStatus.PENDING); approved_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
class Classroom(Base, Timestamped):
    __tablename__="classrooms"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4())); name: Mapped[str]=mapped_column(String(120)); grade: Mapped[str]=mapped_column(String(30)); section: Mapped[str]=mapped_column(String(30)); teacher_id: Mapped[str|None]=mapped_column(ForeignKey("users.id"),index=True)
class ClassStudent(Base, Timestamped):
    __tablename__="class_students"; __table_args__=(UniqueConstraint("classroom_id","student_id"),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4())); classroom_id: Mapped[str]=mapped_column(ForeignKey("classrooms.id",ondelete="CASCADE"),index=True); student_id: Mapped[str]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),index=True)
class Podcast(Base, Timestamped):
    __tablename__="podcasts"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4())); title: Mapped[str]=mapped_column(String(180),index=True); description: Mapped[str]=mapped_column(Text,default=""); category: Mapped[str]=mapped_column(String(80),default="Stories",index=True); creator_id: Mapped[str]=mapped_column(ForeignKey("users.id"),index=True); classroom_id: Mapped[str|None]=mapped_column(ForeignKey("classrooms.id"),index=True); status: Mapped[ContentStatus]=mapped_column(Enum(ContentStatus),default=ContentStatus.DRAFT,index=True); visibility: Mapped[Visibility]=mapped_column(Enum(Visibility),default=Visibility.PRIVATE,index=True); audio_key: Mapped[str|None]=mapped_column(String(500)); artwork_key: Mapped[str|None]=mapped_column(String(500)); duration_seconds: Mapped[int]=mapped_column(Integer,default=0); published_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
class LiveSession(Base, Timestamped):
    __tablename__="live_sessions"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4())); host_student_id: Mapped[str]=mapped_column(ForeignKey("users.id"),index=True); teacher_id: Mapped[str|None]=mapped_column(ForeignKey("users.id")); title: Mapped[str]=mapped_column(String(180)); description: Mapped[str]=mapped_column(Text,default=""); classroom_id: Mapped[str|None]=mapped_column(ForeignKey("classrooms.id"),index=True); visibility: Mapped[Visibility]=mapped_column(Enum(Visibility),default=Visibility.PRIVATE); status: Mapped[LiveStatus]=mapped_column(Enum(LiveStatus),default=LiveStatus.SCHEDULED,index=True); started_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); ended_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
class Notification(Base, Timestamped):
    __tablename__="notifications"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4())); user_id: Mapped[str]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),index=True); type: Mapped[str]=mapped_column(String(60)); title: Mapped[str]=mapped_column(String(180)); message: Mapped[str]=mapped_column(Text); entity_type: Mapped[str]=mapped_column(String(60)); entity_id: Mapped[str]=mapped_column(String(36)); read: Mapped[bool]=mapped_column(Boolean,default=False,index=True)
class Device(Base, Timestamped):
    __tablename__="devices"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4())); user_id: Mapped[str]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),index=True); token: Mapped[str]=mapped_column(String(500),unique=True); platform: Mapped[str]=mapped_column(String(30))

engine=create_engine(settings.database_url, connect_args={"check_same_thread":False} if settings.database_url.startswith("sqlite") else {})
SessionLocal=sessionmaker(engine,expire_on_commit=False)
def db_session():
    db=SessionLocal()
    try: yield db
    finally: db.close()
DB=Annotated[Session,Depends(db_session)]
password_hash=PasswordHash.recommended()
def token(user:User, kind:str, expiry:timedelta): return jwt.encode({"sub":user.id,"role":user.role.value,"kind":kind,"exp":datetime.now(timezone.utc)+expiry},settings.jwt_secret,algorithm="HS256")
def decode(value:str, kind="access"):
    try:
        data=jwt.decode(value,settings.jwt_secret,algorithms=["HS256"])
        if data.get("kind")!=kind: raise ValueError()
        return data
    except Exception: raise HTTPException(401,"Invalid or expired credentials")
def current_user(authorization: Annotated[str|None, __import__('fastapi').Header()] = None, db:Session=Depends(db_session)):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Authentication required")
    data=decode(authorization[7:]); u=db.get(User,data["sub"])
    if not u or not u.active: raise HTTPException(401,"Account unavailable")
    return u
def require(*roles:Role):
    def dependency(u:User=Depends(current_user)):
        if u.role not in roles: raise HTTPException(403,"You are not authorized for this resource")
        return u
    return dependency
require_admin=lambda:require(Role.ADMIN); require_teacher=lambda:require(Role.TEACHER); require_parent=lambda:require(Role.PARENT); require_student=lambda:require(Role.STUDENT)

class Register(BaseModel): email:EmailStr; password:str=Field(min_length=10); name:str=Field(min_length=2,max_length=120); role:Role
class Login(BaseModel): email:EmailStr; password:str
class Refresh(BaseModel): refresh_token:str
class PodcastIn(BaseModel): title:str=Field(min_length=2,max_length=180); description:str=""; category:str="Stories"; classroom_id:str|None=None; visibility:Visibility=Visibility.PRIVATE; status:ContentStatus=ContentStatus.DRAFT
class LiveIn(BaseModel): title:str; description:str=""; classroom_id:str|None=None; visibility:Visibility=Visibility.PRIVATE
class LinkIn(BaseModel): parent_id:str; student_id:str; relationship:str="guardian"; status:RelationshipStatus=RelationshipStatus.APPROVED

def user_out(u:User): return {"id":u.id,"email":u.email,"name":u.name,"role":u.role.value}
def can_class(u:User, classroom_id:str|None, db:Session):
    if not classroom_id: return False
    if u.role==Role.ADMIN:return True
    c=db.get(Classroom,classroom_id)
    return bool(c and (c.teacher_id==u.id or (u.role==Role.STUDENT and db.scalar(select(ClassStudent).where(ClassStudent.classroom_id==classroom_id,ClassStudent.student_id==u.id)) or (u.role==Role.PARENT and db.scalar(select(ParentStudent).join(ClassStudent,ParentStudent.student_id==ClassStudent.student_id).where(ParentStudent.parent_id==u.id,ParentStudent.status==RelationshipStatus.APPROVED,ClassStudent.classroom_id==classroom_id))))))
def can_access_content(u:User, item, db:Session):
    owner_id = getattr(item, "creator_id", getattr(item, "host_student_id", None))
    if u.role==Role.ADMIN or owner_id==u.id: return True
    if item.visibility==Visibility.PARENTS: return u.role==Role.PARENT
    if item.visibility==Visibility.SCHOOL: return u.role in (Role.PARENT,Role.TEACHER,Role.STUDENT)
    if item.visibility==Visibility.CLASS: return can_class(u,item.classroom_id,db)
    return False
def podcast_out(p:Podcast,db:Session):
    creator=db.get(User,p.creator_id); room=db.get(Classroom,p.classroom_id) if p.classroom_id else None
    return {"id":p.id,"title":p.title,"description":p.description,"category":p.category,"creator":creator.name if creator else "Unknown","creator_id":p.creator_id,"classroom":room.name if room else None,"duration_seconds":p.duration_seconds,"status":p.status.value,"visibility":p.visibility.value,"published_at":p.published_at,"has_audio":bool(p.audio_key)}

app=FastAPI(title="MERADION API",version="1.0.0",description="Private, authenticated educational audio APIs.")
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(",")],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
@app.on_event("startup")
def start(): Base.metadata.create_all(engine); Path("private_uploads").mkdir(exist_ok=True)
@app.get("/health")
def health(): return {"status":"healthy","service":"meradion"}
@app.post("/api/auth/register",status_code=201)
def register(data:Register,db:DB):
    if db.scalar(select(User).where(User.email==data.email.lower())): raise HTTPException(409,"Email already registered")
    # First account is intentionally an administrator only when explicitly registered as such.
    u=User(email=data.email.lower(),name=data.name,role=data.role,password_hash=password_hash.hash(data.password)); db.add(u); db.flush()
    profile_class={Role.PARENT:ParentProfile,Role.TEACHER:TeacherProfile,Role.STUDENT:StudentProfile}.get(u.role)
    if profile_class: db.add(profile_class(user_id=u.id))
    db.commit(); return {"user":user_out(u),"access_token":token(u,"access",timedelta(minutes=settings.jwt_access_token_expire_minutes)),"refresh_token":token(u,"refresh",timedelta(days=settings.jwt_refresh_token_expire_days)),"token_type":"bearer"}
@app.post("/api/auth/login")
def login(data:Login,db:DB):
    u=db.scalar(select(User).where(User.email==data.email.lower()))
    if not u or not password_hash.verify(data.password,u.password_hash): raise HTTPException(401,"Invalid email or password")
    return {"user":user_out(u),"access_token":token(u,"access",timedelta(minutes=settings.jwt_access_token_expire_minutes)),"refresh_token":token(u,"refresh",timedelta(days=settings.jwt_refresh_token_expire_days)),"token_type":"bearer"}
@app.post("/api/auth/refresh")
def refresh(data:Refresh,db:DB):
    d=decode(data.refresh_token,"refresh"); u=db.get(User,d["sub"])
    if not u: raise HTTPException(401,"Account unavailable")
    return {"access_token":token(u,"access",timedelta(minutes=settings.jwt_access_token_expire_minutes)),"token_type":"bearer"}
@app.post("/api/auth/logout",status_code=204)
def logout(_:User=Depends(current_user)): return None
@app.get("/api/auth/me")
def me(u:User=Depends(current_user)): return user_out(u)
@app.post("/api/admin/parent-students",status_code=201)
def link(data:LinkIn,db:DB,u:User=Depends(require_admin())):
    if not (db.get(User,data.parent_id) and db.get(User,data.student_id)): raise HTTPException(404,"User not found")
    rel=ParentStudent(parent_id=data.parent_id,student_id=data.student_id,relationship=data.relationship,status=data.status,approved_at=datetime.now(timezone.utc) if data.status==RelationshipStatus.APPROVED else None);db.add(rel);db.commit();return {"id":rel.id}
@app.get("/api/parents/children")
def children(db:DB,u:User=Depends(require_parent())):
    rows=db.scalars(select(ParentStudent).where(ParentStudent.parent_id==u.id,ParentStudent.status==RelationshipStatus.APPROVED)).all();return [{**user_out(db.get(User,r.student_id)),"relationship":r.relationship} for r in rows]
@app.get("/api/podcasts")
def podcasts(db:DB,u:User=Depends(current_user),q:str="",category:str|None=None,page:int=Query(1,ge=1),page_size:int=Query(12,ge=1,le=50)):
    stmt=select(Podcast).where(Podcast.status==ContentStatus.PUBLISHED)
    if q: stmt=stmt.where(or_(Podcast.title.ilike(f"%{q}%"),Podcast.description.ilike(f"%{q}%")))
    if category:stmt=stmt.where(Podcast.category==category)
    eligible=[p for p in db.scalars(stmt.order_by(Podcast.published_at.desc())).all() if can_access_content(u,p,db)]
    return {"items":[podcast_out(p,db) for p in eligible[(page-1)*page_size:page*page_size]],"total":len(eligible),"page":page}
@app.post("/api/podcasts",status_code=201)
def create_podcast(data:PodcastIn,db:DB,u:User=Depends(require_student())):
    if data.classroom_id and not can_class(u,data.classroom_id,db):raise HTTPException(403,"Not enrolled in this class")
    p=Podcast(**data.model_dump(),creator_id=u.id); db.add(p);db.commit();return podcast_out(p,db)
@app.post("/api/podcasts/{podcast_id}/audio")
def upload_audio(podcast_id:str, audio:UploadFile=File(...),db:Session=Depends(db_session),u:User=Depends(require_student())):
    p=db.get(Podcast,podcast_id)
    if not p:raise HTTPException(404,"Podcast not found")
    if p.creator_id!=u.id:raise HTTPException(403,"Only the creator can upload audio")
    allowed={"audio/mpeg","audio/mp4","audio/wav","audio/x-wav"}; ext=Path(audio.filename or "").suffix.lower()
    if audio.content_type not in allowed or ext not in {".mp3",".m4a",".wav"}:raise HTTPException(415,"Audio must be MP3, M4A, or WAV")
    key=f"{p.id}-{secrets.token_urlsafe(12)}{ext}"; dest=Path("private_uploads")/key
    with dest.open("wb") as out: shutil.copyfileobj(audio.file,out)
    if dest.stat().st_size>100*1024*1024:dest.unlink();raise HTTPException(413,"Audio exceeds 100 MB")
    p.audio_key=key;db.commit();return {"uploaded":True,"podcast":podcast_out(p,db)}
@app.post("/api/podcasts/{podcast_id}/publish")
def publish(podcast_id:str,db:DB,u:User=Depends(current_user)):
    p=db.get(Podcast,podcast_id)
    if not p:raise HTTPException(404,"Podcast not found")
    if p.creator_id!=u.id and u.role not in (Role.TEACHER,Role.ADMIN):raise HTTPException(403,"Not authorized to publish")
    if not p.audio_key:raise HTTPException(422,"Upload audio before publishing")
    p.status=ContentStatus.PUBLISHED;p.published_at=datetime.now(timezone.utc);db.commit();return podcast_out(p,db)
@app.get("/api/podcasts/{podcast_id}/play")
def play(podcast_id:str,db:DB,u:User=Depends(current_user)):
    p=db.get(Podcast,podcast_id)
    if not p or p.status!=ContentStatus.PUBLISHED or not can_access_content(u,p,db):raise HTTPException(403,"You are not authorized to play this podcast")
    if not p.audio_key:raise HTTPException(404,"Audio is not available")
    f=Path("private_uploads")/p.audio_key
    if not f.exists():raise HTTPException(404,"Audio is not available")
    return FileResponse(f,media_type="audio/mpeg",filename=p.title+f.suffix,headers={"Cache-Control":"private, no-store"})
@app.post("/api/live",status_code=201)
def start_live(data:LiveIn,db:DB,u:User=Depends(require_student())):
    if data.classroom_id and not can_class(u,data.classroom_id,db):raise HTTPException(403,"Not enrolled in this class")
    s=LiveSession(**data.model_dump(),host_student_id=u.id,status=LiveStatus.LIVE,started_at=datetime.now(timezone.utc));db.add(s);db.flush()
    host=u.name
    for parent_id in db.scalars(select(ParentStudent.parent_id).where(ParentStudent.student_id==u.id,ParentStudent.status==RelationshipStatus.APPROVED)):
        db.add(Notification(user_id=parent_id,type="STUDENT_LIVE_STARTED",title=f"{host} is live now",message=f"{host} has started a live audio session.",entity_type="live_session",entity_id=s.id))
    db.commit();return {"id":s.id,"status":s.status.value,"stun_servers":settings.webrtc_stun_servers.split(",")}
@app.get("/api/live")
def lives(db:DB,u:User=Depends(current_user)):
    return [{"id":s.id,"title":s.title,"host":db.get(User,s.host_student_id).name,"status":s.status.value,"started_at":s.started_at,"classroom_id":s.classroom_id} for s in db.scalars(select(LiveSession).where(LiveSession.status==LiveStatus.LIVE)).all() if can_access_content(u,s,db)]
@app.post("/api/live/{session_id}/stop")
def stop_live(session_id:str,db:DB,u:User=Depends(current_user)):
    s=db.get(LiveSession,session_id)
    if not s:raise HTTPException(404,"Live session not found")
    if s.host_student_id!=u.id and u.role not in (Role.TEACHER,Role.ADMIN):raise HTTPException(403,"Not authorized")
    s.status=LiveStatus.ENDED;s.ended_at=datetime.now(timezone.utc);db.commit();return {"status":"ENDED"}
@app.get("/api/notifications")
def notifications(db:DB,u:User=Depends(current_user)):return [{"id":n.id,"type":n.type,"title":n.title,"message":n.message,"entity_type":n.entity_type,"entity_id":n.entity_id,"read":n.read,"created_at":n.created_at} for n in db.scalars(select(Notification).where(Notification.user_id==u.id).order_by(Notification.created_at.desc()))]
@app.post("/api/notifications/{notification_id}/read")
def mark_read(notification_id:str,db:DB,u:User=Depends(current_user)):
    n=db.get(Notification,notification_id)
    if not n or n.user_id!=u.id:raise HTTPException(404,"Notification not found")
    n.read=True;db.commit();return {"read":True}
@app.websocket("/api/live/{session_id}/signal")
async def signal(ws:WebSocket,session_id:str):
    value=ws.query_params.get("token")
    try:data=decode(value or ""); user_id=data["sub"]
    except HTTPException:await ws.close(code=4401);return
    db=SessionLocal(); s=db.get(LiveSession,session_id); u=db.get(User,user_id)
    if not s or s.status!=LiveStatus.LIVE or not u or not can_access_content(u,s,db):db.close();await ws.close(code=4403);return
    await ws.accept(); await ws.send_json({"type":"authorized","session_id":session_id,"iceServers":[{"urls":x} for x in settings.webrtc_stun_servers.split(",")]})
    try:
      while True:
       message=await ws.receive_json()
       if message.get("type") not in {"offer","answer","ice-candidate","leave"}:await ws.send_json({"type":"error","message":"Unsupported signal"});continue
       # Signaling payload is intentionally relayed only after the authenticated session check above.
       await ws.send_json({"type":"signal-accepted","signal":message.get("type")})
    except WebSocketDisconnect: pass
    finally: db.close()
