import { Database } from 'lucide-react';

export type AISource = {type:string;id:number|null;label:string;date?:string;url?:string|null};

export default function AISourceReferences({sources}:{sources?:AISource[]}){
  if(!sources?.length)return null;
  return <div className="ai-source-references" aria-label="Nguồn dữ liệu đối chiếu"><strong><Database size={14}/> Nguồn đối chiếu</strong><ul>{sources.map((source,index)=><li key={`${source.type}-${source.id}-${index}`}>{source.url?.startsWith('https://')?<a href={source.url} target="_blank" rel="noopener noreferrer">{source.label} ↗</a>:source.label}</li>)}</ul></div>;
}
