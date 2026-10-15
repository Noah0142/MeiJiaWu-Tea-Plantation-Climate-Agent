// 气温预报图组件: canvas 2d 绘制 P10–P90 区间带 + P50 曲线 (+ 可选参照虚线)
// 用法: <line-chart id="chart" hours="{{chartHours}}" ref="{{chartRef}}" />
const { palette } = require("../../utils/format");

Component({
  properties: {
    // [{ label: "10-13 23时", p10, p50, p90 }]
    hours: { type: Array, value: [] },
    // 参照线数值数组(与 hours 对齐, 可为 null), 如监测点 LightGBM 对照
    ref: { type: Array, value: [] },
    refName: { type: String, value: "对照" },
  },

  data: { canvasW: 0, canvasH: 220 },

  lifetimes: {
    ready() {
      this.initCanvas();
    },
  },

  observers: {
    "hours, ref": function () {
      this.draw();
    },
  },

  methods: {
    initCanvas() {
      const query = this.createSelectorQuery();
      query
        .select("#chart")
        .fields({ node: true, size: true })
        .exec((res) => {
          if (!res || !res[0] || !res[0].node) return;
          const canvas = res[0].node;
          const ctx = canvas.getContext("2d");
          // DPR 从 getWindowInfo 获取(getAppBaseInfo 无 pixelRatio 字段)
          const win = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
          const dpr = win.pixelRatio || 2;
          this.canvas = canvas;
          this.ctx = ctx;
          this.cssW = res[0].width;
          this.cssH = res[0].height;
          canvas.width = res[0].width * dpr;
          canvas.height = res[0].height * dpr;
          ctx.scale(dpr, dpr);
          this.draw();
        });
    },

    draw() {
      const ctx = this.ctx;
      const hours = this.data.hours || [];
      if (!ctx || !hours.length) return;
      const W = this.cssW;
      const H = this.cssH;
      const P = palette();

      ctx.clearRect(0, 0, W, H);

      const padL = 46;
      const padR = 14;
      const padT = 18;
      const padB = 34;
      const plotW = W - padL - padR;
      const plotH = H - padT - padB;

      // ---- 数值范围(含区间与参照线) ----
      const lows = hours.map((h) => h.p10).filter((v) => v != null);
      const highs = hours.map((h) => h.p90).filter((v) => v != null);
      const refs = (this.data.ref || []).filter((v) => v != null);
      let min = Math.min(...lows, ...refs);
      let max = Math.max(...highs, ...refs);
      if (!isFinite(min) || !isFinite(max)) return;
      const span = Math.max(max - min, 2);
      min = Math.floor(min - span * 0.08);
      max = Math.ceil(max + span * 0.08);
      const y = (v) => padT + plotH - ((v - min) / (max - min)) * plotH;
      const x = (i) => padL + (plotW * i) / Math.max(hours.length - 1, 1);

      // ---- 水平网格 + Y 轴刻度 ----
      ctx.strokeStyle = P.grid;
      ctx.fillStyle = P.muted;
      ctx.lineWidth = 1;
      ctx.font = "10px sans-serif";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      const ticks = 4;
      for (let t = 0; t <= ticks; t++) {
        const v = min + ((max - min) * t) / ticks;
        const yy = y(v);
        ctx.beginPath();
        ctx.moveTo(padL, yy);
        ctx.lineTo(W - padR, yy);
        ctx.stroke();
        ctx.fillText(`${Math.round(v)}℃`, padL - 8, yy);
      }

      // ---- P10–P90 区间带 ----
      ctx.beginPath();
      hours.forEach((h, i) => {
        const yy = y(h.p90);
        i === 0 ? ctx.moveTo(x(i), yy) : ctx.lineTo(x(i), yy);
      });
      for (let i = hours.length - 1; i >= 0; i--) {
        ctx.lineTo(x(i), y(hours[i].p10));
      }
      ctx.closePath();
      ctx.fillStyle = P.band;
      ctx.fill();

      // ---- 参照线(虚线) ----
      const ref = this.data.ref || [];
      if (ref.some((v) => v != null)) {
        ctx.beginPath();
        ctx.setLineDash([5, 4]);
        ctx.strokeStyle = P.frost;
        ctx.lineWidth = 1.4;
        let started = false;
        ref.forEach((v, i) => {
          if (v == null) return;
          const yy = y(v);
          if (!started) { ctx.moveTo(x(i), yy); started = true; }
          else ctx.lineTo(x(i), yy);
        });
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // ---- P50 曲线 ----
      ctx.beginPath();
      ctx.strokeStyle = P.primary;
      ctx.lineWidth = 2.2;
      hours.forEach((h, i) => {
        const yy = y(h.p50);
        i === 0 ? ctx.moveTo(x(i), yy) : ctx.lineTo(x(i), yy);
      });
      ctx.stroke();

      // ---- X 轴标签(约 4 个, 等距) ----
      ctx.fillStyle = P.muted;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      const step = Math.max(Math.floor(hours.length / 4), 1);
      for (let i = 0; i < hours.length; i += step) {
        ctx.fillText(hours[i].label, Math.min(Math.max(x(i), 30), W - 30), H - padB + 10);
      }
    },
  },
});
