export type MetricMap = Record<string, number | string | null>
export interface Oee { availability:number; performance:number; quality:number; oee:number }
export interface FactoryMetrics { throughput_units:number; throughput_per_hour:number; wip_end:number; planned_downtime_min:number; unplanned_downtime_min:number; scrap_rate:number; late_orders:number; energy_kwh:number; energy_per_finished_unit_kwh:number; oee:Oee; machines:Record<string,{stage:string;utilization:number;failures:number;maintenance_events:number;energy_kwh:number}>; diagnosis?:Array<Record<string,unknown>>; maintenance_window?:{strategy:string;scheduled_start_min:number|null;scheduled_start_hour:number|null;simulation_duration_hours:number} }
export interface Intervention { id:string; name:string; description:string; implementation_effort:number; illustrative_cost:number; risk:number; prerequisites:string[]; cost_label:string }
export interface Twin { machine_id:string; state:string; health_score:number; health_state:string; failure_probability:number|null; model_version:string|null; warning_reason:string|null; latest_telemetry:Record<string,unknown>|null; updated_at:string|null }
export interface ScenarioPayload { name:string; interventions:string[]; duration_hours:number; seed:number; parameters:Record<string,string|number|boolean|null>; cost_overrides:Record<string,number>; effort_overrides:Record<string,number> }
export interface RobustDelta { median:number; p10:number; p90:number }
export interface PortfolioCandidate { decision?:'NO_ACTION'|'TRANSFORM'; interventions:string[]; cost:number; implementation_cost:number; effort:number; risk:number; score:number; score_label:string; robust_deltas:Record<string,RobustDelta>; estimated_value:Record<string,RobustDelta> }
export interface PortfolioResult { objective:string; objective_semantics:string; decision?:'NO_ACTION'|'TRANSFORM'; best:PortfolioCandidate|null; alternatives:PortfolioCandidate[]; explanation:{why:string;caveat:string}|null; impact_label:string }
export interface TwinEventStream { addEventListener(type:string,listener:(event:MessageEvent)=>void):void; close():void }
export type TwinEventStreamFactory=(url:string)=>TwinEventStream
const API=import.meta.env.VITE_API_URL??'http://localhost:8000'
const STREAM_URL=`${API}/api/twins/stream/live`
async function request<T>(path:string,init?:RequestInit):Promise<T>{const response=await fetch(`${API}${path}`,init);if(!response.ok)throw new Error(`${response.status}: ${await response.text()}`);return response.json() as Promise<T>}
const admin=(payload:unknown,token:string):RequestInit=>({method:'POST',headers:{'Content-Type':'application/json','X-Admin-Token':token},body:JSON.stringify(payload)})
export const api={baseline:(durationHours=8,seed=7)=>request<FactoryMetrics>(`/api/baseline?duration_hours=${encodeURIComponent(durationHours)}&seed=${encodeURIComponent(seed)}`),catalog:()=>request<Intervention[]>('/api/catalog'),twins:()=>request<Twin[]>('/api/twins'),mlEvaluation:()=>request<Record<string,unknown>>('/api/ml/evaluation'),runScenario:(p:ScenarioPayload,t:string)=>request<FactoryMetrics>('/api/scenarios/run',admin(p,t)),monteCarlo:(p:ScenarioPayload&{runs:number},t:string)=>request<{summary:Record<string,RobustDelta>}>('/api/scenarios/monte-carlo',admin(p,t)),optimize:(p:unknown,t:string)=>request<PortfolioResult>('/api/optimizer/portfolio',admin(p,t)),businessValue:(p:unknown,t:string)=>request<Record<string,unknown>>('/api/business-value',admin(p,t)),sensitivity:(p:unknown,t:string)=>request<Record<string,unknown>>('/api/sensitivity',admin(p,t)),roadmap:(p:ScenarioPayload)=>request<Array<{phase:number;interventions:string[];rationale:string}>>('/api/roadmap',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)}),streamUrl:STREAM_URL}

export function subscribeToTwinStream(
  onTwins:(twins:Twin[])=>void,
  createStream:TwinEventStreamFactory=(url)=>new EventSource(url) as unknown as TwinEventStream,
):()=>void {
  const stream=createStream(STREAM_URL)
  stream.addEventListener('twins',event=>{
    try { onTwins(JSON.parse(event.data) as Twin[]) }
    catch { /* Leave native EventSource open so its automatic reconnect behavior is preserved. */ }
  })
  return ()=>stream.close()
}
