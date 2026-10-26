import { CheckCircle2, Clock3 } from 'lucide-react';

const money = (value: number) => new Intl.NumberFormat('vi-VN').format(Number(value || 0)) + ' ₫';
const at = (value?: string) => value ? `${value.slice(8, 10)}/${value.slice(5, 7)}/${value.slice(0, 4)} ${value.slice(11, 16)}` : 'Chưa rõ thời gian';
const on = (value?: string) => value ? `${value.slice(8, 10)}/${value.slice(5, 7)}/${value.slice(0, 4)}` : '—';

export default function InvoicePaymentHistory({ invoice }: { invoice: any }) {
  const remaining = Number(invoice.remaining_amount || 0);
  return <section className="work-section invoice-payment-history">
    <h3>Tình trạng & lịch sử thanh toán</h3>
    <div className="payment-ledger-summary"><span>Tổng hóa đơn <strong>{money(invoice.total)}</strong></span><span>Đã trả <strong>{money(invoice.paid_amount)}</strong></span><span>Còn nợ <strong>{money(remaining)}</strong></span></div>
    {invoice.settled_at && <p className="payment-settled"><CheckCircle2 size={16}/> Đã trả đủ lúc {at(invoice.settled_at)}</p>}
    {remaining > 0 && <p className="payment-due"><Clock3 size={16}/> Chưa trả đủ{invoice.due_at ? ` · Hẹn trả tiếp ngày ${on(invoice.due_at)}` : ' · Chưa ghi ngày hẹn trả tiếp'}</p>}
    {invoice.payments?.length ? <div className="payment-history">{invoice.payments.map((payment: any) => <article key={payment.id}>
      <div><strong>{money(payment.amount)}</strong><small>{payment.method} · {at(payment.paid_at)}</small>
        {payment.reference_code && <small>Mã giao dịch: {payment.reference_code}</small>}
        {payment.note && <p>Ghi chú: {payment.note}</p>}</div><CheckCircle2 size={18}/>
    </article>)}</div> : <p className="work-empty">Chưa ghi nhận lần thanh toán nào tại garage.</p>}
    <p className="payment-guidance">Web chỉ hiển thị khoản thu được garage ghi nhận; không thu tiền qua ứng dụng.</p>
  </section>;
}
