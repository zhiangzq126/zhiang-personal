"""Browser SVG import: read-only inspection followed by an explicit batch commit."""
import base64
import copy
import json
import re
from pathlib import Path

from library import ROOT, check_schema, clean, norm, normalize_svg, read_json, review_queue, safe_path, sha, slug, write_json

MAX_FILES = 50
MAX_BYTES = 12_000_000
KINDS = {'product', 'brand', 'component', 'container-symbol', 'status'}


def text(value, label, limit=500, required=False):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(label + '格式不正确或过长')
    value = clean(value)
    if required and not value:
        raise ValueError('请填写' + label)
    return value


class ImportService:
    def __init__(self, root=ROOT):
        self.root = Path(root)

    def state(self):
        names = ('index', 'preferences', 'sources')
        values = [read_json(self.root / 'catalog' / (n + '.json')) for n in names]
        revision = sha(json.dumps(values, sort_keys=True, ensure_ascii=False).encode())
        return (*values, revision)

    def decode(self, items):
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_FILES:
            raise ValueError('每批请选择 1–50 个 SVG')
        results, size = [], 0
        for item in items:
            if not isinstance(item, dict):
                raise ValueError('图标信息格式不正确')
            result = {'filename': str(item.get('filename', ''))}
            if item.get('action') == 'skip':
                results.append({**result, 'skipped': True})
                continue
            try:
                name = text(item.get('filename'), '文件名', 240, True)
                if '/' in name or '\\' in name or '\x00' in name or len(name.encode()) > 240 or not name.lower().endswith('.svg'):
                    raise ValueError('请使用不含路径的 SVG 文件名')
                encoded = item.get('data', '')
                if not isinstance(encoded, str) or len(encoded) > 5_333_336:
                    raise ValueError('单个 SVG 不得超过 4 MB')
                raw = base64.b64decode(encoded, validate=True)
                size += len(raw)
                normalized, box = normalize_svg(raw)
                metadata = {
                    'name': text(item.get('name', Path(name).stem), '产品名称', 200, True),
                    'provider': text(item.get('provider', ''), '厂商标识', 60, True),
                    'category': text(item.get('category', ''), '分类', 100, True),
                    'style': text(item.get('style', '用户导入'), '变体说明', 100, True),
                    'kind': item.get('kind', 'product'),
                    'source': text(item.get('source', ''), '来源', 1000),
                    'note': text(item.get('note', ''), '备注', 1000),
                }
                if not re.fullmatch('[a-z][a-z0-9-]*', metadata['provider']):
                    raise ValueError('厂商标识请使用小写英文、数字和连字符，以字母开头')
                if metadata['kind'] not in KINDS:
                    raise ValueError('请选择有效用途')
                aliases = item.get('aliases', [])
                if not isinstance(aliases, list) or len(aliases) > 30:
                    raise ValueError('别名最多 30 个')
                metadata['aliases'] = list(dict.fromkeys(text(a, '别名', 200) for a in aliases if a))
                digest = sha(normalized)
                result.update(filename=name, metadata=metadata, raw=raw, normalized=normalized,
                              asset={'path': f'assets/{digest[:2]}/{digest}.svg', 'sha256': digest,
                                     'format': 'svg', 'representation': 'vector', 'bytes': len(normalized), 'viewBox': box})
            except Exception as exc:
                result['error'] = str(exc)
            results.append(result)
        if size > MAX_BYTES:
            raise ValueError('每批 SVG 总大小不得超过 12 MB')
        return results

    @staticmethod
    def matches(row, catalog):
        terms = {norm(x) for x in [row['metadata']['name'], *row['metadata']['aliases']] if norm(x)}
        exact = {}
        by_product = {}
        for variant in catalog['variants']:
            by_product.setdefault(variant['product_id'], []).append(variant)
            if variant['asset']['sha256'] == row['asset']['sha256']:
                exact.setdefault(variant['product_id'], []).append(variant)
        matches = []
        for product in catalog['products']:
            reasons = []
            if product['id'] in exact:
                reasons.append('exact')
            if terms & {norm(t) for t in [product['name'], *product['aliases']]}:
                reasons.append('name')
            if reasons:
                variants = exact.get(product['id']) or by_product.get(product['id'], [])
                matches.append({'product': product, 'reasons': reasons, 'variants': variants})
        return sorted(matches, key=lambda m: ('exact' not in m['reasons'], m['product']['provider'] != row['metadata']['provider'], m['product']['id']))

    def inspect(self, payload):
        catalog, _, _, revision = self.state()
        rows = self.decode(payload.get('items'))
        output = []
        for i, row in enumerate(rows):
            public = {k: v for k, v in row.items() if k not in ('raw', 'normalized')}
            if 'asset' in row:
                public['preview'] = 'data:image/svg+xml;base64,' + base64.b64encode(row['normalized']).decode()
                public['matches'] = self.matches(row, catalog)
                terms = {norm(x) for x in [row['metadata']['name'], *row['metadata']['aliases']]}
                public['batch_matches'] = [j for j, other in enumerate(rows) if j != i and 'asset' in other and
                    (other['asset']['sha256'] == row['asset']['sha256'] or terms & {norm(x) for x in [other['metadata']['name'], *other['metadata']['aliases']]})]
            output.append(public)
        return {'revision': revision, 'items': output}

    def commit(self, payload):
        request_id = payload.get('request_id', '')
        if not isinstance(request_id, str) or not re.fullmatch('[a-zA-Z0-9-]{16,80}', request_id):
            raise ValueError('缺少有效的导入请求标识，请重新检查')
        receipt_path = self.root / 'reports/web-imports' / (request_id + '.json')
        payload_hash = sha(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode())
        receipt = read_json(receipt_path)
        if receipt:
            if receipt['payload_hash'] != payload_hash:
                raise ValueError('导入请求已变更，请重新检查')
            return receipt['result']
        catalog, prefs, manifest, revision = self.state()
        if payload.get('revision') != revision:
            raise ValueError('图标库或偏好已更新，请重新检查重复项后再导入')
        status = payload.get('status')
        if status not in ('ready', 'pending'):
            raise ValueError('请选择确认启用或待确认')
        source_name = text(payload.get('source_name', ''), '批次来源', 160, True)
        rows = self.decode(payload.get('items'))
        catalog = copy.deepcopy(catalog)
        writes, result, default_requests = {}, [], {}
        source_paths = {x['path'] for x in manifest['files']}
        for i, (row, decision) in enumerate(zip(rows, payload['items'])):
            if row.get('skipped'):
                result.append({'filename': row['filename'], 'action': 'skipped'})
                continue
            if row.get('error'):
                raise ValueError(f"{row['filename']}：{row['error']}；请更正或跳过")
            meta = row['metadata']
            action = decision.get('action')
            if action not in ('new', 'link'):
                raise ValueError(f"{row['filename']}：请选择新建产品或关联已有产品")
            make_default = decision.get('make_default', False)
            if type(make_default) is not bool:
                raise ValueError('默认偏好格式不正确')
            if status == 'pending' and make_default:
                raise ValueError('待确认图标不能设为默认，请取消该选项')
            if action == 'new':
                if self.matches(row, catalog) and decision.get('distinct') is not True:
                    raise ValueError(f"{row['filename']}：存在重复候选，请关联已有产品，或明确确认为不同产品")
                key = sha((request_id + ':' + str(i)).encode())[:12]
                pid = meta['provider'] + '/web-' + slug(meta['name'])[:60] + '-' + key
                product = {'id': pid, 'provider': meta['provider'], 'name': meta['name'],
                           'category': meta['category'], 'kind': meta['kind'], 'aliases': list(dict.fromkeys([meta['name'], *meta['aliases']])),
                           'status': status, 'identity_basis': 'user-confirmed' if status == 'ready' else 'user-input-pending',
                           'notes': [], 'default_variant': None}
                catalog['products'].append(product)
            else:
                product = next((p for p in catalog['products'] if p['id'] == decision.get('target')), None)
                if not product:
                    raise ValueError(f"{row['filename']}：请选择已有产品")
                if product['provider'] != meta['provider']:
                    raise ValueError(f"{row['filename']}：厂商与关联产品不一致，请更正厂商或选择其他产品")
                pid = product['id']
                # Associating a variant does not rename/reclassify an existing product.
                if status == 'ready':
                    product['aliases'] = list(dict.fromkeys(product['aliases'] + meta['aliases']))
            source_rel = f"sources/imports/web-{request_id}/{i + 1:02d}-{row['filename']}"
            writes[source_rel] = row['raw']
            writes[row['asset']['path']] = row['normalized']
            if source_rel not in source_paths:
                manifest['files'].append({'path': source_rel, 'sha256': sha(row['raw']), 'bytes': len(row['raw'])})
                source_paths.add(source_rel)
            origin = {'path': source_rel, 'entry': row['filename'], 'original_sha256': sha(row['raw'])}
            variant = next((v for v in catalog['variants'] if v['product_id'] == pid and v['asset']['sha256'] == row['asset']['sha256']), None)
            reused = variant is not None
            if variant is None:
                variant = {'id': pid + '@web-' + row['asset']['sha256'][:16], 'product_id': pid,
                           'style': meta['style'], 'status': status, 'asset': row['asset'], 'origins': [],
                           'priority': 10, 'theme': {'preserve_colors': True, 'dark_backdrop': False}, 'optical_scale': 1.0}
                catalog['variants'].append(variant)
            if origin not in variant['origins']:
                variant['origins'].append(origin)
            if status == 'ready':
                variant['status'] = 'ready'
                product['status'] = 'ready'
                product['identity_basis'] = 'user-confirmed'
                if not product.get('default_variant'):
                    product['default_variant'] = variant['id']
            if make_default:
                if pid in default_requests and default_requests[pid] != variant['id']:
                    raise ValueError('同一产品只能选择一个默认图标，请更正：' + product['name'])
                default_requests[pid] = variant['id']
                prefs['defaults'][pid] = variant['id']
            note = '浏览页导入 · ' + source_name + (' · 来源：' + meta['source'] if meta['source'] else '') + (' · ' + meta['note'] if meta['note'] else '')
            if note not in product['notes']:
                product['notes'].append(note)
            result.append({'filename': row['filename'], 'product_id': pid, 'variant_id': variant['id'],
                           'action': 'reused' if reused else ('created' if action == 'new' else 'variant_added'),
                           'status': variant['status'], 'default_changed': make_default, 'metadata': meta})
        if all(r['action'] == 'skipped' for r in result):
            raise ValueError('至少保留一个有效 SVG 后再导入')
        schema = read_json(self.root / 'catalog/schema.json')
        errors = check_schema(catalog, schema) if schema else []
        if errors:
            raise ValueError('索引校验失败：' + '; '.join(errors[:3]))
        # Validate every decision before writing. Restore the prior files if save/validation fails.
        tracked = ['catalog/index.json', 'catalog/preferences.json', 'catalog/sources.json',
                   'catalog/review-queue.json', 'previews/data.js', 'reports/duplicates.json', 'reports/validation.json',
                   str(receipt_path.relative_to(self.root))]
        backups = {rel: (self.root / rel).read_bytes() if (self.root / rel).exists() else None for rel in tracked}
        created = []
        try:
            for rel, raw in writes.items():
                path = safe_path(rel, self.root)
                if path.exists():
                    if path.read_bytes() != raw:
                        raise ValueError('拒绝覆盖已有素材：' + rel)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    created.append(path)
                    path.write_bytes(raw)
            for name, value in [('index', catalog), ('preferences', prefs), ('sources', manifest)]:
                write_json(self.root / 'catalog' / (name + '.json'), value)
            write_json(self.root / 'catalog/review-queue.json', review_queue(catalog))
            from iconlib import validate
            validation = validate(root=self.root)
            if not validation['ok']:
                raise ValueError('入库校验失败：' + '; '.join(validation['errors'][:3]))
            from build_preview import build
            build(root=self.root)
            write_json(self.root / 'reports/validation.json', validation)
            response = {'items': result, 'ok': True}
            write_json(receipt_path, {'payload_hash': payload_hash, 'result': response, 'source_name': source_name})
            return response
        except Exception:
            for rel, raw in backups.items():
                path = self.root / rel
                if raw is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(raw)
            for path in created:
                path.unlink(missing_ok=True)
            raise
