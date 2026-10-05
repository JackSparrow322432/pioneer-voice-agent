"""
Текстовый симулятор: проверка скрипта и инструментов БЕЗ звонков (стоит копейки).
Вы играете клиента в терминале, агент отвечает текстом.

    python chat_sim.py                 # исходящий звонок
    python chat_sim.py --inbound       # входящий
"""
import argparse
import json

from openai import OpenAI

import config
import db
from prompt import build_instructions, greeting_trigger
from tools import chat_tool_schemas, run_tool


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbound", action="store_true")
    ap.add_argument("--name", default="Асель")
    ap.add_argument("--reason", default="оставила заявку на сайте на зимний лагерь для сына 9 лет")
    a = ap.parse_args()

    db.init()
    direction = "inbound" if a.inbound else "outbound"
    ctx = {"call_sid": "SIM-" + db.now(), "phone": "+70000000000"}
    db.upsert_call(ctx["call_sid"], direction=direction, phone=ctx["phone"], lead_name=a.name, status="simulation")

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    msgs = [{"role": "system", "content": build_instructions(direction, a.name, a.reason)},
            {"role": "user", "content": greeting_trigger(direction)}]
    print("Симуляция. Пишите как клиент (по-русски или по-казахски). Выход: Ctrl+C\n")

    while True:
        r = client.chat.completions.create(model=config.SIM_MODEL, messages=msgs, tools=chat_tool_schemas())
        m = r.choices[0].message
        msgs.append(m.model_dump(exclude_none=True))
        if m.tool_calls:
            ended = False
            for tc in m.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                res = run_tool(tc.function.name, args, ctx)
                print(f"  ⚙ {tc.function.name}({json.dumps(args, ensure_ascii=False)})")
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(res, ensure_ascii=False)})
                ended |= tc.function.name == "end_call"
            if m.content:
                print(f"АГЕНТ: {m.content}")
            if ended:
                print("\n[звонок завершён]")
                return
            continue
        print(f"АГЕНТ: {m.content}")
        db.add_transcript(ctx["call_sid"], "agent", m.content or "")
        user = input("ВЫ: ")
        db.add_transcript(ctx["call_sid"], "client", user)
        msgs.append({"role": "user", "content": user})


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
