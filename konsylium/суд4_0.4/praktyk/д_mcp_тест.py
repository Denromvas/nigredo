"""Прогнати MCP-сервер Nigredo на запитах із д_mcp_запити.jsonl; робоча тека — у моїй теці."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ, NIGREDO_WORKDIR=os.path.join(HERE, 'mcp_робоча'))
reqs = open(os.path.join(HERE, 'д_mcp_запити.jsonl'), encoding='utf-8').read()
p = subprocess.run([sys.executable, '/root/ai-agents/Nigredo/mcp/nigredo_mcp.py'], input=reqs,
                   capture_output=True, text=True, env=env, timeout=600)
for line in p.stdout.splitlines():
    m = json.loads(line)
    r = m.get('result') or m.get('error')
    if isinstance(r, dict) and 'content' in r:
        r = {'isError': r['isError'], 'text': r['content'][0]['text'][:700]}
    print(m.get('id'), json.dumps(r, ensure_ascii=False)[:900])
    print('---')
print('stderr:', p.stderr[:500])
