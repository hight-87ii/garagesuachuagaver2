import { Clock3 } from 'lucide-react';

export const workTime = (minutes: number) => {
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return hours ? `${hours} giờ${remainder ? ` ${remainder} phút` : ''}` : `${remainder} phút`;
};

export default function EstimatedWorkTime({ document }: { document: any }) {
  const services = (document.items || []).filter((item: any) => item.kind === 'Dịch vụ' && item.estimated_duration_min);
  if (!document.estimated_duration_min && !services.length) return null;
  return <section className="work-section estimated-work-time">
    <div><Clock3 size={18}/><h3>Thời lượng sửa chữa dự kiến</h3></div>
    {document.estimated_duration_min && <strong>{workTime(Number(document.estimated_duration_min))}</strong>}
    {services.length > 0 && <ul>{services.map((item: any) => <li key={item.id}><span>{item.name} × {item.quantity}{item.estimate_source ? ` · ${item.estimate_source === 'history' ? 'theo lịch sử thực hiện' : 'theo danh mục'}` : ''}</span><b>{workTime(Number(item.estimated_duration_min))}</b></li>)}</ul>}
    <p>Ước tính từ danh mục dịch vụ hoặc các lần thực hiện đã ghi nhận; chưa gồm chờ phụ tùng, kiểm tra phát sinh. Garage xác nhận lịch giao xe sau khi kiểm tra thực tế.</p>
  </section>;
}
