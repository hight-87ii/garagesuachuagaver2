import { useCallback, useEffect, useRef, useState } from 'react';
import { Bell, CalendarDays, CircleAlert, ClipboardList, Package, ReceiptText, RefreshCw, X } from 'lucide-react';

type Notice = { id: string; title: string; description: string; page: string; kind: string };
const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8014';
const icons = { appointment: CalendarDays, repair: ClipboardList, invoice: ReceiptText, part: Package };

export default function NotificationBell({ userId, onNavigate }: { userId: number; onNavigate: (page: string) => void }) {
  const [items, setItems] = useState<Notice[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const holder = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const response = await fetch(`${API}/api/v1/notifications`, {
        headers: { Authorization: `Bearer ${sessionStorage.getItem('garage_token') || ''}` },
      });
      if (!response.ok) throw new Error('Không tải được thông báo.');
      const data = await response.json();
      setItems(data.items || []);
    } catch (err) { setError(err instanceof Error ? err.message : 'Không tải được thông báo.'); }
    finally { setLoading(false); }
  }, [userId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!open) return;
    function dismiss(event: MouseEvent | KeyboardEvent) {
      if (event instanceof KeyboardEvent) {
        if (event.key === 'Escape') setOpen(false);
      } else if (!holder.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', dismiss);
    document.addEventListener('keydown', dismiss);
    return () => { document.removeEventListener('mousedown', dismiss); document.removeEventListener('keydown', dismiss); };
  }, [open]);

  return <div className="notification-holder" ref={holder}>
    <button className="icon-button notification" aria-label={`Thông báo: ${items.length} việc cần xem`} aria-expanded={open} aria-controls="notifications-panel" onClick={() => { if (!open) load(); setOpen(!open); }}>
      <Bell size={20}/>{items.length > 0 && <i aria-hidden="true"/>}
    </button>
    {open && <section className="notifications-panel" id="notifications-panel" aria-label="Việc cần chú ý">
      <div className="notifications-head"><div><strong>Việc cần chú ý</strong><small>{items.length} mục từ dữ liệu garage</small></div><button onClick={() => load()} aria-label="Làm mới thông báo" disabled={loading}><RefreshCw size={17}/></button><button onClick={() => setOpen(false)} aria-label="Đóng thông báo"><X size={17}/></button></div>
      <div className="notifications-list">
        {loading && !items.length ? <p className="notifications-empty">Đang tải thông báo...</p> : error ? <p className="notifications-empty" role="alert"><CircleAlert size={16}/>{error}</p> : items.length ? items.map(item => {
          const Icon = icons[item.kind as keyof typeof icons] || Bell;
          return <button key={item.id} className="notification-item" onClick={() => { onNavigate(item.page); setOpen(false); }}><span><Icon size={18}/></span><span><strong>{item.title}</strong><small>{item.description}</small></span></button>;
        }) : <p className="notifications-empty">Hiện không có việc nào cần chú ý.</p>}
      </div>
      <p className="notifications-foot">Các nhắc việc sẽ tự biến mất khi dữ liệu liên quan được xử lý.</p>
    </section>}
  </div>;
}
