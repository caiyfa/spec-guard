"""specstd.signature — 内容签名检测。

spec 主体签名（剔除 §11 Changelog）+ api 每 path 入参/出参签名。
签名变化检测 → 变更命中 covers 反查 → 受影响场景标 DRIFT。
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

import yaml

from specstd.schema import FILE_SPEC_MD, FILE_API_YAML, DIR_SPECS
from specstd.anchors import scan_anchors, AnchorInfo


def sign_spec_body(text: str) -> str:
    """对 spec.md 主体签名（剔除 §11 Changelog 段落）。"""
    # 匹配 ## 十一、Changelog / ## 11. Changelog / ## Changelog
    patterns = [
        r'^##\s+(?:十一|11)\s*[\.、：:]\s*[Cc]hangelog.*?(?=^##\s|\Z)',
        r'^##\s+[Cc]hangelog.*?(?=^##\s|\Z)',
    ]
    body = text
    for p in patterns:
        body = re.sub(p, '', body, flags=re.MULTILINE | re.DOTALL)
    return hashlib.sha256(body.strip().encode('utf-8')).hexdigest()[:12]


def _norm_schema(schema) -> object:
    """规范化提取 schema 结构（V4 修复：字段级变更可检测）。

    递归提取字段名 / 类型 / 必填 / 枚举 / 数组项结构，忽略描述性文本。
    $ref 保留引用名（引用目标变化会在定义处被独立签名）。
    """
    if not isinstance(schema, dict):
        return None
    if '$ref' in schema:
        return {'$ref': str(schema['$ref']).split('/')[-1]}
    node = {}
    if schema.get('type'):
        node['t'] = schema['type']
    if schema.get('required'):
        node['req'] = sorted(str(r) for r in schema['required'])
    if schema.get('enum'):
        node['enum'] = sorted(str(e) for e in schema['enum'])
    props = schema.get('properties')
    if isinstance(props, dict):
        node['props'] = {k: _norm_schema(v) for k, v in sorted(props.items())}
    items = schema.get('items')
    if isinstance(items, dict):
        node['items'] = _norm_schema(items)
    # allOf/anyOf/oneOf 组合结构
    for comb in ('allOf', 'anyOf', 'oneOf'):
        subs = schema.get(comb)
        if isinstance(subs, list):
            node[comb] = [_norm_schema(s) for s in subs]
    return node or None


def _norm_content(content: dict) -> object:
    """规范化 requestBody/responses 的 content（取 application/json 优先的 schema）。"""
    if not isinstance(content, dict):
        return None
    for mt in ('application/json', 'application/*+json', '*/*'):
        media = content.get(mt)
        if isinstance(media, dict) and 'schema' in media:
            return _norm_schema(media['schema'])
    # 无 json 媒体类型时取第一个带 schema 的
    for media in content.values():
        if isinstance(media, dict) and 'schema' in media:
            return _norm_schema(media['schema'])
    return None


def sign_api_path(path: str, method: str, spec: dict, components: dict | None = None) -> str:
    """对 api.yaml 中单个 path+method 的入参/出参 schema 签名（V4 修复）。

    签名材料：参数（名+位置+必填+schema 结构）、requestBody schema 结构、
    每个响应码的 schema 结构——出参字段级增删改均会导致签名变化。
    """
    params = spec.get('parameters', [])
    request_body = spec.get('requestBody', {})
    responses = spec.get('responses', {})

    contract = {
        'path': path,
        'method': method.upper(),
        'parameters': sorted(
            (
                {
                    'name': str(p.get('name', '')),
                    'in': str(p.get('in', '')),
                    'required': bool(p.get('required')),
                    'schema': _norm_schema(p.get('schema') or {}),
                }
                for p in params if isinstance(p, dict)
            ),
            key=lambda d: (d['name'], d['in']),
        ),
        'request_body': _norm_content(request_body.get('content', {}))
        if isinstance(request_body, dict) else None,
        'responses': {
            str(code): _norm_content((resp or {}).get('content', {}))
            for code, resp in sorted(responses.items()) if isinstance(resp, dict)
        },
    }
    raw = json.dumps(contract, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]


def sign_api_yaml(api_spec: dict) -> dict:
    """对 api.yaml 全量签名，返回 {path: {method: signature}}。"""
    components = api_spec.get('components') or {}
    signatures = {}
    for path, methods in (api_spec.get('paths') or {}).items():
        if not isinstance(methods, dict):
            continue
        signatures[path] = {}
        for method, spec in methods.items():
            if method.upper() in ('GET', 'POST', 'PUT', 'DELETE', 'PATCH') and isinstance(spec, dict):
                signatures[path][method] = sign_api_path(path, method, spec, components)
    return signatures


def compute_signatures(workspace_root: Path) -> dict:
    """计算当前工作区的全部签名。

    返回 {file_path: {spec_body: sha, api_paths: {path: {method: sha}}}}。
    """
    specs_dir = workspace_root / DIR_SPECS
    if not specs_dir.is_dir():
        return {}

    signatures = {}
    for spec_md in sorted(specs_dir.rglob(FILE_SPEC_MD)):
        rel = str(spec_md.relative_to(workspace_root)).replace('\\', '/')
        text = spec_md.read_text(encoding='utf-8')
        signatures[rel] = {'spec_body': sign_spec_body(text), 'api_paths': {}}

        api_yaml = spec_md.parent / FILE_API_YAML
        if api_yaml.is_file():
            try:
                with open(api_yaml, 'r', encoding='utf-8') as f:
                    api_spec = yaml.safe_load(f) or {}
                signatures[rel]['api_paths'] = sign_api_yaml(api_spec)
            except Exception:
                pass

    return signatures


def save_signature_baseline(signatures: dict, path: Path):
    """保存签名基线到 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(signatures, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write('\n')


def load_signature_baseline(path: Path) -> dict:
    """加载签名基线。"""
    if not path.is_file():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def detect_changes(current: dict, baseline: dict) -> list[dict]:
    """检测签名变化，返回变更列表。"""
    changes = []

    for file_path, sigs in current.items():
        if file_path not in baseline:
            changes.append({'file': file_path, 'type': 'added', 'detail': '新增文件'})
            continue

        base = baseline[file_path]
        if sigs.get('spec_body') != base.get('spec_body'):
            changes.append({
                'file': file_path, 'type': 'spec_body_changed',
                'old': base.get('spec_body'), 'new': sigs.get('spec_body'),
                'detail': 'spec.md 主体签名变化',
            })

        cur_api = sigs.get('api_paths', {})
        base_api = base.get('api_paths', {})
        for p, methods in cur_api.items():
            if p not in base_api:
                changes.append({'file': file_path, 'type': 'api_path_added',
                                'path': p, 'detail': f'新增 API 路径: {p}'})
                continue
            for m, sig in methods.items():
                if m not in base_api[p]:
                    changes.append({'file': file_path, 'type': 'api_method_added',
                                    'path': p, 'method': m,
                                    'detail': f'新增 API 方法: {m.upper()} {p}'})
                elif base_api[p][m] != sig:
                    changes.append({'file': file_path, 'type': 'api_signature_changed',
                                    'path': p, 'method': m,
                                    'old': base_api[p][m], 'new': sig,
                                    'detail': f'API 签名变化: {m.upper()} {p}'})

    for file_path in baseline:
        if file_path not in current:
            changes.append({'file': file_path, 'type': 'removed', 'detail': '文件已删除'})

    return changes


def find_affected_scenarios(changes: list[dict], anchors: dict[str, AnchorInfo],
                             scenarios_root: Path) -> list[dict]:
    """根据签名变更反查受影响的场景（通过 covers 关联）。"""
    changed_frs = set()
    for change in changes:
        file_path = change.get('file', '').replace('\\', '/')
        for fr_id, info in anchors.items():
            if file_path and file_path in info.file_path.replace('\\', '/'):
                changed_frs.add(fr_id)

    if not changed_frs:
        return []

    affected = []
    for yaml_file in sorted(scenarios_root.rglob('*.yaml')):
        if yaml_file.name.startswith('_'):
            continue
        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                raw = yaml.safe_load(f) or {}
        except Exception:
            continue

        covers = (raw.get('doc') or {}).get('covers', [])
        matched = set(str(c) for c in covers) & changed_frs
        if matched:
            affected.append({
                'scenario_id': raw.get('id', ''),
                'title': raw.get('title', ''),
                'covers': sorted(matched),
                'path': str(yaml_file.relative_to(scenarios_root)).replace('\\', '/'),
                'status': 'DRIFT',
            })

    return affected
