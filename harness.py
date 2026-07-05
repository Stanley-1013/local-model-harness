#!/usr/bin/env python3
"""Local Ollama model harness for routing, critique, revision, and evals."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "profiles.json"
DEFAULT_EVALS = ROOT / "eval_set.json"


@dataclass
class CallResult:
    model: str
    text: str
    elapsed_s: float
    thinking: str = ""


class OllamaClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach Ollama at {self.base_url}: {exc}") from exc
        if not raw:
            return {}
        return json.loads(raw)

    def tags(self) -> list[str]:
        data = self._request("GET", "/api/tags")
        return [m["name"] for m in data.get("models", [])]

    def chat(
        self,
        model: str,
        system: str,
        prompt: str,
        options: dict[str, Any] | None = None,
        keep_alive: str = "5m",
    ) -> CallResult:
        payload = {
            "model": model,
            "stream": False,
            "think": False,
            "keep_alive": keep_alive,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if options:
            payload["options"] = options
        start = time.perf_counter()
        data = self._request("POST", "/api/chat", payload)
        elapsed = time.perf_counter() - start
        message = data.get("message", {})
        return CallResult(
            model=model,
            text=message.get("content", ""),
            elapsed_s=elapsed,
            thinking=message.get("thinking", ""),
        )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def strip_thinking(text: str) -> str:
    stripped = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I).strip()
    if stripped:
        return stripped
    # Some reasoning models may spend the whole capped response in a think block.
    # Keep that content for diagnostics rather than returning a misleading blank.
    return re.sub(r"</?think>", "", text, flags=re.I).strip()


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def role_config(config: dict[str, Any], role: str) -> dict[str, Any]:
    models = config.get("models", {})
    if role not in models:
        raise RuntimeError(
            f"profiles.json has no model for role '{role}'. "
            f"Available roles: {', '.join(sorted(models)) or 'none'}"
        )
    return models[role]


def role_model(config: dict[str, Any], role: str) -> str:
    return role_config(config, role)["name"]


def role_options(config: dict[str, Any], role: str) -> dict[str, Any]:
    return dict(role_config(config, role).get("options", {}))


def route(config: dict[str, Any], prompt: str, explicit_mode: str) -> str:
    if explicit_mode != "auto":
        return explicit_mode
    text = prompt.lower()
    routing = config.get("routing", {})
    if any(k.lower() in text for k in routing.get("code_keywords", [])):
        return "code"
    if any(k.lower() in text for k in routing.get("reasoning_keywords", [])):
        return "reasoning"
    if any(k.lower() in text for k in routing.get("quick_keywords", [])):
        return "quick"
    if len(prompt) < 240:
        return "quick"
    return "general"


def primary_role(mode: str, prompt: str = "") -> str:
    if mode == "quick" and has_cjk(prompt):
        return "general"
    return {
        "code": "coder",
        "reasoning": "reasoner",
        "quick": "fast",
        "general": "general",
    }.get(mode, "general")


def critic_role(mode: str) -> str:
    return {
        "code": "reasoner",
        "reasoning": "general",
        "quick": "general",
        "general": "reasoner",
    }.get(mode, "reasoner")


def final_role(mode: str) -> str:
    return {
        "code": "coder",
        "reasoning": "reasoner",
        "quick": "general",
        "general": "general",
    }.get(mode, "general")


def system_for(mode: str, phase: str) -> str:
    base = (
        "You are one model in a local multi-model harness. "
        "Be accurate, concise, and explicit about uncertainty. "
        "Do not reveal hidden reasoning; provide the useful conclusion and checks."
    )
    if mode == "code":
        base += (
            " Prefer correct, runnable code, small tests, and minimal dependencies."
            " Output the code plus at most three short bullet notes; no long explanation sections."
        )
    elif mode == "reasoning":
        base += " Solve carefully, state assumptions, and verify the conclusion."
    elif mode == "quick":
        base += " Optimize for speed, clarity, and short output."
    if phase == "critic":
        base += (
            " You are the critic. Find concrete defects, missing constraints, and risky claims."
            " List at most 5 defects as bullets; do not rewrite the answer."
            " If nothing important is wrong, reply exactly: No major issues."
        )
    if phase == "final":
        base += " You are the final editor. Merge useful critique into one polished answer."
    return base


def ensure_models(client: OllamaClient, config: dict[str, Any]) -> tuple[list[str], list[str]]:
    installed = set(client.tags())
    wanted = [m["name"] for m in config["models"].values()]
    missing = [m for m in wanted if m not in installed]
    return sorted(installed), missing


def ask(client: OllamaClient, config: dict[str, Any], prompt: str, mode: str, strength: str) -> dict[str, Any]:
    chosen_mode = route(config, prompt, mode)
    p_role = primary_role(chosen_mode, prompt)
    if strength == "fast" and chosen_mode == "reasoning":
        p_role = "general"
    p = role_config(config, p_role)
    first = client.chat(p["name"], system_for(chosen_mode, "draft"), prompt, role_options(config, p_role))
    draft = strip_thinking(first.text)
    calls = [first]

    if strength == "fast":
        return {
            "mode": chosen_mode,
            "strength": strength,
            "answer": draft,
            "calls": [call.__dict__ for call in calls],
        }

    c_role = critic_role(chosen_mode)
    c = role_config(config, c_role)
    critic_prompt = (
        "User request:\n"
        f"{prompt}\n\n"
        "Draft answer:\n"
        f"{draft}\n\n"
        "List the draft's concrete defects (max 5 bullets). Do not rewrite the answer. "
        "If nothing important is wrong, reply exactly: No major issues."
    )
    critique = client.chat(c["name"], system_for(chosen_mode, "critic"), critic_prompt, role_options(config, c_role))
    critique_text = strip_thinking(critique.text)
    if not critique_text and critique.thinking:
        # Reasoning models can burn the whole output budget inside thinking;
        # salvage the tail of the trace instead of silently accepting a blank critique.
        critique_text = "[salvaged from reasoning trace]\n" + critique.thinking[-1200:].strip()
    if not critique_text:
        print(
            f"warning: critic {c['name']} returned no usable output; answer is unreviewed",
            file=sys.stderr,
        )
    calls.append(critique)

    if strength == "strong":
        f_role = final_role(chosen_mode)
        f = role_config(config, f_role)
        final_prompt = (
            "User request:\n"
            f"{prompt}\n\n"
            "Draft answer:\n"
            f"{draft}\n\n"
            "Critique:\n"
            f"{critique_text}\n\n"
            "Write the final answer. Keep only what is useful; do not mention this harness."
        )
        final = client.chat(f["name"], system_for(chosen_mode, "final"), final_prompt, role_options(config, f_role))
        calls.append(final)
        answer = strip_thinking(final.text)
    elif critique_text:
        answer = draft + "\n\nReview notes:\n" + critique_text
    else:
        answer = draft + "\n\n[Review notes unavailable: critic returned empty output]"

    return {
        "mode": chosen_mode,
        "strength": strength,
        "answer": answer,
        "calls": [call.__dict__ for call in calls],
    }


def heuristic_score(item: dict[str, Any], answer: str) -> dict[str, Any]:
    text = answer.lower()
    score = 1.0 if answer.strip() else 0.0
    reasons = []
    if item["id"] == "biosim_solver":
        checks = [
            ("solve_ivp" in text, "uses solve_ivp"),
            ("odeint" not in text, "avoids odeint"),
            ("assert" in text or "raise" in text, "has sanity check"),
            ("return" in text and "t" in text and "y" in text, "returns t/y"),
            ("-0.7" in text, "uses decay rate"),
        ]
    elif item["id"] == "reasoning_control":
        checks = [
            (any(k in text for k in ["classif", "route", "routing", "分類", "路由"]), "routes tasks"),
            (any(k in text for k in ["confidence", "threshold", "信心", "門檻"]), "uses confidence threshold"),
            (any(k in text for k in ["escalat", "fallback", "升級", "轉交"]), "escalates hard cases"),
            (any(k in text for k in ["measure", "eval", "latency", "accuracy", "評測", "延遲", "準確"]), "measures tradeoffs"),
        ]
    elif item.get("must_include") or item.get("must_exclude"):
        checks = []
        for kw in item.get("must_include", []):
            checks.append((kw.lower() in text, f"includes '{kw}'"))
        for kw in item.get("must_exclude", []):
            checks.append((kw.lower() not in text, f"avoids '{kw}'"))
    else:
        checks = [
            (has_cjk(answer), "uses Chinese"),
            (len(answer.strip()) <= 160, "is concise"),
            (any(k in answer for k in ["硬體", "任務", "配合", "本地", "模型"]), "preserves meaning"),
            ("越大越好" in answer or "不是" in answer, "keeps contrast"),
        ]
    for passed, reason in checks:
        if passed:
            score += 4.0 / len(checks)
            reasons.append(reason)
    return {"score": min(score, 5.0), "reason": "; ".join(reasons) or "heuristic fallback", "raw": ""}


def judge_role_for(config: dict[str, Any], worker_model: str) -> str:
    # Never let a model grade its own answer; pick the first different model.
    for candidate in ("general", "coder", "fast"):
        if candidate in config.get("models", {}) and role_model(config, candidate) != worker_model:
            return candidate
    return "general"


def judge(
    client: OllamaClient,
    config: dict[str, Any],
    item: dict[str, Any],
    answer: str,
    worker_model: str = "",
) -> dict[str, Any]:
    fallback = heuristic_score(item, answer)
    if not answer.strip():
        return fallback
    prompt = (
        "Score the answer from 1 to 5 against the rubric. "
        "Return compact JSON only with keys score and reason.\n\n"
        f"Task:\n{item['prompt']}\n\n"
        f"Rubric:\n{item['rubric']}\n\n"
        f"Answer:\n{answer}"
    )
    j_role = judge_role_for(config, worker_model)
    res = client.chat(role_model(config, j_role), "You are a strict evaluator. Return valid JSON only.", prompt, role_options(config, j_role))
    text = strip_thinking(res.text)
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return {"score": float(parsed.get("score", 0)), "reason": str(parsed.get("reason", "")), "raw": text}
        except json.JSONDecodeError:
            pass
    score_match = re.search(r"(?:score|分數|評分)\D*([1-5](?:\.\d+)?)", text, flags=re.I)
    if not score_match:
        score_match = re.search(r"\b([1-5](?:\.\d+)?)\s*/\s*5\b", text)
    if not score_match:
        return {**fallback, "raw": text}
    return {
        "score": float(score_match.group(1)),
        "reason": text[:500],
        "raw": text,
    }


def run_eval(
    client: OllamaClient,
    config: dict[str, Any],
    eval_path: Path,
    limit: int | None,
    strength: str,
    out: Path | None = None,
) -> list[dict[str, Any]]:
    items = load_json(eval_path)
    if limit is not None:
        items = items[:limit]
    results = []
    for item in items:
        result = ask(client, config, item["prompt"], item.get("mode", "auto"), strength)
        worker_model = result["calls"][-1]["model"] if result["calls"] else ""
        score = judge(client, config, item, result["answer"], worker_model)
        results.append({
            "id": item["id"],
            "mode": result["mode"],
            "score": score["score"],
            "reason": score["reason"],
            "calls": result["calls"],
            "answer": result["answer"],
        })
        if out is not None:
            out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def print_score_band(avg_score: float) -> None:
    if avg_score >= 4.6:
        band = "strong on this eval set; still verify high-stakes output"
    elif avg_score >= 4.0:
        band = "solid for routine tasks; review anything important"
    elif avg_score >= 3.2:
        band = "usable as a drafting aid; expect errors, always review"
    else:
        band = "unstable for this workload; check profiles.json and docs/MODEL_SELECTION.md"
    print(f"Band: {band}")


def cmd_doctor(client: OllamaClient, config: dict[str, Any]) -> int:
    installed, missing = ensure_models(client, config)
    print(f"Ollama: {client.base_url}")
    print("Role assignments (profiles.json):")
    for role, cfg in config.get("models", {}).items():
        mark = "MISSING" if cfg["name"] in missing else "ok"
        print(f"  - {role:<8} -> {cfg['name']} [{mark}]")
    print()
    print("Installed Ollama models:")
    for name in installed:
        print(f"  - {name}")
    print()
    if missing:
        print("Missing models. Install them with:")
        for name in missing:
            print(f"  ollama pull {name}")
        print("Or point that role at an installed model in profiles.json.")
        return 2
    print("Harness profile is complete.")
    print(config.get("hardware_note", ""))
    return 0


def cmd_warm(client: OllamaClient, config: dict[str, Any]) -> int:
    for role in ["fast", "general", "coder", "reasoner"]:
        model = role_model(config, role)
        print(f"Warming {model}...")
        res = client.chat(model, "Reply with OK only.", "OK?", role_options(config, role), keep_alive="10m")
        print(f"  {strip_thinking(res.text)[:80]} ({res.elapsed_s:.1f}s)")
    return 0


COMMANDS = {"doctor", "warm", "ask", "eval", "chat"}


def main(argv: list[str]) -> int:
    # Windows consoles often default to cp950/cp1252; force UTF-8 so Chinese
    # answers do not crash the print at the very end of a model call.
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    # Friendly entry: `harness.py 你的問題` works without typing `ask`.
    if argv and argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv = ["ask", *argv]
    parser = argparse.ArgumentParser(description="Local Ollama multi-model harness")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to profiles.json")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Check Ollama connectivity and installed models")
    sub.add_parser("warm", help="Warm configured models sequentially")

    ask_p = sub.add_parser("ask", help="Ask through the harness")
    ask_p.add_argument("prompt", nargs="+")
    ask_p.add_argument("--mode", choices=["auto", "code", "reasoning", "quick", "general"], default="auto")
    ask_p.add_argument(
        "--strength",
        choices=["fast", "review", "strong"],
        default="fast",
        help="fast=1 call (default), review=+critique, strong=+critique+revision",
    )
    ask_p.add_argument("--json", action="store_true", help="Print JSON envelope")

    chat_p = sub.add_parser("chat", help="Interactive loop (no memory between turns); /exit to quit")
    chat_p.add_argument("--mode", choices=["auto", "code", "reasoning", "quick", "general"], default="auto")
    chat_p.add_argument("--strength", choices=["fast", "review", "strong"], default="fast")

    eval_p = sub.add_parser("eval", help="Run a tiny local eval set")
    eval_p.add_argument("--evals", default=str(DEFAULT_EVALS))
    eval_p.add_argument("--limit", type=int)
    eval_p.add_argument("--strength", choices=["fast", "review", "strong"], default="fast")
    eval_p.add_argument("--out", help="Write detailed JSON results")

    args = parser.parse_args(argv)
    config_path = Path(args.config)
    try:
        config = load_json(config_path)
    except FileNotFoundError:
        print(f"error: config not found: {config_path}", file=sys.stderr)
        print("Fix: check the --config path, or restore from profiles.json.bak.*", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"error: {config_path} is not valid JSON: {exc}", file=sys.stderr)
        print("Fix: repair the JSON, or restore from profiles.json.bak.*", file=sys.stderr)
        return 2
    client = OllamaClient(config.get("ollama_url", "http://127.0.0.1:11434"))

    try:
        return dispatch(args, client, config)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "Next step: if Ollama is unreachable, start it (`ollama serve` or the Ollama app), "
            "then rerun `harness.py doctor`.",
            file=sys.stderr,
        )
        return 2


def cmd_chat(client: OllamaClient, config: dict[str, Any], mode: str, strength: str) -> int:
    print("Local harness chat. Each turn is independent (no memory).")
    print("Commands: /exit  /mode auto|code|reasoning|quick|general  /strength fast|review|strong")
    while True:
        try:
            line = input(f"[{mode}/{strength}] you> ").replace("\ufeff", "").strip()  # strip UTF-8 BOM from redirected stdin
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in {"/exit", "/quit", "exit", "quit"}:
            return 0
        if line.startswith("/mode"):
            parts = line.split()
            if len(parts) == 2 and parts[1] in {"auto", "code", "reasoning", "quick", "general"}:
                mode = parts[1]
            else:
                print("usage: /mode auto|code|reasoning|quick|general")
            continue
        if line.startswith("/strength"):
            parts = line.split()
            if len(parts) == 2 and parts[1] in {"fast", "review", "strong"}:
                strength = parts[1]
            else:
                print("usage: /strength fast|review|strong")
            continue
        result = ask(client, config, line, mode, strength)
        print(result["answer"])
        meta = ", ".join(f"{c['model']} {c['elapsed_s']:.1f}s" for c in result["calls"])
        print(f"  [{result['mode']} | {meta}]")


def dispatch(args: argparse.Namespace, client: OllamaClient, config: dict[str, Any]) -> int:
    if args.command == "doctor":
        return cmd_doctor(client, config)
    if args.command == "chat":
        return cmd_chat(client, config, args.mode, args.strength)
    if args.command == "warm":
        return cmd_warm(client, config)
    if args.command == "ask":
        prompt = " ".join(args.prompt)
        result = ask(client, config, prompt, args.mode, args.strength)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result["answer"])
            print()
            print("Calls:")
            for call in result["calls"]:
                print(f"  - {call['model']}: {call['elapsed_s']:.1f}s")
        return 0
    if args.command == "eval":
        out = Path(args.out) if args.out else None
        results = run_eval(client, config, Path(args.evals), args.limit, args.strength, out)
        avg = sum(r["score"] for r in results) / max(len(results), 1)
        print(f"Average score: {avg:.2f}/5 over {len(results)} tasks")
        print_score_band(avg)
        for r in results:
            print(f"  - {r['id']}: {r['score']:.1f}/5 {r['reason'][:120]}")
        if out is not None:
            print(f"Wrote {args.out}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
