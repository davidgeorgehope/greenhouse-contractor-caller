from __future__ import annotations

from .db import connect


def main() -> None:
    with connect() as conn:
        print("Leads")
        for row in conn.execute(
            """
            SELECT id, status, priority, name, phone, drive_minutes, distance_miles, origin_address
            FROM leads
            ORDER BY priority DESC, id
            """
        ):
            drive = f"{row['drive_minutes']} min" if row["drive_minutes"] is not None else "-"
            miles = f"{row['distance_miles']:.1f} mi" if row["distance_miles"] is not None else "-"
            print(
                f"{row['id']:2} {row['status']:10} {row['priority']:3} {drive:>7} {miles:>8} "
                f"{row['name']} {row['phone']} {row['origin_address'] or ''}"
            )
        print()
        print("Calls")
        for row in conn.execute(
            "SELECT id, lead_id, status, outcome, summary, twilio_sid, created_at FROM calls ORDER BY id DESC LIMIT 20"
        ):
            summary = (row["summary"] or "").replace("\n", " ")[:120]
            print(f"{row['id']:2} lead={row['lead_id']:2} {row['status']:12} {row['twilio_sid'] or '-'} {summary}")
        print()
        print("Texts")
        for row in conn.execute(
            """
            SELECT id, direction, from_number, to_number, body, status, twilio_sid, created_at
            FROM sms_messages
            ORDER BY id DESC
            LIMIT 20
            """
        ):
            body = (row["body"] or "").replace("\n", " ")[:120]
            channel = "twilio" if row["twilio_sid"] else "imsg" if row["status"] == "imsg_sent" else "manual"
            print(
                f"{row['id']:2} {channel:6} {row['direction']:8} {row['from_number']} -> {row['to_number']} "
                f"{row['status'] or '-':10} {row['twilio_sid'] or '-'} {body}"
            )


if __name__ == "__main__":
    main()
