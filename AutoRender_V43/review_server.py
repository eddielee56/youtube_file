"""Loopback-only preview review page, with per-process request authentication."""
import contextlib
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser
import urllib.request

import autorender_review as review
import autorender_v43 as scheduler


def escape(value):
    return html.escape(str(value or ''), quote=True)


def page(queue, token):
    labels = {'APPROVED': '審閱通過', 'PENDING': '待審閱',
              'CHANGES_REQUESTED': '退回修改', 'FAILED': '製片失敗',
              'RUNNING': '製作中', 'SUCCEEDED': '製作完成'}
    cards = []
    for item in queue['items']:
        valid = item['integrity'] == 'OK' and item['status'] == 'SUCCEEDED'
        media = '/media?' + urlencode({'token': token, 'event_key': item['event_key'],
                                        'sha256': item.get('mp4_sha256') or ''})
        video = f'<video controls preload="metadata" src="{escape(media)}"></video>' if valid else ''
        source = ''
        if urlsplit(item['source_url']).scheme == 'https':
            source = f'<a target="_blank" rel="noreferrer" href="{escape(item["source_url"])}">查看官方條款</a>'
        history = ''.join(f'<li>{escape(entry["decided_at"])} · '
                          f'{"通過" if entry["decision"] == "approve" else "退回修改"} '
                          f'{escape(entry["note"])}</li>' for entry in item['decisions'])
        integrity = '<p class="error">影片或審核資料無法驗證，請檢查本機檔案。</p>' if not valid else ''
        form = ''
        if valid:
            form = f'''<form>
              <input type="hidden" name="event_key" value="{escape(item['event_key'])}">
              <input type="hidden" name="sha256" value="{escape(item['mp4_sha256'])}">
              <label>審閱備註，退回時請填寫修改原因
                <textarea name="note" maxlength="2000" rows="2"></textarea></label>
              <div class="actions"><button name="decision" value="approve">通過審閱</button>
              <button class="secondary" name="decision" value="reject">退回修改</button></div>
              <p class="feedback" role="status"></p>
            </form>'''
        cards.append(f'''<article>
          <header><h2>{escape(item['title'])}</h2>
          <span>{escape(labels.get(item.get('review_status') or item['status'], item['status']))}</span></header>
          {integrity}<div class="review-content">{video}<div class="facts">
          <p>來源查核日期 {escape(item['checked_at'])}　活動有效至 {escape(item['valid_until'])}</p>
          {source}<h3>旁白</h3><pre>{escape(item['narration'])}</pre>
          <details><summary>影片版本與審閱紀錄</summary>
          <p class="hash">{escape(item.get('mp4_sha256'))}</p>
          <p>審閱登錄時間 {escape(item.get('reviewed_at'))}</p><ul>{history}</ul></details>
          {form}</div></div></article>''')
    notices = ''.join(f'<li>{escape(item["stage"])} · {escape(item["status"])} '
                      f'{escape(item.get("error_type"))}</li>' for item in queue['notifications'][:8])
    body = '\n'.join(cards) or '<p>目前沒有已登錄的製片工作。</p>'
    return f'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>AutoRender 影片審閱</title>
    <style>
    *{{box-sizing:border-box}}body{{margin:0;background:#f4f6f8;color:#172b3a;font:16px/1.65 Inter,"Segoe UI",sans-serif}}
    main{{max-width:1200px;margin:auto;padding:32px 24px}}h1{{margin:0;font-size:30px}}h2{{font-size:21px;margin:0}}h3{{font-size:16px}}
    .intro{{margin:8px 0 26px;color:#506471}}article{{background:white;border:1px solid #dbe2e8;border-radius:12px;padding:24px;margin:20px 0}}
    header{{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:22px}}header span{{white-space:nowrap;color:#176146}}
    .review-content{{display:flex;gap:28px}}video{{width:270px;max-width:100%;align-self:flex-start;background:#111;border-radius:8px}}
    .facts{{flex:1;min-width:0}}pre{{white-space:pre-wrap;font:inherit;background:#f7f9fa;padding:18px;border-radius:8px}}
    a{{color:#156492}}label{{display:block;margin-top:20px}}textarea{{display:block;width:100%;font:inherit;padding:10px;border:1px solid #aebdc7;border-radius:6px}}
    .actions{{display:flex;gap:10px;margin-top:14px}}button{{cursor:pointer;background:#155d52;color:white;border:1px solid #155d52;border-radius:6px;padding:10px 20px;font:inherit}}
    button.secondary{{background:white;color:#7c3d24;border-color:#bda99f}}button:disabled{{opacity:.55;cursor:wait}}
    .hash{{font:12px/1.6 monospace;overflow-wrap:anywhere}}.error{{color:#a43125}}details{{margin:18px 0}}summary{{cursor:pointer}}
    .feedback{{color:#155d52}}@media(max-width:700px){{.review-content{{flex-direction:column}}header{{align-items:flex-start}}main{{padding:20px 14px}}article{{padding:18px}}video{{width:100%;max-height:520px}}}}
    </style><main><h1>影片審閱</h1><p class="intro">檢查影片、旁白與官方來源後，記錄這個版本的審閱結果。</p>
    {body}<details><summary>最近通知</summary><ul>{notices}</ul></details></main>
    <script>
    const token = {json.dumps(token)};
    for (const form of document.querySelectorAll('form')) {{
      form.addEventListener('submit', async event => {{
        event.preventDefault();
        const data = new FormData(form);
        data.set('decision', event.submitter.value);
        const feedback = form.querySelector('.feedback');
        if (data.get('decision') === 'reject' && !data.get('note').trim()) {{
          feedback.textContent = '請填寫退回修改原因。'; return;
        }}
        for (const button of form.querySelectorAll('button')) button.disabled = true;
        try {{
          const response = await fetch('/decision', {{method:'POST',
            headers:{{'X-Review-Token':token}}, body:new URLSearchParams(data)}});
          const result = await response.json();
          if (!response.ok) throw new Error(result.error);
          window.location.reload();
        }} catch (error) {{
          feedback.textContent = error.message;
          for (const button of form.querySelectorAll('button')) button.disabled = false;
        }}
      }});
    }}
    </script></html>'''


def make_server(port=8765):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format_string, *args):
            # URLs contain a local access token, so access logging is suppressed.
            pass

        def reply(self, code, body, content_type='application/json; charset=utf-8'):
            body = body.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def valid_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            if not self.valid_host() or not secrets.compare_digest(query.get('token', [''])[0], token):
                self.reply(403, '{"error":"Access denied"}')
                return
            try:
                route = urlsplit(self.path).path
                if route == '/':
                    self.reply(200, page(review.review_queue(), token), 'text/html; charset=utf-8')
                elif route == '/media':
                    self.media(query)
                else:
                    self.reply(404, '{"error":"Not found"}')
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.reply(500, '{"error":"Unable to read local review data"}')

        def media(self, query):
            key = query.get('event_key', [''])[0]
            digest = query.get('sha256', [''])[0]
            with contextlib.closing(review.connect()) as conn:
                row = conn.execute('SELECT mp4,mp4_sha256 FROM previews WHERE event_key=?', (key,)).fetchone()
            if row is None or row['mp4_sha256'] != digest:
                self.reply(404, '{"error":"Preview version not found"}')
                return
            movie, current_digest = scheduler.validate_movie(row['mp4'])
            if current_digest != digest:
                self.reply(409, '{"error":"Preview content changed"}')
                return
            size = movie.stat().st_size
            start, end = 0, size - 1
            requested = self.headers.get('Range')
            if requested:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                if not match or not any(match.groups()):
                    self.reply(416, '{"error":"Invalid byte range"}')
                    return
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), end) if last else end
                else:
                    start = max(0, size - int(last))
                if start > end or start >= size:
                    self.reply(416, '{"error":"Invalid byte range"}')
                    return
            self.send_response(206 if requested else 200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Length', str(end - start + 1))
            if requested:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if self.command == 'HEAD':
                return
            with movie.open('rb') as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def do_POST(self):
            origin = self.headers.get('Origin')
            expected_origin = f'http://127.0.0.1:{self.server.server_port}'
            if (not self.valid_host() or origin != expected_origin
                    or not secrets.compare_digest(self.headers.get('X-Review-Token', ''), token)):
                self.reply(403, '{"error":"Access denied"}')
                return
            if urlsplit(self.path).path != '/decision':
                self.reply(404, '{"error":"Not found"}')
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16000:
                    raise scheduler.V43Error('Invalid request size')
                data = parse_qs(self.rfile.read(length).decode('utf-8'), keep_blank_values=True)
                review.decide(data['event_key'][0], data['sha256'][0],
                              data['decision'][0], data.get('note', [''])[0])
                self.reply(200, '{"saved":true}')
            except (KeyError, ValueError, scheduler.V43Error) as error:
                self.reply(409, json.dumps({'error': str(error)}, ensure_ascii=False))
            except Exception:
                self.reply(500, '{"error":"Unable to save review decision"}')

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server, token


def serve(port=8765, open_browser=True):
    try:
        server, token = make_server(port)
    except OSError:
        # A second double-click reopens the existing authenticated review page.
        address_file = scheduler.OUTPUT / 'review_server.json'
        if not address_file.is_file():
            raise
        existing = scheduler.read(address_file)['url']
        address = urlsplit(existing)
        if address.scheme != 'http' or address.hostname != '127.0.0.1' or address.port != port:
            raise scheduler.V43Error('Review port is occupied by another application')
        with urllib.request.urlopen(urllib.request.Request(existing, method='HEAD'), timeout=3) as response:
            if response.status != 200:
                raise scheduler.V43Error('Existing review server is unavailable')
        if open_browser:
            webbrowser.open(existing)
        print('REVIEW PAGE:', existing, flush=True)
        return
    url = f'http://127.0.0.1:{server.server_port}/?token={token}'
    scheduler.write_json(scheduler.OUTPUT / 'review_server.json', {'url': url, 'pid': scheduler.os.getpid()})
    print('REVIEW PAGE:', url, flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
