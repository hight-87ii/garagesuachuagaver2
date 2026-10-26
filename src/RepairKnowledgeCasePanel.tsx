import { useEffect, useState } from 'react';

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8010';
type Case = { id: number; status: 'draft' | 'published'; customer_symptoms: string;
  inspection_findings: string; confirmed_cause: string; work_done: string; outcome: string;
  vehicle_make: string; vehicle_model: string; vehicle_year: number | null; engine_code: string;
  technician_reviewed_by: number | null; technician_reviewer_name: string | null;
  technician_reviewed_at: string | null; published_at: string | null };
type Fields = Pick<Case, 'customer_symptoms' | 'inspection_findings' | 'confirmed_cause' | 'work_done' | 'outcome'>;
const fieldLabels: { key: keyof Fields; label: string; hint: string }[] = [
  { key: 'customer_symptoms', label: 'Triệu chứng khách báo', hint: 'Chỉ mô tả biểu hiện; không ghi tên, biển số hay điện thoại.' },
  { key: 'inspection_findings', label: 'Kỹ thuật viên đã kiểm tra', hint: 'Ghi những kiểm tra thực tế và kết quả quan sát.' },
  { key: 'confirmed_cause', label: 'Nguyên nhân đã xác nhận', hint: 'Để trống nếu chưa xác minh; không lấy suy đoán làm kết luận.' },
  { key: 'work_done', label: 'Hạng mục đã thực hiện', hint: 'Đối chiếu phiếu và ghi đúng công việc thực tế.' },
  { key: 'outcome', label: 'Kết quả sau sửa', hint: 'Ghi kết quả kiểm tra lại sau khi hoàn tất.' },
];

export default function RepairKnowledgeCasePanel({ orderId, canPublish }: { orderId: number; canPublish: boolean }) {
  const [caseData, setCaseData] = useState<Case | null>(null);
  const [form, setForm] = useState<Fields>({ customer_symptoms: '', inspection_findings: '',
    confirmed_cause: '', work_done: '', outcome: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const path = `${API}/api/v1/repair-orders/${orderId}/knowledge-case`;
  const request = async (suffix = '', method = 'GET', body?: Fields) => {
    const response = await fetch(path + suffix, { method, headers: {
      Authorization: `Bearer ${sessionStorage.getItem('garage_token') || ''}`,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    }, ...(body ? { body: JSON.stringify(body) } : {}) });
    if (response.status === 404) return null;
    const result = await response.json().catch(() => null);
    if (!response.ok) throw new Error(result?.error?.message || result?.detail || 'Không xử lý được ca sửa chữa.');
    return result as Case;
  };
  const update = (next: Case | null) => { setCaseData(next);
    if (next) setForm({ customer_symptoms: next.customer_symptoms, inspection_findings: next.inspection_findings,
      confirmed_cause: next.confirmed_cause, work_done: next.work_done, outcome: next.outcome });
  };
  useEffect(() => { let active = true; request().then(data => { if (active) update(data); })
    .catch(e => { if (active) setError(e.message); }); return () => { active = false; }; }, [orderId]);
  const act = async (suffix: string, method = 'POST', body?: Fields) => {
    setBusy(true); setError(''); setNotice('');
    try { const next = await request(suffix, method, body); update(next);
      setNotice(next?.status === 'published' ? 'Ca đã được duyệt và có thể được chat tham khảo.' :
        'Đã cập nhật. Ca ở trạng thái nháp; chỉ xuất bản sau khi kiểm tra, ẩn danh và duyệt chuyên môn.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Không lưu được ca.'); }
    finally { setBusy(false); }
  };
  return <section className="work-section repair-case-panel">
    <h3>Kiến thức từ ca sửa chữa</h3>
    <p className="work-hint">Hệ thống chỉ chụp bản nháp khi phiếu hoàn thành. Không tự suy ra nguyên nhân hay kết quả; kỹ thuật viên ghi rõ, quản lý kiểm tra ẩn danh trước khi chat sử dụng.</p>
    {error && <p className="inline-error" role="alert">{error}</p>}
    {notice && <p className="inline-success" role="status">{notice}</p>}
    {!caseData ? <button type="button" className="btn secondary" disabled={busy} onClick={() => void act('/capture')}>Tạo nháp từ phiếu này</button> : <>
      <p className="work-hint">{caseData.vehicle_make} {caseData.vehicle_model} {caseData.vehicle_year ?? ''}{caseData.engine_code ? ` · động cơ ${caseData.engine_code}` : ''} · {caseData.status === 'published' ? 'Đã xuất bản' : 'Chỉ nhân viên xem'}</p>
      <form onSubmit={e => { e.preventDefault(); void act('', 'PUT', form); }}>
        {fieldLabels.map(({ key, label, hint }) => <label key={key}>{label}
          <textarea rows={2} required={key !== 'confirmed_cause' && key !== 'outcome'} minLength={2} maxLength={key === 'work_done' ? 4000 : 2000}
            aria-describedby={`case-${orderId}-${key}`} value={form[key]} onChange={e => setForm({ ...form, [key]: e.target.value })} />
          <small id={`case-${orderId}-${key}`}>{hint}</small>
        </label>)}
        <div className="technical-actions"><button type="submit" className="btn secondary" disabled={busy}>Lưu nội dung ca (về nháp)</button></div>
      </form>
      <small>Duyệt chuyên môn: {caseData.technician_reviewer_name || 'Chưa duyệt'}{caseData.technician_reviewed_at ? ` · ${new Date(caseData.technician_reviewed_at).toLocaleString('vi-VN')}` : ''}</small>
      <div className="technical-actions">
        {!caseData.technician_reviewed_by && <button type="button" className="btn secondary" disabled={busy} onClick={() => void act('/technical-review')}>Duyệt chuyên môn</button>}
        {canPublish && caseData.status === 'draft' && <button type="button" className="btn primary" disabled={busy || !caseData.technician_reviewed_by} onClick={() => void act('/publish')}>Xuất bản ca ẩn danh</button>}
        {canPublish && caseData.status === 'published' && <button type="button" className="btn secondary" disabled={busy} onClick={() => void act('/unpublish')}>Thu hồi khỏi chat</button>}
      </div>
    </>}
  </section>;
}
