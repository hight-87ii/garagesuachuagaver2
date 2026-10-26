import { useState } from 'react';
import { CircleAlert, PackagePlus, X } from 'lucide-react';

export type RequestedPart = {part_id?:number;name:string;quantity:number};
type PartOption = {id:number;code:string;name:string;compatible:string;unit:string;sell_price:number;availability:string};
const money=(value:number)=>new Intl.NumberFormat('vi-VN').format(value)+' ₫';

export default function AppointmentPartPicker({parts,selected,onChange,step}:{parts:PartOption[];selected:RequestedPart[];onChange:(value:RequestedPart[])=>void;step:string}){
  const [search,setSearch]=useState('');
  const [partId,setPartId]=useState('');
  const [custom,setCustom]=useState('');
  const [quantity,setQuantity]=useState(1);
  const visible=parts.filter(part=>`${part.name} ${part.code} ${part.compatible}`.toLocaleLowerCase('vi-VN').includes(search.toLocaleLowerCase('vi-VN')));
  function add(){
    const option=parts.find(part=>String(part.id)===partId);
    const name=option?.name||custom.trim();
    if(name.length<2||selected.length>=10)return;
    if(selected.some(item=>option?item.part_id===option.id:!item.part_id&&item.name.toLocaleLowerCase('vi-VN')===name.toLocaleLowerCase('vi-VN')))return;
    onChange([...selected,{...(option?{part_id:option.id}:{}),name,quantity}]);
    setPartId('');setCustom('');setQuantity(1);
  }
  return <section className="appointment-part-section"><div className="appointment-section-title"><span>{step}</span><div><h3>Phụ tùng muốn kiểm tra / thay thế</h3><p>Chọn từ danh mục hoặc ghi tên phụ tùng bạn đang quan tâm.</p></div></div>
    <div className="appointment-part-controls"><label>Tìm trong danh mục<input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Tên, mã hoặc dòng xe..."/></label><label>Phụ tùng<select value={partId} onChange={event=>{setPartId(event.target.value);if(event.target.value)setCustom('')}}><option value="">Chọn phụ tùng (không bắt buộc)</option>{visible.map(part=><option key={part.id} value={part.id}>{part.name} · {part.availability} · {money(part.sell_price)}</option>)}</select></label><label>Hoặc nhập yêu cầu khác<input value={custom} disabled={Boolean(partId)} maxLength={120} onChange={event=>setCustom(event.target.value)} placeholder="Ví dụ: muốn kiểm tra lọc gió..."/></label><label>Số lượng dự kiến<input type="number" min={1} max={20} value={quantity} onChange={event=>setQuantity(Number(event.target.value))}/></label><button type="button" className="btn secondary" disabled={(!partId&&custom.trim().length<2)||quantity<1||quantity>20||selected.length>=10} onClick={add}><PackagePlus size={16}/> Thêm yêu cầu</button></div>
    {selected.length>0&&<div className="appointment-part-selected">{selected.map((item,index)=>{const option=parts.find(part=>part.id===item.part_id);return <div key={`${item.part_id||item.name}-${index}`}><span><strong>{item.name}</strong><small>{item.quantity} {option?.unit||'món'} · {option?`${money(option.sell_price)}/đơn vị · ${option.availability}`:'Garage sẽ kiểm tra và tư vấn'}</small></span><button type="button" onClick={()=>onChange(selected.filter((_,i)=>i!==index))} aria-label={`Bỏ ${item.name}`}><X size={15}/></button></div>})}</div>}
    <p className="appointment-part-caution"><CircleAlert size={15}/> Đây là nhu cầu ban đầu, không phải xác nhận thay thế hay đặt giữ hàng. Kỹ thuật viên kiểm tra xe, đối chiếu phụ tùng và trao đổi lại với bạn trước khi lập báo giá chính thức.</p>
  </section>;
}
