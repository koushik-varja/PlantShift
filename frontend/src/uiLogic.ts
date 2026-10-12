export function maintenanceWindowStartHour(strategy:string):number|null {
  if(strategy==='MAINTENANCE_NOW') return 0
  if(strategy==='NEXT_SHIFT') return 8
  if(strategy==='LOW_DEMAND_WINDOW') return 16
  return null
}

export function maintenanceHorizonValidation(
  selected:string[],
  strategy:string,
  durationHours:number,
):string {
  const startHour=maintenanceWindowStartHour(strategy)
  if(selected.includes('maintenance_window') && startHour!==null && durationHours<=startHour) {
    return `Selected maintenance window occurs outside the simulation horizon. ${strategy} starts at ${startHour}h; choose a longer duration.`
  }
  return ''
}

export function showEstimatedValueAssumptions(objective:string):boolean {
  return objective==='MAXIMIZE_ESTIMATED_VALUE'
}


export function matchingBaselineConfig(durationHours:number,seed:number):{durationHours:number;seed:number} {
  return {durationHours,seed}
}
