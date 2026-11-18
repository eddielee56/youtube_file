#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gmail notifier for existing AutoRender V3.8. Windows user-scoped DPAPI secret."""
import argparse
import datetime as dt
from email.message import EmailMessage
import json
import os
from pathlib import Path
import re
import smtplib
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'gmail_email.json'
SECRET=ROOT/'gmail_app_password.dpapi'
SENT=ROOT/'state'/'gmail_sent_events.json'
REPORT=ROOT/'output'/'gmail_last_delivery.json'
TZ=dt.timezone(dt.timedelta(hours=8))

def now(): return dt.datetime.now(TZ).isoformat()
def load(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False,suffix='.tmp') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2)
        f.write('\n')
        temp=Path(f.name)
    os.replace(temp,path)
def settings():
    if not DATA.exists() or not SECRET.exists():
        raise ValueError('Gmail setup not complete. Run setup_gmail.ps1 first.')
    d=load(DATA)
    if not d.get('address') or not re.fullmatch(r'[^\s@]+@gmail\.com|[^\s@]+@googlemail\.com',d['address'],re.I):
        raise ValueError('Gmail address invalid in gmail_email.json')
    return d

def password():
    if os.name!='nt': raise RuntimeError('DPAPI credential unlock works on Windows only.')
    cmd=['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(ROOT/'unlock_gmail_secret.ps1')]
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=15)
    if p.returncode: raise RuntimeError('Cannot unlock Gmail credential under current Windows account.')
    pw=p.stdout.strip()
    if len(pw)!=16 or not re.fullmatch('[A-Za-z0-9]{16}',pw):
        raise ValueError('Gmail app password is not 16 letters/digits.')
    return pw

def message(address,leads,is_test=False):
    msg=EmailMessage()
    msg['From']=address;msg['To']=address
    if is_test:
        msg['Subject']='[AutoRender] Gmail SMTP test - successful connection check'
        msg.set_content('AutoRender Gmail SMTP test. This is a test email, not an active promotion alert.\n')
        return msg
    msg['Subject']=f'[待官方查證] AutoRender 發現 {len(leads)} 項高優先級優惠線索'
    lines=['以下是公開新聞線索，尚未核對銀行或航空公司官方條款。','不得將本信視為有效優惠，亦不應據此轉點或發布影片。','']
    for item in leads:
        src=item.get('sources') or []
        title=next((s.get('title','') for s in src if s.get('title')),'（無標題）')
        url=next((s.get('url','') for s in src if s.get('url')),'')
        lines.extend([f'• {title}',f'  評分：{item.get("score","?")}　狀態：UNVERIFIED',f'  {url}',''])
    lines.append('影片發布需人工查核與核准。')
    msg.set_content('\n'.join(lines))
    return msg

def send(addr,msg,pw):
    with smtplib.SMTP_SSL('smtp.gmail.com',465,timeout=25) as server:
        server.login(addr,pw)
        server.send_message(msg)

def test():
    s=settings()
    send(s['address'],message(s['address'],[],True),password())
    save(REPORT,{'timestamp':now(),'action':'test','status':'SENT','address':s['address']})
    print('TEST SENT to own Gmail:',s['address'])

def notify():
    s=settings()
    if not s.get('enabled'):
        print('EMAIL DISABLED: setup and test before enable.')
        return
    daily=ROOT/'output'/'last_daily_run.json'
    leadsfile=ROOT/'output'/'latest_review_leads.json'
    if not daily.exists() or not leadsfile.exists(): raise RuntimeError('Missing daily report. Run daily first.')
    daily_report=load(daily)
    if daily_report.get('mode')!='LIVE_RSS':
        print('SKIP fixture/test daily run; no mail.')
        return
    # Avoid sending stale reports older than 1 hour
    t=dt.datetime.fromisoformat(daily_report['timestamp'])
    if (dt.datetime.now(TZ)-t.astimezone(TZ)).total_seconds()>3600:
        print('SKIP stale daily report (>1 hour).')
        return
    leads=load(leadsfile).get('events',[])
    mailed=set(load(SENT).get('event_keys',[])) if SENT.exists() else set()
    threshold=int(s.get('min_score',75))
    pending=[e for e in leads if e.get('status')=='NEWS_LEAD_UNVERIFIED'
             and not e.get('official_verified') and not e.get('publication_approved')
             and e.get('event_key') and e['event_key'] not in mailed
             and int(e.get('score',0))>=threshold]
    pending.sort(key=lambda e:-int(e.get('score',0)))
    if not pending:
        print('NO NEW HIGH PRIORITY LEADS.')
        save(REPORT,{'timestamp':now(),'action':'notify','status':'NO_NEW_LEADS','threshold':threshold})
        return
    # Gmail notification not guaranteed to arrive immediately: runs when daily scheduler executes.
    batch=pending[:8]
    send(s['address'],message(s['address'],batch),password())
    mailed.update(e['event_key'] for e in batch)
    save(SENT,{'event_keys':sorted(mailed),'updated_at':now()})
    save(REPORT,{'timestamp':now(),'action':'notify','status':'SENT','count':len(batch),'event_keys':[e['event_key'] for e in batch]})
    print('SENT',len(batch),'UNVERIFIED lead(s) to own Gmail.')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['test','notify','status'])
    a=p.parse_args()
    try:
        if a.action=='test': test()
        elif a.action=='notify':notify()
        else:
            print('Gmail config exists:',DATA.exists(),'DPAPI secret exists:',SECRET.exists())
            if DATA.exists():
                s=load(DATA);print('enabled:',s.get('enabled',False),'address:',s.get('address'),'min_score:',s.get('min_score'))
        return 0
    except (OSError,ValueError,RuntimeError,smtplib.SMTPException,subprocess.TimeoutExpired) as e:
        save(REPORT,{'timestamp':now(),'action':a.action,'status':'FAILED','error_type':type(e).__name__})
        print('Gmail operation failed:',type(e).__name__,str(e) if not isinstance(e,smtplib.SMTPException) else 'SMTP error',file=sys.stderr)
        return 1
if __name__=='__main__':sys.exit(main())
