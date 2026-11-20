# -*- coding: utf-8 -*-
"""AutoRender V2: credit-card / transfer-bonus / award-flight vertical video generator.
Commands:
  py -3.12 autorender_v2.py prepare --input offer_demo.json
  py -3.12 autorender_v2.py demo --input offer_demo.json
  py -3.12 autorender_v2.py voice --input offer_verified.json
  py -3.12 autorender_v2.py render --input offer_verified.json
  py -3.12 autorender_v2.py all --input offer_verified.json
No unattended publishing and no implicit claim that offers are current.
"""
from __future__ import annotations
import argparse, datetime as dt, getpass, json, math, os, re, shutil, subprocess, sys, textwrap, wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
W,H,FPS = 540,960,30
WHITE=(245,247,255); MUTED=(161,177,200); BG=(12,20,40); CYAN=(60,209,232)
VALID_TYPES={'credit_card':'信用卡優惠','transfer_bonus':'點數轉點加成','award_flight':'機票哩程兌換','hotel_to_airline':'飯店點數與航空哩程'}
CAPTION_STYLE='Style: Main,Microsoft JhengHei,26,&H00FFFFFF,&H000000FF,&H92000000,&H60000000,1,0,0,0,100,100,0,0,1,3,1,2,38,38,94,1'
CAPTION_TOKEN=re.compile(r'Reward[ \t]+Points|Asia[ \t]+Miles|[A-Za-z0-9]+(?:[\x27’.-][A-Za-z0-9]+)*[%％]?|[ \t]+|.',re.I)

def load_input(p:Path):
    x=json.loads(p.read_text(encoding='utf-8-sig'))
    required=['type','title','hook','program','headline','benefit','eligibility','deadline','caveat','conclusion','source_url','checked_at','valid_until','source_verified','approved_for_publication']
    miss=[k for k in required if k not in x]
    if miss: raise ValueError('JSON 缺少欄位：'+', '.join(miss))
    if x['type'] not in VALID_TYPES: raise ValueError('type 僅能使用 credit_card / transfer_bonus / award_flight / hotel_to_airline')
    for k in required:
        if isinstance(x[k],str) and not x[k].strip(): raise ValueError('欄位不得空白：'+k)
    return x

def parse_date(s): return dt.date.fromisoformat(s)

def check_publishable(x):
    if not x['source_verified'] or not x['approved_for_publication']:
        raise ValueError('正式製作需 source_verified=true 且 approved_for_publication=true；示範資料請使用 demo 指令。')
    if not str(x['source_url']).startswith('https://'):
        raise ValueError('正式製作必須填入 https:// 官方活動或條款原始網址。')
    today=dt.date.today()
    if parse_date(x['valid_until'])<today:
        raise ValueError(f'優惠已到期（{x["valid_until"]}），禁止輸出正式影片。')
    check=parse_date(x['checked_at'])
    if check>today or (today-check).days>2:
        raise ValueError('來源核對日期超過 48 小時或在未來，請重新核對官方條款。')
    # Flags do not prove a claim. Review source yourself; this tool performs no live retrieval.

def scenes(x):
    return [
        {'tag':'01 / 吸引注意','heading':x['hook'],'detail':x['program'],'narration':x['hook']},
        {'tag':'02 / 核心優惠','heading':x['headline'],'detail':x['benefit'],'narration':f'這次的重點是：{x["headline"]}。{x["benefit"]}'},
        {'tag':'03 / 適用對象','heading':'誰可以參加？','detail':x['eligibility'],'narration':f'適用條件要注意：{x["eligibility"]}'},
        {'tag':'04 / 活動期限','heading':x['deadline'],'detail':'活動期限請以官方條款為準','narration':f'活動期限：{x["deadline"]}。'},
        {'tag':'05 / 特別留意','heading':'重要限制','detail':x['caveat'],'narration':f'還要注意：{x["caveat"]}'},
        {'tag':'06 / 最後整理','heading':x['conclusion'],'detail':'資訊以官方最新公告為準','narration':x['conclusion']},
    ]

def outdir(x, demo=False):
    slug=re.sub(r'[^a-zA-Z0-9_-]', '_',x.get('slug','credit_offer'))[:45]
    d=ROOT/'output'/('DEMO_'+slug if demo else slug)
    d.mkdir(parents=True, exist_ok=True)
    return d

def prepare(x,d):
    s=scenes(x); offset=0; script_parts=[]
    for item in s:
        item['text_start']=offset
        script_parts.append(item['narration'])
        offset += len(item['narration'])+1
    narration='\n'.join(script_parts)
    (d/'narration.txt').write_text(narration,encoding='utf-8-sig')
    (d/'storyboard.json').write_text(json.dumps({'schema_version':1,'type':x['type'],'source_url':x['source_url'],'checked_at':x['checked_at'],'scenes':s},ensure_ascii=False,indent=2),encoding='utf-8')
    return s,narration

def font(size, bold=False):
    candidates=[]
    if os.name=='nt':
        win=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
        candidates += [win/('msjhbd.ttc' if bold else 'msjh.ttc'),win/'msyhbd.ttc',win/'msyh.ttc']
    else:
        candidates += [Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'),Path('/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc'),Path('/usr/share/fonts/truetype/arphic/uming.ttc')]
    for p in candidates:
        try:
            if p.is_file():return ImageFont.truetype(str(p),size)
        except OSError:pass
    raise RuntimeError('找不到繁體中文字型，請確認 Windows 已安裝微軟正黑體。')

def lines_fit(draw,text,ft,maxw,maxlines=6):
    lines=[]
    for para in str(text).split('\n'):
        cur=''
        for char in para:
            if draw.textlength(cur+char,font=ft)<=maxw:cur+=char
            else:
                if cur:lines.append(cur)
                cur=char
        if cur:lines.append(cur)
    if len(lines)>maxlines: raise ValueError('資訊卡文字過長，請縮短，避免畫面裁切：'+text[:70])
    return lines

def card_text_layout(draw,heading,detail):
    for heading_size,detail_size in ((39,27),(36,25),(33,23),(30,21)):
        heading_font=font(heading_size,True)
        detail_font=font(detail_size)
        try:
            heading_lines=lines_fit(draw,heading,heading_font,428,5)
            paragraphs=re.sub(r'(?<=[，；。])(?=.)','\n',detail)
            try:detail_lines=lines_fit(draw,paragraphs,detail_font,420,6)
            except ValueError:detail_lines=lines_fit(draw,detail,detail_font,420,6)
        except ValueError:
            continue
        heading_step=round(heading_size*1.55)
        detail_step=round(detail_size*1.65)
        detail_y=264+len(heading_lines)*heading_step+22
        if detail_y+len(detail_lines)*detail_step<=636:
            return heading_font,detail_font,heading_lines,detail_lines,heading_step,detail_step,detail_y
    raise ValueError('資訊卡文字超出可讀範圍，停止輸出，請調整文案')


def card(x,scene,index,d,demo=False):
    im=Image.new('RGB',(W,H),BG); dr=ImageDraw.Draw(im)
    # Dark navy gradient with teal accent, designed for legibility.
    for y in range(H):
        r=y/(H-1); dr.line((0,y,W,y),fill=(int(12+12*r),int(22+13*r),int(46+14*r)))
    dr.rounded_rectangle((30,38,510,95),radius=20,fill=(27,54,78))
    dr.text((49,50),VALID_TYPES[x['type']],font=font(24,True),fill=CYAN)
    dr.text((34,137),scene['tag'],font=font(24),fill=MUTED)
    logos=x.get('brand_logos',[])
    if logos and len(logos)!=2:raise ValueError('合作品牌需要兩個官方標誌檔案')
    for logo_path,left,fill in zip(logos,(288,404),((10,18,34),(255,255,255))):
        dr.rounded_rectangle((left,110,left+100,202),radius=10,fill=fill)
        with Image.open(logo_path) as source:
            logo=source.convert('RGBA')
        logo.thumbnail((84,76),Image.Resampling.LANCZOS)
        im.paste(logo,(left+(100-logo.width)//2,110+(92-logo.height)//2),logo)
    dr.rounded_rectangle((30,218,510,715),radius=28,fill=(24,43,71))
    dr.rounded_rectangle((30,218,510,228),radius=5,fill=CYAN)
    ft,ft2,hl,dl,heading_step,detail_step,detail_y=card_text_layout(dr,scene['heading'],scene['detail'])
    yy=264
    for line in hl:dr.text((55,yy),line,font=ft,fill=WHITE);yy+=heading_step
    yy=detail_y
    for line in dl:dr.text((56,yy),line,font=ft2,fill=(202,218,236));yy+=detail_step
    dr.text((34,734),'官方資訊需核對活動條款',font=font(20),fill=MUTED)
    dr.rounded_rectangle((32,766,508,775),radius=5,fill=(48,70,93))
    dr.rounded_rectangle((32,766,32+int(476*(index+1)/6),775),radius=5,fill=CYAN)
    # Two-line captions occupy their own band, clear of the source note and metadata.
    dr.rounded_rectangle((30,790,510,873),radius=14,fill=(14,28,47))
    dr.text((34,885),x['title'][:22],font=font(21),fill=(170,197,221))
    dr.text((34,925),'資料查核：'+x['checked_at'],font=font(18),fill=MUTED)
    if demo:
        dr.rounded_rectangle((42,655,498,700),radius=12,fill=(144,49,51))
        dr.text((75,663),'內部試播｜未核准發布',font=font(24,True),fill=(255,255,255))
    p=d/f'scene_{index+1:02}.png';im.save(p);return p

def cmd(args,cwd=None):
    ret=subprocess.run(args,cwd=str(cwd) if cwd else None,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if ret.returncode:raise RuntimeError('外部程式執行失敗：\n'+ret.stderr[-3000:])
    return ret.stdout

def duration(p):
    a=json.loads(cmd(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(p)]))
    return float(a['format']['duration'])

def ass_time(sec):
    q=round(100*sec);h,q=divmod(q,360000);m,q=divmod(q,6000);s,cs=divmod(q,100)
    return f'{h}:{m:02}:{s:02}.{cs:02}'

def wrap_caption(text):
    measure=ImageDraw.Draw(Image.new('RGB',(1,1)))
    caption_font=font(26,True)
    tokens=[]
    for token in CAPTION_TOKEN.findall(text):
        if tokens and re.fullmatch(r'[，。！？；：、,.!?;:）)\]」』]+',token):
            tokens[-1]+=token
        else:
            tokens.append(token)
    lines=[]
    current=''
    for token in tokens:
        if measure.textlength(token,font=caption_font)>448:
            raise ValueError('字幕單字超出字幕帶寬度：'+token)
        if current.strip() and measure.textlength(current+token,font=caption_font)>448:
            lines.append(current.rstrip())
            current=token.lstrip()
        else:
            current+=token
    if current.strip():lines.append(current.rstrip())
    if len(lines)>2:raise ValueError('字幕超過兩行，請調整字幕分段')
    return '\\N'.join(lines)


def caption_fragments(text,limit=26):
    start=0
    for token in CAPTION_TOKEN.finditer(text):
        if token.end()-start>limit and token.start()>start:
            yield start,text[start:token.start()]
            start=token.start()
    if start<len(text):yield start,text[start:]


def ass_subs(cues, d):
    head=f'''[Script Info]\nScriptType: v4.00+\nPlayResX: 540\nPlayResY: 960\nWrapStyle: 2\nScaledBorderAndShadow: yes\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n{CAPTION_STYLE}\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n'''
    events=[]
    for c in cues:
        t=c['text'].replace('{','（').replace('}','）').replace('\\','／')
        # Keep captions on two short lines; fail long captions rather than clipping.
        if len(t)>30:raise ValueError('字幕段落過長，請縮短：'+t)
        t=wrap_caption(t)
        events.append(f'Dialogue: 0,{ass_time(c["start"])},{ass_time(c["end"])},Main,,0,0,0,,{t}')
    (d/'captions.ass').write_text(head+'\n'.join(events)+'\n',encoding='utf-8-sig')


def restyle_captions(source,destination):
    text=Path(source).read_text(encoding='utf-8-sig')
    text,count=re.subn(r'^Style: Main,[^\r\n]*',CAPTION_STYLE,text,flags=re.MULTILINE)
    if count!=1:raise ValueError('字幕缺少唯一 Main 樣式，停止重用')
    lines=[]
    for line in text.splitlines():
        if line.startswith('Dialogue:'):
            columns=line.split(',',9)
            columns[9]=wrap_caption(columns[9].replace('\\N',''))
            line=','.join(columns)
        lines.append(line)
    text='\n'.join(lines)+'\n'
    Path(destination).write_text(text,encoding='utf-8-sig')

def music_mix_filters(duration_s,settings):
    gain=float(settings.get('gain_db',-24.0))
    fade_in=min(float(settings.get('fade_in_s',1.5)),duration_s)
    fade_out=min(float(settings.get('fade_out_s',2.5)),duration_s)
    return [
        '[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0,apad,asplit=2[voice][sidechain]',
        f'[2:a]aresample=48000,aformat=channel_layouts=stereo,volume={gain}dB,'
        f'afade=t=in:st=0:d={fade_in},afade=t=out:st={max(0,duration_s-fade_out):.3f}:d={fade_out}[music]',
        '[music][sidechain]sidechaincompress=threshold=0.03:ratio=4:attack=20:release=350:makeup=1[ducked]',
        '[voice][ducked]amix=inputs=2:normalize=0:duration=first:dropout_transition=0,'
        'alimiter=limit=0.95:level=false:latency=true[a]',
    ]


def make_video(x,d,scene_timing,demo, demo_voice=False):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):raise RuntimeError('請先安裝 FFmpeg，並加入 PATH。')
    imgs=[]
    for i,s in enumerate(scenes(x)):imgs.append(card(x,s,i,d,demo))
    parts=[]
    for i,(img,row) in enumerate(zip(imgs,scene_timing)):
        dur=row['end']-row['start']
        if dur<0.35:raise ValueError('場景時長太短，無法顯示資訊卡。')
        segment=d/f'clip_{i+1:02}.mp4'
        frames=round(dur*FPS);dur=frames/FPS
        cmd(['ffmpeg','-hide_banner','-loglevel','error','-y','-loop','1','-framerate',str(FPS),'-i',str(img),'-frames:v',str(frames),'-vf','format=yuv420p','-c:v','libx264','-preset','ultrafast','-crf','24','-r',str(FPS),str(segment)])
        parts.append(segment)
    concat=d/'concat.txt'; concat.write_text(''.join("file '"+p.name+"'\n" for p in parts),encoding='utf-8')
    vid=d/'video_silent.mp4'
    cmd(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(vid)],cwd=d)
    output=d/('AutoRender_V21_DEMO_VOICE_NOT_FOR_PUBLISHING.mp4' if demo_voice else ('AutoRender_V2_DEMO.mp4' if demo else 'AutoRender_V2_READY_FOR_REVIEW.mp4'))
    if demo and not demo_voice:
        cmd(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(vid),'-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000','-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','96k','-shortest','-movflags','+faststart',str(output)])
    else:
        wav=d/'narration.wav'
        if not wav.exists():raise RuntimeError('缺少 narration.wav，請先執行 voice 或 all。')
        ad=duration(wav);vd=duration(vid)
        if abs(ad-vd)>0.75:raise RuntimeError(f'旁白與影片長度差距過大：{ad:.2f} vs {vd:.2f}')
        music=Path(x.get('background_music',ROOT/'background_music.mp3'))
        args=['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(vid),'-i',str(wav)]
        if music.exists():args += ['-stream_loop','-1','-i',str(music)]
        filters=['[0:v]ass=captions.ass,format=yuv420p[v]']
        if music.exists() and x.get('music_mix'):
            filters+=music_mix_filters(vd,x['music_mix'])
        else:
            filters+=['[1:a]volume=1.0,apad[a1]']
            if music.exists():filters+=['[2:a]volume=0.10[a2]','[a1][a2]amix=inputs=2:duration=first:dropout_transition=0[a]']
            else:filters+=['[a1]anull[a]']
        args += ['-filter_complex',';'.join(filters),'-map','[v]','-map','[a]','-t',f'{vd:.3f}','-c:v','libx264','-preset','veryfast','-crf','23','-r',str(FPS),'-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-movflags','+faststart',str(output)]
        cmd(args,cwd=d)
    if not output.exists() or duration(output)<3: raise RuntimeError('MP4 輸出驗證失敗')
    print('已輸出：',output,'長度',round(duration(output),2),'秒')
    print('僅供人工審核，不會自動上架 YouTube。')
    if demo_voice: print('【示範影片，非真實優惠，禁止當成有效優惠公開發布】')
    return output

def voice(x,d,s,script, demo_voice=False):
    if not demo_voice: check_publishable(x)
    import azure.cognitiveservices.speech as speechsdk
    key=os.environ.get('AZURE_SPEECH_KEY') or getpass.getpass('輸入 Azure Speech API Key（輸入不顯示）：').strip()
    if not key:raise ValueError('未提供 Azure Key')
    cfg=speechsdk.SpeechConfig(subscription=key,region='eastasia')
    cfg.speech_synthesis_voice_name='zh-TW-HsiaoChenNeural'
    cfg.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm)
    syn=speechsdk.SpeechSynthesizer(speech_config=cfg,audio_config=None)
    events=[]
    def boundary(e):
        if e.text and e.text.strip():events.append({'offset':int(e.text_offset),'time':e.audio_offset/1e7})
    syn.synthesis_word_boundary.connect(boundary)
    result=syn.speak_text_async(script).get()
    if result.reason!=speechsdk.ResultReason.SynthesizingAudioCompleted:
        raise RuntimeError('Azure 配音失敗：'+str(getattr(result,'cancellation_details','unknown')))
    data=bytes(result.audio_data)
    if data[:4]!=b'RIFF':raise RuntimeError('Azure 未回傳有效 WAV')
    (d/'narration.wav').write_bytes(data)
    with wave.open(str(d/'narration.wav'),'rb') as w: total=w.getnframes()/w.getframerate()
    events.sort(key=lambda e:e['offset'])
    if len(events)<len(s):raise RuntimeError('不足以取得每場景時間戳，停止輸出。')
    start_offsets=[row['text_start'] for row in s]
    starts=[]
    for off in start_offsets:
        matched=next((e['time'] for e in events if e['offset']>=off),None)
        if matched is None:raise RuntimeError('找不到場景對應 Word Boundary 事件')
        starts.append(matched)
    if any(b<=a for a,b in zip(starts,starts[1:])):raise RuntimeError('場景時間戳未依序增加')
    # Intro card starts at t=0; boundary events still align first spoken word.
    bounds=[0.]+starts[1:]+[total]
    timing=[{'start':bounds[i],'end':bounds[i+1],'title':s[i]['heading']} for i in range(len(s))]
    (d/'timeline.json').write_text(json.dumps({'total':total,'scenes':timing,'source_url':x['source_url']},ensure_ascii=False,indent=2),encoding='utf-8')
    # Generate sentence-level captions using Azure event times, splitting long scene narration by punctuation.
    cues=[]
    for i,scene in enumerate(s):
        txt=scene['narration']; base=scene['text_start']; curr=0
        for match in re.finditer(r'[^，。！？!?,、\n]+[，。！？!?,、]?|\n',txt):
            fragment=match.group().strip()
            if not fragment:continue
            # Split lengthy captions; use boundary events instead of interpolating timings.
            for j,sub in caption_fragments(fragment):
                offset=base+match.start()+j
                t=next((e['time'] for e in events if e['offset']>=offset),None)
                if t is None:raise RuntimeError('字幕缺少 Word Boundary 事件')
                cues.append({'start':t,'text':sub})
    for i,c in enumerate(cues):
        c['end']=max(c['start']+0.10, (cues[i+1]['start']-0.05 if i+1<len(cues) else total-0.05))
        c['end']=min(total,c['end'])
        if i and c['start']<cues[i-1]['end']-0.01:raise RuntimeError('字幕出現重疊，停止製作')
    ass_subs(cues,d)
    def srttime(t):
        ms=round(t*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);ss,ms=divmod(ms,1000)
        return f'{h:02}:{m:02}:{ss:02},{ms:03}'
    (d/'captions.srt').write_text('\n\n'.join(f'{i}\n{srttime(c["start"])} --> {srttime(c["end"])}\n{c["text"]}' for i,c in enumerate(cues,1)),encoding='utf-8-sig')
    print(f'Azure 曉臻配音成功：{total:.2f} 秒、{len(cues)} 段字幕')
    return timing

def main():
    ap=argparse.ArgumentParser(description='AutoRender V2 — 繁體中文優惠資訊卡 Shorts')
    ap.add_argument('command',choices=['prepare','demo','demo-voice','voice','render','all'])
    ap.add_argument('--input',default='offer_demo.json')
    arg=ap.parse_args()
    p=Path(arg.input);p=p if p.is_absolute() else ROOT/p
    x=load_input(p)
    demo=arg.command in ('demo','demo-voice')
    demo_voice=arg.command=='demo-voice'
    d=outdir(x,demo)
    s,script=prepare(x,d)
    if arg.command=='prepare':print('已產生：',d/'narration.txt',d/'storyboard.json');return
    if demo and not demo_voice:
        # 6 two-second sample scenes (no claims of timing-to-voice accuracy).
        tim=[{'start':2.0*i,'end':2.0*(i+1)} for i in range(6)]
        make_video(x,d,tim,True);return
    if not demo_voice: check_publishable(x)
    if arg.command in ('voice','all','demo-voice'):tim=voice(x,d,s,script,demo_voice=demo_voice)
    else:
        p=d/'timeline.json'
        if not p.exists():raise RuntimeError('缺少 timeline.json，請先執行 voice')
        tim=json.loads(p.read_text(encoding='utf-8'))['scenes']
    if arg.command in ('render','all','demo-voice'):make_video(x,d,tim,demo_voice,demo_voice=demo_voice)

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,FileNotFoundError) as e:
        print('錯誤：',e,file=sys.stderr);sys.exit(1)
