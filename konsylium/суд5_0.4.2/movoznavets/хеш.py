import hashlib
for p in ['/root/ai-agents/Nigredo/interpreter/nigredo.py', '/root/ai-agents/Nigredo/mcp/nigredo_mcp.py']:
    print(hashlib.sha256(open(p, 'rb').read()).hexdigest(), p)
