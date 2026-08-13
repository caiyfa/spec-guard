# -*- coding: utf-8 -*-
"""分析会话文件结构：提取 user 消息与 assistant 摘要"""
import json

path = r'agent/sessions/90024166/tdm/20260812_184441_9b7aec0f.jsonl'
with open(path, encoding='utf-8') as f:
    lines = f.readlines()
print('total lines:', len(lines))
for i, line in enumerate(lines):
    try:
        obj = json.loads(line)
    except Exception as e:
        print(i, 'PARSE ERROR', e)
        continue
    role = obj.get('role', obj.get('_type', '?'))
    content = obj.get('content', '')
    if role == 'user':
        print(f'--- line {i} role={role} len={len(content)} ---')
        print(content[:800].replace('\n', ' '))
        print()
