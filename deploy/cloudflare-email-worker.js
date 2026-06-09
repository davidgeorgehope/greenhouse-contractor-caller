export default {
  async email(message, env, ctx) {
    const raw = await new Response(message.raw).text();
    const subject = message.headers.get("subject") || "";
    const messageId = message.headers.get("message-id") || "";
    const text = raw
      .replace(/\r\n/g, "\n")
      .split("\n\n")
      .slice(1)
      .join("\n\n")
      .trim();

    ctx.waitUntil(
      fetch(env.CONTRACTOR_EMAIL_WEBHOOK_URL, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${env.CONTRACTOR_EMAIL_INGEST_SECRET}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          from: message.from,
          to: message.to,
          subject,
          text,
          message_id: messageId,
          raw,
        }),
      }),
    );
  },
};
