import {DOMAIN} from '../constants/domain.js';
import {store,load} from '../stores/research.js';
import {jointRuns} from '../api/research.js';
import {esc} from '../utils/format.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
const DIRECTION={positive:'正向',negative:'负向',zero:'零相关',undefined:'未定义'};
const flagLabels=()=>({insufficient:'余样不足',constant_x:`${DOMAIN.fields[0][1]}常量`,constant_y:`${DOMAIN.fields[1][1]}常量`});
const tau=x=>x===null||x===undefined?'—':Number(x).toFixed(4);
const flags=f=>f.length?f.map(k=>`<span class="flag">${esc(flagLabels()[k]||k)}</span>`).join(''):'—';
function listView(){return `<div class="eyebrow">JOINT SENSITIVITY</div><h1>联合核算 · 逐批剔除</h1><p class="lead">多批合并求精确 Kendall τ-b，再逐批剔除重算：少了哪一批，结论会反向。到「分析执行」页选择批次发起。</p>${table(['编号 / 研究','状态','计数进度','冻结快照','冻结时间'],store.jointRuns.map(r=>[{html:`<a href="#joint/${r.id}">#${r.id} ${esc(r.name)}</a>`},{html:status(r.status)},`${r.completed_batches}/${r.n_batches} 批`,r.n_specimens+' 件 · '+r.checksum.slice(0,12),r.frozen_at]))}`;}
function progressView(r){const pct=r.n_batches?Math.round(100*r.completed_batches/r.n_batches):0;return `<div class="method-note"><strong>计数进行中：${r.completed_batches}/${r.n_batches} 批已确认。</strong><div class="progress"><i style="width:${pct}%"></i></div>所有批次结果齐全后才开放查看；计数中断会从已确认进度续跑，重试不重复计入。此页每2秒自动刷新。</div>`;}
function resultView(res){const {full,summary}=res;return `<section class="result-intro"><strong>${esc(res.interpretation)}</strong><p>${esc(res.caveat)}</p></section>
<h2>全样本</h2>${table(['指标','值'],[['独立试件',full.n],['批次',full.n_batches],['协和对 P',full.concordant],['冲突对 Q',full.discordant],[`${DOMAIN.fields[0][1]}并列对`,full.tie_pairs_x],[`${DOMAIN.fields[1][1]}并列对`,full.tie_pairs_y],['Kendall τ-b（并列修正）',tau(full.tau)],['方向',DIRECTION[full.direction]],['标记',full.flags.length?full.flags.map(k=>flagLabels()[k]||k).join('；'):'—']])}
<h2>逐批剔除 <small>${summary.reversed_count} 批使结论反向 · ${summary.changed_count} 批方向变化</small></h2>
<label class="batch-option"><input type="checkbox" id="only-changed"> 仅看结论变化的批次</label>
<div class="table-wrap"><table><thead><tr><th>批次</th><th>剔除试件</th><th>余样</th><th>协和对</th><th>冲突对</th><th>τ-b</th><th>方向</th><th>标记</th><th>结论</th></tr></thead><tbody>
${res.batches.map(b=>`<tr class="${b.reversed?'reversed':''}" data-changed="${b.direction_changed?1:0}"><td>${esc(b.batch_name)}</td><td>${b.n_removed}</td><td>${b.n_remaining}</td><td>${b.concordant}</td><td>${b.discordant}</td><td>${tau(b.tau)}</td><td>${DIRECTION[b.direction]}</td><td>${flags(b.flags)}</td><td>${b.reversed?'<strong>反向</strong>':b.direction_changed?'方向变化':'—'}</td></tr>`).join('')}
</tbody></table></div>`;}
export async function render(id){
  if(!id)return listView();
  const r=await jointRuns.get(id);store.jointRunId=r.id;
  const writable=localStorage.getItem('research-role')!=='viewer';
  let html=`<div class="eyebrow">JOINT RUN ${r.id}</div><h1>${esc(r.name)} ${status(r.status)}</h1><div class="checksum">INPUT SHA256 ${r.checksum}</div><p>冻结 ${r.n_specimens} 件 · ${r.n_batches} 批 · ${esc(r.frozen_at)} · 最小余样量 ${r.parameters.min_n}${r.source_changed?' · <strong>冻结后源数据又有更正，将体现在下次研究</strong>':''}</p>`;
  if(r.status==='failed')html+=`<div class="error">计数失败：${esc(r.error)}。已确认的批次进度保留。</div>${writable?'<div class="toolbar"><button id="resume">从已确认进度续跑 →</button></div>':''}`;
  else if(r.status!=='completed')html+=progressView(r);
  else html+=resultView(await jointRuns.results(id));
  html+=`<details><summary>冻结的批次清单</summary><pre>${esc(JSON.stringify(r.batches,null,2))}</pre></details>`;
  return html;
}
export function bind(refresh){
  const btn=document.getElementById('resume');
  if(btn)btn.onclick=async()=>{try{await jointRuns.resume(store.jointRunId);await load();refresh();}catch(e){document.getElementById('notice').textContent=e.message;}};
  const toggle=document.getElementById('only-changed');
  if(toggle)toggle.onchange=()=>{document.querySelectorAll('tr[data-changed]').forEach(tr=>{if(toggle.checked&&tr.dataset.changed==='0')tr.style.display='none';else tr.style.display='';});};
}
