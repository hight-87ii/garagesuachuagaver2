import { useEffect, useState } from 'react';

export default function ActualDurationCell({ item, enabled, onSave }: { item: any; enabled: boolean; onSave: (minutes: number) => void }) {
  const [value, setValue] = useState(String(item.actual_duration_min || ''));
  useEffect(() => setValue(String(item.actual_duration_min || '')), [item.actual_duration_min, item.id]);
  if (!enabled) return <span>{item.actual_duration_min ? `${item.actual_duration_min} phút` : 'Chưa ghi'}</span>;
  return <div className="actual-duration-field"><input aria-label={`Phút thực tế ${item.name}`} type="number" min="1" max="1440" step="1" value={value} onChange={event => setValue(event.target.value)} placeholder="Phút"/><button type="button" disabled={!value || Number(value) < 1 || Number(value) > 1440 || Number(value) === Number(item.actual_duration_min)} onClick={() => onSave(Number(value))}>Lưu</button></div>;
}
