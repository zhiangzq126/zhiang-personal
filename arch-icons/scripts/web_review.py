"""Review existing pending products/variants without re-uploading their SVGs."""
import copy
import json
import re
from pathlib import Path

from library import ROOT, check_schema, norm, read_json, review_queue, safe_path, sha, write_json
from web_import import ImportService, KINDS, text


class ReviewService:
    def __init__(self, root=ROOT):
        self.root = Path(root)

    @staticmethod
    def candidates(product, variants, catalog):
        ids = {}
        for variant in variants:
            if variant['status'] != 'pending':
                continue
            row = {'metadata': product, 'asset': variant['asset']}
            for match in ImportService.matches(row, catalog):
                pid = match['product']['id']
                if pid == product['id']:
                    continue
                if pid not in ids:
                    ids[pid] = match
                else:
                    ids[pid]['reasons'] = sorted(set(ids[pid]['reasons'] + match['reasons']))
        return list(ids.values())

    def queue(self):
        catalog, prefs, _, revision = ImportService(self.root).state()
        queued = {p['product_id'] for p in review_queue(catalog)}
        items, targets = [], []
        for product in catalog['products']:
            variants = [v for v in catalog['variants'] if v['product_id'] == product['id']]
            if product['id'] in queued:
                items.append({'product': product, 'variants': variants,
                              'matches': self.candidates(product, variants, catalog)})
            if product['status'] == 'ready':
                default = prefs['defaults'].get(product['id'], product['default_variant'])
                targets.append({'product': product, 'variant': next((v for v in variants if v['id'] == default), None)})
        return {'revision': revision, 'items': items, 'targets': targets}

    @staticmethod
    def deletion_impact(catalog, pid, selected):
        variants = [v for v in catalog['variants'] if v['product_id'] == pid]
        pending = {v['id']: v for v in variants if v['status'] == 'pending'}
        if not isinstance(selected, list) or not selected or any(not isinstance(v, str) for v in selected) or len(set(selected)) != len(selected) or any(v not in pending for v in selected):
            raise ValueError('请仅勾选当前条目中需要清理的待确认图形')
        removed = [pending[v] for v in selected]
        remaining = [v for v in catalog['variants'] if v['id'] not in selected]
        referenced = {v['asset']['path'] for v in remaining}
        assets = {v['asset']['path']: v['asset'] for v in removed}
        return {'variant_ids': selected, 'variant_count': len(selected),
                'remove_product': not any(v['product_id'] == pid for v in remaining),
                'cleanup_assets': [a for path, a in assets.items() if path not in referenced],
                'shared_assets': [a for path, a in assets.items() if path in referenced],
                'original_sources_preserved': True}

    def delete_plan(self, payload):
        catalog, _, _, revision = ImportService(self.root).state()
        if revision != payload.get('revision'):
            raise ValueError('图标库或默认偏好已更新，请刷新审核列表后重试')
        product = next((p for p in catalog['products'] if p['id'] == payload.get('product_id')), None)
        if not product:
            raise ValueError('条目已不存在，请刷新审核列表')
        return {'product_name': product['name'], 'revision': revision,
                **self.deletion_impact(catalog, product['id'], payload.get('variant_ids'))}

    def commit(self, payload):
        request_id = payload.get('request_id', '')
        if not isinstance(request_id, str) or not re.fullmatch('[a-zA-Z0-9-]{16,80}', request_id):
            raise ValueError('无效审核请求，请刷新审核列表')
        fingerprint = sha(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode())
        receipt_path = self.root / 'reports/web-reviews' / (request_id + '.json')
        receipt = read_json(receipt_path)
        if receipt:
            if receipt['fingerprint'] != fingerprint:
                raise ValueError('请求内容已变更，请重新提交')
            return receipt['result']
        catalog, prefs, _, revision = ImportService(self.root).state()
        if revision != payload.get('revision'):
            raise ValueError('图标库或默认偏好已更新，请刷新审核列表后重试')
        catalog = copy.deepcopy(catalog)
        pid = payload.get('product_id')
        product = next((p for p in catalog['products'] if p['id'] == pid), None)
        variants = [v for v in catalog['variants'] if v['product_id'] == pid]
        pending = {v['id']: v for v in variants if v['status'] == 'pending'}
        if not product or not pending:
            raise ValueError('该条目已没有待审核图标，请刷新列表')
        action = payload.get('action')
        if action not in ('approve', 'save', 'link', 'delete'):
            raise ValueError('请选择有效的审核操作')
        selected = payload.get('variant_ids', [])
        if not isinstance(selected, list) or any(not isinstance(v, str) for v in selected) or len(set(selected)) != len(selected) or any(v not in pending for v in selected):
            raise ValueError('只能审核当前条目的待确认变体')
        if action != 'save' and not selected:
            raise ValueError('请至少勾选一个已核实的图标')
        note = text(payload.get('note', ''), '审核依据或备注', 2000, action != 'save')
        chosen = payload.get('default_variant', '')
        if not isinstance(chosen, str) or (chosen and (chosen not in selected or action in ('save', 'delete'))):
            raise ValueError('默认图标必须是本次确认的变体')
        before = {'products': copy.deepcopy([product]), 'variants': copy.deepcopy(variants), 'preferences': copy.deepcopy(prefs)}
        old_pending = product['status'] == 'pending'
        styles = payload.get('styles', {})
        if not isinstance(styles, dict) or any(vid not in pending for vid in styles):
            raise ValueError('变体说明只能修改当前待确认图标')
        if action != 'delete':
            for vid, style in styles.items():
                pending[vid]['style'] = text(style, '变体说明', 100, True)
        id_map = {}
        deletion = None
        if action == 'delete':
            if payload.get('delete_confirmed') is not True:
                raise ValueError('请先核对删除范围，再确认清理')
            deletion = self.deletion_impact(catalog, pid, selected)
            catalog['variants'] = [v for v in catalog['variants'] if v['id'] not in selected]
            if deletion['remove_product']:
                catalog['products'].remove(product)
                prefs['defaults'].pop(pid, None)
            else:
                product['notes'].append('审核清理：移除 ' + str(len(selected)) + ' 个有误图形；' + note)
            result_id = pid
        elif action == 'link':
            target_id = payload.get('target_id')
            target = next((p for p in catalog['products'] if p['id'] == target_id and p['status'] == 'ready'), None)
            if not target or target_id == pid:
                raise ValueError('请选择另一个已确认产品作为关联目标')
            target_variants = [v for v in catalog['variants'] if v['product_id'] == target_id]
            before['products'].append(copy.deepcopy(target))
            before['variants'] += copy.deepcopy(target_variants)
            for old_id in selected:
                variant = pending[old_id]
                same = next((v for v in target_variants if v['asset']['sha256'] == variant['asset']['sha256']), None)
                if same:
                    for origin in variant['origins']:
                        if origin not in same['origins']:
                            same['origins'].append(origin)
                    same['status'] = 'ready'
                    catalog['variants'].remove(variant)
                    id_map[old_id] = same['id']
                else:
                    variant['product_id'] = target_id
                    variant['id'] = target_id + '@review-' + sha(old_id.encode())[:16]
                    variant['status'] = 'ready'
                    target_variants.append(variant)
                    id_map[old_id] = variant['id']
            remaining = [v for v in catalog['variants'] if v['product_id'] == pid]
            if not remaining:
                catalog['products'].remove(product)
                prefs['defaults'].pop(pid, None)
            target['notes'].append('人工审核关联：' + product['name'] + '；' + note)
            if chosen:
                prefs['defaults'][target_id] = id_map[chosen]
            result_id = target_id
        else:
            meta = payload.get('metadata', {})
            if not isinstance(meta, dict):
                raise ValueError('条目信息格式错误')
            if old_pending:
                name = text(meta.get('name', product['name']), '产品名称', 200, True)
                provider = text(meta.get('provider', product['provider']), '厂商标识', 60, True)
                if not re.fullmatch('[a-z][a-z0-9-]*', provider):
                    raise ValueError('厂商标识应为小写英文、数字和连字符，以字母开头')
                category = text(meta.get('category', product['category']), '分类', 100, True)
                kind = meta.get('kind', product['kind'])
                if kind not in KINDS:
                    raise ValueError('用途不正确')
                aliases = meta.get('aliases', product['aliases'])
                if not isinstance(aliases, list) or len(aliases) > 30:
                    raise ValueError('别名最多 30 个')
                aliases = list(dict.fromkeys(text(a, '别名', 200, True) for a in aliases))
                product.update(name=name, provider=provider, category=category, kind=kind, aliases=aliases)
                if action == 'approve':
                    candidates = self.candidates(product, [pending[v] for v in selected], catalog)
                    if candidates and payload.get('distinct') is not True:
                        raise ValueError('存在同名或相同图形的条目，请关联已有产品，或明确确认是独立产品')
                new_id = provider + '/' + pid.split('/', 1)[1]
                if new_id != pid:
                    if any(p['id'] == new_id for p in catalog['products']):
                        raise ValueError('此厂商下已有相同 ID，请关联已有产品')
                    product['id'] = new_id
                    for variant in variants:
                        old_id = variant['id']
                        variant['product_id'] = new_id
                        variant['id'] = new_id + '@review-' + sha(old_id.encode())[:16]
                        id_map[old_id] = variant['id']
            elif meta:
                # Review of an additional variant cannot silently rewrite an already-ready identity.
                if any(meta.get(k, product[k]) != product[k] for k in ('name', 'provider', 'category', 'kind', 'aliases')):
                    raise ValueError('已有可用产品的身份保持不变；这里只审核新增变体')
            if action == 'approve':
                for vid in selected:
                    pending[vid]['status'] = 'ready'
                product['status'] = 'ready'
                product['identity_basis'] = 'user-confirmed'
                if not product.get('default_variant'):
                    product['default_variant'] = id_map.get(selected[0], selected[0])
                if chosen:
                    prefs['defaults'][product['id']] = id_map.get(chosen, chosen)
            if note:
                product['notes'].append(('人工确认：' if action == 'approve' else '待确认补充：') + note)
            result_id = product['id']
        errors = check_schema(catalog, read_json(self.root / 'catalog/schema.json'))
        if errors:
            raise ValueError('索引校验失败：' + '; '.join(errors[:3]))
        result = {'ok': True, 'action': action, 'product_id': result_id, 'previous_product_id': pid,
                  'approved_variants': len(selected) if action in ('approve', 'link') else 0, 'variant_id_map': id_map,
                  'remaining': len(review_queue(catalog))}
        if deletion:
            result.update(deleted_variants=len(selected), deletion=deletion,
                          recovery_path='trash/review-deletions/' + request_id)
        tracked = ['catalog/index.json', 'catalog/preferences.json', 'catalog/review-queue.json',
                   'previews/data.js', 'reports/duplicates.json', 'reports/validation.json',
                   str(receipt_path.relative_to(self.root))]
        backups = {rel: (self.root / rel).read_bytes() if (self.root / rel).exists() else None for rel in tracked}
        moved = []
        try:
            if deletion:
                for asset in deletion['cleanup_assets']:
                    rel = asset['path']
                    if not re.fullmatch(r'assets/[0-9a-f]{2}/[0-9a-f]{64}\.svg', rel):
                        raise ValueError('清理范围只能是规范 SVG 资产')
                    source = safe_path(rel, self.root)
                    raw = source.read_bytes()
                    if sha(raw) != asset['sha256']:
                        raise ValueError('素材已变化，停止清理：' + rel)
                    destination = safe_path(result['recovery_path'] + '/' + rel, self.root)
                    if destination.exists():
                        raise ValueError('回收路径已存在，停止清理：' + rel)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    moved.append((source, destination, raw))
                    destination.write_bytes(raw)
                    source.unlink()
            write_json(self.root / 'catalog/index.json', catalog)
            write_json(self.root / 'catalog/preferences.json', prefs)
            write_json(self.root / 'catalog/review-queue.json', review_queue(catalog))
            from iconlib import validate
            validation = validate(root=self.root)
            if not validation['ok']:
                raise ValueError('审核校验失败：' + '; '.join(validation['errors'][:3]))
            from build_preview import build
            build(root=self.root)
            write_json(self.root / 'reports/validation.json', validation)
            write_json(receipt_path, {'fingerprint': fingerprint, 'result': result, 'before': before,
                                     'decision': payload})
        except Exception:
            for source, destination, raw in reversed(moved):
                source.write_bytes(raw)
                destination.unlink(missing_ok=True)
            for rel, raw in backups.items():
                path = self.root / rel
                if raw is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(raw)
            raise
        return result
