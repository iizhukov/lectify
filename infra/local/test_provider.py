"""Explicit offline HTTP fixture. Never forwards requests or calls real models."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import threading
import time

_observations={}
_lock=threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_GET(self):
        prefix='/observations/'
        if not self.path.startswith(prefix): self.send_error(404); return
        key=self.path[len(prefix):]
        with _lock: count=_observations.get(key,0)
        body=json.dumps({'calls':count}).encode()
        self.send_response(200); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        if self.headers.get('Authorization') != 'Bearer local-offline-fixture':
            self.send_error(401); return
        if self.headers.get('Transfer-Encoding','').lower() == 'chunked':
            chunks=[]
            while True:
                size=int(self.rfile.readline().strip(),16)
                if size==0:
                    self.rfile.readline(); break
                chunks.append(self.rfile.read(size)); self.rfile.read(2)
                if sum(map(len,chunks))>12*1048576:
                    self.send_error(413); return
            raw=b''.join(chunks)
        else:
            size=int(self.headers.get('Content-Length','0'))
            if size>12*1048576: self.send_error(413); return
            raw=self.rfile.read(size)
        data=json.loads(raw)
        if self.path == '/chat/completions':
            content=data['messages'][-1]['content']
            key=hashlib.sha256(content.encode()).hexdigest()
            with _lock:
                count=_observations[key]=_observations.get(key,0)+1
            failures=3 if content.startswith('TEST_FAIL_THREE:') else 1 if content.startswith('TEST_FAIL_ONCE:') else 0
            if count<=failures: self.send_error(503); return
            if content.startswith('TEST_DELAY:'): time.sleep(15)
            text='LOCAL TEST RESPONSE: '+data['messages'][-1]['content']
            system=data['messages'][0]['content']
            if system.startswith('Return only one subject:'): text='math'
            if system.startswith('Создай полный компилируемый LaTeX') or system.startswith('Исправь ошибки компиляции LaTeX'):
                text='```latex\n'+r'\documentclass{article}\begin{document}Offline LaTeX notes: $1+1=2$.\end{document}'+'\n```'
            self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
            for event in ({'choices':[{'delta':{'content':text},'finish_reason':None}]},
                          {'choices':[{'delta':{},'finish_reason':'stop'}],'usage':{'total_tokens':1}}):
                self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        elif self.path == '/audio/transcriptions':
            audio=base64.b64decode(data['file'].split(',',1)[1],validate=True)
            if not audio: self.send_error(400); return
            body=json.dumps({'text':'LOCAL TEST TRANSCRIPT','language':data.get('language','auto'),'duration':1}).encode()
            self.send_response(200); self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        else: self.send_error(404)


if __name__ == '__main__': ThreadingHTTPServer(('127.0.0.1',18080),Handler).serve_forever()
