import { useEffect, useState, type FormEvent } from 'react';
import { CircleAlert, Plus, Trash2, X } from 'lucide-react';

type Rule = { make: string; model: string; year_from: string; year_to: string; variant: string; engine_code: string; fuel_type: string; note: string };
const empty = (): Rule => ({ make: '', model: '', year_from: '', year_to: '', variant: '', engine_code: '', fuel_type: '', note: '' });
const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8010';

export default function PartFitmentsModal({ part, onClose }: { part: { id: number; name: string; code: string }; onClose: () => void }) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const token = sessionStorage.getItem('garage_token');

  useEffect(() => {
    fetch(`${API}/api/v1/parts/${part.id}/fitments`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async response => { if (!response.ok) throw new Error('Không tải được quy tắc tương thích.'); return response.json(); })
      .then(data => setRules(data.map((rule: any) => ({ ...empty(), ...rule,
        year_from: rule.year_from ? String(rule.year_from) : '', year_to: rule.year_to ? String(rule.year_to) : '' }))))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [part.id, token]);

  function change(index: number, field: keyof Rule, value: string) {
    setRules(current => current.map((rule, at) => at === index ? { ...rule, [field]: value } : rule));
  }
  async function save(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError('');
    try {
      const response = await fetch(`${API}/api/v1/parts/${part.id}/fitments`, {
        method: 'PUT', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ fitments: rules.map(rule => ({ ...rule,
          year_from: rule.year_from ? Number(rule.year_from) : null,
          year_to: rule.year_to ? Number(rule.year_to) : null })) }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail?.message || body?.detail || 'Không lưu được quy tắc.');
      }
      onClose();
    } catch (err) { setError(err instanceof Error ? err.message : 'Không lưu được quy tắc.'); }
    finally { setSaving(false); }
  }

  return <div className="modal-overlay" onMouseDown={onClose}><form className="modal fitments-modal" onMouseDown={event => event.stopPropagation()} onSubmit={save}>
    <div className="modal-head"><div><p className="eyebrow">QUY TẮC LẮP VỪA</p><h2>{part.name}</h2><small>{part.code} · Chỉ nhập dữ liệu đã đối chiếu theo tài liệu phụ tùng.</small></div><button type="button" onClick={onClose} aria-label="Đóng"><X/></button></div>
    {loading ? <p>Đang tải cấu hình...</p> : <div className="fitments-list">{rules.length === 0 && <p>Chưa có quy tắc xác nhận. Mô tả tương thích cũ chỉ là gợi ý.</p>}
      {rules.map((rule, index) => <fieldset key={index}><legend>Xe áp dụng #{index + 1}</legend>
        <div className="field-row"><label>Hãng<input required value={rule.make} onChange={e => change(index, 'make', e.target.value)}/></label><label>Dòng xe<input required value={rule.model} onChange={e => change(index, 'model', e.target.value)}/></label></div>
        <div className="field-row"><label>Năm từ<input type="number" min="1900" max="2100" value={rule.year_from} onChange={e => change(index, 'year_from', e.target.value)}/></label><label>Đến năm<input type="number" min="1900" max="2100" value={rule.year_to} onChange={e => change(index, 'year_to', e.target.value)}/></label></div>
        <div className="field-row"><label>Phiên bản (nếu giới hạn)<input value={rule.variant} onChange={e => change(index, 'variant', e.target.value)}/></label><label>Mã động cơ (nếu giới hạn)<input value={rule.engine_code} onChange={e => change(index, 'engine_code', e.target.value)}/></label></div>
        <label>Loại nhiên liệu (nếu giới hạn)<input value={rule.fuel_type} onChange={e => change(index, 'fuel_type', e.target.value)}/></label>
        <label>Ghi chú / nguồn đối chiếu<input value={rule.note} onChange={e => change(index, 'note', e.target.value)} placeholder="Tài liệu nhà sản xuất, mã OEM..."/></label>
        <button type="button" className="btn secondary" onClick={() => setRules(current => current.filter((_, at) => at !== index))}><Trash2 size={15}/> Xóa quy tắc</button>
      </fieldset>)}</div>}
    {!loading && <button type="button" className="btn secondary" onClick={() => setRules(current => [...current, empty()])}><Plus size={15}/> Thêm xe áp dụng</button>}
    {error && <p className="inline-error" role="alert"><CircleAlert size={15}/>{error}</p>}
    <div className="modal-actions"><button type="button" className="btn secondary" onClick={onClose}>Hủy</button><button className="btn primary" disabled={saving || loading}>{saving ? 'Đang lưu...' : 'Lưu quy tắc'}</button></div>
  </form></div>;
}
