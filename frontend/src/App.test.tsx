import {renderToStaticMarkup} from 'react-dom/server'
import {describe,expect,it,vi} from 'vitest'
import App from './App'
import {api, PortfolioResult, Twin, subscribeToTwinStream, TwinEventStream} from './api'
import {maintenanceHorizonValidation, showEstimatedValueAssumptions} from './uiLogic'

describe('Scenario Builder decision controls',()=>{
  it('rejects a low-demand maintenance selection outside the horizon',()=>{
    expect(maintenanceHorizonValidation(['maintenance_window'],'LOW_DEMAND_WINDOW',8)).toContain('outside the simulation horizon')
    expect(maintenanceHorizonValidation(['maintenance_window'],'LOW_DEMAND_WINDOW',24)).toBe('')
  })

  it('renders the decision-relevant scenario controls instead of hiding them in backend-only APIs',()=>{
    const html=renderToStaticMarkup(<App initialPage="Scenario Builder" />)
    for(const label of ['Simulation duration','Paired runs','Maintenance strategy','Maintenance min','Energy multiplier','Inspection accuracy','Buffer B','Scheduling strategy']) {
      expect(html).toContain(label)
    }
    expect(html).toContain('Current horizon:')
    expect(html).toContain('24 hours')
    expect(html).not.toContain('RUN_TO_FAILURE')
    expect(html).not.toContain('CONDITION_TRIGGERED')
  })
})

describe('Optimizer objective UI',()=>{
  it('switches estimated-value assumptions only for the financial objective',()=>{
    expect(showEstimatedValueAssumptions('MAXIMIZE_ESTIMATED_VALUE')).toBe(true)
    expect(showEstimatedValueAssumptions('MAXIMIZE_THROUGHPUT')).toBe(false)
    const financial=renderToStaticMarkup(<App initialPage="Portfolio Optimizer" initialObjective="MAXIMIZE_ESTIMATED_VALUE" />)
    expect(financial).toContain('Financial assumptions — ILLUSTRATIVE SAMPLE VALUES')
    expect(financial).toContain('Energy cost / kWh')
    expect(financial).toContain('Unplanned maintenance cost')
    const operational=renderToStaticMarkup(<App initialPage="Portfolio Optimizer" initialObjective="BALANCED_OPERATIONAL_IMPACT" />)
    expect(operational).not.toContain('Financial assumptions — ILLUSTRATIVE SAMPLE VALUES')
    expect(operational).toContain('throughput weight')
  })

  it('renders a financial recommendation with uncertainty and operational effects',()=>{
    const d={median:120,p10:70,p90:180}
    const result:PortfolioResult={
      objective:'MAXIMIZE_ESTIMATED_VALUE',objective_semantics:'financial',impact_label:'SIMULATED / ESTIMATED',
      best:{interventions:['iot_retrofit','energy_efficiency'],cost:14,implementation_cost:14,effort:3,risk:2,score:120,score_label:'median estimated net value',robust_deltas:{throughput_delta:{median:2,p10:1,p90:3}},estimated_value:{estimated_net_value:d}},
      alternatives:[],explanation:{why:'Best median estimated net value under the configured assumptions.',caveat:'Illustrative.'},
    }
    const html=renderToStaticMarkup(<App initialPage="Portfolio Optimizer" initialObjective="MAXIMIZE_ESTIMATED_VALUE" initialOptimizerResult={result} />)
    expect(html).toContain('Recommended portfolio:')
    expect(html).toContain('iot_retrofit + energy_efficiency')
    expect(html).toContain('median ESTIMATED net value:')
    expect(html).toContain('P10 70')
    expect(html).toContain('SIMULATED operational effects')
  })
})

describe('Live machine state',()=>{
  it('renders real health/risk fields and keeps EventSource open for native reconnect until cleanup',()=>{
    const twin:Twin={machine_id:'machineB',state:'DEGRADED',health_score:41,health_state:'HIGH_RISK',failure_probability:.81,model_version:'failure-risk-rf-v2-observable',warning_reason:'risk elevated',latest_telemetry:null,updated_at:'2026-10-12T10:00:00Z'}
    const html=renderToStaticMarkup(<App initialPage="Live Machine State" initialTwins={[twin]} />)
    expect(html).toContain('machineB · DEGRADED')
    expect(html).toContain('HIGH_RISK')
    expect(html).toContain('81.0%')

    class FakeStream implements TwinEventStream {
      closed=false
      listener:((event:MessageEvent)=>void)|null=null
      addEventListener(type:string,listener:(event:MessageEvent)=>void){if(type==='twins')this.listener=listener}
      close(){this.closed=true}
      emit(data:string){this.listener?.({data} as MessageEvent)}
    }
    const fake=new FakeStream()
    const received=vi.fn()
    const cleanup=subscribeToTwinStream(received,()=>fake)
    fake.emit(JSON.stringify([twin]))
    expect(received).toHaveBeenCalledWith([twin])
    fake.emit('{malformed')
    expect(fake.closed).toBe(false) // native EventSource remains eligible to reconnect
    cleanup()
    expect(fake.closed).toBe(true)
  })
})


describe('Global admin session control',()=>{
  it('is available on Portfolio Optimizer without visiting Scenario Builder and the optimizer request uses that token',async()=>{
    const html=renderToStaticMarkup(<App initialPage="Portfolio Optimizer" initialToken="portfolio-token" />)
    expect(html).toContain('Session admin token')
    expect(html).toContain('type="password"')
    expect(html).toContain('value="portfolio-token"')
    expect(html).toContain('Page-memory only · not persisted')

    const fetchMock=vi.fn().mockResolvedValue(new Response(JSON.stringify({objective:'MAXIMIZE_THROUGHPUT',objective_semantics:'operational',best:null,alternatives:[],explanation:null,impact_label:'SIMULATED'}),{status:200,headers:{'Content-Type':'application/json'}}))
    vi.stubGlobal('fetch',fetchMock)
    await api.optimize({budget:10},'portfolio-token')
    const init=fetchMock.mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string,string>)['X-Admin-Token']).toBe('portfolio-token')
    vi.unstubAllGlobals()
  })
})

describe('No-action optimizer decision',()=>{
  it('renders an explicit management decision and still shows transformation alternatives',()=>{
    const zero={median:0,p10:0,p90:0}
    const result:PortfolioResult={
      objective:'MAXIMIZE_ESTIMATED_VALUE',objective_semantics:'financial',decision:'NO_ACTION',impact_label:'SIMULATED / ESTIMATED',
      best:{decision:'NO_ACTION',interventions:[],cost:0,implementation_cost:0,effort:0,risk:0,score:0,score_label:'median estimated net value',robust_deltas:{throughput:zero},estimated_value:{estimated_net_value:zero}},
      alternatives:[{decision:'TRANSFORM',interventions:['energy_efficiency'],cost:11,implementation_cost:11,effort:2,risk:1,score:-3,score_label:'median estimated net value',robust_deltas:{throughput:zero},estimated_value:{estimated_net_value:{median:-3,p10:-5,p90:-1}}}],
      explanation:{why:'No transformation portfolio improves the selected objective under the current assumptions and constraints.',caveat:'Illustrative.'},
    }
    const html=renderToStaticMarkup(<App initialPage="Portfolio Optimizer" initialObjective="MAXIMIZE_ESTIMATED_VALUE" initialOptimizerResult={result} />)
    expect(html).toContain('No transformation recommended under the current assumptions and constraints.')
    expect(html).toContain('Best transformation alternatives')
    expect(html).toContain('energy_efficiency')
  })
})

describe('Paired baseline display configuration',()=>{
  it('uses the same scenario horizon and seed for the displayed baseline',async()=>{
    const {matchingBaselineConfig}=await import('./uiLogic')
    expect(matchingBaselineConfig(24,7)).toEqual({durationHours:24,seed:7})
    expect(matchingBaselineConfig(48,19)).toEqual({durationHours:48,seed:19})

    const fetchMock=vi.fn().mockImplementation(()=>Promise.resolve(new Response(JSON.stringify({}),{status:200,headers:{'Content-Type':'application/json'}})))
    vi.stubGlobal('fetch',fetchMock)
    await api.baseline(24,7)
    await api.baseline(48,19)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/baseline?duration_hours=24&seed=7')
    expect(String(fetchMock.mock.calls[1][0])).toContain('/api/baseline?duration_hours=48&seed=19')
    vi.unstubAllGlobals()
  })
})

