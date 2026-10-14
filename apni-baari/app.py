from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import datetime, timezone
import sqlite3, secrets, math, json, os

BASE = Path(__file__).resolve().parent
DB = BASE / 'apni_baari.db'
app = FastAPI(title='Apni BAARI e-Procurement API', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

MANDIS = {
    'Karnal': {'lat':29.6857,'lng':76.9905,'temp':31,'rain':45,'ahead':27,'bridges':3},
    'Khanna': {'lat':30.7046,'lng':76.2201,'temp':32,'rain':18,'ahead':12,'bridges':3},
    'Bhopal': {'lat':23.2599,'lng':77.4126,'temp':29,'rain':62,'ahead':34,'bridges':2},
    'Kota': {'lat':25.2138,'lng':75.8648,'temp':34,'rain':12,'ahead':8,'bridges':4},
    'Nizamabad': {'lat':18.6725,'lng':78.0941,'temp':30,'rain':41,'ahead':21,'bridges':3},
}
MSP = {'Wheat':2425,'Paddy':2320,'Mustard':5950,'Gram':5650}
VEHICLE_MIN = {'Tractor-trolley':18,'Mini-Truck':25,'Multi-axle Truck':40}

class TokenIn(BaseModel):
    mandi: str
    crop: str
    quantity: float = Field(gt=0)
    vehicle: str
    vehicle_no: str = ''
    slot: str

class CheckinIn(BaseModel):
    token_id: str
    lat: float | None = None
    lng: float | None = None

class RescheduleIn(BaseModel):
    token_id: str
    slot: str

class OfflineIn(BaseModel):
    token_id: str
    payload: dict = {}

class QualityIn(BaseModel):
    token_id: str | None = None
    moisture: float = 11.4
    foreign_matter: float = 0.5
    broken_grains: float = 1.2
    grade: str = 'FAQ Grade A'

class JFormIn(BaseModel):
    token_id: str | None = None
    gross_kg: float = Field(ge=0)
    tare_kg: float = Field(ge=0)
    crop: str = 'Wheat'


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS tokens(
      id TEXT PRIMARY KEY, mandi TEXT, crop TEXT, quantity REAL, vehicle TEXT,
      vehicle_no TEXT, slot TEXT, stage INTEGER DEFAULT 1, checked_in INTEGER DEFAULT 0,
      created_at TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS offline_tokens(id TEXT PRIMARY KEY, payload TEXT, synced INTEGER DEFAULT 0, created_at TEXT);
    CREATE TABLE IF NOT EXISTS quality(id INTEGER PRIMARY KEY AUTOINCREMENT, token_id TEXT, moisture REAL, foreign_matter REAL, broken_grains REAL, grade TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS jforms(id INTEGER PRIMARY KEY AUTOINCREMENT, token_id TEXT, crop TEXT, gross_kg REAL, tare_kg REAL, net_kg REAL, payout REAL, utr TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, message TEXT, created_at TEXT);
    '''); c.commit(); c.close()
init_db()

@app.get('/api/health')
def health(): return {'ok':True,'service':'Apni BAARI','time':datetime.now(timezone.utc).isoformat()}

@app.get('/api/mandis')
def mandis():
    return [{'name':k, **v, 'congestion': math.ceil(v['ahead']*18/max(v['bridges'],1)/4)} for k,v in MANDIS.items()]

@app.get('/api/msp')
def msp(): return MSP

@app.get('/api/queue/{mandi}')
def queue(mandi: str, vehicle: str='Tractor-trolley'):
    if mandi not in MANDIS: raise HTTPException(404,'Mandi not found')
    if vehicle not in VEHICLE_MIN: vehicle='Tractor-trolley'
    d=MANDIS[mandi]; ewt=math.ceil(d['ahead']*VEHICLE_MIN[vehicle]/max(d['bridges'],1)/4)
    return {'mandi':mandi,'ahead':d['ahead'],'bridges':d['bridges'],'vehicle':vehicle,'process_minutes':VEHICLE_MIN[vehicle],'ewt_minutes':ewt}

@app.post('/api/tokens')
def create_token(x: TokenIn):
    if x.mandi not in MANDIS: raise HTTPException(400,'Invalid mandi')
    if x.vehicle not in VEHICLE_MIN: raise HTTPException(400,'Invalid vehicle')
    prefix='AB-2026-'
    c=db()
    for _ in range(10):
        tid=prefix + secrets.token_hex(2).upper()
        if not c.execute('SELECT 1 FROM tokens WHERE id=?',(tid,)).fetchone(): break
    now=datetime.now(timezone.utc).isoformat()
    c.execute('INSERT INTO tokens VALUES(?,?,?,?,?,?,?,?,?,?,?)',(tid,x.mandi,x.crop.split('/')[0].strip(),x.quantity,x.vehicle,x.vehicle_no,x.slot,1,0,now,now))
    c.execute('INSERT INTO notifications(kind,message,created_at) VALUES(?,?,?)',('Token',f'{tid} booked for {x.mandi}, {x.slot}',now))
    c.commit(); c.close()
    return token(tid)

def token(tid):
    c=db(); r=c.execute('SELECT * FROM tokens WHERE id=?',(tid,)).fetchone(); c.close()
    if not r: raise HTTPException(404,'Token not found')
    q=queue(r['mandi'],r['vehicle'])
    return {**dict(r),'ewt_minutes':q['ewt_minutes'],'bridges':q['bridges'],'msp':MSP.get(r['crop'],0)}

@app.get('/api/tokens/{tid}')
def get_token(tid): return token(tid)

@app.post('/api/tokens/advance')
def advance_token(tid: str):
    c=db(); r=c.execute('SELECT * FROM tokens WHERE id=?',(tid,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'Token not found')
    stage=min(6,r['stage']+1); now=datetime.now(timezone.utc).isoformat()
    c.execute('UPDATE tokens SET stage=?,updated_at=? WHERE id=?',(stage,now,tid))
    labels={1:'स्लॉट आरक्षित',2:'मंडी आगमन',3:'सकल तौल',4:'गुणवत्ता परख',5:'उतराई शेड',6:'अंतिम तौल व जे-फॉर्म'}
    c.execute('INSERT INTO notifications(kind,message,created_at) VALUES(?,?,?)',('Stage Update',f'{tid}: {labels[stage]}',now)); c.commit(); c.close(); return token(tid)

@app.post('/api/tokens/checkin')
def checkin(x: CheckinIn):
    c=db(); r=c.execute('SELECT * FROM tokens WHERE id=?',(x.token_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'Token not found')
    now=datetime.now(timezone.utc).isoformat(); c.execute('UPDATE tokens SET checked_in=1,stage=2,updated_at=? WHERE id=?',(now,x.token_id)); c.execute('INSERT INTO notifications(kind,message,created_at) VALUES(?,?,?)',('Gate Check-in',f'{x.token_id} checked in at {r["mandi"]}',now)); c.commit(); c.close(); return token(x.token_id)

@app.post('/api/tokens/reschedule')
def reschedule(x: RescheduleIn):
    c=db(); r=c.execute('SELECT 1 FROM tokens WHERE id=?',(x.token_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'Token not found')
    now=datetime.now(timezone.utc).isoformat(); c.execute('UPDATE tokens SET slot=?,updated_at=? WHERE id=?',(x.slot,now,x.token_id)); c.execute('INSERT INTO notifications(kind,message,created_at) VALUES(?,?,?)',('Reschedule',f'{x.token_id} moved to {x.slot} (penalty-free)',now)); c.commit(); c.close(); return token(x.token_id)

@app.post('/api/offline/sync')
def offline_sync(x: OfflineIn):
    c=db(); now=datetime.now(timezone.utc).isoformat(); c.execute('INSERT OR REPLACE INTO offline_tokens(id,payload,synced,created_at) VALUES(?,?,1,?)',(x.token_id,json.dumps(x.payload),now)); c.execute('INSERT INTO notifications(kind,message,created_at) VALUES(?,?,?)',('Offline Sync',f'{x.token_id} synchronized after reconnect',now)); c.commit(); c.close(); return {'ok':True,'token_id':x.token_id,'synced':True}

@app.post('/api/quality')
def quality(x: QualityIn):
    c=db(); now=datetime.now(timezone.utc).isoformat(); c.execute('INSERT INTO quality(token_id,moisture,foreign_matter,broken_grains,grade,created_at) VALUES(?,?,?,?,?,?)',(x.token_id,x.moisture,x.foreign_matter,x.broken_grains,x.grade,now)); c.commit(); c.close(); return x.model_dump()

@app.post('/api/officer/call-next')
def call_next():
    c=db(); r=c.execute('SELECT * FROM tokens WHERE stage<6 ORDER BY created_at LIMIT 1').fetchone(); now=datetime.now(timezone.utc).isoformat()
    if not r: c.close(); return {'ok':True,'message':'No waiting token'}
    c.execute('UPDATE tokens SET stage=2,updated_at=? WHERE id=?',(now,r['id'])); c.execute('INSERT INTO notifications(kind,message,created_at) VALUES(?,?,?)',('Officer Call',f'Next farmer called: {r["id"]}',now)); c.commit(); c.close(); return {'ok':True,'token_id':r['id'],'message':f'Next farmer called: {r["id"]}','sms_triggered':True}

@app.post('/api/jforms')
def jform(x: JFormIn):
    if x.tare_kg > x.gross_kg: raise HTTPException(400,'Tare cannot exceed gross')
    net=x.gross_kg-x.tare_kg; payout=round((net/100)*MSP.get(x.crop.split('/')[0].strip(),0),2); utr='PFMSAB'+datetime.now().strftime('%Y%m%d')+secrets.token_hex(3).upper(); now=datetime.now(timezone.utc).isoformat()
    c=db(); c.execute('INSERT INTO jforms(token_id,crop,gross_kg,tare_kg,net_kg,payout,utr,created_at) VALUES(?,?,?,?,?,?,?,?)',(x.token_id,x.crop, x.gross_kg,x.tare_kg,net,payout,utr,now)); c.commit(); c.close(); return {'net_kg':net,'payout':payout,'utr':utr,'form':'J'}

@app.get('/api/notifications')
def notifications():
    c=db(); rows=c.execute('SELECT * FROM notifications ORDER BY id DESC LIMIT 20').fetchall(); c.close(); return [dict(r) for r in rows]

# ---------------------------------------------------------------------------
# WhatsApp farmer slot-booking system (SIH26032 "Apni Baari").
#
# This EXTENDS the app above -- it does not touch or replace any of the
# tokens/mandi/MSP/quality/J-form endpoints already defined. It adds its own
# tables to the same apni_baari.db (see backend/db.py) and its own routes
# under /api/farmers, /api/auth, /api/centres, /api/bookings, /api/officer,
# plus the real WhatsApp Cloud API webhook at /webhook.
from backend.webhook_routes import router as whatsapp_webhook_router
from backend.api_routes import router as whatsapp_api_router
from backend.seed import seed as seed_procurement_data

app.include_router(whatsapp_webhook_router)
app.include_router(whatsapp_api_router)

# Local WhatsApp test harness (see backend/simulator_routes.py). Calls the
# exact same conversation/booking/OTP code the real webhook uses, but lets
# you demo/test the bot in a browser without live Meta credentials. Never
# mounted when APP_ENV=production.
if os.environ.get("APP_ENV", "development") != "production":
    from backend.simulator_routes import router as whatsapp_sim_router
    app.include_router(whatsapp_sim_router)

# Seed procurement centres/slots from the existing MANDIS/MSP data on
# startup. Safe to re-run: it only inserts rows that don't already exist.
seed_procurement_data()

app.mount('/', StaticFiles(directory=BASE, html=True), name='static')
