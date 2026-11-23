from app.modules.overlaps.sweep import spans

# 取舍原因码：切轨请求相对原句实际出帧的处置
STATUS = {
    'PLAYED_BEFORE': '切轨前完整播完',
    'ABANDONED': '原句未播完，随切轨弃用',
    'MISSED': '译文在切轨前开播，整句漏播',
    'STRADDLED': '译文跨过切点，前段漏播后段保留',
    'PLAYED_AFTER': '切轨后完整播放',
}
CODES = {
    'MISSED': '漏播：译文先于切轨开播',
    'STRADDLED': '截断：译文跨切点，仅保留切后段',
    'REPLAY': '重播：同帧被两条译文覆盖',
    'ABANDONED': '弃用：原句在切轨点截断',
    'OVERLAP': '同轨目标帧相交',
}


def integer_union(intervals):
    """整数半开帧区间 [lo, hi) 的并集长度，复用扫线保证首尾相接不重复。"""
    normalized = [(item[0], item[1], index) for index, item in enumerate(intervals)]
    return sum(right - left for left, right, _ in spans(normalized))


def split_cue(fragments, track, cue_id, cut_frame):
    """把一条字幕的 KEEP 交付片段在切轨帧处切成前、后两段（半开，无重叠无缺口）。"""
    before, after = [], []
    for row in fragments:
        if row['track'] != track or row['cue_id'] != cue_id or row['kind'] != 'KEEP':
            continue
        lo, hi = row['frame_in'], row['frame_out']
        if hi <= cut_frame:
            before.append((lo, hi))
        elif lo >= cut_frame:
            after.append((lo, hi))
        else:
            before.append((lo, cut_frame))
            after.append((cut_frame, hi))
    return before, after


def cue_span(fragments, track, cue_id):
    intervals = [(row['frame_in'], row['frame_out'], index)
                 for index, row in enumerate(fragments)
                 if row['track'] == track and row['cue_id'] == cue_id and row['kind'] == 'KEEP']
    return integer_union(intervals)


def decide(track_cues, fragments, track, actual_frame, side):
    """side='from' 给原轨行取舍，side='to' 给译轨行取舍。"""
    rows = []
    for cue in track_cues:
        before, after = split_cue(fragments, track, cue['cue_id'], actual_frame)
        played_before, played_after = integer_union(before), integer_union(after)
        total = cue_span(fragments, track, cue['cue_id'])
        if side == 'from':
            status = 'PLAYED_BEFORE' if played_after == 0 else 'ABANDONED'
        elif played_before and played_after:
            status = 'STRADDLED'
        elif played_before:
            status = 'MISSED'
        else:
            status = 'PLAYED_AFTER'
        rows.append(dict(track=track, cue_id=cue['cue_id'], line=cue['line'], text=cue['text'],
                         frame_in=min((lo for lo, _ in before + after), default=None),
                         frame_out=max((hi for _, hi in before + after), default=None),
                         played_before=played_before, played_after=played_after, total_frames=total,
                         status=status, reason_codes=list_status_codes(status)))
    return rows


def list_status_codes(status):
    if status == 'ABANDONED':
        return ['ABANDONED']
    if status == 'MISSED':
        return ['MISSED']
    if status == 'STRADDLED':
        return ['MISSED']
    return []


def replay_regions(fragments, to_track, actual_frame):
    """译轨切轨后的同轨重叠帧：深度 >=2 的每帧只计一次（独立记录重播）。"""
    intervals = [(row['frame_in'], row['frame_out'], (row['line'], row['cue_id']))
                 for row in fragments
                 if row['track'] == to_track and row['kind'] == 'KEEP' and row['frame_in'] >= actual_frame]
    regions = []
    for left, right, active in spans(intervals):
        if len(active) > 1:
            regions.append(dict(track=to_track, frame_in=left, frame_out=right, frames=right - left,
                                lines=[token[0] for token in active], cues=[token[1] for token in active],
                                code='OVERLAP'))
    return regions


def build(clock_rows, fragments, edits, request, decision):
    actual = decision['actual_frame']
    tracks = sorted({row['track'] for row in clock_rows})
    if request['from_track'] not in tracks or request['to_track'] not in tracks:
        raise ValueError('UNKNOWN_TRACK')
    from_cues = [cue for cue in clock_rows if cue['track'] == request['from_track']]
    to_cues = [cue for cue in clock_rows if cue['track'] == request['to_track']]
    decisions = decide(from_cues, fragments, request['from_track'], actual, 'from')
    decisions += decide(to_cues, fragments, request['to_track'], actual, 'to')

    ledgers = []
    for track, cues in ((request['from_track'], from_cues), (request['to_track'], to_cues)):
        kept_intervals = [(row['frame_in'], row['frame_out'], index)
                          for index, row in enumerate(fragments)
                          if row['track'] == track and row['kind'] == 'KEEP']
        union_total = integer_union(kept_intervals)
        before = integer_union([(lo, hi, 0) for cue in cues
                                for lo, hi in split_cue(fragments, track, cue['cue_id'], actual)[0]])
        after = integer_union([(lo, hi, 0) for cue in cues
                               for lo, hi in split_cue(fragments, track, cue['cue_id'], actual)[1]])
        ledgers.append(dict(track=track, side='from' if track == request['from_track'] else 'to',
                            union_frames=union_total, before_switch=before, after_switch=after,
                            balanced=before + after == union_total,
                            difference=union_total - before - after))
    replays = replay_regions(fragments, request['to_track'], actual)
    missed_rows = {'MISSED', 'STRADDLED'}
    counts = dict(missed=sum(row['played_before'] for row in decisions if row['status'] in missed_rows),
                  abandoned=sum(row['played_after'] for row in decisions if row['status'] == 'ABANDONED'),
                  straddled=sum(1 for row in decisions if row['status'] == 'STRADDLED'),
                  replayed=sum(row['frames'] for row in replays),
                  replay_regions=len(replays),
                  delayed=len(decision['active_cues']))
    return dict(decision=decision, requests=[request], rows=decisions, ledgers=ledgers,
                replays=replays, counts=counts,
                balanced=all(row['balanced'] for row in ledgers))


def merge_batches(clock_rows, fragments, edits, requests):
    """同一校对册上的多请求：逐条求切点，合并取舍行与覆盖账。"""
    from .locate import resolve
    decisions, all_rows, replay_acc, ledger_acc = [], [], {}, {}
    for request in requests:
        decision = resolve(edits, clock_rows, fragments, request)
        batch = build(clock_rows, fragments, edits, request, decision)
        decisions.append(decision)
        all_rows.extend(batch['rows'])
        for region in batch['replays']:
            # 同轨同区间在多请求下只保留一条，重播帧按并集计每帧一次
            replay_acc[(region['track'], region['frame_in'], region['frame_out'])] = region
        for ledger in batch['ledgers']:
            ledger_acc.setdefault(ledger['track'], ledger)
    dedup = {(row['track'], row['cue_id'], row['line']): row for row in all_rows}
    all_replays = list(replay_acc.values())
    missed_rows = {'MISSED', 'STRADDLED'}
    replay_frames = sum(row['frames'] for row in all_replays)
    counts = dict(missed=sum(row['played_before'] for row in dedup.values() if row['status'] in missed_rows),
                  abandoned=sum(row['played_after'] for row in dedup.values() if row['status'] == 'ABANDONED'),
                  straddled=sum(1 for row in dedup.values() if row['status'] == 'STRADDLED'),
                  replayed=replay_frames, replay_regions=len(all_replays),
                  delayed=sum(len(d['active_cues']) for d in decisions))
    return dict(decision=decisions[0], decisions=decisions, requests=requests, rows=list(dedup.values()),
                ledgers=list(ledger_acc.values()), replays=all_replays, counts=counts,
                balanced=all(row['balanced'] for row in ledger_acc.values()))
