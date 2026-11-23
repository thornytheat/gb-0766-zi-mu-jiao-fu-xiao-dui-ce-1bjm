from app.pipeline import inspect
from app.problems import Rejection
from .ledger import build, merge_batches
from .locate import resolve


def parse_request(body):
    if not isinstance(body, dict):
        raise Rejection('SWITCH_PAYLOAD', '提交切轨请求 JSON', 422)
    raw = body.get('requests') if 'requests' in body else [body]
    if not isinstance(raw, list) or not raw:
        raise Rejection('SWITCH_PAYLOAD', '切轨请求至少包含一条', 422)
    requests = []
    for item in raw:
        if not isinstance(item, dict):
            raise Rejection('SWITCH_PAYLOAD', '切轨请求字段缺失', 422)
        frame = item.get('frame')
        if not isinstance(frame, int) or isinstance(frame, bool) or frame < 0:
            raise Rejection('SWITCH_FRAME', '切轨帧必须是非负整数', 422)
        from_track, to_track = item.get('from_track'), item.get('to_track')
        if not isinstance(from_track, str) or not isinstance(to_track, str) or from_track == to_track:
            raise Rejection('SWITCH_TRACK', '切轨请求需指定两条不同轨道', 422)
        requests.append(dict(frame=frame, from_track=from_track, to_track=to_track))
    return requests


def analyze(material, requests):
    stages = inspect(material)
    clock_rows, fragments, edits = stages['clock']['rows'], stages['edits']['rows'], stages['edits']['cuts']
    try:
        if len(requests) == 1:
            decision = resolve(edits, clock_rows, fragments, requests[0])
            result = build(clock_rows, fragments, edits, requests[0], decision)
        else:
            result = merge_batches(clock_rows, fragments, edits, requests)
    except ValueError as error:
        codes = {'OUT_OF_RANGE': ('SWITCH_OUT_OF_RANGE', '切轨帧超出公映版交付范围', 422),
                 'NO_KEEP': ('SWITCH_NO_KEEP', '切版没有 KEEP 段可供切轨', 422),
                 'UNKNOWN_TRACK': ('SWITCH_TRACK', '切轨请求引用了不存在的轨道', 422),
                 'NO_DELIVERED_FRAME': ('SWITCH_NO_EVIDENCE', '原句没有任何交付帧，无法定切轨点', 422)}
        code, text, status = codes.get(str(error), ('SWITCH_FAILED', '切轨计算失败', 422))
        raise Rejection(code, text, status) from error
    result['stages_ref'] = {name: stages[name]['counts'] for name in
                            ('source', 'clock', 'edits', 'overlaps', 'balance')}
    return result
