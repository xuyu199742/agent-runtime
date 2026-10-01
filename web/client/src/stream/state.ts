export interface RunEvent {
  type: string;
  sequence: number;
  data: Record<string, unknown>;
}

export interface RunStreamState {
  sequence: number;
  status: string;
  stepId: string;
  partial: string;
  hasApproval: boolean;
}

export function emptyRunState(status = "PENDING"): RunStreamState {
  return { sequence: 0, status, stepId: "", partial: "", hasApproval: false };
}

export function applyRunEvent(
  state: RunStreamState,
  event: RunEvent,
): RunStreamState {
  if (event.type !== "run.snapshot" && event.sequence <= state.sequence)
    return state;
  const next = { ...state, sequence: Math.max(state.sequence, event.sequence) };
  const stepId = String(event.data.step_id || "");
  switch (event.type) {
    case "run.started":
    case "run.resumed":
      next.status = "RUNNING";
      next.hasApproval = false;
      break;
    case "model.started":
      next.stepId = stepId;
      next.partial = "";
      break;
    case "model.delta":
      if (stepId && stepId === next.stepId)
        next.partial += String(event.data.text || "");
      break;
    case "run.waiting":
      next.status = "WAITING";
      break;
    case "approval.required":
      next.hasApproval = true;
      break;
    case "run.completed":
      next.status = "COMPLETED";
      next.partial = String(event.data.answer ?? next.partial);
      break;
    case "run.failed":
      next.status = "FAILED";
      break;
    case "run.cancelled":
      next.status = "CANCELLED";
      break;
    case "run.snapshot":
      next.status = String(event.data.status || next.status);
      break;
  }
  return next;
}

export function isTerminal(status: string): boolean {
  return ["COMPLETED", "FAILED", "CANCELLED"].includes(status);
}
