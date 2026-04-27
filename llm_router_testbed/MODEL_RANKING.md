# Router Model Ranking

This ranking is for this router workload on the configured NVIDIA OpenAI-compatible endpoint:
strict JSON-array tool selection over the full JAKATA tool catalog.

## Current Choice

Use:

```text
qwen/qwen3.5-122b-a10b,nvidia/nemotron-mini-4b-instruct
```

Qwen is the best observed semantic router when the provider accepts requests. Nemotron Mini is the fastest stable fallback when Qwen rate-limits.

## Measured Ranking

| Rank | Model | Result | Notes |
| ---: | --- | --- | --- |
| 1 | `qwen/qwen3.5-122b-a10b` | 7/8 exact, 0 format errors, 1 provider error | Best observed accuracy on the balanced hard sample. Rate-limit sensitive on longer batches. |
| 2 | `nvidia/nemotron-mini-4b-instruct` | 6/8 exact, 0 format errors, 0 provider errors | Best stable fast baseline. Lower semantic accuracy, but reliable for long evals. |
| 3 | `minimaxai/minimax-m2.5` | 1/8 exact, 2 format errors, 5 provider errors | Not reliable enough here. |
| 4 | `google/gemma-4-31b-it` | 0/8 exact, 8 provider errors | Timed out under the 12s router budget. |
| 5 | `z-ai/glm4.7` | 0/8 exact, 8 provider errors | Timed out under the 12s router budget. |
| 6 | `z-ai/glm-5.1` | 0/8 exact, 8 provider errors | Timed out under the 12s router budget. |
| 7 | `minimaxai/minimax-m2.7` | 0/8 exact, 8 provider errors | Timed out under the 12s router budget. |
| 8 | `moonshotai/kimi-k2.5` | 0/8 exact, 8 provider errors at 12s | Works for individual prompts with longer timeout, but too slow for mandatory live routing here. |

## Research Notes

- GLM-4.7 documentation highlights function calling and structured output support, so it was worth testing.
- MiniMax-M2.7 documentation positions the model around agentic tool use and interleaved thinking, so it was worth testing.
- NVIDIA and Moonshot describe Kimi K2.5 as agentic and tool-augmented, but the hosted endpoint was too slow for this router budget.
- Qwen was not chosen blindly; it won the live endpoint benchmark for this strict router workload.

## Commands

List available endpoint models:

```powershell
python llm_router_testbed\router\list_models.py
```

Run a benchmark:

```powershell
python llm_router_testbed\eval\benchmark_models.py --models qwen/qwen3.5-122b-a10b nvidia/nemotron-mini-4b-instruct --cases llm_router_testbed\eval\hard_cases.jsonl --max-cases 20
```

Use a specific router model or fallback chain:

```powershell
python test_router.py --model "qwen/qwen3.5-122b-a10b,nvidia/nemotron-mini-4b-instruct" --interactive
```
