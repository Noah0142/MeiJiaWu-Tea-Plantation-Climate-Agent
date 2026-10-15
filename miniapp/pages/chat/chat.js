// 农事助手: 多轮对话(复用后端 /api/chat, 回答基于微气候模型预报)
const api = require("../../utils/api");

const WELCOME = "您好! 我是梅家坞茶园微气候助手, 可以问我: 会不会有霜冻? 要不要覆盖防霜布? 什么时候可以采摘?";

Page({
  data: {
    messages: [{ id: 0, role: "agent", content: WELCOME }],
    quick: ["明后两天凌晨会有霜冻吗?", "要不要盖防霜布?", "什么时候可以采摘?", "最近要不要浇水?"],
    draft: "",
    sending: false,
    engine: "",
    scrollTo: "",
  },

  onLoad() {
    // 恢复上一次会话(本机缓存)
    const saved = wx.getStorageSync("chatHistory");
    if (saved && Array.isArray(saved) && saved.length) {
      this.setData({ messages: saved, engine: wx.getStorageSync("chatEngine") || "" });
      this.scrollBottom();
    }
  },

  onInput(e) {
    this.setData({ draft: e.detail.value });
  },

  onQuick(e) {
    const q = e.currentTarget.dataset.q;
    this.setData({ draft: q });
    this.send();
  },

  async send() {
    const text = (this.data.draft || "").trim();
    if (!text || this.data.sending) return;
    const id = Date.now();
    const messages = this.data.messages.concat([{ id, role: "user", content: text }]);
    this.setData({ messages, draft: "", sending: true });
    this.scrollBottom(id);

    try {
      // 携带最近 10 条作为上下文
      const history = messages.slice(-11, -1).map((m) => ({ role: m.role, content: m.content }));
      const payload = history.concat([{ role: "user", content: text }]);
      const d = await api.chat(payload);
      const reply = {
        id: id + 1,
        role: "agent",
        content: d.reply || "暂时无法回答, 请稍后再试",
      };
      this.setData({
        messages: this.data.messages.concat([reply]),
        sending: false,
        engine: d.engine || "",
      });
      // 会话写入本机缓存(最多 50 条)
      const keep = this.data.messages.slice(-50);
      wx.setStorageSync("chatHistory", keep);
      wx.setStorageSync("chatEngine", this.data.engine);
    } catch (e) {
      this.setData({
        messages: this.data.messages.concat([
          { id: id + 2, role: "agent", content: `回答失败: ${e.message}\n请检查"数据接入"页的服务器地址是否可用。` },
        ]),
        sending: false,
      });
    }
    this.scrollBottom();
  },

  scrollBottom(id) {
    const target = id || (this.data.messages.length ? this.data.messages[this.data.messages.length - 1].id : 0);
    this.setData({ scrollTo: `msg-${target}` });
  },

  clearChat() {
    wx.showModal({
      title: "清空对话",
      content: "确定清空当前对话记录吗?",
      success: (r) => {
        if (r.confirm) {
          wx.removeStorageSync("chatHistory");
          wx.removeStorageSync("chatEngine");
          this.setData({ messages: [{ id: 0, role: "agent", content: WELCOME }], engine: "" });
        }
      },
    });
  },
});
