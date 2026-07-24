/** 发言块头行阶段词（立论 / 续辩 / 答问 / 结辩）。 */
export function speechStageLabel(roundNo: number): string {
  return roundNo <= 1 ? "立论" : "续辩";
}
