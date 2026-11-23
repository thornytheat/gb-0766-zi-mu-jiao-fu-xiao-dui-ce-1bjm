import pytest
from app.material import example
from app.modules.switching.checks import verify
from app.modules.switching.files import SwitchArchive, record
from app.modules.switching.ledger import build, integer_union
from app.modules.switching.locate import resolve, reverse_locate
from app.modules.switching.service import analyze, parse_request
from app.pipeline import inspect
from app.problems import Rejection

REQUEST = dict(frame=350, from_track='简中', to_track='英语')


@pytest.fixture
def bilingual():
    return inspect(example('bilingual'))


@pytest.fixture
def saved_switch(client):
    return client.post('/api/switch/runs', json={'sample': 'bilingual', **REQUEST}).json


# ---- 定位与取舍规则 ----

def test_mid_sentence_request_defers_to_cue_end(bilingual):
    decision = resolve(bilingual['edits']['cuts'], bilingual['clock']['rows'],
                       bilingual['edits']['rows'], REQUEST)
    assert decision['requested_frame'] == 350
    assert decision['actual_frame'] == 401
    assert decision['rule'] == 'SWITCH_DEFER_CUE_END'
    assert decision['active_cues'] == [
        dict(cue_id='Z2', line=3, source_start='400', source_end='600', deferred_to_frame=401)]
    assert decision['segment']['cut'] == 'B-01'


def test_decision_keeps_source_line_evidence(bilingual):
    decision = resolve(bilingual['edits']['cuts'], bilingual['clock']['rows'],
                       bilingual['edits']['rows'], REQUEST)
    assert decision['segment']['cut_line'] == 4
    assert decision['active_cues'][0]['line'] == 3


def test_request_at_sentence_boundary_switches_immediately(bilingual):
    # 帧 401 是 Z2 的交付末帧；半开区间 [start,end) 下没有原句跨过该点
    decision = resolve(bilingual['edits']['cuts'], bilingual['clock']['rows'],
                       bilingual['edits']['rows'], dict(REQUEST, frame=401))
    assert decision['actual_frame'] == 401 and decision['rule'] == 'SWITCH_IMMEDIATE'
    assert decision['active_cues'] == []


def test_gap_frame_advances_to_next_keep_anchor():
    cuts_text = ('cut,start,end,target,kind\n'
                 'A,0,100,0,KEEP\n'          # 交付 [0, 81)
                 'B,300,400,500,KEEP\n')     # 交付 [500, 581)，目标待证 [81,500)
    cues_text = ('cue_id,track,format,in,out,text\n'
                 'Z1,简中,FRAME,20,60,原句\n'
                 'E1,英语,FRAME,320,360,translation\n')
    material = dict(cues=cues_text, cuts=cuts_text)
    result = analyze(material, [dict(frame=100, from_track='简中', to_track='英语')])
    decision = result['decision']
    assert decision['actual_frame'] == 500
    assert decision['gap'] == dict(gap_from=81, gap_to=500, advance_to=500)
    assert decision['rule'].startswith('SWITCH_GAP')


def test_out_of_range_frame_rejected():
    with pytest.raises(Rejection) as error:
        analyze(example('bilingual'), [dict(frame=99999, from_track='简中', to_track='英语')])
    assert error.value.code == 'SWITCH_OUT_OF_RANGE'


def test_unknown_track_rejected():
    with pytest.raises(Rejection) as error:
        analyze(example('bilingual'), [dict(frame=100, from_track='简中', to_track='火星语')])
    assert error.value.code == 'SWITCH_TRACK'


def test_bad_request_shapes(client):
    assert client.post('/api/switch/preview', json={'frame': -1, 'from_track': 'a',
                                                    'to_track': 'b'}).status_code == 422
    assert client.post('/api/switch/preview', json={'frame': 5, 'from_track': 'a',
                                                    'to_track': 'a'}).json['code'] == 'SWITCH_TRACK'
    assert client.post('/api/switch/preview', json={'requests': []}).status_code == 422


# ---- 覆盖对账：漏播、重播、弃用与守恒 ----

def test_ledger_decisions_and_counts(bilingual):
    result = analyze(example('bilingual'), [REQUEST])
    statuses = {(row['cue_id'], row['status']) for row in result['rows']}
    assert statuses == {
        ('Z1', 'PLAYED_BEFORE'), ('Z2', 'PLAYED_BEFORE'),
        ('Z3', 'ABANDONED'), ('Z4', 'ABANDONED'),
        ('E1', 'MISSED'), ('E2', 'MISSED'),
        ('E3', 'PLAYED_AFTER'), ('E4', 'PLAYED_AFTER'), ('E5', 'PLAYED_AFTER')}
    assert result['counts'] == dict(missed=160, abandoned=200, straddled=0, replayed=40,
                                    replay_regions=1, delayed=1)


def test_ledger_conservation_half_open(bilingual):
    result = analyze(example('bilingual'), [REQUEST])
    for ledger in result['ledgers']:
        assert ledger['before_switch'] + ledger['after_switch'] == ledger['union_frames']
        assert ledger['balanced'] and ledger['difference'] == 0
    assert result['balanced']


def test_replay_region_uses_half_open_union(bilingual):
    # E3 [442,602) 与 E4 [562,682) 重叠 [562,602) = 40 帧，深度>=2 每帧只计一次
    replay, = result_replays(analyze(example('bilingual'), [REQUEST]))
    assert (replay['frame_in'], replay['frame_out'], replay['frames']) == (562, 602, 40)
    assert replay['cues'] == ['E3', 'E4']


def result_replays(result):
    return result['replays']


def test_touching_intervals_are_not_replay():
    assert integer_union([(0, 10), (10, 20)]) == 20


def test_target_cue_straddling_switch_is_split():
    # 切点 40 落在译文 E2 目标区间 [33,49) 中间：前段 7 帧漏播，后段 9 帧保留
    cues_text = ('cue_id,track,format,in,out,text\n'
                 'Z1,简中,FRAME,10,30,原句一\n'
                 'Z2,简中,FRAME,60,90,原句二\n'
                 'E1,英语,FRAME,10,30,first\n'
                 'E2,英语,FRAME,40,60,second\n')
    cuts_text = 'cut,start,end,target,kind\nA,0,200,0,KEEP\n'
    result = analyze(dict(cues=cues_text, cuts=cuts_text),
                     [dict(frame=40, from_track='简中', to_track='英语')])
    row = next(row for row in result['rows'] if row['cue_id'] == 'E2')
    assert row['status'] == 'STRADDLED'
    assert (row['played_before'], row['played_after']) == (7, 9)
    assert result['counts']['straddled'] == 1 and result['counts']['missed'] >= 7
    assert all(ledger['balanced'] for ledger in result['ledgers'])


def test_overlapping_cues_force_fixed_point_deferral():
    # 两条原轨字幕重叠：顺延到第一条末帧时第二条仍在播，切点必须继续后移
    cues_text = ('cue_id,track,format,in,out,text\n'
                 'Z1,简中,FRAME,10,60,第一句\n'
                 'Z2,简中,FRAME,40,120,第二句\n'
                 'E1,英语,FRAME,10,120,translation\n')
    cuts_text = 'cut,start,end,target,kind\nA,0,200,0,KEEP\n'
    result = analyze(dict(cues=cues_text, cuts=cuts_text),
                     [dict(frame=40, from_track='简中', to_track='英语')])
    # 切点必须越过两条原句的末帧 120（目标帧 ceil(120*RATIO)=97）
    assert result['decision']['actual_frame'] == 97
    assert {cue['cue_id'] for cue in result['decision']['active_cues']} == {'Z1', 'Z2'}
    assert result['balanced']


# ---- 多请求批次 ----

def test_batch_requests_merged(bilingual):
    result = analyze(example('bilingual'), [
        REQUEST, dict(frame=500, from_track='简中', to_track='英语')])
    assert len(result['decisions']) == 2 and len(result['requests']) == 2
    # 取舍行按 轨道+字幕号+原行 去重
    keys = [(row['track'], row['cue_id'], row['line']) for row in result['rows']]
    assert len(keys) == len(set(keys))


def test_batch_replay_regions_deduped(bilingual):
    # 两个请求的切点都早于 E3/E4 重叠区，重播区只计一次、40 帧不翻倍
    result = analyze(example('bilingual'), [
        REQUEST, dict(frame=300, from_track='简中', to_track='英语')])
    assert result['counts']['replayed'] == 40
    assert result['counts']['replay_regions'] == 1
    assert len(result['replays']) == 1


# ---- 归档幂等：重试不新增档案 ----

def test_retry_same_request_reuses_archive(tmp_path):
    store = SwitchArchive(tmp_path)
    first = record(store, example('bilingual'), [REQUEST])
    second = record(store, example('bilingual'), [REQUEST])
    assert first['id'] == second['id'] and second['reused'] and not first['reused']
    assert len(tuple(tmp_path.glob('*.json'))) == 1


def test_different_request_creates_new_archive(tmp_path):
    store = SwitchArchive(tmp_path)
    first = record(store, example('bilingual'), [REQUEST])
    second = record(store, example('bilingual'), [dict(REQUEST, frame=500)])
    assert first['id'] != second['id']
    assert len(tuple(tmp_path.glob('*.json'))) == 2


def test_different_material_creates_new_archive(tmp_path):
    store = SwitchArchive(tmp_path)
    first = record(store, example('bilingual'), [REQUEST])
    second = record(store, example('clean'),
                    [dict(frame=50, from_track='简中', to_track='英语')])
    assert first['id'] != second['id']


# ---- 签发证据：散列、取舍与原行依据 ----

def test_signed_export_passes_verification(tmp_path):
    store = SwitchArchive(tmp_path)
    saved = record(store, example('bilingual'), [REQUEST])
    entry = store.read(saved['id'])
    stamp = verify(entry)
    assert stamp['id'] == saved['id']
    # 证据中能查到取舍规则与原行依据
    assert entry['switch']['decision']['rule'] == 'SWITCH_DEFER_CUE_END'
    assert entry['switch']['decision']['active_cues'][0]['line'] == 3


def test_tampered_result_fails_verification(tmp_path):
    store = SwitchArchive(tmp_path)
    saved = record(store, example('bilingual'), [REQUEST])
    entry = store.read(saved['id'])
    entry['switch']['counts']['missed'] = 0
    with pytest.raises(Rejection, match='切轨结果散列不符'):
        verify(entry)


def test_tampered_request_fails_verification(tmp_path):
    store = SwitchArchive(tmp_path)
    saved = record(store, example('bilingual'), [REQUEST])
    entry = store.read(saved['id'])
    entry['manifest']['requests'][0]['frame'] = 1
    with pytest.raises(Rejection, match='切轨请求散列不符'):
        verify(entry)


# ---- HTTP 路由 ----

def test_preview_endpoint(client):
    response = client.post('/api/switch/preview', json={'sample': 'bilingual', **REQUEST})
    assert response.status_code == 200
    assert response.json['decision']['actual_frame'] == 401
    # 预览不落盘
    assert client.get('/api/switch/runs').json['count'] == 0


def test_publish_and_repeat_endpoints(client, saved_switch):
    key = saved_switch['id']
    assert not saved_switch['reused']
    repeat = client.post(f'/api/switch/runs/{key}/repeat').json
    assert repeat['reused'] and repeat['manifest'] == saved_switch['manifest']
    assert client.get('/api/switch/runs').json['count'] == 1


def test_export_endpoint(client, saved_switch):
    response = client.get(f"/api/switch/runs/{saved_switch['id']}/export")
    assert response.status_code == 200 and 'attachment;' in response.headers['Content-Disposition']
    assert response.json['verified']
    assert response.json['switch']['decision']['actual_frame'] == 401


def test_unknown_switch_record(client):
    assert client.get('/api/switch/runs/nope/export').json['code'] == 'NO_SWITCH'


def test_switching_web_tab(client):
    html = client.get('/sheet/switching').get_data(as_text=True)
    assert '双语试映切轨对账' in html and '实际切轨定位' in html
    assert 'SWITCH_DEFER_CUE_END' in html and '覆盖对账' in html


def test_switching_tab_uses_own_archive(client, saved_switch):
    # 切轨档案与主交付档案互不干扰
    assert client.get('/api/runs').json['count'] == 0
    html = client.get(f"/sheet/switching?switch={saved_switch['id']}").get_data(as_text=True)
    assert '下载切轨证据' in html
