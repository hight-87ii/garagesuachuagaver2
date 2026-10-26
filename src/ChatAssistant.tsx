import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ArrowUpRight, Bot, CalendarPlus, CarFront, CircleAlert, Database, MessageSquarePlus, PackageSearch, Send, ShieldCheck, Sparkles, Trash2 } from 'lucide-react';
import { AIService, type AIConversation, type AIMessage, type AIResult } from './services/aiService';
import type { AppointmentSelection } from './AppointmentCreateModal';
import AISourceReferences from './AISourceReferences';

type Vehicle = { id: number; make: string; model: string; plate: string; fuel_type?: string };
type User = { id: number; role: string };
const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8010';
function savedConversationId(userId:number){try{return Number(localStorage.getItem(`garage_ai_conversation_${userId}`))||null}catch{return null}}

function AssistantAppointmentItems({items,vehicleId,onAdd}:{items:NonNullable<AIResult['suggested_items']>;vehicleId:string;onAdd:(selection:AppointmentSelection)=>void}){
  if(!items.length)return null;
  return <div className="assistant-appointment-items"><strong>Hạng mục được nhắc tới trong danh mục</strong>
    {items.map(item=><div key={`${item.kind}-${item.id}`}><span>{item.name}<small>{item.kind==='part'?'Phụ tùng':'Dịch vụ'} · {new Intl.NumberFormat('vi-VN').format(item.price)} ₫{item.availability?` · ${item.availability}`:''}</small></span><button type="button" disabled={!vehicleId} onClick={()=>onAdd({vehicle_id:Number(vehicleId),kind:item.kind,id:item.id,name:item.name})}><CalendarPlus size={14}/> Đưa hạng mục này vào lịch hẹn</button></div>)}
    {!vehicleId&&<small>Chọn xe trong tài khoản để đưa hạng mục vào lịch hẹn.</small>}
    <small>Chỉ là yêu cầu ban đầu; kỹ thuật viên xác nhận sau khi kiểm tra xe.</small>
  </div>;
}

export default function ChatAssistant({user,compact=false,onAddToAppointment,onOpenAppointment}:{user:User;compact?:boolean;onAddToAppointment?:(selection:AppointmentSelection)=>void;onOpenAppointment?:(id:number)=>void}){
  const customer=user.role==='Khách hàng';
  const [vehicles,setVehicles]=useState<Vehicle[]>([]);
  const [vehicleId,setVehicleId]=useState('');
  const [plate,setPlate]=useState('');
  const [conversations,setConversations]=useState<AIConversation[]>([]);
  const [activeId,setActiveId]=useState<number|null>(null);
  const [turns,setTurns]=useState<AIMessage[]>([]);
  const [question,setQuestion]=useState('');
  const [loadingList,setLoadingList]=useState(true);
  const [loadingThread,setLoadingThread]=useState(false);
  const [vehicleLoading,setVehicleLoading]=useState(customer);
  const [sending,setSending]=useState(false);
  const [deletingId,setDeletingId]=useState<number|null>(null);
  const [confirmId,setConfirmId]=useState<number|null>(null);
  const [error,setError]=useState('');
  const [hydrated,setHydrated]=useState(false);
  const draftKey=useRef(crypto.randomUUID());
  const remembered=useRef<number|null>(savedConversationId(user.id));
  const threadRef=useRef<HTMLDivElement>(null);

  useLayoutEffect(()=>{
    const thread=threadRef.current;
    if(thread)thread.scrollTop=thread.scrollHeight;
  },[activeId,turns,loadingThread,sending]);

  useEffect(()=>{
    let active=true;
    AIService.listConversations().then(list=>{
      if(!active)return;
      setConversations(list);
      const restored=list.find(item=>item.id===remembered.current);
      setActiveId(restored?.id||list[0]?.id||null);
    }).catch(err=>{if(active)setError(err.message)}).finally(()=>{if(active){setLoadingList(false);setHydrated(true)}});
    return()=>{active=false};
  },[user.id]);

  useEffect(()=>{
    if(!customer)return;
    let active=true;
    fetch(`${API}/api/v1/my-vehicles`,{headers:{Authorization:`Bearer ${sessionStorage.getItem('garage_token')||''}`}})
      .then(async response=>{if(!response.ok)throw new Error('Không tải được hồ sơ xe.');return response.json()})
      .then(data=>{if(!active)return;const list=(data.vehicles||[]) as Vehicle[];setVehicles(list);
        setVehicleId(current=>current|| (list.length===1?String(list[0].id):''))})
      .catch(err=>{if(active)setError(err.message)})
      .finally(()=>{if(active)setVehicleLoading(false)});
    return()=>{active=false};
  },[customer,user.id]);

  useEffect(()=>{
    if(!hydrated)return;
    const key=`garage_ai_conversation_${user.id}`;
    try{if(activeId)localStorage.setItem(key,String(activeId));else localStorage.removeItem(key)}catch{}
  },[activeId,hydrated,user.id]);

  useEffect(()=>{
    if(!activeId){setTurns([]);return}
    let active=true;setLoadingThread(true);setError('');
    AIService.getConversation(activeId).then(data=>{
      if(!active)return;
      setTurns(data.messages);
      setVehicleId(data.vehicle_id?String(data.vehicle_id):'');
      if(!customer)setPlate(data.vehicle_plate||'');
    }).catch(err=>{if(active)setError(err.message)})
      .finally(()=>{if(active)setLoadingThread(false)});
    return()=>{active=false};
  },[activeId,user.id,customer]);

  function newConversation(){
    if(sending)return;
    draftKey.current=crypto.randomUUID();setActiveId(null);setTurns([]);setQuestion('');setError('');
  }
  function changeVehicle(value:string){
    setVehicleId(value);newConversation();
  }
  function changePlate(value:string){
    setPlate(value.toUpperCase());newConversation();
  }

  async function send(text=question,retry?:AIMessage){
    const prompt=text.trim();if(!prompt||sending||loadingThread)return;
    const requestId=retry?.request_id||crypto.randomUUID();
    const tempId=-Date.now();let conversationId=activeId;
    if(!retry)setTurns(current=>[...current,{id:tempId,role:'user',content:prompt,status:'pending',request_id:requestId,created_at:new Date().toISOString(),result:null}]);
    setQuestion('');setError('');setSending(true);
    try{
      if(!conversationId){
        const created=await AIService.createConversation({client_key:draftKey.current,
          ...(customer?(vehicleId?{vehicle_id:Number(vehicleId)}:{}):(plate.trim()?{plate:plate.trim()}:{}))});
        conversationId=created.id;
      }
      const reply=await AIService.sendConversationMessage(conversationId,{request_id:requestId,question:prompt});
      setTurns(current=>[...current.filter(turn=>turn.id!==tempId&&turn.request_id!==requestId),
        reply.user_message,reply.assistant_message]);
      if(activeId!==conversationId)setActiveId(conversationId);
      const updated=await AIService.listConversations().catch(()=>null);
      if(updated)setConversations(updated);
    }catch(err){
      setError(err instanceof Error?err.message:'Không gửi được câu hỏi.');
      if(conversationId){
        if(activeId!==conversationId)setActiveId(conversationId);
        try{const data=await AIService.getConversation(conversationId);setTurns(data.messages);
          setConversations(await AIService.listConversations())}catch{setTurns(current=>current.filter(turn=>turn.id!==tempId))}
      }else setTurns(current=>current.filter(turn=>turn.id!==tempId));
      if(!retry)setQuestion(prompt);
    }finally{setSending(false)}
  }

  async function deleteConversation(conversation:AIConversation){
    setDeletingId(conversation.id);setError('');
    try{
      await AIService.deleteConversation(conversation.id);
      const remaining=conversations.filter(item=>item.id!==conversation.id);
      setConversations(remaining);
      setConfirmId(null);
      if(activeId===conversation.id){setActiveId(remaining[0]?.id||null);setTurns([]);draftKey.current=crypto.randomUUID()}
    }catch(err){setError(err instanceof Error?err.message:'Không xóa được cuộc trò chuyện.')}finally{setDeletingId(null)}
  }

  return <div className={`assistant-chat ${compact?'compact':''}`}>
    <section className="assistant-conversation-list" aria-label="Lịch sử trò chuyện">
      <div className="assistant-conversation-heading"><strong>Cuộc trò chuyện</strong><button type="button" onClick={newConversation} disabled={sending} aria-label="Tạo cuộc trò chuyện mới"><MessageSquarePlus size={16}/> Mới</button></div>
      {loadingList?<small>Đang tải lịch sử...</small>:conversations.length===0?<small>Chưa có cuộc trò chuyện nào.</small>
      :<div className="assistant-conversation-items">{conversations.map(item=><div className={`assistant-conversation-row ${activeId===item.id?'active':''}`} key={item.id}>
        <button type="button" className="assistant-conversation-open" onClick={()=>setActiveId(item.id)} disabled={sending} aria-current={activeId===item.id?'true':undefined}><span>{item.title}</span><small>{item.vehicle_plate||'Hỏi chung'}</small></button>
        <button type="button" className="assistant-conversation-delete" aria-label={`Xóa ${item.title}`} title="Xóa cuộc trò chuyện" disabled={deletingId!==null||sending} onClick={()=>setConfirmId(item.id)}><Trash2 size={15}/></button>
      </div>)}</div>}
    </section>
    <div className="assistant-context"><label htmlFor={compact?'drawer-ai-vehicle':'center-ai-vehicle'}><CarFront size={16}/> {customer?'Xe trong tài khoản':'Biển số xe (không bắt buộc)'}</label>
      {customer?<select id={compact?'drawer-ai-vehicle':'center-ai-vehicle'} value={vehicleId} disabled={vehicleLoading||sending||loadingThread} onChange={event=>changeVehicle(event.target.value)}>
        <option value="">{vehicleLoading?'Đang tải xe...':'Hỏi chung / giá linh kiện'}</option>
        {vehicles.map(vehicle=><option key={vehicle.id} value={vehicle.id}>{vehicle.make} {vehicle.model} · {vehicle.plate}{vehicle.fuel_type?` · ${vehicle.fuel_type}`:''}</option>)}
      </select>:<input id={compact?'drawer-ai-vehicle':'center-ai-vehicle'} value={plate} disabled={sending||loadingThread} onChange={event=>changePlate(event.target.value)} placeholder="Nhập biển số để hỏi theo hồ sơ"/>}
    </div>
    <div className="assistant-thread" ref={threadRef} role="log" aria-live="polite">
      {loadingThread?<div className="assistant-bubble assistant"><Bot size={17}/><p>Đang mở cuộc trò chuyện...</p></div>:!turns.length?<div className="assistant-intro"><span className="assistant-spark"><Sparkles size={24}/></span><h3>Hỏi trợ lý ThreeH</h3><p>Hỏi cụ thể điều bạn cần biết. Trợ lý sẽ giữ ngữ cảnh trong cuộc trò chuyện này.</p><div className="assistant-suggestions">
         {[...(['Admin','Quản lý','Lễ tân','Khách hàng'].includes(user.role)?['Có bao nhiêu lịch hẹn chưa xác nhận?', 'Ngày mai có những lịch hẹn nào chưa xác nhận?']:[]),...(['Admin','Quản lý','Thu ngân','Khách hàng'].includes(user.role)?['Liệt kê hóa đơn trên 10 triệu đồng.', 'Tìm hóa đơn còn nợ trên 5 triệu đồng.']:[]),'Ai sở hữu xe Hyundai Accent?', 'Khách hàng nào có 2 xe?', 'Giá vệ sinh xe và mất bao lâu?', 'Xe tôi bị ngập nước, cần làm gì trước?', 'Xe này đã sửa những gì?'].map(text=><button type="button" key={text} onClick={()=>send(text)} disabled={sending||loadingList}><PackageSearch size={14}/>{text}</button>)}
      </div></div>:turns.map(turn=><div key={turn.id} className={`assistant-bubble ${turn.role}`}>
        {turn.role==='assistant'&&<Bot size={17} aria-hidden="true"/>}
         <div><p>{turn.content}</p>
           {turn.role==='assistant'&&turn.result?.sources?.some(source=>source.type==='appointment')&&onOpenAppointment&&<div className="assistant-appointment-links" aria-label="Mở lịch hẹn">
             {turn.result.sources.filter(source=>source.type==='appointment'&&source.id!=null).map(source=><button type="button" key={source.id} onClick={()=>onOpenAppointment(source.id!)} aria-label={`Mở lịch hẹn ${source.label}`}>{source.label} <ArrowUpRight size={14} aria-hidden="true"/></button>)}
           </div>}
          {turn.status==='failed'&&<button type="button" className="assistant-retry" disabled={sending} onClick={()=>send(turn.content,turn)}>Gửi lại tin nhắn</button>}
          {turn.status==='pending'&&<><small>Đang chờ xử lý...</small>{turn.id>0&&<button type="button" className="assistant-retry" disabled={sending} onClick={()=>send(turn.content,turn)}>Kiểm tra / thử lại</button>}</>}
           {turn.result&&<>{Boolean(turn.result.sources?.some(source=>source.type!=='appointment'))&&<details className="assistant-sources"><summary>Xem nguồn đối chiếu</summary><AISourceReferences sources={turn.result.sources?.filter(source=>source.type!=='appointment')}/>{customer&&onAddToAppointment&&<AssistantAppointmentItems items={turn.result.suggested_items||[]} vehicleId={vehicleId} onAdd={onAddToAppointment}/>}</details>}
            <small><Database size={12}/>{turn.result.status==='safety'?'Hướng dẫn an toàn chung':turn.result.status==='clarification'?'Cần bạn bổ sung thông tin':turn.result.no_data?'Chưa đủ dữ liệu':turn.result.status==='success'?'AI đã trả lời':'Dữ liệu hệ thống'}</small></>}
        </div></div>)}
      {sending&&<div className="assistant-bubble assistant"><Bot size={17}/><p>Đang đối chiếu dữ liệu...</p></div>}
    </div>
    <div className="assistant-compose">
      {error&&<p className="assistant-error" role="alert"><CircleAlert size={15}/>{error}</p>}
      <div className="assistant-compose-row"><input aria-label="Câu hỏi cho trợ lý AI" value={question} maxLength={500} disabled={sending||loadingList||loadingThread} onChange={event=>setQuestion(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();send()}}} placeholder="Hỏi tiếp trong cuộc trò chuyện này..."/><button type="button" onClick={()=>send()} disabled={sending||loadingList||loadingThread||question.trim().length<2} aria-label="Gửi câu hỏi"><Send size={19}/></button></div>
      <small><ShieldCheck size={13}/> Nội dung được lưu theo tài khoản; giá và tương thích phải đối chiếu dữ liệu garage.</small>
    </div>
    {confirmId!==null&&<div className="assistant-confirm-overlay" role="presentation"><section className="assistant-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="assistant-delete-heading">
      <h3 id="assistant-delete-heading">Xóa cuộc trò chuyện?</h3><p>Chỉ xóa “{conversations.find(item=>item.id===confirmId)?.title}” và các tin nhắn trong cuộc trò chuyện này. Các cuộc trò chuyện khác vẫn được giữ.</p>
      {error&&<p className="assistant-error" role="alert">{error}</p>}
      <div><button type="button" className="btn secondary" autoFocus disabled={deletingId!==null} onClick={()=>setConfirmId(null)}>Hủy</button><button type="button" className="btn danger" disabled={deletingId!==null} onClick={()=>{const selected=conversations.find(item=>item.id===confirmId);if(selected)deleteConversation(selected)}}>{deletingId!==null?'Đang xóa...':'Xóa cuộc trò chuyện'}</button></div>
    </section></div>}
  </div>;
}
