import request from "@/utils/request.js";
import proxy from "@/config/proxy.js";

const AGENT_PREFIX = "/ais/api/v1";
const env = import.meta.env.MODE || "development";
const apiHost = env === "mock" ? "" : proxy[env].host;

export const createConversation = (data = {}) => request({ url: `${AGENT_PREFIX}/conversations`, method: "post", data });
export const listConversations = () => request({ url: `${AGENT_PREFIX}/conversations`, method: "get" });
export const getConversationMessages = id => request({ url: `${AGENT_PREFIX}/conversations/${id}/messages`, method: "get" });
export const deleteConversation = id => request({ url: `${AGENT_PREFIX}/conversations/${id}`, method: "delete" });
export const confirmAgentAction = id => request({ url: `${AGENT_PREFIX}/actions/${id}/confirm`, method: "post" });
export const cancelAgentAction = id => request({ url: `${AGENT_PREFIX}/actions/${id}/cancel`, method: "post" });
export const submitAgentFeedback = (id, data) => request({ url: `${AGENT_PREFIX}/messages/${id}/feedback`, method: "post", data });

export function streamAgentMessage(conversationId, payload, handlers = {}) {
  const controller = new AbortController();
  const token = sessionStorage.getItem("token") || "";
  const authorization = token ? (token.startsWith("Bearer ") ? token : `Bearer ${token}`) : "";
  fetch(`${apiHost}${AGENT_PREFIX}/conversations/${conversationId}/messages:stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: authorization, Accept: "text/event-stream" },
    body: JSON.stringify(payload),
    signal: controller.signal,
  }).then(async response => {
    if (!response.ok) throw new Error(`AI 助教请求失败 (${response.status})`);
    if (!response.body) throw new Error("AI 助教未返回流式内容");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() || "";
      blocks.forEach(block => {
        const eventName = block.match(/^event:\s*(.+)$/m)?.[1] || "message";
        const eventId = block.match(/^id:\s*(.+)$/m)?.[1] || "";
        const data = block.split(/\r?\n/).filter(line => line.startsWith("data:")).map(line => line.slice(5).trim()).join("\n");
        if (!data) return;
        try {
          const parsed = JSON.parse(data);
          handlers.event?.({ eventId, type: eventName, envelope: parsed });
          (handlers[eventName] || handlers.message)?.(parsed?.data ?? parsed);
        } catch {
          handlers.error?.(new Error("AI 助教返回格式错误"));
        }
      });
    }
  }).catch(error => {
    if (error.name !== "AbortError") handlers.error?.(error);
  }).finally(() => handlers.end?.());
  return () => controller.abort();
}
