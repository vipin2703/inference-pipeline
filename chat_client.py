# """
# chat_client.py -- Terminal se backend ke /chat endpoint pe query bhejta rahega
# jab tak tu 'exit', 'quit', ya Ctrl+C se rok na de.

# NOTE: temperature/max_tokens client se nahi bheje jaate -- ye model
# behavior control backend (schemas.py defaults) ke haath me hai, client
# sirf user ka message bhejta hai.
# """

# import requests

# BACKEND_URL = "http://localhost:5000/chat"  # apne backend ka URL/port yaha set karo

# # Conversation history yaha store hoga taaki backend ko context mile
# messages = []

# def send_query(user_input: str) -> str:
#     messages.append({"role": "user", "content": user_input})

#     payload = {
#         "messages": messages,
#     }

#     response = requests.post(BACKEND_URL, json=payload, timeout=120)
    
#     response.raise_for_status()
#     data = response.json()
#     # print(data)

#     reply = data["response"]
#     # messages.append({"role": "assistant", "content": reply}) #### ye tb h agr merko dalna ho ki ai can mistakes
    
#     return reply


# def main():
#     print("Chat shuru ho gaya. Rokne ke liye 'exit' ya 'quit' likho (ya Ctrl+C dabao).\n")

#     while True:
#         try:
#             user_input = input("You: ").strip()
#         except (KeyboardInterrupt, EOFError):
#             print("\nBand ho raha hai. Bye!")
#             break

#         if not user_input:
#             continue

#         if user_input.lower() in ("exit", "quit"):
#             print("Bye!")
#             break

#         try:
#             reply = send_query(user_input)
#             print(f"Bot: {reply}\n")
#         except requests.exceptions.RequestException as e:
#             print(f"[ERROR] Backend se connect nahi ho paya: {e}\n")


# if __name__ == "__main__":
#     main()














"""
chat_client.py -- Terminal se backend ke /chat/stream endpoint pe query bhejta
rahega jab tak tu 'exit', 'quit', ya Ctrl+C se rok na de.

Ye backend se SSE (Server-Sent Events) format me streaming response leta hai
aur usse live, word-by-word terminal me print karta hai.
"""

import requests

BACKEND_URL = "http://localhost:5000/chat/stream"  # apne backend ka URL/port yaha set karo

# Conversation history yaha store hoga taaki backend ko context mile
messages = []


def send_query_stream(user_input: str) -> str:
    """
    Backend ko streaming request bhejta hai aur SSE chunks ko live print karta
    hai. Poora assembled response string return karta hai taaki history me
    append ho sake.
    """
    messages.append({"role": "user", "content": user_input})

    payload = {
        "messages": messages,
    }

    full_response = ""

    with requests.post(BACKEND_URL, json=payload, stream=True, timeout=120) as response:
        response.raise_for_status()

        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue  # SSE me blank lines aati hain, skip karo

            # SSE format: "data: <content>"
            if line.startswith("data: "):
                chunk = line[len("data: "):]

                if chunk == "[DONE]":
                    break

                if chunk.startswith("[ERROR]"):
                    raise RuntimeError(chunk)

                print(chunk, end="", flush=True)
                full_response += chunk

    print()  # stream khatam hone ke baad newline
    messages.append({"role": "assistant", "content": full_response})
    return full_response


def main():
    print("Chat shuru ho gaya. Rokne ke liye 'exit' ya 'quit' likho (ya Ctrl+C dabao).\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBand ho raha hai. Bye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Bye!")
            break

        try:
            print("Bot: ", end="", flush=True)
            send_query_stream(user_input)
            print()
        except requests.exceptions.RequestException as e:
            print(f"\n[ERROR] Backend se connect nahi ho paya: {e}\n")
        except RuntimeError as e:
            print(f"\n[ERROR] {e}\n")


if __name__ == "__main__":
    main()