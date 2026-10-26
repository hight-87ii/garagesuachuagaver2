import React, { useEffect, useMemo, useState } from 'react';
import {
  ArrowRight, CarFront, CheckCircle2, CircleAlert, CircleDollarSign, Clock3,
  FileText, ReceiptText, Search, ShieldCheck, Wallet, Wrench, X,
} from 'lucide-react';
import PaymentRecordDialog from './PaymentRecordDialog';

type Props={apiBase:string};
const money=(value:number)=>new Intl.NumberFormat('vi-VN').format(Number(value||0))+' ₫';
const dateText=(value:string)=>{if(!value)return '—';const [date,time]=value.replace('T',' ').split(' ');const [y,m,d]=date.split('-');return `${d}/${m}/${y}${time?` ${time.slice(0,5)}`:''}`};

export default function CashierBillingPage({apiBase}:Props){
  const [invoices,setInvoices]=useState<any[]>([]);const [pipeline,setPipeline]=useState<any[]>([]);const [tab,setTab]=useState<'pipeline'|'invoices'>('pipeline');const [query,setQuery]=useState('');const [loading,setLoading]=useState(true);const [busyId,setBusyId]=useState<number|null>(null);const [selected,setSelected]=useState<any>(null);const [error,setError]=useState('');const [message,setMessage]=useState('');
  const [paymentSummary,setPaymentSummary]=useState<{collected:number;remaining:number;partial_count:number;unpaid_count:number}|null>(null);
  const [invoicesLoaded,setInvoicesLoaded]=useState(false);const [pipelineLoaded,setPipelineLoaded]=useState(false);
  const token=()=>sessionStorage.getItem('garage_token')||'';
  async function request(path:string,options:RequestInit={}){
    const response=await fetch(`${apiBase}/api/v1${path}`,{...options,headers:{...(options.headers||{}),Authorization:`Bearer ${token()}`}});
    const body=await response.json().catch(()=>null);
    if(!response.ok){
      const location=body?.error?.details?.[0]?.loc?.join(' › ');
      if(response.status===422&&location?.includes('invoice_id')&&['/invoices/pipeline','/invoices/payment-summary'].includes(path)){
        throw new Error('Backend chưa nhận API này. Hãy khởi động lại backend và thử lại.');
      }
      const detail=body?.error?.message||body?.detail||`Lỗi HTTP ${response.status}`;
      throw new Error(`${detail}${location?` (${location})`:''}`);
    }
    return body;
  }
  async function load(){
    setLoading(true);setError('');
    const results=await Promise.allSettled([
      request('/invoices?page_size=200'),request('/invoices/pipeline'),request('/invoices/payment-summary'),
    ]);
    const [invoiceResult,pipelineResult,summaryResult]=results;
    if(invoiceResult.status==='fulfilled'){setInvoices(invoiceResult.value.items||[]);setInvoicesLoaded(true)}
    if(pipelineResult.status==='fulfilled'){setPipeline(pipelineResult.value||[]);setPipelineLoaded(true)}
    if(summaryResult.status==='fulfilled')setPaymentSummary(summaryResult.value);
    const labels=['Danh sách hóa đơn','Luồng xe tiếp nhận','Tổng hợp thanh toán'];
    const issues=results.flatMap((result,index)=>result.status==='rejected'?[`${labels[index]}: ${result.reason instanceof Error?result.reason.message:'Không tải được dữ liệu.'}`]:[]);
    setError(issues.join(' • '));setLoading(false);
  }
  useEffect(()=>{load()},[]);
  async function createInvoice(item:any){setBusyId(item.repair_order_id);setError('');try{const created=await request('/invoices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repair_order_id:item.repair_order_id,quote_id:item.quote_id,note:'Lập từ luồng quầy thu ngân'})});setMessage(`Đã lập hóa đơn ${created.code}.`);await load();setTab('invoices');setTimeout(()=>setMessage(''),3000)}catch(err:any){setError(err.message)}finally{setBusyId(null)}}
  async function openInvoice(invoice:any){setSelected(invoice);try{setSelected(await request(`/invoices/${invoice.id}`))}catch(err:any){setError(err.message)}}
  const filteredPipeline=useMemo(()=>pipeline.filter(item=>`${item.order_code} ${item.plate} ${item.customer_name}`.toLowerCase().includes(query.toLowerCase())),[pipeline,query]);const filteredInvoices=useMemo(()=>invoices.filter(item=>`${item.code} ${item.order_code} ${item.plate} ${item.customer_name}`.toLowerCase().includes(query.toLowerCase())),[invoices,query]);const ready=pipeline.filter(item=>item.stage_code==='READY').length;const waiting=pipeline.filter(item=>['WAITING_QUOTE','WAITING_QUOTE_APPROVAL'].includes(item.stage_code)).length;const debt=paymentSummary?.remaining||0;const collected=paymentSummary?.collected||0;const partialCount=paymentSummary?.partial_count||0;const unpaidCount=paymentSummary?.unpaid_count||0;
  return <div className="page cashier-billing-page"><section className="page-heading"><div><p className="eyebrow">QUẦY THU NGÂN</p><h1>Hóa đơn &amp; thanh toán</h1><p>Theo dõi xe đã tiếp nhận từ lúc vào xưởng đến khi đủ điều kiện lập hóa đơn.</p></div></section>{message&&<div className="inline-success billing-notice"><CheckCircle2 size={16}/>{message}</div>}{error&&<div className="inline-error billing-notice billing-load-error" role="alert"><CircleAlert size={16}/><span>{error}</span><button type="button" onClick={load} disabled={loading}>Thử lại</button></div>}
    <section className="billing-metrics"><BillingMetric icon={<CarFront/>} color="blue" label="Xe đã tiếp nhận" value={pipelineLoaded?pipeline.length:'—'} note="Có phiếu sửa chữa"/><BillingMetric icon={<Clock3/>} color="orange" label="Đang chờ báo giá" value={pipelineLoaded?waiting:'—'} note="Chưa thể lập hóa đơn"/><BillingMetric icon={<CheckCircle2/>} color="green" label="Sẵn sàng lập" value={pipelineLoaded?ready:'—'} note="Báo giá đã duyệt"/><BillingMetric icon={<Wallet/>} color="violet" label="Còn phải thu" value={paymentSummary?money(debt):'—'} note="Theo hóa đơn hiện có"/></section>
    <section className="payment-overview" aria-label="Tổng hợp khoản thu và công nợ"><div><small>Đã ghi nhận thu tại quầy</small><strong>{paymentSummary?money(collected):'—'}</strong></div><div><small>Đang trả một phần</small><strong>{paymentSummary?`${partialCount} hóa đơn`:'—'}</strong></div><div><small>Chưa thanh toán lần nào</small><strong>{paymentSummary?`${unpaidCount} hóa đơn`:'—'}</strong></div></section>
    <div className="billing-tabs"><button className={tab==='pipeline'?'active':''} onClick={()=>setTab('pipeline')}><Wrench/>Luồng xe đã tiếp nhận <b>{pipelineLoaded?pipeline.length:'—'}</b></button><button className={tab==='invoices'?'active':''} onClick={()=>setTab('invoices')}><ReceiptText/>Danh sách hóa đơn <b>{invoicesLoaded?invoices.length:'—'}</b></button></div>
    <section className="card billing-content"><div className="billing-head"><div><h2>{tab==='pipeline'?'Theo dõi điều kiện lập hóa đơn':'Hóa đơn đã phát hành'}</h2><p>{tab==='pipeline'?'Xe mới tiếp nhận chưa phải là hóa đơn; cần hoàn tất báo giá trước.':'Ghi nhận và đối soát thanh toán của khách hàng.'}</p></div><label><Search/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Tìm mã phiếu, biển số, khách hàng..."/></label></div>{loading?<div className="billing-loading"><i/>Đang đồng bộ dữ liệu...</div>:tab==='pipeline'?pipelineLoaded?<PipelineTable items={filteredPipeline} busyId={busyId} onCreate={createInvoice}/>:<BillingLoadError onRetry={load}/>:invoicesLoaded?<InvoiceTable items={filteredInvoices} onOpen={openInvoice}/>:<BillingLoadError onRetry={load}/>}</section>
    {selected&&<PaymentRecordDialog invoice={selected} request={request} onClose={()=>setSelected(null)} onChanged={async()=>{await load();setSelected(await request(`/invoices/${selected.id}`))}}/>}
  </div>;
}

function PipelineTable({items,busyId,onCreate}:{items:any[];busyId:number|null;onCreate:(item:any)=>void}){if(!items.length)return <Empty icon={<CarFront/>} title="Không có phiếu tiếp nhận" text="Xe được lễ tân tiếp nhận sẽ xuất hiện tại đây."/>;return <div className="table-wrap"><table className="billing-table"><thead><tr><th>PHIẾU / XE</th><th>KHÁCH HÀNG</th><th>TRẠNG THÁI XƯỞNG</th><th>BÁO GIÁ</th><th>ĐIỀU KIỆN HÓA ĐƠN</th><th/></tr></thead><tbody>{items.map(item=><tr key={item.repair_order_id}><td><strong>{item.order_code}</strong><small>{item.plate} • {dateText(item.opened_at)}</small></td><td>{item.customer_name||'Khách lẻ'}</td><td><span className="workshop-state">{item.order_status}</span></td><td>{item.quote_code?<><strong>{item.quote_code}</strong><small>{item.quote_status} • {money(item.quote_total)}</small></>:<span className="muted-text">Chưa có báo giá</span>}</td><td><BillingStage code={item.stage_code} text={item.stage}/></td><td>{item.stage_code==='READY'?<button className="billing-create" disabled={busyId===item.repair_order_id} onClick={()=>onCreate(item)}><FileText/>{busyId===item.repair_order_id?'Đang lập...':'Lập hóa đơn'}</button>:item.invoice_id?<span className="invoice-code">{item.invoice_code}</span>:<span className="waiting-label">Chưa đủ điều kiện</span>}</td></tr>)}</tbody></table></div>}
function InvoiceTable({items,onOpen}:{items:any[];onOpen:(item:any)=>void}){if(!items.length)return <Empty icon={<ReceiptText/>} title="Chưa có hóa đơn" text="Hóa đơn sẽ xuất hiện sau khi báo giá được duyệt và thu ngân lập chứng từ."/>;return <div className="table-wrap"><table className="billing-table"><thead><tr><th>HÓA ĐƠN</th><th>KHÁCH HÀNG / XE</th><th>TỔNG TIỀN</th><th>ĐÃ THU</th><th>CÒN LẠI</th><th>TRẠNG THÁI</th><th/></tr></thead><tbody>{items.map(item=><tr key={item.id} onClick={()=>onOpen(item)} className="billing-clickable"><td><strong>{item.code}</strong><small>{dateText(item.issued_at)} • {item.order_code}</small></td><td><strong>{item.customer_name||'Khách lẻ'}</strong><small>{item.plate}</small></td><td>{money(item.total)}</td><td>{money(item.paid_amount)}</td><td><strong className="billing-debt">{money(item.remaining_amount)}</strong></td><td><InvoiceState status={item.status}/></td><td><button><ArrowRight/></button></td></tr>)}</tbody></table></div>}

function BillingMetric({icon,color,label,value,note}:{icon:React.ReactNode;color:string;label:string;value:React.ReactNode;note:string}){return <article><span className={color}>{icon}</span><div><small>{label}</small><strong>{value}</strong><p>{note}</p></div></article>}
function BillingStage({code,text}:{code:string;text:string}){return <span className={`billing-stage ${code.toLowerCase()}`}><i/>{text}</span>}
function InvoiceState({status}:{status:string}){return <span className={`billing-invoice-state ${status==='Đã thanh toán'?'paid':status==='Thanh toán một phần'?'partial':status==='Đã hủy'?'cancelled':'unpaid'}`}><i/>{status}</span>}
function Empty({icon,title,text}:{icon:React.ReactNode;title:string;text:string}){return <div className="billing-empty">{icon}<strong>{title}</strong><p>{text}</p></div>}
function BillingLoadError({onRetry}:{onRetry:()=>void}){return <div className="billing-empty"><CircleAlert/><strong>Chưa tải được dữ liệu</strong><p>Không thể xác nhận danh sách hiện tại. Vui lòng thử lại hoặc kiểm tra kết nối backend.</p><button type="button" className="btn secondary" onClick={onRetry}>Tải lại dữ liệu</button></div>}
