import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import Connections from './Connections';
import './style.css';

const tabs = ['Overview', 'Runs', 'History', 'Evaluation', 'Connections', 'Connect MCP'];
const labels = {offline: 'Offline checks', contracts: 'Contract baseline', evaluation: 'Response evaluation', target:'Target API contract', openai:'OpenAI authentication', anthropic:'Anthropic authentication'};
const descriptions = {
  offline: 'Exercise retries, contracts, persistence, and controlled failures. No API credentials needed.',
  contracts: 'Compare the seven model schemas with their versioned baselines.',
  evaluation: 'Check four supplied synthetic responses against schemas and numeric properties.',
};
const statuses = {queued: 'Queued', running: 'Running', passed: 'Passed', failed: 'Failed', interrupted: 'Interrupted'};
const isBusy = run => ['queued', 'running'].includes(run.status);
const when = value => value ? new Date(value).toLocaleString('en-US', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : '—';
const configTemplate = JSON.stringify({mcpServers: {'api-testing-framework': {
  command: '<MCP_VENV_PYTHON>', args: ['<PROJECT_ROOT>/scripts/mcp_server.py', '--console-state', '<CONSOLE_STATE_JSON>'],
}}}, null, 2);

const codexTemplate = `[mcp_servers.api-testing-framework]
command = "<MCP_VENV_PYTHON>"
args = ["<PROJECT_ROOT>/scripts/mcp_server.py", "--console-state", "<CONSOLE_STATE_JSON>"]

[mcp_servers.api-testing-framework.env]
PYTHONDONTWRITEBYTECODE = "1"`;

function Icon({name, size=20}) {
  const paths = {
    Overview: <><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>,
    Runs: <><path d="m9 5 11 7-11 7z"/><path d="M4 5v14"/></>,
    History: <><path d="M3 11a9 9 0 1 1 2 7M3 4v7h7"/><path d="M12 7v5l3 2"/></>,
    Evaluation: <><path d="m5 12 4 4L20 5M4 4h8M4 20h16"/></>,
    Connections: <><path d="M9 4H5v4m10-4h4v4M5 16v4h4m6 0h4v-4M8 12h8"/></>,
    'Connect MCP': <><path d="M8 3v5m8-5v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4"/></>,
    arrow: <><path d="M5 12h14m-6-6 6 6-6 6"/></>,
    check: <path d="m5 12 4 4L20 5"/>,
    close: <path d="m6 6 12 12M6 18 18 6"/>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.Overview}</svg>;
}

function App() {
  const [tab, setTab] = useState('Overview');
  const dialog = useRef(null);
  const opener = useRef(null);
  const [token, setToken] = useState(() => {
    const hash = location.hash.slice(1);
    const value = new URLSearchParams(hash).get('token') || (hash && !hash.includes('=') ? hash : '') || sessionStorage.getItem('console_token') || '';
    if (value) sessionStorage.setItem('console_token', value);
    if (hash) history.replaceState(null, '', location.pathname);
    return value;
  });
  const [draftToken, setDraftToken] = useState('');
  const [runs, setRuns] = useState([]);
  const [capabilities, setCapabilities] = useState(null);
  const [selected, setSelected] = useState(null);
  const [operation, setOperation] = useState('offline');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [filter, setFilter] = useState('all');
  const [copied, setCopied] = useState(false);
  const [host, setHost] = useState('Claude');
  const clientTemplate = host === 'Codex' ? codexTemplate : configTemplate;
  const [needsToken, setNeedsToken] = useState(!token);

  function openRun(run, origin = document.activeElement) { opener.current = origin; setSelected(run); }

  async function api(path, options = {}) {
    const response = await fetch(`/api/${path}`, {
      ...options, headers: {'X-Console-Token': token, ...(options.body ? {'Content-Type':'application/json'} : {}), ...options.headers},
    });
    const result = await response.json();
    if (response.status === 401 || response.status === 403) setNeedsToken(true);
    if (!response.ok) throw new Error(result.error || 'request_failed');
    return result;
  }

  async function refresh() {
    if (!token) { setLoading(false); return; }
    try {
      const [info, data] = await Promise.all([api('capabilities'), api('runs')]);
      setCapabilities(info); setRuns(data.runs); setError(''); setNeedsToken(false);
    } catch (failure) { setError(failure.message); }
    finally { setLoading(false); }
  }

  useEffect(() => { refresh(); const timer = setInterval(refresh, 2000); return () => clearInterval(timer); }, [token]);
  useEffect(() => {
    if (selected) setSelected(current => runs.find(run => run.run_id === current?.run_id) || current);
  }, [runs]);
  useEffect(() => {
    if (!selected) return;
    const previous = opener.current || document.activeElement;
    const close = event => {
      if (event.key === 'Escape') setSelected(null);
      if (event.key === 'Tab') {
        const buttons = dialog.current?.querySelectorAll('button:not(:disabled), a[href], input, select');
        if (!buttons?.length) return;
        const first = buttons[0], last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', close);
    return () => { document.removeEventListener('keydown', close); if (previous?.isConnected) previous.focus(); };
  }, [Boolean(selected)]);

  const busy = runs.some(isBusy);
  const completed = runs.filter(run => ['passed', 'failed'].includes(run.status));
  const visible = runs.filter(run => filter === 'all' || run.status === filter);
  const latestOffline = runs.find(run => run.operation === 'offline' && run.status === 'passed');
  const available = capabilities?.operations || [];

  async function start(kind = operation) {
    if (starting || busy || !capabilities) return;
    const origin = document.activeElement;
    setStarting(true); setError('');
    try {
      const run = await api('runs', {method:'POST', body:JSON.stringify({operation:kind})});
      openRun(run, origin); await refresh();
    } catch (failure) { setError(failure.message); }
    finally { setStarting(false); }
  }

  const status = run => <span className={`status ${run.status}`}><i/>{statuses[run.status] || run.status}</span>;
  const empty = (title, text) => <div className="empty"><div className="empty-icon"><Icon name="Runs" size={26}/></div><h3>{title}</h3><p>{text}</p></div>;
  const table = list => list.length ? <div className="table-scroll"><table><thead><tr><th>Check</th><th>Started</th><th>Outcome</th><th>Passed / total</th><th><span className="sr-only">Details</span></th></tr></thead><tbody>{list.map(run => <tr key={run.run_id}><td><button className="run-name" onClick={() => openRun(run)}>{labels[run.operation] || run.operation}<small>{run.run_id.slice(0,8)}</small></button></td><td>{when(run.created_utc)}</td><td>{status(run)}</td><td>{run.summary?.total != null ? `${run.summary.passed ?? '—'} / ${run.summary.total}` : '—'}</td><td><button className="icon-button" onClick={() => openRun(run)} aria-label={`Inspect ${labels[run.operation]} ${run.run_id.slice(0,8)}`}><Icon name="arrow"/></button></td></tr>)}</tbody></table></div> : runs.length ? empty('No runs match this view', 'Choose another filter or run the check you want to see.') : empty('Your first result starts here', 'Run a check to create a real result. No sample runs are shown.');

  return <div className="shell">
    <aside className="sidebar">
      <a href="#" className="brand" onClick={e => {e.preventDefault(); setTab('Overview');}}><span className="brand-mark"><span/><span/><span/><span/></span>api<span className="brand-light">lab</span><sup>LOCAL</sup></a>
      <div className="workspace"><span className="workspace-icon">A</span><div>Reliability workspace<small>Local API checks</small></div></div>
      <nav aria-label="Workspace navigation">{tabs.map(name => <button key={name} className={tab === name ? 'nav-item active' : 'nav-item'} onClick={() => {setTab(name); setSelected(null);}} aria-current={tab === name ? 'page' : undefined}><Icon name={name}/>{name}{name === 'Runs' && runs.length > 0 && <span className="nav-count">{runs.length}</span>}</button>)}<a className="nav-item" href="/architecture" target="_blank" rel="noreferrer"><Icon name="Overview"/>Architecture<span className="external">↗</span></a></nav>
      <div className="sidebar-note"><span className="local-dot"/>Your machine. Your results.<p>Checks run locally. This console shows summaries; raw evidence stays in your sandbox.</p></div>
      <div className="sidebar-footer"><span className="avatar">AP</span><div>Personal workspace<small>No account required</small></div></div>
    </aside>
    <main>
      <header className="topbar"><span>Workspace <span className="breadcrumb">/</span> <strong>{tab}</strong></span><span className="local-pill"><span className="local-dot"/>Local session</span></header>
      <div className="content">
        {needsToken && <section className="connect-card"><h2>Connect to your local session</h2><p>Open the launch link printed by the console server, or paste its session token here. It stays in this browser tab.</p><form onSubmit={e => {e.preventDefault(); sessionStorage.setItem('console_token', draftToken.trim()); setToken(draftToken.trim()); setDraftToken('');}}><label className="sr-only" htmlFor="session-token">Session token</label><input id="session-token" type="password" autoComplete="off" value={draftToken} onChange={e => setDraftToken(e.target.value)} required placeholder="Local session token"/><button className="primary" type="submit">Connect</button></form></section>}
        {error && <div className="error" role="alert">{error === 'execution_in_progress' ? 'A check is already running. Wait for its result before starting another.' : `Could not complete the request (${error}). Check that the local server is running.`}<button className="text-button" onClick={refresh}>Try again</button></div>}
        {tab === 'Overview' && <>
          <div className="hero"><div><span className="eyebrow">A LITTLE CERTAINTY GOES A LONG WAY</span><h1>Run checks.<br/><em>See results.</em></h1><p>Small checks. Clear evidence.<br/>One calm place to see how your API holds up.</p></div><div className="hero-art" aria-hidden="true"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="art-center"><Icon name="check" size={45}/></div><span className="art-label">Built on evidence</span><span className="spark spark-one">✦</span><span className="spark spark-two">✧</span></div></div>
          <div className="stats"><article><span>Recorded runs</span><strong>{loading ? '—' : runs.length}</strong><small>In this local workspace</small></article><article><span>Completed checks</span><strong>{loading ? '—' : completed.length}</strong><small>{completed.filter(run => run.status === 'failed').length} failed runs remain visible</small></article><article><span>Latest offline tests</span><strong>{latestOffline?.summary ? `${latestOffline.summary.passed} / ${latestOffline.summary.total}` : '—'}</strong><small>{latestOffline ? when(latestOffline.finished_utc) : 'Waiting for your first offline run'}</small></article></div>
          <section className="launch-card"><div className="section-heading"><div><span className="eyebrow">START SOMETHING USEFUL</span><h2>Your next check</h2></div><span className="tag">No external API needed</span></div><div className="launch-options">{['offline','contracts','evaluation'].map(kind => <button key={kind} className={`check-option ${operation === kind ? 'chosen' : ''}`} onClick={() => setOperation(kind)} aria-pressed={operation === kind}><span className="radio"/><strong>{labels[kind]}</strong><small>{descriptions[kind]}</small></button>)}</div><div className="launch-footer"><span>{busy ? 'A check is running. You can keep browsing.' : 'Creates a new run. Previous evidence is preserved.'}</span><button className="primary" disabled={starting || busy || !capabilities || needsToken} onClick={() => start()}>{starting || busy ? 'Check in progress' : 'Run check'}<Icon name="arrow" size={18}/></button></div></section>
          <section className="results-card"><div className="section-heading"><div><h2>A little more clarity</h2><p>Your recent results, exactly as they happened.</p></div><button className="text-button" onClick={() => setTab('Runs')}>View all runs ↗</button></div>{table(runs.slice(0,4))}</section>
        </>}
        {tab === 'Runs' && <><div className="page-heading"><span className="eyebrow">THE EVIDENCE, ALL TOGETHER</span><h1>Every check counts.</h1><p>Inspect outcomes without exposing raw logs or local file paths.</p></div><section className="results-card"><div className="section-heading"><h2>Recorded runs</h2><label className="filter">Show <select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All outcomes</option>{Object.entries(statuses).map(([value,label]) => <option value={value} key={value}>{label}</option>)}</select></label></div>{table(visible)}</section></>}
        {tab === 'History' && <><div className="page-heading"><span className="eyebrow">KEEP THE WHOLE PICTURE</span><h1>A record, over time.</h1><p>Each tile is a run. Select one to see its outcome.</p></div><section className="results-card"><div className="section-heading"><h2>Run journal</h2><span className="tag">{runs.length} observations</span></div>{runs.length ? <div className="journal">{[...runs].reverse().map(run => <button key={run.run_id} className={`journal-tile ${run.status}`} onClick={() => openRun(run)} aria-label={`${labels[run.operation]}, ${when(run.created_utc)}, ${statuses[run.status]}`}><Icon name={run.status === 'passed' ? 'check' : 'Runs'} size={24}/><strong>{labels[run.operation]}</strong><small>{when(run.created_utc)}</small>{status(run)}</button>)}</div> : empty('Give your checks a history', 'Each completed run will appear here, including failures.')}<div className="footnote">This journal shows run outcomes. It does not classify flaky tests. Use the context-aware CLI history report for comparisons across matching test, code, and environment contexts.</div></section></>}
        {tab === 'Evaluation' && <><div className="page-heading"><span className="eyebrow">DIFFERENT OUTPUT. THE SAME STANDARD.</span><h1>Check the properties.</h1><p>Evaluate structured responses without expecting identical answers.</p></div><section className="launch-card evaluation-card"><div className="evaluation-symbol"><Icon name="Evaluation" size={40}/></div><h2>A small, honest sample</h2><p>Four synthetic response records. Two model/prompt groups. Schema checks and approved numeric invariants. No model calls, API key, or provider cost.</p><div className="tag-row"><span className="tag">JSON Schema</span><span className="tag">Numeric properties</span><span className="tag">Version grouping</span></div><button className="primary" disabled={starting || busy || !capabilities || needsToken} onClick={() => start('evaluation')}>Evaluate sample<Icon name="arrow" size={18}/></button><div className="footnote">The sample does not validate a live provider. Groups below 20 observations do not report p95.</div></section><section className="results-card"><div className="section-heading"><h2>Evaluation runs</h2></div>{table(runs.filter(run => run.operation === 'evaluation'))}</section></>}
        {tab === 'Connections' && <Connections key={token} api={api} start={start} busy={busy || starting} disabled={needsToken || !capabilities}/> }
        {tab === 'Connect MCP' && <><div className="page-heading"><span className="eyebrow">ONE WORKSPACE. ANOTHER WAY IN.</span><h1>Bring your assistant.</h1><p>Use the same bounded local checks from an MCP-compatible desktop host.</p></div><section className="results-card setup-card"><div className="host-heading"><h2>Choose your assistant</h2><span className="tag">Recommended hosts</span></div><div className="host-options">{['Claude','Codex'].map(name => <button key={name} className={host === name ? 'host-option selected' : 'host-option'} aria-pressed={host === name} onClick={() => {setHost(name); setCopied(false);}}><strong>{name}</strong><small>{name === 'Claude' ? 'JSON · Claude Desktop or Claude Code' : 'TOML · Codex CLI or IDE'}</small></button>)}</div><p>Your assistant handles model sign-in or provider API keys. Offline tools need no model key. Optional connection checks use profiles entered in Connections; model text generation is not implemented. Both hosts receive the same structured run summaries.</p><span className="step-number">01</span><h2>Prepare the connector</h2><p>From your activated core environment, run the setup helper. It installs the optional MCP SDK in a separate sandbox environment and prints a configuration with your actual local paths.</p><pre>{`python scripts/setup_mcp.py --format ${host.toLowerCase()} --console-state "<CONSOLE_STATE_JSON>"`}</pre><span className="step-number">02</span><h2>Add the printed configuration</h2><p>Paste it into your host's MCP settings. The template below explains the required fields; replace every placeholder or use the setup helper's output.</p><div className="code-heading"><span>{host} configuration template</span><button className="text-button" onClick={async () => {try {await navigator.clipboard.writeText(clientTemplate); setCopied(true);} catch {setCopied(false); setError('clipboard_unavailable');}}}>{copied ? 'Copied template' : 'Copy template'}</button></div><pre>{clientTemplate}</pre><div className="bridge-guide"><h2>Share Connections with VS Code</h2><p>Keep the console running and use the console bridge. It reads the launcher state on each call and uses the same in-memory connections. No keys belong in host settings or chat.</p><pre>{`python scripts/setup_mcp.py --format ${host.toLowerCase()} --console-state "<SANDBOX>/desktop/<CHECKOUT_ID>/state.json"`}</pre><p>Use the private state.json path created by the Linux launcher. Standalone MCP has a separate process session and cannot see keys entered in this console.</p></div><span className="step-number">03</span><h2>Ask for a check</h2><p>“List available API checks, run the contract baseline, and show the result.” Tools list connection flags, start a fixed operation, and inspect sanitized results. Raw files and arbitrary commands are outside this interface.</p><div className="footnote">Standard input/output transport. No public endpoint or hosted account. Your MCP host controls tool permissions.</div></section></>}
        <footer className="page-footer"><span>API Testing Framework · Local reliability checks</span><span>{available.length ? `${available.length} local checks available` : 'Connect a local session to get started'}</span></footer>
      </div>
    </main>
    {selected && <div className="drawer-backdrop" onClick={() => setSelected(null)}><section className="drawer" ref={dialog} role="dialog" aria-modal="true" aria-labelledby="run-title" onClick={e => e.stopPropagation()}><button className="icon-button drawer-close" autoFocus onClick={() => setSelected(null)} aria-label="Close run details"><Icon name="close"/></button><span className="eyebrow">RUN DETAILS</span><h2 id="run-title">{labels[selected.operation] || selected.operation}</h2>{status(selected)}<dl><dt>Run ID</dt><dd className="mono">{selected.run_id}</dd><dt>Started</dt><dd>{when(selected.created_utc)}</dd><dt>Finished</dt><dd>{when(selected.finished_utc)}</dd></dl>{selected.summary && <div className="detail-counts">{['total','passed','failed','skipped','incomplete'].filter(key => selected.summary[key] != null).map(key => <div key={key}><strong>{selected.summary[key]}</strong><span>{key}</span></div>)}</div>}{selected.error_code && <div className="error">Check did not complete successfully: {selected.error_code}</div>}<p className="drawer-note">{isBusy(selected) ? 'This check is running. The result updates automatically.' : 'This is a summary of one execution, not a guarantee about another environment.'} Raw evidence stays in the configured sandbox.</p><button className="secondary" onClick={() => {setSelected(null); setTab('Runs');}}>View all runs</button></section></div>}
  </div>;
}

createRoot(document.getElementById('root')).render(<App/>);
