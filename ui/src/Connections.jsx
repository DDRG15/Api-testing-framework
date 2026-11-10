import React, {useEffect, useRef, useState} from 'react';

const initialSchema = JSON.stringify({type:'object', required:['status'], properties:{status:{const:'ok'}}}, null, 2);
const messages = {
  invalid_target_url:'Use HTTPS, or HTTP on loopback, without URL credentials, query strings or fragments.',
  invalid_contract_schema:'Enter a valid, nonempty JSON Schema object.',
  schema_references_not_supported:'Use an inline schema without references.',
  invalid_credential:'Enter a key without whitespace or control characters.',
  invalid_auth_header:'Choose a valid authentication header, such as X-API-Key.',
};

export default function Connections({api, start, busy, disabled}) {
  const [connections, setConnections] = useState([]);
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [url, setUrl] = useState('');
  const [auth, setAuth] = useState('none');
  const [header, setHeader] = useState('X-API-Key');
  const [schema, setSchema] = useState(initialSchema);
  const [expected, setExpected] = useState('200');
  const [dirty, setDirty] = useState({target:true, openai:false, anthropic:false});
  const markDirty = kind => setDirty(current => ({...current, [kind]:true}));
  const targetKey = useRef(null), openaiKey = useRef(null), anthropicKey = useRef(null);
  const keyRefs = {target:targetKey, openai:openaiKey, anthropic:anthropicKey};
  const configured = kind => connections.find(item => item.kind === kind)?.configured;

  async function refresh() {
    try {const result = await api('connections'); setConnections(result.connections);}
    catch {setError('Connections are unavailable. Check your local session.');}
  }
  useEffect(() => {refresh(); const timer=setInterval(refresh,3000); return () => clearInterval(timer);}, []);

  async function save(kind, event) {
    event.preventDefault(); setError(''); setNotice('');
    let contract;
    if (kind === 'target') {
      try {contract=JSON.parse(schema);} catch {setError(messages.invalid_contract_schema); return;}
    }
    const input=keyRefs[kind].current;
    const secret=input?.value || '';
    if (input) input.value='';
    const body=kind === 'target' ? {url, auth_mode:auth, header_name:header, secret:auth === 'none' ? '' : secret, expected_status:Number(expected), schema:contract} : {secret};
    setWorking(true);
    try {
      const result=await api(`connections/${kind}`,{method:'POST',body:JSON.stringify(body)});
      setConnections(result.connections); setDirty(current => ({...current,[kind]:false})); setNotice('Saved for this server session. Run a check to verify the connection.');
    } catch (failure) {setError(messages[failure.message] || 'Could not save the connection. Check the fields and local session.');}
    finally {setWorking(false);}
  }

  async function disconnect(kind) {
    setWorking(true); setError(''); setNotice('');
    for (const ref of Object.values(keyRefs)) if (ref.current) ref.current.value='';
    try {
      const result=await api('connections/disconnect',{method:'POST',body:JSON.stringify({kind})});
      setConnections(result.connections); setNotice('Disconnected. Completed summaries are preserved.');
    } catch {setError('Could not disconnect. Check your local session.');}
    finally {setWorking(false);}
  }

  const actions=kind => <div className="connection-actions"><button className="primary" type="submit" disabled={disabled || working}>Save for this session</button><button className="secondary" type="button" disabled={disabled || working || busy || !configured(kind) || dirty[kind]} onClick={() => start(kind)}>{kind === 'target' ? 'Check target' : 'Check authentication'}</button><button className="text-button" type="button" disabled={disabled || working || !configured(kind)} onClick={() => disconnect(kind)}>Disconnect</button></div>;
  const badge=kind => <span className="tag">{configured(kind) ? 'Configured in memory' : 'Not configured'}</span>;
  return <>
    <div className="page-heading"><span className="eyebrow">YOUR API. YOUR CONNECTIONS.</span><h1>Choose what to check.</h1><p>Configure one JSON endpoint and optional AI providers. Keys stay out of saved reports and browser storage.</p></div>
    {error && <div className="error" role="alert">{error}</div>}
    {notice && <div className="connection-notice" role="status">{notice}</div>}
    <section className="results-card connection-card"><div className="section-heading"><div><h2>API under test</h2><p>One GET request, an expected HTTP status and your inline JSON Schema.</p></div>{badge('target')}</div>
      <form onSubmit={event => save('target',event)}><fieldset disabled={working || disabled}>
        <label>Endpoint URL<input type="url" value={url} onChange={event => {setUrl(event.target.value); markDirty('target');}} placeholder="https://api.example.com/health" required autoComplete="off"/></label>
        <div className="connection-fields"><label>Authentication<select value={auth} onChange={event => {setAuth(event.target.value); markDirty('target'); if(targetKey.current) targetKey.current.value='';}}><option value="none">None</option><option value="bearer">Bearer token</option><option value="header">API key header</option></select></label><label>Expected HTTP status<input type="number" min="200" max="299" value={expected} onChange={event => {setExpected(event.target.value); markDirty('target');}} required/></label></div>
        {auth === 'header' && <label>Authentication header<input value={header} onChange={event => {setHeader(event.target.value); markDirty('target');}} required maxLength="64" autoComplete="off"/></label>}
        {auth !== 'none' && <label>Target API credential<input ref={targetKey} onChange={() => markDirty('target')} type="password" autoComplete="off" spellCheck="false" maxLength="4096" required placeholder="Enter a new credential to save"/></label>}
        <label>JSON Schema<textarea value={schema} onChange={event => {setSchema(event.target.value); markDirty('target');}} rows="8" required spellCheck="false" maxLength="16384"/></label>
        {actions('target')}
      </fieldset></form><div className="footnote">Save edited fields before checking. Re-enter and save the target profile after reloading this view. HTTPS except on loopback. No redirects or retries. This checks one response contract; it does not adapt the booking suite to another API. Raw response bodies are not saved.</div>
    </section>
    <section className="results-card connection-card"><div className="section-heading"><div><h2>Optional AI providers</h2><p>Check authentication against a provider's model catalog.</p></div><span className="tag">No text generation</span></div>
      {['openai','anthropic'].map(kind => <form key={kind} className="provider-form" onSubmit={event => save(kind,event)}><fieldset disabled={working || disabled}><div className="host-heading"><h3>{kind === 'openai' ? 'OpenAI' : 'Anthropic'}</h3>{badge(kind)}</div><label>{kind === 'openai' ? 'OpenAI' : 'Anthropic'} API key<input ref={keyRefs[kind]} onChange={() => markDirty(kind)} type="password" autoComplete="off" spellCheck="false" required maxLength="4096" placeholder="Enter your provider API key"/></label>{actions(kind)}</fieldset></form>)}
      <div className="footnote">Checks contact the provider's fixed catalog endpoint. A passing check does not prove inference access or evaluate a model. Provider keys are separate from the target API credential.</div>
    </section>
    <section className="results-card connection-card"><h2>A session you control</h2><p>Connections live in this console process. Restarting it forgets all credentials. Closing a tab leaves the server session running. Disconnect removes the saved profile; an already running request may finish with its captured configuration.</p><button className="secondary" disabled={working || disabled} onClick={() => disconnect('all')}>Disconnect all connections</button><p>From VS Code, use the console bridge in Connect MCP to share these connections. Enter keys here rather than in assistant messages or tool arguments.</p></section>
  </>;
}
