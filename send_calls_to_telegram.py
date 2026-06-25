import argparse
import html
import json
import os
import re
import urllib.parse
import urllib.request
import uuid
from typing import Dict, List, Tuple


DEFAULT_SELECTION_FILE = "selected_calls.json"
MAX_TELEGRAM_TEXT = 3800


def load_dotenv(dotenv_path: str) -> None:
    if not os.path.exists(dotenv_path):
        return
    for raw_line in read_text(dotenv_path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def extract_call_datetime(file_name: str) -> str:
    base = os.path.basename(file_name)
    match = re.match(r"(\d{4}-\d{2}-\d{2})__(\d{2}-\d{2}-\d{2})__", base)
    if not match:
        return "unknown"
    date_part, time_part = match.groups()
    return f"{date_part} {time_part.replace('-', ':')}"


def parse_html_transcript(file_path: str) -> List[Tuple[str, str]]:
    src = read_text(file_path)
    rows = re.findall(
        r"<tr>\s*<td><strong>(.*?)</strong></td>.*?<td style=\"width: 70%\">(.*?)</td>\s*</tr>",
        src,
        flags=re.IGNORECASE | re.DOTALL,
    )

    transcript = []
    for speaker, text_block in rows:
        cleaned = re.sub(r"<br\s*/?>", "\n", text_block, flags=re.IGNORECASE)
        cleaned = re.sub(r"<.*?>", "", cleaned, flags=re.DOTALL)
        cleaned = html.unescape(cleaned)
        cleaned = "\n".join(line.strip() for line in cleaned.splitlines() if line.strip())
        if cleaned:
            transcript.append((speaker.strip(), cleaned))
    return transcript


def build_message_chunks(header: str, transcript: List[Tuple[str, str]]) -> List[str]:
    body_lines = [f"{speaker}: {text}" for speaker, text in transcript]
    full_text = header + "\n\n" + "\n".join(body_lines)

    if len(full_text) <= MAX_TELEGRAM_TEXT:
        return [full_text]

    chunks: List[str] = []
    current = header + "\n\n"
    part_num = 1

    for line in body_lines:
        candidate = current + line + "\n"
        if len(candidate) <= MAX_TELEGRAM_TEXT:
            current = candidate
            continue

        chunks.append(current.rstrip() + f"\n\n(часть {part_num})")
        part_num += 1
        current = header + "\n\n" + line + "\n"

        if len(current) > MAX_TELEGRAM_TEXT:
            slices = [line[i : i + 1500] for i in range(0, len(line), 1500)]
            current = header + "\n\n"
            for idx, slc in enumerate(slices):
                candidate_slice = current + slc + "\n"
                if len(candidate_slice) > MAX_TELEGRAM_TEXT:
                    chunks.append(current.rstrip() + f"\n\n(часть {part_num})")
                    part_num += 1
                    current = header + "\n\n" + slc + "\n"
                else:
                    current = candidate_slice
                if idx == len(slices) - 1:
                    continue

    if current.strip():
        chunks.append(current.rstrip() + f"\n\n(часть {part_num})")

    return chunks


def tg_send_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")

    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8")
    if '"ok":true' not in body:
        raise RuntimeError(f"Telegram API error: {body}")


def tg_send_document(bot_token: str, chat_id: str, file_path: str, caption: str) -> None:
    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    file_name = os.path.basename(file_path)
    file_bytes = open(file_path, "rb").read()

    def part_text(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    body = bytearray()
    body.extend(part_text("chat_id", chat_id))
    body.extend(part_text("caption", caption[:1024]))
    body.extend(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="document"; filename="{file_name}"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    req = urllib.request.Request(
        url,
        data=bytes(body),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp_body = resp.read().decode("utf-8")
    if '"ok":true' not in resp_body:
        raise RuntimeError(f"Telegram API error: {resp_body}")


def load_selection(selection_path: str) -> List[Dict[str, str]]:
    raw = read_text(selection_path)
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("selected_calls.json must contain a JSON array")
    result: List[Dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if "file" not in item:
            continue
        result.append(
            {
                "file": str(item["file"]),
                "category": str(item.get("category", "Без категории")),
            }
        )
    return result


def short_problem_comment(category: str) -> str:
    c = category.lower()
    if "техсбой" in c or "техпроблем" in c:
        return "Проблема: сбой онлайн-записи; клиент теряет доверие и нужен быстрый ручной дожим."
    if "не записался" in c or "без записи" in c or "уход без записи" in c:
        return "Проблема: лид не закрыт в запись после звонка."
    if "цена" in c:
        return "Проблема: риск потери на этапе цены; не всегда сделан дожим до конкретного слота."
    if "отказ" in c:
        return "Проблема: отказ в услуге без сильной альтернативы может приводить к потере клиента."
    if "отмена" in c or "перенос" in c or "перезапис" in c:
        return "Проблема: перенос/отмена; важно фиксировать новую дату сразу в звонке."
    if "неудобное время" in c:
        return "Проблема: неудобное время; нужно предлагать 2-3 релевантных окна и закреплять запись."
    if "новый клиент" in c:
        return "Фокус: первый контакт; важно удержать теплый тон и довести до записи."
    return "Проблема: звонок требует ручного контроля качества и корректного закрытия в запись."


def write_transcript_file(
    export_dir: str,
    idx: int,
    total: int,
    file_name: str,
    category: str,
    transcript: List[Tuple[str, str]],
) -> str:
    os.makedirs(export_dir, exist_ok=True)
    dt = extract_call_datetime(file_name)
    problem = short_problem_comment(category)
    out_name = f"{idx:02d}_{os.path.splitext(os.path.basename(file_name))[0]}.txt"
    out_path = os.path.join(export_dir, out_name)
    lines = [
        f"Звонок {idx}/{total}",
        f"Файл: {file_name}",
        f"Дата/время: {dt}",
        f"Категория: {category}",
        f"Комментарий: {problem}",
        "",
        "Полная расшифровка:",
        "",
    ]
    for speaker, text in transcript:
        lines.append(f"{speaker}: {text}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).strip() + "\n")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send selected call transcripts to Telegram."
    )
    parser.add_argument(
        "--selection-file",
        default=DEFAULT_SELECTION_FILE,
        help="Path to JSON file with selected calls.",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Base directory where call HTML files are located.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not send to Telegram, only print summary.",
    )
    parser.add_argument(
        "--dotenv",
        default=".env",
        help="Path to .env file with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.",
    )
    parser.add_argument(
        "--send-as-files",
        action="store_true",
        help="Send each call as a separate .txt document with a short problem comment.",
    )
    parser.add_argument(
        "--export-dir",
        default="telegram_exports",
        help="Directory for generated .txt files when --send-as-files is used.",
    )
    args = parser.parse_args()

    load_dotenv(os.path.join(args.base_dir, args.dotenv))
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not args.dry_run and (not bot_token or not chat_id):
        raise SystemExit(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables first."
        )

    selection_path = os.path.join(args.base_dir, args.selection_file)
    selected = load_selection(selection_path)

    if not selected:
        raise SystemExit("No calls found in selection file.")

    sent_messages = 0
    sent_documents = 0
    for idx, item in enumerate(selected, start=1):
        file_name = item["file"]
        category = item["category"]
        html_path = os.path.join(args.base_dir, file_name)
        if not os.path.exists(html_path):
            print(f"[WARN] Missing file: {file_name}")
            continue

        transcript = parse_html_transcript(html_path)
        if not transcript:
            print(f"[WARN] No transcript rows parsed: {file_name}")
            continue
        if args.dry_run:
            if args.send_as_files:
                print(f"[DRY-RUN] {file_name} -> document")
            else:
                call_dt = extract_call_datetime(file_name)
                header = (
                    f"Звонок {idx}/{len(selected)}\n"
                    f"Категория: {category}\n"
                    f"Дата/время: {call_dt}\n"
                    f"Файл: {file_name}"
                )
                chunks = build_message_chunks(header, transcript)
                print(f"[DRY-RUN] {file_name} -> {len(chunks)} msg")
            continue

        if args.send_as_files:
            out_path = write_transcript_file(
                export_dir=os.path.join(args.base_dir, args.export_dir),
                idx=idx,
                total=len(selected),
                file_name=file_name,
                category=category,
                transcript=transcript,
            )
            caption = (
                f"Звонок {idx}/{len(selected)}\n"
                f"{os.path.basename(file_name)}\n"
                f"{short_problem_comment(category)}"
            )
            tg_send_document(bot_token, chat_id, out_path, caption)
            sent_documents += 1
            print(f"[OK] Sent document: {file_name}")
        else:
            call_dt = extract_call_datetime(file_name)
            header = (
                f"Звонок {idx}/{len(selected)}\n"
                f"Категория: {category}\n"
                f"Дата/время: {call_dt}\n"
                f"Файл: {file_name}"
            )
            chunks = build_message_chunks(header, transcript)
            for chunk in chunks:
                tg_send_message(bot_token, chat_id, chunk)
                sent_messages += 1
            print(f"[OK] Sent: {file_name} ({len(chunks)} msg)")

    if args.dry_run:
        print("Dry-run complete.")
    else:
        if args.send_as_files:
            print(f"Done. Sent {sent_documents} Telegram documents.")
        else:
            print(f"Done. Sent {sent_messages} Telegram messages.")


if __name__ == "__main__":
    main()
