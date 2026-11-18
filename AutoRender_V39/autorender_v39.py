# -*- coding: utf-8 -*-
"""AutoRender V3.9: reviewed event -> draft/storyboard -> optionally V2.1 internal preview.
Does NOT verify live terms, fetch websites, send email or upload videos.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, pathlib, re, subprocess, sys
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).resolve().parent
PARENT = ROOT.parent
LIBRARY = ROOT / 'approved_for_preview'
OUT = ROOT / 'output'
RENDERER = PARENT / 'AutoRender_V21' / 'autorender_v21_preview.py'
V38_WEEKLY = PARENT / 'AutoRender_V38' / 'output' / 'weekly_topic_review.json'
SUPPORTED = {'credit_card', 'transfer_bonus', 'award_flight', 'hotel_to_airline'}
FIELD_TEXT = ('title','hook','program','headline','benefit','eligibility','deadline','caveat','conclusion')
TODAY = lambda: dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()

class Invalid(Exception): pass

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def check_url(url):
    try:
        p = urlsplit(url)
        return p.scheme == 'https' and bool(p.hostname) and not p.username and not p.password and p.port in (None, 443) and p.hostname not in ('localhost','127.0.0.1')
    except ValueError:
        return False

def validate(item):
    required = ('event_key','type','slug','source_url','checked_at','valid_until','source_verified',
                'approved_for_preview','publication_approved','reviewer_confirmation','evidence','title',
                'hook','program','headline','benefit','eligibility','deadline','caveat','conclusion')
    missing = [k for k in required if k not in item]
    if missing: raise Invalid('Required fields missing: ' + ','.join(missing))
    if item['type'] not in SUPPORTED: raise Invalid('Unsupported offer type: '+str(item['type']))
    if not isinstance(item['event_key'],str) or not item['event_key'].strip(): raise Invalid('event_key missing')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{3,55}', str(item['slug'])): raise Invalid('Invalid slug')
    if not check_url(item['source_url']): raise Invalid('Requires official HTTPS URL')
    for key in FIELD_TEXT:
        if not isinstance(item[key],str) or not item[key].strip():raise Invalid('Text missing: '+key)
        if len(item[key])>180:raise Invalid('Text too long for readable card: '+key)
    try:
        chk=dt.date.fromisoformat(item['checked_at']); end=dt.date.fromisoformat(item['valid_until'])
    except (ValueError,TypeError):raise Invalid('Invalid dates')
    now=TODAY()
    if end<now: raise Invalid('Offer expired')
    if chk>now or (now-chk).days>2:raise Invalid('Official evidence review older than 2 days')
    if item['source_verified'] is not True or item['approved_for_preview'] is not True:
        raise Invalid('Requires explicit human review for preview: source_verified and approved_for_preview = true')
    if item['publication_approved'] is not False:raise Invalid('V3.9 accepts preview-only records; publication_approved must be false')
    if item['reviewer_confirmation'] != 'I_CHECKED_OFFICIAL_TERMS':raise Invalid('Missing human confirmation token')
    e=item['evidence']
    if not isinstance(e,list) or len(e)<3: raise Invalid('At least three manually checked source excerpts required')
    expected={'bonus_or_value','dates','eligibility'}
    fields=set()
    for x in e:
        if not isinstance(x,dict) or x.get('field') not in expected or x.get('official_url')!=item['source_url'] or not str(x.get('excerpt','')).strip():
            raise Invalid('Evidence must include excerpt on identical official URL: bonus_or_value, dates, eligibility')
        fields.add(x['field'])
    if fields != expected: raise Invalid('Evidence categories incomplete')
    return item

def make_draft(item):
    keys=('slug','type','title','hook','program','headline','benefit','eligibility','deadline','caveat',
          'conclusion','source_url','checked_at','valid_until')
    draft={k:item[k] for k in keys}
    draft.update(source_verified=False, approved_for_publication=False,
                 production_status='INTERNAL_PREVIEW_NOT_FOR_PUBLICATION',
                 event_key=item['event_key'])
    return draft

def latest_weekly():
    if not V38_WEEKLY.exists():return None
    x=read(V38_WEEKLY)
    return {'event_key':x.get('selected_event_key'),'headline':x.get('headline'),'status':x.get('status')}

def prepare(path, weekly_match=False):
    item=validate(read(path))
    weekly=latest_weekly()
    if weekly_match and (not weekly or weekly.get('event_key')!=item['event_key']):
        raise Invalid('Approved event does not match V3.8 weekly selection')
    out=OUT/item['slug']
    draft=make_draft(item)
    write(out/'preview_offer.json',draft)
    script=[draft['hook'],
            '這次優惠的重點是：'+draft['headline']+'。'+draft['benefit'],
            '適用條件要注意：'+draft['eligibility'],
            '活動期限：'+draft['deadline']+'。',
            '還要注意：'+draft['caveat'],draft['conclusion']]
    (out/'narration_draft.txt').write_text('\n'.join(script),encoding='utf-8-sig')
    manifest={'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
              'event_key':item['event_key'],'official_url':item['source_url'],
              'reviewed_at':item['checked_at'],'human_preview_approval_recorded':True,
              'official_claims_verified_by_program':False,
              'publication_approved':False, 'auto_upload':False,
              'reviewer_checklist':['Re-read the actual official page before recording',
                                    'Listen to narration and check subtitles and scene timing',
                                    'Verify offer is still live before publishing',
                                    'Approve YouTube publishing separately'],
              'draft_sha256':hashlib.sha256(json.dumps(draft,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
              'preview_input':str(out/'preview_offer.json')}
    write(out/'review_manifest.json',manifest)
    print('PREPARED:',out/'preview_offer.json')
    print('NARRATION:',out/'narration_draft.txt')
    print('PREVIEW ONLY; NOT APPROVED FOR PUBLISHING')
    return out/'preview_offer.json'

def render(input_path, weekly_match=False):
    preview=prepare(input_path,weekly_match)
    if not RENDERER.is_file():raise Invalid('V2.1 renderer not found: '+str(RENDERER))
    print('Launching Azure HsiaoChen preview: you will be prompted for key on your own Windows PC.',flush=True)
    subprocess.run([sys.executable,str(RENDERER),'demo-voice','--input',str(preview)],check=True)
    print('Preview completed; YouTube upload remains disabled.')

def candidate_status():
    weekly=latest_weekly()
    items=[]
    for file in sorted(LIBRARY.glob('*.json')):
        try:
            data=validate(read(file));state='ELIGIBLE_FOR_INTERNAL_PREVIEW'
        except (Invalid,ValueError,KeyError) as exc:
            data=read(file);state='BLOCKED: '+str(exc)
        items.append({'filename':file.name,'event_key':data.get('event_key'), 'status':state})
    write(OUT/'review_queue.json',{'weekly':weekly,'items':items,'publication_approved':False})
    print('WEEKLY TOPIC:',weekly)
    print('LIBRARY:',[(x['filename'],x['status']) for x in items])
    print('REPORT:',OUT/'review_queue.json')

def selftest():
    today=TODAY()
    base={'event_key':'test|sample','type':'transfer_bonus','slug':'test_sample','source_url':'https://example.com/terms',
          'checked_at':today.isoformat(),'valid_until':(today+dt.timedelta(days=15)).isoformat(),
          'source_verified':True,'approved_for_preview':True,'publication_approved':False,
          'reviewer_confirmation':'I_CHECKED_OFFICIAL_TERMS',
          'evidence':[{'field':k,'official_url':'https://example.com/terms','excerpt':'SAMPLE ONLY'} for k in ('bonus_or_value','dates','eligibility')]}
    base.update({k:'示範文字' for k in FIELD_TEXT})
    validate(base)
    for field, bad in [('source_verified',False),('approved_for_preview',False),('publication_approved',True),
                       ('valid_until',(today-dt.timedelta(days=1)).isoformat()),('source_url','http://example.com')]:
        tmp=dict(base);tmp[field]=bad
        try:validate(tmp)
        except Invalid:pass
        else:raise AssertionError('Safety gate failed: '+field)
    assert make_draft(base)['approved_for_publication'] is False
    print('SELFTEST PASS: 6 checks; no Azure, network, email, or upload')

def main():
    ap=argparse.ArgumentParser(description='V3.9 reviewed offers to internal Shorts preview')
    sp=ap.add_subparsers(dest='command',required=True)
    for name in ('prepare','render'):
        p=sp.add_parser(name);p.add_argument('--input',type=pathlib.Path,required=True)
        p.add_argument('--match-weekly',action='store_true',help='Require selected event key to match V3.8 weekly report')
    sp.add_parser('status');sp.add_parser('selftest')
    args=ap.parse_args()
    try:
        if args.command=='selftest':selftest()
        elif args.command=='status':candidate_status()
        elif args.command=='prepare':prepare(args.input.resolve(),args.match_weekly)
        elif args.command=='render':render(args.input.resolve(),args.match_weekly)
        return 0
    except (Invalid,OSError,ValueError,KeyError,subprocess.CalledProcessError) as exc:
        print('V3.9 STOP:',str(exc),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
