def evaluate(steps, profile):
    remaining = [s for s in steps if s["status"] not in ("completed", "abandoned")]
    unknown = any(s["low"] is None or s["high"] is None for s in remaining)
    low = None if unknown or not steps else sum(s["low"] for s in remaining)
    high = None if unknown or not steps else sum(s["high"] for s in remaining)
    available = profile["available_minutes"]
    verdict = "unknown"
    if low is not None and available is not None:
        verdict = "conflict" if available < low else "conditional" if available < high else "fits"
    warnings = []
    if not profile["criterion"]:
        warnings.append("请先明确整个任务的完成标准。")
    if not profile["foundation"]:
        warnings.append("基础与前提尚未确认。")
    if any(s["status"] == "abandoned" for s in steps):
        warnings.append("有已放弃步骤，请核对目标是否仍能完成。")
    if any(s["status"] == "in_progress" for s in steps):
        warnings.append("进行中的步骤仍沿用原估时，请手工重估剩余时间。")
    if unknown:
        warnings.append("有步骤尚未估计时间，剩余总量不完整。")
    return {
        "time": verdict,
        "remaining_low": low,
        "remaining_high": high,
        "available_minutes": available,
        "warnings": warnings,
        "explanation": {
            "unknown": "信息不足：请补齐步骤估时和时间窗口内的可用总分钟。",
            "conflict": "可用时间小于剩余估时下限，建议缩小目标或延后。",
            "conditional": "覆盖估时下限但不足上限，需缩小范围或保留余量。",
            "fits": "时间能覆盖当前估计；基础、资源和其他任务负载仍需另行核对。",
        }[verdict],
    }
