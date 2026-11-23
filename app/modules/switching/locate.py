from fractions import Fraction
from math import ceil
from app.modules.clock.timecode import RATIO
from app.rational import show

KEEP = 'KEEP'


def keep_segments(edits):
    """每个 KEEP 切段在 24 fps 交付轴上的整数帧区间 [frame_in, frame_out)。"""
    segments = []
    for edit in edits:
        if edit['kind'] != KEEP:
            continue
        left = Fraction(edit['target'])
        right = left + (edit['end'] - edit['start']) * RATIO
        segments.append(dict(edit=edit, lo=ceil(left), hi=ceil(right), anchor=left))
    return segments


def reverse_locate(edits, frame):
    """把交付整数帧反查回公映版切段与源坐标。落在目标待证区时给出下一 KEEP 锚帧。"""
    segments = keep_segments(edits)
    if not segments:
        raise ValueError('NO_KEEP')
    for index, segment in enumerate(segments):
        if segment['lo'] <= frame < segment['hi']:
            edit = segment['edit']
            source_point = edit['start'] + (Fraction(frame) - segment['anchor']) / RATIO
            return dict(kind='KEEP', edit=edit, source_point=source_point, frame=frame, gap=None)
        if frame < segment['hi']:
            previous_hi = segments[index - 1]['hi'] if index else 0
            gap = dict(gap_from=previous_hi, gap_to=segment['lo'], advance_to=segment['lo'])
            return dict(kind='GAP', edit=segment['edit'], source_point=Fraction(segment['edit']['start']),
                        frame=segment['lo'], gap=gap)
    raise ValueError('OUT_OF_RANGE')


def kept_fragments(fragments, track, cue_id):
    return [row for row in fragments
            if row['track'] == track and row['cue_id'] == cue_id and row['kind'] == KEEP]


def last_delivered_frame(fragments, track, cue_id):
    kept = kept_fragments(fragments, track, cue_id)
    if not kept:
        raise ValueError('NO_DELIVERED_FRAME')
    return max(row['frame_out'] for row in kept)


def resolve(edits, clock_rows, fragments, request):
    """按公映版切段求实际切轨帧：待证区顺延，原句未读完则等至其交付末帧。

    顺延可能让切轨点落入下一条原句（同轨重叠字幕），因此循环到没有原句跨过切点。
    """
    located = reverse_locate(edits, request['frame'])
    rule = 'SWITCH_GAP_ADVANCE' if located['gap'] else 'SWITCH_IMMEDIATE'
    actual = located['frame']
    active_cues = []
    while True:
        active = [cue for cue in clock_rows
                  if cue['track'] == request['from_track']
                  and Fraction(cue['start']) <= located['source_point'] < Fraction(cue['end'])]
        if not active:
            break
        rule = 'SWITCH_DEFER_CUE_END' if located['gap'] is None else 'SWITCH_GAP_DEFER_CUE_END'
        next_frame = max(last_delivered_frame(fragments, cue['track'], cue['cue_id']) for cue in active)
        for cue in active:
            if not any(row['cue_id'] == cue['cue_id'] and row['line'] == cue['line'] for row in active_cues):
                active_cues.append(dict(cue_id=cue['cue_id'], line=cue['line'],
                                        source_start=cue['start'], source_end=cue['end'],
                                        deferred_to_frame=next_frame))
        if next_frame <= actual:
            break
        actual = next_frame
        located = reverse_locate(edits, actual)
    edit = located['edit']
    return dict(requested_frame=request['frame'], actual_frame=actual, rule=rule,
                segment=dict(cut=edit['cut'], cut_line=edit['line'], kind=edit['kind'],
                             source_point=show(located['source_point']), target_anchor=show(Fraction(edit['target']))),
                gap=located['gap'], active_cues=active_cues)
