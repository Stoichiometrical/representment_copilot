import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

function icon(paths) {
  return function Icon({ className = "" }) {
    return <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths}</svg>;
  };
}

const AlertTriangle = icon(<><path d="M10.3 3.7 2.2 18a2 2 0 0 0 1.7 3h16.2a2 2 0 0 0 1.7-3L13.7 3.7a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></>);
const ArrowUpRight = icon(<><path d="M7 17 17 7"/><path d="M7 7h10v10"/></>);
const Check = icon(<path d="m5 12 4 4L19 6"/>);
const ChevronRight = icon(<path d="m9 18 6-6-6-6"/>);
const CircleDot = icon(<><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2"/></>);
const Clock3 = icon(<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>);
const FileSearch = icon(<><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h8"/><path d="M14 2v6h6"/><circle cx="17" cy="17" r="3"/><path d="m19.5 19.5 2 2"/></>);
const FileText = icon(<><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h6"/></>);
const FolderInput = icon(<><path d="M3 6a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="m12 10 3 3-3 3M8 13h7"/></>);
const LoaderCircle = icon(<><path d="M21 12a9 9 0 1 1-6.2-8.6"/></>);
const Plus = icon(<><path d="M12 5v14M5 12h14"/></>);
const RefreshCw = icon(<><path d="M20 7h-5V2"/><path d="M20 7a9 9 0 1 0 1 8"/></>);
const Search = icon(<><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>);
const ShieldCheck = icon(<><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></>);
const Upload = icon(<><path d="M12 16V4M7 9l5-5 5 5"/><path d="M5 20h14"/></>);
const X = icon(<><path d="M18 6 6 18M6 6l12 12"/></>);

const ACTIONS = {
  represent: "Represent",
  accept_liability: "Accept liability",
  request_more_evidence: "Request evidence",
};

const emptyManual = {
  case_id: "",
  scheme: "visa",
  reason_code: "13.1",
  reason_code_label: "",
  chargeback_date: "",
  amount: "",
  currency: "GBP",
  transaction_id: "",
  merchant_name: "",
  merchant_mcc: "",
  transaction_date: "",
  card_bin_country: "",
  avs_result: "",
  cvv_result: "",
  three_ds_status: "not_attempted",
  ip_address: "",
  device_fingerprint: "",
  billing_address_postcode: "",
  shipping_address_postcode: "",
  issuer_narrative: "",
};

async function api(path, options) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "Request failed");
  return payload;
}

function money(value, currency) {
  if (value == null) return "—";
  try {
    return new Intl.NumberFormat("en-GB", {
      style: "currency",
      currency: currency || "GBP",
    }).format(value);
  } catch {
    return `${currency || ""} ${value}`;
  }
}

function ActionBadge({ action }) {
  if (!action) return <span className="badge neutral">Unprocessed</span>;
  return <span className={`badge action ${action}`}>{ACTIONS[action]}</span>;
}

function StatusMark({ status }) {
  const icon = status === "satisfied" ? <Check /> : status === "partial" ? <CircleDot /> : <X />;
  return <span className={`status-mark ${status}`}>{icon}<b>{status?.replace("_", " ")}</b></span>;
}

function Queue({ cases, selected, onSelect, query, setQuery, filter, setFilter }) {
  const filtered = useMemo(() => cases.filter((item) => {
    const haystack = `${item.case_id} ${item.merchant} ${item.reason_code} ${item.reason_code_label}`.toLowerCase();
    const actionMatch = filter === "all" || (filter === "unprocessed" ? !item.recommended_action : item.recommended_action === filter);
    return actionMatch && haystack.includes(query.toLowerCase());
  }), [cases, query, filter]);

  return <aside className="queue">
    <div className="queue-title"><div><span className="eyebrow">ANALYST QUEUE</span><h2>Chargebacks</h2></div><strong>{filtered.length}</strong></div>
    <label className="search"><Search /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search cases" /></label>
    <div className="filters">
      {["all", "unprocessed", "request_more_evidence"].map((value) => <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{value === "all" ? "All" : value === "unprocessed" ? "Ready" : "Needs evidence"}</button>)}
    </div>
    <div className="queue-list">
      {filtered.map((item) => <button key={item.case_id} className={`queue-item ${selected === item.case_id ? "selected" : ""}`} onClick={() => onSelect(item.case_id)}>
        <div className="queue-line"><code>{item.case_id.replace("CB-2025-", "CB-")}</code><span>{money(item.amount, item.currency)}</span></div>
        <h3>{item.merchant}</h3>
        <div className="queue-meta"><span>{item.scheme?.toUpperCase()} {item.reason_code}</span><span>{item.document_count} docs</span></div>
        <ActionBadge action={item.recommended_action} />
      </button>)}
      {!filtered.length && <div className="queue-empty">No cases match this view.</div>}
    </div>
  </aside>;
}

function FactTable({ transaction }) {
  const rows = [
    ["Transaction ID", transaction.transaction_id], ["Transaction date", transaction.transaction_date],
    ["MCC", transaction.merchant_mcc], ["BIN country", transaction.card_bin_country],
    ["AVS", transaction.avs_result], ["CVV", transaction.cvv_result],
    ["3-D Secure", transaction.three_ds_status], ["IP address", transaction.ip_address],
    ["Device", transaction.device_fingerprint], ["Billing postcode", transaction.billing_address_postcode],
    ["Shipping postcode", transaction.shipping_address_postcode],
  ];
  return <div className="fact-table">{rows.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value || "—"}</strong></div>)}</div>;
}

function EvidenceMatrix({ assessments, onCitation }) {
  const satisfied = assessments.filter((item) => item.status === "satisfied").length;
  return <section className="panel matrix-panel">
    <div className="section-head"><div><span className="eyebrow">03 · EVIDENCE MATRIX</span><h2>What the submission proves</h2></div><span className="coverage">{satisfied}/{assessments.length} satisfied</span></div>
    <div className="matrix">
      {assessments.map((item, index) => <article className="requirement" key={item.requirement_id}>
        <div className="requirement-index">{String(index + 1).padStart(2, "0")}</div>
        <div className="requirement-body">
          <div className="requirement-title"><h3>{item.requirement}</h3><StatusMark status={item.status} /></div>
          <p>{item.assessment}</p>
          {!!item.gaps?.length && <div className="gap"><AlertTriangle /> <span>{item.gaps.join(" · ")}</span></div>}
          <div className="citations">
            {item.evidence?.map((source) => <button key={source.chunk_id} onClick={() => onCitation(source)}><FileSearch /> <span>{source.document}</span><b>{source.location}</b><ChevronRight /></button>)}
            {!item.evidence?.length && <span className="no-source">No supporting source cited</span>}
          </div>
        </div>
      </article>)}
    </div>
  </section>;
}

function SourceInspector({ bundle, selectedSource, onSelectSource }) {
  const documents = bundle?.documents || [];
  const [doc, setDoc] = useState(null);
  const [chunks, setChunks] = useState([]);
  const [chunkLoading, setChunkLoading] = useState(false);
  const caseId = bundle?.case?.case_id;

  useEffect(() => {
    const next = selectedSource?.document || documents[0]?.filename || null;
    if (next) setDoc(next);
  }, [caseId, selectedSource?.document, documents.length]);

  useEffect(() => {
    if (!caseId || !doc) { setChunks([]); return; }
    setChunkLoading(true);
    api(`/api/cases/${encodeURIComponent(caseId)}/chunks?filename=${encodeURIComponent(doc)}`)
      .then(setChunks).catch(() => setChunks([])).finally(() => setChunkLoading(false));
  }, [caseId, doc, bundle?.workup?.generated_at]);

  const isImage = /\.(png|jpe?g|webp)$/i.test(doc || "");
  const sourceUrl = doc ? `/api/cases/${encodeURIComponent(caseId)}/documents/${encodeURIComponent(doc)}` : "";
  return <aside className="inspector">
    <div className="inspector-head"><div><span className="eyebrow">SOURCE INSPECTOR</span><h2>Verify evidence</h2></div>{doc && <a href={sourceUrl} target="_blank" rel="noreferrer"><ArrowUpRight /></a>}</div>
    <div className="doc-tabs">{documents.map((item, index) => <button className={doc === item.filename ? "active" : ""} key={item.filename} onClick={() => { setDoc(item.filename); onSelectSource(null); }}><span>{String(index + 1).padStart(2, "0")}</span><div><b>{item.filename.replace(`${caseId}_`, "")}</b><small>{item.page_count || "—"} pages · {item.chunk_count || 0} chunks</small></div></button>)}</div>
    {doc ? <>
      <div className="preview">
        {isImage ? <img src={sourceUrl} alt={doc} /> : <iframe title={doc} src={`${sourceUrl}${selectedSource?.page ? `#page=${selectedSource.page}` : ""}`} />}
      </div>
      {selectedSource?.document === doc && <div className="cited-excerpt"><span>CITED · {selectedSource.location}</span><p>{selectedSource.snippet}</p><small>{selectedSource.supports}</small></div>}
      <div className="chunk-head"><span>Extracted source text</span><b>{chunks.length} chunks</b></div>
      <div className="chunks">{chunkLoading ? <LoaderCircle className="spin" /> : chunks.map((chunk) => <article className={selectedSource?.chunk_id === chunk.chunk_id ? "active" : ""} key={chunk.chunk_id}><div><code>{chunk.chunk_id}</code><span>{chunk.page ? `page ${chunk.page}` : "image"}</span></div><p>{chunk.text}</p></article>)}</div>
    </> : <div className="empty-inspector"><FileText /><p>Select a case document to inspect it.</p></div>}
  </aside>;
}

function DecisionEditor({ bundle, onSaved }) {
  const workup = bundle.workup;
  const [action, setAction] = useState(workup.recommended_action);
  const [rationale, setRationale] = useState(workup.analyst_rationale);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setAction(bundle.override?.action || workup.recommended_action);
    setRationale(bundle.override?.rationale || workup.analyst_rationale);
    setNote(bundle.override?.analyst_note || "");
  }, [bundle.case.case_id, workup.generated_at, bundle.override?.updated_at]);

  async function save() {
    setSaving(true);
    try {
      await api(`/api/cases/${bundle.case.case_id}/override`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, rationale, analyst_note: note }) });
      await onSaved();
    } finally { setSaving(false); }
  }

  return <section className="panel decision-panel">
    <div className="section-head"><div><span className="eyebrow">04 · ANALYST DECISION</span><h2>Edit, override and file</h2></div><ActionBadge action={action} /></div>
    <div className="system-call"><ShieldCheck /><div><span>System recommendation</span><strong>{workup.action_justification}</strong></div></div>
    {!!workup.request_more_evidence?.length && <div className="request-box"><span>REQUEST FROM MERCHANT</span><ul>{workup.request_more_evidence.map((item, index) => <li key={index}>{typeof item === "string" ? item : <><b>{item.request_to_merchant || item.missing_requirement}</b>{item.why_needed && <small>{item.why_needed}</small>}</>}</li>)}</ul></div>}
    <label className="field-label">Recommended action</label>
    <div className="action-picker">{Object.entries(ACTIONS).map(([value, label]) => <button className={action === value ? `selected ${value}` : ""} onClick={() => setAction(value)} key={value}>{label}</button>)}</div>
    <label className="field-label" htmlFor="rationale">Representment rationale</label>
    <textarea id="rationale" rows="6" value={rationale} onChange={(e) => setRationale(e.target.value)} />
    <label className="field-label" htmlFor="note">Analyst note / reason for override</label>
    <input id="note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Record why you changed or confirmed the recommendation" />
    <div className="decision-actions"><button className="ghost" onClick={() => navigator.clipboard?.writeText(rationale)}>Copy rationale</button><button className="primary" disabled={saving || !rationale.trim()} onClick={save}>{saving ? <LoaderCircle className="spin" /> : <Check />} Save decision</button></div>
  </section>;
}

function ManualIntake({ open, onClose, onCreated }) {
  const [form, setForm] = useState(emptyManual);
  const [files, setFiles] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  if (!open) return null;
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const rows = [
    ["Case ID", "case_id"], ["Reason code", "reason_code"], ["Reason label", "reason_code_label"],
    ["Chargeback date", "chargeback_date", "date"], ["Amount", "amount", "number"], ["Currency", "currency"],
    ["Merchant", "merchant_name"], ["MCC", "merchant_mcc"], ["Transaction ID", "transaction_id"],
    ["Transaction date", "transaction_date", "datetime-local"], ["BIN country", "card_bin_country"],
    ["AVS result", "avs_result"], ["CVV result", "cvv_result"], ["3DS status", "three_ds_status"],
    ["IP address", "ip_address"], ["Device fingerprint", "device_fingerprint"],
    ["Billing postcode", "billing_address_postcode"], ["Shipping postcode", "shipping_address_postcode"],
  ];

  async function submit(e) {
    e.preventDefault(); setSaving(true); setError("");
    const amount = Number(form.amount);
    const payload = {
      case_id: form.case_id, scheme: form.scheme, reason_code: form.reason_code, reason_code_label: form.reason_code_label,
      chargeback_date: form.chargeback_date, chargeback_amount: { value: amount, currency: form.currency }, issuer_narrative: form.issuer_narrative,
      merchant_evidence_documents: [], transaction: {
        transaction_id: form.transaction_id, merchant_name: form.merchant_name, merchant_mcc: form.merchant_mcc,
        transaction_date: form.transaction_date, amount: { value: amount, currency: form.currency }, card_bin_country: form.card_bin_country,
        avs_result: form.avs_result, cvv_result: form.cvv_result, three_ds_status: form.three_ds_status,
        ip_address: form.ip_address, device_fingerprint: form.device_fingerprint,
        billing_address_postcode: form.billing_address_postcode, shipping_address_postcode: form.shipping_address_postcode,
      },
    };
    const body = new FormData(); body.append("case_json", JSON.stringify(payload)); files.forEach((file) => body.append("files", file));
    try { const result = await api("/api/cases/manual", { method: "POST", body }); setForm(emptyManual); setFiles([]); onCreated(result.case.case_id); onClose(); }
    catch (err) { setError(err.message); } finally { setSaving(false); }
  }

  return <div className="modal-backdrop"><form className="modal" onSubmit={submit}>
    <div className="modal-head"><div><span className="eyebrow">RAW CASE INTAKE</span><h2>Add a chargeback manually</h2><p>Enter source transaction fields and attach the merchant submission.</p></div><button type="button" onClick={onClose}><X /></button></div>
    <div className="intake-table"><label><span>Scheme</span><select value={form.scheme} onChange={(e) => set("scheme", e.target.value)}><option value="visa">Visa</option><option value="mastercard">Mastercard</option><option value="other">Other</option></select></label>{rows.map(([label, key, type]) => <label key={key}><span>{label}</span><input required={["case_id", "reason_code", "chargeback_date", "amount", "merchant_name", "transaction_id"].includes(key)} type={type || "text"} step={type === "number" ? "0.01" : undefined} value={form[key]} onChange={(e) => set(key, e.target.value)} /></label>)}</div>
    <label className="narrative-input"><span>Issuer narrative</span><textarea required rows="4" value={form.issuer_narrative} onChange={(e) => set("issuer_narrative", e.target.value)} /></label>
    <label className="upload-zone"><Upload /><div><b>Attach merchant evidence</b><span>PDF, PNG, JPG or WebP · up to 20 MB each</span></div><input multiple accept=".pdf,.png,.jpg,.jpeg,.webp" type="file" onChange={(e) => setFiles([...e.target.files])} /></label>
    {!!files.length && <div className="file-list">{files.map((file) => <span key={file.name}><FileText />{file.name}</span>)}</div>}
    {error && <div className="form-error">{error}</div>}
    <div className="modal-actions"><button className="ghost" type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={saving}>{saving ? <LoaderCircle className="spin" /> : <Plus />} Add to queue</button></div>
  </form></div>;
}

function Workspace({ bundle, processing, onProcess, onRefresh, selectedSource, setSelectedSource }) {
  if (!bundle) return <main className="welcome"><div><FolderInput /><h1>Load the case queue</h1><p>Import the supplied cases, select one, and run its evidence-to-workup pipeline.</p></div></main>;
  const { case: chargeback, workup } = bundle;
  const tx = chargeback.transaction;
  return <>
    <main className="workspace">
      <section className="case-hero">
        <div><div className="hero-line"><code>{chargeback.case_id}</code>{workup && <ActionBadge action={bundle.override?.action || workup.recommended_action} />}</div><h1>{tx.merchant_name}</h1><p>{chargeback.scheme.toUpperCase()} {chargeback.reason_code} · {chargeback.reason_code_label}</p></div>
        <div className="hero-right"><span>Disputed amount</span><strong>{money(chargeback.chargeback_amount.value, chargeback.chargeback_amount.currency)}</strong><small>Raised {chargeback.chargeback_date}</small><button className="primary run" disabled={processing} onClick={onProcess}>{processing ? <LoaderCircle className="spin" /> : <RefreshCw />} {workup ? "Refresh analysis" : "Process case"}</button></div>
      </section>
      <section className="issuer"><span>ISSUER ALLEGATION</span><p>“{chargeback.issuer_narrative}”</p></section>
      {!workup ? <section className="unprocessed panel"><Clock3 /><h2>Ready for analysis</h2><p>The three-stage engine will extract the evidence, apply the reason-code rule, recommend an action and prepare the rationale.</p><div className="document-pills">{bundle.documents.map((doc) => <span key={doc.filename}><FileText />{doc.filename.replace(`${chargeback.case_id}_`, "")}</span>)}</div><button className="primary" disabled={processing} onClick={onProcess}>{processing ? <LoaderCircle className="spin" /> : <ShieldCheck />} Run representment workup</button></section> : <>
        <div className="summary-grid">
          <section className="panel standard"><span className="eyebrow">01 · REASON-CODE STANDARD</span><h2>{workup.reason_code_summary.code} · {workup.reason_code_summary.name}</h2><h3>{workup.reason_code_summary.issuer_allegation}</h3><p>{workup.reason_code_summary.evidence_standard}</p><ul className="standard-list">{workup.reason_code_summary.compelling_evidence?.map((requirement, index) => <li key={index}>{requirement}</li>)}</ul><div className="logic"><b>{workup.reason_code_summary.logic?.toUpperCase()}</b><span>Minimum required: {workup.reason_code_summary.minimum_required ?? "—"}</span></div></section>
          <section className="panel"><span className="eyebrow">02 · TRANSACTION FACTS</span><FactTable transaction={tx} /></section>
        </div>
        <EvidenceMatrix assessments={workup.evidence_assessment} onCitation={setSelectedSource} />
        <DecisionEditor bundle={bundle} onSaved={onRefresh} />
      </>}
    </main>
    <SourceInspector bundle={bundle} selectedSource={selectedSource} onSelectSource={setSelectedSource} />
  </>;
}

function App() {
  const [cases, setCases] = useState([]);
  const [selected, setSelected] = useState(null);
  const [bundle, setBundle] = useState(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [processing, setProcessing] = useState(false);
  const [loadingCases, setLoadingCases] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [selectedSource, setSelectedSource] = useState(null);
  const [toast, setToast] = useState("");

  async function refreshCases() { const result = await api("/api/cases"); setCases(result); return result; }
  async function loadBundle(id) { if (!id) return; setSelectedSource(null); setBundle(await api(`/api/cases/${id}`)); }
  useEffect(() => { refreshCases().then((items) => { if (items[0]) setSelected(items[0].case_id); }).catch(() => {}); }, []);
  useEffect(() => { if (selected) loadBundle(selected).catch((err) => setToast(err.message)); }, [selected]);

  async function loadCases() {
    setLoadingCases(true);
    try { const result = await api("/api/cases/load", { method: "POST" }); setCases(result.cases); if (!selected && result.cases[0]) setSelected(result.cases[0].case_id); setToast(`${result.loaded} cases loaded`); }
    catch (err) { setToast(err.message); } finally { setLoadingCases(false); }
  }
  async function processSelected() {
    setProcessing(true); setToast("Processing evidence, decision and workup…");
    try { const result = await api(`/api/cases/${selected}/process`, { method: "POST" }); setBundle(result); await refreshCases(); setToast("Workup ready for review"); }
    catch (err) { setToast(err.message); } finally { setProcessing(false); }
  }

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span>R</span><div><b>Representment</b><small>Analyst desk</small></div></div><div className="top-actions"><button className="ghost" onClick={() => setManualOpen(true)}><Plus /> Add case</button><button className="primary" onClick={loadCases} disabled={loadingCases}>{loadingCases ? <LoaderCircle className="spin" /> : <FolderInput />} Load cases</button></div></header>
    <div className="layout"><Queue cases={cases} selected={selected} onSelect={setSelected} query={query} setQuery={setQuery} filter={filter} setFilter={setFilter} /><Workspace bundle={bundle} processing={processing} onProcess={processSelected} onRefresh={() => loadBundle(selected)} selectedSource={selectedSource} setSelectedSource={setSelectedSource} /></div>
    <ManualIntake open={manualOpen} onClose={() => setManualOpen(false)} onCreated={async (id) => { await refreshCases(); setSelected(id); }} />
    {toast && <button className="toast" onClick={() => setToast("")}>{toast}<X /></button>}
  </div>;
}

createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);
