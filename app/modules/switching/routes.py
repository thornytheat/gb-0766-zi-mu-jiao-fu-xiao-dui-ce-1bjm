from flask import Blueprint, current_app, jsonify, request
from app.material import material
from app.problems import Rejection
from .checks import verify
from .files import SwitchArchive, record
from .service import analyze, parse_request

switching = Blueprint('switching', __name__, url_prefix='/api/switch')


def store():
    return current_app.extensions['switch_archive']


@switching.get('/runs')
def index():
    stamps = store().inventory()
    return jsonify(count=len(stamps), rows=stamps)


@switching.post('/preview')
def preview():
    body = request.get_json(silent=True)
    requests = parse_request(body)
    return jsonify(analyze(_material_of(body), requests))


@switching.post('/runs')
def publish():
    body = request.get_json(silent=True)
    requests = parse_request(body)
    return jsonify(record(store(), _material_of(body), requests))


@switching.get('/runs/<key>')
def detail(key):
    entry = store().read(key)
    return jsonify(manifest=entry['manifest'], counts=entry['switch']['counts'],
                   balanced=entry['switch']['balanced'])


@switching.post('/runs/<key>/repeat')
def repeat(key):
    entry = store().read(key)
    return jsonify(record(store(), entry['original'], entry['manifest']['requests']))


@switching.get('/runs/<key>/export')
def export(key):
    entry = store().read(key)
    verify(entry)
    response = jsonify(dict(verified=True, certificate=entry['manifest'], **entry))
    response.headers['Content-Disposition'] = f'attachment; filename="track-switch-{key}.json"'
    return response


def _material_of(body):
    if isinstance(body, dict) and 'sample' in body:
        return material({'sample': body['sample']})
    if isinstance(body, dict) and {'cues', 'cuts'} <= set(body):
        return material({'cues': body['cues'], 'cuts': body['cuts']})
    raise Rejection('PAYLOAD', '提交字幕和切版 CSV，或指定样例', 422)
