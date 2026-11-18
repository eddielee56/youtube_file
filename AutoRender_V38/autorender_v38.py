#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AutoRender V3.8: safe, local orchestration for V3.3→V3.4→V3.5.
The monitor discovers *news leads*, not verified promotions. Never publishes.
Python 3.12 standard library only.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import smtplib
from email.message import EmailMessage
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
OUTPUT = ROOT / 'output'
STATE = ROOT / 'state'
TZ = dt.timezone(dt.timedelta(hours=8))

def stamp(): return dt.datetime.now(TZ).isoformat()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',delete=False,dir=path.parent,suffix='.tmp') as f:
        json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n');tmp=Path(f.name)
    os.replace(tmp,path)
def cfg():return read(ROOT/'config.json')
def paths(config):
    return {name:(PROJECT/config['folders'][name]/script) for name,script in [('v33','autorender_v33.py'),('v34','autorender_v34.py'),('v35','autorender_v35.py')]}
def invoke(cmd, *, timeout=180):
    p=subprocess.run(cmd,text=True,capture_output=True,encoding='utf-8',errors='replace',timeout=timeout)
    return {'command':[str(x) for x in cmd],'returncode':p.returncode,'stdout':p.stdout[-2500:],'stderr':p.stderr[-2500:]}
def ensure(config,names):
    missing=[str(paths(config)[k]) for k in names if not paths(config)[k].is_file()]
    if missing:raise RuntimeError('找不到所需檔案：'+', '.join(missing))
def get_events(data):return data.get('needs_official_review',[]) if isinstance(data,dict) else []
def headline(e):return next((x.get('title','') for x in e.get('sources',[]) if x.get('title')),e.get('event_key',''))
def candidates(data):
    return [e for e in get_events(data) if e.get('status')=='NEWS_LEAD_UNVERIFIED' and not e.get('official_verified') and not e.get('publication_approved')]
def key(e):return str(e.get('event_key') or '')
def fresh_new(lead,seen):
    result=[]
    for e in lead:
        if key(e) and key(e) not in seen:result.append(e)
    return result
def notification(config, items, *, dry_run=False):
    """Optional email: news leads ONLY. Never mail if config missing or SMTP not configured."""
    c=config.get('email',{})
    if not items:return 'NO_NEW_HIGH_PRIORITY_LEADS'
    if not c.get('enabled'):return 'NOT_CONFIGURED'
    if dry_run:return 'DRY_RUN'
    server=os.environ.get('AUTORENDER_SMTP_HOST')
    user=os.environ.get('AUTORENDER_SMTP_USER')
    password=os.environ.get('AUTORENDER_SMTP_PASSWORD')
    to=os.environ.get('AUTORENDER_ALERT_TO')
    sender=os.environ.get('AUTORENDER_ALERT_FROM') or user
    if not all((server,user,password,to,sender)):return 'SMTP_ENV_MISSING'
    msg=EmailMessage()
    msg['Subject']='[待官方查核] AutoRender 重大優惠新聞線索'
    msg['From']=sender;msg['To']=to
    body=['以下均為未驗證新聞線索，不代表優惠有效，請勿據此轉點或公開發布：','']
    for e in items[:8]:
        body.append(f"- {headline(e)}（系統分數 {e.get('score',0)}）")
        body.append('  '+next((s.get('url','') for s in e.get('sources',[]) if s.get('url')),''))
    msg.set_content('\n'.join(body))
    try:
        with smtplib.SMTP_SSL(server,int(os.environ.get('AUTORENDER_SMTP_PORT','465')),timeout=20) as smtp:
            smtp.login(user,password);smtp.send_message(msg)
        return 'SENT'
    except (OSError,smtplib.SMTPException) as exc:return 'SEND_FAILED:'+type(exc).__name__
def select(offers):
    # Candidate for *review*, never automatically approved or published.
    return sorted(offers,key=lambda e:(-int(e.get('score',0)),key(e)))[0] if offers else None

def daily(args):
    conf=cfg();ensure(conf,['v33','v34'])
    log=[];cmd=[sys.executable,str(paths(conf)['v33']),'daily']
    if args.fixture:cmd+=['--fixture',str(Path(args.fixture).resolve())]
    res=invoke(cmd,timeout=240);log.append(res)
    if res['returncode']:raise RuntimeError('V3.3 RSS 搜尋失敗：'+res['stderr'][-350:])
    v33_file=paths(conf)['v33'].parent/'output'/'latest_alert_candidates.json'
    if not v33_file.is_file():raise RuntimeError('V3.3 沒有輸出候選 JSON')
    res=invoke([sys.executable,str(paths(conf)['v34']),'triage','--input',str(v33_file)]);log.append(res)
    if res['returncode']:raise RuntimeError('V3.4 篩選失敗：'+res['stderr'][-350:])
    triage=read(paths(conf)['v34'].parent/'output'/'v34_triage.json')
    offers=candidates(triage)
    # Earlier run ID cache; only write alert cache after a successful email or disabled emails.
    seen_path=STATE/'seen_leads.json';seen=set(read(seen_path).get('keys',[])) if seen_path.exists() else set()
    new=fresh_new(offers,seen)
    important=[e for e in new if int(e.get('score',0))>=int(conf.get('alert_score',75))]
    status=notification(conf,important,dry_run=bool(args.fixture or args.no_email))
    if status in ('SENT','NOT_CONFIGURED','NO_NEW_HIGH_PRIORITY_LEADS','DRY_RUN'):
        # DRY_RUN never consumes alert IDs, preserving future notification on a real run.
        if status!='DRY_RUN':write(seen_path,{'keys':sorted(seen|{key(e) for e in new}),'updated_at':stamp()})
    report={'timestamp':stamp(),'mode':'FIXTURE' if args.fixture else 'LIVE_RSS',
            'v33_source':str(v33_file),'total_candidates':triage.get('counts',{}).get('total'),
            'needs_official_review':len(offers),'new_review_leads':len(new),
            'high_priority_new_leads':len(important),'email':status,
            'publication_approved':False,'automatic_video_generation':False,
            'important':'僅新聞線索。未經人工逐條核對官方來源、期限及資格，不得發布或轉點。',
            'steps':log}
    write(OUTPUT/'last_daily_run.json',report)
    write(OUTPUT/'latest_review_leads.json',{'generated_at':stamp(),'events':offers,'official_verified':False,'publication_approved':False})
    print(f"V3.8 每日完成：候選 {report['total_candidates']}；待官方查核 {len(offers)}；新線索 {len(new)}；通知 {status}")
    print('報告：',OUTPUT/'last_daily_run.json')
    return 0

def weekly(args):
    conf=cfg();ensure(conf,['v34'])
    triage_path=paths(conf)['v34'].parent/'output'/'v34_triage.json'
    if not triage_path.is_file():raise RuntimeError('沒有 V3.4 篩選結果。請先執行 daily。')
    triage=read(triage_path);items=candidates(triage);top=select(items)
    brief={'generated_at':stamp(),'status':'EDITORIAL_REVIEW_ONLY','selected_event_key':key(top) if top else None,
           'headline':headline(top) if top else None,'category':top.get('category') if top else None,
           'score':top.get('score') if top else None,'source_articles':top.get('sources',[]) if top else [],
           'required_before_draft':['直接對照官網原始條款','活動起訖與時區','適用會員／地區','優惠數字與上限','人工核准試播'],
           'official_verified':False,'publication_approved':False,'rendered':False,
           'reason':'新聞推薦不能直接等同官方確認；尚不會自動製片或發布。'}
    write(OUTPUT/'weekly_topic_review.json',brief)
    print('每週選題清單已產生（僅待審核，無影片）：',OUTPUT/'weekly_topic_review.json')
    return 0

def prepare(args):
    conf=cfg();ensure(conf,['v34','v35'])
    triage_path=paths(conf)['v34'].parent/'output'/'v34_triage.json'
    if not triage_path.exists():raise RuntimeError('請先執行 daily')
    p=invoke([sys.executable,str(paths(conf)['v35']),'prepare','--input',str(triage_path)]);print(p['stdout'])
    if p['returncode']:raise RuntimeError('建立官方查核清單失敗：'+p['stderr'][-250:])
    print('請人工填入確切官方活動 URL 與查核詞後，再使用 V3.5 inspect。')
    return 0

def status(args):
    conf=cfg();loc=paths(conf)
    print('AutoRender V3.8：')
    for name,p in loc.items():print(name,'OK' if p.is_file() else 'MISSING',p)
    for f in [OUTPUT/'last_daily_run.json',OUTPUT/'weekly_topic_review.json']:
        print(f.name,('EXISTS' if f.exists() else 'NOT YET'))
    print('自動影片發布：永遠停用；正式優惠查核：需要人工審核。')
    return 0

def main():
    p=argparse.ArgumentParser(description='AutoRender V3.8 safe Windows coordinator')
    sub=p.add_subparsers(dest='cmd',required=True)
    daily_parser=sub.add_parser('daily');daily_parser.add_argument('--fixture');daily_parser.add_argument('--no-email',action='store_true')
    sub.add_parser('weekly');sub.add_parser('prepare-review');sub.add_parser('status')
    a=p.parse_args()
    try:return {'daily':daily,'weekly':weekly,'prepare-review':prepare,'status':status}[a.cmd](a)
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.TimeoutExpired) as exc:
        print('V3.8 失敗：'+str(exc),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
