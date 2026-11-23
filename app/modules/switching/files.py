import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter_ns
from app.digests import digest, encode, fingerprints
from app.problems import Rejection
from app.settings import VERSION
from .service import analyze

SWITCH_VERSION = 'venue-switch/1'


class SwitchArchive:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def read(self, key):
        if not re.fullmatch('[0-9a-f]{64}', key):
            raise Rejection('NO_SWITCH', '切轨档案不存在', 404)
        try:
            return json.loads((self.root / f'{key}.json').read_bytes())
        except FileNotFoundError as error:
            raise Rejection('NO_SWITCH', '切轨档案不存在', 404) from error

    def publish(self, key, record):
        with NamedTemporaryFile(dir=self.root, prefix='.draft-', delete=False) as draft:
            path = Path(draft.name)
            try:
                draft.write(encode(record))
                draft.flush()
                os.fsync(draft.fileno())
                try:
                    os.link(path, self.root / f'{key}.json')
                except FileExistsError:
                    return self.read(key), True
                descriptor = os.open(self.root, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                path.unlink(missing_ok=True)
        return record, False

    def inventory(self):
        stamps = [self.read(file.stem)['manifest'] for file in self.root.glob('*.json')
                  if re.fullmatch('[0-9a-f]{64}', file.stem)]
        return sorted(stamps, key=lambda row: (row['created_at'], row['id']), reverse=True)


def record(store, material, requests):
    """同一切轨请求（原件散列 + 请求内容）重试得到同一档号，不新增档案。"""
    start = perf_counter_ns()
    hashes = fingerprints(material)
    result = analyze(material, requests)
    key = digest(encode([SWITCH_VERSION, hashes, requests]))
    result_hash = digest(encode(result))
    manifest = dict(id=key, version=SWITCH_VERSION, rule_version=VERSION,
                    input_sha256=hashes, request_sha256=digest(encode(requests)),
                    result_sha256=result_hash, requests=requests,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    elapsed_us=(perf_counter_ns() - start) // 1000)
    actual, reused = store.publish(key, dict(manifest=manifest, original=material, switch=result))
    if actual['manifest']['result_sha256'] != result_hash or digest(encode(actual['switch'])) != result_hash:
        raise Rejection('SWITCH_DRIFT', '复算与已归档切轨结果不一致', 409)
    return dict(id=actual['manifest']['id'], manifest=actual['manifest'], counts=result['counts'],
                balanced=result['balanced'], reused=reused)
