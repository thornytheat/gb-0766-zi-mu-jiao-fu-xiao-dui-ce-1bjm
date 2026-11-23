from flask import Blueprint, current_app, jsonify, render_template, request
from .grid_view import HEADERS, LABELS, cells
from .material import example, material
from .modules.delivery.checks import verify
from .modules.delivery.service import CODES
from .modules.runs.routes import archive
from .modules.switching.checks import verify as verify_switch
from .modules.switching.ledger import CODES as SWITCH_CODES
from .modules.switching.service import analyze
from .pipeline import inspect
from .problems import Rejection

sheets = Blueprint('sheets', __name__)
TABS = {'source': '文件采信', 'clock': '帧率校核', 'edits': '切版映射', 'overlaps': '冲突定位',
        'balance': '覆盖对账', 'runs': '版本归档', 'delivery': '交付签发', 'switching': '双语切轨'}
DEFAULT_SWITCH = dict(frame=350, from_track='简中', to_track='英语')


def current_switch_store():
    return current_app.extensions['switch_archive']


def current():
    key = request.args.get('run')
    name = request.args.get('sample', 'dirty')
    if key:
        entry = archive().read(key)
        return entry['stages'], entry['manifest'], name
    return inspect(example(name)), None, name


@sheets.get('/api/check/<sheet>')
def data(sheet):
    if sheet not in tuple(TABS)[:5]:
        raise Rejection('NO_SHEET', '未找到校对页', 404)
    key = request.args.get('run')
    if key:
        return jsonify(archive().read(key)['stages'][sheet])
    return jsonify(inspect(example(request.args.get('sample', 'dirty')), until=sheet))


@sheets.post('/api/check/<sheet>')
def check_originals(sheet):
    if sheet not in tuple(TABS)[:5]:
        raise Rejection('NO_SHEET', '未找到校对页', 404)
    return jsonify(inspect(material(request.get_json(silent=True)), until=sheet))


@sheets.get('/', defaults={'sheet': 'edits'})
@sheets.get('/sheet/<sheet>')
def grid(sheet):
    if sheet not in TABS:
        raise Rejection('NO_SHEET', '未找到校对页', 404)
    if sheet == 'switching':
        return switching_page()
    stages, manifest, sample = current()
    if sheet == 'delivery' and manifest:
        verify(archive().read(manifest['id']))
    return render_template('workbook.html', sheet=sheet, tabs=TABS, sample=sample, manifest=manifest,
                           totals=stages['balance']['counts'], rows=cells(stages, sheet, archive(), manifest),
                           columns=HEADERS[sheet], labels=LABELS, codes=CODES)


def switching_page():
    switch_key = request.args.get('switch')
    sample = request.args.get('sample', 'bilingual')
    if switch_key:
        entry = current_switch_store().read(switch_key)
        verify_switch(entry)
        result, stamp = entry['switch'], entry['manifest']
    else:
        try:
            result = analyze(example(sample), [DEFAULT_SWITCH])
        except Rejection:
            # 当前样例不含默认切轨轨道时，给出空结果而非整页失败
            result = _empty_switch()
        stamp = None
    return render_template('switching.html', sheet='switching', tabs=TABS, sample=sample, manifest=stamp,
                           result=result, default_switch=DEFAULT_SWITCH,
                           columns=HEADERS['switching'], labels=LABELS, codes=SWITCH_CODES)


def _empty_switch():
    return dict(decision=dict(requested_frame=DEFAULT_SWITCH['frame'], actual_frame=None, rule='—',
                              segment=dict(cut='—', cut_line='—', kind='—', source_point='—', target_anchor='—'),
                              gap=None, active_cues=[]),
                rows=[], ledgers=[], replays=[],
                counts=dict(missed=0, abandoned=0, straddled=0, replayed=0, replay_regions=0, delayed=0),
                balanced=True)
