import { useRef, useState, type FormEvent } from 'react';
import { CheckCircle2, CircleAlert, ReceiptText, ShieldCheck, X } from 'lucide-react';
import InvoiceItemsSection from './InvoiceItemsSection';
import EstimatedWorkTime from './EstimatedWorkTime';

type Props = {
  invoice: any;
  request: (path: string, options?: RequestInit) => Promise<any>;
  onClose: () => void;
  onChanged: () => Promise<void> | void;
};
const money = (value: number) => new Intl.NumberFormat('vi-VN').format(Number(value || 0)) + ' ₫';
const timestamp = (value?: string) => value ? `${value.slice(8, 10)}/${value.slice(5, 7)}/${value.slice(0, 4)} ${value.slice(11, 16)}` : 'Chưa có thời gian';
const calendarDate = (value: string) => `${value.slice(8, 10)}/${value.slice(5, 7)}/${value.slice(0, 4)}`;

export default function PaymentRecordDialog({ invoice, request, onClose, onChanged }: Props) {
  const [choice, setChoice] = useState<'full' | 'partial'>('full');
  const [amount, setAmount] = useState('');
  const [method, setMethod] = useState<'Tiền mặt' | 'Quét mã cửa hàng'>('Tiền mặt');
  const [reference, setReference] = useState('');
  const [note, setNote] = useState('');
  const [nextDueAt, setNextDueAt] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const key = useRef('');
  const remaining = Number(invoice.remaining_amount ?? Math.max(0, Number(invoice.total || 0) - Number(invoice.paid_amount || 0)));

  async function save(event: FormEvent) {
    event.preventDefault(); setError('');
    const received = choice === 'full' ? remaining : Number(amount);
    if (!Number.isSafeInteger(received) || received <= 0 || received > remaining || (choice === 'partial' && received === remaining)) {
      setError('Số tiền trả một phần phải lớn hơn 0 và nhỏ hơn số còn nợ.');
      return;
    }
    if (choice === 'partial' && !note.trim()) {
      setError('Vui lòng ghi chú số tiền khách trả và phần còn hẹn trả.');
      return;
    }
    setSaving(true);
    try {
      key.current ||= `payment:${invoice.id}:${crypto.randomUUID()}`;
      await request('/payments', { method: 'POST', headers: {
        'Content-Type': 'application/json', 'Idempotency-Key': key.current,
      }, body: JSON.stringify({ invoice_id: invoice.id, amount: received, method,
        reference_code: method === 'Quét mã cửa hàng' ? reference.trim() : '',
        note: note.trim(), next_due_at: choice === 'partial' && nextDueAt ? nextDueAt : null,
      }) });
      key.current = ''; setAmount(''); setReference(''); setNote(''); setNextDueAt('');
      await onChanged();
    } catch (err) { setError(err instanceof Error ? err.message : 'Không ghi nhận được khoản thu.'); }
    finally { setSaving(false); }
  }

  return <div className="drawer-overlay invoice-detail-overlay" onMouseDown={onClose}>
    <aside className="work-drawer billing-drawer" role="dialog" aria-modal="true" aria-label={`Hóa đơn ${invoice.code}`} onMouseDown={event => event.stopPropagation()}>
      <div className="work-head"><div className="work-head-main"><div className="work-icon"><ReceiptText/></div><div><strong>{invoice.code}</strong><small>{invoice.order_code} • {invoice.plate}</small></div></div><button onClick={onClose} aria-label="Đóng"><X/></button></div>
      <div className="work-body">
        <div className="billing-invoice-hero"><small>CÒN PHẢI THU</small><strong>{money(remaining)}</strong><span className="payment-state">{invoice.status}</span></div>
        <InvoiceItemsSection invoice={invoice}/>
        <EstimatedWorkTime document={invoice}/>
        <section className="work-section"><h3>Tổng hợp thanh toán</h3><div className="billing-totals"><div><span>Tổng hóa đơn</span><b>{money(invoice.total)}</b></div><div><span>Đã thu</span><b>{money(invoice.paid_amount)}</b></div><div className="grand"><span>Còn nợ</span><b>{money(remaining)}</b></div></div>
          {invoice.settled_at && <p className="payment-settled"><CheckCircle2 size={17}/> Đã trả đủ ngày {timestamp(invoice.settled_at)}</p>}
          {remaining > 0 && invoice.due_at && <p className="payment-due">Hẹn thanh toán phần còn lại: {calendarDate(invoice.due_at)}</p>}
        </section>
        {remaining > 0 && invoice.status !== 'Đã hủy' && <form className="work-section billing-payment-form" onSubmit={save}>
          <h3>Ghi nhận khách thanh toán tại quầy</h3><p className="payment-guidance">Ứng dụng không nhận tiền. Chỉ ghi sổ sau khi thu tiền mặt hoặc xác nhận khách đã quét mã QR của cửa hàng.</p>
          <div className="payment-choice" role="group" aria-label="Số tiền khách trả"><label><input type="radio" checked={choice === 'full'} onChange={() => setChoice('full')}/> Trả hết {money(remaining)}</label><label><input type="radio" checked={choice === 'partial'} onChange={() => setChoice('partial')}/> Trả một phần</label></div>
          {choice === 'partial' && <label>Số tiền khách trả lần này<input required type="number" min="1" max={remaining - 1} step="1" value={amount} onChange={event => setAmount(event.target.value)} placeholder="Nhập số tiền thực thu"/></label>}
          <div><label>Hình thức đã nhận<select value={method} onChange={event => setMethod(event.target.value as typeof method)}><option>Tiền mặt</option><option>Quét mã cửa hàng</option></select></label>
            {method === 'Quét mã cửa hàng' && <label>Mã giao dịch (nếu có)<input value={reference} onChange={event => setReference(event.target.value)} placeholder="Mã giao dịch trên tài khoản cửa hàng"/></label>}
          </div>
          {choice === 'partial' && <label>Ngày hẹn trả tiếp (nếu có)<input type="date" value={nextDueAt} onChange={event => setNextDueAt(event.target.value)}/></label>}
          <label>Ghi chú lần thu<textarea value={note} maxLength={500} required={choice === 'partial'} onChange={event => setNote(event.target.value)} placeholder="Khách trả bao nhiêu, phần còn lại hẹn khi nào..."/></label>
          {error && <div className="inline-error" role="alert"><CircleAlert size={16}/>{error}</div>}
          <button className="btn primary" disabled={saving}>{saving ? 'Đang ghi nhận...' : 'Xác nhận đã nhận tiền'}</button>
        </form>}
        <section className="work-section"><h3>Các lần thanh toán</h3>{invoice.payments?.length ? <div className="payment-history">{invoice.payments.map((payment: any) => <article key={payment.id}><div><strong>{money(payment.amount)}</strong><small>{payment.method} • {timestamp(payment.paid_at)}</small>{payment.reference_code && <small>Mã giao dịch: {payment.reference_code}</small>}{payment.note && <p>{payment.note}</p>}</div><CheckCircle2 size={18}/></article>)}</div> : <p className="work-empty">Chưa ghi nhận khoản thu.</p>}</section>
        <div className="billing-security-note"><ShieldCheck/><p>Số dư tự cập nhật từ các lần thu đã ghi nhận; chỉ nhân viên có quyền mới được ghi thêm khoản thu.</p></div>
      </div>
    </aside>
  </div>;
}
