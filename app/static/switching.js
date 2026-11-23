import {bindSheet} from './cells.js';
bindSheet(document.querySelector('#frames'), document.querySelector('#focused-cell'));
const notice = document.querySelector('#notice');
const reel = document.querySelector('#reel');
reel.addEventListener('change', () => {
  const params = new URLSearchParams({sample: reel.value});
  location.assign(`/sheet/switching?${params}`);
});

async function send(button, payload, id) {
  button.disabled = true;
  notice.textContent = '正在计算切轨…';
  try {
    const endpoint = id ? `/api/switch/runs/${id}/repeat` : '/api/switch/runs';
    const response = await fetch(endpoint, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.message);
    notice.textContent = result.reused ? '切轨复算一致，未新增档案' : '切轨请求已归档';
    if (!id) location.assign(`/sheet/switching?${new URLSearchParams({switch: result.id, sample: reel.value})}`);
  } catch (error) {
    notice.textContent = error.message || '提交失败，请重试';
  } finally { button.disabled = false; }
}

document.querySelector('#sample-form').addEventListener('submit', event => {
  event.preventDefault();
  const form = document.querySelector('#switch-form');
  const request = Object.fromEntries(new FormData(form));
  request.frame = Number(request.frame);
  send(event.submitter, {sample: reel.value, ...request});
});

document.querySelector('#switch-form').addEventListener('submit', async event => {
  event.preventDefault();
  const request = Object.fromEntries(new FormData(event.currentTarget));
  request.frame = Number(request.frame);
  notice.textContent = '正在预览…';
  try {
    const response = await fetch('/api/switch/preview', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({sample: reel.value, ...request})
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.message);
    render(result, request);
    notice.textContent = '预览完成（未归档）';
  } catch (error) {
    notice.textContent = error.message || '预览失败';
  }
});

function render(result, request) {
  document.querySelector('#kpi-requested_frame').textContent = result.decision.requested_frame;
  document.querySelector('#kpi-actual_frame').textContent = result.decision.actual_frame;
  document.querySelector('#kpi-rule').textContent = result.decision.rule;
  document.querySelector('#kpi-missed').textContent = result.counts.missed;
  document.querySelector('#kpi-abandoned').textContent = result.counts.abandoned;
  document.querySelector('#kpi-replayed').textContent = result.counts.replayed;
  document.querySelector('#decision-segment').textContent =
    `切段 ${result.decision.segment.cut}（原行 ${result.decision.segment.cut_line}）`;
  const gapText = result.decision.gap
    ? `请求帧位于目标待证区 [${result.decision.gap.gap_from}, ${result.decision.gap.gap_to})，顺延到 ${result.decision.gap.advance_to}。` : '';
  document.querySelector('#decision-summary').innerHTML =
    `请求切在目标帧 <b>${result.decision.requested_frame}</b>，反查源坐标 ${result.decision.segment.source_point}，落在切段 <b>${result.decision.segment.cut}</b>。${gapText}`;
  document.querySelector('#decision-cues').innerHTML = result.decision.active_cues.length
    ? '原句未读完，等至其交付末帧再切：' + result.decision.active_cues
      .map(cue => `<span class="cue-ref">原行 ${cue.line} · ${cue.cue_id} → 帧 ${cue.deferred_to_frame}</span>`).join('')
    : '切点未落在任何原句中间，立即切换。';
  const labels = {PLAYED_BEFORE: '切前播完', ABANDONED: '切后弃用', MISSED: '漏播',
    STRADDLED: '跨点截断', PLAYED_AFTER: '切后播放'};
  const body = document.querySelector('#decision-rows');
  body.innerHTML = result.rows.map((row, index) => {
    const cells = ['line', 'cue_id', 'track', 'frame_in', 'frame_out', 'played_before',
      'played_after', 'status', 'text'].map((field, col) => {
        const value = row[field];
        const content = field === 'status' ? `<span class="seg ${value.toLowerCase()}">${labels[value]}</span>`
          : (value === null || value === undefined ? '—' : value);
        return `<td tabindex="${index === 0 && col === 0 ? 0 : -1}" data-cell="${'ABCDEFGHI'[col]}${index + 1}" class="status-${row.status.toLowerCase()}">${content}</td>`;
      }).join('');
    return `<tr><th scope="row" class="pinned">${index + 1}</th>${cells}</tr>`;
  }).join('');
  document.querySelector('#ledger-rows').innerHTML = result.ledgers.map(row =>
    `<tr><td>${row.track}</td><td>${row.side === 'from' ? '原轨' : '译轨'}</td>` +
    `<td class="number">${row.union_frames}</td><td class="number">${row.before_switch}</td>` +
    `<td class="number">${row.after_switch}</td><td class="number">${row.difference}</td></tr>`).join('');
  document.querySelector('#ledger-balanced').textContent = result.balanced ? '勾稽平衡' : '勾稽不平';
  document.querySelector('#replay-block').innerHTML = result.replays.length
    ? `<h3 class="replay-title">重播定位（同轨重叠，深度 ≥2 的帧只计一次）</h3><table class="ledger"><thead><tr><th>轨道</th><th>入帧</th><th>出帧</th><th>重播帧</th><th>字幕号</th><th>原行组</th></tr></thead><tbody>${
      result.replays.map(row => `<tr><td>${row.track}</td><td class="number">${row.frame_in}</td><td class="number">${row.frame_out}</td><td class="number">${row.frames}</td><td>${row.cues.join(' / ')}</td><td>${row.lines.join(' / ')}</td></tr>`).join('')
    }</tbody></table>`
    : '<p class="empty">切轨后无同轨重叠重播。</p>';
  bindSheet(document.querySelector('#frames'), document.querySelector('#focused-cell'));
}
