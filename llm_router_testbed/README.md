# LLM Router Testbed

Standalone mandatory LLM-first router for testing JAKATA tool selection. It does not replace the emergency/current router.

## Interactive Testing

```powershell
python test_router.py --interactive
```

Type like a normal chatbot. The router prints only a JSON array:

```json
["search_web","document"]
```

Debug info goes to stderr:

```powershell
python test_router.py --interactive --debug
```

## Batch Eval

Run the 200+ hard prompt eval:

```powershell
python llm_router_testbed\eval\eval_router.py --cases llm_router_testbed\eval\hard_cases.jsonl --max-cases 200 --no-fail-code
```

Run all generated cases:

```powershell
python llm_router_testbed\eval\eval_router.py --no-fail-code
```

Reports are written to:

```text
llm_router_testbed/eval/reports/
```

## Tool Registry

The default registry is generated from the live JAKATA tool manifest:

```text
llm_router_testbed/router/tools.json
```

Refresh it:

```powershell
python llm_router_testbed\router\export_jakata_tools.py
```

The five-label starter profile is still available:

```powershell
python test_router.py --profile starter --interactive
```

## Model Choice

Default chain:

```text
qwen/qwen3.5-122b-a10b,nvidia/nemotron-mini-4b-instruct
```

See `MODEL_RANKING.md` for the measured ranking of Qwen, Gemma, GLM, MiniMax, Kimi, and Nemotron on this router workload.

Override the model:

```powershell
python test_router.py --model "nvidia/nemotron-mini-4b-instruct" --interactive
```

## Production Integration

The production JAKATA runtime now builds a mandatory first-pass router from the live tool registry and passes it into `JakataAgent`.

Default behavior:

```text
mandatory router -> old planner only fills args for selected tools -> execution
```

Disable only for emergency testing:

```powershell
$env:JAKATA_MANDATORY_ROUTER_ENABLED="0"
```

Allow emergency fallback to the old planner if the mandatory router provider fails:

```powershell
$env:JAKATA_MANDATORY_ROUTER_EMERGENCY_FALLBACK="1"
```

Override the production mandatory router model chain:

```powershell
$env:JAKATA_MANDATORY_ROUTER_MODELS="qwen/qwen3.5-122b-a10b,nvidia/nemotron-mini-4b-instruct"
```

The live app defaults to the higher-accuracy Qwen->Nemotron chain for mandatory selection, then uses `nvidia/nemotron-mini-4b-instruct` for fast argument filling. This keeps the routing decision strong while removing the old slow second router call.

Override the fast argument filler:

```powershell
$env:JAKATA_ARG_PLANNER_MODELS="nvidia/nemotron-mini-4b-instruct"
```

Benchmark models:

```powershell
python llm_router_testbed\eval\benchmark_models.py --models google/gemma-4-31b-it z-ai/glm4.7 minimaxai/minimax-m2.7 qwen/qwen3.5-122b-a10b --max-cases 8
```

## Datasets

- `eval/real_cases.jsonl`: 202 realistic cases
- `eval/hard_cases.jsonl`: 236 hard cases

Each JSONL row has:

```json
{"prompt":"...","expected_tools":["..."],"difficulty":"hard","category":"...","notes":"..."}
```

Regenerate:

```powershell
python llm_router_testbed\eval\generate_datasets.py
```
