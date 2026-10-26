import { useCallback, useEffect, useRef, useState } from 'react';
import { FileText, Plus, Search, SlidersHorizontal, X } from 'lucide-react';

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8014';
type SafetyLevel = 'low' | 'medium' | 'high' | 'critical';
type Article = { id: number; title: string; symptoms: string; source_name: string; source_url: string;
  document_version: string; vehicle_make: string; vehicle_model: string; year_from: number | null;
  year_to: number | null; engine_code: string; safety_level: SafetyLevel; status: 'draft' | 'published';
  reviewed_by: number | null; technical_reviewed_by: number | null; technical_reviewed_at: string | null;
  technical_reviewer_name: string | null; publisher_name?: string | null; document_filename: string | null;
  document_uploaded_at: string | null; updated_at: string; revision: number; withdrawn_at: string | null };
type Detail = Article & { content: string; safety: string; chunk_count: number;
  chunks: { chunk_index: number; content: string }[];
  history: { id: number; revision: number; action: string; actor_name: string | null; reason: string;
    document_filename: string | null; created_at: string }[] };
type Form = Pick<Detail, 'title' | 'symptoms' | 'content' | 'safety' | 'source_name' | 'source_url' |
  'document_version' | 'vehicle_make' | 'vehicle_model' | 'year_from' | 'year_to' | 'engine_code' | 'safety_level'>;
type Filters = { q: string; review: string; safety_level: string; vehicle_make: string; vehicle_model: string;
  technical_reviewer: string; publisher: string; has_document: string; has_source: string; updated_since: string; sort: string };
const blank: Form = { title: '', symptoms: '', content: '', safety: '', source_name: '', source_url: '',
  document_version: '', vehicle_make: '', vehicle_model: '', year_from: null, year_to: null, engine_code: '', safety_level: 'medium' };
const initialFilters: Filters = { q: '', review: '', safety_level: '', vehicle_make: '', vehicle_model: '',
  technical_reviewer: '', publisher: '', has_document: '', has_source: '', updated_since: '', sort: 'priority' };
const safetyLabels: Record<SafetyLevel, string> = { low: 'Thấp', medium: 'Trung bình', high: 'Cao', critical: 'Khẩn cấp' };
const tabs = [['', 'Tất cả'], ['draft', 'Bản nháp'], ['pending_technical', 'Chờ duyệt chuyên môn'],
  ['pending_publish', 'Chờ xuất bản'], ['published', 'Đã xuất bản'], ['withdrawn', 'Đã thu hồi'],
  ['source_warning', 'Cần kiểm tra nguồn']] as const;
type Stats = { total: number; draft: number; pending_technical: number; pending_publish: number;
  published: number; withdrawn: number; source_warning: number };
type List = { items: Article[]; total: number; page: number; page_size: number; pages: number; stats: Stats };
type FilterOptions = { reviewers: { id: number; name: string }[]; publishers: { id: number; name: string }[];
  makes: string[]; models: string[] };
const dateText = (value?: string | null) => value ? new Date(value).toLocaleString('vi-VN') : 'Chưa có';
const statusText = (item: Article) => item.status === 'published'
  ? item.reviewed_by ? 'Đã xuất bản · garage duyệt' : 'Tham khảo công khai · chưa duyệt'
  : item.withdrawn_at ? 'Đã thu hồi' : item.technical_reviewed_by ? 'Chờ xuất bản' : 'Chờ duyệt chuyên môn';

export default function TechnicalKnowledgePage({ canPublish }: { canPublish: boolean }) {
  const [draft, setDraft] = useState<Filters>(initialFilters);
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [tab, setTab] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [list, setList] = useState<List | null>(null);
  const [options, setOptions] = useState<FilterOptions>({ reviewers: [], publishers: [], makes: [], models: [] });
  const [selected, setSelected] = useState<Detail | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Form>(blank);
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  const detailRequest = useRef(0);
  const closeButton = useRef<HTMLButtonElement>(null);
  const panelOpen = Boolean(selected || editing || detailLoading);

  const request = useCallback(async (path = '', init: RequestInit = {}) => {
    const response = await fetch(`${API}/api/v1/ai/technical-articles${path}`, {
      ...init, headers: { Authorization: `Bearer ${sessionStorage.getItem('garage_token') || ''}`,
        ...(init.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...init.headers },
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.error?.message || data?.detail || 'Không thực hiện được thao tác.');
    return data;
  }, []);

  useEffect(() => { request('/filter-options').then(data => setOptions(data as FilterOptions)).catch(() => {}); }, [request, refreshKey]);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize), status: tab, sort: filters.sort });
    (Object.keys(filters) as (keyof Filters)[]).forEach(key => { if (key !== 'sort' && filters[key]) params.set(key, filters[key]); });
    setLoading(true); setError('');
    request(`?${params}`, { signal: controller.signal }).then(data => setList(data as List))
      .catch(err => { if (!controller.signal.aborted) setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [request, filters, tab, page, pageSize, refreshKey]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  function closePanel() {
    if (dirty && !window.confirm('Bạn có thay đổi chưa lưu. Đóng mà không lưu?')) return;
    detailRequest.current += 1; setSelected(null); setEditing(false); setDirty(false);
  }
  useEffect(() => {
    if (!panelOpen) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButton.current?.focus();
    return () => previous?.focus();
  }, [panelOpen]);
  useEffect(() => {
    if (!panelOpen) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') closePanel(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [panelOpen, dirty]);
  async function openArticle(id: number, saved = false) {
    if (!saved && dirty && !window.confirm('Bạn có thay đổi chưa lưu. Chuyển bài mà không lưu?')) return;
    const serial = ++detailRequest.current;
    setSelected(null); setEditing(false); setDirty(false); setDetailLoading(true); setError('');
    try { const data = await request(`/${id}`) as Detail;
      if (serial === detailRequest.current) setSelected(data);
    } catch (err) { if (serial === detailRequest.current) setError((err as Error).message); }
    finally { if (serial === detailRequest.current) setDetailLoading(false); }
  }
  function startEdit(article: Detail) {
    setForm(Object.fromEntries((Object.keys(blank) as (keyof Form)[]).map(key => [key, article[key]])) as Form);
    setDirty(false); setEditing(true);
  }
  function setField<K extends keyof Form>(key: K, value: Form[K]) {
    setForm(current => ({ ...current, [key]: value })); setDirty(true);
  }
  async function mutate(path: string, method = 'POST', body?: unknown, keepDetail = true) {
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await request(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) });
      setDirty(false); setEditing(false); setRefreshKey(value => value + 1);
      if (keepDetail && result?.id) await openArticle(result.id, true);
      else setSelected(null);
      setNotice('Đã cập nhật. Nội dung mới cần duyệt chuyên môn trước khi xuất bản.');
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  async function upload(file: File) {
    if (!selected) return;
    if (!/\.(pdf|docx)$/i.test(file.name) || file.size > 5 * 1024 * 1024) {
      setError('Chỉ nhận PDF/DOCX tối đa 5 MB, có văn bản trích xuất được.'); return;
    }
    const body = new FormData(); body.append('file', file);
    setBusy(true); setError(''); setNotice('Đang trích xuất nội dung tệp…');
    try {
      await request(`/${selected.id}/document?expected_revision=${selected.revision}`, { method: 'POST', body });
      setRefreshKey(value => value + 1); await openArticle(selected.id, true);
      setNotice('Đã tách văn bản. Bài về nháp, lịch sử duyệt cũ vẫn được lưu; cần duyệt lại.');
    } catch (err) { setNotice(''); setError((err as Error).message); }
    finally { setBusy(false); }
  }
  async function download(article: Article, history?: { id: number; document_filename: string | null }) {
    setError('');
    try {
      const response = await fetch(`${API}/api/v1/ai/technical-articles/${article.id}/${history ? `history/${history.id}/document` : 'document'}`, {
        headers: { Authorization: `Bearer ${sessionStorage.getItem('garage_token') || ''}` },
      });
      if (!response.ok) throw new Error('Không tải được tệp nguồn.');
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = url; link.download = history?.document_filename || article.document_filename || 'nguon';
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) { setError((err as Error).message); }
  }
  const action = (type: 'technical-review' | 'publish' | 'unpublish') => {
    if (!selected) return;
    if (!window.confirm(type === 'unpublish' ? `Thu hồi “${selected.title}” khỏi câu trả lời mới của AI?` :
      `Xác nhận ${type === 'publish' ? 'xuất bản' : 'duyệt chuyên môn'} phiên bản ${selected.revision} của “${selected.title}”?`)) return;
    const reason = type === 'unpublish' ? window.prompt('Lý do thu hồi (bắt buộc):') : null;
    if (type === 'unpublish' && (!reason || reason.trim().length < 3)) return;
    void mutate(`/${selected.id}/${type}?expected_revision=${selected.revision}${reason ? `&reason=${encodeURIComponent(reason)}` : ''}`);
  };
  const remove = () => {
    if (!selected || !window.confirm(`Xóa mềm “${selected.title}”? Bài sẽ ngừng được AI sử dụng; lịch sử và tệp nguồn được giữ lại.`)) return;
    const reason = window.prompt('Nhập lý do xóa (ít nhất 3 ký tự):');
    if (!reason || reason.trim().length < 3) return;
    void mutate(`/${selected.id}?expected_revision=${selected.revision}&reason=${encodeURIComponent(reason)}`, 'DELETE', undefined, false);
  };
  const count = (key: string) => list?.stats[key as keyof Stats] ?? 0;
  const stats = list?.stats;

  return <div className="technical-knowledge technical-admin">
    <header className="technical-header"><div><h2>Kho kiến thức kỹ thuật</h2><p>Soạn, kiểm tra nguồn và duyệt bài trước khi trợ lý sử dụng.</p></div>
      <button type="button" className="btn primary" onClick={() => { if (dirty && !window.confirm('Bỏ thay đổi chưa lưu?')) return;
        setSelected(null); setForm(blank); setEditing(true); setDirty(false); }}><Plus size={16}/> Tạo bài kỹ thuật</button></header>
    <div className="technical-overview" aria-label="Thống kê bài kỹ thuật">
      {[['Tổng bài', stats?.total], ['Bản nháp', stats?.draft], ['Chờ kỹ thuật', stats?.pending_technical],
        ['Chờ xuất bản', stats?.pending_publish], ['Đã xuất bản', stats?.published], ['Cần kiểm tra nguồn', stats?.source_warning]]
        .map(([label, value]) => <div key={label}><strong>{value ?? '–'}</strong><span>{label}</span></div>)}
    </div>
    <form className="technical-filter" onSubmit={event => { event.preventDefault(); setFilters({ ...draft }); setPage(1); }}>
      <div className="technical-filter-main"><label><Search size={17}/><span className="sr-only">Tìm bài kỹ thuật</span>
        <input value={draft.q} onChange={event => setDraft({ ...draft, q: event.target.value })} placeholder="Tìm tiêu đề, triệu chứng, hãng xe, mã động cơ, nguồn, ID…" /></label>
        <button type="submit" className="btn primary">Lọc</button>
        <button type="button" className="btn secondary" onClick={() => { setDraft(initialFilters); setFilters(initialFilters); setTab(''); setPage(1); }}>Xóa bộ lọc</button></div>
      <details className="technical-advanced"><summary><SlidersHorizontal size={16}/> Bộ lọc nâng cao</summary><div className="technical-filter-grid">
        <label>Duyệt chuyên môn<select value={draft.review} onChange={e => setDraft({ ...draft, review: e.target.value })}><option value="">Tất cả</option><option value="reviewed">Đã duyệt</option><option value="unreviewed">Chưa duyệt</option></select></label>
        <label>An toàn<select value={draft.safety_level} onChange={e => setDraft({ ...draft, safety_level: e.target.value })}><option value="">Tất cả</option>{Object.entries(safetyLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>
        {([['vehicle_make', 'Hãng xe', options.makes], ['vehicle_model', 'Dòng xe', options.models]] as const).map(([key, label, entries]) =>
          <label key={key}>{label}<input list={`technical-${key}`} value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value })} /><datalist id={`technical-${key}`}>{entries.map(entry => <option key={entry} value={entry}/>)}</datalist></label>)}
        {([['technical_reviewer', 'Người duyệt kỹ thuật', options.reviewers], ['publisher', 'Người xuất bản', options.publishers]] as const).map(([key, label, entries]) =>
          <label key={key}>{label}<select value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value })}><option value="">Tất cả</option>{entries.map(entry => <option key={entry.id} value={entry.id}>{entry.name}</option>)}</select></label>)}
        <label>Tệp nguồn<select value={draft.has_document} onChange={e => setDraft({ ...draft, has_document: e.target.value })}><option value="">Tất cả</option><option value="true">Có tệp</option><option value="false">Chưa có tệp</option></select></label>
        <label>Tên nguồn<select value={draft.has_source} onChange={e => setDraft({ ...draft, has_source: e.target.value })}><option value="">Tất cả</option><option value="true">Có nguồn</option><option value="false">Thiếu nguồn</option></select></label>
        <label>Cập nhật từ ngày<input type="date" value={draft.updated_since} onChange={e => setDraft({ ...draft, updated_since: e.target.value })} /></label>
        <label>Sắp xếp<select value={draft.sort} onChange={e => setDraft({ ...draft, sort: e.target.value })}><option value="priority">Ưu tiên chờ xử lý</option><option value="recent">Mới cập nhật</option><option value="title">Tiêu đề A–Z</option></select></label>
      </div></details>
    </form>
    <nav className="technical-tabs" aria-label="Lọc nhanh trạng thái">{tabs.map(([value, label]) => <button type="button" key={value} aria-current={tab === value ? 'page' : undefined} className={tab === value ? 'active' : ''}
      onClick={() => { setTab(value); setPage(1); }}>{label} <small>{value === '' ? count('total') : value === 'draft' ? count('draft') : count(value)}</small></button>)}</nav>
    <div className="technical-list-header"><strong>{loading ? 'Đang tải…' : `${list?.total ?? 0} kết quả`}</strong><label>Số dòng <select value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setPage(1); }}><option>10</option><option>20</option><option>50</option></select></label></div>
    {error && <p role="alert" className="assistant-error">{error}</p>}
    {notice && <p role="status" className="technical-notice">{notice}</p>}
    {loading && !list ? <div className="technical-loading" role="status">Đang tải bài viết…</div> : list?.items.length === 0 && !loading ?
      <div className="technical-empty"><FileText size={28}/><strong>Không tìm thấy bài phù hợp</strong><p>Thử xóa bộ lọc hoặc tạo bài kỹ thuật mới.</p></div> :
      <div className="technical-table-wrap"><table className="technical-table"><thead><tr><th>Bài viết</th><th>Xe áp dụng</th><th>Nguồn</th><th>An toàn</th><th>Kiểm duyệt</th><th>Cập nhật</th><th>Thao tác</th></tr></thead><tbody>
        {list?.items.map(article => <tr key={article.id}><td><button type="button" className="technical-title" onClick={() => void openArticle(article.id)}>{article.title}</button><small>#{article.id} · {article.symptoms}</small></td>
          <td>{[article.vehicle_make, article.vehicle_model, article.year_from || article.year_to ? `${article.year_from ?? '…'}–${article.year_to ?? '…'}` : '', article.engine_code].filter(Boolean).join(' · ') || 'Dùng chung'}</td>
          <td><span className="technical-clamp">{article.source_name || 'Thiếu nguồn'}</span><small>{article.document_version || 'Chưa ghi phiên bản'} · {article.document_filename ? 'Có tệp' : 'Chưa có tệp'}</small></td>
          <td><span className={`technical-safety ${article.safety_level}`}>{safetyLabels[article.safety_level]}</span></td>
          <td><span className={`technical-state ${article.status}`}>{statusText(article)}</span><small>{article.technical_reviewer_name || 'Chưa duyệt chuyên môn'}</small></td>
          <td>{dateText(article.updated_at)}</td>
          <td><button type="button" className="btn secondary" onClick={() => void openArticle(article.id)}>Xem</button></td></tr>)}</tbody></table></div>}
    <div className="technical-pagination"><span>Trang {page}/{list?.pages || 1}</span><button type="button" className="btn secondary" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)}>Trước</button><button type="button" className="btn secondary" disabled={loading || page >= (list?.pages || 1)} onClick={() => setPage(page + 1)}>Sau</button></div>

    {(selected || editing || detailLoading) && <div className="technical-panel-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) closePanel(); }}>
      <section className="technical-panel" role="dialog" aria-modal="true" aria-labelledby="technical-panel-title">
        <header><div><small>{selected ? `Bài #${selected.id} · Phiên bản ${selected.revision}` : 'Bài mới'}</small><h3 id="technical-panel-title">{editing ? selected ? 'Sửa bài kỹ thuật' : 'Tạo bài kỹ thuật' : selected?.title || 'Đang tải…'}</h3></div><button ref={closeButton} type="button" aria-label="Đóng chi tiết" onClick={closePanel}><X size={20}/></button></header>
        {detailLoading ? <p role="status">Đang tải nội dung và lịch sử…</p> : editing ? <form className="technical-editor" onSubmit={event => { event.preventDefault(); void mutate(selected ? `/${selected.id}` : '', selected ? 'PUT' : 'POST', { ...form, ...(selected ? { expected_revision: selected.revision } : {}) }); }}>
          <fieldset><legend>Nội dung bài viết</legend>
            <label>Tiêu đề<input required minLength={5} maxLength={180} value={form.title} onChange={e => setField('title', e.target.value)} /></label>
            <label>Triệu chứng, tên gọi khác<textarea required minLength={3} maxLength={800} value={form.symptoms} onChange={e => setField('symptoms', e.target.value)} /></label>
            <label>Nội dung tham khảo<textarea required minLength={30} maxLength={8000} rows={6} value={form.content} onChange={e => setField('content', e.target.value)} /></label></fieldset>
          <fieldset><legend>Phạm vi xe áp dụng</legend><div className="technical-filter-grid">
            {([['vehicle_make', 'Hãng xe'], ['vehicle_model', 'Dòng xe'], ['engine_code', 'Mã động cơ']] as const).map(([key, label]) => <label key={key}>{label}<input maxLength={80} value={form[key]} onChange={e => setField(key, e.target.value)} /></label>)}
            {([['year_from', 'Năm từ'], ['year_to', 'Năm đến']] as const).map(([key, label]) => <label key={key}>{label}<input type="number" min={1950} max={2100} value={form[key] ?? ''} onChange={e => setField(key, e.target.value ? Number(e.target.value) : null)} /></label>)}
          </div></fieldset>
          <fieldset><legend>Nguồn tài liệu</legend><label>Tên nguồn<input required minLength={3} maxLength={200} value={form.source_name} onChange={e => setField('source_name', e.target.value)} /></label>
            <label>Liên kết nguồn<input type="url" maxLength={500} value={form.source_url} onChange={e => setField('source_url', e.target.value)} /></label>
            <label>Phiên bản tài liệu<input maxLength={80} value={form.document_version} onChange={e => setField('document_version', e.target.value)} /></label>
            <small>URL chưa được hệ thống xác minh. Tải PDF/DOCX sau khi lưu bài.</small></fieldset>
          <fieldset><legend>An toàn và kiểm duyệt</legend><label>Cảnh báo an toàn<textarea maxLength={1000} value={form.safety} onChange={e => setField('safety', e.target.value)} /></label>
            <label>Mức cảnh báo<select value={form.safety_level} onChange={e => setField('safety_level', e.target.value as SafetyLevel)}>{Object.entries(safetyLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <p>Lưu sẽ chuyển bài về nháp và yêu cầu duyệt lại. Lịch sử duyệt cũ vẫn được giữ.</p></fieldset>
          <div className="technical-panel-actions"><button className="btn primary" disabled={busy} type="submit">{busy ? 'Đang lưu…' : 'Lưu bản nháp'}</button><button type="button" className="btn secondary" onClick={() => { if (selected) { if (dirty && !window.confirm('Bỏ thay đổi chưa lưu?')) return; setEditing(false); setDirty(false); } else closePanel(); }}>Hủy</button></div>
        </form> : selected && <div className="technical-detail">
          <div className="technical-detail-state"><span className={`technical-state ${selected.status}`}>{statusText(selected)}</span><span className={`technical-safety ${selected.safety_level}`}>{safetyLabels[selected.safety_level]}</span></div>
          <section><h4>Thông tin bài viết</h4><p><strong>Triệu chứng:</strong> {selected.symptoms}</p><p className="technical-content">{selected.content}</p>{selected.safety && <p><strong>Cảnh báo:</strong> {selected.safety}</p>}
            <p><strong>Xe áp dụng:</strong> {[selected.vehicle_make, selected.vehicle_model, selected.year_from || selected.year_to ? `${selected.year_from ?? '…'}–${selected.year_to ?? '…'}` : '', selected.engine_code].filter(Boolean).join(' · ') || 'Dùng chung'}</p></section>
          <section><h4>Nguồn tài liệu</h4><p>{selected.source_name || 'Chưa ghi nguồn'} · Phiên bản: {selected.document_version || 'Chưa ghi'}</p>
            {/^https?:\/\//i.test(selected.source_url) && <a href={selected.source_url} target="_blank" rel="noopener noreferrer">Mở nguồn ngoài</a>}
            <p>Tệp: {selected.document_filename || 'Chưa tải'} · Tải lúc: {dateText(selected.document_uploaded_at)}</p>
            <p>Chưa có kết quả xác minh độc lập cho nguồn/phiên bản; nhân viên cần đối chiếu trước khi duyệt.</p>
            <div className="technical-panel-actions"><label className="btn secondary technical-upload">Tải PDF/DOCX<input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" disabled={busy} onChange={e => { const file = e.target.files?.[0]; if (file) void upload(file); e.target.value = ''; }}/></label>
              {selected.document_filename && <button className="btn secondary" type="button" onClick={() => void download(selected)}>Tải tệp gốc</button>}</div></section>
          <section><h4>Kiểm duyệt</h4><p>Duyệt chuyên môn: {selected.technical_reviewer_name || 'Chưa duyệt'} · {dateText(selected.technical_reviewed_at)}</p><p>Xuất bản: {selected.publisher_name || (selected.reviewed_by ? `Tài khoản #${selected.reviewed_by}` : selected.status === 'published' ? 'Bài tham khảo cũ, garage chưa duyệt' : 'Chưa xuất bản')} · {selected.history.find(entry => entry.action === 'publish')?.created_at ? dateText(selected.history.find(entry => entry.action === 'publish')?.created_at) : 'Không có mốc xuất bản trước khi bật lịch sử phiên bản'}</p></section>
          <section><h4>Văn bản trích xuất ({selected.chunks.length} đoạn)</h4>{selected.chunks.map(chunk => <details key={chunk.chunk_index}><summary>Đoạn {chunk.chunk_index + 1}</summary><p className="technical-content">{chunk.content}</p></details>)}{!selected.chunks.length && <p>Chưa có văn bản trích xuất.</p>}</section>
          <section><h4>Lịch sử thao tác</h4>{selected.history.map(record => <p key={record.id}>{dateText(record.created_at)} · {record.actor_name || 'Không rõ người'} · {record.action} · phiên bản {record.revision}{record.reason ? ` · ${record.reason}` : ''}{record.document_filename && <> · <button type="button" className="technical-title" onClick={() => void download(selected, record)}>Tải tệp cũ</button></>}</p>)}{!selected.history.length && <p>Chưa có lịch sử phiên bản trước khi bật tính năng này; xem nhật ký kiểm toán cũ nếu cần.</p>}</section>
          <div className="technical-panel-actions"><button type="button" className="btn secondary" onClick={() => startEdit(selected)}>Sửa</button>
            {selected.status === 'draft' && !selected.technical_reviewed_by && <button type="button" className="btn secondary" disabled={busy} onClick={() => action('technical-review')}>Duyệt chuyên môn</button>}
            {canPublish && selected.status === 'draft' && selected.technical_reviewed_by && <button type="button" className="btn primary" disabled={busy} onClick={() => action('publish')}>Duyệt xuất bản</button>}
            <details className="technical-more"><summary>Thao tác khác</summary>{canPublish && selected.status === 'published' && <button type="button" disabled={busy} onClick={() => action('unpublish')}>Thu hồi</button>}{canPublish && <button type="button" disabled={busy} onClick={remove}>Xóa bài (lưu lịch sử)</button>}</details></div>
        </div>}
        {error && <p role="alert" className="assistant-error">{error}</p>}
      </section></div>}
  </div>;
}
