"""
chat_client.py -- Terminal client for backend /chat/structured.

Memory model:
  - `messages` = chat history (user/assistant turns)
  - `facts`    = persistent extracted memory
  - Har request pe `memory` field bhejte hain taaki model system prompt me
    facts dekh sake (warna sirf store hota tha, recall nahi hota tha)
"""

import json
import requests

BACKEND_URL = "http://localhost:5000/chat/structured"

messages: list[dict] = []

facts: dict[str, list[str]] = {
    "entities": [],
    "facts_about_user": [],
    "constraints": [],
}


def merge_facts(new_facts: dict):
    if not isinstance(new_facts, dict):
        return
    for category, new_items in new_facts.items():
        if category not in facts:
            facts[category] = []
        if not isinstance(new_items, list):
            continue
        for item in new_items:
            if not item:
                continue
            # case-insensitive dedupe
            existing_lower = {x.lower() for x in facts[category]}
            if item.lower() not in existing_lower:
                facts[category].append(item)


def has_memory() -> bool:
    return any(facts.get(k) for k in facts)


def print_facts_summary():
    if not has_memory():
        print("\n(Abhi tak koi memory/facts nahi)\n")
        return
    print("\n--- MEMORY (persistent) ---")
    for category, items in facts.items():
        if items:
            print(f"  {category}: {items}")
    print("---------------------------\n")


def send_query(user_input: str) -> tuple[str, dict]:
    messages.append({"role": "user", "content": user_input})

    # IMPORTANT: pehle se jami memory bhejo (is turn se pehle wali)
    payload = {
        "messages": messages,
        "memory": {
            "entities": list(facts["entities"]),
            "facts_about_user": list(facts["facts_about_user"]),
            "constraints": list(facts["constraints"]),
        },
    }

    try:
        response = requests.post(BACKEND_URL, json=payload, timeout=180)
        if response.status_code != 200:
            try:
                error_body = response.json()
            except Exception:
                error_body = response.text
            print(f"\n[BACKEND ERROR {response.status_code}]: {error_body}\n")
            messages.pop()
            response.raise_for_status()

        data = response.json()
    except Exception:
        if messages and messages[-1].get("role") == "user":
            messages.pop()
        raise

    answer = data.get("answer", "")
    extracted = data.get("extracted_facts") or {}
    # is turn ke naye facts persistent memory me merge
    merge_facts(extracted)

    messages.append({"role": "assistant", "content": answer})
    return answer, extracted


def main():
    print("Chat shuru.")
    print("  facts  = memory dekho")
    print("  clear  = memory + history wipe")
    print("  exit   = band\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("Bye!")
            break
        if user_input.lower() == "facts":
            print_facts_summary()
            continue
        if user_input.lower() == "clear":
            messages.clear()
            for k in facts:
                facts[k] = []
            print("\n(Memory + history clear)\n")
            continue

        try:
            answer, turn_facts = send_query(user_input)
            print(f"\nBot: {answer}\n")
            print("--- this turn new facts ---")
            print(json.dumps(turn_facts, indent=2, ensure_ascii=False))
            print("--- full memory ---")
            print(json.dumps(facts, indent=2, ensure_ascii=False))
            print("-------------------------\n")
        except requests.exceptions.RequestException as e:
            print(f"\n[ERROR] Backend se connect nahi ho paya: {e}\n")
        except Exception as e:
            print(f"\n[ERROR] {e}\n")


if __name__ == "__main__":
    main()







