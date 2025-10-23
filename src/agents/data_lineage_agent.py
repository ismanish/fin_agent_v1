import os
import re
import json
import glob
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Optional: YAML prompt loader
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

# Optional: OpenAI SDK (preferred for chat per user's request)
try:  # pragma: no cover
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

# Optional: dotenv to load .env from project root
try:  # pragma: no cover
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))


def get_hfa_logs_dir() -> str:
    return os.path.join(_project_root(), "logs", "HFA")


def _parse_ts_from_name(path: str) -> Optional[datetime]:
    m = re.search(r"_HFA_(\d{4}-\d{2}-\d{2}_\d{6})\.json$", os.path.basename(path))
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d_%H%M%S")
    except Exception:
        return None


def find_latest_hfa_log(ticker: str, logs_dir: Optional[str] = None) -> Optional[str]:
    logs_dir = logs_dir or get_hfa_logs_dir()
    pattern = os.path.join(logs_dir, f"{ticker.upper()}_HFA_*.json")
    files = glob.glob(pattern)
    if not files:
        return None

    def sort_key(p: str) -> Tuple[int, float]:
        ts = _parse_ts_from_name(p)
        if ts:
            return (1, ts.timestamp())
        try:
            return (0, os.path.getmtime(p))
        except Exception:
            return (0, 0.0)

    files.sort(key=sort_key, reverse=True)
    return os.path.abspath(files[0])


def load_json_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_combined_json_data_from_local(ticker: str) -> Optional[str]:
    """
    Fetch latest HFA, COMP, and CAP JSON files for the ticker from local storage,
    combine them into a single string with headings for the lineage agent.
    Also prints available files and which one is picked for each log type.
    """
    ticker = ticker.upper()
    logs_dir = os.path.join(_project_root(), "logs")
    log_types = ["HFA", "COMP", "CAP"]
    combined_text = ""

    for log_type in log_types:
        log_type_dir = os.path.join(logs_dir, log_type)

        # Check if log type directory exists
        if not os.path.exists(log_type_dir):
            print(f"[{log_type}] Directory not found: {log_type_dir}")
            continue

        # Find all files matching the pattern for this ticker
        pattern = f"{log_type}_{ticker}_*.json"
        files = glob.glob(os.path.join(log_type_dir, pattern))

        if not files:
            print(f"[{log_type}] No files found for ticker {ticker}")
            continue

        print(f"[{log_type}] Files found for ticker {ticker}: {[os.path.basename(f) for f in files]}")

        # Sort by timestamp in filename descending
        def sort_key(path: str):
            # Filename format: LOGTYPE_TICKER_YYYYMMDD_HHMMSS.json
            name = os.path.basename(path)
            m = re.search(rf"{log_type}_{ticker}_(\d{{8}}_\d{{6}})\.json$", name)
            if not m:
                return 0
            ts_str = m.group(1)
            return int(ts_str.replace('_', ''))  # simple numeric sort YYYYMMDDHHMMSS

        files.sort(key=sort_key, reverse=True)
        latest_file = files[0]

        print(f"[{log_type}] Picking latest file: {os.path.basename(latest_file)}")

        try:
            with open(latest_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"[{log_type}] Failed to read file: {latest_file}. Error: {e}")
            continue

        heading_start = f"<--{log_type} Logs START-->"
        heading_end = f"<--{log_type} Logs END--/>"
        combined_text += f"{heading_start}\n{json.dumps(data, ensure_ascii=False, indent=2)}\n{heading_end}\n\n"

    if not combined_text:
        print(f"No logs found for ticker {ticker} in any log type.")

    return combined_text if combined_text else None



"""Chat-first agent; deterministic formatting helpers removed."""


def _load_system_prompt(prompt_path: Optional[str] = None) -> Optional[str]:
    prompt_path = prompt_path or os.path.join(_project_root(), "utils", "data-lineage-agent-prompt.yaml")
    if not os.path.exists(prompt_path):
        return None
    with open(prompt_path, "r", encoding="utf-8") as f:
        if yaml is None:
            return f.read()
        data = yaml.safe_load(f)
        if isinstance(data, dict):
            return data.get("system_prompt") or data.get("prompt") or None
        if isinstance(data, str):
            return data
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Data Lineage Agent (HFA logs) - Azure OpenAI Chat")
    parser.add_argument("ticker", help="Company ticker, e.g., ELME")
    # Optional positional initial question (backwards-friendly)
    parser.add_argument("question", nargs="*", help="Optional initial question (alternative to --initial)")
    parser.add_argument("--initial", nargs=argparse.REMAINDER, help="Optional initial user question for chat")
    args = parser.parse_args()

    # Lazy import inside main for optional deps
    def _load_env_from_dotenv():
        try:
            if load_dotenv is not None:
                # load .env from project root
                load_dotenv(os.path.join(_project_root(), ".env"))
        except Exception:
            pass

    def _openai_config() -> Tuple[Optional[str], Optional[str]]:
        _load_env_from_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        model = os.getenv("OPENAI_MODEL") or "gpt-4o"
        return api_key, model

    def start_chat_session_azure_openai(ticker: str, initial_question: Optional[str] = None):
        if OpenAI is None:
            print("OpenAI SDK is not installed. Please: pip install openai")
            return

        context_json = get_combined_json_data_from_local(ticker)
        if not context_json:
            print("No logs found in local storage for the requested ticker.")
            return


        system_prompt = _load_system_prompt() or (
            "You are a Data Lineage Assistant. Only use the provided JSON to answer."
        )

        api_key, model = _openai_config()
        if not api_key:
            print("OPENAI_API_KEY is not set. Configure it in .env or environment.")
            return

        client = OpenAI(
            api_key=api_key,
        )

        try:
            # Exclude __file_path__ so the model does not treat the JSON path as a source file
            
            base_messages: List[Dict[str, str]] = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Here are the latest JSON logs for ticker {ticker}. Use only this content to answer future questions.\n\n"
                        + context_json
                    ),
                },
            ]


            print("Context loaded from logs/HFA. Starting chat. Type 'exit' to quit.\n")
            # If user provided an initial question, send it immediately
            def _ask_and_stream(question: str):
                messages = base_messages + [{"role": "user", "content": question}]
                response = client.chat.completions.create(
                    stream=True,
                    messages=messages,
                    max_tokens=int(os.getenv("OPENAI_MAX_TOKENS", "2048")),
                    temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.0")),
                    top_p=float(os.getenv("OPENAI_TOP_P", "1.0")),
                    frequency_penalty=float(os.getenv("OPENAI_FREQ_PENALTY", "0.0")),
                    presence_penalty=float(os.getenv("OPENAI_PRES_PENALTY", "0.0")),
                    model=model,
                )
                try:
                    for update in response:
                        if hasattr(update, "choices") and update.choices:
                            delta = update.choices[0].delta
                            if delta and getattr(delta, "content", None):
                                print(delta.content, end="")
                    print("")
                finally:
                    try:
                        response.close()  # type: ignore[attr-defined]
                    except Exception:
                        pass

            if initial_question:
                _ask_and_stream(initial_question)

            while True:
                try:
                    user_in = input("You: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nExiting chat.")
                    break
                if not user_in:
                    continue
                if user_in.lower() in {"exit", "quit", "q"}:
                    break
                _ask_and_stream(user_in)
        finally:
            try:
                client.close()
            except Exception:
                pass

    initial = None
    if args.initial:
        initial = " ".join(args.initial).strip() or None
    elif args.question:
        initial = " ".join(args.question).strip() or None
    start_chat_session_azure_openai(args.ticker, initial)
