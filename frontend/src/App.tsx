import {useEffect, useMemo, useState} from 'react'
import {api, FactoryMetrics, Intervention, PortfolioResult, RobustDelta, ScenarioPayload, subscribeToTwinStream, Twin} from './api'
import {maintenanceHorizonValidation, maintenanceWindowStartHour, matchingBaselineConfig, showEstimatedValueAssumptions} from './uiLogic'
import './styles.css'

const pages = [
  'Transformation Overview', 'Current-State Factory', 'Live Machine State', 'Production KPIs',
  'Transformation Catalog', 'Scenario Builder', 'Scenario Comparison', 'Portfolio Optimizer',
  'Sensitivity', 'Transformation Roadmap', 'ML Evaluation', 'Assumptions / Limitations',
] as const
export type Page = typeof pages[number]
export interface AppProps { initialPage?:Page; initialObjective?:string; initialOptimizerResult?:PortfolioResult|null; initialTwins?:Twin[]; initialToken?:string }
const objectiveOptions = ['MAXIMIZE_THROUGHPUT','MAXIMIZE_OEE','MINIMIZE_DOWNTIME','MINIMIZE_SCRAP','MINIMIZE_ENERGY','MINIMIZE_LATE_ORDERS','MAXIMIZE_ESTIMATED_VALUE','MAXIMIZE_BENEFIT_PER_EFFORT','BALANCED_OPERATIONAL_IMPACT']
const pct = (v:number) => `${(v*100).toFixed(1)}%`

function Metric({label,value}:{label:string; value:string|number}) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>
}
function DeltaTable({summary}:{summary:Record<string,RobustDelta>}) {
  return <table><thead><tr><th>Metric</th><th>Median</th><th>P10</th><th>P90</th></tr></thead><tbody>
    {Object.entries(summary).map(([k,v]) => <tr key={k}><td>{k.replaceAll('_',' ')}</td><td>{v.median}</td><td>{v.p10}</td><td>{v.p90}</td></tr>)}
  </tbody></table>
}
function NumericInput({label,value,onChange,step=1}:{label:string;value:number;onChange:(v:number)=>void;step?:number}) {
  return <label>{label}<input type="number" step={step} value={value} onChange={e=>onChange(Number(e.target.value))}/></label>
}

export default function App({initialPage='Transformation Overview',initialObjective='MAXIMIZE_BENEFIT_PER_EFFORT',initialOptimizerResult=null,initialTwins=[],initialToken=''}:AppProps={}) {
  const [page,setPage] = useState<Page>(initialPage)
  const [baseline,setBaseline] = useState<FactoryMetrics|null>(null)
  const [baselineConfig,setBaselineConfig] = useState({durationHours:24,seed:7})
  const [catalog,setCatalog] = useState<Intervention[]>([])
  const [twins,setTwins] = useState<Twin[]>(initialTwins)
  const [ml,setMl] = useState<Record<string,unknown>>({})
  const [error,setError] = useState('')
  const [token,setToken] = useState(initialToken)

  const [selected,setSelected] = useState<string[]>(['iot_retrofit','telemetry_platform','condition_maintenance'])
  const [scenario,setScenario] = useState<FactoryMetrics|null>(null)
  const [comparison,setComparison] = useState<Record<string,RobustDelta>|null>(null)
  const [business,setBusiness] = useState<Record<string,unknown>|null>(null)
  const [roadmap,setRoadmap] = useState<Array<{phase:number;interventions:string[];rationale:string}>>([])
  const [opt,setOpt] = useState<PortfolioResult|null>(initialOptimizerResult)
  const [sensitivity,setSensitivity] = useState<Record<string,unknown>|null>(null)

  const [budget,setBudget] = useState(100)
  const [effort,setEffort] = useState(10)
  const [risk,setRisk] = useState(8)
  const [objective,setObjective] = useState(initialObjective)
  const [runs,setRuns] = useState(5)
  const [durationHours,setDurationHours] = useState(24)
  const [costs,setCosts] = useState<Record<string,number>>({})
  const [efforts,setEfforts] = useState<Record<string,number>>({})
  const [maintenanceStrategy,setMaintenanceStrategy] = useState('LOW_DEMAND_WINDOW')
  const [maintenanceStage,setMaintenanceStage] = useState('B')
  const [plannedMaintenance,setPlannedMaintenance] = useState(30)
  const [energyFactor,setEnergyFactor] = useState(.9)
  const [inspectionAccuracy,setInspectionAccuracy] = useState(.98)
  const [inspectionDelay,setInspectionDelay] = useState(.75)
  const [defectDetection,setDefectDetection] = useState(.96)
  const [schedulingRule,setSchedulingRule] = useState('weighted_priority')
  const [bufferB,setBufferB] = useState(28)
  const [bufferC,setBufferC] = useState(22)
  const [capacityStage,setCapacityStage] = useState('B')
  const [capacityCount,setCapacityCount] = useState(2)
  const [speedMultiplier,setSpeedMultiplier] = useState(1)
  const [valuePerUnit,setValuePerUnit] = useState(80)
  const [downtimeCost,setDowntimeCost] = useState(200)
  const [scrapCost,setScrapCost] = useState(55)
  const [reworkCost,setReworkCost] = useState(18)
  const [energyCost,setEnergyCost] = useState(.12)
  const [plannedMaintenanceCost,setPlannedMaintenanceCost] = useState(90)
  const [unplannedMaintenanceCost,setUnplannedMaintenanceCost] = useState(220)
  const [weights,setWeights] = useState<Record<string,number>>({throughput:1,oee:1,downtime:1,scrap:1,energy:1,late_orders:1})

  useEffect(() => {
    Promise.all([api.baseline(24,7),api.catalog(),api.twins(),api.mlEvaluation()])
      .then(([b,c,t,m]) => {setBaseline(b);setBaselineConfig({durationHours:24,seed:7});setCatalog(c);setTwins(t);setMl(m)})
      .catch(e => setError(String(e)))
  },[])
  useEffect(() => subscribeToTwinStream(setTwins),[])

  const payload = useMemo<ScenarioPayload>(() => ({
    name:'ui-scenario', interventions:selected, duration_hours:durationHours, seed:7,
    parameters:{maintenance_strategy:maintenanceStrategy,maintenance_stage:maintenanceStage,planned_maintenance_min:plannedMaintenance,energy_factor:energyFactor,inspection_accuracy:inspectionAccuracy,inspection_delay_min:inspectionDelay,defect_detection_rate:defectDetection,scheduling_rule:schedulingRule,buffer_b:bufferB,buffer_c:bufferC,capacity_stage:capacityStage,capacity_count:capacityCount,speed_multiplier:speedMultiplier},
    cost_overrides:costs, effort_overrides:efforts,
  }),[selected,durationHours,maintenanceStrategy,maintenanceStage,plannedMaintenance,energyFactor,inspectionAccuracy,inspectionDelay,defectDetection,schedulingRule,bufferB,bufferC,capacityStage,capacityCount,speedMultiplier,costs,efforts])
  const businessAssumptions = {value_per_finished_unit:valuePerUnit,downtime_cost_per_hour:downtimeCost,scrap_cost_per_unit:scrapCost,rework_cost_per_unit:reworkCost,energy_cost_per_kwh:energyCost,planned_maintenance_cost:plannedMaintenanceCost,unplanned_maintenance_cost:unplannedMaintenanceCost}
  const maintenanceStartHour = maintenanceWindowStartHour(maintenanceStrategy)
  const maintenanceHorizonError = maintenanceHorizonValidation(selected,maintenanceStrategy,durationHours)

  const runScenario = async () => {
    try {
      setError('')
      if(maintenanceHorizonError){setError(maintenanceHorizonError);return}
      const baselineRequest = matchingBaselineConfig(payload.duration_hours,payload.seed)
      const [matchedBaseline,s,m,b] = await Promise.all([
        api.baseline(baselineRequest.durationHours,baselineRequest.seed),
        api.runScenario(payload,token),
        api.monteCarlo({...payload,runs},token),
        api.businessValue({scenario:payload,...businessAssumptions},token),
      ])
      setBaseline(matchedBaseline);setBaselineConfig({durationHours:payload.duration_hours,seed:payload.seed})
      setScenario(s);setComparison(m.summary);setBusiness(b)
    } catch(e) {setError(String(e))}
  }
  const runOptimizer = async () => {
    try {
      setError('')
      setOpt(await api.optimize({budget,implementation_capacity:effort,maximum_risk:risk,objective,evaluation_runs:runs,duration_hours:durationHours,weights,cost_overrides:costs,effort_overrides:efforts,business_assumptions:businessAssumptions,scenario_parameters:payload.parameters},token))
    } catch(e) {setError(String(e))}
  }
  const runSensitivity = async () => {
    const alt = selected.includes('energy_efficiency') ? selected.filter(x=>x!=='energy_efficiency') : [...selected,'energy_efficiency']
    try {
      setError('')
      setSensitivity(await api.sensitivity({scenarios:[payload,{...payload,name:'ui-alternative',interventions:alt}],...businessAssumptions},token))
    } catch(e) {setError(String(e))}
  }
  const buildRoadmap = async () => {
    try { setRoadmap(await api.roadmap(payload)) } catch(e) {setError(String(e))}
  }

  const metrics = baseline && <div className="metrics">
    <Metric label="Throughput" value={baseline.throughput_units}/><Metric label="OEE" value={pct(baseline.oee.oee)}/>
    <Metric label="Downtime" value={`${baseline.unplanned_downtime_min} min`}/><Metric label="Energy / unit" value={`${baseline.energy_per_finished_unit_kwh} kWh`}/>
  </div>
  const diagnoses = baseline?.diagnosis ?? []
  const featureImportance = Array.isArray(ml.feature_importance) ? ml.feature_importance as Array<{feature:string;importance:number}> : []
  const winnerCounts = sensitivity && typeof sensitivity.winner_counts==='object' && sensitivity.winner_counts ? sensitivity.winner_counts as Record<string,number> : {}

  let content = <></>
  if(page==='Transformation Overview') content=<><h2>Transformation Overview</h2><p className="lede">Brownfield decision support: diagnose → simulate → compare uncertainty → optimize a constrained portfolio → phase a prerequisite-aware roadmap.</p>{baseline&&<p className="lede"><b>Current-state baseline — {baselineConfig.durationHours}h simulation</b> · seed {baselineConfig.seed}</p>}{metrics}{scenario&&<div className="callout"><b>Transformed scenario — {baselineConfig.durationHours}h simulation:</b> throughput {scenario.throughput_units}, OEE {pct(scenario.oee.oee)}, energy {scenario.energy_kwh} kWh.</div>}{business&&<div className="callout"><b>ESTIMATED:</b> net value {String(business.estimated_net_value??business.estimated_financial_effect)} per simulated period. Not guaranteed ROI.</div>}</>
  if(page==='Current-State Factory') content=<><h2>Current-State Factory</h2><div className="flow"><b>A · Cutting</b>→<b>B · Processing</b>→<b>C · Assembly</b>→<b>Manual Quality</b>→<b>D · Packaging</b></div>{metrics}<h3>Evidence-based diagnosis</h3><table><thead><tr><th>Asset / issue</th><th>Evidence</th></tr></thead><tbody>{diagnoses.map((d,i)=><tr key={i}><td>{String(d.machine_id??d.type??'diagnosis')}</td><td>{Array.isArray(d.evidence)?d.evidence.join(' · '):''}</td></tr>)}</tbody></table></>
  if(page==='Live Machine State') content=<><h2>Live Machine State</h2><p className="lede">SSE updates automatically without refresh. Failure risk is produced by the startup-loaded model from observable telemetry.</p><div className="grid">{twins.length===0?<p>No telemetry ingested yet.</p>:twins.map(t=><div className="card" key={t.machine_id}><b>{t.machine_id} · {t.state}</b><p>Health {t.health_state} · risk {t.failure_probability==null?'n/a':pct(t.failure_probability)}</p><small>{t.warning_reason??'Awaiting model output'}</small></div>)}</div></>
  if(page==='Production KPIs') content=<><h2>Production KPIs</h2>{baseline&&<><div className="metrics"><Metric label="Availability" value={pct(baseline.oee.availability)}/><Metric label="Performance" value={pct(baseline.oee.performance)}/><Metric label="Quality" value={pct(baseline.oee.quality)}/><Metric label="WIP" value={baseline.wip_end}/></div>{metrics}<div className="metrics"><Metric label="Scrap" value={pct(baseline.scrap_rate)}/><Metric label="Late orders" value={baseline.late_orders}/><Metric label="Planned downtime" value={`${baseline.planned_downtime_min} min`}/><Metric label="Energy" value={`${baseline.energy_kwh} kWh`}/></div></>}</>
  if(page==='Transformation Catalog') content=<><h2>Transformation Catalog</h2><p className="lede">Defaults are ILLUSTRATIVE SAMPLE VALUES. Override cost and effort without editing source.</p><div className="grid">{catalog.map(c=><div className="card" key={c.id}><b>{c.name}</b><p>{c.description}</p><NumericInput label="Illustrative cost" value={costs[c.id]??c.illustrative_cost} onChange={v=>setCosts(x=>({...x,[c.id]:v}))}/><NumericInput label="Effort" value={efforts[c.id]??c.implementation_effort} onChange={v=>setEfforts(x=>({...x,[c.id]:v}))}/><small>Risk {c.risk} · prerequisites {c.prerequisites.join(', ')||'none'}</small></div>)}</div></>
  if(page==='Scenario Builder') content=<><h2>Scenario Builder</h2><div className="controls"><label>Simulation duration<select value={durationHours} onChange={e=>setDurationHours(Number(e.target.value))}>{[8,16,24,48,72].map(h=><option key={h} value={h}>{h}h</option>)}</select></label><NumericInput label="Paired runs" value={runs} onChange={setRuns}/><label>Maintenance strategy<select value={maintenanceStrategy} onChange={e=>setMaintenanceStrategy(e.target.value)}>{['MAINTENANCE_NOW','NEXT_SHIFT','LOW_DEMAND_WINDOW'].map(x=><option key={x}>{x}</option>)}</select></label><label>Stage<select value={maintenanceStage} onChange={e=>setMaintenanceStage(e.target.value)}>{['A','B','C','D'].map(x=><option key={x}>{x}</option>)}</select></label><NumericInput label="Maintenance min" value={plannedMaintenance} onChange={setPlannedMaintenance}/></div><div className="callout"><b>Current horizon:</b> {durationHours} hours · <b>Scheduled maintenance window:</b> {`${maintenanceStrategy} starts at ${maintenanceStartHour}h`} · Condition-triggered maintenance is configured by selecting the Condition-based maintenance intervention.</div>{maintenanceHorizonError&&<div className="error">{maintenanceHorizonError}</div>}<div className="checks">{catalog.map(c=><label key={c.id}><input type="checkbox" checked={selected.includes(c.id)} onChange={()=>setSelected(v=>v.includes(c.id)?v.filter(x=>x!==c.id):[...v,c.id])}/>{c.name}</label>)}</div><h3>Decision-relevant intervention parameters</h3><div className="controls"><NumericInput label="Energy multiplier" value={energyFactor} step={.01} onChange={setEnergyFactor}/><NumericInput label="Inspection accuracy" value={inspectionAccuracy} step={.01} onChange={setInspectionAccuracy}/><NumericInput label="Defect detection rate" value={defectDetection} step={.01} onChange={setDefectDetection}/><NumericInput label="Inspection delay min" value={inspectionDelay} step={.1} onChange={setInspectionDelay}/><label>Scheduling strategy<select value={schedulingRule} onChange={e=>setSchedulingRule(e.target.value)}>{['fifo','edd','weighted_priority'].map(x=><option key={x}>{x}</option>)}</select></label><NumericInput label="Buffer B" value={bufferB} onChange={setBufferB}/><NumericInput label="Buffer C" value={bufferC} onChange={setBufferC}/><label>Capacity stage<select value={capacityStage} onChange={e=>setCapacityStage(e.target.value)}>{['A','B','C','D'].map(x=><option key={x}>{x}</option>)}</select></label><NumericInput label="Machine count" value={capacityCount} onChange={setCapacityCount}/><NumericInput label="Speed multiplier" value={speedMultiplier} step={.1} onChange={setSpeedMultiplier}/></div><h3>Business assumptions — ILLUSTRATIVE SAMPLE VALUES</h3><div className="controls"><NumericInput label="Value / finished unit" value={valuePerUnit} onChange={setValuePerUnit}/><NumericInput label="Downtime cost / hr" value={downtimeCost} onChange={setDowntimeCost}/><NumericInput label="Scrap cost / unit" value={scrapCost} onChange={setScrapCost}/><NumericInput label="Rework cost / unit" value={reworkCost} onChange={setReworkCost}/><NumericInput label="Energy cost / kWh" value={energyCost} step={.01} onChange={setEnergyCost}/><NumericInput label="Planned maintenance cost" value={plannedMaintenanceCost} onChange={setPlannedMaintenanceCost}/><NumericInput label="Unplanned maintenance cost" value={unplannedMaintenanceCost} onChange={setUnplannedMaintenanceCost}/></div><button disabled={Boolean(maintenanceHorizonError)} onClick={runScenario}>Run scenario + paired Monte Carlo + value model</button></>
  if(page==='Scenario Comparison') content=<><h2>Scenario Comparison</h2>{comparison?<><p className="lede">Current-state baseline — {baselineConfig.durationHours}h simulation · Transformed scenario — {baselineConfig.durationHours}h simulation · seed {baselineConfig.seed}</p><DeltaTable summary={comparison}/></>:<p>Run a scenario first. Baseline and transformed cases use identical horizon, demand and paired stochastic seeds.</p>}</>
  if(page==='Portfolio Optimizer') content=<><h2>Portfolio Optimizer</h2><p className="lede">Operational objectives use SIMULATED KPI deltas. MAXIMIZE_ESTIMATED_VALUE uses the configurable financial model and median paired-seed net value.</p><div className="controls"><NumericInput label="Budget" value={budget} onChange={setBudget}/><NumericInput label="Effort capacity" value={effort} onChange={setEffort}/><NumericInput label="Risk ceiling" value={risk} onChange={setRisk}/><label>Simulation duration<select value={durationHours} onChange={e=>setDurationHours(Number(e.target.value))}>{[8,16,24,48,72].map(h=><option key={h} value={h}>{h}h</option>)}</select></label><label>Objective<select value={objective} onChange={e=>setObjective(e.target.value)}>{objectiveOptions.map(x=><option key={x}>{x}</option>)}</select></label></div>{objective==='BALANCED_OPERATIONAL_IMPACT'&&<div className="controls">{Object.entries(weights).map(([k,v])=><NumericInput key={k} label={`${k} weight`} value={Number(v)} step={.1} onChange={n=>setWeights(w=>({...w,[k]:n}))}/>)}</div>}{showEstimatedValueAssumptions(objective)&&<><h3>Financial assumptions — ILLUSTRATIVE SAMPLE VALUES</h3><div className="controls"><NumericInput label="Value / finished unit" value={valuePerUnit} onChange={setValuePerUnit}/><NumericInput label="Downtime cost / hr" value={downtimeCost} onChange={setDowntimeCost}/><NumericInput label="Scrap cost / unit" value={scrapCost} onChange={setScrapCost}/><NumericInput label="Rework cost / unit" value={reworkCost} onChange={setReworkCost}/><NumericInput label="Energy cost / kWh" value={energyCost} step={.01} onChange={setEnergyCost}/><NumericInput label="Planned maintenance cost" value={plannedMaintenanceCost} onChange={setPlannedMaintenanceCost}/><NumericInput label="Unplanned maintenance cost" value={unplannedMaintenanceCost} onChange={setUnplannedMaintenanceCost}/></div><p className="lede">Implementation-cost overrides come from the Transformation Catalog controls.</p></>}<button onClick={runOptimizer}>Optimize robust portfolio</button>{opt?.best&&<>{opt.best.decision==='NO_ACTION'||opt.decision==='NO_ACTION'?<div className="callout"><b>No transformation recommended under the current assumptions and constraints.</b>{objective==='MAXIMIZE_ESTIMATED_VALUE'&&<> · median ESTIMATED net value: 0</>}</div>:<div className="callout"><b>Recommended portfolio:</b> {opt.best.interventions.join(' + ')} · illustrative implementation cost {opt.best.implementation_cost} · effort {opt.best.effort} · risk {opt.best.risk}{objective==='MAXIMIZE_ESTIMATED_VALUE'&&<> · <b>median ESTIMATED net value:</b> {opt.best.estimated_value.estimated_net_value.median} (P10 {opt.best.estimated_value.estimated_net_value.p10}, P90 {opt.best.estimated_value.estimated_net_value.p90})</>}</div>}<p><b>Why selected?</b> {opt.explanation?.why}</p><h3>SIMULATED operational effects</h3><DeltaTable summary={opt.best.robust_deltas}/>{objective==='MAXIMIZE_ESTIMATED_VALUE'&&<><h3>ESTIMATED financial breakdown</h3><DeltaTable summary={opt.best.estimated_value}/></>}<h3>Best transformation alternatives</h3><table><thead><tr><th>Portfolio</th><th>{objective==='MAXIMIZE_ESTIMATED_VALUE'?'Median estimated net value':'Score'}</th><th>Cost</th></tr></thead><tbody>{opt.alternatives.map((a,i)=><tr key={i}><td>{a.interventions.length?a.interventions.join(' + '):'No action'}</td><td>{objective==='MAXIMIZE_ESTIMATED_VALUE'?a.estimated_value.estimated_net_value.median:a.score}</td><td>{a.cost}</td></tr>)}</tbody></table></>}</>
  if(page==='Sensitivity') content=<><h2>Sensitivity / Decision Stability</h2><p className="lede">Tests whether the preferred scenario survives changes in production value, downtime cost, energy cost and implementation cost assumptions.</p><button onClick={runSensitivity}>Run decision stability analysis</button>{sensitivity&&<><div className="callout"><b>Decision stability:</b> {String(sensitivity.decision_stability)} · winner share {String(sensitivity.winner_share)}</div><table><thead><tr><th>Candidate</th><th>Wins</th></tr></thead><tbody>{Object.entries(winnerCounts).map(([k,v])=><tr key={k}><td>{k}</td><td>{v}</td></tr>)}</tbody></table></>}</>
  if(page==='Transformation Roadmap') content=<><h2>Transformation Roadmap</h2><button onClick={buildRoadmap}>Generate from selected interventions</button>{roadmap.map(r=><div className="card" key={r.phase}><b>Phase {r.phase}</b><p>{r.interventions.join(', ')}</p><small>{r.rationale}</small></div>)}</>
  if(page==='ML Evaluation') content=<><h2>ML Evaluation</h2><p className="lede">Observable telemetry only. Hidden simulator wear is used for synthetic ground truth, never as a deployable feature.</p><table><tbody>{['precision','recall','f1','roc_auc','pr_auc','decision_threshold'].map(k=><tr key={k}><th>{k}</th><td>{String(ml[k]??'not trained')}</td></tr>)}</tbody></table>{featureImportance.length>0&&<><h3>Feature importance</h3><table><thead><tr><th>Feature</th><th>Importance</th></tr></thead><tbody>{featureImportance.map(x=><tr key={x.feature}><td>{x.feature}</td><td>{x.importance.toFixed(4)}</td></tr>)}</tbody></table></>}</>
  if(page==='Assumptions / Limitations') content=<><h2>Assumptions / Limitations</h2><ul><li><b>SYNTHETIC:</b> generated factory telemetry and failure labels.</li><li><b>SIMULATED:</b> operational scenario outcomes and transformation deltas.</li><li><b>ESTIMATED:</b> financial effects from configurable assumptions.</li><li><b>MEASURED:</b> only tests and benchmarks that were actually executed.</li><li>The twin is operational, not physics-grade or industrially certified.</li><li>No real PLC/MES connection or vendor ROI is claimed.</li></ul></>

  return <div className="shell"><aside><div className="brand">PLANTSHIFT<small>Brownfield Transformation Twin</small></div><div className="session-control"><label>Session admin token<input aria-label="Session admin token" type="password" value={token} onChange={e=>setToken(e.target.value)} autoComplete="off"/></label><small>Page-memory only · not persisted</small></div>{pages.map(p=><button className={p===page?'nav active':'nav'} onClick={()=>setPage(p)} key={p}>{p}</button>)}</aside><main>{error&&<div className="error">{error}</div>}{content}<footer>SYNTHETIC data · SIMULATED outcomes · ESTIMATED financial effects · MEASURED checks only where executed</footer></main></div>
}
