import React, {useEffect, useRef, useState} from 'react';
import {RefreshCw, ShieldCheck, Activity} from 'lucide-react';
import './v3.css';

const number = (n, digits = 2) => n == null ? '--' : Number(n).toLocaleString('zh-CN', {minimumFractionDigits: digits, maximumFractionDigits: digits});
const money = n => n == null ? '--' : `$${number(n)}`;
const date = value => value ? new Date(value.endsWith('Z') ? value : `${value}Z`).toLocaleString('zh-CN') : '--';

function EquityChart({points}) {
  const canvas = useRef(null);
  useEffect(() => {
    const node = canvas.current;
    function draw() {
      const width = node.clientWidth, height = 220, ratio = window.devicePixelRatio || 1;
      node.width = width * ratio; node.height = height * ratio;
      const ctx = node.getContext('2d'); ctx.scale(ratio, ratio);
      ctx.clearRect(0, 0, width, height);
      if (points.length < 2) return;
      const values = points.map(p => p.equity), min = Math.min(...values), max = Math.max(...values), span = Math.max(max - min, .1);
      const start = new Date(points[0].at+'Z').getTime(), end = new Date(points.at(-1).at+'Z').getTime();
      const x = p => 65 + (new Date(p.at+'Z').getTime()-start) / Math.max(1,end-start) * (width-85);
      const y = n => 20 + (max-n)/span*160;
      ctx.font = '12px system-ui'; ctx.fillStyle = '#596760'; ctx.strokeStyle = '#dce3df'; ctx.lineWidth = 1;
      [min, (min+max)/2, max].forEach(v => {ctx.fillText(number(v), 3, y(v)+4); ctx.beginPath(); ctx.moveTo(60,y(v)); ctx.lineTo(width-20,y(v)); ctx.stroke();});
      ctx.strokeStyle = '#167957'; ctx.lineWidth = 2; ctx.beginPath();
      points.forEach((p,i) => {const previous=points[i-1]; if (!previous || p.quality!=='GOOD' || previous.quality!=='GOOD' || new Date(p.at+'Z')-new Date(previous.at+'Z')>900000) ctx.moveTo(x(p),y(p.equity)); else ctx.lineTo(x(p),y(p.equity));}); ctx.stroke();
    }
    const observer=new ResizeObserver(draw); observer.observe(node); draw();
    return () => observer.disconnect();
  },[points]);
  return <div className="v3-curve"><canvas ref={canvas} aria-label="V3模拟账户权益曲线" role="img"/>{points.length<2 && <p className="v3-empty">权益样本积累中</p>}</div>;
}

function Table({heads, rows}) {
  return <div className="v3-table-wrap"><table><thead><tr>{heads.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.length ? rows.map((r,i)=><tr key={i}>{r.map((c,j)=><td key={j}>{c}</td>)}</tr>) : <tr><td colSpan={heads.length} className="v3-empty">暂无前向样本</td></tr>}</tbody></table></div>;
}

export default function V3Dashboard({api, legacy}) {
  const [data,setData]=useState(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[group,setGroup]=useState('wallet'),[tier,setTier]=useState('all'),[sort,setSort]=useState('score');
  async function refresh() {setLoading(true);try {setData(await api.v3Dashboard());setError('');}catch(e){setError(e.message);}finally{setLoading(false);}}
  useEffect(()=>{refresh(); const id=setInterval(refresh,60000);return()=>clearInterval(id);},[api]);
  if(data && !data.enabled)return legacy;
  const a=data?.account || {}, attribution=data?.attribution || {}, metrics=attribution.summary || {};
  const walletNames=Object.fromEntries((data?.wallets || []).map(w=>[w.wallet_id,w.address]));
  const sortedWallets=[...(data?.wallets || [])].filter(w=>tier==='all'||w.tier===tier).sort((a,b)=>(b[sort] ?? b.metrics[sort] ?? -Infinity)-(a[sort] ?? a.metrics[sort] ?? -Infinity));
  return <div className="v3-page">
    <header className="v3-header"><div><h1>NOVAION Smart Money</h1><p>V3 · Shadow Validation · 仅模拟，非真实交易</p></div><button className="icon-button" title="刷新运行数据" aria-label="刷新运行数据" disabled={loading} onClick={refresh}><RefreshCw size={18}/></button></header>
    {error && <div className="error-box" role="alert">{error}</div>}
    {!data ? <p aria-live="polite">{loading?'正在读取运行数据':'运行数据暂不可用'}</p> : <>
      <div className="v3-status"><span><ShieldCheck size={16}/> 实盘关闭</span><span><Activity size={16}/> 调度：{data.scheduler}</span><span>数据：{a.quality}</span><span>验证：{data.started_at ? '进行中' : '等待首条有效新信号'}</span></div>
      <dl className="v3-metrics">{[['初始本金',money(a.starting_balance)],['当前权益',money(a.equity)],['已实现净收益',money(a.realized_pnl)],['预计净浮动收益',money(a.unrealized_pnl)],['占用保证金',money(a.used_margin)],['可用资金',money(Math.max(0,a.available_funds_raw || 0))]].map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      <section><div className="v3-section-title"><h2>前向权益</h2><span>最大回撤：{data.drawdown.amount==null ? '数据不足' : `${money(data.drawdown.amount)} / ${number(data.drawdown.percent)}%`}</span></div><EquityChart points={data.equity}/><div className="v3-note">起点：{date(data.cutover_at)}　验证开始：{date(data.started_at)}　结束：{date(data.end_at)}</div></section>
      <section><div className="v3-section-title"><h2>钱包观察池</h2><div className="v3-filters"><select aria-label="钱包排序" value={sort} onChange={e=>setSort(e.target.value)}>{[['score','评分'],['net_after_fees','观测净收益'],['profit_factor','PF'],['expectancy','期望值'],['copyability','可跟随性']].map(([k,v])=><option key={k} value={k}>{v}</option>)}</select><select aria-label="钱包等级" value={tier} onChange={e=>setTier(e.target.value)}><option value="all">全部等级</option>{['S','A','B','C','Reject'].map(t=><option key={t}>{t}</option>)}</select></div></div>
        <Table heads={['钱包','评分 / 等级','可跟随性','状态','近30天观测净收益','PF','期望值','样本 / 活跃日','数据质量','同步秒数']} rows={sortedWallets.map(w=>[w.address,`${number(w.score,1)} / ${w.tier}`,number(w.copyability,1),w.lifecycle,money(w.metrics.net_after_fees),number(w.metrics.profit_factor),money(w.metrics.expectancy),`${w.metrics.close_fill_count ?? '--'} / ${w.metrics.active_days ?? '--'}`,w.data_quality ?? w.quality,number(w.freshness_seconds,0)])}/>
        <div className="v3-note">源钱包指标为观测估算值；资金流与资金费覆盖不足时，不提供确切 ROI。评分不是收益承诺。</div></section>
      <section><h2>新信号处理</h2><Table heads={['时间','钱包','币种 / 方向','动作','质量评分','处理状态','原因']} rows={data.signals.map(s=>[date(s.created_at),walletNames[s.wallet_id] || s.wallet_id,`${s.symbol} / ${s.side}`,s.action,number(s.score,1),s.status,s.reason || '--'])}/></section>
      <section><h2>Shadow 当前仓位</h2><Table heads={['钱包','币种','方向','数量','保证金','均价','市价','净浮动盈亏','质量']} rows={data.positions.map(p=>[walletNames[p.wallet_id] || p.wallet_id,p.symbol,p.state==='OPEN_LONG'?'做多':'做空',number(p.quantity,6),money(p.margin),number(p.average_entry,5),number(p.mark_price,5),money(p.unrealized_pnl),p.quality])}/></section>
      <section><div className="v3-section-title"><h2>净收益归因</h2><select aria-label="归因维度" value={group} onChange={e=>setGroup(e.target.value)}>{[['wallet','钱包'],['symbol','币种'],['side','方向'],['tier','等级'],['regime','市场状态']].map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></div>
        <Table heads={['分组','交易 / 已平仓','胜率','已实现净收益','净 PF','期望值','平均持仓小时']} rows={(attribution[group]||[]).map(r=>[group==='wallet'?(walletNames[r.key] || r.key):r.key,`${r.trades} / ${r.closed_trades}`,r.win_rate==null?'--':`${number(r.win_rate*100)}%`,money(r.net_realized_pnl),number(r.profit_factor),money(r.expectancy),r.average_holding_seconds==null?'--':number(r.average_holding_seconds/3600)])}/>
        <p className="v3-note">{attribution.validation?.grade} · 已平仓样本：{metrics.closed_trades || 0} · 资金费按公开费率与观测名义仓位估算。</p></section>
      <section><h2>动作现金流与数据质量</h2><Table heads={['动作','次数','毛收益','手续费','滑点成本','资金费成本','净收益']} rows={(attribution.action||[]).map(r=>[r.action,r.count,money(r.gross_pnl),money(r.fees),money(r.slippage),money(r.funding),money(r.net_pnl)])}/>
        <div className="v3-quality">{Object.entries(data.quality).map(([k,v])=><span key={k}>{k}: {v}</span>)}{!Object.keys(data.quality).length && <span>起点后未记录数据质量异常</span>}</div></section>
      <footer className="v3-note">交易有风险，模拟结果不代表未来收益。历史 V1/V2 数据保留，未进入本轮 Shadow 回放。</footer>
    </>}
  </div>;
}
