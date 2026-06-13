import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Bell,
  Home,
  ListChecks,
  LogOut,
  Plus,
  RefreshCw,
  Save,
  Settings,
  ShieldAlert,
  Trash2,
  WalletCards,
} from "lucide-react";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

function apiClient(token) {
  async function request(path, options = {}) {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers || {}),
      },
    });
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Request failed");
    return data;
  }
  return {
    login: (email, password) => request("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
    me: () => request("/api/auth/me"),
    summary: () => request("/api/dashboard/summary"),
    wallets: () => request("/api/wallets"),
    walletMetrics: () => request("/api/market-data/wallet-metrics"),
    walletMarketData: (id) => request(`/api/market-data/wallets/${id}`),
    refreshWallet: (id) => request(`/api/market-data/wallets/${id}/refresh`, { method: "POST" }),
    refreshAllMarketData: () => request("/api/market-data/refresh", { method: "POST" }),
    signals: () => request("/api/signals"),
    updateSignal: (id, status) => request(`/api/signals/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
    simulateSignal: (id) => request(`/api/signals/${id}/simulate`, { method: "POST" }),
    paperSummary: () => request("/api/signals/paper/summary"),
    paperTrades: () => request("/api/signals/paper/trades"),
    closePaperTrade: (id) => request(`/api/signals/paper/trades/${id}/close`, { method: "POST" }),
    createWallet: (payload) => request("/api/wallets", { method: "POST", body: JSON.stringify(payload) }),
    updateWallet: (id, payload) => request(`/api/wallets/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
    deleteWallet: (id) => request(`/api/wallets/${id}`, { method: "DELETE" }),
    logs: () => request("/api/system/logs?limit=20"),
  };
}

const emptyWallet = {
  address: "",
  platform: "hyperliquid",
  name: "",
  tags: "",
  manual_score: 50,
  status: "active",
  notes: "",
};

function LoginPage({ onLogin }) {
  const [email, setEmail] = useState("admin@novaion.ai");
  const [password, setPassword] = useState("Novaion@123");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const api = apiClient();
      const data = await api.login(email, password);
      onLogin(data.access_token);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-panel">
        <div>
          <p className="eyebrow">Internal MVP</p>
          <h1>NOVAION Smart Money Agent</h1>
          <p className="muted">Research and paper-following only. No private keys, no live orders.</p>
        </div>
        <form onSubmit={submit} className="form-stack">
          <label>
            Email
            <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required />
          </label>
          <label>
            Password
            <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" required />
          </label>
          {error && <div className="error-box">{error}</div>}
          <button className="primary-button" disabled={loading}>
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}

function Shell({ children, activePage, setActivePage, onLogout }) {
  const nav = [
    ["dashboard", "Dashboard", Home],
    ["wallets", "Wallets", WalletCards],
    ["signals", "Signals", Bell],
    ["settings", "Settings", Settings],
  ];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark">N</div>
          <div>
            <strong>NOVAION</strong>
            <span>Smart Money MVP</span>
          </div>
        </div>
        <nav>
          {nav.map(([key, label, Icon]) => (
            <button key={key} className={activePage === key ? "nav-link active" : "nav-link"} onClick={() => setActivePage(key)}>
              <Icon size={18} />
              {label}
            </button>
          ))}
        </nav>
        <button className="nav-link logout" onClick={onLogout}>
          <LogOut size={18} />
          Logout
        </button>
      </aside>
      <section className="content-shell">{children}</section>
    </div>
  );
}

function DashboardPage({ api }) {
  const [summary, setSummary] = useState(null);
  const [paper, setPaper] = useState(null);
  const [logs, setLogs] = useState([]);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const [summaryData, paperData, logsData] = await Promise.all([api.summary(), api.paperSummary(), api.logs()]);
      setSummary(summaryData);
      setPaper(paperData);
      setLogs(logsData);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <Page title="Dashboard" action={<IconButton title="Refresh" onClick={load} icon={RefreshCw} />}>
      {error && <div className="error-box">{error}</div>}
      <div className="metric-grid">
        <Metric label="Total wallets" value={summary?.total_wallets ?? 0} />
        <Metric label="Active" value={summary?.active_wallets ?? 0} />
        <Metric label="Disabled" value={summary?.disabled_wallets ?? 0} />
        <Metric label="Hyperliquid" value={summary?.hyperliquid_wallets ?? 0} />
      </div>
      <section className="section-band">
        <div className="section-title">
          <h2>Paper Account</h2>
          <span>Default capital 1000 USDT</span>
        </div>
        <div className="metric-grid">
          <Metric label="Equity" value={formatUsd(paper?.current_equity ?? 1000)} />
          <Metric label="Today PnL" value={formatUsd(paper?.today_pnl ?? 0)} />
          <Metric label="Total PnL" value={formatUsd(paper?.total_pnl ?? 0)} />
          <Metric label="Win Rate" value={formatPercent(paper?.win_rate ?? 0)} />
        </div>
      </section>
      <section className="section-band">
        <div className="section-title">
          <h2>Wallet Ranking</h2>
          <span>Part 2 will calculate live metrics</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Wallet</th>
                <th>Trades 30D</th>
                <th>Realized PnL</th>
                <th>Unrealized PnL</th>
                <th>Win Rate</th>
                <th>Profit Factor</th>
              </tr>
            </thead>
            <tbody>
              {(summary?.rankings || []).map((item) => (
                <tr key={item.wallet_id}>
                  <td>{item.name}</td>
                  <td>{item.trades_30d}</td>
                  <td className={item.realized_pnl >= 0 ? "positive" : "negative"}>{formatUsd(item.realized_pnl)}</td>
                  <td className={item.unrealized_pnl >= 0 ? "positive" : "negative"}>{formatUsd(item.unrealized_pnl)}</td>
                  <td>{formatPercent(item.win_rate)}</td>
                  <td>{formatNumber(item.profit_factor)}</td>
                </tr>
              ))}
              {!(summary?.rankings || []).length && (
                <tr><td colSpan="6" className="empty-cell">No metrics yet. Add a Hyperliquid wallet and run sync.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      <section className="section-band">
        <div className="section-title">
          <h2>System Logs</h2>
          <span>Latest 20</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Level</th>
                <th>Module</th>
                <th>Message</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id}>
                  <td><span className={`pill ${log.level.toLowerCase()}`}>{log.level}</span></td>
                  <td>{log.module}</td>
                  <td>{log.message}</td>
                  <td>{new Date(log.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </Page>
  );
}

function WalletsPage({ api, openWallet }) {
  const [wallets, setWallets] = useState([]);
  const [metrics, setMetrics] = useState([]);
  const [form, setForm] = useState(emptyWallet);
  const [editingId, setEditingId] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const [walletData, metricData] = await Promise.all([api.wallets(), api.walletMetrics()]);
      setWallets(walletData);
      setMetrics(metricData);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function edit(wallet) {
    setEditingId(wallet.id);
    setForm({
      address: wallet.address,
      platform: wallet.platform,
      name: wallet.name,
      tags: wallet.tags || "",
      manual_score: wallet.manual_score,
      status: wallet.status,
      notes: wallet.notes || "",
    });
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    try {
      if (editingId) {
        await api.updateWallet(editingId, form);
      } else {
        await api.createWallet(form);
      }
      setForm(emptyWallet);
      setEditingId(null);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(wallet) {
    setError("");
    try {
      await api.deleteWallet(wallet.id);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function refreshAll() {
    setError("");
    try {
      await api.refreshAllMarketData();
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  const metricByWalletId = Object.fromEntries(metrics.map((metric) => [metric.wallet_id, metric]));

  return (
    <Page title="Wallet Watchlist" action={<div className="button-row"><button className="ghost-button" onClick={refreshAll}><RefreshCw size={16} />Sync</button><IconButton title="Refresh" onClick={load} icon={RefreshCw} /></div>}>
      {error && <div className="error-box">{error}</div>}
      <section className="section-band">
        <div className="section-title">
          <h2>{editingId ? "Edit Wallet" : "Add Wallet"}</h2>
          <span>Hyperliquid is the Part 2 live data target</span>
        </div>
        <form onSubmit={submit} className="wallet-form">
          <label>
            Name
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </label>
          <label>
            Address
            <input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} required />
          </label>
          <label>
            Platform
            <select value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value })}>
              <option value="hyperliquid">hyperliquid</option>
              <option value="polymarket">polymarket</option>
            </select>
          </label>
          <label>
            Status
            <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              <option value="active">active</option>
              <option value="disabled">disabled</option>
            </select>
          </label>
          <label>
            Score
            <input type="number" min="1" max="100" value={form.manual_score} onChange={(e) => setForm({ ...form, manual_score: Number(e.target.value) })} />
          </label>
          <label>
            Tags
            <input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} placeholder="BTC高手, low-risk" />
          </label>
          <label className="wide">
            Notes
            <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </label>
          <div className="form-actions">
            <button className="primary-button" type="submit"><Save size={16} />{editingId ? "Save" : "Add"}</button>
            {editingId && <button className="ghost-button" type="button" onClick={() => { setEditingId(null); setForm(emptyWallet); }}>Cancel</button>}
          </div>
        </form>
      </section>
      <section className="section-band">
        <div className="section-title">
          <h2>Watchlist</h2>
          <span>{wallets.length} wallets</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Platform</th>
                <th>Tags</th>
                <th>Score</th>
                <th>Trades 30D</th>
                <th>Win Rate</th>
                <th>Realized PnL</th>
                <th>Status</th>
                <th>Address</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {wallets.map((wallet) => (
                <WalletRow
                  key={wallet.id}
                  wallet={wallet}
                  metric={metricByWalletId[wallet.id]}
                  openWallet={openWallet}
                  edit={edit}
                  remove={remove}
                />
              ))}
              {!wallets.length && (
                <tr><td colSpan="10" className="empty-cell">No wallets yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </Page>
  );
}

function WalletRow({ wallet, metric, openWallet, edit, remove }) {
  return (
    <tr>
      <td><button className="text-link" onClick={() => openWallet(wallet)}>{wallet.name}</button></td>
      <td>{wallet.platform}</td>
      <td>{wallet.tags || "-"}</td>
      <td>{wallet.manual_score}</td>
      <td>{metric?.trades_30d ?? 0}</td>
      <td>{formatPercent(metric?.win_rate ?? 0)}</td>
      <td className={(metric?.realized_pnl ?? 0) >= 0 ? "positive" : "negative"}>{formatUsd(metric?.realized_pnl ?? 0)}</td>
      <td><span className={`pill ${wallet.status}`}>{wallet.status}</span></td>
      <td className="mono">{wallet.address}</td>
      <td className="row-actions">
        <button title="Edit wallet" onClick={() => edit(wallet)}><ListChecks size={16} /></button>
        <button title="Delete wallet" onClick={() => remove(wallet)}><Trash2 size={16} /></button>
      </td>
    </tr>
  );
}

function WalletDetailPage({ wallet, api, back }) {
  const [marketData, setMarketData] = useState(null);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);

  async function load() {
    setError("");
    try {
      setMarketData(await api.walletMarketData(wallet.id));
    } catch (err) {
      setError(err.message);
    }
  }

  async function sync() {
    setError("");
    setSyncing(true);
    try {
      await api.refreshWallet(wallet.id);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSyncing(false);
    }
  }

  useEffect(() => {
    load();
  }, [wallet.id]);

  if (!wallet) return null;
  return (
    <Page title={wallet.name} action={<div className="button-row"><button className="ghost-button" onClick={sync} disabled={syncing}><RefreshCw size={16} />{syncing ? "Syncing" : "Sync"}</button><button className="ghost-button" onClick={back}>Back</button></div>}>
      {error && <div className="error-box">{error}</div>}
      <section className="section-band">
        <div className="section-title">
          <h2>Wallet Detail</h2>
          <span>Read-only Hyperliquid data</span>
        </div>
        <div className="detail-grid">
          <Metric label="Platform" value={wallet.platform} />
          <Metric label="Manual score" value={wallet.manual_score} />
          <Metric label="Status" value={wallet.status} />
          <Metric label="Trades 30D" value={marketData?.metric?.trades_30d ?? 0} />
        </div>
        <p className="mono detail-address">{wallet.address}</p>
      </section>
      <section className="section-band">
        <div className="section-title">
          <h2>Positions</h2>
          <span>{marketData?.positions?.length ?? 0} active</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Coin</th>
                <th>Side</th>
                <th>Size</th>
                <th>Entry</th>
                <th>Value</th>
                <th>Leverage</th>
                <th>Unrealized PnL</th>
              </tr>
            </thead>
            <tbody>
              {(marketData?.positions || []).map((position) => (
                <tr key={`${position.coin}-${position.side}`}>
                  <td>{position.coin}</td>
                  <td>{position.side}</td>
                  <td>{formatNumber(position.size)}</td>
                  <td>{formatNumber(position.entry_price)}</td>
                  <td>{formatUsd(position.position_value)}</td>
                  <td>{formatNumber(position.leverage)}x</td>
                  <td className={position.unrealized_pnl >= 0 ? "positive" : "negative"}>{formatUsd(position.unrealized_pnl)}</td>
                </tr>
              ))}
              {!(marketData?.positions || []).length && (
                <tr><td colSpan="7" className="empty-cell">No current positions.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      <section className="section-band">
        <div className="section-title">
          <h2>Recent Fills</h2>
          <span>{marketData?.fills?.length ?? 0} shown</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Coin</th>
                <th>Side</th>
                <th>Price</th>
                <th>Size</th>
                <th>Closed PnL</th>
                <th>Fee</th>
              </tr>
            </thead>
            <tbody>
              {(marketData?.fills || []).map((fill) => (
                <tr key={fill.id}>
                  <td>{new Date(fill.trade_time).toLocaleString()}</td>
                  <td>{fill.coin}</td>
                  <td>{fill.side}</td>
                  <td>{formatNumber(fill.price)}</td>
                  <td>{formatNumber(fill.size)}</td>
                  <td className={fill.closed_pnl >= 0 ? "positive" : "negative"}>{formatUsd(fill.closed_pnl)}</td>
                  <td>{formatUsd(fill.fee)}</td>
                </tr>
              ))}
              {!(marketData?.fills || []).length && (
                <tr><td colSpan="7" className="empty-cell">No fills synced yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      <section className="section-band">
        <div className="section-title">
          <h2>Open Orders</h2>
          <span>{marketData?.open_orders?.length ?? 0} active</span>
        </div>
        <div className="placeholder-row">{(marketData?.open_orders || []).length ? JSON.stringify(marketData.open_orders.slice(0, 5)) : "No open orders."}</div>
      </section>
    </Page>
  );
}

function SignalsPage({ api }) {
  const [signals, setSignals] = useState([]);
  const [trades, setTrades] = useState([]);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const [signalData, tradeData, summaryData] = await Promise.all([api.signals(), api.paperTrades(), api.paperSummary()]);
      setSignals(signalData);
      setTrades(tradeData);
      setSummary(summaryData);
    } catch (err) {
      setError(err.message);
    }
  }

  async function ignore(signal) {
    setError("");
    try {
      await api.updateSignal(signal.id, "ignored");
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function markRead(signal) {
    setError("");
    try {
      await api.updateSignal(signal.id, "read");
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function simulate(signal) {
    setError("");
    try {
      await api.simulateSignal(signal.id);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function closeTrade(trade) {
    setError("");
    try {
      await api.closePaperTrade(trade.id);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <Page title="Signals" action={<IconButton title="Refresh" onClick={load} icon={RefreshCw} />}>
      {error && <div className="error-box">{error}</div>}
      <section className="section-band">
        <div className="section-title">
          <h2>Paper Summary</h2>
          <span>Simulation only</span>
        </div>
        <div className="metric-grid">
          <Metric label="Current equity" value={formatUsd(summary?.current_equity ?? 1000)} />
          <Metric label="Open positions" value={summary?.open_positions ?? 0} />
          <Metric label="Max drawdown" value={formatPercent(summary?.max_drawdown ?? 0)} />
          <Metric label="Closed trades" value={summary?.closed_trades ?? 0} />
        </div>
      </section>
      <section className="section-band">
        <div className="section-title">
          <h2>Signal Inbox</h2>
          <span>open / add / reduce / close</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Wallet</th>
                <th>Signal</th>
                <th>Size</th>
                <th>Lev</th>
                <th>Confidence</th>
                <th>Risk</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {signals.map((signal) => (
                <tr key={signal.id}>
                  <td>{new Date(signal.created_at).toLocaleString()}</td>
                  <td>{signal.wallet_name || signal.wallet_id}</td>
                  <td>{signal.symbol} {signal.side} / {signal.signal_type}</td>
                  <td>{formatUsd(signal.source_size)}</td>
                  <td>{formatNumber(signal.source_leverage)}x</td>
                  <td>{signal.confidence_score}</td>
                  <td className={signal.risk_score > 80 ? "negative" : ""}>{signal.risk_score}</td>
                  <td><span className={`pill ${signal.status}`}>{signal.status}</span></td>
                  <td className="row-actions">
                    <button title="Simulate" onClick={() => simulate(signal)}><Plus size={16} /></button>
                    <button title="Mark read" onClick={() => markRead(signal)}><ListChecks size={16} /></button>
                    <button title="Ignore" onClick={() => ignore(signal)}><Trash2 size={16} /></button>
                  </td>
                </tr>
              ))}
              {!signals.length && (
                <tr><td colSpan="9" className="empty-cell">No signals yet. Sync a wallet after positions change.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      <section className="section-band">
        <div className="section-title">
          <h2>Paper Trades</h2>
          <span>{trades.length} recent</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Opened</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Size</th>
                <th>Lev</th>
                <th>Status</th>
                <th>PnL</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade) => (
                <tr key={trade.id}>
                  <td>{new Date(trade.opened_at).toLocaleString()}</td>
                  <td>{trade.symbol}</td>
                  <td>{trade.side}</td>
                  <td>{formatNumber(trade.entry_price)}</td>
                  <td>{formatUsd(trade.size_usd)}</td>
                  <td>{formatNumber(trade.leverage)}x</td>
                  <td><span className={`pill ${trade.status}`}>{trade.status}</span></td>
                  <td className={trade.pnl >= 0 ? "positive" : "negative"}>{formatUsd(trade.pnl)}</td>
                  <td className="row-actions">
                    {trade.status === "open" && <button title="Close trade" onClick={() => closeTrade(trade)}><ListChecks size={16} /></button>}
                  </td>
                </tr>
              ))}
              {!trades.length && (
                <tr><td colSpan="9" className="empty-cell">No paper trades yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </Page>
  );
}

function SettingsPage() {
  return (
    <Page title="Settings">
      <section className="risk-banner">
        <ShieldAlert size={20} />
        Trading is risky. This MVP is research and simulation only. Simulated results do not represent future returns.
      </section>
      <section className="section-band">
        <div className="section-title">
          <h2>Live Trading Controls</h2>
          <span>Displayed only, not executed in MVP</span>
        </div>
        <div className="settings-grid">
          <ReadonlySetting label="enable_live_trading" value="false" />
          <ReadonlySetting label="require_manual_approval" value="true" />
          <ReadonlySetting label="max_live_order_usd" value="20" />
          <ReadonlySetting label="max_daily_live_loss_usd" value="50" />
          <ReadonlySetting label="emergency_stop" value="true" />
        </div>
      </section>
    </Page>
  );
}

function Page({ title, action, children }) {
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">NOVAION Smart Money Agent</p>
          <h1>{title}</h1>
        </div>
        {action}
      </header>
      {children}
    </>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ReadonlySetting({ label, value }) {
  return (
    <div className="setting-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function IconButton({ icon: Icon, title, onClick }) {
  return (
    <button className="icon-button" title={title} onClick={onClick}>
      <Icon size={18} />
    </button>
  );
}

function App() {
  const [token, setToken] = useState(localStorage.getItem("novaion_token") || "");
  const [activePage, setActivePage] = useState("dashboard");
  const [selectedWallet, setSelectedWallet] = useState(null);
  const api = useMemo(() => apiClient(token), [token]);

  function onLogin(nextToken) {
    localStorage.setItem("novaion_token", nextToken);
    setToken(nextToken);
  }

  function logout() {
    localStorage.removeItem("novaion_token");
    setToken("");
  }

  if (!token) return <LoginPage onLogin={onLogin} />;

  let page = <DashboardPage api={api} />;
  if (activePage === "wallets") {
    page = selectedWallet ? (
      <WalletDetailPage wallet={selectedWallet} api={api} back={() => setSelectedWallet(null)} />
    ) : (
      <WalletsPage api={api} openWallet={(wallet) => setSelectedWallet(wallet)} />
    );
  }
  if (activePage === "signals") page = <SignalsPage api={api} />;
  if (activePage === "settings") page = <SettingsPage />;

  return (
    <Shell activePage={activePage} setActivePage={(pageKey) => { setSelectedWallet(null); setActivePage(pageKey); }} onLogout={logout}>
      {page}
    </Shell>
  );
}

function formatUsd(value) {
  return `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function formatPercent(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 6 });
}

createRoot(document.getElementById("root")).render(<App />);
