import React from 'react';
import { CircleAlert } from 'lucide-react';

const money=(value:number)=>new Intl.NumberFormat('vi-VN').format(Number(value||0))+' ₫';

export default function InvoiceItemsSection({invoice}:{invoice:any}){
  const items=invoice.items||[];
  const labor=items.filter((item:any)=>item.kind==='Dịch vụ').reduce((sum:number,item:any)=>sum+Number(item.line_total||0),0);
  const parts=items.filter((item:any)=>item.kind==='Phụ tùng').reduce((sum:number,item:any)=>sum+Number(item.line_total||0),0);
  return <section className="work-section billing-item-section"><div className="billing-item-title"><div><h3>Dịch vụ &amp; linh kiện đã thực hiện</h3><p>Đơn giá là snapshot tại thời điểm lập hóa đơn.</p></div><span>{items.length} hạng mục</span></div>{items.length?<div className="item-table-wrap"><table className="billing-item-table"><thead><tr><th>LOẠI</th><th>DỊCH VỤ / LINH KIỆN</th><th>SỐ LƯỢNG</th><th>ĐƠN GIÁ</th><th>THÀNH TIỀN</th></tr></thead><tbody>{items.map((item:any)=><tr key={item.id}><td><span className={`billing-kind ${item.kind==='Dịch vụ'?'service':'part'}`}>{item.kind}</span></td><td><strong>{item.name}</strong></td><td>{Number(item.quantity).toLocaleString('vi-VN')}</td><td>{money(item.unit_price)}</td><td><strong>{money(item.line_total)}</strong></td></tr>)}</tbody><tfoot><tr><td colSpan={4}>Tổng tiền công dịch vụ</td><td>{money(labor)}</td></tr><tr><td colSpan={4}>Tổng tiền linh kiện / phụ tùng</td><td>{money(parts)}</td></tr></tfoot></table></div>:<div className="billing-items-empty"><CircleAlert/><span>Hóa đơn cũ chưa có snapshot hạng mục. Hệ thống sẽ bổ sung từ báo giá hoặc phiếu sửa chữa.</span></div>}</section>;
}
