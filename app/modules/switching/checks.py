from app.digests import digest, encode, fingerprints
from app.problems import Rejection


def verify(record):
    stamp = record['manifest']
    if fingerprints(record['original']) != stamp['input_sha256']:
        raise Rejection('INVALID_SWITCH_EVIDENCE', '切轨原件散列不符', 409)
    if digest(encode(record['switch'])) != stamp['result_sha256']:
        raise Rejection('INVALID_SWITCH_EVIDENCE', '切轨结果散列不符', 409)
    if digest(encode(stamp['requests'])) != stamp['request_sha256']:
        raise Rejection('INVALID_SWITCH_EVIDENCE', '切轨请求散列不符', 409)
    if not record['switch']['balanced']:
        raise Rejection('INVALID_SWITCH_EVIDENCE', '切轨覆盖勾稽不符', 409)
    return stamp
