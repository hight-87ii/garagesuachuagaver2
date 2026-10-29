import { useEffect, useState, type FormEvent } from 'react';
import { CalendarDays, CarFront, CircleAlert, ClipboardList, Copy, Gauge, History, Pencil, Save, Sparkles, X } from 'lucide-react';
import { AIService, type AIResult } from './services/aiService';

type Vehicle = {
  id:number; plate:string; make:string; model:string; year:number|null; vin:string|null;
  variant:string|null; engine_code:string|null; fuel_type:string|null; color:string|null;
  mileage:number|null; created_at:string; profile:Record<string,any>;
  history:Array<Record<string,any>>; orders:Array<Record<string,any>>; appointments:Array<Record<string,any>>;
};
type OwnerField = 'color'|'mileage'|'first_registration_year'|'vehicle_type'|'seat_count'|'door_count'|'registration_info'|'inspection_expires_at'|'liability_insurance_expires_at'|'comprehensive_insurance_expires_at';
const editable:OwnerField[]=['color','mileage','first_registration_year','vehicle_type','seat_count','door_count','registration_info','inspection_expires_at','liability_insurance_expires_at','comprehensive_insurance_expires_at'];
const ownerLabels:Record<OwnerField,string>={color:'Màu ngoại thất',mileage:'Số km hiện tại',first_registration_year:'Năm đăng ký lần đầu',vehicle_type:'Loại xe',seat_count:'Số chỗ',door_count:'Số cửa',registration_info:'Thông tin đăng ký',inspection_expires_at:'Hạn đăng kiểm',liability_insurance_expires_at:'Hạn bảo hiểm bắt buộc',comprehensive_insurance_expires_at:'Hạn bảo hiểm vật chất'};
const numeric = new Set<OwnerField>(['mileage','first_registration_year','seat_count','door_count']);
const dates = new Set<OwnerField>(['inspection_expires_at','liability_insurance_expires_at','comprehensive_insurance_expires_at']);
const na=(value:unknown)=>value===null||value===undefined||value===''?'Chưa cập nhật':String(value);
const km=(value:unknown)=>value===null||value===undefined?'Chưa cập nhật':`${Number(value).toLocaleString('vi-VN')} km`;
const date=(value:unknown)=>value?new Intl.DateTimeFormat('vi-VN',{day:'2-digit',month:'2-digit',year:'numeric',timeZone:'Asia/Ho_Chi_Minh'}).format(new Date(String(value).length===10?`${value}T12:00:00+07:00`:String(value))):'Chưa cập nhật';
const money=(value:number)=>`${Number(value).toLocaleString('vi-VN')} ₫`;
const open=(order:Record<string,any>)=>!['COMPLETED','DELIVERED','CANCELLED'].includes(order.status_code);
function expiry(value:string|null|undefined){
  if(!value)return 'Chưa cập nhật';
  const days=Math.ceil((new Date(`${value}T12:00:00+07:00`).getTime()-Date.now())/86400000);
  return days<0?'Hết hạn':days<=30?'Sắp hết hạn':'Còn hạn';
}
function mileageWarnings(vehicle:Vehicle){
  const rows=[...vehicle.history].filter(row=>row.mileage!=null).sort((a,b)=>String(a.repaired_at).localeCompare(String(b.repaired_at)));
  const issues=[] as string[];
  if(rows.some((row,index)=>index>0&&Number(row.mileage)<Number(rows[index-1].mileage)))issues.push('Số km trong lịch sử giảm theo thời gian; cần garage đối chiếu phiếu gốc.');
  if(vehicle.mileage!=null&&rows.length&&Number(vehicle.mileage)<Number(rows[rows.length-1].mileage))issues.push('Số km hiện tại thấp hơn lần ghi nhận gần nhất.');
  return issues;
}
const identity=(v:Vehicle):Array<[string,unknown]>=>[
  ...(()=>{const p=v.profile||{};return [
  ['Biển số',v.plate],['Hãng',v.make],['Dòng xe',v.model],['Phiên bản',v.variant],['Năm sản xuất',v.year],
  ['Năm đăng ký lần đầu',p.first_registration_year],['VIN / số khung',v.vin],
   ['Số máy',v.profile?.engine_number],['Mã động cơ',v.engine_code],['Màu ngoại thất',v.color],
  ['Loại phương tiện',p.vehicle_type],['Số chỗ',p.seat_count],['Số cửa',p.door_count],
  ['Ngày vào hệ thống',date(v.created_at)],
  ] as Array<[string,unknown]>})(),
];
const technical=(v:Vehicle):Array<[string,unknown]>=>{const p=v.profile||{}, electric=/điện|electric|\bev\b/i.test(v.fuel_type||''), liquid=/xăng|diesel|dầu|hybrid|petrol|gasoline/i.test(v.fuel_type||'');return [
  ['Loại động cơ / nhiên liệu',v.fuel_type],['Dung tích động cơ (cc)',p.displacement_cc],
  ['Công suất cực đại',p.power_kw!=null?`${p.power_kw} kW`:null],['Mô-men xoắn cực đại',p.torque_nm!=null?`${p.torque_nm} Nm`:null],
  ['Hộp số',p.transmission],['Hệ dẫn động',p.drivetrain],
  ['Mức tiêu thụ tham khảo',p.fuel_consumption],...(liquid&&!electric?[['Dung tích bình nhiên liệu (L)',p.fuel_tank_liters] as [string,unknown]]:[]),
  ['Kích thước lốp',p.tire_size],['Áp suất lốp khuyến nghị',p.tire_pressure],
  ['Dung tích dầu động cơ (L)',p.oil_capacity_liters],['Tiêu chuẩn dầu',p.oil_spec],
]};
const documents=(v:Vehicle):Array<[string,string|null|undefined]>=>{const p=v.profile||{};return [
  ['Đăng kiểm',p.inspection_expires_at],['Bảo hiểm trách nhiệm dân sự',p.liability_insurance_expires_at],
  ['Bảo hiểm vật chất',p.comprehensive_insurance_expires_at],
]};
function Facts({items}:{items:Array<[string,unknown]>}){return <dl className="my-profile-facts">{items.map(([label,value])=><div key={label}><dt>{label}</dt><dd>{na(value)}</dd></div>)}</dl>}

export default function MyVehiclesPage({apiBase,onOpenAI,onNewAppointment}:{apiBase:string;onOpenAI:(vehicleId?:number)=>void;onNewAppointment:()=>void}){
  const [data,setData]=useState<{customer:Record<string,any>;vehicles:Vehicle[]}|null>(null);
  const [error,setError]=useState('');const [loading,setLoading]=useState(true);
  const [editing,setEditing]=useState<number|null>(null);const [draft,setDraft]=useState<Record<string,string>>({});
  const [saving,setSaving]=useState(false);const [notice,setNotice]=useState('');
  const [answer,setAnswer]=useState<{vehicleId:number;question:string;result:AIResult}|null>(null);
  const [asking,setAsking]=useState(false);
  const [selectedId,setSelectedId]=useState<number|null>(null);
  const [historyYear,setHistoryYear]=useState('');const [historyStatus,setHistoryStatus]=useState('');const [historyService,setHistoryService]=useState('');
  const auth=()=>({Authorization:`Bearer ${sessionStorage.getItem('garage_token')||''}`});
  async function request(path:string, options:RequestInit={}){
    const response=await fetch(`${apiBase}/api/v1${path}`,{...options,headers:{...auth(),...(options.headers||{})}});
    const body=await response.json().catch(()=>null);
    if(!response.ok)throw new Error(body?.error?.message||body?.detail||'Không thể xử lý yêu cầu.');
    return body;
  }
  async function load(){setLoading(true);setError('');try{const loaded=await request('/my-vehicles');setData(loaded);setSelectedId(current=>loaded.vehicles.some((v:Vehicle)=>v.id===current)?current:loaded.vehicles[0]?.id??null)}catch(err){setError(err instanceof Error?err.message:'Không tải được xe.')}finally{setLoading(false)}}
  useEffect(()=>{void load()},[]);
  function edit(vehicle:Vehicle){setDraft(Object.fromEntries(editable.map(key=>[key,String((key==='color'||key==='mileage'?vehicle[key]:vehicle.profile[key])??'')])));setEditing(vehicle.id);setError('');setNotice('')}
  async function save(event:FormEvent,vehicle:Vehicle){
    event.preventDefault();setSaving(true);setError('');setNotice('');
    try{
      const body=Object.fromEntries(editable.filter(key=>{
        const previous=key==='color'||key==='mileage'?vehicle[key]:(vehicle.profile||{})[key];
        return (draft[key]?.trim()||'')!==String(previous??'');
      }).map(key=>[key,draft[key]?.trim()?numeric.has(key)?Number(draft[key]):draft[key].trim():null]));
      if(!Object.keys(body).length)throw new Error('Chưa có thông tin nào thay đổi.');
      await request(`/my-vehicles/${vehicle.id}/profile`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      setEditing(null);setNotice(`Đã lưu hồ sơ xe ${vehicle.plate}.`);await load();
    }catch(err){setError(err instanceof Error?err.message:'Không lưu được hồ sơ.')}finally{setSaving(false)}
  }
  async function ask(vehicle:Vehicle,question:string){setAsking(true);setError('');setAnswer(null);try{
    const result=await AIService.chat({question,vehicle_id:vehicle.id});setAnswer({vehicleId:vehicle.id,question,result});
  }catch(err){setError(err instanceof Error?err.message:'Trợ lý chưa phản hồi.')}finally{setAsking(false)}}
  if(loading&&!data)return <div className="page"><div className="detail-loading"><i/> Đang tải hồ sơ xe...</div></div>;
  return <div className="page my-profile-page">
    <section className="page-heading"><div><p className="eyebrow">GARAGE CỦA BẠN</p><h1>Xe của tôi</h1><p>Hồ sơ, giấy tờ và lịch sử thực tế của từng phương tiện.</p></div><button className="btn secondary" onClick={()=>onOpenAI()}><Sparkles size={16}/> Trợ lý AI</button></section>
    {error&&<div className="inline-error" role="alert"><CircleAlert size={16}/>{error}<button onClick={()=>void load()}>Thử tải lại</button></div>}
    {notice&&<div className="inline-success" role="status">{notice}</div>}
    {data&&<section className="owner-summary card"><div className="owner-avatar"><CarFront size={22}/></div><div><p>CHỦ SỞ HỮU</p><h2>{data.customer?.name||'Khách hàng'}</h2><span>{data.customer?.email||'Chưa cập nhật liên hệ'}</span></div></section>}
    {data&&!data.vehicles.length&&<div className="empty-state"><CarFront size={30}/><strong>Chưa có xe trong hồ sơ</strong><p>Liên hệ garage để liên kết phương tiện.</p></div>}
    {data&&<div className="my-profile-overview" aria-label="Tổng quan phương tiện"><span>{data.vehicles.length} xe đã đăng ký</span><span>{data.vehicles.reduce((n,v)=>n+v.orders.filter(open).length,0)} phiếu đang mở</span><span>{data.vehicles.reduce((n,v)=>n+v.history.length,0)} lần sửa chữa / bảo dưỡng đã ghi</span></div>}
    {data&&data.vehicles.length>1&&<nav className="my-profile-switch" aria-label="Chọn xe">{data.vehicles.map(v=><button type="button" key={v.id} aria-current={selectedId===v.id?'true':undefined} onClick={()=>{setSelectedId(v.id);setHistoryYear('');setHistoryStatus('');setHistoryService('');setAnswer(null);setEditing(null)}}>{v.plate}<small>{v.make} {v.model}</small></button>)}</nav>}
    {data?.vehicles.filter(vehicle=>vehicle.id===selectedId).map(vehicle=>{
       const p=vehicle.profile||{}, completedHistory=vehicle.history.filter(row=>!row.order_status_code||['COMPLETED','DELIVERED'].includes(row.order_status_code));
       const last=completedHistory[0], warnings=mileageWarnings(vehicle);
       const years=Array.from(new Set(completedHistory.map(row=>String(row.repaired_at||'').slice(0,4)).filter(Boolean)));
       const filteredHistory=completedHistory.filter(row=>(!historyYear||String(row.repaired_at).startsWith(historyYear))&&(!historyStatus||row.order_status===historyStatus)&&(!historyService||String(row.services||'').toLocaleLowerCase('vi-VN').includes(historyService.toLocaleLowerCase('vi-VN'))));
      const plan=Boolean(p.maintenance_source&&(p.next_service_at||p.next_service_mileage!=null));
      const overdue=plan&&((p.next_service_mileage!=null&&vehicle.mileage!=null&&vehicle.mileage>=p.next_service_mileage)||(p.next_service_at&&new Date(`${p.next_service_at}T23:59:59+07:00`).getTime()<Date.now()));
      const soon=plan&&!overdue&&((p.next_service_mileage!=null&&vehicle.mileage!=null&&p.next_service_mileage-vehicle.mileage<=1000)||(p.next_service_at&&new Date(`${p.next_service_at}T12:00:00+07:00`).getTime()-Date.now()<=30*86400000));
      const status=!plan||warnings.length?'Chưa đủ dữ liệu đánh giá':overdue?'Quá hạn':soon?'Sắp đến hạn':'Bình thường theo lịch đã lưu';
      const current=vehicle.mileage;
      return <article className="card my-profile-card" key={vehicle.id}>
        <header className="my-profile-hero"><span className="my-profile-icon"><CarFront size={27}/></span><div><small>PHƯƠNG TIỆN · {vehicle.year||'Chưa rõ năm'}</small><h2>{vehicle.make} {vehicle.model}{vehicle.variant?` · ${vehicle.variant}`:''}</h2><strong>{vehicle.plate}</strong><p>VIN: {na(vehicle.vin)} {vehicle.vin&&<button aria-label={`Sao chép VIN xe ${vehicle.plate}`} onClick={()=>navigator.clipboard.writeText(vehicle.vin!).then(()=>setNotice('Đã sao chép VIN.')).catch(()=>setError('Không sao chép được VIN.'))}><Copy size={14}/></button>}</p></div><div className="my-profile-actions"><span className="my-profile-badge">{status}</span><button className="btn secondary" onClick={()=>edit(vehicle)}><Pencil size={15}/> Cập nhật thông tin xe</button><button className="btn primary" onClick={onNewAppointment}><CalendarDays size={15}/> Đặt lịch bảo dưỡng</button></div></header>
         {warnings.map(warning=><p key={warning} className="my-profile-warning"><CircleAlert size={16}/>{warning} Nhân viên cần kiểm tra chứng từ gốc; hệ thống không tự sửa số km.</p>)}
         {vehicle.history.some(row=>row.review_flags?.length)&&<p className="my-profile-warning"><CircleAlert size={16}/>Một số lịch sử có liên kết hoặc biển số cần nhân viên đối chiếu. Chưa kết luận dữ liệu sai.</p>}
        <div className="my-profile-stats"><div><Gauge/><small>SỐ KM HIỆN TẠI</small><strong>{km(current)}</strong></div><div><History/><small>LẦN GẦN NHẤT</small><strong>{date(last?.repaired_at)}</strong></div><div><CalendarDays/><small>LỊCH TIẾP THEO</small><strong>{plan?(p.next_service_at?date(p.next_service_at):km(p.next_service_mileage)):'Chưa có lịch xác minh'}</strong></div><div><ClipboardList/><small>PHIẾU ĐANG MỞ</small><strong>{vehicle.orders.filter(open).length}</strong></div></div>
        <div className="my-profile-sections">
          <details open><summary>Thông tin nhận dạng</summary><Facts items={identity(vehicle)}/></details>
           <details open><summary>Thông số kỹ thuật</summary><p className="my-profile-hint">Thông số do garage nhập; không suy ra từ hãng và dòng xe. Cần đối chiếu đúng phiên bản.</p><Facts items={technical(vehicle)}/></details>
          <details><summary>Tình trạng sử dụng</summary><Facts items={[
            ['Số km hiện tại',km(current)],['Cập nhật km gần nhất',date(p.mileage_updated_at)],
            ['Lần sửa chữa gần nhất',date(last?.repaired_at)],['Hạng mục gần nhất',last?.services],
            ['Đã đi từ lần gần nhất',!warnings.length&&current!=null&&last?.mileage!=null&&current>=last.mileage?km(current-last.mileage):null],
            ['Bảo dưỡng dự kiến',plan?p.next_service_at?date(p.next_service_at):km(p.next_service_mileage):null],
            ['Số km còn lại',plan&&p.next_service_mileage!=null&&current!=null?km(Math.max(0,p.next_service_mileage-current)):null],
            ['Nguồn lịch bảo dưỡng',p.maintenance_source],['Trạng thái',status],
          ]}/></details>
          <details><summary>Giấy tờ xe</summary><Facts items={[["Thông tin đăng ký",p.registration_info],...documents(vehicle).flatMap(([label,value])=>[[`${label} · ngày hết hạn`,value?date(value):null],[`${label} · trạng thái`,expiry(value)]]) as Array<[string,unknown]>]}/><p className="my-profile-hint">Thời hạn do chủ xe khai báo; hãy đối chiếu giấy tờ gốc. Hệ thống không lưu bản chụp giấy tờ.</p></details>
        </div>
         <section className="my-profile-history"><h3>Lịch sử sửa chữa và bảo dưỡng đã ghi</h3><div className="my-profile-filters"><label>Năm <select value={historyYear} onChange={e=>setHistoryYear(e.target.value)}><option value="">Tất cả</option>{years.map(y=><option key={y}>{y}</option>)}</select></label><label>Trạng thái <select value={historyStatus} onChange={e=>setHistoryStatus(e.target.value)}><option value="">Tất cả</option>{Array.from(new Set(completedHistory.map(r=>r.order_status).filter(Boolean))).map(s=><option key={s}>{s}</option>)}</select></label><label>Hạng mục <input value={historyService} onChange={e=>setHistoryService(e.target.value)} placeholder="Tìm dịch vụ"/></label></div>{!completedHistory.length?<p>Chưa có lịch sử hoàn thành được ghi nhận cho xe này.</p>:!filteredHistory.length?<p>Không có lịch sử phù hợp bộ lọc.</p>:filteredHistory.map(row=><details key={row.id}><summary><span><strong>{row.order_code||'Lần sửa chữa'}</strong> · {date(row.repaired_at)} · {row.services||'Chưa có hạng mục'}</span><small>{row.mileage!=null?km(row.mileage):'Không ghi km'} · {row.order_status||'Chưa có trạng thái phiếu'}{row.review_flags?.length?' · Cần đối chiếu':''}</small></summary><div className="my-profile-history-detail">{row.review_flags?.map((flag:string)=><p className="my-profile-warning" key={flag}>{flag}</p>)}<p>Ngày tiếp nhận: {date(row.received_at)} · Chi phí đã ghi: {row.total!=null?money(row.total):'Chưa cập nhật'}</p><p>Dịch vụ: {(row.items||[]).filter((item:any)=>item.kind==='Dịch vụ').map((item:any)=>item.name).join(', ')||'Chưa có chi tiết'}</p><p>Phụ tùng thực tế trong phiếu: {(row.parts||[]).map((item:any)=>item.name).join(', ')||'Chưa có ghi nhận xuất dùng'}</p><p>Báo giá: {na(row.quote_code)} · Hóa đơn: {na(row.invoice_code)}</p><p>Yêu cầu khi tiếp nhận: {na(row.customer_request)}</p><p>Kết quả kiểm tra: {na(row.inspection_notes)}</p><p>Ghi chú lịch sử: {na(row.note)}</p></div></details>)}</section>
         <section className="my-profile-process"><h3>Phiếu đang xử lý</h3>{vehicle.orders.filter(open).length?vehicle.orders.filter(open).map(row=><p key={row.id}><strong>{row.code}</strong> · {row.status} · {na(row.note)}</p>):<p>Không có phiếu đang xử lý.</p>}<h3>Lịch hẹn chưa tiếp nhận</h3>{vehicle.appointments.filter(row=>!['Đã hủy','Đã tiếp nhận'].includes(row.status)).length?vehicle.appointments.filter(row=>!['Đã hủy','Đã tiếp nhận'].includes(row.status)).map(row=><p key={row.id}>{date(row.appointment_at)} · {row.service} · {row.status}</p>):<p>Không có lịch hẹn chưa tiếp nhận.</p>}</section>
        <section className="my-profile-reminders"><h3>Nhắc lịch bảo dưỡng</h3><p>{plan?`Lịch tham khảo theo nguồn: ${p.maintenance_source}. ${p.next_service_at?`Ngày ${date(p.next_service_at)}. `:''}${p.next_service_mileage!=null?`Mốc ${km(p.next_service_mileage)}. `:''}${p.maintenance_items?`Hạng mục đã xác minh: ${p.maintenance_items}.`:''}`:'Chưa có chu kỳ, hạng mục hoặc mốc bảo dưỡng được garage xác minh cho xe này. Hỏi kỹ thuật viên để lập kế hoạch.'} Đây không phải lịch hẹn đã xác nhận.</p></section>
         <section className="my-profile-ai"><h3><Sparkles size={17}/> Hỏi trợ lý về xe này</h3><button className="btn secondary" onClick={()=>onOpenAI(vehicle.id)}>Hỏi AI về xe này · {vehicle.plate}</button><div>{['Tóm tắt lịch sử sửa chữa của xe tôi.','Xe đã thay những phụ tùng nào?','Xe còn bao nhiêu km nữa đến kỳ bảo dưỡng?','Những hạng mục nào cần kiểm tra trong lần bảo dưỡng tiếp theo?','Giải thích những hạng mục sửa chữa trong phiếu gần nhất.'].map(q=><button key={q} disabled={asking} onClick={()=>void ask(vehicle,q)}>{q}</button>)}</div>{asking&&<p role="status">Đang đối chiếu hồ sơ...</p>}{answer?.vehicleId===vehicle.id&&<div className="my-profile-answer" role="status"><strong>{answer.question}</strong><p>{answer.result.result}</p>{answer.result.sources?.length?<small>Nguồn: {answer.result.sources.map(source=>source.label).join(' · ')}</small>:<small>Chưa có nguồn đối chiếu cho câu trả lời này.</small>}</div>}</section>
        {editing===vehicle.id&&<form className="my-profile-form" onSubmit={event=>void save(event,vehicle)}><h3>Cập nhật hồ sơ · {vehicle.plate}</h3><p>Chỉ cập nhật dữ liệu bạn cung cấp. VIN, biển số và thông số kỹ thuật cần garage xác minh.</p><div>{editable.map(key=>{const inputId=`vehicle-${vehicle.id}-${key}`;return <label key={key} htmlFor={inputId}>{ownerLabels[key]}<input id={inputId} type={dates.has(key)?'date':numeric.has(key)?'number':'text'} min={key==='mileage'?Math.max(vehicle.mileage||0,...vehicle.history.map(row=>Number(row.mileage||0))):key==='first_registration_year'?1900:numeric.has(key)?1:undefined} max={key==='first_registration_year'?2100:undefined} value={draft[key]||''} onChange={event=>setDraft(current=>({...current,[key]:event.target.value}))}/></label>})}</div><footer><button type="button" className="btn secondary" onClick={()=>setEditing(null)}><X size={15}/> Hủy</button><button className="btn primary" disabled={saving} type="submit"><Save size={15}/>{saving?'Đang lưu...':'Lưu thông tin'}</button></footer></form>}
      </article>;
    })}
  </div>;
}
