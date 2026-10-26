import React, { useEffect, useRef, useState } from 'react';
import { Bot, CircleAlert, Send, ShieldCheck, Sparkles } from 'lucide-react';
import { AIService } from './services/aiService';
import AISourceReferences, { type AISource } from './AISourceReferences';

type ChatTurn = { role: 'user' | 'assistant' | 'error'; text: string; status?: string; sources?: AISource[] };

const QUICK_QUESTIONS = [
  'Vì sao cần làm dịch vụ này?',
  'Chi phí gồm những gì?',
  'Mỗi hạng mục có công dụng gì?',
  'Những công việc nào đã được xác nhận hoàn thành?',
  'Có thông tin bảo hành không?',
  'Còn thiếu thông tin gì để xác nhận báo giá?',
  'Có hạng mục nào cần kỹ thuật viên kiểm tra lại không?',
];

export default function ServiceFollowUpChat({ orderCode, invoiceId }: { orderCode: string; invoiceId?: number }) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [question, setQuestion] = useState('');
  const [sending, setSending] = useState(false);
  const sectionRef = useRef<HTMLElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Khi bản giải thích vừa hiện ra, đưa ô chat vào vùng nhìn thấy ngay dưới câu trả lời.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const section = sectionRef.current;
      if (!section) return;
      const rect = section.getBoundingClientRect();
      if (rect.top > window.innerHeight - 80 || rect.bottom > window.innerHeight) {
        section.scrollIntoView({ behavior: 'auto', block: 'center' });
      }
    }, 150);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    const thread = threadRef.current;
    if (thread) thread.scrollTop = thread.scrollHeight;
  }, [turns, sending]);

  async function send(text: string) {
    const clean = text.trim();
    if (!clean || sending) return;
    const history = turns
      .filter(turn => turn.role !== 'error')
      .slice(-8)
      .map(turn => ({ role: turn.role === 'assistant' ? 'assistant' as const : 'user' as const, text: turn.text }));
    setTurns(current => [...current, { role: 'user', text: clean }]);
    setQuestion('');
    setSending(true);
    try {
      const answer = invoiceId
        ? await AIService.askInvoiceFollowUp(invoiceId, clean, history)
        : await AIService.askServiceFollowUp(orderCode, clean, history);
      setTurns(current => [...current, { role: 'assistant', text: answer.result, status: answer.status, sources: answer.sources }]);
    } catch (error: any) {
      setTurns(current => [...current, {
        role: 'error',
        text: error?.message || 'Không thể trả lời câu hỏi này. Vui lòng thử lại.',
      }]);
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    send(question);
  }

  return <section className="ai-followup" ref={sectionRef} aria-label="Hỏi thêm về dịch vụ">
    <div className="ai-followup-head">
      <div>
        <Bot size={18} />
        <span>
          <strong>Chat tiếp với ThreeH Workshop</strong>
          <small>{invoiceId ? `Trả lời dựa trên hóa đơn ${orderCode} và xe của bạn.` : `Trả lời dựa trên phiếu ${orderCode} và báo giá bạn được phép xem (nếu có).`}</small>
        </span>
      </div>
      <ShieldCheck size={16} />
    </div>

    <div className="ai-chat-thread" ref={threadRef} aria-live="polite">
      {!turns.length && <div className="ai-chat-intro">
        <Sparkles size={16} />
        <p>Bạn có thể hỏi thêm ngay tại đây. Trợ lý chỉ dùng dữ liệu của phiếu này, không tự chẩn đoán hoặc cam kết bảo hành.</p>
      </div>}
      {turns.map((turn, index) => <div key={index} className={`ai-chat-message ${turn.role}`}>
        <span>{turn.role === 'user' ? 'Bạn' : turn.role === 'assistant' ? 'ThreeH Workshop' : 'Không gửi được'}</span>
        <p>{turn.text}</p>
        {turn.role === 'assistant' && <small>{turn.status === 'error' ? 'Lỗi xử lý' : turn.status === 'no_data' ? 'Chưa có nguồn xác nhận cho câu hỏi' : 'Diễn giải từ dữ liệu phiếu · cần đối chiếu trước khi tư vấn'}</small>}
        {turn.role === 'assistant' && <AISourceReferences sources={turn.sources}/>}
      </div>)}
      {sending && <div className="ai-chat-message assistant">
        <span>ThreeH Workshop</span>
        <div className="typing"><i /><i /><i /></div>
      </div>}
    </div>

    {!turns.length && <div className="ai-followup-suggestions" aria-label="Câu hỏi gợi ý">
      {QUICK_QUESTIONS.map(item => <button key={item} type="button" disabled={sending} onClick={() => send(item)}>
        {item}
      </button>)}
    </div>}

    <form onSubmit={submit}>
      <input
        ref={inputRef}
        value={question}
        onChange={event => setQuestion(event.target.value)}
        maxLength={500}
        placeholder="Nhập câu hỏi của bạn về dịch vụ, chi phí, phụ tùng..."
        aria-label="Câu hỏi tiếp theo"
      />
      <button disabled={sending || question.trim().length < 2} aria-label="Gửi câu hỏi">
        <Send size={17} />
      </button>
    </form>
    <footer><CircleAlert size={12} /> AI không tự chẩn đoán hoặc cam kết bảo hành. Thông tin chưa có sẽ được chuyển cho kỹ thuật viên xác nhận.</footer>
  </section>;
}
