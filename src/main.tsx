import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Bell, CalendarDays, CarFront, ChevronDown, CircleDollarSign, ClipboardList, Clock3, Gauge,
  LayoutDashboard, Menu, Package, Plus, Search, Settings, Sparkles, Users, Wrench, X, ArrowUpRight,
  CheckCircle2, CircleAlert, MoreHorizontal, Bot, Send, FileText, PanelLeftClose
  , LogOut, Mail, LockKeyhole, Eye, EyeOff, ShieldCheck
  , Trash2, Phone, MapPin, History, Pencil, UserPlus, Wallet
  , BarChart3, Database, TrendingUp, ReceiptText
  , UserCog, FileCheck2, SlidersHorizontal, Shield, Building2
} from 'lucide-react';
import './styles.css';
import { AIService } from './services/aiService';
import UsersAccessPage from './UsersAccessPage';
import QuotesManagementPage from './QuotesManagementPage';
import SystemSettingsManagementPage from './SystemSettingsManagementPage';
import ServicesManagementPage from './ServicesManagementPage';
import CustomerInvoicesPage from './CustomerInvoicesPage';
import AppointmentCreateModal from './AppointmentCreateModal';
import type { AppointmentSelection } from './AppointmentCreateModal';
import CustomerDashboardPage from './CustomerDashboardPage';
import CashierBillingPage from './CashierBillingPage';
import ServiceFollowUpChat from './ServiceFollowUpChat';
import AISourceReferences, { type AISource } from './AISourceReferences';
import ManagerDashboardPage from './ManagerDashboardPage';
import ChatAssistant from './ChatAssistant';
import TechnicalKnowledgePage from './TechnicalKnowledgePage';
import RepairKnowledgeCasePanel from './RepairKnowledgeCasePanel';
import PartFitmentsModal from './PartFitmentsModal';
import PaymentRecordDialog from './PaymentRecordDialog';
import NotificationBell from './NotificationBell';
import ActualDurationCell from './ActualDurationCell';
import EstimatedWorkTime, { workTime } from './EstimatedWorkTime';

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8014';
let sessionUserCache:any=null;

const ROLE_HOME: Record<string, string> = {
  'Lễ tân': 'Lịch hẹn', 'Kỹ thuật viên': 'Phiếu sửa chữa', 'Khách hàng': 'Tổng quan',
};

// Authorization phía client: kiểm tra quyền trước khi hiển thị/điều hướng.
function userPermissions(user: any): string[] {
  return user?.permissions || [];
}
function can(user: any, permission: string): boolean {
  const granted = userPermissions(user);
  return granted.includes('*') || granted.includes(permission);
}
function homeFor(user: any): string {
  return ROLE_HOME[user?.role] || 'Tổng quan';
}

// Gọi API kèm token để backend xác thực (authentication) và kiểm tra quyền.
// Đường dẫn được tự động phiên bản hóa thành /api/v1 (API có version).
function api(path: string, options: RequestInit = {}): Promise<Response> {
  const versioned = path.startsWith('/api/') ? path.replace('/api/', '/api/v1/') : path;
  const headers: Record<string, string> = { ...(options.headers as any) };
  const token = sessionStorage.getItem('garage_token');
  if (token && !headers.Authorization) headers.Authorization = `Bearer ${token}`;
  return fetch(`${API}${versioned}`, { ...options, headers });
}

// Chuẩn hóa phản hồi danh sách: backend trả về { items, total, page, ... }.
async function readList(response: Response): Promise<any[]> {
  const data = await response.json();
  return Array.isArray(data) ? data : (data?.items ?? []);
}

// Chỉ là cấu trúc rỗng khi chưa tải API, không chứa dữ liệu nghiệp vụ mẫu.
const emptyDashboard = { metrics: { appointments: 0, in_progress: 0, completed: 0, revenue: 0, growth: 0 }, appointments: [] as any[], repair_orders: [] as any[], revenue: [0, 0, 0, 0, 0, 0, 0] };

type Data = typeof emptyDashboard;
const money = (value: number) => new Intl.NumberFormat('vi-VN').format(value) + ' ₫';
const menu = [
  ['Tổng quan', LayoutDashboard, 'dashboard'], ['Lịch hẹn', CalendarDays, 'appointments'], ['Phiếu sửa chữa', ClipboardList, 'repair_orders'],
  ['Khách hàng', Users, 'customers'], ['Xe', CarFront, 'vehicles'], ['Xe của tôi', CarFront, 'my_vehicles'],
  ['Tiếp nhận xe', CarFront, 'appointments'], ['Dịch vụ', Wrench, 'services'], ['Kho phụ tùng', Package, 'inventory'],
  ['Báo giá', FileCheck2, 'repair_orders'], ['Hóa đơn', CircleDollarSign, 'invoices'], ['Tra cứu & báo cáo', BarChart3, 'reports'],
  ['Trung tâm trợ lý AI', Bot, 'dashboard'], ['Người dùng & phân quyền', UserCog, 'staff'], ['Cài đặt hệ thống', SlidersHorizontal, 'staff']
] as const;
const CUSTOMER_MENU = new Set(['Tổng quan','Lịch hẹn','Xe của tôi','Hóa đơn','Trung tâm trợ lý AI']);
const permissionOf = (label: string) => menu.find(([name]) => name === label)?.[2] || 'dashboard';

function App() {
  const [user, setUser] = useState<any>(null);
  const [authChecking, setAuthChecking] = useState(() => Boolean(sessionStorage.getItem('garage_token')));
  const [data, setData] = useState<Data>(emptyDashboard);
  const [dashboardError,setDashboardError]=useState('');
  const [active, setActive] = useState('Tổng quan');
  const [sidebar, setSidebar] = useState(false);
  const [modal, setModal] = useState(false);
  const [appointmentSelection,setAppointmentSelection]=useState<AppointmentSelection|null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedAppointment, setSelectedAppointment] = useState<any>(null);
  const [apptCount, setApptCount] = useState<number | null>(null);
  const [custCount, setCustCount] = useState<number | null>(null);
  const [vehicleCount, setVehicleCount] = useState<number | null>(null);

  useEffect(() => {
    const token = sessionStorage.getItem('garage_token');
    if (!token) { setAuthChecking(false); return; }
    api(`/api/auth/me`, {headers:{Authorization:`Bearer ${token}`}}).then(async r => {
      if (!r.ok) throw new Error();
      const profile = await r.json(); sessionUserCache=profile; setUser(profile);
    }).catch(() => { sessionStorage.removeItem('garage_token'); sessionUserCache=null; setUser(null); }).finally(() => setAuthChecking(false));
  }, []);
  useEffect(() => { if (user) api(`/api/dashboard`).then(async r => {if(!r.ok)throw new Error();setData(await r.json());setDashboardError('')}).catch(() => {setData(emptyDashboard);setDashboardError('Không tải được dữ liệu tổng quan từ database.')}); }, [user]);
  // Role-based routing: sau khi xác thực, đưa người dùng về trang mặc định của vai trò.
  useEffect(() => { if (user) setActive(homeFor(user)); }, [user?.role]);

  const filteredOrders = useMemo(() => data.repair_orders.filter(order =>
    `${order.code} ${order.plate} ${order.technician}`.toLowerCase().includes(query.toLowerCase())), [data, query]);
  const revenueTotal = data.revenue.reduce((sum, value) => sum + Number(value || 0), 0);
  const revenueMax = Math.max(...data.revenue.map(Number), 1);

  async function openAppointment(appointment: any) {
    setSelectedAppointment({ ...appointment, loading: true });
    try {
      const response = await api(`/api/appointments/${appointment.id}`);
      if (!response.ok) {setSelectedAppointment(null); return}
      setSelectedAppointment(await response.json());
    } catch { setSelectedAppointment(null); }
  }

  function updateAppointmentStatus(id: number, status: string) {
    setData(current => ({ ...current, appointments: current.appointments.map(item => item.id === id ? { ...item, status } : item) }));
    setSelectedAppointment((current: any) => ({ ...current, status }));
  }

  function authenticated(payload:any) {
    sessionStorage.setItem('garage_token', payload.access_token);
    sessionUserCache=payload.user;
    setUser(payload.user);
  }

  function logout() {
    sessionStorage.removeItem('garage_token'); sessionUserCache=null; setUser(null);
  }

  function openAppointmentFromAI(selection:AppointmentSelection){
    setAppointmentSelection(selection);
    setAiOpen(false);
    setModal(true);
  }
  function openAppointmentLink(id:number){
    setAiOpen(false);
    setActive('Lịch hẹn');
    openAppointment({id});
  }

  if (authChecking) return <div className="auth-loading"><div className="auth-logo"><Wrench/></div><span>Đang kiểm tra phiên đăng nhập...</span></div>;
  if (!user) return <AuthScreen onAuthenticated={authenticated}/>;

  // Authorization phía client: menu chỉ hiển thị chức năng vai trò được phép;
  // truy cập trang không có quyền sẽ bị đưa về trang mặc định của vai trò.
  // "Xe của tôi" chỉ dành cho Khách hàng (kể cả Admin cũng không thấy mục này).
  const allowedMenu = menu.filter(([label, , permission]) =>
    user.role === 'Khách hàng' ? CUSTOMER_MENU.has(label)
    : label === 'Tiếp nhận xe' ? ['Admin','Quản lý','Lễ tân'].includes(user.role)
    : permission === 'my_vehicles' ? user.role === 'Khách hàng' : can(user, permission)
  );
  const activeAllowed = user.role === 'Khách hàng'
    ? CUSTOMER_MENU.has(active) || active === 'Cài đặt'
    : can(user, permissionOf(active));
  const page = activeAllowed ? active : homeFor(user);
  const isManager = user.role === 'Admin' || user.role === 'Quản lý';

  return <div className="app-shell">
    <aside className={`sidebar ${sidebar ? 'open' : ''}`}>
      <div className="brand"><div className="brand-mark"><Wrench size={22}/></div><div><strong>ThreeH <span>Workshop</span></strong><small>Quản lý thông minh</small></div><button className="mobile-close" onClick={() => setSidebar(false)}><PanelLeftClose/></button></div>
       <nav><p className="nav-label">QUẢN LÝ</p>{allowedMenu.map(([label, Icon]) => <button key={label} className={page === label ? 'active' : ''} onClick={() => {setActive(label); setSidebar(false)}}><Icon size={19}/><span>{label}</span>{label === 'Lịch hẹn' && apptCount !== null && <b>{apptCount}</b>}{label === 'Khách hàng' && custCount !== null && <b>{custCount}</b>}{label === 'Xe' && vehicleCount !== null && <b>{vehicleCount}</b>}</button>)}</nav>
      <div className="sidebar-bottom">
         <button className={page === 'Cài đặt' ? 'active' : ''} onClick={() => {setActive('Cài đặt'); setSidebar(false)}}><Settings size={19}/><span>Cài đặt</span></button>
        <div className="user"><div className="avatar">{user.full_name.split(' ').slice(-2).map((x:string)=>x[0]).join('').toUpperCase()}</div><div><strong>{user.full_name}</strong><small>{user.role}</small></div><button className="logout-button" onClick={logout} title="Đăng xuất" aria-label="Đăng xuất"><LogOut size={17}/></button></div>
      </div>
    </aside>
    {sidebar && <div className="overlay" onClick={() => setSidebar(false)}/>} 

    <main>
      <header>
        <button className="icon-button menu-button" onClick={() => setSidebar(true)}><Menu/></button>
        <div className="search"><Search size={18}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Tìm biển số, khách hàng, phiếu sửa chữa..."/><kbd>⌘ K</kbd></div>
         <div className="header-actions"><NotificationBell userId={user.id} onNavigate={setActive}/><div className="today"><small>Hôm nay</small><strong>{new Intl.DateTimeFormat('vi-VN',{day:'2-digit',month:'long',year:'numeric'}).format(new Date())}</strong></div></div>
      </header>

       {page === 'Cài đặt'
         ? <SettingsPage user={user}/>
         : page === 'Lịch hẹn'
         ? <AppointmentsPage onOpenAI={() => setAiOpen(true)} onLoaded={setApptCount}/>
         : page === 'Tiếp nhận xe'
         ? <AppointmentsPage onOpenAI={() => setAiOpen(true)} receptionMode/>
        : page === 'Khách hàng'
        ? <CustomersPage onOpenAI={() => setAiOpen(true)} onLoaded={setCustCount}/>
        : page === 'Xe'
        ? <VehiclesPage onOpenAI={() => setAiOpen(true)} onLoaded={setVehicleCount}/>
        : page === 'Xe của tôi'
        ? <MyVehiclesPage onOpenAI={() => setAiOpen(true)}/>
         : page === 'Hóa đơn'
         ? user.role === 'Khách hàng' ? <CustomerInvoicesPage apiBase={API}/> : <CashierBillingPage apiBase={API}/>
         : page === 'Dịch vụ'
         ? <ServicesManagementPage apiBase={API} onOpenAI={() => setAiOpen(true)}/>
        : page === 'Kho phụ tùng'
        ? <InventoryPage onOpenAI={() => setAiOpen(true)}/>
         : page === 'Phiếu sửa chữa'
         ? <RepairOrdersPage onOpenAI={() => setAiOpen(true)}/>
         : page === 'Báo giá'
         ? <QuotesManagementPage currentUser={user} apiBase={API} onNavigate={setActive}/>
         : page === 'Tra cứu & báo cáo'
         ? <ReportsPage/>
         : page === 'Trung tâm trợ lý AI'
           ? <AICenterPage onNavigate={setActive} user={user} onAddToAppointment={openAppointmentFromAI} onOpenAppointment={openAppointmentLink}/>
         : page === 'Người dùng & phân quyền'
         ? <UsersAccessPage currentUser={user} apiBase={API}/>
         : page === 'Cài đặt hệ thống'
         ? <SystemSettingsManagementPage currentUser={user} apiBase={API}/>
          : page === 'Tổng quan' && user.role === 'Khách hàng'
          ? <CustomerDashboardPage user={user} apiBase={API} onNavigate={setActive} onNewAppointment={()=>setModal(true)} onOpenAI={()=>setAiOpen(true)}/>
          : page === 'Tổng quan' && user.role === 'Quản lý'
          ? <ManagerDashboardPage user={user} apiBase={API} onNavigate={setActive} onNewAppointment={()=>setModal(true)}/>
          : page === 'Tổng quan' && isManager
         ? <div className="page">
        {dashboardError&&<div className="inline-error report-error"><CircleAlert size={15}/>{dashboardError}</div>}
        <section className="page-heading"><div><p className="eyebrow">TRUNG TÂM ĐIỀU HÀNH</p><h1>{page}</h1><p>Xin chào {user.full_name}. Dữ liệu dưới đây được đồng bộ từ hệ thống.</p></div><div className="heading-actions"><button className="btn secondary" onClick={() => setAiOpen(true)}><Sparkles size={17}/> Trợ lý AI</button><button className="btn primary" onClick={() => setModal(true)}><Plus size={18}/> Tạo lịch hẹn</button></div></section>

        <section className="metrics">
          <Metric icon={CalendarDays} label="Lịch hẹn hôm nay" value={data.metrics.appointments} note="Theo database hiện tại" color="blue"/>
          <Metric icon={Gauge} label="Xe đang sửa" value={data.metrics.in_progress} note="Phiếu đang hoạt động" color="orange"/>
          <Metric icon={CheckCircle2} label="Đã hoàn thành" value={data.metrics.completed} note="Tổng phiếu hoàn thành" color="green"/>
          <Metric icon={CircleDollarSign} label="Doanh thu hôm nay" value={money(data.metrics.revenue)} note={`↗ ${data.metrics.growth}% so với hôm qua`} color="violet" wide/>
        </section>

        <section className="dashboard-grid">
          <div className="card schedule-card">
            <div className="card-title"><div><h2>Lịch hẹn gần nhất</h2><p>{data.appointments.length} lịch từ database</p></div><button>Xem tất cả <ArrowUpRight size={15}/></button></div>
            <div className="appointment-list">{data.appointments.map((a, i) => <div className="appointment" key={a.id} role="button" tabIndex={0} onClick={() => openAppointment(a)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') openAppointment(a) }}>
              <div className="time"><strong>{a.appointment_at.slice(11,16)}</strong><span>{a.duration_min||60} phút</span></div>
              <div className={`timeline-dot dot-${i}`}/><div className="appointment-main"><div className="car-icon"><CarFront size={20}/></div><div><strong>{a.customer_name}</strong><span>{a.service}</span></div></div>
              <div className="plate">{a.plate}</div><Status text={a.status}/><button className="dots"><MoreHorizontal/></button>
            </div>)}</div>
          </div>

          <div className="card revenue-card">
            <div className="card-title"><div><h2>Doanh thu 7 ngày</h2><p>Dữ liệu hóa đơn không bị hủy</p></div></div>
            <div className="revenue-head"><div><strong>{money(revenueTotal)}</strong></div><em>{data.revenue.some(Boolean) ? 'Dữ liệu thực' : 'Chưa có dữ liệu'}</em></div>
            <div className="mini-bars" aria-label="Biểu đồ doanh thu 7 ngày">{data.revenue.map((value,index)=><div key={index}><i style={{height:`${Math.max(2,Number(value)/revenueMax*100)}%`}} title={money(Number(value))}/><span>{['T2','T3','T4','T5','T6','T7','CN'][index]}</span></div>)}</div>
          </div>
        </section>

        <section className="card orders-card">
          <div className="card-title"><div><h2>Phiếu sửa chữa đang xử lý</h2><p>Theo dõi tiến độ công việc trong xưởng</p></div><button>Xem tất cả <ArrowUpRight size={15}/></button></div>
          <div className="table-wrap"><table><thead><tr><th>MÃ PHIẾU</th><th>XE / BIỂN SỐ</th><th>NỘI DUNG</th><th>KỸ THUẬT VIÊN</th><th>TRẠNG THÁI</th><th>TẠM TÍNH</th><th/></tr></thead><tbody>{filteredOrders.map((o) => <tr key={o.id}><td><strong className="order-code">{o.code}</strong><small>{formatMoment(o.opened_at)}</small></td><td><div className="vehicle-cell"><div className="mini-car"><CarFront size={19}/></div><div><strong>{o.make&&o.model?`${o.make} ${o.model}`:'Chưa cập nhật dòng xe'}</strong><small>{o.plate}</small></div></div></td><td>{o.note}</td><td><div className="tech"><span>{(o.technician||'—').split(' ').slice(-2).map((x:string)=>x[0]).join('')}</span>{o.technician||'Chưa phân công'}</div></td><td><OrderStatus code={statusCodeOf(o)}/></td><td><strong>{money(o.total)}</strong></td><td><button className="dots"><MoreHorizontal/></button></td></tr>)}</tbody></table></div>
        </section>

        <section className="bottom-grid"><div className="ai-banner"><div className="ai-orb"><Sparkles/></div><div><span className="ai-tag">THREEH WORKSHOP</span><h2>Tiếp nhận xe nhanh hơn với trợ lý AI</h2><p>Tóm tắt lịch sử sửa chữa từ dữ liệu xe trong hệ thống.</p></div><button onClick={() => setAiOpen(true)}>Thử ngay <ArrowUpRight size={16}/></button></div></section>
      </div>
        : page === 'Tổng quan'
        ? <RoleDashboard user={user} data={data} onOpenAI={() => setAiOpen(true)} onNewAppointment={() => setModal(true)} onOpenAppointment={openAppointment}/>
        : <PlaceholderPage title={page}/>}
    </main>

    {modal && <AppointmentCreateModal currentUser={user} apiBase={API} initialSelection={appointmentSelection} onClose={() => {setModal(false);setAppointmentSelection(null)}} onCreated={(appointment) => {setData({...data, appointments: [...data.appointments, appointment]}); setModal(false);setAppointmentSelection(null)}}/>}
    {selectedAppointment && <AppointmentDetail appointment={selectedAppointment} onClose={() => setSelectedAppointment(null)} onStatusChange={updateAppointmentStatus}/>} 
     {aiOpen && <div className="drawer-overlay" onClick={() => setAiOpen(false)}><aside className="ai-drawer assistant-drawer" onClick={event => event.stopPropagation()} aria-label="Trợ lý ThreeH Workshop"><div className="drawer-head"><div><span><Bot size={20}/></span><div><strong>Trợ lý ThreeH Workshop</strong><small><i/> Hỏi đáp theo quyền truy cập</small></div></div><button onClick={() => setAiOpen(false)} aria-label="Đóng trợ lý"><X/></button></div><ChatAssistant key={user.id} user={user} compact onAddToAppointment={openAppointmentFromAI} onOpenAppointment={openAppointmentLink}/></aside></div>}
  </div>
}

function QuotesPage(){
  const [quotes,setQuotes]=useState<any[]>([]);const [loading,setLoading]=useState(true);const [status,setStatus]=useState('Tất cả');const [selected,setSelected]=useState<any>(null);const [error,setError]=useState('');
  async function load(){setLoading(true);try{const r=await api('/api/quotes?page_size=200');if(!r.ok)throw new Error();setQuotes(await readList(r));setError('')}catch{setError('Không tải được danh sách báo giá.')}finally{setLoading(false)}}useEffect(()=>{load()},[]);
  async function open(item:any){const r=await api(`/api/quotes/${item.id}`);setSelected(r.ok?await r.json():item)}
  const visible=quotes.filter(q=>status==='Tất cả'||q.status===status);const total=visible.reduce((sum,q)=>sum+Number(q.total||0),0);
  return <div className="page"><section className="page-heading"><div><p className="eyebrow">KIỂM SOÁT CHI PHÍ</p><h1>Báo giá</h1><p>Theo dõi phiên bản nháp, chờ duyệt và báo giá đã được phê duyệt.</p></div></section><section className="metrics"><StatCard icon={FileCheck2} label="Tổng báo giá" value={quotes.length} note="Tất cả phiên bản" color="blue"/><StatCard icon={Clock3} label="Chờ duyệt" value={quotes.filter(q=>q.status==='Chờ duyệt').length} note="Cần người có thẩm quyền" color="orange"/><StatCard icon={CheckCircle2} label="Đã duyệt" value={quotes.filter(q=>q.status==='Đã duyệt').length} note="Có thể lập hóa đơn" color="green"/><StatCard icon={CircleDollarSign} label="Giá trị hiển thị" value={money(total)} note="Theo bộ lọc" color="violet"/></section><section className="card orders-card"><div className="card-title"><div><h2>Danh sách báo giá</h2><p>Giá và tổng tiền do backend tính</p></div></div><div className="order-toolbar"><div className="filter-tabs">{['Tất cả','Nháp','Chờ duyệt','Đã duyệt','Từ chối','Hết hiệu lực'].map(s=><button key={s} className={status===s?'active':''} onClick={()=>setStatus(s)}>{s}</button>)}</div></div>{error&&<div className="inline-error"><CircleAlert size={15}/>{error}</div>}{loading?<div className="detail-loading"><i/><span>Đang tải báo giá...</span></div>:<ReportTable headers={['MÃ BÁO GIÁ','PHIẾU / XE','PHIÊN BẢN','TRẠNG THÁI','TẠM TÍNH','THUẾ','TỔNG']} rows={visible.map(q=><tr key={q.id} onClick={()=>open(q)} className="clickable-row"><td><strong className="order-code">{q.code}</strong><small>{dateText(q.created_at)}</small></td><td><strong>{q.order_code}</strong><small>{q.plate}</small></td><td>v{q.version}</td><td><QuoteBadge status={q.status}/></td><td>{money(q.subtotal||0)}</td><td>{money(q.tax||0)}</td><td><strong>{money(q.total||0)}</strong></td></tr>)} empty="Chưa có báo giá."/>}</section>{selected&&<div className="drawer-overlay" onMouseDown={()=>setSelected(null)}><aside className="work-drawer" onMouseDown={e=>e.stopPropagation()}><div className="work-head"><div className="work-head-main"><div className="work-icon"><FileCheck2 size={20}/></div><div><strong>{selected.code}</strong><small>{selected.order_code} • {selected.plate}</small></div></div><button onClick={()=>setSelected(null)}><X/></button></div><div className="work-body"><div className="work-section"><h3>Trạng thái</h3><QuoteBadge status={selected.status}/></div><div className="work-section"><h3>Hạng mục báo giá</h3><ReportTable headers={['LOẠI','HẠNG MỤC','SL','ĐƠN GIÁ','THÀNH TIỀN']} rows={(selected.items||[]).map((i:any)=><tr key={i.id}><td>{i.kind}</td><td><strong>{i.name}</strong></td><td>{i.quantity}</td><td>{money(i.unit_price)}</td><td><strong>{money(i.line_total)}</strong></td></tr>)} empty="Báo giá chưa có hạng mục."/></div><div className="work-section total-section"><div className="total-row"><span>Tạm tính</span><strong>{money(selected.subtotal||0)}</strong></div><div className="total-row"><span>Chiết khấu</span><strong>{money(selected.discount||0)}</strong></div><div className="total-row"><span>Thuế</span><strong>{money(selected.tax||0)}</strong></div><div className="total-row note"><span>Tổng tiền</span><strong>{money(selected.total||0)}</strong></div></div>{selected.note&&<div className="work-section"><h3>Diễn giải</h3><p className="ai-summary-text">{selected.note}</p></div>}</div></aside></div>}</div>
}
function QuoteBadge({status}:{status:string}){return <span className={`status ${status==='Đã duyệt'?'green':status==='Chờ duyệt'?'orange':status==='Nháp'?'blue':'gray'}`}><i/>{status}</span>}

function AICenterPage({onNavigate,user,onAddToAppointment,onOpenAppointment}:{onNavigate:(page:string)=>void;user:any;onAddToAppointment:(selection:AppointmentSelection)=>void;onOpenAppointment:(id:number)=>void}){
  const [mode,setMode]=useState<'chat'|'history'|'service'|'quote'|'knowledge'>('chat');
  const [plate,setPlate]=useState('');
  const [orderCode,setOrderCode]=useState('');
  const [result,setResult]=useState<any>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const [customerOrders,setCustomerOrders]=useState<{code:string;plate:string}[]>([]);
  const [customerVehicles,setCustomerVehicles]=useState<any[]>([]);
  const [selectedVehicleId,setSelectedVehicleId]=useState('');
  const [customerDataLoading,setCustomerDataLoading]=useState(false);
  const aiCenterUser=sessionUserCache;
  const isCustomer=aiCenterUser?.role==='Khách hàng';

  // Khách hàng chỉ thấy mã phiếu thuộc hồ sơ của mình để chọn nhanh.
  useEffect(()=>{
    if(!isCustomer)return;
    let active=true;setCustomerDataLoading(true);
    api('/api/my-vehicles').then(async response=>{
      if(!response.ok)return;
      const data=await response.json();
      if(!active)return;
      const vehicles=data.vehicles||[];
      setCustomerVehicles(vehicles);
      setSelectedVehicleId(vehicles.length===1?String(vehicles[0].id):'');
      const seen=new Set<string>();
      const orders=vehicles.flatMap((vehicle:any)=>(vehicle.orders||[])
        .filter((order:any)=>order?.code)
        .map((order:any)=>({code:String(order.code),plate:String(vehicle.plate||'')})))
        .filter((order:any)=>{if(seen.has(order.code))return false;seen.add(order.code);return true});
      setCustomerOrders(orders);
    }).catch(()=>{}).finally(()=>{if(active)setCustomerDataLoading(false)});
    return ()=>{active=false};
  },[isCustomer]);

  function switchMode(next:'chat'|'history'|'service'|'quote'|'knowledge'){
    setMode(next);setResult(null);setOrderCode('');setError('');
  }

  async function run(codeOverride?:string){
    const code=String(codeOverride??orderCode).trim().toUpperCase();
    setLoading(true);setError('');setResult(null);
    try{
      if(mode==='history'){
        if(isCustomer){
          if(!customerVehicles.length)throw new Error('Tài khoản chưa có xe trong hồ sơ.');
          if(!selectedVehicleId)throw new Error('Vui lòng chọn xe cần tóm tắt.');
          setResult(await AIService.summarizeRepairHistory({vehicle_id:Number(selectedVehicleId)}));
        }else{
          if(!plate.trim())throw new Error('Vui lòng nhập biển số xe.');
          setResult(await AIService.summarizeRepairHistory({plate:plate.trim()}));
        }
      }else if(mode==='service'){
        if(!code)throw new Error('Vui lòng nhập hoặc chọn mã phiếu sửa chữa.');
        setOrderCode(code);
        setResult(await AIService.explainServicesByCode(code));
      }
    }catch(err:any){
      setError(err.message||'Trợ lý AI không phản hồi.');
    }finally{
      setLoading(false);
    }
  }

  const descriptions={
    chat:{title:'Trò chuyện cùng trợ lý',subtitle:'Hỏi trực tiếp về hồ sơ xe và giá phụ tùng tham khảo theo quyền của bạn.',label:'',placeholder:'',value:'',set:()=>{},action:''},
    history:{title:'Tóm tắt lịch sử sửa chữa',subtitle:'Tổng hợp các lần sửa, hạng mục, số km và ghi chú được phép truy cập.',label:'Biển số xe',placeholder:'Ví dụ: 51H-123.45',value:plate,set:setPlate,action:'Tạo bản tóm tắt'},
    service:{title:'Giải thích dịch vụ cho khách',subtitle:'Chuyển nội dung kỹ thuật và báo giá hiện tại thành ngôn ngữ dễ hiểu.',label:'Mã phiếu sửa chữa',placeholder:'Ví dụ: PSC-1028',value:orderCode,set:setOrderCode,action:'Tạo bản giải thích'},
    quote:{title:'Báo giá nháp có AI hỗ trợ',subtitle:'Chọn hạng mục trên phiếu; backend lấy giá và tính tổng, AI chỉ viết diễn giải.',label:'',placeholder:'',value:'',set:()=>{},action:''},
    knowledge:{title:'Kho kiến thức kỹ thuật',subtitle:'Soạn, kiểm tra nguồn và duyệt bài trước khi trợ lý trả lời khách.',label:'',placeholder:'',value:'',set:()=>{},action:''}
  } as const;
  const active=descriptions[mode];

  return <div className="page ai-center-page">
    <section className="page-heading"><div><p className="eyebrow">AI CÓ KIỂM SOÁT</p><h1>Trung tâm trợ lý AI</h1><p>Chọn đúng tác vụ, kiểm tra nguồn dữ liệu và duyệt nội dung trước khi sử dụng.</p></div><div className="report-live"><ShieldCheck size={16}/><span>Backend giữ quyền quyết định</span><i/></div></section>
    <section className="ai-trust-strip"><div><Database size={18}/><span><strong>Dữ liệu có nguồn</strong><small>Đọc từ hồ sơ garage</small></span></div><div><Shield size={18}/><span><strong>Theo quyền truy cập</strong><small>Không vượt phạm vi tài khoản</small></span></div><div><CircleAlert size={18}/><span><strong>Luôn là bản nháp</strong><small>Cần con người kiểm tra</small></span></div></section>
    <div className="ai-workspace">
      <nav className="card ai-task-nav" aria-label="Tác vụ AI"><p>CHỌN TÁC VỤ</p>
        <button className={mode==='chat'?'active':''} onClick={()=>switchMode('chat')}><Bot size={19}/><span><strong>Hỏi đáp trực tiếp</strong><small>Hồ sơ xe · giá tham khảo</small></span><ArrowUpRight size={15}/></button>
        <button className={mode==='history'?'active':''} onClick={()=>switchMode('history')}><History size={19}/><span><strong>Tóm tắt lịch sử</strong><small>Theo xe và các lần sửa</small></span><ArrowUpRight size={15}/></button>
        <button className={mode==='service'?'active':''} onClick={()=>switchMode('service')}><Wrench size={19}/><span><strong>Giải thích dịch vụ</strong><small>Theo phiếu và báo giá của bạn</small></span><ArrowUpRight size={15}/></button>
        {can(user,'repair_orders')&&<button className={mode==='quote'?'active':''} onClick={()=>switchMode('quote')}><FileCheck2 size={19}/><span><strong>Báo giá nháp</strong><small>Giá do backend kiểm soát</small></span><ArrowUpRight size={15}/></button>}
        {can(user,'repair_orders')&&<button className={mode==='knowledge'?'active':''} onClick={()=>switchMode('knowledge')}><Database size={19}/><span><strong>Kiến thức kỹ thuật</strong><small>Soạn bài · duyệt nguồn</small></span><ArrowUpRight size={15}/></button>}
        <div className="ai-nav-policy"><ShieldCheck size={18}/><p>{isCustomer?'AI chỉ truy cập hồ sơ xe và dịch vụ thuộc tài khoản của bạn.':'AI không thay đổi giá, trạng thái, tồn kho hoặc thanh toán.'}</p></div>
      </nav>
      <section className="card ai-console">
        <div className="ai-console-head"><span><Bot size={21}/></span><div><p>{mode==='quote'?'QUY TRÌNH NGHIỆP VỤ':'TRỢ LÝ ĐANG SẴN SÀNG'}</p><h2>{active.title}</h2><small>{active.subtitle}</small></div></div>
           {mode==='chat'?<ChatAssistant user={user} onAddToAppointment={onAddToAppointment} onOpenAppointment={onOpenAppointment}/>:mode==='knowledge'?<TechnicalKnowledgePage canPublish={can(user,'staff')}/>:mode==='quote'?<div className="ai-quote-guide">
          <div className="ai-process"><span><b>1</b>Chọn phiếu sửa chữa</span><i/><span><b>2</b>Chọn hạng mục</span><i/><span><b>3</b>Backend tính tiền</span><i/><span><b>4</b>AI viết diễn giải</span></div>
          <div className="ai-empty-visual"><FileCheck2 size={34}/><h3>Tạo báo giá trong chi tiết phiếu</h3><p>Dịch vụ, phụ tùng, số lượng và giá tham chiếu sẽ được backend đọc lại từ database. Báo giá luôn bắt đầu ở trạng thái Nháp.</p><button className="btn primary" onClick={()=>onNavigate('Phiếu sửa chữa')}>Đến phiếu sửa chữa <ArrowUpRight size={16}/></button></div>
        </div>:<>
          <div className="ai-query-box">
            <label>{mode==='history'&&isCustomer?'Xe của bạn':active.label}
              <div>
                <Search size={17}/>
                {mode==='history'&&isCustomer?<select value={selectedVehicleId} onChange={event=>{setSelectedVehicleId(event.target.value);setResult(null);setError('')}} disabled={customerDataLoading}>
                  <option value="">{customerDataLoading?'Đang tải hồ sơ xe...':'Chọn xe...'}</option>
                  {customerVehicles.map((vehicle:any)=><option key={vehicle.id} value={vehicle.id}>{vehicle.make} {vehicle.model} • {vehicle.plate}</option>)}
                </select>:<input
                  value={active.value}
                  onChange={event=>active.set(event.target.value.toUpperCase())}
                  placeholder={active.placeholder}
                  list={mode==='service'&&isCustomer&&customerOrders.length?'customer-order-codes':undefined}
                  onKeyDown={event=>{if(event.key==='Enter'&&active.value.trim())run()}}
                />}
                {mode==='service'&&isCustomer&&customerOrders.length>0&&<datalist id="customer-order-codes">{customerOrders.map(order=><option key={order.code} value={order.code}>{order.plate}</option>)}</datalist>}
                <button className="btn primary" disabled={loading||(mode==='history'&&isCustomer?!selectedVehicleId:!active.value.trim())} onClick={()=>run()}><Sparkles size={16}/>{loading?'Đang phân tích...':active.action}</button>
              </div>
            </label>
            {mode==='history'&&isCustomer&&customerVehicles.length===1&&<small className="ai-auto-selected"><CheckCircle2 size={13}/> Đã tự động chọn xe duy nhất trong tài khoản.</small>}
            {mode==='service'&&isCustomer&&customerOrders.length>0&&<div className="ai-order-chips"><span>Phiếu của bạn:</span>{customerOrders.slice(0,4).map(order=><button key={order.code} type="button" disabled={loading} onClick={()=>run(order.code)}>{order.code}<small>{order.plate}</small></button>)}</div>}
            <small><Database size={13}/> Dữ liệu được truy vấn trực tiếp từ database theo quyền hiện tại.{mode==='service'&&isCustomer?' Mã phiếu cũng có trong mục Hóa đơn.':''}</small>
          </div>
          {error&&<div className="inline-error ai-center-error"><CircleAlert size={15}/>{error}</div>}
          {loading&&<div className="ai-thinking"><div className="typing"><i/><i/><i/></div><strong>Đang đối chiếu dữ liệu nguồn...</strong><span>AI không được thêm thông tin ngoài hồ sơ.</span></div>}
          {!loading&&!result&&!error&&<div className="ai-empty-visual"><Bot size={34}/><h3>Chưa có nội dung được tạo</h3><p>{mode==='history'?(isCustomer?'Chọn xe trong hồ sơ để tổng hợp lịch sử sửa chữa và các dữ liệu còn thiếu.':'Nhập biển số để tổng hợp lịch sử sửa chữa và các dữ liệu còn thiếu.'):'Nhập hoặc chọn mã phiếu để giải thích các dịch vụ, lý do và chi phí đã được garage xác nhận.'}</p></div>}
          {result&&<>
            <AIResultView result={result}/>
            {mode==='service'&&<ServiceFollowUpChat key={result.ref_code||orderCode} orderCode={String(result.ref_code||orderCode).toUpperCase()}/>}
          </>}
        </>}
      </section>
    </div>
  </div>
}

function AIResultView({result}:{result:any}){
  const sections=String(result.result||'').split(/\n\s*\n/).map((text:string)=>text.trim()).filter(Boolean);
  const statusLabel=result.data_status==='error'||result.status==='error'?'Không thể xử lý đầy đủ':result.data_status==='no_data'||result.status==='no_data'?'Chưa có dữ liệu phù hợp':result.data_status==='partial'?'Có nguồn · còn thiếu dữ liệu':result.data_status==='sourced'?'Đã đối chiếu chứng từ':result.status==='fallback'?'Diễn giải dự phòng':result.status==='success'?'Có dữ liệu đối chiếu':result.status;
  return <div className="ai-result-panel">
    <div className="ai-result-meta"><span><CheckCircle2 size={16}/>Đã tạo bản nháp</span><b>{result.sources?.length??result.source_count??0} nguồn đối chiếu</b><em>{statusLabel}</em></div>
    <div className="ai-result-sections">{sections.map((section:string,index:number)=>{
      const clean=section.replace(/\*\*/g,'');
      const separator=clean.indexOf(':');
      const title=separator>0&&separator<70?clean.slice(0,separator):index===0?'Kết quả':'';
      const content=separator>0&&separator<70?clean.slice(separator+1).trim():clean;
      return <article key={index}>{title&&<h3>{title}</h3>}<p>{content}</p></article>;
    })}</div>
    {result.history_summary&&<HistoryTimeline summary={result.history_summary}/>} 
    <AISourceReferences sources={result.sources}/>
    {result.missing_data?.length>0&&<div className="ai-missing"><CircleAlert size={16}/><div><strong>Dữ liệu cần bổ sung</strong><p>{result.missing_data.join(' • ')}</p></div></div>}
    <footer><ShieldCheck size={14}/> Nội dung AI là bản nháp, cần kỹ thuật viên hoặc người có thẩm quyền xác nhận.</footer>
  </div>;
}

function HistoryTimeline({summary}:{summary:any}){
  const timeline=Array.isArray(summary?.timeline)?summary.timeline:[];
  if(!timeline.length)return null;
  const formatKm=(value:any)=>value==null?'Chưa có số km':`${new Intl.NumberFormat('vi-VN').format(Number(value))} km`;
  return <section className="history-timeline-block" aria-label="Chi tiết từng phiếu sửa chữa">
    <header><div><strong>Chi tiết từng phiếu</strong><small>Mở từng dòng để xem dịch vụ, phụ tùng, ghi chú và dữ liệu còn thiếu.</small></div><span>{timeline.length} lần</span></header>
    <div>{timeline.map((visit:any)=><details key={`${visit.id}-${visit.order_code}`}>
      <summary><span><b>{visit.order_code}</b><small>{visit.date} · {formatKm(visit.mileage)}</small></span><em>{visit.work_state}</em></summary>
      <div className="history-visit-detail">
        <p><strong>Dịch vụ thực tế</strong>{visit.services?.length?visit.services.map((item:any)=>`${item.name}${item.quantity?` × ${item.quantity}`:''}`).join(' • '):'Chưa có dữ liệu'}</p>
        <p><strong>Phụ tùng / vật tư thực tế</strong>{visit.parts?.length?visit.parts.map((item:any)=>`${item.name}${item.code?` [${item.code}]`:''}${item.quantity?` × ${item.quantity}`:''}`).join(' • '):'Không ghi nhận'}</p>
        <p><strong>Ghi chú kỹ thuật / kết quả</strong>{visit.technical_notes?.length?visit.technical_notes.join(' • '):'Chưa có dữ liệu được phép hiển thị'}</p>
        {visit.proposed_items?.length>0&&<p><strong>Đề xuất chưa có bằng chứng thực hiện</strong>{visit.proposed_items.map((item:any)=>`${item.name} (${item.quote_code} · ${item.quote_status})`).join(' • ')}</p>}
        {visit.missing_fields?.length>0&&<p className="history-missing"><strong>Dữ liệu còn thiếu</strong>{visit.missing_fields.join(' • ')}</p>}
      </div>
    </details>)}</div>
  </section>
}

function SystemSettingsPage({currentUser}:{currentUser:any}){const [form,setForm]=useState<any>(null);const [message,setMessage]=useState('');const [error,setError]=useState('');useEffect(()=>{api('/api/system-settings').then(async r=>{if(!r.ok)throw new Error();setForm(await r.json())}).catch(()=>setError('Không tải được cài đặt hệ thống.'))},[]);async function save(){const body={garage_name:form.garage_name,garage_phone:form.garage_phone,garage_address:form.garage_address,invoice_prefix:form.invoice_prefix,quote_valid_days:Number(form.quote_valid_days)};const r=await api('/api/system-settings',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok){const info=await readApiError(r);setError(info.message);return}setForm(await r.json());setMessage('Đã lưu cài đặt hệ thống.')}if(!form)return <div className="page"><div className="card report-loading"><i/><span>Đang tải cài đặt...</span></div></div>;const editable=currentUser.role==='Admin';return <div className="page"><section className="page-heading"><div><p className="eyebrow">CẤU HÌNH TOÀN HỆ THỐNG</p><h1>Cài đặt hệ thống</h1><p>Thông tin garage và các quy tắc vận hành đang áp dụng.</p></div>{editable&&<button className="btn primary" onClick={save}><CheckCircle2 size={16}/>Lưu cài đặt</button>}</section>{message&&<div className="inline-success report-error"><CheckCircle2 size={15}/>{message}</div>}{error&&<div className="inline-error report-error"><CircleAlert size={15}/>{error}</div>}<div className="settings-system-grid"><section className="card settings-card"><div><h2>Thông tin garage</h2><p>Hiển thị trên tài liệu và giao diện vận hành.</p></div><div className="settings-form"><label>Tên garage<input disabled={!editable} value={form.garage_name||''} onChange={e=>setForm({...form,garage_name:e.target.value})}/></label><label>Số điện thoại<input disabled={!editable} value={form.garage_phone||''} onChange={e=>setForm({...form,garage_phone:e.target.value})}/></label><label className="full-setting">Địa chỉ<input disabled={!editable} value={form.garage_address||''} onChange={e=>setForm({...form,garage_address:e.target.value})}/></label><label>Tiền tố hóa đơn<input disabled={!editable} value={form.invoice_prefix||'HD'} onChange={e=>setForm({...form,invoice_prefix:e.target.value.toUpperCase()})}/></label><label>Hiệu lực báo giá (ngày)<input disabled={!editable} type="number" min="1" max="90" value={form.quote_valid_days} onChange={e=>setForm({...form,quote_valid_days:e.target.value})}/></label></div></section><section className="card settings-card"><div><h2>Quy tắc chỉ đọc</h2><p>Cấu hình từ môi trường triển khai, cần khởi động lại để thay đổi.</p></div><div className="system-rule-list"><div><span>Thuế suất báo giá</span><strong>{Number(form.financial_rules.tax_rate*100).toLocaleString('vi-VN')}%</strong></div><div><span>Chiết khấu nháp mặc định</span><strong>{Number(form.financial_rules.draft_discount_rate*100).toLocaleString('vi-VN')}%</strong></div><div><span>Ngày làm việc</span><strong>{form.working_hours.days}</strong></div><div><span>Giờ làm việc</span><strong>{form.working_hours.start} — {form.working_hours.end}</strong></div></div></section></div></div>}

function ReportsPage() {
  const localDay=(d:Date)=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Ho_Chi_Minh',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);
  const today=()=>localDay(new Date());
  const monthStart=()=>`${today().slice(0,7)}-01`;
  const [from,setFrom]=useState(monthStart); const [to,setTo]=useState(today);
  const [appointmentStatus,setAppointmentStatus]=useState(''); const [historyQuery,setHistoryQuery]=useState('');
  const [invoiceStatus,setInvoiceStatus]=useState(''); const [orderStatus,setOrderStatus]=useState('');
  const [partCategory,setPartCategory]=useState(''); const [serviceCategory,setServiceCategory]=useState('');
  const [detail,setDetail]=useState<{kind:string;title:string;day?:string;month?:string;name?:string;stock?:string}|null>(null);
  const [detailData,setDetailData]=useState<any>(null); const [detailPage,setDetailPage]=useState(1);
  const [detailLoading,setDetailLoading]=useState(false); const [detailError,setDetailError]=useState('');
  const [aiQuestion,setAiQuestion]=useState(''); const [aiAnswer,setAiAnswer]=useState<any>(null); const [aiLoading,setAiLoading]=useState(false);
  const [topCount,setTopCount]=useState(5);
  const [granularity,setGranularity]=useState<'day'|'month'>('day'); const [tab,setTab]=useState('Tổng hợp');
  const [report,setReport]=useState<any>(null); const [loading,setLoading]=useState(true); const [error,setError]=useState('');
  useEffect(()=>{if(!detail)return;const previous=document.activeElement as HTMLElement;document.querySelector<HTMLButtonElement>('.report-detail-actions .btn.ghost')?.focus();const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape')setDetail(null)};window.addEventListener('keydown',onKey);return()=>{window.removeEventListener('keydown',onKey);previous?.focus()}},[detail]);
  async function load(nextFrom=from,nextTo=to,reset=false){if(nextFrom>nextTo){setError('Từ ngày không được sau đến ngày.');return}setLoading(true);setError('');setDetail(null);setAiAnswer(null);try{const q=new URLSearchParams({from_date:nextFrom,to_date:nextTo});if(!reset){if(appointmentStatus)q.set('appointment_status',appointmentStatus);if(invoiceStatus)q.set('invoice_status',invoiceStatus);if(orderStatus)q.set('order_status',orderStatus);if(partCategory)q.set('part_category',partCategory);if(serviceCategory)q.set('service_category',serviceCategory);if(historyQuery.trim())q.set('history_query',historyQuery.trim())}const r=await api(`/api/reports/overview?${q}`);if(!r.ok){if(r.status===404)throw new Error('Backend chưa nạp API báo cáo mới. Hãy khởi động lại backend rồi thử lại.');const info=await readApiError(r);throw new Error(info.message)}setReport(await r.json())}catch(err:any){setError(err.message||'Không tải được báo cáo.');setReport(null)}finally{setLoading(false)}}
  useEffect(()=>{load()},[]);
  function preset(kind:string){const endDate=new Date(`${today()}T12:00:00+07:00`);let startDate=new Date(endDate);
    if(kind==='yesterday'){startDate.setDate(endDate.getDate()-1);endDate.setDate(endDate.getDate()-1)}
    if(kind==='week'||kind==='last30')startDate.setDate(endDate.getDate()-(kind==='week'?6:29));
    if(kind==='month'||kind==='previous_month'){startDate.setDate(1);if(kind==='previous_month'){endDate.setDate(0);startDate.setMonth(startDate.getMonth()-1)}}
    if(kind==='quarter'||kind==='previous_quarter'){startDate.setMonth(Math.floor(startDate.getMonth()/3)*3,1);if(kind==='previous_quarter'){endDate.setTime(startDate.getTime()-86400000);startDate.setMonth(startDate.getMonth()-3)}}
    if(kind==='year')startDate.setMonth(0,1);
    const start=localDay(startDate),end=localDay(endDate);setFrom(start);setTo(end);void load(start,end)}
  async function openDetail(kind:string,title:string,extra:Record<string,string>={}){setDetail({kind,title,...extra});setDetailPage(1);setDetailData(null)}
  useEffect(()=>{if(!detail||!report)return;let active=true;setDetailLoading(true);setDetailError('');const q=new URLSearchParams({kind:detail.kind,from_date:report.period.from,to_date:report.period.to,page:String(detailPage)});for(const key of ['invoice_status','appointment_status','order_status','part_category','service_category']){if(report.filters?.[key])q.set(key,report.filters[key])}if(detail.kind==='history'&&report.filters?.history_query)q.set('q',report.filters.history_query);if(detail.day)q.set('day',detail.day);if(detail.month)q.set('month',detail.month);if(detail.name)q.set('name',detail.name);if(detail.stock)q.set('stock',detail.stock);api(`/api/reports/drilldown?${q}`).then(async r=>{if(!r.ok)throw new Error((await readApiError(r)).message);return r.json()}).then(data=>{if(active)setDetailData(data)}).catch(e=>{if(active)setDetailError(e.message)}).finally(()=>{if(active)setDetailLoading(false)});return()=>{active=false}},[detail,detailPage,report]);
  async function askReport(){if(!aiQuestion.trim()||!report)return;setAiLoading(true);setAiAnswer(null);try{const r=await api('/api/reports/explain',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:aiQuestion,from_date:report.period.from,to_date:report.period.to,...report.filters})});if(!r.ok)throw new Error((await readApiError(r)).message);setAiAnswer(await r.json())}catch(e:any){setAiAnswer({result:e.message,status:'error'})}finally{setAiLoading(false)}}
  async function exportDetail(){if(!detail||!report)return;setDetailError('');const q=new URLSearchParams({kind:detail.kind,from_date:report.period.from,to_date:report.period.to});for(const key of ['invoice_status','appointment_status','order_status','part_category','service_category']){if(report.filters?.[key])q.set(key,report.filters[key])}if(detail.kind==='history'&&report.filters?.history_query)q.set('q',report.filters.history_query);if(detail.day)q.set('day',detail.day);if(detail.month)q.set('month',detail.month);if(detail.name)q.set('name',detail.name);if(detail.stock)q.set('stock',detail.stock);try{const r=await api(`/api/reports/export?${q}`);if(!r.ok)throw new Error((await readApiError(r)).message);const url=URL.createObjectURL(await r.blob());const link=document.createElement('a');link.href=url;link.download=`threeh-${detail.kind}-${report.period.from}-${report.period.to}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),60_000)}catch(e:any){setDetailError(e.message)}}
  const daily=report?.revenue_series||[];
  const series=granularity==='day'?daily:(report?.monthly_series||[]);
  const chartMax=Math.max(...series.map((item:any)=>Number(item.revenue)),1);
  const s=report?.summary||{};
  const comparison=report?.comparison;
  return <div className="page reports-page">
    <section className="page-heading"><div><p className="eyebrow">DỮ LIỆU VẬN HÀNH THỰC</p><h1>Tra cứu &amp; báo cáo</h1><p>Lịch sử sửa chữa, lịch hẹn, doanh thu, tồn kho và công nợ từ database.</p></div><div className="report-live"><Database size={16}/><span>Nguồn: SQLite</span><i/></div></section>
    <section className="card report-filters"><div className="report-presets">{[['today','Hôm nay'],['yesterday','Hôm qua'],['week','7 ngày'],['last30','30 ngày'],['month','Tháng này'],['previous_month','Tháng trước'],['quarter','Quý này'],['previous_quarter','Quý trước'],['year','Năm nay']].map(([key,label])=><button key={key} type="button" onClick={()=>preset(key)}>{label}</button>)}</div><label>Từ ngày<input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></label><label>Đến ngày<input type="date" value={to} onChange={e=>setTo(e.target.value)}/></label><label>Trạng thái lịch hẹn<select value={appointmentStatus} onChange={e=>setAppointmentStatus(e.target.value)}><option value="">Tất cả</option><option>Đang chờ</option><option>Đã xác nhận</option><option>Đã tiếp nhận</option><option>Đã hủy</option></select></label><details className="report-advanced"><summary>Bộ lọc nghiệp vụ</summary><div><label>Hóa đơn<select value={invoiceStatus} onChange={e=>setInvoiceStatus(e.target.value)}><option value="">Tất cả hợp lệ</option><option>Chưa thanh toán</option><option>Thanh toán một phần</option><option>Đã thanh toán</option></select></label><label>Phiếu đang xử lý<select value={orderStatus} onChange={e=>setOrderStatus(e.target.value)}><option value="">Tất cả</option>{['Tiếp nhận','Đang kiểm tra','Đã báo giá','Đã duyệt','Đang sửa','Chờ phụ tùng','Tạm dừng'].map(x=><option key={x}>{x}</option>)}</select></label><label>Nhóm phụ tùng<input value={partCategory} onChange={e=>setPartCategory(e.target.value)} placeholder="Tên nhóm trong kho"/></label><label>Nhóm dịch vụ<input value={serviceCategory} onChange={e=>setServiceCategory(e.target.value)} placeholder="Tên nhóm trong danh mục"/></label></div><small>Mỗi bộ lọc chỉ áp dụng cho nghiệp vụ tương ứng; công nợ và tồn kho là số dư hiện tại.</small></details><button className="btn primary" onClick={()=>void load()} disabled={loading}><Search size={16}/>{loading?'Đang tải':'Áp dụng'}</button><button className="btn secondary" onClick={()=>{setAppointmentStatus('');setInvoiceStatus('');setOrderStatus('');setPartCategory('');setServiceCategory('');setHistoryQuery('');setFrom(monthStart());setTo(today());void load(monthStart(),today(),true)}} disabled={loading}>Đặt lại</button></section>
    <p className="report-period">Kỳ đang xem: <strong>{report?`${dateText(report.period.from)} – ${dateText(report.period.to)}`:`${dateText(from)} – ${dateText(to)}`}</strong> · Asia/Ho_Chi_Minh. Công nợ/tồn kho là số dư hiện tại.</p>
    {error&&<div className="inline-error report-error"><CircleAlert size={16}/>{error}</div>}
    {loading&&!report?<div className="card report-loading"><i/><span>Đang tổng hợp trực tiếp từ database...</span></div>:report&&<>
       <section className="metrics report-metrics"><button className="report-kpi" onClick={()=>void openDetail('revenue','Hóa đơn hợp lệ trong kỳ')}><StatCard icon={CircleDollarSign} label="Doanh thu" value={money(s.revenue||0)} note={`${s.invoice_count||0} hóa đơn · nhấn xem nguồn`} color="blue"/></button><StatCard icon={Wrench} label="Tiền công" value={money(s.labor||0)} note="Dòng dịch vụ trước giảm giá, thuế" color="green"/><StatCard icon={Package} label="Phụ tùng" value={money(s.parts||0)} note="Dòng phụ tùng trước giảm giá, thuế" color="violet"/><button className="report-kpi" onClick={()=>void openDetail('debt','Hóa đơn còn nợ hiện tại')}><StatCard icon={Wallet} label="Công nợ" value={money(s.debt||0)} note={`${s.debt_invoices||0} hóa đơn · nhấn xem nguồn`} color="orange"/></button></section>
       <div className="report-secondary-kpis"><button onClick={()=>void openDetail('revenue','Hóa đơn hợp lệ trong kỳ')}><strong>{s.invoice_count||0}</strong><span>Hóa đơn hợp lệ</span></button><div><strong>{money(s.collected||0)}</strong><span>Thực thu theo ngày thanh toán trong kỳ</span></div><button onClick={()=>void openDetail('inventory','Mã phụ tùng dưới ngưỡng',{stock:'low'})}><strong>{s.inventory_counts?.low_stock||0}</strong><span>Mã tồn dưới ngưỡng · hết hàng {s.inventory_counts?.out_of_stock||0}</span></button><button onClick={()=>void openDetail('appointments','Lịch hẹn trong kỳ')}><strong>{Object.values(s.appointment_counts||{}).reduce((sum:number,n:any)=>sum+Number(n),0)}</strong><span>Lịch hẹn trong kỳ · xác nhận {s.appointment_counts?.['Đã xác nhận']||0}</span></button></div>
      <div className="report-tabs" role="tablist">{['Tổng hợp','Lịch sử sửa chữa','Phiếu đang xử lý','Lịch hẹn','Kho & công nợ'].map(name=><button key={name} className={tab===name?'active':''} onClick={()=>setTab(name)}>{name}</button>)}</div>
      {tab==='Tổng hợp'&&<div className="report-grid">
         <section className="card report-chart"><div className="card-title"><div><h2>Doanh thu theo {granularity==='day'?'ngày':'tháng'}</h2><p>{dateText(report.period.from)} — {dateText(report.period.to)} • Không gồm hóa đơn đã hủy</p></div><select value={granularity} onChange={e=>setGranularity(e.target.value as any)} aria-label="Đơn vị thời gian biểu đồ"><option value="day">Theo ngày</option><option value="month">Theo tháng</option></select></div>{series.length?<div className="report-bars">{series.map((item:any)=><button type="button" key={item.day} className="report-bar" title={`${item.day}: ${money(item.revenue)} · ${item.invoice_count} hóa đơn`} onClick={()=>void openDetail('revenue',`Hóa đơn ${granularity==='day'?'ngày':'tháng'} ${item.day}`,granularity==='day'?{day:item.day}:{month:item.day})}><span>{money(item.revenue)}</span><div><i style={{height:`${Math.max(3,item.revenue/chartMax*100)}%`}}/></div><b>{granularity==='day'?dateText(item.day).slice(0,5):item.day}</b></button>)}</div>:<ReportEmpty text="Không có hóa đơn hợp lệ trong khoảng đã chọn."/>}<div className="report-comparison"><strong>Kỳ này {money(s.revenue||0)}</strong><span>Kỳ trước {comparison?`${dateText(comparison.from)} – ${dateText(comparison.to)}: ${money(comparison.revenue)}`:'—'}</span><span>Chênh lệch {comparison?money(comparison.difference):'—'} · {comparison?.percent==null?'Không có cơ sở tính tỷ lệ (kỳ trước bằng 0)':`${comparison.percent}%`}</span></div></section>
         <section className="card report-breakdown"><div className="card-title"><div><h2>Cấu phần doanh thu</h2><p>Đối soát trước giảm giá, thuế và tổng hóa đơn</p></div></div><div className="breakdown-list"><div><span>Tiền công</span><strong>{money(s.labor||0)}</strong></div><div><span>Phụ tùng</span><strong>{money(s.parts||0)}</strong></div><div><span>Giảm giá</span><strong>- {money(s.discount||0)}</strong></div><div><span>Thuế</span><strong>+ {money(s.tax||0)}</strong></div><div className="total"><span>Doanh thu hóa đơn</span><strong>{money(s.revenue||0)}</strong></div></div><p className="report-math">Đối soát dòng trước giảm giá/thuế (backend): {money(s.reconciled_total||0)}. {s.reconciliation_difference?'Có chênh lệch; kiểm tra hóa đơn thiếu dòng hoặc dữ liệu cũ.':'Khớp tổng hóa đơn.'}</p></section>
         <Ranking title="Dịch vụ phổ biến" items={report.popular_services.slice(0,topCount)} onSelect={item=>void openDetail('service',`Dòng dịch vụ: ${item.name}`,{name:item.name})}/><Ranking title="Phụ tùng trên hóa đơn" items={report.popular_parts.slice(0,topCount)} onSelect={item=>void openDetail('part',`Dòng phụ tùng: ${item.name}`,{name:item.name})}/><div className="report-top-control"><label>Xem top <select value={topCount} onChange={e=>setTopCount(Number(e.target.value))}><option>5</option><option>10</option></select></label><small>Số lượng trên hóa đơn không phải số xe hay lượng xuất kho.</small></div>
        <section className="card report-rules"><div className="card-title"><div><h2>Quy tắc tính báo cáo</h2><p>Công thức được áp dụng thống nhất ở backend</p></div><ShieldCheck size={20}/></div><dl><div><dt>Kỳ ghi nhận</dt><dd>Ngày phát hành hóa đơn, múi giờ Việt Nam (UTC+7).</dd></div><div><dt>Doanh thu</dt><dd>Tổng tiền hóa đơn không bị hủy trong kỳ.</dd></div><div><dt>Hóa đơn hủy</dt><dd>Loại khỏi doanh thu, tiền công, phụ tùng và công nợ.</dd></div><div><dt>Công nợ</dt><dd>Tổng (tiền hóa đơn − đã thanh toán), chỉ lấy phần dương.</dd></div></dl></section>
      </div>}
       {tab==='Lịch sử sửa chữa'&&<section className="card orders-card"><div className="card-title"><div><h2>Lịch sử theo xe hoặc khách hàng</h2><p>Tối đa 100 dòng xem nhanh · <button className="report-link" onClick={()=>void openDetail('history','Lịch sử sửa chữa trong kỳ')}>Tra cứu đầy đủ, phân trang</button></p></div><div className="order-search"><Search size={16}/><input value={historyQuery} onChange={e=>setHistoryQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')void load()}} placeholder="Mã phiếu, biển số, tên hoặc số điện thoại..."/><button className="btn ghost" onClick={()=>void load()}>Tra cứu</button></div></div><ReportTable headers={['NGÀY / PHIẾU','KHÁCH HÀNG / XE','DỊCH VỤ','KM','TỔNG TIỀN']} rows={report.history.map((h:any)=><tr key={h.id}><td>{dateText(h.repaired_at)}<small>{h.order_code||'Lịch sử không liên kết phiếu'}</small></td><td><strong>{h.customer_name||'—'}</strong><small>{h.make} {h.model} • {h.plate}</small></td><td>{h.services}<small>{h.note||'—'}</small></td><td>{h.mileage?new Intl.NumberFormat('vi-VN').format(h.mileage):'—'}</td><td><strong>{money(h.total)}</strong></td></tr>)} empty="Chưa có lịch sử phù hợp."/></section>}
       {tab==='Phiếu đang xử lý'&&<section className="card orders-card"><div className="card-title"><div><h2>Phiếu đang xử lý</h2><p>{report.active_orders.length} phiếu xem nhanh · <button className="report-link" onClick={()=>void openDetail('orders','Phiếu đang xử lý')}>Xem danh sách phân trang</button></p></div></div><ReportTable headers={['MÃ PHIẾU','KHÁCH HÀNG / XE','NỘI DUNG','KỸ THUẬT VIÊN','TRẠNG THÁI','TẠM TÍNH']} rows={report.active_orders.map((o:any)=><tr key={o.id}><td><strong className="order-code">{o.code}</strong><small>{dateText(o.opened_at)}</small></td><td><strong>{o.customer_name||'—'}</strong><small>{o.plate}</small></td><td>{o.note||'—'}</td><td>{o.technician||'Chưa phân công'}</td><td><OrderStatus code={o.status_code}/></td><td><strong>{money(o.total)}</strong></td></tr>)} empty="Không có phiếu đang xử lý."/></section>}
       {tab==='Lịch hẹn'&&<section className="card orders-card"><div className="card-title"><div><h2>Lịch hẹn theo khoảng thời gian</h2><p>{report.appointments.length} lịch xem nhanh · <button className="report-link" onClick={()=>void openDetail('appointments','Lịch hẹn trong kỳ')}>Xem tất cả, phân trang</button> · ngưỡng tải cần cấu hình riêng</p></div></div><ReportTable headers={['THỜI GIAN','KHÁCH HÀNG / XE','DỊCH VỤ','KỸ THUẬT VIÊN','TRẠNG THÁI']} rows={report.appointments.map((a:any)=><tr key={a.id}><td><strong>{dateTimeText(a.appointment_at)}</strong><small>{a.duration_min} phút</small></td><td><strong>{a.customer_name}</strong><small>{a.plate}</small></td><td>{a.service}</td><td>{a.technician||'Chưa phân công'}</td><td><Status text={a.status}/></td></tr>)} empty="Không có lịch hẹn trong khoảng đã chọn."/></section>}
       {tab==='Kho & công nợ'&&<div className="report-stack"><p className="report-status-strip">Hóa đơn hiện tại: đã thu đủ <strong>{s.payment_status_counts?.['Đã thanh toán']||0}</strong> · thu một phần <strong>{s.payment_status_counts?.['Thanh toán một phần']||0}</strong> · chưa thu <strong>{s.payment_status_counts?.['Chưa thanh toán']||0}</strong>. Không gồm hóa đơn đã hủy.</p><section className="card orders-card"><div className="card-title"><div><h2>Tình trạng tồn kho</h2><p>{s.inventory_counts?.total||0} mã đang hoạt động · <button className="report-link" onClick={()=>void openDetail('inventory','Tồn kho hiện tại')}>Xem tất cả</button> · <button className="report-link" onClick={()=>void openDetail('inventory','Phụ tùng sắp hết',{stock:'low'})}>Dưới ngưỡng</button></p></div></div><ReportTable headers={['MÃ / PHỤ TÙNG','TỒN','NGƯỠNG','GIÁ TRỊ VỐN','TÌNH TRẠNG']} rows={report.inventory.map((p:any)=><tr key={p.id}><td><strong>{p.code}</strong><small>{p.name}</small></td><td>{p.stock} {p.unit}</td><td>{p.min_stock} {p.unit}</td><td><strong>{money(p.cost_value)}</strong></td><td><span className={`status ${p.status==='An toàn'?'green':p.status==='Hết hàng'?'gray':'orange'}`}><i/>{p.status}</span></td></tr>)} empty="Chưa có dữ liệu kho."/></section><section className="card orders-card"><div className="card-title"><div><h2>Công nợ chưa thanh toán</h2><p>{s.debt_invoices||0} hóa đơn · tổng còn phải thu {money(s.debt||0)} · <button className="report-link" onClick={()=>void openDetail('debt','Hóa đơn còn nợ')}>Xem tất cả</button></p></div></div><ReportTable headers={['HÓA ĐƠN','KHÁCH HÀNG / XE','TỔNG','ĐÃ THU','CÒN LẠI','TRẠNG THÁI']} rows={report.debts.map((d:any)=><tr key={d.id}><td><strong className="order-code">{d.code}</strong><small>{d.order_code}</small></td><td><strong>{d.customer_name||'—'}</strong><small>{d.plate}</small></td><td>{money(d.total)}</td><td>{money(d.paid_amount)}</td><td><strong className="debt-value">{money(d.remaining)}</strong></td><td><InvoiceStatus status={d.status}/></td></tr>)} empty="Không còn công nợ."/></section></div>}
       <section className="card report-ai"><div className="card-title"><div><h2>Giải thích số liệu báo cáo</h2><p>Chỉ dùng dữ liệu backend theo quyền; không thay đổi chứng từ.</p></div><Sparkles size={18}/></div><div className="report-ai-prompts">{['Doanh thu kỳ này so với kỳ trước?','Vì sao doanh thu và tiền thực thu khác nhau?','Dịch vụ nào phổ biến nhất?','Phụ tùng nào sắp hết?'].map(q=><button key={q} onClick={()=>setAiQuestion(q)}>{q}</button>)}</div><div className="report-ai-form"><input value={aiQuestion} onChange={e=>setAiQuestion(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')void askReport()}} placeholder="Hỏi về số liệu đang xem..." aria-label="Câu hỏi về báo cáo"/><button className="btn secondary" disabled={aiLoading||aiQuestion.trim().length<3} onClick={()=>void askReport()}>{aiLoading?'Đang đối chiếu':'Giải thích'}</button></div>{aiAnswer&&<p role="status" className="report-ai-answer">{aiAnswer.result}<small>{aiAnswer.sources?.map((x:any)=>x.label).join(' · ')||'Chưa có nguồn phù hợp'}</small></p>}</section>
     </>}
     {detail&&<div className="report-detail-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setDetail(null)}}><section className="card report-detail" role="dialog" aria-modal="true" aria-label={detail.title}><div className="card-title"><div><h2>{detail.title}</h2><p>{detail.kind==='debt'||detail.kind==='inventory'?'Số dư hiện tại':`${dateText(report?.period.from)} – ${dateText(report?.period.to)}`} · Quy tắc backend · trang {detailPage}/{detailData?.pages||1}</p></div><div className="report-detail-actions"><button className="btn secondary" onClick={()=>void exportDetail()}>Xuất CSV</button><button className="btn ghost" aria-label="Đóng chi tiết" onClick={()=>setDetail(null)}>Đóng</button></div></div>{detailError&&<p role="alert" className="inline-error">{detailError}</p>}{detailLoading?<div className="report-loading">Đang tải dữ liệu nguồn…</div>:detailData&&<><p><strong>{detailData.total} bản ghi</strong>{['revenue','debt','service','part'].includes(detail.kind)&&<> · Tổng giá trị {money(detailData.amount)}</>}</p>{detailData.items.length?<div className="report-detail-rows">{detailData.items.map((row:any)=><div key={row.id}><strong>{row.code||row.invoice_code||row.order_code||row.name||`#${row.id}`}</strong><span>{row.name||row.plate||row.service||row.status||'—'} · {row.issued_at?dateText(row.issued_at):row.repaired_at?dateText(row.repaired_at):row.appointment_at?dateText(row.appointment_at):row.opened_at?dateText(row.opened_at):''}</span>{row.remaining!=null?<b>Còn {money(row.remaining)}</b>:row.line_total!=null?<b>{row.quantity} × · {money(row.line_total)}</b>:row.total!=null&&detail.kind==='revenue'?<b>{money(row.total)}</b>:row.stock!=null?<b>{row.stock}/{row.min_stock} {row.unit}</b>:null}</div>)}</div>:<ReportEmpty text="Không có bản ghi phù hợp với bộ lọc."/>}<div className="report-detail-pagination"><button className="btn secondary" disabled={detailPage<=1} onClick={()=>setDetailPage(detailPage-1)}>Trước</button><span>Trang {detailPage}/{detailData.pages}</span><button className="btn secondary" disabled={detailPage>=detailData.pages} onClick={()=>setDetailPage(detailPage+1)}>Sau</button></div></>}</section></div>}
   </div>
}

function dateText(value:string){if(!value)return '—';const d=value.slice(0,10).split('-');return d.length===3?`${d[2]}/${d[1]}/${d[0]}`:value}
function dateTimeText(value:string){if(!value)return '—';return `${dateText(value)} ${value.slice(11,16)}`}
function ReportEmpty({text}:{text:string}){return <div className="empty-state compact"><Database size={26}/><strong>Không có dữ liệu</strong><p>{text}</p></div>}
function ReportTable({headers,rows,empty}:{headers:string[];rows:React.ReactNode[];empty:string}){return rows.length?<div className="table-wrap"><table className="report-table"><thead><tr>{headers.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows}</tbody></table></div>:<ReportEmpty text={empty}/>}
function Ranking({title,items,onSelect}:{title:string;items:any[];onSelect?:(item:any)=>void}){const max=Math.max(...items.map(i=>Number(i.quantity)),1);return <section className="card ranking-card"><div className="card-title"><div><h2>{title}</h2><p>Theo số lượng trên hóa đơn hợp lệ trong kỳ</p></div></div>{items.length?<div className="ranking-list">{items.map((item,index)=><button type="button" key={item.name} onClick={()=>onSelect?.(item)}><b>{index+1}</b><span><strong>{item.code?`${item.code} · `:''}{item.name}</strong><i><em style={{width:`${Number(item.quantity)/max*100}%`}}/></i></span><small>{Number(item.quantity).toLocaleString('vi-VN')} đơn vị · {item.invoice_count} hóa đơn</small></button>)}</div>:<ReportEmpty text="Chưa có hạng mục phát sinh trong kỳ."/>}</section>}

function SettingsPage({user}:{user:any}) {
  const [tab,setTab]=useState<'profile'|'notifications'|'security'>('profile');
  const [form,setForm]=useState({full_name:user.full_name||'',email:user.email||'',phone:'',language:'Tiếng Việt'});
  const [notifications,setNotifications]=useState({appointment:true,repair:true,promotion:false});
  const [password,setPassword]=useState({current_password:'',new_password:'',confirm:''});
  const [message,setMessage]=useState('');
  const [error,setError]=useState('');
  async function save(){setError('');try{const response=await api('/api/auth/settings',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({full_name:form.full_name,phone:form.phone,language:form.language,notify_appointment:notifications.appointment,notify_repair:notifications.repair,notify_promotion:notifications.promotion})});if(!response.ok){const info=await readApiError(response);throw new Error(info.message)}setMessage('Đã lưu thay đổi vào database.');setTimeout(()=>setMessage(''),3000)}catch(err:any){setError(err.message)} }
  async function changePassword(event:React.FormEvent){event.preventDefault();setError('');setMessage('');if(password.new_password!==password.confirm){setError('Mật khẩu xác nhận không khớp.');return}try{const response=await api('/api/auth/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_password:password.current_password,new_password:password.new_password})});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Không đổi được mật khẩu.');setPassword({current_password:'',new_password:'',confirm:''});setMessage(result.message)}catch(err:any){setError(err.message)} }
  useEffect(()=>{api('/api/auth/settings').then(async response=>{if(!response.ok)throw new Error();const saved=await response.json();setForm({full_name:saved.full_name,email:saved.email,phone:saved.phone||'',language:saved.language||'Tiếng Việt'});setNotifications({appointment:Boolean(saved.notify_appointment),repair:Boolean(saved.notify_repair),promotion:Boolean(saved.notify_promotion)})}).catch(()=>setError('Không tải được cài đặt tài khoản từ database.'))},[]);
  return <div className="page settings-page"><section className="page-heading"><div><p className="eyebrow">TÀI KHOẢN &amp; TÙY CHỌN</p><h1>Cài đặt</h1><p>Quản lý thông tin cá nhân, thông báo và tùy chọn sử dụng ThreeH Workshop.</p></div></section>
    {message&&<div className="inline-success"><CheckCircle2 size={15}/>{message}</div>}{error&&<div className="inline-error"><CircleAlert size={15}/>{error}</div>}
    <div className="settings-layout"><aside className="card settings-nav"><button className={tab==='profile'?'active':''} onClick={()=>setTab('profile')}><Users size={17}/>Thông tin cá nhân</button><button className={tab==='notifications'?'active':''} onClick={()=>setTab('notifications')}><Bell size={17}/>Thông báo</button><button className={tab==='security'?'active':''} onClick={()=>setTab('security')}><ShieldCheck size={17}/>Bảo mật tài khoản</button></aside><div className="settings-content">
      {tab==='profile'&&<><section className="card settings-card"><div className="settings-card-head"><div><h2>Thông tin cá nhân</h2><p>Thông tin hiển thị trên tài khoản của bạn.</p></div><div className="settings-avatar">{initialsOf(user.full_name)}</div></div><div className="settings-form"><label>Họ và tên<input value={form.full_name} onChange={e=>setForm({...form,full_name:e.target.value})}/></label><label>Email đăng nhập<input value={form.email} readOnly/></label><label>Số điện thoại<input placeholder="Chưa cập nhật" value={form.phone} onChange={e=>setForm({...form,phone:e.target.value})}/></label><label>Ngôn ngữ<select value={form.language} onChange={e=>setForm({...form,language:e.target.value})}><option>Tiếng Việt</option><option>English</option></select></label></div></section><div className="settings-actions"><button className="btn primary" onClick={save}><CheckCircle2 size={16}/>Lưu thay đổi</button></div></>}
      {tab==='notifications'&&<section className="card settings-card"><div><h2>Thông báo</h2><p>Chọn loại thông báo bạn muốn nhận từ garage.</p></div><div className="settings-options"><label><span><strong>Nhắc lịch hẹn</strong><small>Nhận thông báo trước khi đến lịch hẹn.</small></span><input type="checkbox" checked={notifications.appointment} onChange={e=>setNotifications({...notifications,appointment:e.target.checked})}/></label><label><span><strong>Cập nhật sửa chữa</strong><small>Thông báo khi trạng thái xe hoặc phiếu sửa chữa thay đổi.</small></span><input type="checkbox" checked={notifications.repair} onChange={e=>setNotifications({...notifications,repair:e.target.checked})}/></label><label><span><strong>Ưu đãi và tin garage</strong><small>Nhận thông tin khuyến mãi và chăm sóc xe.</small></span><input type="checkbox" checked={notifications.promotion} onChange={e=>setNotifications({...notifications,promotion:e.target.checked})}/></label></div><div className="settings-actions"><button className="btn primary" onClick={save}><CheckCircle2 size={16}/>Lưu thông báo</button></div></section>}
      {tab==='security'&&<section className="card settings-card"><div className="security-card"><div className="security-icon"><ShieldCheck size={21}/></div><div><h2>Đổi mật khẩu</h2><p>Dùng mật khẩu dài ít nhất 8 ký tự để bảo vệ tài khoản.</p><small>Vai trò hiện tại: <b>{user.role}</b></small></div></div><form className="security-form" onSubmit={changePassword}><label>Mật khẩu hiện tại<input required type="password" value={password.current_password} onChange={e=>setPassword({...password,current_password:e.target.value})}/></label><label>Mật khẩu mới<input required minLength={8} type="password" value={password.new_password} onChange={e=>setPassword({...password,new_password:e.target.value})}/></label><label>Xác nhận mật khẩu mới<input required minLength={8} type="password" value={password.confirm} onChange={e=>setPassword({...password,confirm:e.target.value})}/></label><div className="settings-actions"><button className="btn primary"><ShieldCheck size={16}/>Đổi mật khẩu</button></div></form></section>}
    </div></div>
  </div>
}

function InventoryPage({onOpenAI}:{onOpenAI:()=>void}) {
  const [parts,setParts]=useState<any[]>([]); const [meta,setMeta]=useState({total:0,pages:1,page:1});
  const [loading,setLoading]=useState(true); const [search,setSearch]=useState(''); const [filter,setFilter]=useState('');
  const [editing,setEditing]=useState<any>(null); const [stocking,setStocking]=useState<any>(null); const [fitting,setFitting]=useState<any>(null); const [error,setError]=useState('');
  async function load(nextPage=meta.page){
    setLoading(true); try { const query=new URLSearchParams({page:String(nextPage),page_size:'20'}); if(search.trim())query.set('q',search.trim()); if(filter==='Sắp hết')query.set('low_stock','true');
      const response=await api(`/api/parts?${query}`); if(!response.ok)throw new Error(); const data=await response.json(); setParts(data.items||[]); setMeta({total:data.total||0,pages:data.pages||1,page:data.page||nextPage}); setError('');
    } catch { setError('Không tải được kho phụ tùng.'); } finally { setLoading(false); }
  }
  useEffect(()=>{load(1)},[filter]);
  const low=parts.filter(p=>Number(p.stock)<=Number(p.min_stock));
  const inventoryValue=parts.reduce((s,p)=>s+Number(p.stock)*Number(p.sell_price),0);
  const saveAndClose=()=>{setEditing(null);setStocking(null);load(meta.page)};
  return <div className="page"><section className="page-heading"><div><p className="eyebrow">QUẢN LÝ TỒN KHO</p><h1>Kho phụ tùng</h1><p>Quản lý mã, giá bán, tồn kho và cảnh báo dưới ngưỡng an toàn.</p></div><div className="heading-actions"><button className="btn secondary" onClick={onOpenAI}><Sparkles size={17}/> Trợ lý AI</button><button className="btn primary" onClick={()=>setEditing({})}><Plus size={18}/> Thêm phụ tùng</button></div></section>
    <section className="metrics"><StatCard icon={Package} label="Mã phụ tùng" value={meta.total} note="Theo bộ lọc hiện tại" color="blue"/><StatCard icon={CircleAlert} label="Sắp hết hàng" value={low.length} note="Trang hiện tại" color="orange"/><StatCard icon={CheckCircle2} label="Còn hàng an toàn" value={parts.filter(p=>Number(p.stock)>Number(p.min_stock)).length} note="Trên ngưỡng tối thiểu" color="green"/><StatCard icon={CircleDollarSign} label="Giá trị tồn kho" value={money(inventoryValue)} note="Trang hiện tại theo giá bán" color="violet"/></section>
    <section className="card orders-card"><div className="card-title"><div><h2>Danh sách phụ tùng</h2><p>{meta.total} mã • Không cho phép tồn kho âm</p></div></div><div className="order-toolbar"><div className="filter-tabs"><button className={!filter?'active':''} onClick={()=>setFilter('')}>Tất cả</button><button className={filter==='Sắp hết'?'active':''} onClick={()=>setFilter('Sắp hết')}>Sắp hết</button></div><div className="order-search"><Search size={16}/><input value={search} onChange={e=>setSearch(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')load(1)}} placeholder="Tìm mã, tên, nhà cung cấp..."/><button className="btn ghost" onClick={()=>load(1)}>Tìm</button></div></div>{error&&<div className="inline-error"><CircleAlert size={15}/>{error}</div>}{loading?<div className="detail-loading"><i/><span>Đang tải kho...</span></div>:parts.length===0?<div className="empty-state"><Package size={30}/><strong>Không có phụ tùng phù hợp</strong><p>Thử thay đổi từ khóa hoặc bộ lọc.</p></div>:<div className="table-wrap"><table className="order-table"><thead><tr><th>MÃ / TÊN</th><th>NHÓM</th><th>GIÁ BÁN</th><th>TỒN KHO</th><th>NGƯỠNG</th><th>NHÀ CUNG CẤP</th><th/></tr></thead><tbody>{parts.map(part=><tr key={part.id}><td><strong className="order-code">{part.code}</strong><small>{part.name}</small></td><td>{part.category}</td><td><strong>{money(part.sell_price)}</strong><small>Giá nhập {money(part.cost_price)}</small></td><td><span className={`status ${Number(part.stock)<=Number(part.min_stock)?'orange':'green'}`}><i/>{part.stock} {part.unit}</span></td><td>{part.min_stock}</td><td>{part.supplier||'—'}</td><td><div className="row-actions"><button className="row-open" onClick={()=>setEditing(part)}><Pencil size={14}/> Sửa</button><button className="row-open" onClick={()=>setFitting(part)}><CarFront size={14}/> Cấu hình xe</button><button className="row-open" onClick={()=>setStocking(part)}><Plus size={14}/> Nhập</button></div></td></tr>)}</tbody></table></div>}<Pagination meta={meta} onPage={load}/></section>{editing!==null&&<PartModal part={editing.id?editing:undefined} onClose={()=>setEditing(null)} onSaved={saveAndClose}/>} {stocking&&<StockModal part={stocking} onClose={()=>setStocking(null)} onSaved={saveAndClose}/>}{fitting&&<PartFitmentsModal part={fitting} onClose={()=>setFitting(null)}/>}</div>;
}

function Pagination({meta,onPage}:{meta:{page:number;pages:number;total:number};onPage:(page:number)=>void}){if(meta.pages<=1)return null;return <div className="pagination"><button className="btn ghost" disabled={meta.page<=1} onClick={()=>onPage(meta.page-1)}>Trước</button><span>Trang {meta.page}/{meta.pages} • {meta.total} bản ghi</span><button className="btn ghost" disabled={meta.page>=meta.pages} onClick={()=>onPage(meta.page+1)}>Sau</button></div>}

function PartModal({part,onClose,onSaved}:{part?:any,onClose:()=>void,onSaved:()=>void}){const [form,setForm]=useState({code:part?.code||'',name:part?.name||'',category:part?.category||'Phụ tùng',compatible:part?.compatible||'',unit:part?.unit||'cái',stock:part?.stock??0,min_stock:part?.min_stock??3,sell_price:part?.sell_price??0,cost_price:part?.cost_price??0,supplier:part?.supplier||'',active:part?.active!==0});const [error,setError]=useState('');const [saving,setSaving]=useState(false);async function save(e:React.FormEvent){e.preventDefault();setSaving(true);setError('');try{const body=part?(({stock,...editable})=>({...editable,code:form.code.toUpperCase(),cost_price:Number(form.cost_price),sell_price:Number(form.sell_price),min_stock:Number(form.min_stock),active:Boolean(form.active)}))(form):{...form,code:form.code.toUpperCase(),stock:Number(form.stock),min_stock:Number(form.min_stock),sell_price:Number(form.sell_price),cost_price:Number(form.cost_price)};const r=await api(part?`/api/parts/${part.id}`:'/api/parts',{method:part?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok){const info=await readApiError(r);throw new Error(info.message)}onSaved()}catch(err:any){setError(err.message)}finally{setSaving(false)}}return <div className="modal-overlay" onMouseDown={onClose}><form className="modal" onMouseDown={e=>e.stopPropagation()} onSubmit={save}><div className="modal-head"><div><p className="eyebrow">{part?'CẬP NHẬT':'DANH MỤC PHỤ TÙNG'}</p><h2>{part?'Chỉnh sửa phụ tùng':'Thêm phụ tùng'}</h2></div><button type="button" onClick={onClose}><X/></button></div><div className="field-row"><label>Mã phụ tùng<input required value={form.code} onChange={e=>setForm({...form,code:e.target.value.toUpperCase()})}/></label><label>Tên phụ tùng<input required value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label></div><label>Nhóm phụ tùng<input value={form.category} onChange={e=>setForm({...form,category:e.target.value})}/></label><label>Xe tương thích<input value={form.compatible} onChange={e=>setForm({...form,compatible:e.target.value})}/></label><div className="field-row"><label>Giá nhập<input type="number" min="0" value={form.cost_price} onChange={e=>setForm({...form,cost_price:e.target.value as any})}/></label><label>Giá bán<input type="number" min="0" value={form.sell_price} onChange={e=>setForm({...form,sell_price:e.target.value as any})}/></label></div><div className="field-row"><label>{part?'Tồn kho hiện tại':'Số lượng nhập kho'}<input type="number" min="0" disabled={!!part} value={form.stock} onChange={e=>setForm({...form,stock:Number(e.target.value)})}/></label><label>Ngưỡng cảnh báo<input type="number" min="0" value={form.min_stock} onChange={e=>setForm({...form,min_stock:Number(e.target.value)})}/></label></div><label>Nhà cung cấp<input value={form.supplier} onChange={e=>setForm({...form,supplier:e.target.value})}/></label>{part&&<p className="work-hint">Tồn kho chỉ thay đổi qua giao dịch nhập/xuất/hoàn kho, không sửa trực tiếp.</p>}{error&&<div className="inline-error"><CircleAlert size={15}/>{error}</div>}<div className="modal-actions"><button type="button" className="btn secondary" onClick={onClose}>Hủy</button><button className="btn primary" disabled={saving}>{saving?'Đang lưu...':'Lưu phụ tùng'}</button></div></form></div>}

function StockModal({part,onClose,onSaved}:{part:any,onClose:()=>void,onSaved:()=>void}){const [amount,setAmount]=useState(1);const [saving,setSaving]=useState(false);const [error,setError]=useState('');async function save(e:React.FormEvent){e.preventDefault();setSaving(true);setError('');try{const key=`stock-in:${part.id}:${crypto.randomUUID()}`;const r=await api(`/api/parts/${part.id}/stock`,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify({amount:Number(amount)})});if(!r.ok){const info=await readApiError(r);throw new Error(info.message)}onSaved()}catch(err:any){setError(err.message)}finally{setSaving(false)}}return <div className="modal-overlay" onMouseDown={onClose}><form className="modal" onMouseDown={e=>e.stopPropagation()} onSubmit={save}><div className="modal-head"><div><p className="eyebrow">GIAO DỊCH NHẬP KHO</p><h2>Nhập thêm phụ tùng</h2></div><button type="button" onClick={onClose}><X/></button></div><div className="stock-modal-item"><Package size={22}/><div><strong>{part.name}</strong><small>{part.code} • Tồn hiện tại: {part.stock}</small></div></div><label>Số lượng nhập thêm<input type="number" min="1" required value={amount} onChange={e=>setAmount(Number(e.target.value))}/></label>{error&&<div className="inline-error"><CircleAlert size={15}/>{error}</div>}<div className="modal-actions"><button type="button" className="btn secondary" onClick={onClose}>Hủy</button><button className="btn primary" disabled={saving}>{saving?'Đang ghi nhận...':'Xác nhận nhập kho'}</button></div></form></div>}

function ServicesPage({onOpenAI}:{onOpenAI:()=>void}) {
  const [services,setServices]=useState<any[]>([]);const [meta,setMeta]=useState({total:0,pages:1,page:1});const [loading,setLoading]=useState(true);const [search,setSearch]=useState('');const [category,setCategory]=useState('');const [creating,setCreating]=useState(false);const [editing,setEditing]=useState<any>(null);const [error,setError]=useState('');
  async function load(nextPage=meta.page){setLoading(true);try{const query=new URLSearchParams({page:String(nextPage),page_size:'20'});if(search.trim())query.set('q',search.trim());if(category)query.set('category',category);const r=await api(`/api/services?${query}`);if(!r.ok)throw new Error();const data=await r.json();setServices(data.items||[]);setMeta({total:data.total||0,pages:data.pages||1,page:data.page||nextPage});setError('')}catch{setError('Không tải được danh mục dịch vụ.')}finally{setLoading(false)}}useEffect(()=>{load(1)},[category]);const active=services.filter(s=>s.active).length;const avg=services.length?services.reduce((a,s)=>a+Number(s.price),0)/services.length:0;const categories=['','Bảo dưỡng','Sửa chữa','Chăm sóc xe','Gầm - lốp','Kiểm tra'];
  return <div className="page"><section className="page-heading"><div><p className="eyebrow">DANH MỤC XƯỞNG</p><h1>Dịch vụ</h1><p>CRUD danh mục dịch vụ, giá bán và thời gian thực hiện.</p></div><div className="heading-actions"><button className="btn secondary" onClick={onOpenAI}><Sparkles size={17}/> Trợ lý AI</button><button className="btn primary" onClick={()=>setCreating(true)}><Plus size={18}/> Thêm dịch vụ</button></div></section><section className="metrics"><StatCard icon={Wrench} label="Tổng dịch vụ" value={meta.total} note="Theo bộ lọc hiện tại" color="blue"/><StatCard icon={CheckCircle2} label="Đang hoạt động" value={active} note="Có thể thêm vào phiếu" color="green"/><StatCard icon={Clock3} label="Thời gian TB" value={services.length?`${Math.round(services.reduce((a,s)=>a+Number(s.duration_min),0)/services.length)} phút`:'0 phút'} note="Trang hiện tại" color="orange"/><StatCard icon={CircleDollarSign} label="Giá TB" value={money(avg)} note="Trang hiện tại" color="violet"/></section><section className="card orders-card"><div className="card-title"><div><h2>Danh mục dịch vụ</h2><p>{meta.total} dịch vụ • bật/tắt thay vì xóa cứng</p></div></div><div className="order-toolbar"><div className="filter-tabs">{categories.map(c=><button key={c||'all'} className={category===c?'active':''} onClick={()=>setCategory(c)}>{c||'Tất cả'}</button>)}</div><div className="order-search"><Search size={16}/><input value={search} onChange={e=>setSearch(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')load(1)}} placeholder="Tìm tên hoặc nhóm dịch vụ..."/><button className="btn ghost" onClick={()=>load(1)}>Tìm</button></div></div>{error&&<div className="inline-error"><CircleAlert size={15}/>{error}</div>}{loading?<div className="detail-loading"><i/><span>Đang tải dịch vụ...</span></div>:<div className="service-grid">{services.map(s=><article className={`service-card ${!s.active?'inactive':''}`} key={s.id}><div className="service-card-top"><span className="service-icon"><Wrench size={17}/></span><span className="service-status">{s.active?'Đang hoạt động':'Đã tắt'}</span></div><h3>{s.name}</h3><p>{s.description||'Chưa có mô tả dịch vụ.'}</p><div className="service-card-meta"><span>{s.category}</span><span>{s.duration_min} phút</span><strong>{money(s.price)}</strong></div><div className="service-card-actions"><button className="btn ghost" onClick={()=>setEditing(s)}><Pencil size={14}/> Sửa</button><button className="btn secondary" onClick={async()=>{const r=await api(`/api/services/${s.id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({active:!s.active})});if(r.ok)load(meta.page)}}>{s.active?'Tắt':'Bật'}</button></div></article>)}</div>}<Pagination meta={meta} onPage={load}/></section>{(creating||editing)&&<ServiceModal service={editing||undefined} onClose={()=>{setCreating(false);setEditing(null)}} onSaved={()=>{setCreating(false);setEditing(null);load(meta.page)}}/>}</div>;
}

function ServiceModal({service,onClose,onSaved}:{service?:any,onClose:()=>void,onSaved:()=>void}){const [form,setForm]=useState({name:service?.name||'',category:service?.category||'Bảo dưỡng',description:service?.description||'',price:service?.price??'',duration_min:service?.duration_min||60,active:service?.active!==0});const [error,setError]=useState('');const [saving,setSaving]=useState(false);async function save(e:React.FormEvent){e.preventDefault();setSaving(true);setError('');try{const r=await api(service?`/api/services/${service.id}`:'/api/services',{method:service?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...form,price:Number(form.price),duration_min:Number(form.duration_min),active:Boolean(form.active)})});if(!r.ok){const info=await readApiError(r);throw new Error(info.message)}onSaved()}catch(err:any){setError(err.message)}finally{setSaving(false)}}return <div className="modal-overlay" onMouseDown={onClose}><form className="modal" onMouseDown={e=>e.stopPropagation()} onSubmit={save}><div className="modal-head"><div><p className="eyebrow">DANH MỤC XƯỞNG</p><h2>{service?'Chỉnh sửa dịch vụ':'Thêm dịch vụ'}</h2></div><button type="button" onClick={onClose}><X/></button></div><label>Tên dịch vụ<input required minLength={2} value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label><label>Nhóm dịch vụ<input required value={form.category} onChange={e=>setForm({...form,category:e.target.value})}/></label><label>Mô tả<textarea rows={3} value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/></label><div className="field-row"><label>Giá bán<input type="number" min="0" step="1000" value={form.price} onChange={e=>setForm({...form,price:e.target.value as any})}/></label><label>Thời gian (phút)<input type="number" min="5" value={form.duration_min} onChange={e=>setForm({...form,duration_min:Number(e.target.value)})}/></label></div>{service&&<label className="check-line"><input type="checkbox" checked={form.active} onChange={e=>setForm({...form,active:e.target.checked})}/> Đang hoạt động</label>}{error&&<div className="inline-error"><CircleAlert size={15}/>{error}</div>}<div className="modal-actions"><button type="button" className="btn secondary" onClick={onClose}>Hủy</button><button className="btn primary" disabled={saving}>{saving?'Đang lưu...':'Lưu dịch vụ'}</button></div></form></div>}

function InvoicesPage({onOpenAI}:{onOpenAI:()=>void}) {
  const [invoices,setInvoices]=useState<any[]>([]); const [loading,setLoading]=useState(true); const [status,setStatus]=useState('Tất cả'); const [search,setSearch]=useState(''); const [selected,setSelected]=useState<any>(null); const [creating,setCreating]=useState(false); const [error,setError]=useState('');
  async function load(){try{setLoading(true);const r=await api('/api/invoices?page_size=200');if(!r.ok)throw new Error();setInvoices(await readList(r));setError('')}catch{setError('Không tải được danh sách hóa đơn.')}finally{setLoading(false)}}useEffect(()=>{load()},[]);
  const visible=invoices.filter(i=>(status==='Tất cả'||i.status===status)&&`${i.id} ${i.code} ${i.order_code} ${i.plate} ${i.customer_name||''}`.toLowerCase().includes(search.toLowerCase()));const paid=invoices.filter(i=>i.status==='Đã thanh toán');const unpaid=invoices.filter(i=>i.status!=='Đã thanh toán'&&i.status!=='Đã hủy');const revenue=invoices.filter(i=>i.status!=='Đã hủy').reduce((s,i)=>s+Number(i.total||0),0);const count=(s:string)=>s==='Tất cả'?invoices.length:invoices.filter(i=>i.status===s).length;
  return <div className="page"><section className="page-heading"><div><p className="eyebrow">THU NGÂN &amp; THANH TOÁN</p><h1>Hóa đơn</h1><p>Hóa đơn lấy từ báo giá đã duyệt; tổng tiền và trạng thái do backend tính.</p></div><div className="heading-actions"><button className="btn secondary" onClick={onOpenAI}><Sparkles size={17}/> Trợ lý AI</button><button className="btn primary" onClick={()=>setCreating(true)}><Plus size={17}/> Lập hóa đơn</button></div></section><section className="metrics"><StatCard icon={FileText} label="Tổng hóa đơn" value={invoices.length} note="Hóa đơn trong hệ thống" color="blue"/><StatCard icon={CheckCircle2} label="Đã thanh toán" value={paid.length} note={money(paid.reduce((s,i)=>s+Number(i.total||0),0))} color="green"/><StatCard icon={Clock3} label="Còn phải thu" value={unpaid.length} note={money(unpaid.reduce((s,i)=>s+Number(i.remaining_amount??(Number(i.total||0)-Number(i.paid_amount||0))),0))} color="orange"/><StatCard icon={CircleDollarSign} label="Tổng giá trị" value={money(revenue)} note="Theo hóa đơn không bị hủy" color="violet"/></section><section className="card orders-card"><div className="card-title"><div><h2>Danh sách hóa đơn</h2><p>{visible.length} hóa đơn hiển thị • Mỗi hóa đơn liên kết một báo giá đã duyệt</p></div></div><div className="order-toolbar"><div className="filter-tabs">{['Tất cả','Chưa thanh toán','Thanh toán một phần','Đã thanh toán','Đã hủy'].map(s=><button key={s} className={status===s?'active':''} onClick={()=>setStatus(s)}>{s}<b>{count(s)}</b></button>)}</div><div className="order-search"><Search size={16}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Tìm mã hóa đơn, phiếu, biển số..."/></div></div>{error&&<div className="inline-error"><CircleAlert size={15}/>{error}</div>}{loading?<div className="detail-loading"><i/><span>Đang tải hóa đơn...</span></div>:visible.length===0?<div className="empty-state"><FileText size={30}/><strong>Không có hóa đơn phù hợp</strong><p>Hãy lập hóa đơn từ một báo giá đã duyệt.</p></div>:<div className="table-wrap"><table className="order-table"><thead><tr><th>MÃ HÓA ĐƠN</th><th>PHIẾU / BÁO GIÁ</th><th>KHÁCH HÀNG</th><th>TỔNG TIỀN</th><th>ĐÃ THU</th><th>CÒN LẠI</th><th>TRẠNG THÁI</th></tr></thead><tbody>{visible.map(i=><tr key={i.id} onClick={()=>setSelected(i)}><td><strong className="order-code">{i.code}</strong><small>{i.issued_at||'—'}</small></td><td><strong>{i.order_code}</strong><small>{i.quote_code||'Báo giá legacy'}</small></td><td><strong>{i.customer_name||'—'}</strong><small>{i.plate}</small></td><td><strong>{money(i.total)}</strong><small>VAT {money(i.tax)}</small></td><td>{money(i.paid_amount)}</td><td><strong>{money(i.remaining_amount??(Number(i.total||0)-Number(i.paid_amount||0)))}</strong></td><td><InvoiceStatus status={i.status}/></td></tr>)}</tbody></table></div>}</section>{selected&&<InvoiceDrawer invoice={selected} onClose={()=>setSelected(null)} onUpdate={()=>{setSelected(null);load()}}/>}{creating&&<NewInvoiceModal onClose={()=>setCreating(false)} onCreated={()=>{setCreating(false);load()}}/>}</div>;
}

function InvoiceStatus({status}:{status:string}){const kind=status==='Đã thanh toán'?'green':status==='Chưa thanh toán'?'orange':status==='Đã hủy'?'gray':'blue';return <span className={`status ${kind}`}><i/>{status}</span>}

function NewInvoiceModal({onClose,onCreated}:{onClose:()=>void;onCreated:()=>void}){const [candidates,setCandidates]=useState<any[]>([]);const [selected,setSelected]=useState('');const [note,setNote]=useState('');const [error,setError]=useState('');const [saving,setSaving]=useState(false);useEffect(()=>{api('/api/invoices/candidates').then(async r=>{if(!r.ok)throw new Error();setCandidates(await r.json())}).catch(()=>setError('Không tải được các báo giá đã duyệt.'))},[]);async function save(e:React.FormEvent){e.preventDefault();if(!selected)return;setSaving(true);setError('');try{const r=await api('/api/invoices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repair_order_id:Number(candidates.find(c=>String(c.quote_id)===selected)?.repair_order_id),quote_id:Number(selected),note})});if(!r.ok){const info=await readApiError(r);throw new Error(info.message)}onCreated()}catch(err:any){setError(err.message)}finally{setSaving(false)}}return <div className="modal-overlay" onMouseDown={onClose}><form className="modal" onMouseDown={e=>e.stopPropagation()} onSubmit={save}><div className="modal-head"><div><p className="eyebrow">HÓA ĐƠN TỪ BÁO GIÁ</p><h2>Lập hóa đơn</h2></div><button type="button" onClick={onClose}><X/></button></div><label>Báo giá đã duyệt<select required value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Chọn báo giá</option>{candidates.map(c=><option key={c.quote_id} value={c.quote_id}>{c.quote_code} • {c.order_code} • {c.customer_name||'Khách lẻ'} • {money(c.total)}</option>)}</select></label><label>Ghi chú<textarea rows={2} value={note} onChange={e=>setNote(e.target.value)}/></label><p className="work-hint">Tổng tiền, chiết khấu, thuế và chi tiết hạng mục được sao chép từ báo giá đã duyệt; không nhận giá từ giao diện.</p>{error&&<div className="inline-error"><CircleAlert size={15}/>{error}</div>}<div className="modal-actions"><button type="button" className="btn secondary" onClick={onClose}>Hủy</button><button className="btn primary" disabled={saving||!selected}>{saving?'Đang lập...':'Lập hóa đơn'}</button></div></form></div>}

function InvoiceDrawer({invoice,onClose,onUpdate}:{invoice:any;onClose:()=>void;onUpdate:()=>void}){
  const [detail,setDetail]=useState<any>(invoice);
  useEffect(()=>{api(`/api/invoices/${invoice.id}`).then(response=>response.ok?response.json():invoice).then(setDetail).catch(()=>setDetail(invoice))},[invoice.id]);
  async function refresh(){const response=await api(`/api/invoices/${invoice.id}`);if(response.ok)setDetail(await response.json());onUpdate()}
  async function request(path:string,options:RequestInit={}){const response=await api(`/api${path}`,options);const body=await response.json();if(!response.ok)throw new Error(body?.error?.message||body?.detail||'Không ghi nhận được khoản thu.');return body}
  return <PaymentRecordDialog invoice={detail} request={request} onClose={onClose} onChanged={refresh}/>;
}

function PlaceholderPage({title}:{title:string}) {
  return <div className="page">
    <section className="page-heading"><div><p className="eyebrow">ĐANG PHÁT TRIỂN</p><h1>{title}</h1><p>Chức năng này đang được hoàn thiện và sẽ sớm ra mắt.</p></div></section>
    <section className="card orders-card"><div className="empty-state"><Wrench size={30}/><strong>{title} đang được xây dựng</strong><p>Vui lòng quay lại sau hoặc liên hệ quản trị viên để được hỗ trợ.</p></div></section>
  </div>;
}

// Role-based dashboard: mỗi vai trò có màn hình tổng quan riêng.
function RoleDashboard({user,data,onOpenAI,onNewAppointment,onOpenAppointment}:{user:any,data:Data,onOpenAI:()=>void,onNewAppointment:()=>void,onOpenAppointment:(a:any)=>void}) {
  const name = user.full_name.split(' ').slice(-1)[0];
  const appointments = data.appointments || [];
  const orders = data.repair_orders || [];
  const waiting = appointments.filter(a => a.status === 'Đang chờ').length;
  const confirmed = appointments.filter(a => a.status === 'Đã xác nhận').length;
  const inProgress = orders.filter(o => ['INSPECTING','QUOTED','APPROVED','IN_PROGRESS'].includes(statusCodeOf(o))).length;
  const waitingParts = orders.filter(o => statusCodeOf(o) === 'WAITING_FOR_PARTS').length;
  const done = orders.filter(o => ['COMPLETED','DELIVERED'].includes(statusCodeOf(o))).length;
  const aiBanner = <div className="ai-banner"><div className="ai-orb"><Sparkles/></div><div><span className="ai-tag">THREEH WORKSHOP</span><h2>Trợ lý AI đồng hành cùng bạn</h2><p>Tóm tắt lịch sử xe và gợi ý nội dung tư vấn chỉ trong vài giây.</p></div><button onClick={onOpenAI}>Thử ngay <ArrowUpRight size={16}/></button></div>;

  if (user.role === 'Lễ tân') return <div className="page">
    <section className="page-heading"><div><p className="eyebrow">BÀN TIẾP NHẬN</p><h1>Tổng quan lễ tân</h1><p>Chào {name}, đây là lịch hẹn khách hàng cần bạn xử lý hôm nay.</p></div><div className="heading-actions"><button className="btn secondary" onClick={onOpenAI}><Sparkles size={17}/> Trợ lý AI</button><button className="btn primary" onClick={onNewAppointment}><Plus size={18}/> Tạo lịch hẹn</button></div></section>
    <section className="metrics">
      <Metric icon={CalendarDays} label="Lịch hẹn" value={appointments.length} note="Tổng lịch trong hệ thống" color="blue"/>
      <Metric icon={Clock3} label="Đang chờ xác nhận" value={waiting} note={waiting ? 'Gọi xác nhận với khách' : 'Đã xác nhận tất cả'} color="orange"/>
      <Metric icon={CheckCircle2} label="Đã xác nhận" value={confirmed} note="Sẵn sàng tiếp nhận xe" color="green"/>
    </section>
    <section className="card orders-card">
      <div className="card-title"><div><h2>Lịch hẹn cần xử lý</h2><p>{appointments.length} lịch hẹn • bấm vào dòng để xem chi tiết</p></div></div>
      {appointments.length === 0 ? <div className="empty-state"><CalendarDays size={30}/><strong>Chưa có lịch hẹn</strong><p>Tạo lịch hẹn mới cho khách hàng đến garage.</p></div>
      : <div className="table-wrap"><table className="order-table"><thead><tr><th>GIỜ HẸN</th><th>KHÁCH HÀNG</th><th>DỊCH VỤ</th><th>BIỂN SỐ</th><th>TRẠNG THÁI</th></tr></thead><tbody>{appointments.map(a => <tr key={a.id} onClick={() => onOpenAppointment(a)}><td><div className="appt-time"><strong>{a.appointment_at.slice(11,16)}</strong><small>{a.appointment_at.slice(0,10)}</small></div></td><td>{a.customer_name}</td><td><span className="note-cell">{a.service}</span></td><td>{a.plate}</td><td><Status text={a.status}/></td></tr>)}</tbody></table></div>}
    </section>
    <section className="bottom-grid">{aiBanner}</section>
  </div>;

  if (user.role === 'Kỹ thuật viên') return <div className="page">
    <section className="page-heading"><div><p className="eyebrow">XƯỞNG DỊCH VỤ</p><h1>Tổng quan kỹ thuật</h1><p>Chào {name}, đây là các xe đang trong xưởng và phụ tùng cần lưu ý.</p></div><div className="heading-actions"><button className="btn secondary" onClick={onOpenAI}><Sparkles size={17}/> Trợ lý AI</button></div></section>
    <section className="metrics">
      <Metric icon={Wrench} label="Xe đang sửa" value={inProgress} note="Cần theo dõi tiến độ" color="orange"/>
      <Metric icon={Package} label="Chờ phụ tùng" value={waitingParts} note={waitingParts ? 'Cần bổ sung vật tư' : 'Đủ phụ tùng'} color="blue"/>
      <Metric icon={CheckCircle2} label="Đã hoàn thành" value={done} note="Sẵn sàng bàn giao" color="green"/>
    </section>
    <section className="card orders-card">
      <div className="card-title"><div><h2>Phiếu trong xưởng</h2><p>{orders.length} phiếu sửa chữa đang xử lý</p></div></div>
      <div className="table-wrap"><table className="order-table"><thead><tr><th>MÃ PHIẾU</th><th>BIỂN SỐ</th><th>NỘI DUNG</th><th>TRẠNG THÁI</th></tr></thead><tbody>{orders.map(o => <tr key={o.id}><td><strong className="order-code">{o.code}</strong></td><td>{o.plate}</td><td><span className="note-cell">{o.note}</span></td><td><OrderStatus code={statusCodeOf(o)}/></td></tr>)}</tbody></table></div>
    </section>
    <section className="bottom-grid">{aiBanner}</section>
  </div>;

  if (user.role === 'Thu ngân') return <div className="page">
    <section className="page-heading"><div><p className="eyebrow">QUẦY THU NGÂN</p><h1>Tổng quan thu ngân</h1><p>Chào {name}, đây là doanh thu và các phiếu cần xuất hóa đơn.</p></div><div className="heading-actions"><button className="btn secondary" onClick={onOpenAI}><Sparkles size={17}/> Trợ lý AI</button></div></section>
    <section className="metrics">
      <Metric icon={CircleDollarSign} label="Doanh thu hôm nay" value={money(data.metrics.revenue)} note={`↗ ${data.metrics.growth}% so với hôm qua`} color="violet" wide/>
      <Metric icon={CheckCircle2} label="Xe đã hoàn thành" value={data.metrics.completed} note="Cần xuất hóa đơn" color="green"/>
      <Metric icon={FileText} label="Phiếu chờ thu" value={orders.length} note="Theo dõi thanh toán" color="blue"/>
    </section>
    <section className="dashboard-grid">
      <div className="card revenue-card">
        <div className="card-title"><div><h2>Doanh thu 7 ngày</h2><p>Dữ liệu hóa đơn không bị hủy</p></div></div>
        <div className="revenue-head"><div><strong>{money(data.revenue.reduce((sum,value)=>sum+Number(value||0),0))}</strong></div><em>{data.revenue.some(Boolean)?'Dữ liệu API':'Chưa có dữ liệu'}</em></div>
        <div className="mini-bars">{data.revenue.map((value,index)=>{const max=Math.max(...data.revenue.map(Number),1);return <div key={index}><i style={{height:`${Math.max(2,Number(value)/max*100)}%`}} title={money(Number(value))}/><span>{['T2','T3','T4','T5','T6','T7','CN'][index]}</span></div>})}</div>
      </div>
      <div className="card orders-card"><div className="card-title"><div><h2>Phiếu cần xuất hóa đơn</h2><p>Dựa trên phiếu sửa chữa gần đây</p></div></div><div className="table-wrap"><table className="order-table"><thead><tr><th>MÃ PHIẾU</th><th>BIỂN SỐ</th><th>TẠM TÍNH</th></tr></thead><tbody>{orders.map(o => <tr key={o.id}><td><strong className="order-code">{o.code}</strong></td><td>{o.plate}</td><td><strong className="spend-value">{money(Number(o.total || 0))}</strong></td></tr>)}</tbody></table></div></div>
    </section>
    <section className="bottom-grid">{aiBanner}</section>
  </div>;

  // Khách hàng: cổng thông tin cá nhân, chỉ xem thông tin của mình.
  return <div className="page">
    <section className="page-heading"><div><p className="eyebrow">CỔNG THÔNG TIN KHÁCH HÀNG</p><h1>Xin chào, {user.full_name}</h1><p>Đây là lịch hẹn và tình trạng xe của bạn tại garage.</p></div><div className="heading-actions"><button className="btn secondary" onClick={onOpenAI}><Sparkles size={17}/> Trợ lý AI</button></div></section>
    <section className="metrics">
      <Metric icon={CalendarDays} label="Lịch hẹn sắp tới" value={appointments.length} note="Sắp tới tại garage" color="blue"/>
      <Metric icon={CarFront} label="Xe đang quản lý" value={orders.length} note="Hồ sơ xe của bạn" color="orange"/>
      <Metric icon={CheckCircle2} label="Hoàn thành" value={done} note="Dịch vụ đã xong" color="green"/>
    </section>
    <section className="orders-card card">
      <div className="card-title"><div><h2>Lịch hẹn của bạn</h2><p>Theo dõi các lần đưa xe đến garage</p></div></div>
      {appointments.length === 0 ? <div className="empty-state"><CalendarDays size={30}/><strong>Chưa có lịch hẹn</strong><p>Liên hệ garage để đặt lịch bảo dưỡng cho xe của bạn.</p></div>
      : <div className="table-wrap"><table className="order-table"><thead><tr><th>THỜI GIAN</th><th>DỊCH VỤ</th><th>BIỂN SỐ</th><th>TRẠNG THÁI</th></tr></thead><tbody>{appointments.map(a => <tr key={a.id}><td>{a.appointment_at.slice(0,10)} • {a.appointment_at.slice(11,16)}</td><td><span className="note-cell">{a.service}</span></td><td>{a.plate}</td><td><Status text={a.status}/></td></tr>)}</tbody></table></div>}
    </section>
    <section className="bottom-grid">{aiBanner}</section>
  </div>;
}

const APPOINTMENT_STATUSES = ['Đang chờ', 'Đã xác nhận', 'Đã tiếp nhận', 'Đã hủy'];

// Nhãn trạng thái lịch hẹn.
function AppointmentStatusBadge({text}:{text:string}) {
  const kind = text === 'Đã xác nhận' ? 'green' : text === 'Đang chờ' ? 'orange' : text === 'Đã tiếp nhận' ? 'blue' : 'gray';
  return <span className={`status ${kind}`}><i/>{text}</span>
}

function formatAppointment(value:string) {
  const raw = (value || '').replace(' ', 'T');
  const [datePart, timePart] = raw.split('T');
  const [year, month, day] = datePart.split('-');
  return { time: (timePart || '').slice(0, 5) || '--:--', date: `${day}/${month}/${year}`, isoDate: datePart };
}

function AppointmentsPage({onOpenAI,onLoaded,receptionMode=false}:{onOpenAI:()=>void,onLoaded?:(count:number)=>void;receptionMode?:boolean}) {
  const [appointments,setAppointments]=useState<any[]>([]);
  const [loading,setLoading]=useState(true);
  const [filter,setFilter]=useState('Tất cả');
  const [search,setSearch]=useState('');
  const [date,setDate]=useState('');
  const [selected,setSelected]=useState<any>(null);
  const [detailMode,setDetailMode]=useState('');
  const [creating,setCreating]=useState(false);
  const [error,setError]=useState('');
  const sessionUser=sessionUserCache;
  const canProcessAppointments=['Admin','Quản lý','Lễ tân'].includes(sessionUser?.role);

  async function load(){
    try{
      const response=await api(`/api/appointments`);
      if(!response.ok) throw new Error();
      const data=await readList(response);
      setAppointments(data); setError(''); onLoaded?.(data.length);
    }catch{ setError('Không tải được danh sách lịch hẹn. Vui lòng kiểm tra backend.') }
    finally{ setLoading(false) }
  }
  useEffect(()=>{ load(); },[]);

  const keyword = search.trim().toLowerCase();
  const visible = appointments.filter(item => {
    const info = formatAppointment(item.appointment_at);
    return (!receptionMode || ['Đang chờ','Đã xác nhận'].includes(item.status))
      && (filter === 'Tất cả' || item.status === filter)
      && (!date || info.isoDate === date)
      && `${item.customer_name} ${item.plate} ${item.service} ${item.phone || ''}`.toLowerCase().includes(keyword);
  });
  const countOf = (status:string) => appointments.filter(item => item.status === status).length;
  const todayIso = new Date().toISOString().slice(0,10);
  const todayCount = appointments.filter(item => formatAppointment(item.appointment_at).isoDate === todayIso).length;

  async function openDetail(appointment:any, mode=''){
    setDetailMode(mode);
    setSelected({ ...appointment, loading: true });
    try{
      const response=await api(`/api/appointments/${appointment.id}`);
      setSelected(response.ok ? await response.json() : appointment);
    }catch{ setSelected(appointment) }
  }

  async function confirmQuick(appointment:any){
    try{
      const response=await api(`/api/appointments/${appointment.id}/confirm`,{method:'POST'});
      if(response.ok){
        const fresh=await response.json();
        setAppointments(current => current.map(item => item.id===appointment.id?{...item,status:fresh.status}:item));
        setError('');
        return;
      }
      const info=await readApiError(response);
      setError(info.message);
      await openDetail(appointment);
    }catch{ setError('Không xác nhận được lịch hẹn.') }
  }

  return <div className="page">
    <section className="page-heading">
      <div><p className="eyebrow">ĐIỀU PHỐI TIẾP NHẬN</p><h1>{receptionMode?'Tiếp nhận xe':'Lịch hẹn'}</h1><p>{receptionMode?'Xác nhận thông tin, số km và chuyển lịch hẹn thành phiếu sửa chữa.':'Quản lý lịch hẹn của khách, xác nhận và tiếp nhận xe vào xưởng.'}</p></div>
      <div className="heading-actions">
        <button className="btn secondary" onClick={onOpenAI}><Sparkles size={17}/> Trợ lý AI</button>
        {!receptionMode&&<button className="btn primary" onClick={()=>setCreating(true)}><Plus size={18}/> Tạo lịch hẹn</button>}
      </div>
    </section>

    <section className="metrics">
      <StatCard icon={CalendarDays} label="Tổng lịch hẹn" value={appointments.length} note={`${todayCount} lịch trong hôm nay`} color="blue"/>
      <StatCard icon={Clock3} label="Đang chờ xác nhận" value={countOf('Đang chờ')} note={countOf('Đang chờ') ? 'Cần gọi xác nhận với khách' : 'Đã xác nhận tất cả'} color="orange"/>
      <StatCard icon={CheckCircle2} label="Đã xác nhận" value={countOf('Đã xác nhận')} note="Sẵn sàng tiếp nhận xe" color="green"/>
      <StatCard icon={CarFront} label="Đã tiếp nhận" value={countOf('Đã tiếp nhận')} note="Xe đã vào xưởng" color="violet"/>
    </section>

    <section className="card orders-card">
      <div className="card-title">
        <div><h2>Danh sách lịch hẹn</h2><p>{visible.length} lịch hẹn hiển thị • {countOf('Đã hủy')} lịch đã hủy</p></div>
      </div>
      <div className="order-toolbar">
        <div className="filter-tabs">
          {['Tất cả', ...APPOINTMENT_STATUSES].map(status =>
            <button key={status} className={filter === status ? 'active' : ''} onClick={()=>setFilter(status)}>
              {status}{status !== 'Tất cả' && <b>{countOf(status)}</b>}
            </button>
          )}
        </div>
        <div className="appointment-filters">
          <label className="date-filter"><CalendarDays size={15}/><input type="date" value={date} onChange={e=>setDate(e.target.value)} aria-label="Lọc theo ngày hẹn"/></label>
          {date && <button className="clear-date" onClick={()=>setDate('')}>Bỏ lọc ngày</button>}
          <div className="order-search"><Search size={16}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Tìm khách hàng, biển số, dịch vụ..."/></div>
        </div>
      </div>

      {error && <div className="inline-error"><CircleAlert size={15}/>{error}</div>}
      {loading ? <div className="detail-loading"><i/><span>Đang tải lịch hẹn...</span></div>
      : visible.length === 0 ? <div className="empty-state"><CalendarDays size={30}/><strong>Không có lịch hẹn phù hợp</strong><p>Thử bỏ bộ lọc hoặc tạo lịch hẹn mới cho khách hàng.</p></div>
      : <div className="table-wrap"><table className="order-table">
        <thead><tr><th>GIỜ HẸN</th><th>KHÁCH HÀNG</th><th>XE / BIỂN SỐ</th><th>DỊCH VỤ YÊU CẦU</th><th>PHÂN CÔNG</th><th>TRẠNG THÁI</th><th>THAO TÁC</th></tr></thead>
        <tbody>{visible.map(item => {
          const info = formatAppointment(item.appointment_at);
          return <tr key={item.id} onClick={()=>openDetail(item)}>
            <td><div className="appt-time"><strong>{info.time}</strong><small>{info.date}</small></div></td>
            <td><div className="appt-customer"><span>{(item.customer_name || '—').split(' ').slice(-2).map((x:string)=>x[0]).join('')}</span><div><strong>{item.customer_name}</strong><small>{item.phone || 'Chưa có số điện thoại'}</small></div></div></td>
            <td><div className="vehicle-cell"><div className="mini-car"><CarFront size={19}/></div><div><strong>{item.make ? `${item.make} ${item.model}` : 'Chưa rõ dòng xe'}</strong><small>{item.plate}</small></div></div></td>
            <td><span className="note-cell">{item.service}</span></td>
            <td><div className="appt-assign"><strong>{item.technician || 'Chưa phân công'}</strong><small>{item.resource_name || 'Chưa xếp nguồn lực'}</small></div></td>
            <td><AppointmentStatusBadge text={item.status}/></td>
            <td><div className="row-actions">
              {canProcessAppointments && item.status === 'Đang chờ' && <button className="row-quick" onClick={e=>{e.stopPropagation(); confirmQuick(item)}}><CheckCircle2 size={14}/> Xác nhận</button>}
              {canProcessAppointments && (item.status === 'Đang chờ' || item.status === 'Đã xác nhận') && <button className="row-quick receive" onClick={e=>{e.stopPropagation(); openDetail(item,'receive')}}><CarFront size={14}/> Tiếp nhận</button>}
              <button className="row-open" onClick={e=>{e.stopPropagation(); openDetail(item)}}>Mở <ArrowUpRight size={14}/></button>
            </div></td>
          </tr>
        })}</tbody>
      </table></div>}
    </section>

    {selected && <AppointmentDetail appointment={selected} initialMode={detailMode} onClose={()=>setSelected(null)} onStatusChange={(id,status)=>setAppointments(current=>current.map(item=>item.id===id?{...item,status}:item))} onChanged={load}/>}
    {creating && <AppointmentCreateModal currentUser={sessionUser} apiBase={API} onClose={()=>setCreating(false)} onCreated={()=>{ setCreating(false); load(); }}/>} 
  </div>
}

function initialsOf(name?:string):string {
  return (name || '')
    .trim()
    .split(/\s+/)
    .slice(-2)
    .map(part => part[0] || '')
    .join('')
    .toUpperCase() || 'KH';
}

function CustomersPage({onOpenAI,onLoaded}:{onOpenAI:()=>void;onLoaded?:(count:number)=>void}) {
  const [customers,setCustomers]=useState<any[]>([]);
  const [query,setQuery]=useState('');
  const [vehicleFilter,setVehicleFilter]=useState<'all'|'with'|'without'>('all');
  const [currentPage,setCurrentPage]=useState(1);
  const [pageSize,setPageSize]=useState(20);
  const [total,setTotal]=useState(0);
  const [pages,setPages]=useState(0);
  const [summary,setSummary]=useState({customers:0,vehicles:0,appointments:0,lifetime_value:0,with_vehicles:0});
  const requestId=useRef(0);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [selectedId,setSelectedId]=useState<number|null>(null);
  const [creating,setCreating]=useState(false);

  async function load(){
    const id=++requestId.current;
    setLoading(true);
    try{
      const [response,summaryResponse]=await Promise.all([
        api(`/api/customers?page=${currentPage}&page_size=${pageSize}&vehicle_filter=${vehicleFilter}&q=${encodeURIComponent(query.trim())}`),
        api('/api/customers/summary')
      ]);
      if(!response.ok || !summaryResponse.ok) throw new Error();
      const [list,totals]=await Promise.all([response.json(),summaryResponse.json()]);
      if(id!==requestId.current)return;
      setCustomers(list.items);
      setTotal(list.total);
      setPages(list.pages);
      setSummary(totals);
      onLoaded?.(totals.customers);
      setError('');
    }catch{ if(id===requestId.current)setError('Không tải được danh sách khách hàng.') }
    finally{ if(id===requestId.current)setLoading(false) }
  }
  useEffect(()=>{ const timer=window.setTimeout(()=>{load()},query?250:0);return ()=>{window.clearTimeout(timer);requestId.current++} },[query,vehicleFilter,currentPage,pageSize]);

  const visible=customers;

  return <div className="page customers-page">
    <section className="page-heading">
      <div><p className="eyebrow">HỒ SƠ KHÁCH HÀNG</p><h1>Khách hàng</h1><p>Quản lý hồ sơ, xe sở hữu và lịch sử chăm sóc khách hàng.</p></div>
      <div className="heading-actions"><button className="btn secondary" onClick={onOpenAI}><Sparkles size={17}/> Trợ lý AI</button><button className="btn primary" onClick={()=>setCreating(true)}><UserPlus size={18}/> Thêm khách hàng</button></div>
    </section>
    <section className="metrics">
      <StatCard icon={Users} label="Khách hàng" value={summary.customers} note={`${total} hồ sơ theo bộ lọc`} color="blue"/>
      <StatCard icon={CarFront} label="Xe đang quản lý" value={summary.vehicles} note="Tổng số phương tiện" color="orange"/>
      <StatCard icon={CalendarDays} label="Lịch hẹn" value={summary.appointments} note="Lịch hẹn đã ghi nhận" color="violet"/>
      <StatCard icon={CircleDollarSign} label="Giá trị trọn đời" value={money(summary.lifetime_value)} note="Tổng chi tiêu đã ghi nhận" color="green"/>
    </section>
    <section className="card orders-card">
      <div className="card-title"><div><h2>Danh sách khách hàng</h2><p>Bấm vào dòng để xem hồ sơ, xe và lịch sử sửa chữa</p></div></div>
      <div className="order-toolbar">
        <div className="filter-tabs" aria-label="Lọc khách hàng theo phương tiện"><button className={vehicleFilter==='all'?'active':''} aria-pressed={vehicleFilter==='all'} onClick={()=>{setVehicleFilter('all');setCurrentPage(1)}}>Tất cả<b>{summary.customers}</b></button><button className={vehicleFilter==='with'?'active':''} aria-pressed={vehicleFilter==='with'} onClick={()=>{setVehicleFilter('with');setCurrentPage(1)}}>Có xe<b>{summary.with_vehicles}</b></button><button className={vehicleFilter==='without'?'active':''} aria-pressed={vehicleFilter==='without'} onClick={()=>{setVehicleFilter('without');setCurrentPage(1)}}>Chưa có xe<b>{summary.customers-summary.with_vehicles}</b></button></div>
        <div className="order-search"><Search size={16}/><input aria-label="Tìm khách hàng theo tên, số điện thoại, email hoặc biển số" value={query} onChange={e=>{setQuery(e.target.value);setCurrentPage(1)}} placeholder="Tìm tên, SĐT, email, biển số..."/>{query&&<button type="button" className="customer-clear-search" onClick={()=>{setQuery('');setCurrentPage(1)}} aria-label="Xóa từ khóa tìm kiếm"><X size={15}/></button>}</div>
      </div>
      {error && <div className="inline-error"><CircleAlert size={15}/>{error}</div>}
      {loading ? <div className="detail-loading"><i/><span>Đang tải khách hàng...</span></div>
      : visible.length===0 ? <div className="empty-state"><Users size={30}/><strong>Chưa có khách hàng phù hợp</strong><p>Thêm hồ sơ mới hoặc thử từ khóa khác.</p></div>
       : <div className="table-wrap"><table className="order-table">
         <thead><tr><th scope="col">KHÁCH HÀNG</th><th scope="col">LIÊN HỆ</th><th scope="col">XE / BIỂN SỐ</th><th scope="col">LẦN GHÉ GẦN NHẤT</th><th scope="col">GIÁ TRỊ TRỌN ĐỜI</th><th scope="col">LỊCH HẸN</th><th scope="col">THAO TÁC</th></tr></thead>
        <tbody>{visible.map(customer=><tr key={customer.id} onClick={()=>setSelectedId(customer.id)}>
          <td><div className="customer-cell"><div className="customer-avatar">{initialsOf(customer.name)}</div><div><strong>{customer.name}</strong><small>{customer.address || `Khách hàng từ ${formatMoment(customer.created_at,false)}`}</small></div></div></td>
          <td><div className="contact-cell"><strong>{customer.phone || 'Chưa có SĐT'}</strong><small>{customer.email || 'Chưa có email'}</small></div></td>
           <td><div className="vehicle-count"><strong>{customer.vehicle_count || 0} xe</strong>{customer.plates ? <span className="customer-plates" title={customer.plates}>{customer.plates.split(' • ').slice(0,2).map((plate:string,index:number)=><small key={`${plate}-${index}`}>{plate}</small>)}{Number(customer.vehicle_count||0)>2&&<small className="customer-more-vehicles">+{Number(customer.vehicle_count)-2} xe</small>}</span> : <small>Chưa liên kết xe</small>}</div></td>
           <td><div className="visit-cell"><strong>{customer.last_visit ? formatMoment(customer.last_visit,false) : 'Chưa có lịch sử'}</strong><small>{customer.last_visit && customer.last_mileage!=null ? `${new Intl.NumberFormat('vi-VN').format(customer.last_mileage)} km` : (customer.last_visit ? customer.last_service || '—' : '—')}</small></div></td>
           <td className="customer-money"><strong>{money(Number(customer.lifetime_value||0))}</strong></td>
          <td><span className="item-count">{customer.appointment_count || 0} lịch</span></td>
           <td><button className="row-open" aria-label={`Mở hồ sơ ${customer.name}`}>Mở <ArrowUpRight size={14}/></button></td>
        </tr>)}</tbody>
       </table></div>}
       {!loading && pages>0 && <div className="customer-pagination"><span>{total} hồ sơ phù hợp · Trang {currentPage}/{pages}</span><label>Số dòng <select value={pageSize} onChange={e=>{setPageSize(Number(e.target.value));setCurrentPage(1)}}><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option></select></label><div><button disabled={currentPage<=1} onClick={()=>setCurrentPage(page=>page-1)}>Trước</button><button disabled={currentPage>=pages} onClick={()=>setCurrentPage(page=>page+1)}>Sau</button></div></div>}
    </section>
    {selectedId!==null && <CustomerDrawer customerId={selectedId} onClose={()=>setSelectedId(null)} onChanged={load}/>}
    {creating && <CustomerModal onClose={()=>setCreating(false)} onCreated={()=>{setCreating(false);load()}}/>}
  </div>;
}

function CustomerModal({onClose,onCreated}:{onClose:()=>void;onCreated:()=>void}) {
  const [form,setForm]=useState({name:'',phone:'',email:'',address:'',note:''});
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');
  const [duplicates,setDuplicates]=useState<any[]>([]);

  async function save(event:React.FormEvent, force=false){
    event.preventDefault(); setSaving(true); setError('');
    try{
      const response=await api(`/api/customers${force?'?allow_duplicate=true':''}`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(form)
      });
      if(!response.ok){
        const info=await readApiError(response);
        if(response.status===409 && info.details?.customers){
          setDuplicates(info.details.customers);
          setError('Có hồ sơ khách hàng tương tự trong hệ thống. Kiểm tra trước khi tạo mới.');
        }else setError(info.message);
        return;
      }
      onCreated();
    }catch{ setError('Không tạo được khách hàng.') }
    finally{ setSaving(false) }
  }

  return <div className="modal-overlay" onMouseDown={onClose}><form className="modal" onMouseDown={e=>e.stopPropagation()} onSubmit={save}>
    <div className="modal-head"><div><p className="eyebrow">HỒ SƠ MỚI</p><h2>Thêm khách hàng</h2></div><button type="button" onClick={onClose} aria-label="Đóng"><X/></button></div>
    <label>Họ và tên<input required minLength={2} value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
    <div className="field-row"><label>Số điện thoại<input required minLength={6} value={form.phone} onChange={e=>setForm({...form,phone:e.target.value})}/></label><label>Email<input type="email" value={form.email} onChange={e=>setForm({...form,email:e.target.value})}/></label></div>
    <label>Địa chỉ<input value={form.address} onChange={e=>setForm({...form,address:e.target.value})}/></label>
    <label>Ghi chú<textarea rows={2} value={form.note} onChange={e=>setForm({...form,note:e.target.value})}/></label>
    {duplicates.length>0 && <div className="duplicate-box"><div><CircleAlert size={16}/><div><strong>Có thể trùng hồ sơ</strong><p>Chọn một hồ sơ bên dưới để mở, hoặc xác nhận tạo mới.</p></div></div><ul className="duplicate-list">{duplicates.map(item=><li key={item.id}><div><strong>{item.name}</strong><small>{item.phone} • {item.plates || 'Chưa có xe'}</small></div></li>)}</ul><div className="duplicate-actions"><button type="button" className="btn secondary" onClick={()=>setDuplicates([])}>Quay lại</button><button type="button" className="btn primary" onClick={e=>save(e,true)} disabled={saving}>Vẫn tạo mới</button></div></div>}
    {error && <div className="inline-error"><CircleAlert size={15}/>{error}</div>}
    <div className="modal-actions"><button type="button" className="btn secondary" onClick={onClose}>Hủy</button><button className="btn primary" disabled={saving}>{saving?'Đang lưu...':'Tạo khách hàng'}</button></div>
  </form></div>;
}

function CustomerDrawer({customerId,onClose,onChanged}:{customerId:number;onClose:()=>void;onChanged:()=>void}) {
  const [customer,setCustomer]=useState<any>(null);
  const [editing,setEditing]=useState(false);
  const [form,setForm]=useState({name:'',phone:'',email:'',address:'',note:''});
  const [vehicle,setVehicle]=useState({plate:'',make:'',model:'',year:'',vin:'',variant:'',engine_code:'',fuel_type:'',mileage:''});
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');
  const [message,setMessage]=useState('');

  async function load(){
    try{
      const response=await api(`/api/customers/${customerId}`);
      if(!response.ok) throw new Error();
      const data=await response.json();
      setCustomer(data);
      setForm({name:data.name||'',phone:data.phone||'',email:data.email||'',address:data.address||'',note:data.note||''});
    }catch{ setError('Không tải được hồ sơ khách hàng.') }
  }
  useEffect(()=>{ load(); },[customerId]);

  async function saveCustomer(event:React.FormEvent){
    event.preventDefault(); setSaving(true); setError(''); setMessage('');
    try{
      const response=await api(`/api/customers/${customerId}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(form)});
      if(!response.ok){ const info=await readApiError(response); setError(info.message); return; }
      setEditing(false); await load(); onChanged(); setMessage('Đã cập nhật hồ sơ khách hàng.');
    }catch{ setError('Không cập nhật được hồ sơ.') }
    finally{ setSaving(false) }
  }

  async function addVehicle(event:React.FormEvent){
    event.preventDefault(); setSaving(true); setError(''); setMessage('');
    try{
      const response=await api(`/api/customers/${customerId}/vehicles`,{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({plate:vehicle.plate,make:vehicle.make,model:vehicle.model,year:vehicle.year?Number(vehicle.year):null,vin:vehicle.vin,variant:vehicle.variant,engine_code:vehicle.engine_code,fuel_type:vehicle.fuel_type,mileage:vehicle.mileage===''?null:Number(vehicle.mileage)})
      });
      if(!response.ok){ const info=await readApiError(response); setError(info.message); return; }
      setVehicle({plate:'',make:'',model:'',year:'',vin:'',variant:'',engine_code:'',fuel_type:'',mileage:''});
      await load(); onChanged(); setMessage('Đã thêm xe vào hồ sơ khách hàng.');
    }catch{ setError('Không thêm được xe.') }
    finally{ setSaving(false) }
  }

  return <div className="drawer-overlay" onMouseDown={onClose}><aside className="work-drawer customer-detail-drawer" onMouseDown={e=>e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Hồ sơ khách hàng">
    <div className="work-head"><div className="work-head-main"><div className="work-icon"><Users size={20}/></div><div><strong>{customer?.name || 'Hồ sơ khách hàng'}</strong><small>{customer?.phone || customer?.email || 'Thông tin liên hệ'}</small></div></div><button onClick={onClose} aria-label="Đóng"><X/></button></div>
     {!customer ? <div className="detail-loading"><i/><span>Đang tải hồ sơ...</span></div> : <div className="work-body">
       <div className="customer-record-meta"><span>Hồ sơ KH-{String(customer.id).padStart(5,'0')}</span><span>Ngày tạo: {customer.created_at ? formatMoment(customer.created_at,false) : 'Chưa có thông tin'}</span></div>
      <div className="work-meta four">
        <div><CarFront size={15}/><span><small>Số xe</small><strong>{customer.vehicle_count || 0} xe</strong></span></div>
        <div><CalendarDays size={15}/><span><small>Lần gần nhất</small><strong>{customer.last_visit ? formatMoment(customer.last_visit,false) : 'Chưa có'}</strong></span></div>
        <div><Gauge size={15}/><span><small>Số km gần nhất</small><strong>{customer.last_mileage ? `${new Intl.NumberFormat('vi-VN').format(customer.last_mileage)} km` : '—'}</strong></span></div>
        <div><CircleDollarSign size={15}/><span><small>Giá trị trọn đời</small><strong>{money(Number(customer.lifetime_value||0))}</strong></span></div>
      </div>

      <div className="work-section">
        <div className="section-title-row"><h3>Thông tin liên hệ</h3><button className="row-open" onClick={()=>setEditing(!editing)}><Pencil size={14}/>{editing?'Đóng':'Chỉnh sửa'}</button></div>
        {!editing ? <div className="detail-grid">
          <Info icon={Phone} label="Điện thoại" value={customer.phone || 'Chưa cập nhật'}/>
          <Info icon={Mail} label="Email" value={customer.email || 'Chưa cập nhật'}/>
          <Info icon={MapPin} label="Địa chỉ" value={customer.address || 'Chưa cập nhật'}/>
          <Info icon={FileText} label="Ghi chú" value={customer.note || 'Không có ghi chú'}/>
        </div> : <form onSubmit={saveCustomer}>
          <div className="field-row"><label>Họ tên<input required value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label><label>Số điện thoại<input required value={form.phone} onChange={e=>setForm({...form,phone:e.target.value})}/></label></div>
          <div className="field-row"><label>Email<input type="email" value={form.email} onChange={e=>setForm({...form,email:e.target.value})}/></label><label>Địa chỉ<input value={form.address} onChange={e=>setForm({...form,address:e.target.value})}/></label></div>
          <label className="full">Ghi chú<textarea rows={2} value={form.note} onChange={e=>setForm({...form,note:e.target.value})}/></label>
          <div className="work-actions"><button className="btn primary" disabled={saving}>Lưu thay đổi</button></div>
        </form>}
      </div>

      <div className="work-section">
        <h3>Xe của khách hàng</h3>
        {(customer.vehicles||[]).length===0 ? <p className="work-empty">Chưa liên kết xe nào.</p> : <ul className="vehicle-list">{customer.vehicles.map((item:any)=><li key={item.id}><div className="vehicle-list-icon"><CarFront size={17}/></div><div><strong>{item.plate}</strong><small>{[item.make,item.model,item.year,item.variant,item.engine_code,item.fuel_type].filter(Boolean).join(' • ')}{item.vin ? ` • VIN ${item.vin}` : ''}</small></div><b>{item.last_mileage ? `${new Intl.NumberFormat('vi-VN').format(item.last_mileage)} km` : '—'}</b></li>)}</ul>}
        <form className="vehicle-form" onSubmit={addVehicle}>
          <input required placeholder="Biển số *" value={vehicle.plate} onChange={e=>setVehicle({...vehicle,plate:e.target.value.toUpperCase()})}/>
          <input required placeholder="Hãng *" value={vehicle.make} onChange={e=>setVehicle({...vehicle,make:e.target.value})}/>
          <input required placeholder="Dòng xe *" value={vehicle.model} onChange={e=>setVehicle({...vehicle,model:e.target.value})}/>
          <input type="number" min="1900" max="2100" placeholder="Năm sản xuất" value={vehicle.year} onChange={e=>setVehicle({...vehicle,year:e.target.value})}/>
          <input placeholder="VIN" value={vehicle.vin} onChange={e=>setVehicle({...vehicle,vin:e.target.value.toUpperCase()})}/>
          <input placeholder="Phiên bản xe" value={vehicle.variant} onChange={e=>setVehicle({...vehicle,variant:e.target.value})}/>
          <input placeholder="Mã động cơ" value={vehicle.engine_code} onChange={e=>setVehicle({...vehicle,engine_code:e.target.value.toUpperCase()})}/>
          <input placeholder="Loại nhiên liệu (xăng, dầu, hybrid, điện...)" value={vehicle.fuel_type} onChange={e=>setVehicle({...vehicle,fuel_type:e.target.value})}/>
          <input type="number" min="0" placeholder="Số km" value={vehicle.mileage} onChange={e=>setVehicle({...vehicle,mileage:e.target.value})}/>
          <button className="btn secondary" disabled={saving}><Plus size={14}/> Thêm xe vào hồ sơ</button>
        </form>
      </div>

       <div className="work-section">
         <h3>Lịch sử sửa chữa</h3>
         {(customer.history||[]).length===0 ? <p className="work-empty">Chưa có lịch sử sửa chữa.</p> : <ol className="order-history">{customer.history.map((row:any)=><li key={`h-${row.id}`}><i className="done"/><div><strong>{row.order_code || row.plate || 'Lần sửa chữa'}</strong><small>{formatMoment(row.repaired_at)} • {row.mileage ? `${new Intl.NumberFormat('vi-VN').format(row.mileage)} km` : 'Không ghi km'}</small><p>{row.services || row.note || 'Không có nội dung'} {row.total ? `• ${money(Number(row.total))}` : ''}</p></div></li>)}</ol>}
       </div>

       <div className="work-section customer-appointments">
         <h3>Lịch hẹn gần đây</h3>
         {(customer.appointments||[]).length===0 ? <p className="work-empty">Chưa có lịch hẹn.</p> : <ul>{customer.appointments.map((appointment:any)=><li key={appointment.id}><span className="customer-appt-icon"><CalendarDays size={16}/></span><div><strong>{formatMoment(appointment.appointment_at)} · {appointment.plate || 'Chưa có biển số'}</strong><small>{appointment.service || 'Chưa có nội dung'} · {appointment.status}</small></div></li>)}</ul>}
       </div>

      <div className="work-section">
        <h3>Ghi chú gần đây</h3>
        {(customer.notes||[]).length===0 ? <p className="work-empty">Chưa có ghi chú kỹ thuật.</p> : <ul className="vehicle-list">{customer.notes.map((note:any)=><li key={`n-${note.id}`}><div className="vehicle-list-icon"><ClipboardList size={16}/></div><div><strong>{note.order_code} • {note.plate}</strong><small>{note.content}</small></div><b>{formatMoment(note.created_at,false)}</b></li>)}</ul>}
      </div>
      {message && <div className="inline-success"><CheckCircle2 size={15}/>{message}</div>}
      {error && <div className="inline-error"><CircleAlert size={15}/>{error}</div>}
    </div>}
  </aside></div>;
}

function VehiclesPage({onOpenAI,onLoaded}:{onOpenAI:()=>void;onLoaded?:(count:number)=>void}) {
  const [vehicles,setVehicles]=useState<any[]>([]);
  const [query,setQuery]=useState('');
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [selectedId,setSelectedId]=useState<number|null>(null);
  const [creating,setCreating]=useState(false);

  async function load(){
    setLoading(true);
    try{
      const response=await api('/api/vehicles?page_size=200');
      if(!response.ok) throw new Error();
      const rows=await readList(response);
      setVehicles(rows); onLoaded?.(rows.length); setError('');
    }catch{ setError('Không tải được danh sách xe.') }
    finally{ setLoading(false) }
  }
  useEffect(()=>{ load(); },[]);

  const keyword=query.trim().toLowerCase();
  const visible=vehicles.filter(vehicle=>`${vehicle.plate||''} ${vehicle.make||''} ${vehicle.model||''} ${vehicle.year||''} ${vehicle.variant||''} ${vehicle.engine_code||''} ${vehicle.fuel_type||''} ${vehicle.vin||''} ${vehicle.customer_name||''} ${vehicle.customer_phone||''}`.toLowerCase().includes(keyword));
  const active=vehicles.reduce((sum,vehicle)=>sum+Number(vehicle.active_order_count||0),0);
  const history=vehicles.reduce((sum,vehicle)=>sum+Number(vehicle.history_count||0),0);

  return <div className="page vehicles-page">
    <section className="page-heading"><div><p className="eyebrow">DANH MỤC PHƯƠNG TIỆN</p><h1>Xe</h1><p>Hồ sơ phương tiện, chủ sở hữu và lịch sử bảo dưỡng.</p></div><div className="heading-actions"><button className="btn secondary" onClick={onOpenAI}><Sparkles size={17}/> Trợ lý AI</button><button className="btn primary" onClick={()=>setCreating(true)}><Plus size={18}/> Thêm xe</button></div></section>
    <section className="metrics">
      <StatCard icon={CarFront} label="Tổng số xe" value={vehicles.length} note={`${visible.length} xe hiển thị`} color="blue"/>
      <StatCard icon={ClipboardList} label="Đang có phiếu mở" value={active} note="Xe đang trong xưởng" color="orange"/>
      <StatCard icon={History} label="Lần sửa chữa" value={history} note="Lịch sử đã ghi nhận" color="violet"/>
      <StatCard icon={Gauge} label="Xe có số km" value={vehicles.filter(vehicle=>vehicle.last_mileage!=null).length} note="Đã cập nhật số km" color="green"/>
    </section>
    <section className="card orders-card">
      <div className="card-title"><div><h2>Danh sách phương tiện</h2><p>Bấm vào dòng để xem hồ sơ xe và lịch sử sửa chữa</p></div></div>
      <div className="order-toolbar"><div className="filter-tabs"><button className="active">Tất cả<b>{vehicles.length}</b></button></div><div className="order-search"><Search size={16}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Tìm biển số, VIN, chủ xe..."/></div></div>
      {error && <div className="inline-error"><CircleAlert size={15}/>{error}</div>}
      {loading ? <div className="detail-loading"><i/><span>Đang tải danh sách xe...</span></div>
      : visible.length===0 ? <div className="empty-state"><CarFront size={30}/><strong>Chưa có xe phù hợp</strong><p>Thêm xe mới hoặc thử từ khóa khác.</p></div>
      : <div className="table-wrap"><table className="order-table">
        <thead><tr><th>BIỂN SỐ</th><th>XE</th><th>CHỦ SỞ HỮU</th><th>VIN</th><th>SỐ KM</th><th>LỊCH SỬ</th><th>PHIẾU MỞ</th><th/></tr></thead>
        <tbody>{visible.map(vehicle=><tr key={vehicle.id} onClick={()=>setSelectedId(vehicle.id)}>
          <td><strong className="order-code">{vehicle.plate}</strong><small>Đang quản lý</small></td>
           <td><div className="vehicle-cell"><div className="mini-car"><CarFront size={19}/></div><div><strong>{vehicle.make} {vehicle.model}</strong><small>{[vehicle.year||'Chưa rõ năm',vehicle.variant,vehicle.engine_code,vehicle.fuel_type].filter(Boolean).join(' • ')}</small></div></div></td>
          <td><div className="contact-cell"><strong>{vehicle.customer_name || 'Chưa có chủ'}</strong><small>{vehicle.customer_phone || 'Chưa có SĐT'}</small></div></td>
          <td><small>{vehicle.vin || '—'}</small></td>
          <td><strong>{vehicle.last_mileage ? `${new Intl.NumberFormat('vi-VN').format(vehicle.last_mileage)} km` : '—'}</strong></td>
          <td><span className="item-count">{vehicle.history_count || 0} lần</span></td>
          <td><span className={`status ${Number(vehicle.active_order_count||0)>0?'orange':'gray'}`}><i/>{vehicle.active_order_count || 0} phiếu</span></td>
          <td><button className="row-open">Mở <ArrowUpRight size={14}/></button></td>
        </tr>)}</tbody>
      </table></div>}
    </section>
    {selectedId!==null && <VehicleDrawer vehicleId={selectedId} onClose={()=>setSelectedId(null)} onChanged={load}/>}
    {creating && <VehicleModal onClose={()=>setCreating(false)} onCreated={()=>{setCreating(false);load()}}/>}
  </div>;
}

function VehicleModal({onClose,onCreated}:{onClose:()=>void;onCreated:()=>void}) {
  const [customers,setCustomers]=useState<any[]>([]);
  const [form,setForm]=useState({customer_id:'',plate:'',make:'',model:'',year:'',vin:'',variant:'',engine_code:'',fuel_type:'',mileage:''});
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');

  useEffect(()=>{ api('/api/customers?page_size=200').then(readList).then(setCustomers).catch(()=>{}) },[]);

  async function save(event:React.FormEvent){
    event.preventDefault(); setSaving(true); setError('');
    try{
      const response=await api(`/api/vehicles?customer_id=${form.customer_id}`,{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({plate:form.plate,make:form.make,model:form.model,year:form.year?Number(form.year):null,vin:form.vin,variant:form.variant,engine_code:form.engine_code,fuel_type:form.fuel_type,mileage:form.mileage===''?null:Number(form.mileage)})
      });
      if(!response.ok){ const info=await readApiError(response); setError(info.message); return; }
      onCreated();
    }catch{ setError('Không tạo được xe.') }
    finally{ setSaving(false) }
  }

  return <div className="modal-overlay" onMouseDown={onClose}><form className="modal" onMouseDown={e=>e.stopPropagation()} onSubmit={save}>
    <div className="modal-head"><div><p className="eyebrow">PHƯƠNG TIỆN MỚI</p><h2>Thêm xe</h2></div><button type="button" onClick={onClose} aria-label="Đóng"><X/></button></div>
    <label>Chủ sở hữu<select required value={form.customer_id} onChange={e=>setForm({...form,customer_id:e.target.value})}><option value="">Chọn khách hàng</option>{customers.map(customer=><option key={customer.id} value={customer.id}>{customer.name} • {customer.phone}</option>)}</select></label>
    <label>Biển số<input required minLength={5} value={form.plate} onChange={e=>setForm({...form,plate:e.target.value.toUpperCase()})}/></label>
    <div className="field-row"><label>Hãng<input required value={form.make} onChange={e=>setForm({...form,make:e.target.value})}/></label><label>Dòng xe<input required value={form.model} onChange={e=>setForm({...form,model:e.target.value})}/></label></div>
    <div className="field-row"><label>Năm sản xuất<input type="number" min="1900" max="2100" value={form.year} onChange={e=>setForm({...form,year:e.target.value})}/></label><label>Số km<input type="number" min="0" value={form.mileage} onChange={e=>setForm({...form,mileage:e.target.value})}/></label></div>
    <label>VIN<input value={form.vin} onChange={e=>setForm({...form,vin:e.target.value.toUpperCase()})}/></label>
    <div className="field-row"><label>Phiên bản xe<input value={form.variant} onChange={e=>setForm({...form,variant:e.target.value})} placeholder="Theo hồ sơ xe"/></label><label>Mã động cơ<input value={form.engine_code} onChange={e=>setForm({...form,engine_code:e.target.value.toUpperCase()})} placeholder="Theo tem/mã động cơ"/></label></div>
    <label>Loại nhiên liệu<input value={form.fuel_type} onChange={e=>setForm({...form,fuel_type:e.target.value})} placeholder="Xăng, dầu, hybrid..."/></label>
    {error && <div className="inline-error"><CircleAlert size={15}/>{error}</div>}
    <div className="modal-actions"><button type="button" className="btn secondary" onClick={onClose}>Hủy</button><button className="btn primary" disabled={saving}>{saving?'Đang lưu...':'Tạo xe'}</button></div>
  </form></div>;
}

function VehicleDrawer({vehicleId,onClose,onChanged}:{vehicleId:number;onClose:()=>void;onChanged:()=>void}) {
  const [vehicle,setVehicle]=useState<any>(null);
  const [editing,setEditing]=useState(false);
  const [form,setForm]=useState({make:'',model:'',year:'',vin:'',variant:'',engine_code:'',fuel_type:'',mileage:''});
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');
  const [message,setMessage]=useState('');

  async function load(){
    try{
      const response=await api(`/api/vehicles/${vehicleId}`);
      if(!response.ok) throw new Error();
      const data=await response.json();
      setVehicle(data);
      setForm({make:data.make||'',model:data.model||'',year:data.year||'',vin:data.vin||'',variant:data.variant||'',engine_code:data.engine_code||'',fuel_type:data.fuel_type||'',mileage:data.last_mileage ?? data.mileage ?? ''});
    }catch{ setError('Không tải được hồ sơ xe.') }
  }
  useEffect(()=>{ load(); },[vehicleId]);

  async function save(event:React.FormEvent){
    event.preventDefault(); setSaving(true); setError(''); setMessage('');
    try{
      const response=await api(`/api/vehicles/${vehicleId}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({make:form.make,model:form.model,year:form.year?Number(form.year):null,vin:form.vin,variant:form.variant,engine_code:form.engine_code,fuel_type:form.fuel_type,mileage:form.mileage===''?null:Number(form.mileage)})});
      if(!response.ok){ const info=await readApiError(response); setError(info.message); return; }
      setEditing(false); await load(); onChanged(); setMessage('Đã cập nhật hồ sơ xe.');
    }catch{ setError('Không cập nhật được hồ sơ xe.') }
    finally{ setSaving(false) }
  }

  return <div className="drawer-overlay" onMouseDown={onClose}><aside className="work-drawer" onMouseDown={e=>e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Hồ sơ xe">
    <div className="work-head"><div className="work-head-main"><div className="work-icon"><CarFront size={20}/></div><div><strong>{vehicle?.plate || 'Hồ sơ xe'}</strong><small>{vehicle ? `${vehicle.make} ${vehicle.model} ${vehicle.year ? `• ${vehicle.year}` : ''}` : 'Đang tải...'}</small></div></div><button onClick={onClose} aria-label="Đóng"><X/></button></div>
    {!vehicle ? <div className="detail-loading"><i/><span>Đang tải hồ sơ xe...</span></div> : <div className="work-body">
      <div className="work-meta four">
        <div><Users size={15}/><span><small>Chủ sở hữu</small><strong>{vehicle.customer_name || 'Chưa có'}</strong></span></div>
        <div><Phone size={15}/><span><small>Điện thoại</small><strong>{vehicle.customer_phone || '—'}</strong></span></div>
        <div><Gauge size={15}/><span><small>Số km gần nhất</small><strong>{vehicle.last_mileage ? `${new Intl.NumberFormat('vi-VN').format(vehicle.last_mileage)} km` : '—'}</strong></span></div>
        <div><CalendarDays size={15}/><span><small>Lần gần nhất</small><strong>{vehicle.last_visit || vehicle.history?.[0]?.repaired_at ? formatMoment(vehicle.last_visit || vehicle.history?.[0]?.repaired_at,false) : '—'}</strong></span></div>
      </div>
      <div className="work-section">
        <div className="section-title-row"><h3>Thông tin xe</h3><button className="row-open" onClick={()=>setEditing(!editing)}><Pencil size={14}/>{editing?'Đóng':'Chỉnh sửa'}</button></div>
        <p className="work-hint">Mỗi xe có một năm sản xuất. “Năm từ – Đến năm” là phạm vi áp dụng của phụ tùng trong Cấu hình xe, không phải thông tin của xe này.</p>
         {!editing ? <div className="detail-grid"><Info icon={CarFront} label="Biển số" value={vehicle.plate}/><Info icon={CarFront} label="Hãng" value={vehicle.make||'Chưa cập nhật'}/><Info icon={CarFront} label="Dòng xe" value={vehicle.model||'Chưa cập nhật'}/><Info icon={CalendarDays} label="Năm sản xuất" value={vehicle.year?String(vehicle.year):'Chưa cập nhật'}/><Info icon={CarFront} label="Phiên bản" value={vehicle.variant || 'Chưa cập nhật'}/><Info icon={Wrench} label="Mã động cơ" value={vehicle.engine_code || 'Chưa cập nhật'}/><Info icon={Gauge} label="Loại nhiên liệu" value={vehicle.fuel_type || 'Chưa cập nhật'}/><Info icon={ShieldCheck} label="VIN" value={vehicle.vin || 'Chưa cập nhật'}/><Info icon={Gauge} label="Số km" value={(vehicle.last_mileage ?? vehicle.mileage)!=null?`${new Intl.NumberFormat('vi-VN').format(vehicle.last_mileage ?? vehicle.mileage)} km`:'Chưa cập nhật'}/></div>
        : <form onSubmit={save}><div className="field-row"><label>Hãng<input required value={form.make} onChange={e=>setForm({...form,make:e.target.value})}/></label><label>Dòng xe<input required value={form.model} onChange={e=>setForm({...form,model:e.target.value})}/></label></div><div className="field-row"><label>Năm sản xuất<input type="number" value={form.year} onChange={e=>setForm({...form,year:e.target.value})}/></label><label>Số km<input type="number" value={form.mileage} onChange={e=>setForm({...form,mileage:e.target.value})}/></label></div><label className="full">VIN<input value={form.vin} onChange={e=>setForm({...form,vin:e.target.value.toUpperCase()})}/></label><div className="field-row"><label>Phiên bản<input value={form.variant} onChange={e=>setForm({...form,variant:e.target.value})}/></label><label>Mã động cơ<input value={form.engine_code} onChange={e=>setForm({...form,engine_code:e.target.value.toUpperCase()})}/></label></div><label className="full">Loại nhiên liệu<input value={form.fuel_type} onChange={e=>setForm({...form,fuel_type:e.target.value})}/></label><div className="work-actions"><button className="btn primary" disabled={saving}>Lưu thay đổi</button></div></form>}
      </div>
      <div className="work-section"><h3>Lịch sử sửa chữa</h3>{(vehicle.history||[]).length===0?<p className="work-empty">Chưa có lịch sử.</p>:<ol className="order-history">{vehicle.history.map((row:any)=><li key={`vh-${row.id}`}><i className="done"/><div><strong>{row.order_code || 'Lần sửa chữa'}</strong><small>{formatMoment(row.repaired_at)} • {row.mileage?`${new Intl.NumberFormat('vi-VN').format(row.mileage)} km`:'Không ghi km'}</small><p>{row.services || row.note || '—'}{row.total?` • ${money(Number(row.total))}`:''}</p></div></li>)}</ol>}</div>
      <div className="work-section"><h3>Phiếu sửa chữa gần đây</h3>{(vehicle.orders||[]).length===0?<p className="work-empty">Chưa có phiếu sửa chữa.</p>:<ul className="vehicle-list">{vehicle.orders.map((order:any)=><li key={`vo-${order.id}`}><div className="vehicle-list-icon"><ClipboardList size={16}/></div><div><strong>{order.code}</strong><small>{order.note || 'Không có ghi chú'}</small></div><OrderStatus code={order.status_code} text={order.status}/></li>)}</ul>}</div>
      {message && <div className="inline-success"><CheckCircle2 size={15}/>{message}</div>}
      {error && <div className="inline-error"><CircleAlert size={15}/>{error}</div>}
    </div>}
  </aside></div>;
}

function MyVehiclesPage({onOpenAI}:{onOpenAI:()=>void}) {
  const [data,setData]=useState<any>(null);
  const [error,setError]=useState('');
  useEffect(()=>{ api('/api/my-vehicles').then(r=>{ if(!r.ok) throw new Error(); return r.json() }).then(setData).catch(()=>setError('Không tải được danh sách xe của bạn.')) },[]);
  if(error) return <div className="page"><div className="inline-error"><CircleAlert size={15}/>{error}</div></div>;
  if(!data) return <div className="page"><div className="detail-loading"><i/><span>Đang tải xe của bạn...</span></div></div>;
  const vehicles=data.vehicles||[];
  const openOrders=vehicles.reduce((sum:number,vehicle:any)=>sum+(vehicle.orders||[]).filter((order:any)=>!['COMPLETED','DELIVERED','CANCELLED'].includes(statusCodeOf(order))).length,0);
  return <div className="page">
    <section className="page-heading"><div><p className="eyebrow">GARAGE CỦA BẠN</p><h1>Xe của tôi</h1><p>Theo dõi phương tiện, lịch sử bảo dưỡng và lịch hẹn tại garage.</p></div><div className="heading-actions"><button className="btn secondary" onClick={onOpenAI}><Sparkles size={17}/> Trợ lý AI</button></div></section>
    <section className="owner-summary card"><div className="owner-avatar">{initialsOf(data.customer?.full_name || data.customer?.name)}</div><div><p>CHỦ SỞ HỮU</p><h2>{data.customer?.full_name || data.customer?.name || 'Khách hàng'}</h2><span>{data.customer?.email || data.customer?.phone || 'Chưa cập nhật liên hệ'}</span></div><div className="owner-address"><MapPin size={15}/>{data.customer?.address || 'Chưa cập nhật địa chỉ'}</div></section>
    <section className="metrics"><StatCard icon={CarFront} label="Xe của tôi" value={vehicles.length} note="Phương tiện đã đăng ký" color="blue"/><StatCard icon={ClipboardList} label="Phiếu đang mở" value={openOrders} note="Đang được garage xử lý" color="orange"/><StatCard icon={History} label="Lần bảo dưỡng" value={vehicles.reduce((sum:number,vehicle:any)=>sum+(vehicle.history||[]).length,0)} note="Lịch sử đã ghi nhận" color="green"/></section>
    {vehicles.length===0 ? <div className="empty-state"><CarFront size={30}/><strong>Chưa có xe</strong><p>Liên hệ garage để cập nhật phương tiện của bạn.</p></div> : <div className="vehicle-list">{vehicles.map((vehicle:any)=><article className="card" key={vehicle.id} style={{padding:'16px 18px',marginTop:'12px'}}>
      <div className="card-title" style={{padding:0,marginBottom:'10px'}}><div><h2>{vehicle.plate}</h2><p>{vehicle.make} {vehicle.model}{vehicle.year?` • ${vehicle.year}`:''}{vehicle.vin?` • VIN ${vehicle.vin}`:''}</p></div><span className="status navy"><i/>{vehicle.last_mileage || vehicle.history?.[0]?.mileage ? `${new Intl.NumberFormat('vi-VN').format(vehicle.last_mileage || vehicle.history?.[0]?.mileage)} km` : 'Chưa rõ km'}</span></div>
      <div className="my-vehicle-spec-grid" aria-label={`Thông tin xe ${vehicle.plate}`}>
        <div><small>Hãng</small><strong>{vehicle.make||'Chưa cập nhật'}</strong></div>
        <div><small>Dòng xe</small><strong>{vehicle.model||'Chưa cập nhật'}</strong></div>
        <div><small>Năm sản xuất</small><strong>{vehicle.year||'Chưa cập nhật'}</strong></div>
        <div><small>Phiên bản</small><strong>{vehicle.variant||'Chưa cập nhật'}</strong></div>
        <div><small>Mã động cơ</small><strong>{vehicle.engine_code||'Chưa cập nhật'}</strong></div>
        <div><small>Loại nhiên liệu</small><strong>{vehicle.fuel_type||'Chưa cập nhật'}</strong></div>
      </div>
      {(vehicle.orders||[]).length>0 && <div className="table-wrap"><table className="order-table"><thead><tr><th>PHIẾU</th><th>NỘI DUNG</th><th>TRẠNG THÁI</th><th>TẠM TÍNH</th></tr></thead><tbody>{vehicle.orders.map((order:any)=><tr key={order.id}><td><strong className="order-code">{order.code}</strong></td><td><span className="note-cell">{order.note || '—'}</span></td><td><OrderStatus code={order.status_code} text={order.status}/></td><td><strong>{money(Number(order.total||0))}</strong></td></tr>)}</tbody></table></div>}
      {(vehicle.history||[]).length>0 && <div className="work-section"><h3>Lịch sử bảo dưỡng</h3><ol className="order-history">{vehicle.history.slice(0,5).map((row:any)=><li key={`mh-${row.id}`}><i className="done"/><div><strong>{row.services || 'Bảo dưỡng'}</strong><small>{formatMoment(row.repaired_at)} • {row.mileage?`${new Intl.NumberFormat('vi-VN').format(row.mileage)} km`:'Không ghi km'}</small>{row.note&&<p>{row.note}</p>}</div></li>)}</ol></div>}
    </article>)}</div>}
  </div>;
}


const ORDER_STATUS_OPTIONS = [
  {code:'RECEIVED',label:'Tiếp nhận'},
  {code:'INSPECTING',label:'Đang kiểm tra'},
  {code:'QUOTED',label:'Đã báo giá'},
  {code:'APPROVED',label:'Đã duyệt'},
  {code:'IN_PROGRESS',label:'Đang sửa'},
  {code:'WAITING_FOR_PARTS',label:'Chờ phụ tùng'},
  {code:'ON_HOLD',label:'Tạm dừng'},
  {code:'COMPLETED',label:'Hoàn thành'},
  {code:'DELIVERED',label:'Đã bàn giao'},
  {code:'CANCELLED',label:'Đã hủy'},
] as const;
const ORDER_STATUS_LABELS:Record<string,string> = Object.fromEntries(ORDER_STATUS_OPTIONS.map(item=>[item.code,item.label]));
const ORDER_STATUS_CODES:Record<string,string> = Object.fromEntries(ORDER_STATUS_OPTIONS.map(item=>[item.label,item.code]));
const ORDER_STEPS = ['RECEIVED','INSPECTING','QUOTED','APPROVED','IN_PROGRESS','COMPLETED','DELIVERED'];
const ORDER_OPEN_CODES = ['RECEIVED','INSPECTING','QUOTED','APPROVED','IN_PROGRESS','WAITING_FOR_PARTS','ON_HOLD'];
const TRANSITION_NOTE_CODES = ['CANCELLED','ON_HOLD','WAITING_FOR_PARTS'];
const ORDER_STATUSES = ORDER_STATUS_OPTIONS.map(item=>item.label);
const PRIORITIES = ['Thấp', 'Bình thường', 'Cao', 'Gấp'];
const WORKFLOW_ACTION_LABELS:Record<string,string>={INSPECTING:'Bắt đầu kiểm tra',QUOTED:'Chuyển sang đã báo giá',APPROVED:'Xác nhận đã duyệt',IN_PROGRESS:'Bắt đầu sửa chữa',WAITING_FOR_PARTS:'Chuyển sang chờ phụ tùng',ON_HOLD:'Tạm dừng phiếu',COMPLETED:'Đánh dấu hoàn thành',DELIVERED:'Xác nhận bàn giao',CANCELLED:'Hủy phiếu'};

function statusCodeOf(order:any):string {
  const code = order?.status_code;
  if (code && ORDER_STATUS_LABELS[code]) return code;
  return ORDER_STATUS_CODES[order?.status] || 'RECEIVED';
}
function statusLabelOf(order:any):string {
  return ORDER_STATUS_LABELS[statusCodeOf(order)] || order?.status || '—';
}
function isOrderClosed(order:any):boolean {
  return ['COMPLETED','DELIVERED','CANCELLED'].includes(statusCodeOf(order));
}
function isOrderEditable(order:any):boolean {
  return !['COMPLETED','DELIVERED','CANCELLED'].includes(statusCodeOf(order));
}
function formatMoment(value?:string|null, withTime=true):string {
  if (!value) return '—';
  let raw = String(value).trim();
  if (!/[zZ]|[+-]\d\d:\d\d$/.test(raw)) raw = raw.replace(' ', 'T') + 'Z';
  const moment = new Date(raw);
  if (Number.isNaN(moment.getTime())) return String(value);
  return new Intl.DateTimeFormat('vi-VN', {
    timeZone:'Asia/Ho_Chi_Minh', day:'2-digit', month:'2-digit', year:'numeric',
    ...(withTime ? {hour:'2-digit',minute:'2-digit',hour12:false} : {}),
  }).format(moment);
}

function OrderStatus({code,text}:{code?:string;text?:string}) {
  const byLabel = Object.entries(ORDER_STATUS_LABELS).find(([,label])=>label===text)?.[0];
  const resolved = code || byLabel || 'RECEIVED';
  const label = ORDER_STATUS_LABELS[resolved] || text || '—';
  const kind = resolved === 'DELIVERED' || resolved === 'COMPLETED' ? 'green'
    : resolved === 'IN_PROGRESS' ? 'blue'
    : resolved === 'WAITING_FOR_PARTS' || resolved === 'ON_HOLD' ? 'orange'
    : resolved === 'CANCELLED' ? 'gray'
    : resolved === 'INSPECTING' ? 'violet'
    : 'navy';
  return <span className={`status ${kind}`}><i/>{label}</span>
}

function Priority({level}:{level:string}) {
  const kind = level === 'Gấp' ? 'danger' : level === 'Cao' ? 'warning' : level === 'Thấp' ? 'muted' : 'normal';
  return <span className={`priority ${kind}`}>{level || 'Bình thường'}</span>
}

function StatCard({icon: Icon, label, value, note, color}:any) {
  return <div className="metric-card">
    <div className={`metric-icon ${color}`}><Icon size={22}/></div>
    <div className="metric-body"><span>{label}</span><div><strong>{value}</strong></div><small>{note}</small></div>
  </div>
}

function RepairOrdersPage({onOpenAI}:{onOpenAI:()=>void}) {
  const [orders,setOrders]=useState<any[]>([]);
  const [loading,setLoading]=useState(true);
  const [filter,setFilter]=useState('ALL');
  const [search,setSearch]=useState('');
  const [selectedId,setSelectedId]=useState<number|null>(null);
  const [creating,setCreating]=useState(false);
  const [error,setError]=useState('');

  async function load(){
    try{
      const response=await api(`/api/repair-orders?page_size=100`);
      if(!response.ok) throw new Error();
      setOrders(await readList(response)); setError('');
    }catch{ setError('Không tải được danh sách phiếu sửa chữa. Vui lòng kiểm tra backend.') }
    finally{ setLoading(false) }
  }
  useEffect(()=>{ load(); },[]);

  const keyword = search.trim().toLowerCase();
  const visible = orders.filter(order => {
    const code = statusCodeOf(order);
    return (filter === 'ALL' || code === filter) &&
      `${order.code} ${order.plate} ${order.technician || ''} ${order.customer_name || ''} ${order.customer_request || ''} ${order.inspection_notes || ''} ${order.note || ''}`.toLowerCase().includes(keyword);
  });
  const countOf = (code:string) => orders.filter(order => statusCodeOf(order) === code).length;
  const activeCount = orders.filter(order => ORDER_OPEN_CODES.includes(statusCodeOf(order))).length;
  const inspectingCount = orders.filter(order => ['INSPECTING','QUOTED','APPROVED'].includes(statusCodeOf(order))).length;
  const workingCount = countOf('IN_PROGRESS');
  const waitingParts = countOf('WAITING_FOR_PARTS');
  const completedCount = countOf('COMPLETED');
  const workshopValue = orders.filter(order => !['CANCELLED','DELIVERED'].includes(statusCodeOf(order))).reduce((sum, order) => sum + Number(order.total || 0), 0);

  return <div className="page">
    <section className="page-heading">
      <div><p className="eyebrow">XƯỞNG DỊCH VỤ</p><h1>Phiếu sửa chữa</h1><p>Theo dõi tiếp nhận, kiểm tra, báo giá, thi công và bàn giao xe.</p></div>
      <div className="heading-actions">
        <button className="btn secondary" onClick={onOpenAI}><Sparkles size={17}/> Trợ lý AI</button>
        <button className="btn primary" onClick={()=>setCreating(true)}><Plus size={18}/> Tạo phiếu sửa chữa</button>
      </div>
    </section>

    <section className="metrics">
      <StatCard icon={ClipboardList} label="Phiếu trong xưởng" value={activeCount} note={`${countOf('RECEIVED')} phiếu vừa tiếp nhận`} color="blue"/>
      <StatCard icon={Wrench} label="Đang sửa" value={workingCount} note={`${inspectingCount} phiếu đang kiểm tra/báo giá`} color="orange"/>
      <StatCard icon={Package} label="Chờ phụ tùng" value={waitingParts} note={waitingParts ? 'Cần bổ sung vật tư' : 'Đủ phụ tùng'} color="violet"/>
      <StatCard icon={CheckCircle2} label="Hoàn thành" value={completedCount} note="Chờ lập hóa đơn và bàn giao" color="green"/>
    </section>

    <section className="card orders-card">
      <div className="card-title">
        <div><h2>Danh sách phiếu sửa chữa</h2><p>Tổng tạm tính {money(workshopValue)} • {visible.length} phiếu hiển thị</p></div>
      </div>
      <div className="order-toolbar">
        <div className="filter-tabs">
          <button className={filter === 'ALL' ? 'active' : ''} onClick={()=>setFilter('ALL')}>Tất cả<b>{orders.length}</b></button>
          {ORDER_STATUS_OPTIONS.map(status =>
            <button key={status.code} className={filter === status.code ? 'active' : ''} onClick={()=>setFilter(status.code)}>
              {status.label}<b>{countOf(status.code)}</b>
            </button>
          )}
        </div>
        <div className="order-search"><Search size={16}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Tìm mã phiếu, biển số, khách hàng..."/></div>
      </div>

      {error && <div className="inline-error"><CircleAlert size={15}/>{error}</div>}
      {loading ? <div className="detail-loading"><i/><span>Đang tải danh sách phiếu...</span></div>
      : visible.length === 0 ? <div className="empty-state"><ClipboardList size={30}/><strong>Chưa có phiếu phù hợp</strong><p>Thử đổi bộ lọc hoặc tạo phiếu sửa chữa mới cho xe vừa tiếp nhận.</p></div>
      : <div className="table-wrap"><table className="order-table">
        <thead><tr><th>MÃ PHIẾU</th><th>XE / BIỂN SỐ</th><th>KHÁCH HÀNG / YÊU CẦU</th><th>KỸ THUẬT VIÊN</th><th>ƯU TIÊN</th><th>TRẠNG THÁI</th><th>HẠNG MỤC</th><th>TẠM TÍNH</th><th/></tr></thead>
        <tbody>{visible.map(order => <tr key={order.id} onClick={()=>setSelectedId(order.id)}>
          <td><strong className="order-code">{order.code}</strong><small>{formatMoment(order.received_at || order.opened_at || order.created_at)}</small></td>
          <td><div className="vehicle-cell"><div className="mini-car"><CarFront size={19}/></div><div><strong>{order.make ? `${order.make} ${order.model}` : 'Chưa rõ dòng xe'}</strong><small>{order.plate}</small></div></div></td>
          <td><div className="order-request"><strong>{order.customer_name || 'Khách lẻ'}</strong><small>{order.customer_request || order.note || '—'}</small></div></td>
          <td><div className="tech"><span>{(order.technician || '—').split(' ').slice(-2).map((x:string)=>x[0]).join('')}</span>{order.technician || 'Chưa phân công'}</div></td>
          <td><Priority level={order.priority}/></td>
          <td><OrderStatus code={statusCodeOf(order)}/></td>
          <td><span className="item-count">{order.item_count || 0} hạng mục</span></td>
          <td><strong>{money(Number(order.total || 0))}</strong></td>
          <td><button className="row-open">Mở <ArrowUpRight size={14}/></button></td>
        </tr>)}</tbody>
      </table></div>}
    </section>

    {selectedId !== null && <RepairOrderDrawer orderId={selectedId} onClose={()=>setSelectedId(null)} onChanged={load}/>}
    {creating && <NewRepairOrderModal onClose={()=>setCreating(false)} onCreated={()=>{ setCreating(false); load(); }}/>}
  </div>
}

function RepairOrderDrawer({orderId,onClose,onChanged}:{orderId:number,onClose:()=>void,onChanged:()=>void}) {
  const [order,setOrder]=useState<any>(null);
  const [form,setForm]=useState({technician:'',priority:'Bình thường',km_in:'',note:'',initial_condition:'',customer_request:'',inspection_notes:''});
  const [itemForm,setItemForm]=useState({service_id:'',quantity:'1'});
  const [partForm,setPartForm]=useState({part_id:'',quantity:'1'});
  const [parts,setParts]=useState<any[]>([]);
  const [services,setServices]=useState<any[]>([]);
  const [technicians,setTechnicians]=useState<string[]>([]);
  const [selectedServiceIds,setSelectedServiceIds]=useState<number[]>([]);
  const [selectedPartIds,setSelectedPartIds]=useState<number[]>([]);
  const [saving,setSaving]=useState(false);
  const [message,setMessage]=useState('');
  const [error,setError]=useState('');
  const [aiDraft,setAiDraft]=useState('');
  const [aiDraftSources,setAiDraftSources]=useState<AISource[]>([]);
  const [aiLoading,setAiLoading]=useState(false);
  const [quoteReviewId,setQuoteReviewId]=useState<number|null>(null);
  const [pendingTransition,setPendingTransition]=useState<any>(null);
  const [transitionNote,setTransitionNote]=useState('');
  const partRequestKeys=useRef<Record<string,string>>({});

  async function load(){
    try{
      const [response, partsResponse, optionsResponse] = await Promise.all([
        api(`/api/repair-orders/${orderId}`),
        api(`/api/parts?page_size=200`),
        api(`/api/repair-orders/options`),
      ]);
      if(!response.ok) throw new Error();
      const data=await response.json();
      setOrder(data);
      setForm({
        technician:data.technician || '', priority:data.priority || 'Bình thường',
        km_in:data.km_in ?? '', note:data.note || '',
        initial_condition:data.initial_condition || '',
        customer_request:data.customer_request || '',
        inspection_notes:data.inspection_notes || '',
      });
      setSelectedServiceIds((data.items||[]).filter((item:any)=>item.kind==='Dịch vụ'&&item.service_id).map((item:any)=>Number(item.id)));
      setSelectedPartIds((data.parts_used||[]).map((item:any)=>Number(item.id)));
      if(partsResponse.ok) setParts(await readList(partsResponse));
      if(optionsResponse.ok){const options=await optionsResponse.json();setTechnicians((options.technicians||[]).map((item:any)=>item.full_name));setServices(options.services||[])}
    }catch{ setError('Không tải được chi tiết phiếu sửa chữa.') }
  }
  useEffect(()=>{ load(); },[orderId]);

  const currentCode = order ? statusCodeOf(order) : 'RECEIVED';
  const editable = order ? isOrderEditable(order) : false;
  const currentUser = sessionUserCache;
  const canApproveQuote = ['Admin','Quản lý'].includes(currentUser?.role);
  const canRecordTime = ['Admin','Quản lý','Kỹ thuật viên'].includes(currentUser?.role) && ['IN_PROGRESS','COMPLETED'].includes(currentCode);
  const items = order?.items || [];
  const partsUsed = order?.parts_used || [];
  const quotes = order?.quotes || [];
  const currentStepIndex = ORDER_STEPS.indexOf(currentCode);
  const branchStepIndex = currentStepIndex < 0 ? 4 : currentStepIndex;
  const nextStepGuidance = currentCode==='RECEIVED'
    ? 'Điền đủ kỹ thuật viên, số km, tình trạng ban đầu và yêu cầu khách hàng; lưu lại rồi chọn “Bắt đầu kiểm tra”.'
    : currentCode==='INSPECTING'
    ? 'Ghi kết quả kiểm tra, thêm dịch vụ/phụ tùng và tạo báo giá nháp; sau đó chuyển sang “Đã báo giá”.'
    : currentCode==='QUOTED'
    ? 'Báo giá cần được Admin hoặc Quản lý phê duyệt trước khi bắt đầu sửa chữa.'
    : currentCode==='APPROVED'
    ? 'Báo giá đã duyệt. Chọn “Bắt đầu sửa chữa” để sang bước thi công.'
    : currentCode==='IN_PROGRESS'
    ? 'Sau khi hoàn tất công việc, kiểm tra hạng mục và chọn “Đánh dấu hoàn thành”.'
    : '';
  const itemTotal = items.reduce((sum:number,item:any)=>sum + Number(item.quantity) * Number(item.unit_price), 0)
    + partsUsed.reduce((sum:number,item:any)=>sum + Number(item.quantity) * Number(item.unit_price), 0);
  const selectedLabor=items.filter((item:any)=>selectedServiceIds.includes(Number(item.id)))
    .reduce((sum:number,item:any)=>sum+Number(item.quantity)*Number(services.find((service:any)=>service.id===item.service_id)?.price??item.unit_price),0);
  const selectedParts=partsUsed.filter((item:any)=>selectedPartIds.includes(Number(item.id)))
    .reduce((sum:number,item:any)=>sum+Number(item.quantity)*Number(parts.find((part:any)=>part.id===item.part_id)?.sell_price??item.unit_price),0);
  const selectedMinutes=items.filter((item:any)=>selectedServiceIds.includes(Number(item.id)))
    .reduce((sum:number,item:any)=>sum+Number(item.quantity)*Number(services.find((service:any)=>service.id===item.service_id)?.duration_min||0),0);

  async function runTransition(step:any, note=''){
    setSaving(true); setMessage(''); setError('');
    try{
      const response=await api(`/api/repair-orders/${orderId}/transition`,{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({status_code:step.code,note}),
      });
      if(!response.ok){
        const info=await readApiError(response);
        setError(info.message);
        return;
      }
      const updated=await response.json();
      setPendingTransition(null); setTransitionNote('');
      await load(); onChanged();
      setMessage(`Đã chuyển trạng thái: ${ORDER_STATUS_LABELS[updated.status_code] || updated.status}.`);
    }catch{ setError('Không chuyển được trạng thái phiếu.') }
    finally{ setSaving(false) }
  }

  function requestTransition(step:any){
    if(!step.enabled || saving) return;
    if(TRANSITION_NOTE_CODES.includes(step.code)){
      setPendingTransition(step); setTransitionNote('');
    }else{
      runTransition(step, '');
    }
  }

  async function saveFields(event:React.FormEvent){
    event.preventDefault(); setSaving(true); setMessage(''); setError('');
    try{
      const response=await api(`/api/repair-orders/${orderId}`,{
        method:'PATCH',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          technician:form.technician, priority:form.priority,
          km_in:form.km_in === '' ? null : Number(form.km_in), note:form.note,
          initial_condition:form.initial_condition,
          customer_request:form.customer_request,
          inspection_notes:form.inspection_notes,
        })
      });
      if(!response.ok){ const info=await readApiError(response); setError(info.message); return; }
      await load(); onChanged(); setMessage(currentCode==='RECEIVED'?'Đã lưu thông tin. Phiếu đã đủ dữ liệu sẽ cho phép chọn “Bắt đầu kiểm tra” ở phần chuyển trạng thái.':'Đã lưu thông tin phiếu.');
    }catch{ setError('Không lưu được thông tin phiếu.') }
    finally{ setSaving(false) }
  }

  async function addItem(event:React.FormEvent){
    event.preventDefault();
    const service=services.find((entry:any)=>String(entry.id)===itemForm.service_id);
    if(!service) return;
    setSaving(true); setMessage(''); setError('');
    try{
      const response=await api(`/api/repair-orders/${orderId}/items`,{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({kind:'Dịch vụ',service_id:Number(service.id),name:service.name,quantity:Number(itemForm.quantity||1),unit_price:Number(service.price)})
      });
      if(!response.ok){ const info=await readApiError(response); setError(info.message); return; }
      setItemForm({service_id:'',quantity:'1'});
      await load(); onChanged(); setMessage('Đã thêm hạng mục vào phiếu.');
    }catch{ setError('Không thêm được hạng mục.') }
    finally{ setSaving(false) }
  }

  async function removeItem(itemId:number){
    setError('');
    try{
      const response=await api(`/api/repair-orders/${orderId}/items/${itemId}`,{method:'DELETE'});
      if(!response.ok){ const info=await readApiError(response); setError(info.message); return; }
      await load(); onChanged();
    }catch{ setError('Không xóa được hạng mục.') }
  }

  async function saveActualTime(itemId:number, minutes:number){
    setError('');
    try{
      const response=await api(`/api/repair-orders/${orderId}/items/${itemId}/actual-duration`,{
        method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({actual_duration_min:minutes}),
      });
      if(!response.ok){const info=await readApiError(response);setError(info.message);return}
      await load();setMessage('Đã ghi nhận thời gian thực tế cho dịch vụ.');
    }catch{setError('Không lưu được thời gian thực tế.')}
  }

  async function addPart(event:React.FormEvent){
    event.preventDefault();
    if(!partForm.part_id) return;
    setSaving(true); setMessage(''); setError('');
    try{
      const requestKey=`${partForm.part_id}:${partForm.quantity}`;
      const idempotencyKey=partRequestKeys.current[requestKey] || (partRequestKeys.current[requestKey]=`consume:${orderId}:${crypto.randomUUID()}`);
      const response=await api(`/api/repair-orders/${orderId}/parts`,{
        method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':idempotencyKey},
        body:JSON.stringify({part_id:Number(partForm.part_id),quantity:Number(partForm.quantity || 1)})
      });
      if(!response.ok){ const info=await readApiError(response); setError(info.message); return; }
      setPartForm({part_id:'',quantity:'1'});
      delete partRequestKeys.current[requestKey];
      await load(); onChanged(); setMessage('Đã ghi nhận phụ tùng sử dụng và trừ tồn kho.');
    }catch{ setError('Không thêm được phụ tùng.') }
    finally{ setSaving(false) }
  }

  async function removePart(partUseId:number){
    setError('');
    try{
      const response=await api(`/api/repair-orders/${orderId}/parts/${partUseId}`,{method:'DELETE'});
      if(!response.ok){ const info=await readApiError(response); setError(info.message); return; }
      await load(); onChanged();
    }catch{ setError('Không xóa được phụ tùng.') }
  }

  async function createQuote(){
    setSaving(true); setMessage(''); setError('');
    try{
      const serviceIds=selectedServiceIds;
      const partIds=selectedPartIds;
      if(serviceIds.length===0&&partIds.length===0){setError('Cần chọn ít nhất một dịch vụ hoặc phụ tùng từ database.');return}
      const result=await AIService.createQuoteDraft({repair_order_id:orderId,service_item_ids:serviceIds,part_usage_ids:partIds});
      setAiDraft(result.explanation);
      setAiDraftSources(result.sources||[]);
      await load(); onChanged(); setMessage(`Đã tạo ${result.code} ở trạng thái Nháp. Giá và tổng tiền do backend tính từ database.`);
    }catch(err:any){ setError(err.message||'Không tạo được báo giá.') }
    finally{ setSaving(false) }
  }

  async function setQuoteStatus(quoteId:number,status:string){
    setSaving(true); setMessage(''); setError('');
    try{
      const response=await api(`/api/quotes/${quoteId}/status`,{
        method:'PATCH',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({status})
      });
      if(!response.ok){ const info=await readApiError(response); setError(info.message); return; }
      await load(); onChanged();
      setMessage(status === 'Đã duyệt' ? 'Đã duyệt báo giá; phiếu được chuyển sang Đã duyệt nếu đang chờ.' : `Đã cập nhật báo giá: ${status}.`);
    }catch{ setError('Không cập nhật được báo giá.') }
    finally{ setSaving(false) }
  }

  async function draftEstimate(){
    setAiLoading(true); setAiDraft(''); setAiDraftSources([]);
    try{
      const result=await AIService.explainServices(orderId); setAiDraft(result.result); setAiDraftSources(result.sources||[]);
    }catch{ setAiDraft('Không tạo được bản giải thích dịch vụ. Vui lòng thử lại.') }
    setAiLoading(false);
  }

  return <div className="drawer-overlay" onMouseDown={onClose}><aside className="work-drawer repair-work-drawer" onMouseDown={e=>e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Chi tiết phiếu sửa chữa">
    <div className="work-head">
      <div className="work-head-main">
        <div className="work-icon"><ClipboardList size={20}/></div>
        <div><strong>{order?.code || 'Đang tải...'}</strong><small>{order?.plate} {order?.make ? `• ${order.make} ${order.model}` : ''}</small></div>
      </div>
      <button onClick={onClose} aria-label="Đóng"><X/></button>
    </div>

    {!order ? <div className="detail-loading"><i/><span>Đang tải phiếu sửa chữa...</span></div> : <div className="work-body">
      <div className="work-status">
        <div className="work-status-head"><span>Trạng thái công việc</span><OrderStatus code={currentCode}/></div>
        <div className="order-status-steps">
          {ORDER_STEPS.map((code,index)=><div key={code} className={`order-step ${index < branchStepIndex ? 'done' : ''} ${index === branchStepIndex ? 'active' : ''} ${currentCode === 'CANCELLED' ? 'cancelled' : ''}`}>
            <i>{index < branchStepIndex ? '✓' : index + 1}</i><span>{ORDER_STATUS_LABELS[code]}</span>
          </div>)}
        </div>
        {['WAITING_FOR_PARTS','ON_HOLD','CANCELLED'].includes(currentCode) && <div className={`status-branch ${currentCode === 'CANCELLED' ? 'danger' : 'warning'}`}>
          {currentCode === 'WAITING_FOR_PARTS' ? 'Phiếu đang tạm dừng để chờ phụ tùng.' : currentCode === 'ON_HOLD' ? 'Phiếu đang tạm dừng, cần lý do cụ thể.' : `Phiếu đã hủy${order.cancel_reason ? `: ${order.cancel_reason}` : '.'}`}
        </div>}
      </div>

      <div className="work-section">
        <h3>Chuyển trạng thái hợp lệ</h3>
        <p className="work-hint">Mỗi bước được kiểm tra điều kiện nghiệp vụ. Bước chưa đủ điều kiện sẽ hiển thị lý do.</p>
        <div className="workflow-actions">
          {(order.allowed_transitions || []).map((step:any)=><button key={step.code} type="button" disabled={saving || !step.enabled}
            className={`transition-button ${step.code === 'CANCELLED' ? 'danger' : step.code === 'DELIVERED' ? 'deliver' : ''}`}
            onClick={()=>requestTransition(step)}>
            <span>{WORKFLOW_ACTION_LABELS[step.code]||step.label}</span>
            {!step.enabled && <small>{step.blockers.map((blocker:any)=>blocker.message).join(' ')}</small>}
          </button>)}
          {(order.allowed_transitions || []).length === 0 && <p className="work-empty">Phiếu đã ở trạng thái kết thúc, không còn bước chuyển.</p>}
        </div>
        {pendingTransition && <div className="transition-note-box">
          <strong>Nhập lý do: {pendingTransition.label}</strong>
          <textarea rows={2} value={transitionNote} onChange={e=>setTransitionNote(e.target.value)} placeholder="VD: Khách yêu cầu tạm dừng, chờ phụ tùng..."/>
          <div className="work-actions">
            <button type="button" className="btn secondary" onClick={()=>setPendingTransition(null)}>Hủy</button>
            <button type="button" className="btn primary" disabled={saving || transitionNote.trim().length < 2} onClick={()=>runTransition(pendingTransition, transitionNote.trim())}>Xác nhận chuyển</button>
          </div>
        </div>}
      </div>

      <div className="work-meta">
        <div><Users size={15}/><span><small>Khách hàng</small><strong>{order.customer_name || 'Khách lẻ'}</strong></span></div>
        <div><Phone size={15}/><span><small>Liên hệ</small><strong>{order.customer_phone || 'Chưa cập nhật'}</strong></span></div>
        <div><Gauge size={15}/><span><small>Số km tiếp nhận</small><strong>{order.km_in ? `${new Intl.NumberFormat('vi-VN').format(order.km_in)} km` : 'Chưa ghi'}</strong></span></div>
        <div><CalendarDays size={15}/><span><small>Tiếp nhận</small><strong>{formatMoment(order.received_at || order.opened_at)}</strong></span></div>
        <div><CheckCircle2 size={15}/><span><small>Hoàn thành</small><strong>{formatMoment(order.completed_at)}</strong></span></div>
        <div><ArrowUpRight size={15}/><span><small>Bàn giao</small><strong>{formatMoment(order.delivered_at)}</strong></span></div>
      </div>

      <form className="work-section" onSubmit={saveFields}>
        <h3>Thông tin tiếp nhận &amp; kỹ thuật</h3>
        <div className="field-row">
          <label>Kỹ thuật viên phụ trách
            <select disabled={!editable} value={form.technician} onChange={e=>setForm({...form,technician:e.target.value})}>
              <option value="">Chưa phân công</option>
              {[...new Set([...technicians, form.technician].filter(Boolean))].map(name=><option key={name} value={name}>{name}</option>)}
            </select>
          </label>
          <label>Mức ưu tiên
            <select disabled={!editable} value={form.priority} onChange={e=>setForm({...form,priority:e.target.value})}>
              {PRIORITIES.map(level=><option key={level} value={level}>{level}</option>)}
            </select>
          </label>
          <label>Số km tiếp nhận
            <input disabled={!editable} type="number" min="0" placeholder="VD: 42500" value={form.km_in} onChange={e=>setForm({...form,km_in:e.target.value})}/>
          </label>
        </div>
        <label className="full">Tình trạng ban đầu
          <textarea disabled={!editable} rows={2} placeholder="Tình trạng xe khi tiếp nhận..." value={form.initial_condition} onChange={e=>setForm({...form,initial_condition:e.target.value})}/>
        </label>
        <label className="full">Yêu cầu của khách hàng
          <textarea disabled={!editable} rows={2} placeholder="Khách yêu cầu kiểm tra/sửa những gì..." value={form.customer_request} onChange={e=>setForm({...form,customer_request:e.target.value})}/>
        </label>
        <label className="full">Ghi chú kiểm tra kỹ thuật
          <textarea disabled={!editable} rows={2} placeholder="Kết quả kiểm tra, hư hỏng phát hiện..." value={form.inspection_notes} onChange={e=>setForm({...form,inspection_notes:e.target.value})}/>
        </label>
        <label className="full">Ghi chú nội bộ
          <textarea disabled={!editable} rows={2} placeholder="Lưu ý khi sửa chữa..." value={form.note} onChange={e=>setForm({...form,note:e.target.value})}/>
        </label>
        {editable && <div className="work-actions"><button className="btn primary" disabled={saving}><CheckCircle2 size={16}/>{saving ? 'Đang lưu...' : 'Lưu thông tin'}</button></div>}
      </form>
      {['COMPLETED','DELIVERED'].includes(currentCode) && <RepairKnowledgeCasePanel orderId={orderId} canPublish={canApproveQuote}/>}
      {nextStepGuidance&&<div className="workflow-next-hint"><ArrowUpRight size={17}/><div><strong>Bước tiếp theo</strong><p>{nextStepGuidance}</p></div></div>}

      <div className="work-section">
        <h3>Hạng mục dịch vụ</h3>
        {items.length === 0 ? <p className="work-empty">Chưa có hạng mục nào. Thêm dịch vụ hoặc phụ tùng để tính chi phí.</p>
        : <div className="item-table-wrap"><table className="item-table">
            <thead><tr><th>CHỌN BÁO GIÁ</th><th>LOẠI</th><th>TÊN HẠNG MỤC</th><th>SL</th><th>GIÁ TRÊN PHIẾU</th><th>THÀNH TIỀN</th><th>THỰC TẾ</th><th/></tr></thead>
            <tbody>{items.map((item:any)=><tr key={item.id}>
              <td><input type="checkbox" checked={selectedServiceIds.includes(Number(item.id))} disabled={item.kind!=='Dịch vụ'||!item.service_id} title={!item.service_id?'Hạng mục chưa liên kết danh mục dịch vụ':''} onChange={e=>setSelectedServiceIds(current=>e.target.checked?[...current,Number(item.id)]:current.filter(id=>id!==Number(item.id)))}/></td>
              <td><span className={`kind-tag ${item.kind === 'Phụ tùng' ? 'part' : 'service'}`}>{item.kind}</span></td>
              <td><strong>{item.name}</strong></td>
              <td>{item.quantity}</td>
              <td>{money(Number(item.unit_price))}</td>
              <td><strong>{money(Number(item.quantity) * Number(item.unit_price))}</strong></td>
              <td>{item.kind==='Dịch vụ'&&item.service_id?<ActualDurationCell item={item} enabled={canRecordTime} onSave={minutes=>saveActualTime(item.id,minutes)}/>: '—'}</td>
              <td>{editable && <button type="button" className="icon-danger" onClick={()=>removeItem(item.id)} aria-label={`Xóa ${item.name}`}><Trash2 size={15}/></button>}</td>
            </tr>)}</tbody>
          </table></div>}
        {editable && <form className="item-form service-catalog-form" onSubmit={addItem}>
          <select value={itemForm.service_id} onChange={e=>setItemForm({...itemForm,service_id:e.target.value})}>
            <option value="">Chọn dịch vụ từ database</option>{services.map((service:any)=><option key={service.id} value={service.id}>{service.name} • {money(Number(service.price))}</option>)}
          </select>
          <input type="number" min="0.5" step="0.5" value={itemForm.quantity} onChange={e=>setItemForm({...itemForm,quantity:e.target.value})} aria-label="Số lượng"/>
          <button className="btn secondary" disabled={saving||!itemForm.service_id}><Plus size={15}/> Thêm dịch vụ</button>
        </form>}
      </div>

      <div className="work-section">
        <h3>Phụ tùng đã sử dụng</h3>
        {partsUsed.length === 0 ? <p className="work-empty">Chưa ghi nhận phụ tùng. Thêm từ kho để trừ tồn kho và tính vào chi phí.</p>
        : <div className="item-table-wrap"><table className="item-table">
            <thead><tr><th>CHỌN BÁO GIÁ</th><th>MÃ</th><th>TÊN PHỤ TÙNG</th><th>SL</th><th>GIÁ TRÊN PHIẾU</th><th>THÀNH TIỀN</th><th/></tr></thead>
            <tbody>{partsUsed.map((item:any)=><tr key={item.id}>
              <td><input type="checkbox" checked={selectedPartIds.includes(Number(item.id))} onChange={e=>setSelectedPartIds(current=>e.target.checked?[...current,Number(item.id)]:current.filter(id=>id!==Number(item.id)))}/></td>
              <td><small>{item.part_code || '—'}</small></td>
              <td><strong>{item.name}</strong></td>
              <td>{item.quantity}</td>
              <td>{money(Number(item.unit_price))}</td>
              <td><strong>{money(Number(item.line_total || Number(item.quantity) * Number(item.unit_price)))}</strong></td>
              <td>{editable && <button type="button" className="icon-danger" onClick={()=>removePart(item.id)} aria-label={`Xóa ${item.name}`}><Trash2 size={15}/></button>}</td>
            </tr>)}</tbody>
          </table></div>}
        {editable && <form className="item-form part-form" onSubmit={addPart}>
          <select value={partForm.part_id} onChange={e=>setPartForm({...partForm,part_id:e.target.value})}>
            <option value="">Chọn phụ tùng từ kho</option>
            {parts.filter((part:any)=>Number(part.stock) > 0).map((part:any)=><option key={part.id} value={part.id}>{part.name} • {part.code} • tồn {part.stock}</option>)}
          </select>
          <input type="number" min="1" step="1" value={partForm.quantity} onChange={e=>setPartForm({...partForm,quantity:e.target.value})} aria-label="Số lượng phụ tùng"/>
          <button className="btn secondary" disabled={saving || !partForm.part_id}><Plus size={15}/> Thêm phụ tùng</button>
        </form>}
      </div>

      <div className="work-section quote-section">
        <h3>Báo giá</h3>
        <p className="work-hint">Chọn dịch vụ và phụ tùng ở hai bảng phía trên. Phụ tùng tại đây là phụ tùng đã xuất kho trên phiếu; lập báo giá không xuất kho thêm.</p>
        {(selectedServiceIds.length>0||selectedPartIds.length>0)&&<div className="quote-selection-preview"><strong>Đang chọn {selectedServiceIds.length} dịch vụ và {selectedPartIds.length} phụ tùng</strong><span>Tiền công tham khảo: {money(selectedLabor)} • Phụ tùng tham khảo: {money(selectedParts)}{selectedMinutes>0?` • Thời lượng danh mục: ${workTime(selectedMinutes)}`:''}</span><small>Giá và thời lượng chính thức trên bản nháp do backend đọc lại; chưa gồm thời gian chờ phụ tùng.</small></div>}
        {quotes.length === 0 ? <p className="work-empty">Chưa có báo giá. Tạo báo giá nháp từ hạng mục và phụ tùng của phiếu.</p>
        : <div className="quote-list">{quotes.map((quote:any)=><div className="quote-card" key={quote.id}>
            <div><strong>{quote.code}</strong><small>Phiên bản {quote.version} • {formatMoment(quote.created_at)}{quote.estimated_duration_min?` • khoảng ${workTime(Number(quote.estimated_duration_min))}`:''}</small></div>
            <span className={`quote-status ${quote.status === 'Đã duyệt' ? 'approved' : quote.status === 'Từ chối' || quote.status === 'Hết hiệu lực' ? 'expired' : 'pending'}`}>{quote.status}</span>
            <strong className="quote-total">{money(Number(quote.total || 0))}</strong>
            <div className="quote-actions">
              <button type="button" className="row-open" onClick={()=>setQuoteReviewId(quote.id)}>Xem &amp; chỉnh diễn giải</button>
              {quote.status === 'Nháp' && editable && <button type="button" className="row-open" disabled={saving} onClick={()=>setQuoteStatus(quote.id,'Chờ duyệt')}>Gửi duyệt</button>}
              {canApproveQuote && quote.status === 'Chờ duyệt' && !['DELIVERED','CANCELLED','COMPLETED'].includes(currentCode) && <button type="button" className="row-quick" disabled={saving} onClick={()=>setQuoteStatus(quote.id,'Đã duyệt')}>Duyệt báo giá</button>}
            </div>
          </div>)}</div>}
        {editable && <div className="work-actions"><button type="button" className="btn secondary" onClick={createQuote} disabled={saving||!(selectedServiceIds.length||selectedPartIds.length)}><Sparkles size={15}/>{saving?'Đang tạo...':'Tạo báo giá nháp, AI diễn giải'}</button></div>}
        <p className="work-hint">Duyệt báo giá là thao tác nhạy cảm: báo giá phải có hạng mục, tổng tiền &gt; 0 và phiếu đã ở bước “Đã báo giá”.</p>
      </div>

      <div className="work-section">
        <h3>Lịch sử trạng thái</h3>
        {(order.history || []).length === 0 ? <p className="work-empty">Chưa có lịch sử trạng thái.</p>
        : <ol className="order-history">{order.history.map((row:any)=><li key={row.id}>
            <i className={row.to_status === 'CANCELLED' ? 'danger' : row.to_status === 'DELIVERED' || row.to_status === 'COMPLETED' ? 'done' : ''}/>
            <div><strong>{row.to_status_label || ORDER_STATUS_LABELS[row.to_status] || row.to_status}</strong>
              <small>{formatMoment(row.created_at)} • {row.changed_by_name || 'Hệ thống'}</small>
              {row.note && <p>{row.note}</p>}
            </div>
          </li>)}</ol>}
      </div>

      <div className="work-section total-section">
        <div className="total-row"><span>Tạm tính hạng mục &amp; phụ tùng</span><strong>{money(itemTotal)}</strong></div>
        <div className="total-row note"><span>Tổng lưu trên phiếu</span><strong>{money(Number(order.total || 0))}</strong></div>
        <button className="btn ai-button" onClick={draftEstimate} disabled={aiLoading || items.length === 0}>
          <Sparkles size={16}/>{aiLoading ? 'Đang diễn giải...' : 'AI giải thích dịch vụ cho khách'}
        </button>
        {aiDraft && <div className="ai-draft"><div><Sparkles size={15}/><strong>Diễn giải dịch vụ cho khách</strong></div><p>{aiDraft}</p><AISourceReferences sources={aiDraftSources}/><small><CircleAlert size={13}/> AI không chẩn đoán, cam kết hiệu quả hoặc tự đặt điều kiện bảo hành.</small></div>}
      </div>

      {message && <div className="inline-success"><CheckCircle2 size={15}/>{message}</div>}
      {error && <div className="inline-error"><CircleAlert size={15}/>{error}</div>}
    </div>}
    {quoteReviewId!==null&&<QuoteDraftReview quoteId={quoteReviewId} onClose={()=>setQuoteReviewId(null)} onSaved={()=>{load();onChanged()}}/>}
  </aside></div>
}

function QuoteDraftReview({quoteId,onClose,onSaved}:{quoteId:number;onClose:()=>void;onSaved:()=>void}){
  const [quote,setQuote]=useState<any>(null);
  const [note,setNote]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{let active=true;api(`/api/quotes/${quoteId}`).then(async response=>{
    if(!response.ok)throw new Error('Không tải được báo giá.');
    const data=await response.json();if(active){setQuote(data);setNote(data.note||'')}
  }).catch((err:Error)=>{if(active)setError(err.message)});return()=>{active=false}},[quoteId]);
  async function save(){setBusy(true);setError('');try{
    const response=await api(`/api/quotes/${quoteId}/narrative`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({note:note.trim()})});
    if(!response.ok){const issue=await readApiError(response);throw new Error(issue.message)}
    const updated=await response.json();setQuote(updated);setNote(updated.note||'');onSaved();
  }catch(err:any){setError(err.message||'Không lưu được diễn giải.')}finally{setBusy(false)}}
  return <div className="quote-review-overlay" onMouseDown={onClose}><section className="quote-review-panel" role="dialog" aria-modal="true" aria-label="Kiểm tra báo giá nháp" onMouseDown={event=>event.stopPropagation()}>
    <header><div><h2>{quote?.code||'Đang tải báo giá...'}</h2><small>{quote?.status} • Giá được chốt tại thời điểm tạo nháp</small></div><button type="button" onClick={onClose} aria-label="Đóng"><X size={18}/></button></header>
    {error&&<div className="inline-error"><CircleAlert size={15}/>{error}</div>}
    {quote&&<div className="quote-review-content"><table><thead><tr><th>Hạng mục</th><th>SL</th><th>Thành tiền</th></tr></thead><tbody>{(quote.items||[]).map((item:any)=><tr key={item.id}><td>{item.name}</td><td>{item.quantity}</td><td>{money(item.line_total)}</td></tr>)}</tbody></table>
      <EstimatedWorkTime document={quote}/><div className="quote-review-totals"><span>Tạm tính: {money(quote.subtotal)}</span><span>Chiết khấu: {money(quote.discount)}</span><span>Thuế: {money(quote.tax)}</span><strong>Tổng: {money(quote.total)}</strong></div>
      <label>Diễn giải cho khách hàng<textarea rows={9} maxLength={4000} value={note} disabled={quote.status!=='Nháp'} onChange={event=>setNote(event.target.value)}/></label>
      <small>Nội dung AI là bản nháp. Kiểm tra và chỉnh lại trước khi gửi duyệt; sửa hạng mục cần tạo phiên bản báo giá mới.</small>
      {quote.status==='Nháp'&&<button type="button" className="btn primary" disabled={busy||!note.trim()||note===quote.note} onClick={save}>{busy?'Đang lưu...':'Lưu diễn giải'}</button>}
    </div>}
  </section></div>;
}

function NewRepairOrderModal({onClose,onCreated}:{onClose:()=>void,onCreated:()=>void}) {
  const [form,setForm]=useState({plate:'',technician:'',priority:'Bình thường',km_in:'',initial_condition:'',customer_request:'',inspection_notes:'',note:''});
  const [technicians,setTechnicians]=useState<string[]>([]);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{api('/api/repair-orders/options').then(async response=>{if(!response.ok)throw new Error();const data=await response.json();const names=(data.technicians||[]).map((item:any)=>item.full_name);setTechnicians(names);setForm(current=>({...current,technician:current.technician||names[0]||''}))}).catch(()=>setError('Không tải được danh sách kỹ thuật viên từ database.'))},[]);

  async function save(event:React.FormEvent){
    event.preventDefault(); setSaving(true); setError('');
    try{
      const response=await api(`/api/repair-orders`,{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          plate:form.plate.trim().toUpperCase(),technician:form.technician,
          status:'Tiếp nhận',status_code:'RECEIVED',priority:form.priority,
          km_in:form.km_in === '' ? null : Number(form.km_in),
          initial_condition:form.initial_condition,
          customer_request:form.customer_request,
          inspection_notes:form.inspection_notes,
          note:form.note,
        })
      });
      if(!response.ok){ const info=await readApiError(response); setError(info.message); return; }
      onCreated();
    }catch{ setError('Không tạo được phiếu sửa chữa.') }
    finally{ setSaving(false) }
  }

  return <div className="modal-overlay" onMouseDown={onClose}><form className="modal repair-order-modal" onMouseDown={e=>e.stopPropagation()} onSubmit={save} aria-label="Tạo phiếu sửa chữa">
    <div className="modal-head"><div><p className="eyebrow">TIẾP NHẬN XE</p><h2>Tạo phiếu sửa chữa</h2></div><button type="button" onClick={onClose} aria-label="Đóng"><X/></button></div>
    <label>Biển số xe<input required minLength={5} placeholder="VD: 51H-123.45" value={form.plate} onChange={e=>setForm({...form,plate:e.target.value.toUpperCase()})}/></label>
    <div className="field-row">
      <label>Kỹ thuật viên phụ trách<select required value={form.technician} onChange={e=>setForm({...form,technician:e.target.value})}><option value="">Chọn kỹ thuật viên</option>{technicians.map(name=><option key={name} value={name}>{name}</option>)}</select></label>
      <label>Mức ưu tiên<select value={form.priority} onChange={e=>setForm({...form,priority:e.target.value})}>{PRIORITIES.map(level=><option key={level} value={level}>{level}</option>)}</select></label>
    </div>
    <label>Số km tiếp nhận<input required type="number" min="0" placeholder="VD: 42500" value={form.km_in} onChange={e=>setForm({...form,km_in:e.target.value})}/></label>
    <label>Tình trạng ban đầu<textarea required rows={2} placeholder="Tình trạng xe khi tiếp nhận..." value={form.initial_condition} onChange={e=>setForm({...form,initial_condition:e.target.value})}/></label>
    <label>Yêu cầu của khách hàng<textarea required rows={2} placeholder="Khách yêu cầu kiểm tra/sửa những gì..." value={form.customer_request} onChange={e=>setForm({...form,customer_request:e.target.value})}/></label>
    <label>Ghi chú kiểm tra kỹ thuật<textarea rows={2} placeholder="Kết quả kiểm tra ban đầu..." value={form.inspection_notes} onChange={e=>setForm({...form,inspection_notes:e.target.value})}/></label>
    <label>Ghi chú nội bộ<textarea rows={2} placeholder="Lưu ý khi sửa chữa..." value={form.note} onChange={e=>setForm({...form,note:e.target.value})}/></label>
    {error && <div className="inline-error"><CircleAlert size={15}/>{error}</div>}
    <div className="modal-actions"><button type="button" className="btn secondary" onClick={onClose}>Hủy</button><button className="btn primary" disabled={saving}>{saving ? 'Đang tạo...' : 'Tạo phiếu'}</button></div>
  </form></div>
}


function Metric({icon: Icon, label, value, note, color, wide}: any) { return <div className="metric-card"><div className={`metric-icon ${color}`}><Icon size={22}/></div><div className="metric-body"><span>{label}</span><div><strong className={wide?'money-value':''}>{value}</strong>{!wide && <em>xe</em>}</div><small className={color==='green'||color==='violet'?'positive':''}>{note}</small></div><button><ArrowUpRight size={17}/></button></div> }
function Status({text}:{text:string}) { const kind = text.includes('xác nhận')||text.includes('sửa')?'green':text.includes('chờ')||text.includes('Chờ')?'orange':'blue'; return <span className={`status ${kind}`}><i/>{text}</span> }

async function readApiError(response:Response):Promise<{message:string;details:any}>{
  try{
    const data=await response.json();
    return {
      message:data?.error?.message || (typeof data?.detail==='string'?data.detail:'Có lỗi xảy ra, vui lòng thử lại.'),
      details:data?.error?.details || {},
    };
  }catch{ return {message:'Có lỗi xảy ra, vui lòng thử lại.',details:{}} }
}

function appointmentInputValue(value:string){
  return (value||'').replace(' ','T').slice(0,16);
}

function nextAppointmentSlot(){
  const moment=new Date();
  moment.setDate(moment.getDate()+1);
  moment.setHours(9,0,0,0);
  const pad=(value:number)=>String(value).padStart(2,'0');
  return `${moment.getFullYear()}-${pad(moment.getMonth()+1)}-${pad(moment.getDate())}T${pad(moment.getHours())}:${pad(moment.getMinutes())}`;
}

function schedulingTitle(item:any){
  if(item?.kind==='resource_busy') return 'Trùng nguồn lực';
  if(item?.kind==='technician_busy') return 'Trùng lịch kỹ thuật viên';
  if(item?.kind==='technician_working') return 'Kỹ thuật viên đang có phiếu mở';
  if(item?.code==='closed_day') return 'Ngày garage không làm việc';
  if(item?.code==='outside_working_hours') return 'Ngoài giờ làm việc';
  return 'Cảnh báo lịch hẹn';
}

function SchedulingCheck({checking,blocking,warnings}:{checking?:boolean;blocking:any[];warnings:any[]}){
  if(checking) return <div className="slot-check checking"><i/><span>Đang kiểm tra lịch làm việc và phân công...</span></div>;
  if(!blocking.length && !warnings.length) return <div className="slot-check ok"><CheckCircle2 size={15}/><span>Khung giờ hợp lệ, không trùng kỹ thuật viên hoặc nguồn lực.</span></div>;
  return <div className="slot-check-list">
    {blocking.map((item,index)=><div className="slot-item blocking" key={`blocking-${index}`}><CircleAlert size={15}/><div><strong>{schedulingTitle(item)}</strong><p>{item.message}</p></div></div>)}
    {warnings.map((item,index)=><div className="slot-item warning" key={`warning-${index}`}><CircleAlert size={15}/><div><strong>{schedulingTitle(item)}</strong><p>{item.message}</p></div></div>)}
  </div>;
}

function AppointmentModal({onClose,onCreated,appointment}:{onClose:()=>void;onCreated:(x:any)=>void;appointment?:any}) {
  const editing=Boolean(appointment?.id);
  const appointmentUser=sessionUserCache;
  const canAssignAppointment=['Admin','Quản lý','Lễ tân'].includes(appointmentUser?.role);
  const [rules,setRules]=useState<any>(null);
  const [customers,setCustomers]=useState<any[]>([]);
  const [vehicles,setVehicles]=useState<any[]>([]);
  const [loading,setLoading]=useState(true);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');
  const [canForce,setCanForce]=useState(false);
  const [check,setCheck]=useState<any>({blocking:[],warnings:[]});
  const [checking,setChecking]=useState(false);
  const [form,setForm]=useState(()=>({
    customer_id:String(appointment?.customer_id || appointment?.linked_customer_id || ''),
    vehicle_id:appointment?.vehicle_id?String(appointment.vehicle_id):'',
    plate:appointment?.plate || '',
    service:appointment?.service || '',
    appointment_at:appointment?.appointment_at?appointmentInputValue(appointment.appointment_at):nextAppointmentSlot(),
    duration_min:appointment?.duration_min || 60,
    reason:appointment?.reason || '',
    technician:appointment?.technician || '',
    resource_id:appointment?.resource_id?String(appointment.resource_id):'',
  }));

  useEffect(()=>{
    let active=true;
    Promise.all([api('/api/appointments/rules'),api('/api/customers?page_size=200')])
      .then(async ([rulesResponse,customersResponse])=>{
        if(!active) return;
        if(rulesResponse.ok) setRules(await rulesResponse.json());
        if(customersResponse.ok) setCustomers(await readList(customersResponse));
      })
      .catch(()=>{})
      .finally(()=>{ if(active) setLoading(false) });
    return ()=>{ active=false };
  },[]);

  useEffect(()=>{
    if(!form.customer_id){ setVehicles([]); return }
    let active=true;
    api(`/api/customers/${form.customer_id}`)
      .then(async response=>{
        if(!response.ok||!active) return;
        const detail=await response.json();
        if(active) setVehicles(detail.vehicles||[]);
      })
      .catch(()=>{});
    return ()=>{ active=false };
  },[form.customer_id]);

  useEffect(()=>{
    if(editing || !vehicles.length) return;
    setForm(current=>{
      if(current.vehicle_id && vehicles.some(vehicle=>String(vehicle.id)===current.vehicle_id)) return current;
      const first=vehicles[0];
      return {...current,vehicle_id:String(first.id),plate:first.plate||''};
    });
  },[vehicles,editing]);

  useEffect(()=>{
    if(!form.customer_id || !form.appointment_at){ setCheck({blocking:[],warnings:[]}); return }
    let active=true;
    setChecking(true);
    const timer=setTimeout(async()=>{
      try{
        const params=new URLSearchParams({at:form.appointment_at,duration_min:String(form.duration_min||60)});
        if(form.technician) params.set('technician',form.technician);
        if(form.resource_id) params.set('resource_id',form.resource_id);
        if(editing) params.set('exclude_id',String(appointment.id));
        const response=await api(`/api/appointments/conflicts?${params.toString()}`);
        if(!active) return;
        setCheck(response.ok?await response.json():{blocking:[],warnings:[]});
      }catch{}
      if(active) setChecking(false);
    },350);
    return ()=>{ active=false; clearTimeout(timer) };
  },[form.customer_id,form.appointment_at,form.duration_min,form.technician,form.resource_id,editing,appointment?.id]);

  function chooseCustomer(value:string){
    setForm(current=>({...current,customer_id:value,vehicle_id:'',plate:''}));
    if(!value) setVehicles([]);
  }

  async function submit(force=false){
    setError('');
    setCanForce(false);
    if(!form.customer_id){ setError('Vui lòng chọn khách hàng.'); return }
    if(!form.vehicle_id && form.plate.trim().length<5){ setError('Vui lòng chọn xe hoặc nhập biển số (tối thiểu 5 ký tự).'); return }
    if(form.service.trim().length<2){ setError('Vui lòng nhập nội dung dịch vụ.'); return }
    setSaving(true);
    const payload:any={
      customer_id:Number(form.customer_id),
      service:form.service.trim(),
      appointment_at:form.appointment_at,
      duration_min:Number(form.duration_min),
      reason:form.reason,
      technician:form.technician,
    };
    if(form.vehicle_id) payload.vehicle_id=Number(form.vehicle_id);
    else payload.plate=form.plate.trim().toUpperCase();
    if(form.resource_id) payload.resource_id=Number(form.resource_id);
    else if(editing) payload.resource_id=0;
    if(!editing) payload.status='Đang chờ';
    try{
      const response=await api(editing?`/api/appointments/${appointment.id}${force?'?force=true':''}`:'/api/appointments',{
        method:editing?'PATCH':'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),
      });
      if(!response.ok){
        const info=await readApiError(response);
        setError(info.message);
        if(response.status===409){
          setCanForce(true);
          setCheck({blocking:info.details?.blocking||[],warnings:info.details?.warnings||[]});
        }
        setSaving(false);
        return;
      }
      onCreated(await response.json());
    }catch{ setError('Không kết nối được tới hệ thống.'); setSaving(false) }
  }

  return <div className="modal-overlay" onMouseDown={onClose}>
    <form className="modal appointment-form" onMouseDown={event=>event.stopPropagation()} onSubmit={event=>{event.preventDefault();submit(false)}}>
      <div className="modal-head">
        <div><p className="eyebrow">ĐIỀU PHỐI TIẾP NHẬN</p><h2>{editing?'Sửa lịch hẹn':'Tạo lịch hẹn mới'}</h2></div>
        <button type="button" onClick={onClose} aria-label="Đóng"><X/></button>
      </div>
      {!editing && <div className="form-hint"><CircleAlert size={15}/><p>Lịch mới luôn ở trạng thái <strong>Đang chờ</strong>. Chỉ xác nhận sau khi khung giờ và phân công hợp lệ.</p></div>}
      {loading ? <div className="detail-loading"><i/><span>Đang tải lịch làm việc...</span></div> : <>
        <label>Khách hàng<select required value={form.customer_id} onChange={event=>chooseCustomer(event.target.value)}>
          <option value="">Chọn khách hàng...</option>
          {customers.map(customer=><option key={customer.id} value={customer.id}>{customer.name}{customer.phone?` • ${customer.phone}`:''}</option>)}
        </select></label>
        <div className="field-row">
          <label>Xe của khách<select value={form.vehicle_id} onChange={event=>{
            const vehicle=vehicles.find(item=>String(item.id)===event.target.value);
            setForm({...form,vehicle_id:event.target.value,plate:vehicle?.plate||''});
          }}>
            <option value="">Nhập biển số bên dưới</option>
            {vehicles.map(vehicle=><option key={vehicle.id} value={vehicle.id}>{vehicle.plate}{vehicle.make?` • ${vehicle.make} ${vehicle.model||''}`:''}</option>)}
          </select></label>
          <label>Biển số xe<input value={form.plate} disabled={Boolean(form.vehicle_id)} placeholder="VD: 51H-123.45" onChange={event=>setForm({...form,plate:event.target.value.toUpperCase()})}/></label>
        </div>
        <label>Dịch vụ yêu cầu<input required list="appointment-services" value={form.service} onChange={event=>setForm({...form,service:event.target.value})}/>
          <datalist id="appointment-services">{(rules?.services||[]).map((service:any)=><option key={service.id} value={service.name}/>)}</datalist>
        </label>
        <div className="field-row">
          <label>Thời gian hẹn<input required type="datetime-local" value={form.appointment_at} onChange={event=>setForm({...form,appointment_at:event.target.value})}/></label>
          <label>Thời lượng (phút)<input required type="number" min={15} max={1440} step={15} value={form.duration_min} onChange={event=>setForm({...form,duration_min:Number(event.target.value)})}/></label>
        </div>
        {canAssignAppointment&&<div className="field-row">
          <label>Kỹ thuật viên<select value={form.technician} onChange={event=>setForm({...form,technician:event.target.value})}>
            <option value="">Chưa phân công</option>
            {(rules?.technicians||[]).map((name:string)=><option key={name} value={name}>{name}</option>)}
            {form.technician && !(rules?.technicians||[]).includes(form.technician) && <option value={form.technician}>{form.technician}</option>}
          </select></label>
          <label>Nguồn lực<select value={form.resource_id} disabled={!rules?.resources_enabled} onChange={event=>setForm({...form,resource_id:event.target.value})}>
            <option value="">{rules?.resources_enabled?'Chưa xếp nguồn lực':'Chưa cấu hình nguồn lực'}</option>
            {(rules?.resources||[]).map((resource:any)=><option key={resource.id} value={resource.id}>{resource.name} • {resource.kind}</option>)}
          </select></label>
        </div>}
        <label>Lý do / yêu cầu của khách<textarea rows={2} placeholder="VD: Khách báo tiếng kêu ở gầm khi qua ổ gà..." value={form.reason} onChange={event=>setForm({...form,reason:event.target.value})}/></label>
        {rules && <div className="form-meta"><Clock3 size={14}/><span>Lịch làm việc: {rules.working_days_text} • {rules.working_hours?.start} - {rules.working_hours?.end}</span></div>}
        {form.customer_id && <SchedulingCheck checking={checking} blocking={check.blocking||[]} warnings={check.warnings||[]}/>}
        {error && <div className="inline-error form-error"><CircleAlert size={15}/>{error}</div>}
        <div className="modal-actions">
          <button type="button" className="btn secondary" onClick={onClose}>Hủy</button>
          {canForce && <button type="button" className="btn secondary" onClick={()=>submit(true)} disabled={saving}>Vẫn lưu dù trùng lịch</button>}
          <button className="btn primary" disabled={saving}>{saving?'Đang lưu...':editing?'Lưu thay đổi':'Tạo lịch hẹn'}</button>
        </div>
      </>}
    </form>
  </div>
}

function AppointmentDetail({appointment,onClose,onStatusChange,onChanged,initialMode}:{appointment:any,onClose:()=>void,onStatusChange:(id:number,status:string)=>void,onChanged?:()=>void,initialMode?:string}) {
  const id=appointment.id;
  const [data,setData]=useState<any>(appointment);
  const [rules,setRules]=useState<any>(null);
  const [mode,setMode]=useState(initialMode||'');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [blocking,setBlocking]=useState<any[]>([]);
  const [warnings,setWarnings]=useState<any[]>([]);
  const [canForce,setCanForce]=useState(false);
  const [cancelReason,setCancelReason]=useState('');
  const [receive,setReceive]=useState({km_in:'',priority:'Bình thường',technician:appointment?.technician||'',note:''});
  const detailUser=sessionUserCache;
  const canProcessAppointment=['Admin','Quản lý','Lễ tân'].includes(detailUser?.role);

  useEffect(()=>{
    setData(appointment);
    setReceive(current=>({...current,technician:current.technician||appointment?.technician||''}));
  },[appointment]);

  useEffect(()=>{
    api('/api/appointments/rules')
      .then(async response=>{ if(response.ok) setRules(await response.json()) })
      .catch(()=>{});
  },[]);

  async function reload(){
    try{
      const response=await api(`/api/appointments/${id}`);
      if(!response.ok) return;
      const fresh=await response.json();
      setData(fresh);
      onStatusChange(id,fresh.status);
    }catch{}
  }

  async function act(path:string,options:RequestInit={},successMessage=''){
    setBusy(true); setError(''); setCanForce(false); setBlocking([]); setWarnings([]);
    try{
      const response=await api(`/api/appointments/${id}${path}`,options);
      if(!response.ok){
        const info=await readApiError(response);
        setError(info.message);
        if(response.status===409){
          setBlocking(info.details?.blocking||[]);
          setWarnings(info.details?.warnings||[]);
          setCanForce(true);
        }
        setBusy(false);
        return;
      }
      const result=await response.json();
      setBusy(false);
      setMode('');
      if(path==='/receive'){
        setNotice(result.message || `Đã tiếp nhận xe bằng phiếu ${result.code}.`);
        onStatusChange(id,'Đã tiếp nhận');
      }else{
        setNotice(successMessage || 'Đã cập nhật lịch hẹn.');
        onStatusChange(id,result.status||data.status);
      }
      await reload();
      onChanged?.();
    }catch{ setError('Không kết nối được tới hệ thống.'); setBusy(false) }
  }

  const confirmAppointment=(force=false)=>act(`/confirm${force?'?force=true':''}`,{method:'POST'},force?'Đã xác nhận lịch dù có cảnh báo.':'Đã xác nhận lịch hẹn.');
  const restoreAppointment=()=>act('/status',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:'Đang chờ'})},'Đã khôi phục lịch về Đang chờ.');
  function cancelAppointment(){
    if(cancelReason.trim().length<2){ setError('Vui lòng nhập lý do hủy (ít nhất 2 ký tự).'); return }
    act('/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:cancelReason.trim()})},'Đã hủy lịch hẹn.');
  }
  function receiveAppointment(){
    act('/receive',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      km_in:receive.km_in===''?null:Number(receive.km_in),
      priority:receive.priority,
      technician:receive.technician,
      note:receive.note,
    })});
  }

  const when=formatAppointment(data.appointment_at||'');
  const canEdit=canProcessAppointment&&['Đang chờ','Đã xác nhận'].includes(data.status);
  const canCancel=['Đang chờ','Đã xác nhận'].includes(data.status);
  const liveWarnings:any[]=data.warnings||[];
  const blockingItems=blocking.length?blocking:liveWarnings.filter(item=>item.level==='blocking');
  const warningItems=warnings.length?warnings:liveWarnings.filter(item=>item.level!=='blocking');
  const technicianOptions=Array.from(new Set([...(rules?.technicians||[]),receive.technician].filter(Boolean)));

  return <div className="modal-overlay" onMouseDown={onClose}>
    <section className="appointment-detail" onMouseDown={event=>event.stopPropagation()} aria-modal="true" role="dialog" aria-label="Thông tin lịch hẹn">
       <div className="detail-hero"><div className="detail-icon"><CalendarDays/></div><div><p className="eyebrow">THÔNG TIN LỊCH HẸN</p><h2>{data.customer_name}</h2><span>Mã lịch hẹn LH-{String(id).padStart(5,'0')}</span></div><button onClick={onClose} aria-label="Đóng"><X/></button></div>
      {data.loading ? <div className="detail-loading"><i/><span>Đang tải thông tin...</span></div> : <>
        <div className="detail-status">
          <div><span>Trạng thái hiện tại</span><AppointmentStatusBadge text={data.status}/></div>
          <div className="detail-status-note">{data.repair_order_code?`Phiếu ${data.repair_order_code}`:data.status==='Đã tiếp nhận'?'Đã vào xưởng':'Chờ điều phối'}</div>
        </div>
        {notice && <div className="inline-success detail-notice-line"><CheckCircle2 size={15}/>{notice}</div>}
        {error && <div className="inline-error detail-notice-line"><CircleAlert size={15}/>{error}</div>}
        <div className="detail-section"><h3>Thời gian & dịch vụ</h3><div className="detail-grid">
          <Info icon={Clock3} label="Thời gian hẹn" value={`${when.time} • ${when.date}`}/>
          <Info icon={Clock3} label="Thời lượng" value={`${data.duration_min||60} phút`}/>
          <Info icon={Wrench} label="Dịch vụ yêu cầu" value={data.service||'—'}/>
          <Info icon={Users} label="Kỹ thuật viên" value={data.technician||'Chưa phân công'}/>
        </div>
        <div className="detail-inline"><span>Nguồn lực</span><strong>{data.resource_name||'Chưa xếp nguồn lực'}</strong></div>
        {data.reason && <div className="detail-reason"><span>Lý do / yêu cầu của khách</span><p>{data.reason}</p></div>}
        {(data.requested_parts||[]).length>0&&<div className="detail-reason appointment-request-detail"><span>Phụ tùng khách muốn trao đổi</span><ul>{data.requested_parts.map((part:any)=><li key={part.id}><strong>{part.name}</strong> · dự kiến {part.quantity}{part.availability?` · ${part.availability}`:''}</li>)}</ul><p>Chưa xác nhận thay hoặc giữ hàng. Kiểm tra xe và thống nhất phương án với khách trước khi thêm phụ tùng vào phiếu sửa chữa.</p></div>}
        </div>
        <div className="detail-section"><h3>Khách hàng</h3><div className="detail-grid"><Info icon={Users} label="Họ và tên" value={data.customer_name}/><Info icon={CircleDollarSign} label="Số điện thoại" value={data.phone || 'Chưa cập nhật'}/><Info icon={FileText} label="Email" value={data.email || 'Chưa cập nhật'}/></div></div>
        <div className="detail-section"><h3>Thông tin xe</h3><div className="vehicle-summary"><div className="vehicle-visual"><CarFront size={27}/></div><div><strong>{data.make ? `${data.make} ${data.model}` : 'Chưa cập nhật dòng xe'}</strong><span>{data.year || '—'} • Biển số <b>{data.plate}</b></span></div></div></div>
        {(blockingItems.length>0 || warningItems.length>0) && <div className="detail-section"><h3>Kiểm tra lịch & phân công</h3><SchedulingCheck blocking={blockingItems} warnings={warningItems}/></div>}
        {data.repair_order_code && <div className="detail-success"><CheckCircle2 size={17}/><div><strong>Đã tiếp nhận bằng phiếu {data.repair_order_code}</strong><p>Trạng thái phiếu: {data.repair_order_status||'Tiếp nhận'}. Tiếp nhận lại sẽ dùng đúng phiếu này, không tạo bản ghi trùng.</p></div></div>}
        {mode==='cancel' && <div className="detail-section action-panel"><h3>Hủy lịch hẹn</h3><label>Lý do hủy<textarea rows={2} value={cancelReason} onChange={event=>setCancelReason(event.target.value)} placeholder="VD: Khách báo bận, hẹn sang tuần sau..."/></label><div className="action-panel-actions"><button className="btn secondary" onClick={()=>setMode('')}>Đóng</button><button className="btn danger-outline" onClick={cancelAppointment} disabled={busy}>Xác nhận hủy</button></div></div>}
        {mode==='receive' && <div className="detail-section action-panel"><h3>Tiếp nhận xe vào xưởng</h3><p className="action-panel-note">Nếu xe đã có phiếu đang mở, hệ thống dùng lại phiếu đó thay vì tạo phiếu trùng.</p><div className="field-row"><label>Số km hiện tại<input type="number" min={0} value={receive.km_in} onChange={event=>setReceive({...receive,km_in:event.target.value})} placeholder="VD: 61200"/></label><label>Mức ưu tiên<select value={receive.priority} onChange={event=>setReceive({...receive,priority:event.target.value})}>{PRIORITIES.map(priority=><option key={priority}>{priority}</option>)}</select></label></div><label>Kỹ thuật viên<select value={receive.technician} onChange={event=>setReceive({...receive,technician:event.target.value})}><option value="">Chưa phân công</option>{technicianOptions.map((name:string)=><option key={name}>{name}</option>)}</select></label><label>Ghi chú tiếp nhận<textarea rows={2} value={receive.note} onChange={event=>setReceive({...receive,note:event.target.value})} placeholder="Tình trạng xe, yêu cầu thêm..."/></label><div className="action-panel-actions"><button className="btn secondary" onClick={()=>setMode('')}>Đóng</button><button className="btn primary" onClick={receiveAppointment} disabled={busy}>{busy?'Đang tiếp nhận...':'Tiếp nhận xe'}</button></div></div>}
        <div className="detail-actions">
          <button className="btn secondary" onClick={onClose}>Đóng</button>
          {canEdit && <button className="btn secondary" onClick={()=>setMode(mode==='edit'?'':'edit')}><Pencil size={15}/> Sửa</button>}
          {canCancel && <button className="btn secondary danger-text" onClick={()=>setMode(mode==='cancel'?'':'cancel')}>Hủy lịch</button>}
          {canProcessAppointment && data.status==='Đã hủy' && <button className="btn secondary" onClick={restoreAppointment} disabled={busy}>Khôi phục lịch</button>}
          {canProcessAppointment && data.status==='Đang chờ' && <button className="btn secondary" onClick={()=>confirmAppointment(false)} disabled={busy}><CheckCircle2 size={16}/> Xác nhận</button>}
          {canProcessAppointment && canForce && <button className="btn secondary" onClick={()=>confirmAppointment(true)} disabled={busy}>Xác nhận dù trùng lịch</button>}
          {canEdit && <button className="btn primary" onClick={()=>setMode('receive')} disabled={busy}><CarFront size={16}/> Tiếp nhận xe</button>}
        </div>
      </>}
    </section>
    {mode==='edit' && <div onMouseDown={event=>event.stopPropagation()}><AppointmentModal appointment={data} onClose={()=>setMode('')} onCreated={async()=>{ setMode(''); setNotice('Đã lưu thay đổi lịch hẹn.'); await reload(); onChanged?.() }}/></div>}
  </div>
}

function Info({icon:Icon,label,value}:{icon:any,label:string,value:string}) { return <div className="info-item"><span><Icon size={17}/></span><div><small>{label}</small><strong>{value}</strong></div></div> }

function AuthScreen({onAuthenticated}:{onAuthenticated:(payload:any)=>void}) {
  const [mode,setMode]=useState<'login'|'register'>('login');
  const [showPassword,setShowPassword]=useState(false);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const [demoAccounts,setDemoAccounts]=useState<any[]>([]);
  const [form,setForm]=useState({full_name:'',email:'',password:'',confirm:''});
  useEffect(()=>{api('/api/auth/demo-accounts').then(async response=>{if(response.ok)setDemoAccounts(await response.json())}).catch(()=>{})},[]);
  async function submit(e:React.FormEvent){
    e.preventDefault(); setError('');
    if(mode==='register' && form.password!==form.confirm){setError('Mật khẩu xác nhận không khớp.');return}
    setLoading(true);
    try{
      const body=mode==='login'?{email:form.email,password:form.password}:{full_name:form.full_name,email:form.email,password:form.password};
      const response=await api(`/api/auth/${mode}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const result=await response.json();
      if(!response.ok) throw new Error(result.detail||'Không thể xác thực tài khoản.');
      onAuthenticated(result);
    }catch(err:any){setError(err.message==='Failed to fetch'?'Không thể kết nối máy chủ. Vui lòng kiểm tra backend.':err.message)}finally{setLoading(false)}
  }
  function switchMode(next:'login'|'register'){setMode(next);setError('');setForm({full_name:'',email:'',password:'',confirm:''})}
  function fillDemo(account:any){setMode('login');setError('');setForm({full_name:'',email:account.email,password:account.password,confirm:''});setShowPassword(false)}
  return <main className="auth-page">
    <section className="auth-showcase">
      <div className="auth-showcase-grid" aria-hidden="true"/>
      <div className="auth-brand"><span><Wrench size={24}/></span><strong>ThreeH <i>Workshop</i></strong></div>
      <div className="auth-showcase-content">
        <div className="auth-copy">
          <span className="auth-kicker"><Sparkles size={14}/> SMART AUTOMOTIVE WORKSHOP MANAGEMENT</span>
          <h1>Quản lý garage.<br/><em>Vận hành thông minh.</em></h1>
          <strong className="auth-highlight">Mọi quy trình, trên một nền tảng.</strong>
          <p>Quản lý lịch hẹn, sửa chữa, phụ tùng, doanh thu và chăm sóc khách hàng tập trung trong một hệ thống duy nhất.</p>
        </div>
        <div className="workshop-visual" aria-label="Minh họa giao diện quản lý garage thông minh">
          <div className="visual-heading"><div><span>WORKSHOP OVERVIEW</span><strong>Trung tâm vận hành</strong></div><small>MINH HỌA</small></div>
          <div className="visual-workflow">
            <div><span><CalendarDays/></span><small>Lịch hẹn</small></div><i/>
            <div><span><Wrench/></span><small>Sửa chữa</small></div><i/>
            <div><span><CheckCircle2/></span><small>Hoàn tất</small></div>
          </div>
          <div className="visual-modules">
            <div><Package/><span><small>PHỤ TÙNG</small><strong>Quản lý tập trung</strong></span></div>
            <div><BarChart3/><span><small>DOANH THU</small><strong>Theo dõi trực quan</strong></span></div>
          </div>
          <div className="visual-ai"><Bot/><span><small>TRỢ LÝ AI THREEH</small><strong>Tra cứu theo quyền truy cập</strong></span><Sparkles/></div>
        </div>
        <div className="auth-benefits">
          <div><CheckCircle2/><span><strong>Quy trình rõ ràng</strong><small>Theo dõi lịch hẹn và tiến độ sửa chữa tập trung.</small></span></div>
          <div><ShieldCheck/><span><strong>Dữ liệu an toàn</strong><small>Phân quyền truy cập theo vai trò nhân viên.</small></span></div>
          <div><Bot/><span><strong>Trợ lý AI thông minh</strong><small>Hỗ trợ tra cứu và tư vấn theo thông tin được phép truy cập.</small></span></div>
        </div>
      </div>
      <div className="auth-quote"><Database size={18}/><p>Dữ liệu nghiệp vụ được đồng bộ từ database qua API.</p></div>
    </section>
    <section className="auth-panel"><div className="auth-box"><div className="mobile-auth-brand"><Wrench/><strong>ThreeH <span>Workshop</span></strong></div><div className="auth-heading"><p>{mode==='login'?'CHÀO MỪNG TRỞ LẠI':'TẠO TÀI KHOẢN MỚI'}</p><h2>{mode==='login'?'Đăng nhập hệ thống':'Đăng ký nhân viên'}</h2><span>{mode==='login'?'Nhập thông tin để tiếp tục quản lý garage.':'Tài khoản mới sẽ được cấp quyền Lễ tân.'}</span></div><div className="auth-tabs"><button className={mode==='login'?'active':''} onClick={()=>switchMode('login')}>Đăng nhập</button><button className={mode==='register'?'active':''} onClick={()=>switchMode('register')}>Đăng ký</button></div><form className="auth-form" onSubmit={submit}>
      {mode==='register'&&<label>Họ và tên<div><Users size={17}/><input required minLength={2} autoComplete="name" placeholder="Nguyễn Văn An" value={form.full_name} onChange={e=>setForm({...form,full_name:e.target.value})}/></div></label>}
      <label>Email<div><Mail size={17}/><input required type="email" autoComplete="email" placeholder="ten@garage.vn" value={form.email} onChange={e=>setForm({...form,email:e.target.value})}/></div></label>
      <label>Mật khẩu<div><LockKeyhole size={17}/><input required minLength={8} type={showPassword?'text':'password'} autoComplete={mode==='login'?'current-password':'new-password'} placeholder="Tối thiểu 8 ký tự" value={form.password} onChange={e=>setForm({...form,password:e.target.value})}/><button type="button" onClick={()=>setShowPassword(!showPassword)} aria-label={showPassword?'Ẩn mật khẩu':'Hiện mật khẩu'}>{showPassword?<EyeOff size={17}/>:<Eye size={17}/>}</button></div></label>
      {mode==='register'&&<label>Xác nhận mật khẩu<div><LockKeyhole size={17}/><input required minLength={8} type={showPassword?'text':'password'} autoComplete="new-password" placeholder="Nhập lại mật khẩu" value={form.confirm} onChange={e=>setForm({...form,confirm:e.target.value})}/></div></label>}
      {error&&<div className="auth-error"><CircleAlert size={16}/><span>{error}</span></div>}
      {mode==='login'&&<div className="auth-options"><label><input type="checkbox"/> Ghi nhớ đăng nhập</label><button type="button">Quên mật khẩu?</button></div>}
      <button className="auth-submit" disabled={loading}>{loading?<><i/>Đang xử lý...</>:<>{mode==='login'?'Đăng nhập':'Tạo tài khoản'}<ArrowUpRight size={18}/></>}</button>
    </form>{mode==='login'&&demoAccounts.length>0&&<div className="demo-accounts"><div className="demo-title"><span>TÀI KHOẢN THEO VAI TRÒ</span><small>Nhấn để tự điền thông tin đăng nhập</small></div><div className="demo-list">{demoAccounts.map(account=><button key={account.email} type="button" onClick={()=>fillDemo(account)}><span className={`demo-avatar role-${demoRoleClass(account.role)}`}>{demoInitials(account.role)}</span><span className="demo-info"><strong>{account.role}</strong><small>{account.email}</small></span><span className="demo-enter">Điền thông tin<ArrowUpRight size={14}/></span></button>)}</div></div>}<p className="auth-footer">Bằng việc tiếp tục, bạn đồng ý với <a>Điều khoản sử dụng</a> và <a>Chính sách bảo mật</a>.</p></div></section>
  </main>
}

function demoInitials(role:string){return role.split(' ').map(word=>word[0]).join('').slice(0,2).toUpperCase()}
function demoRoleClass(role:string){return role.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\s+/g,'-')}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);

