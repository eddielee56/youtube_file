# -*- coding: utf-8 -*-
"""AutoRender V4.3: weekly approved-event internal-preview scheduler.
No browser verification, no publication or YouTube upload. A reviewed event must
match V3.8's selected event key and pass V3.9 validation at execution time.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parent
V39=PROJECT/'AutoRender_V39'/'autorender_v39.py'
V42=PROJECT/'AutoRender_V42'/'autorender_v42.py'
WEEKLY=PROJECT/'AutoRender_V38'/'output'/'weekly_topic_review.json'
APPROVALS=PROJECT/'AutoRender_V39'/'approved_for_preview'
STATE=ROOT/'state'/'v43.sqlite3'
OUTPUT=ROOT/'output'
SECRET_SCRIPT=ROOT/'unlock_secret.ps1'
MODEL='gemini-3.5-flash'

class V43Error(Exception):pass

def utcnow():return dt.datetime.now(dt.timezone.utc)
def iso_now():return utcnow().isoformat()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                                     prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
        temporary=Path(stream.name)
        json.dump(obj,stream,ensure_ascii=False,indent=2)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
def load_mod(path,name):
    if not path.is_file():raise V43Error('Missing module: '+str(path))
    spec=importlib.util.spec_from_file_location(name,str(path))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod

def db_open():
    STATE.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(str(STATE),timeout=15,isolation_level=None)
    conn.execute('PRAGMA busy_timeout=15000')
    conn.execute('CREATE TABLE IF NOT EXISTS runs (event_key TEXT PRIMARY KEY, status TEXT NOT NULL, attempts INTEGER NOT NULL, last_error TEXT, rendered_at TEXT, updated_at TEXT NOT NULL)')
    # Keep existing installations and their attempt counts intact.
    conn.execute('CREATE TABLE IF NOT EXISTS previews (event_key TEXT PRIMARY KEY, mp4 TEXT NOT NULL, mp4_sha256 TEXT NOT NULL, receipt TEXT NOT NULL, review_status TEXT NOT NULL, reviewed_at TEXT)')
    return conn

def status_for(conn,key):
    return conn.execute('SELECT status,attempts FROM runs WHERE event_key=?',(key,)).fetchone()

def claim(conn,key):
    conn.execute('BEGIN IMMEDIATE')
    try:
        found=status_for(conn,key)
        if found and found[0] in ('SUCCEEDED','RUNNING'):
            conn.execute('COMMIT');return False,found[0]
        if found and found[1]>=3:
            conn.execute('COMMIT');return False,'RETRIES_EXHAUSTED'
        conn.execute('INSERT INTO runs(event_key,status,attempts,updated_at) VALUES(?,?,?,?) ON CONFLICT(event_key) DO UPDATE SET status=excluded.status,attempts=runs.attempts+1,last_error=NULL,updated_at=excluded.updated_at',(key,'RUNNING',1,iso_now()))
        conn.execute('COMMIT');return True,'CLAIMED'
    except Exception:
        conn.execute('ROLLBACK');raise

def complete(conn,key,ok,error=None):
    conn.execute('UPDATE runs SET status=?,last_error=?,rendered_at=?,updated_at=? WHERE event_key=?',('SUCCEEDED' if ok else 'FAILED',error,None if not ok else iso_now(),iso_now(),key))


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def validate_movie(path):
    movie=Path(path).resolve()
    if not movie.is_file() or movie.stat().st_size<1024:
        raise V43Error('MP4 output missing or too small')
    probe=subprocess.run(['ffprobe','-v','error','-show_entries',
                          'stream=codec_type:format=duration','-of','json',str(movie)],
                         capture_output=True,timeout=30,check=False)
    if probe.returncode!=0:
        raise V43Error('MP4 could not be read by ffprobe')
    metadata=json.loads(probe.stdout)
    tracks={track.get('codec_type') for track in metadata.get('streams',[])}
    if not {'video','audio'}<=tracks or float(metadata.get('format',{}).get('duration',0))<=0:
        raise V43Error('MP4 requires video, audio and positive duration')
    return movie,file_sha(movie)


def save_preview(conn,key,movie,digest,receipt,reviewed=False):
    if reviewed:raise V43Error('Local review decisions are disabled; use the Muse review page')
    conn.execute('INSERT INTO previews VALUES(?,?,?,?,?,?) ON CONFLICT(event_key) DO UPDATE SET '
                 'mp4=excluded.mp4,mp4_sha256=excluded.mp4_sha256,receipt=excluded.receipt, '
                 'review_status=excluded.review_status,reviewed_at=NULL',
                 (key,str(movie),digest,str(receipt),'PENDING',None))


def preview_fields(conn,key):
    row=conn.execute('SELECT mp4,mp4_sha256,receipt FROM previews WHERE event_key=?',(key,)).fetchone()
    if not row:return {}
    fields=dict(zip(('mp4','mp4_sha256','receipt'),row))
    import autorender_review
    record=autorender_review.read_review(key)
    matches=record is not None and autorender_review.record_matches_movie(record,fields['mp4_sha256'])
    fields.update(review_status=record['status'] if matches else 'pending',
                  reviewed_at=record['decision']['at'] if matches else None,
                  review_source='Muse',publication_approved=record['publication_approved'] if matches else False,
                  review_file=str(autorender_review.review_path(key)))
    return fields


def adopt_preview(receipt_path,reviewed=False,replace=False):
    """Register an existing V4.2 render. Muse owns the review decision."""
    if reviewed:raise V43Error('Local review decisions are disabled; use the Muse review page')
    receipt_path=Path(receipt_path).resolve()
    receipt=read(receipt_path)
    key=receipt.get('event_key')
    if not isinstance(key,str) or not key.strip():raise V43Error('Receipt event key missing')
    if receipt.get('preview_only') is not True or receipt.get('publication_approved') is not False or receipt.get('auto_upload') is not False:
        raise V43Error('Requires an internal-preview receipt')
    mod=load_mod(V42,'renderer_v42_adopt')
    snapshot=read(receipt_path.parent/'source_fact_snapshot.json')
    if snapshot.get('event_key')!=key or mod.canonical_sha(snapshot)!=receipt.get('snapshot_sha256'):
        raise V43Error('Receipt fact snapshot mismatch')
    approval,reason=approved_for_key(key)
    if reason:raise V43Error(reason)
    if mod.canonical_sha(read(approval))!=receipt['snapshot_sha256']:
        raise V43Error('Current approval differs from rendered facts')
    facts,scenes,folder=mod.load_checked_draft(approval)
    script='\n'.join(scene['narration'] for scene in scenes)
    if folder.resolve()!=receipt_path.parent or hashlib.sha256(script.encode('utf-8')).hexdigest()!=receipt.get('narration_sha256'):
        raise V43Error('Receipt narration mismatch')
    movie,digest=validate_movie(receipt['mp4_path'])
    conn=db_open()
    try:
        conn.execute('BEGIN IMMEDIATE')
        existing=status_for(conn,key)
        if existing and existing[0]=='RUNNING':raise V43Error('Event is currently running')
        previous=preview_fields(conn,key)
        changed=bool(previous and previous['mp4_sha256']!=digest)
        if changed and not (replace and previous['review_status']=='returned'):
            raise V43Error('A different preview is registered; reject the old version and use --replace')
        conn.execute('INSERT INTO runs(event_key,status,attempts,rendered_at,updated_at) VALUES(?,?,?,?,?) '
                     'ON CONFLICT(event_key) DO UPDATE SET status=excluded.status,last_error=NULL, '
                     'rendered_at=excluded.rendered_at,updated_at=excluded.updated_at',
                     (key,'SUCCEEDED',0,receipt['created_at'],iso_now()))
        save_preview(conn,key,movie,digest,receipt_path)
        conn.execute('COMMIT')
        return report('PREVIEW_READY',event_key=key,**preview_fields(conn,key))
    except Exception:
        if conn.in_transaction:conn.execute('ROLLBACK')
        raise
    finally:conn.close()

def selected_event():
    if not WEEKLY.is_file():return None,'WEEKLY_REPORT_MISSING'
    obj=read(WEEKLY)
    if obj.get('status')!='EDITORIAL_REVIEW_ONLY':return None,'WEEKLY_REPORT_INVALID_STATUS'
    k=obj.get('selected_event_key')
    if not isinstance(k,str) or not k.strip():return None,'NO_WEEKLY_TOPIC'
    stamp=obj.get('generated_at')
    if not stamp:return None,'WEEKLY_TIMESTAMP_MISSING'
    try:
        when=dt.datetime.fromisoformat(stamp.replace('Z','+00:00'))
        if when.tzinfo is None:raise ValueError('naive time')
        elapsed=(utcnow()-when.astimezone(dt.timezone.utc)).total_seconds()
        if elapsed< -300 or elapsed>8*86400:return None,'STALE_WEEKLY_REPORT'
    except (TypeError,ValueError):return None,'INVALID_WEEKLY_TIMESTAMP'
    return k,None

def approved_for_key(key):
    if not APPROVALS.is_dir():return None,'APPROVAL_FOLDER_MISSING'
    matches=[]
    validator=load_mod(V39,'reviewer_v43')
    for p in sorted(APPROVALS.glob('*.json')):
        try:
            obj=read(p)
        except (ValueError,OSError):continue
        if obj.get('event_key')!=key:continue
        try:validator.validate(obj)
        except Exception:continue
        matches.append(p)
    if not matches:return None,'NO_CURRENT_HUMAN_APPROVAL'
    if len(matches)>1:return None,'AMBIGUOUS_APPROVALS'
    return matches[0],None

def report(stage,**kwargs):
    data={'checked_at':iso_now(),'stage':stage,'publication_approved':False,'youtube_upload':False,**kwargs}
    write_json(OUTPUT/'last_weekly_render.json',data)
    print('V4.3:',stage)
    print('REPORT:',OUTPUT/'last_weekly_render.json')
    return data

def secret(name):
    # PowerShell decrypts DPAPI under same signed-in Windows account; do not log values.
    if os.name!='nt':raise V43Error('DPAPI requires Windows')
    if not SECRET_SCRIPT.is_file():raise V43Error('Secret helper missing')
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(SECRET_SCRIPT),'-Name',name],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,check=False)
    if p.returncode!=0:raise V43Error('Cannot unlock '+name+' for current Windows user; sign in and check DPAPI setup')
    value=p.stdout.decode('utf-8-sig').strip()
    if not value:raise V43Error('Empty credential: '+name)
    return value

def run_weekly(dry_run=False):
    key,reason=selected_event()
    if reason:return report('WAITING_REVIEW',reason=reason)
    conn=db_open()
    try:
        existing=status_for(conn,key)
        if existing and existing[0]=='SUCCEEDED':
            fields=preview_fields(conn,key)
            if fields:
                try:
                    movie,digest=validate_movie(fields['mp4'])
                    if digest!=fields['mp4_sha256']:raise V43Error('MP4 content changed')
                except (V43Error,OSError,ValueError,subprocess.SubprocessError):
                    return report('OUTPUT_INVALID',event_key=key,reason='Registered MP4 missing, changed or unreadable')
            return report('ALREADY_RENDERED',event_key=key,**fields)
        path,reason=approved_for_key(key)
        if reason:return report('WAITING_REVIEW',event_key=key,reason=reason)
        if existing and existing[0]=='RUNNING':return report('SKIPPED',event_key=key,reason='RUNNING')
        if existing and existing[1]>=3:return report('SKIPPED',event_key=key,reason='RETRIES_EXHAUSTED')
        if dry_run:return report('READY_TO_RENDER',event_key=key,reviewed_filename=path.name)
        claimed,why=claim(conn,key)
        if not claimed:return report('SKIPPED',event_key=key,reason=why)
        try:
            # Keep all real API keys in process memory only; never write credentials to artifacts.
            gem=secret('gemini')
            az=secret('azure')
            mod=load_mod(V42,'renderer_v42_weekly')
            mod.draft(path,model=MODEL,mode='gemini',key=gem)
            previous=os.environ.get('AZURE_SPEECH_KEY')
            try:
                os.environ['AZURE_SPEECH_KEY']=az
                movie=mod.render(path)
            finally:
                if previous is None:os.environ.pop('AZURE_SPEECH_KEY',None)
                else:os.environ['AZURE_SPEECH_KEY']=previous
            movie,digest=validate_movie(movie)
            receipt=mod.OUTPUT/read(path)['slug']/'render_receipt.json'
            conn.execute('BEGIN IMMEDIATE')
            save_preview(conn,key,movie,digest,receipt)
            complete(conn,key,True)
            conn.execute('COMMIT')
        except Exception as exc:
            if conn.in_transaction:conn.execute('ROLLBACK')
            # Keep errors generic: external services sometimes include sensitive request data.
            complete(conn,key,False,type(exc).__name__)
            return report('RENDER_FAILED',event_key=key,reason='See local renderer diagnostic; no publication performed',exception_type=type(exc).__name__)
        return report('PREVIEW_READY',event_key=key,**preview_fields(conn,key))
    finally:conn.close()

def reset(key):
    conn=db_open()
    try:
        returned=preview_fields(conn,key).get('review_status')=='returned'
        changed=conn.execute("UPDATE runs SET status='FAILED',attempts=0,last_error='MANUAL_RETRY',updated_at=? "
                             "WHERE event_key=? AND (status='FAILED' OR (status='SUCCEEDED' AND ?))",
                             (iso_now(),key,returned)).rowcount
        print('RESET:',changed,'entry; retry only after reviewing error and approval status')
    finally:conn.close()

def status():
    print('V4.3 companion scheduler (separate from existing V3.8 tasks)')
    for name,p in [('V3.8 weekly',WEEKLY),('V3.9 validation',V39),('V4.2 renderer',V42),('Secret setup',SECRET_SCRIPT)]:print(name,'OK' if p.is_file() else 'MISSING')
    key,reason=selected_event();print('Weekly selection:',key if key else reason)
    if key:
        p,r=approved_for_key(key);print('Human preview approval:',p.name if p else r)
    if STATE.exists():
        c=db_open()
        try:
            for r in c.execute('SELECT event_key,status,attempts FROM runs ORDER BY updated_at DESC LIMIT 5'):print('EVENT:',*r)
            if key:
                for field,value in preview_fields(c,key).items():print(field+':',value)
        finally:c.close()
    print('Never uploads to YouTube; no publication approvals generated')

def selftest():
    import tempfile
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as d:
        global STATE,OUTPUT
        saved=(STATE,OUTPUT);STATE=Path(d)/'test.sqlite3';OUTPUT=Path(d)/'out'
        try:
            c=db_open();ok,why=claim(c,'fiction|1');assert ok
            ok,why=claim(c,'fiction|1');assert not ok and why=='RUNNING'
            complete(c,'fiction|1',False,'TestFailure')
            ok,why=claim(c,'fiction|1');assert ok
            complete(c,'fiction|1',True)
            ok,why=claim(c,'fiction|1');assert not ok and why=='SUCCEEDED'
            c.close()
            with patch(__name__+'.selected_event',return_value=(None,'NO_WEEKLY_TOPIC')):
                r=run_weekly();assert r['stage']=='WAITING_REVIEW'
            with patch(__name__+'.selected_event',return_value=('example|test',None)),patch(__name__+'.approved_for_key',return_value=(Path('approved.json'),None)):
                r=run_weekly(True);assert r['stage']=='READY_TO_RENDER'
            assert read(OUTPUT/'last_weekly_render.json')['youtube_upload'] is False
        finally:STATE,OUTPUT=saved
    print('SELFTEST PASS: 8 isolated checks; no API calls, no mail, no video, no Windows tasks changed')

def main():
    ap=argparse.ArgumentParser(description='Weekly approved-event internal-preview runner')
    sub=ap.add_subparsers(dest='cmd',required=True)
    sub.add_parser('status');sub.add_parser('selftest');sub.add_parser('weekly');sub.add_parser('dry-run')
    rp=sub.add_parser('retry');rp.add_argument('--event-key',required=True)
    adopt=sub.add_parser('adopt-preview',help='Register a completed V4.2 preview')
    adopt.add_argument('--receipt',required=True)
    adopt.add_argument('--reviewed',action='store_true',help='Disabled legacy flag; decisions belong to Muse')
    adopt.add_argument('--replace',action='store_true',help='Register a revised movie after the previous version was rejected')
    sub.add_parser('review-queue',help='List the authoritative reviews in the Git repository')
    sub.add_parser('review',help='Explain the Muse-only review entry point')
    prepare=sub.add_parser('prepare-review',help='Prepare a pending Muse record for a video already in Git')
    prepare.add_argument('--offer',required=True)
    prepare.add_argument('--video',required=True)
    prepare.add_argument('--repo-path',required=True)
    prepare.add_argument('--commit-sha',required=True)
    decision=sub.add_parser('import-muse-review',help='Write a complete Muse review record to the repository')
    decision.add_argument('--file',required=True)
    decision.add_argument('--expected-version',required=True)
    sub.add_parser('validate-reviews',help='Validate the repository review records')
    notification=sub.add_parser('notify',help='Gmail disabled; completion events are handed to Muse')
    notification.add_argument('--dry-run',action='store_true')
    notification.add_argument('--retry-failed',action='store_true',help='Disabled legacy Gmail option')
    args=ap.parse_args()
    try:
        if args.cmd=='status':status()
        elif args.cmd=='selftest':selftest()
        elif args.cmd in ('weekly','dry-run'):
            result=run_weekly(args.cmd=='dry-run')
            if args.cmd=='weekly':
                import autorender_review
                autorender_review.finish(result)
            if result['stage'] in ('RENDER_FAILED','OUTPUT_INVALID'):return 2
        elif args.cmd=='retry':reset(args.event_key)
        elif args.cmd=='adopt-preview':
            result=adopt_preview(args.receipt,args.reviewed,args.replace)
            import autorender_review
            autorender_review.finish(result)
        elif args.cmd=='review':
            print('Local review page disabled. Review decisions are made on the Muse review page.')
        elif args.cmd in ('review-queue','validate-reviews'):
            import autorender_review
            for path in sorted((autorender_review.repository()/'reviews').glob('*.review.json')):
                record=autorender_review.validate(read(path))
                if autorender_review.review_path(record['event_key'])!=path:raise V43Error('Review filename mismatch')
                print('MUSE REVIEW:',record['status'],path)
        elif args.cmd=='prepare-review':
            import autorender_review
            record=autorender_review.build_record(read(args.offer),args.video,args.repo_path,args.commit_sha)
            autorender_review.prepare_review(record)
            print('MUSE REVIEW:',autorender_review.review_path(record['event_key']))
        elif args.cmd=='import-muse-review':
            import autorender_review
            record=autorender_review.import_muse_review(read(args.file),args.expected_version)
            print('MUSE REVIEW SAVED:',record['status'],autorender_review.review_path(record['event_key']))
        elif args.cmd=='notify':
            print('GMAIL_DISABLED: completion and failure notifications belong to Muse conversations.')
        return 0
    except (V43Error,ValueError,KeyError,OSError,sqlite3.Error,subprocess.SubprocessError) as e:
        print('V4.3 ERROR:',str(e),file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
