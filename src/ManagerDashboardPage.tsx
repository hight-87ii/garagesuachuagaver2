import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, CalendarDays, CarFront, CircleAlert, ClipboardList, Clock3, CreditCard, FileCheck2, PackageX, RefreshCw, TrendingUp, Wrench } from 'lucide-react';

type Report = {
  period: {from:string;to:string};
  summary: {revenue:number;invoice_count:number;labor:number;parts:number;debt:number;debt_invoices:number};
  revenue_series: {day:string;revenue:number;invoice_count:number}[];
  active_orders: {id:number;code:string;plate:string;customer_name:string;technician:string|null;status:string;status_code:string;opened_at:string}[];
  appointments: {id:number;customer_name:string;plate:string;service:string;appointment_at:string;status:string}[];
  popular_services: {name:string;quantity:number;amount:number}[];
  inventory: {id:number;name:string;stock:number;min_stock:number;unit:string;status:string}[];
  debts: {id:number;code:string;customer_name:string;plate:string;paid_amount:number;remaining:number;due_at:string|null}[];
};

const currency=(value:number)=>new Intl.NumberFormat('vi-VN').format(value||0)+' ₫';
const number=(value:number)=>new Intl.NumberFormat('vi-VN').format(value||0);
const localDate=(date:Date)=>`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
const shortDate=(value:string)=>value ? new Intl.DateTimeFormat('vi-VN',{day:'2-digit',month:'2-digit'}).format(new Date(value.slice(0,10)+'T12:00:00')) : '—';

async function authorizedReport(path:string, apiBase:string):Promise<Report>{
  const token=sessionStorage.getItem('garage_token');
  const response=await fetch(`${apiBase}/api/v1${path}`,{headers:token?{Authorization:`Bearer ${token}`}:{}});
  if(!response.ok)throw new Error('Không thể tải số liệu vận hành. Vui lòng thử lại.');
  return response.json();
}

export default function ManagerDashboardPage({user,apiBase,onNavigate,onNewAppointment}:{user:any;apiBase:string;onNavigate:(page:string)=>void;onNewAppointment:()=>void}){
  const [range,setRange]=useState<30|90>(90);
  const [report,setReport]=useState<Report|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [refresh,setRefresh]=useState(0);
  const load=useCallback(()=>setRefresh(current=>current+1),[]);

  useEffect(()=>{
    let active=true;
    const end=new Date();const start=new Date(end);start.setDate(end.getDate()-(range-1));
    setLoading(true);setError('');
    authorizedReport(`/reports/overview?from_date=${localDate(start)}&to_date=${localDate(end)}`,apiBase)
      .then(value=>{if(active)setReport(value)})
      .catch((reason:Error)=>{if(active){setError(reason.message);setReport(null)}})
      .finally(()=>{if(active)setLoading(false)});
    return ()=>{active=false};
  },[apiBase,range,refresh]);

  const summary=report?.summary;
  const orders=report?.active_orders||[];
  const appointmentToday=(report?.appointments||[]).filter(item=>item.appointment_at.slice(0,10)===report?.period.to && item.status!=='Đã hủy');
  const lowStock=(report?.inventory||[]).filter(item=>item.status==='Hết hàng'||item.status==='Sắp hết');
  const awaitingQuote=orders.filter(item=>['RECEIVED','INSPECTING','QUOTED'].includes(item.status_code)).length;
  const waitingParts=orders.filter(item=>item.status_code==='WAITING_FOR_PARTS').length;
  const bars=Array.from({length:Math.ceil(range/7)},(_,index)=>{
    const start=new Date(`${report?.period.from||localDate(new Date())}T12:00:00`);start.setDate(start.getDate()+index*7);
    const end=new Date(start);end.setDate(end.getDate()+6);
    const points=(report?.revenue_series||[]).filter(point=>point.day>=localDate(start)&&point.day<=localDate(end));
    return {label:`${shortDate(localDate(start))}`,amount:points.reduce((sum,point)=>sum+point.revenue,0)};
  });
  const maxBar=Math.max(1,...bars.map(bar=>bar.amount));

  return <div className="page manager-page">
    <section className="page-heading manager-heading"><div><p className="eyebrow">BẢNG ĐIỀU HÀNH · GARAGEAI</p><h1>Tổng quan quản lý</h1><p>Chào {user.full_name}. Nắm tình hình xưởng, tài chính và các việc cần xử lý từ dữ liệu thực.</p></div><div className="manager-heading-actions"><button className="btn secondary" onClick={load} disabled={loading} aria-label="Làm mới dữ liệu"><RefreshCw size={16}/> Làm mới</button><button className="btn primary" onClick={onNewAppointment}><CalendarDays size={16}/> Tạo lịch hẹn</button></div></section>
    <div className="manager-toolbar"><div className="manager-range" role="group" aria-label="Khoảng thời gian báo cáo"><button className={range===30?'active':''} aria-pressed={range===30} onClick={()=>setRange(30)}>30 ngày</button><button className={range===90?'active':''} aria-pressed={range===90} onClick={()=>setRange(90)}>90 ngày</button></div><span><Clock3 size={15}/> Doanh thu theo ngày phát hành hóa đơn · {report?`${shortDate(report.period.from)} – ${shortDate(report.period.to)}`:'Đang tải...'}</span></div>
    {error&&<div className="inline-error manager-error" role="alert"><CircleAlert size={17}/>{error}<button onClick={load}>Thử lại</button></div>}
    {loading&&!report?<div className="card manager-loading" role="status">Đang tải báo cáo vận hành...</div>:report&&<>
      <section className="manager-kpis" aria-label="Chỉ số điều hành">
        <div className="manager-kpi"><span className="manager-kpi-icon indigo"><TrendingUp size={21}/></span><span>Doanh thu kỳ này</span><strong>{currency(summary?.revenue||0)}</strong><small>{number(summary?.invoice_count||0)} hóa đơn · không gồm hóa đơn hủy</small></div>
        <div className="manager-kpi"><span className="manager-kpi-icon sky"><CarFront size={21}/></span><span>Xe đang xử lý</span><strong>{number(orders.length)}</strong><small>{awaitingQuote} phiếu cần kiểm tra / báo giá</small></div>
        <div className="manager-kpi"><span className="manager-kpi-icon amber"><CreditCard size={21}/></span><span>Công nợ hiện tại</span><strong>{currency(summary?.debt||0)}</strong><small>{number(summary?.debt_invoices||0)} hóa đơn còn phải thu · toàn thời gian</small></div>
        <div className="manager-kpi"><span className="manager-kpi-icon rose"><PackageX size={21}/></span><span>Phụ tùng cần bổ sung</span><strong>{number(lowStock.length)}</strong><small>{waitingParts} phiếu đang chờ phụ tùng</small></div>
      </section>

      <section className="manager-main-grid">
        <div className="card manager-panel manager-revenue"><div className="manager-panel-heading"><div><span className="manager-overline">TÀI CHÍNH</span><h2>Xu hướng doanh thu</h2><p>Giá trị hóa đơn theo tuần trong {range} ngày gần nhất</p></div><button onClick={()=>onNavigate('Tra cứu & báo cáo')}>Xem báo cáo <ArrowRight size={15}/></button></div><div className="manager-revenue-total">{currency(summary?.revenue||0)}<small>{number(summary?.invoice_count||0)} hóa đơn phát hành</small></div><div className="manager-chart" role="img" aria-label={`Biểu đồ doanh thu ${range} ngày theo tuần`}>{bars.map((bar,index)=><div className="manager-chart-col" key={index} title={`${bar.label}: ${currency(bar.amount)}`}><div className="manager-chart-track"><div className={bar.amount?'manager-chart-bar':'manager-chart-bar empty'} style={{height:`${bar.amount?Math.max(6,bar.amount/maxBar*100):2}%`}}/></div><span>{bar.label}</span></div>)}</div><div className="manager-chart-foot"><span>Đầu kỳ · {shortDate(report.period.from)}</span><span>Hôm nay · {shortDate(report.period.to)}</span></div></div>
        <div className="card manager-panel manager-watch"><div className="manager-panel-heading"><div><span className="manager-overline">ƯU TIÊN HÔM NAY</span><h2>Việc cần theo dõi</h2><p>Các điểm cần chú ý trong vận hành</p></div></div><div className="manager-watch-list"><button onClick={()=>onNavigate('Phiếu sửa chữa')}><span className="manager-watch-icon blue"><ClipboardList size={20}/></span><span><strong>{awaitingQuote} phiếu chờ kiểm tra / báo giá</strong><small>Theo các phiếu tiếp nhận và đang kiểm tra</small></span><ArrowRight size={16}/></button><button onClick={()=>onNavigate('Phiếu sửa chữa')}><span className="manager-watch-icon orange"><Wrench size={20}/></span><span><strong>{waitingParts} phiếu chờ phụ tùng</strong><small>Cần phối hợp bộ phận kho</small></span><ArrowRight size={16}/></button><button onClick={()=>onNavigate('Kho phụ tùng')}><span className="manager-watch-icon red"><PackageX size={20}/></span><span><strong>{lowStock.length} mặt hàng chạm ngưỡng tồn</strong><small>Gồm phụ tùng sắp hết hoặc hết hàng</small></span><ArrowRight size={16}/></button><button onClick={()=>onNavigate('Hóa đơn')}><span className="manager-watch-icon purple"><CreditCard size={20}/></span><span><strong>{summary?.debt_invoices||0} hóa đơn chưa thu đủ</strong><small>Công nợ của tất cả hóa đơn chưa hủy</small></span><ArrowRight size={16}/></button></div></div>
      </section>

      <section className="manager-secondary-grid">
        <div className="card manager-panel"><div className="manager-panel-heading"><div><span className="manager-overline">XƯỞNG DỊCH VỤ</span><h2>Phiếu đang xử lý</h2><p>{orders.length} phiếu chưa hoàn tất</p></div><button onClick={()=>onNavigate('Phiếu sửa chữa')}>Tất cả phiếu <ArrowRight size={15}/></button></div>{orders.length?<div className="manager-table-wrap"><table className="manager-table"><thead><tr><th>PHIẾU / BIỂN SỐ</th><th>KHÁCH HÀNG</th><th>KỸ THUẬT VIÊN</th><th>TRẠNG THÁI</th></tr></thead><tbody>{orders.slice(0,6).map(order=><tr key={order.id}><td><strong>{order.code}</strong><small>{order.plate}</small></td><td>{order.customer_name}</td><td>{order.technician||'Chưa phân công'}</td><td><span className="manager-state">{order.status}</span></td></tr>)}</tbody></table></div>:<p className="manager-empty">Hiện không có phiếu sửa chữa đang xử lý.</p>}</div>
        <div className="card manager-panel"><div className="manager-panel-heading"><div><span className="manager-overline">LỊCH LÀM VIỆC</span><h2>Lịch hẹn hôm nay</h2><p>{appointmentToday.length} lịch hẹn không bị hủy</p></div><button onClick={()=>onNavigate('Lịch hẹn')}>Xem lịch <ArrowRight size={15}/></button></div>{appointmentToday.length?<div className="manager-appointment-list">{appointmentToday.slice(0,5).map(item=><div key={item.id}><span className="manager-appt-time">{item.appointment_at.slice(11,16)}</span><div><strong>{item.customer_name}</strong><small>{item.plate} · {item.service}</small></div><span className="manager-state">{item.status}</span></div>)}</div>:<p className="manager-empty">Không có lịch hẹn trong hôm nay.</p>}</div>
      </section>
      <section className="manager-bottom-grid">
        <div className="card manager-panel"><div className="manager-panel-heading"><div><span className="manager-overline">HIỆU SUẤT DỊCH VỤ</span><h2>Dịch vụ phổ biến</h2><p>Theo số lượng trên hóa đơn trong kỳ</p></div><button onClick={()=>onNavigate('Tra cứu & báo cáo')}>Chi tiết <ArrowRight size={15}/></button></div>{report.popular_services.length?<div className="manager-service-list">{report.popular_services.slice(0,4).map((service,index)=><div key={service.name}><span>{String(index+1).padStart(2,'0')}</span><strong>{service.name}</strong><small>{number(service.quantity)} lượt</small><b>{currency(service.amount)}</b></div>)}</div>:<p className="manager-empty">Chưa có dịch vụ trên hóa đơn trong kỳ.</p>}</div>
        <div className="card manager-panel"><div className="manager-panel-heading"><div><span className="manager-overline">CÔNG NỢ & KHO</span><h2>Cần đối soát</h2><p>Hóa đơn còn thu và mặt hàng chạm ngưỡng tồn</p></div></div><div className="manager-alerts">{report.debts.slice(0,2).map(debt=><button key={debt.id} onClick={()=>onNavigate('Hóa đơn')}><CreditCard size={18}/><span><strong>{debt.code} · {debt.customer_name}</strong><small>{debt.plate} · còn thu {currency(debt.remaining)}</small></span><ArrowRight size={15}/></button>)}{lowStock.slice(0,2).map(part=><button key={part.id} onClick={()=>onNavigate('Kho phụ tùng')}><PackageX size={18}/><span><strong>{part.name}</strong><small>Còn {number(part.stock)} {part.unit} · tối thiểu {number(part.min_stock)}</small></span><ArrowRight size={15}/></button>)}{!report.debts.length&&!lowStock.length&&<p className="manager-empty">Không có công nợ hoặc cảnh báo kho cần đối soát.</p>}</div></div>
      </section>
      <section className="card manager-panel" aria-label="Bảng công nợ khách hàng">
        <div className="manager-panel-heading"><div><span className="manager-overline">ĐỐI SOÁT THANH TOÁN</span><h2>Hóa đơn còn nợ</h2><p>Danh sách theo số dư hiện tại, không gồm hóa đơn đã hủy</p></div><button onClick={()=>onNavigate('Hóa đơn')}>Xem hóa đơn <ArrowRight size={15}/></button></div>
        {report.debts.length ? <div className="manager-table-wrap"><table className="manager-table"><thead><tr><th>HÓA ĐƠN / XE</th><th>KHÁCH HÀNG</th><th>ĐÃ TRẢ</th><th>CÒN NỢ</th><th>HẸN TRẢ TIẾP</th></tr></thead><tbody>{report.debts.slice(0,8).map(item=><tr key={item.id}><td><strong>{item.code}</strong><small>{item.plate}</small></td><td>{item.customer_name}</td><td>{currency(item.paid_amount)}</td><td><strong>{currency(item.remaining)}</strong></td><td>{item.due_at?shortDate(item.due_at):'Chưa hẹn'}</td></tr>)}</tbody></table></div> : <p className="manager-empty">Không có hóa đơn còn nợ.</p>}
      </section>
      <p className="manager-data-note"><FileCheck2 size={15}/> Tất cả số liệu đọc từ hệ thống · doanh thu tính theo hóa đơn chưa hủy, công nợ và tồn kho là số dư hiện tại.</p>
    </>}
  </div>;
}
