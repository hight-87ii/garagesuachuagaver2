const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8014';

export type AIResult = {
  result: string;
  is_draft: boolean;
  status: 'success' | 'fallback' | 'no_data' | 'clarification' | 'safety' | 'error';
  no_data?: boolean;
  source_count?: number;
  sources?: {type:string;id:number|null;label:string;date?:string;url?:string|null}[];
  suggested_items?: {kind:'service'|'part';id:number;name:string;price:number;availability?:string}[];
  missing_data?: string[];
  history_summary?: Record<string, unknown>;
  analytics?: Record<string, unknown>;
  data_status?: 'sourced' | 'partial' | 'no_data' | 'error';
};

export type AIConversation = {
  id: number; title: string; status: 'active' | 'archived'; vehicle_id: number | null;
  vehicle_plate?: string | null; created_at: string; updated_at: string;
};
export type AIMessage = {
  id: number; role: 'user' | 'assistant'; content: string;
  status: 'pending' | 'completed' | 'failed'; request_id: string | null;
  created_at: string; result: AIResult | null;
};
export type AIConversationDetail = AIConversation & { messages: AIMessage[] };
export type AIMessageReply = {
  conversation_id: number; user_message: AIMessage; assistant_message: AIMessage; result: AIResult;
};

async function conversationRequest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/v1/ai/conversations${path}`, {
      method,
      headers: { ...(body ? { 'Content-Type': 'application/json' } : {}),
        Authorization: `Bearer ${sessionStorage.getItem('garage_token') || ''}` },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
  } catch {
    throw new Error('Không kết nối được backend. Tin nhắn chưa được xác nhận; hãy thử lại.');
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status===404 && (payload?.detail==='Not Found'||!payload))
      throw new Error('Backend chưa nạp API hội thoại mới; hãy khởi động lại backend.');
    throw new Error(payload?.error?.message || payload?.detail || 'Không xử lý được cuộc trò chuyện.');
  }
  return payload as T;
}

async function post<T = AIResult>(path: string, body?: unknown): Promise<T> {
  const token = sessionStorage.getItem('garage_token');
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/v1${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error('Không kết nối được máy chủ GarageAI. Vui lòng kiểm tra backend đang chạy và thử lại.');
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 404 && path === '/ai/assistant/chat' &&
        (payload?.detail === 'Not Found' || !payload)) {
      throw new Error('Backend chưa có chức năng trò chuyện. Vui lòng khởi động lại backend rồi thử lại.');
    }
    throw new Error(payload?.detail?.message || payload?.detail || 'Dịch vụ AI không phản hồi.');
  }
  return payload;
}

// Mọi component chỉ gọi facade này; không biết hoặc gọi trực tiếp nhà cung cấp AI.
export const AIService = {
  listConversations() { return conversationRequest<AIConversation[]>(''); },
  getConversation(id: number) { return conversationRequest<AIConversationDetail>(`/${id}`); },
  createConversation(input: { client_key: string; vehicle_id?: number; plate?: string }) {
    return conversationRequest<AIConversation>('', 'POST', input);
  },
  deleteConversation(id: number) { return conversationRequest<{id:number;deleted:boolean}>(`/${id}`, 'DELETE'); },
  sendConversationMessage(id: number, input: { request_id: string; question: string }) {
    return conversationRequest<AIMessageReply>(`/${id}/messages`, 'POST', input);
  },
  chat(input: { question: string; vehicle_id?: number; plate?: string; history?: { role: 'user' | 'assistant'; text: string }[] }) {
    return post('/ai/assistant/chat', input);
  },
  summarizeRepairHistory(selector: { vehicle_id?: number; plate?: string }) {
    return post('/ai/repair-history-summary', selector);
  },
  createEstimateDraft(repairOrderId: number) {
    return post(`/ai/repair-orders/${repairOrderId}/estimate-draft`);
  },
  explainServices(repairOrderId: number, selector: { quote_id?: number; quote_item_id?: number } = {}) {
    return post(`/ai/repair-orders/${repairOrderId}/service-explanation`, selector);
  },
  explainServicesByCode(orderCode: string) {
    return post(`/ai/service-explanations/${encodeURIComponent(orderCode)}`, {});
  },
  explainInvoiceServices(invoiceId: number) {
    return post(`/ai/invoices/${invoiceId}/service-explanation`);
  },
  askInvoiceFollowUp(invoiceId: number, question: string, history: { role: 'user' | 'assistant'; text: string }[] = []) {
    return post(`/ai/invoices/${invoiceId}/service-explanation/follow-up`, { question, history });
  },
  askServiceFollowUp(
    orderCode: string,
    question: string,
    history: { role: 'user' | 'assistant'; text: string }[] = [],
  ) {
    return post(`/ai/service-explanations/${encodeURIComponent(orderCode)}/follow-up`, { question, history });
  },
  createQuoteDraft(input: { repair_order_id: number; service_item_ids: number[]; part_usage_ids: number[] }) {
    return post<AIQuoteDraftResult>('/quotes/ai-draft', input);
  },
};

export type AIQuoteDraftResult = {
  id: number;
  code: string;
  status: 'Nháp';
  subtotal: number;
  labor_subtotal: number;
  parts_subtotal: number;
  discount: number;
  tax: number;
  total: number;
  estimated_duration_min?: number | null;
  ai_status: string;
  explanation: string;
  sources?: {type:string;id:number|null;label:string;date?:string}[];
};
