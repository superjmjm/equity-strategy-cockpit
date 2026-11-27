/* Production Frontend Logic for Equity Strategy Workbench */
const App = (() => {
  const DEFAULT_DATA_URL = "./snapshot.json";
  const CART_STORAGE_KEY = "equity_cockpit_briefing_cart_v1";
  const THEME_STORAGE_KEY = "equity_cockpit_theme_v1";

  const state = {
    snapshot: null,
    currentWeek: null,
    pool: "all", // 'all' | 'core'
    tab: "macro",
    ddmFilter: "all",
    nuggetFilter: "all",
    stockFilter: "all",
    selectedSectorId: null,
    cart: [],
    lookup: {}
  };

  function esc(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function resolveDataUrl() {
    const params = new URLSearchParams(window.location.search);
    const custom = params.get("data");
    if (custom && /^https:\/\/raw\.githubusercontent\.com\/[\w.-]+\/[\w.-]+\/.+\.json$/i.test(custom)) {
      return custom;
    }
    return DEFAULT_DATA_URL;
  }

  function loadPersisted() {
    try {
      const savedCart = JSON.parse(localStorage.getItem(CART_STORAGE_KEY) || "[]");
      if (Array.isArray(savedCart)) state.cart = savedCart;
    } catch (_) {}
    const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    if (savedTheme === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
      const btn = document.getElementById("btn-theme");
      if (btn) btn.textContent = "日间";
    }
  }

  function saveCart() {
    try {
      localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(state.cart));
    } catch (_) {}
  }

  function toggleTheme() {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    if (isDark) {
      document.documentElement.removeAttribute("data-theme");
      localStorage.setItem(THEME_STORAGE_KEY, "light");
      document.getElementById("btn-theme").textContent = "夜间";
    } else {
      document.documentElement.setAttribute("data-theme", "dark");
      localStorage.setItem(THEME_STORAGE_KEY, "dark");
      document.getElementById("btn-theme").textContent = "日间";
    }
    if (state.tab === "sector") renderSectorQuadrant();
  }

  function weekData() {
    if (!state.snapshot || !state.currentWeek) return null;
    return state.snapshot.weeks[state.currentWeek] || null;
  }

  function rebuildLookup() {
    state.lookup = {};
    if (!state.snapshot) return;
    Object.values(state.snapshot.weeks || {}).forEach((wk) => {
      (wk.marginal_shifts || []).forEach((s) => {
        state.lookup[s.id] = {
          id: s.id,
          type: "边际转向信号",
          title: `${s.broker}：${s.from_label} → ${s.to_label}`,
          summary: s.summary,
          broker: s.broker,
          report_title: s.report_title,
          report_date: s.report_date,
          drive_file_id: s.drive_file_id,
          evidence: s.evidence || [],
          schema: s.schema_preview
        };
      });
      (wk.ddm_claims || []).forEach((c) => {
        state.lookup[c.id] = {
          id: c.id,
          type: c.side === "bull" ? `多方论据 (${c.pillar_label})` : `谨慎顾虑 (${c.pillar_label})`,
          title: c.title,
          summary: `共振机构：${(c.brokers_all || []).join("、")}`,
          broker: c.lead_broker,
          report_title: c.report_title,
          report_date: c.report_date,
          drive_file_id: c.drive_file_id,
          evidence: c.evidence || [],
          schema: c.schema_preview
        };
      });
      (wk.sector_matrix || []).forEach((sec) => {
        state.lookup[sec.id] = {
          id: sec.id,
          type: "中观行业主线",
          title: `${sec.sw_name} (${sec.narrative_label}) · ${sec.quadrant}`,
          summary: `看多催化：${sec.bull_logic} | 分歧提示：${sec.bear_logic}`,
          broker: sec.lead_broker,
          report_title: sec.report_title,
          report_date: sec.report_date,
          drive_file_id: sec.drive_file_id,
          evidence: sec.evidence || [],
          schema: sec.schema_preview
        };
      });
      (wk.data_nuggets || []).forEach((n) => {
        state.lookup[n.id] = {
          id: n.id,
          type: "增量数据抓手",
          title: `[${n.metric_phrase}] ${n.implication}`,
          summary: `来源：${n.broker}《${n.report_title}》P.${n.primary_page}`,
          broker: n.broker,
          report_title: n.report_title,
          report_date: n.report_date,
          drive_file_id: n.drive_file_id,
          evidence: n.evidence || [],
          schema: n.schema_preview
        };
      });
      (wk.golden_stocks || []).forEach((st) => {
        state.lookup[st.id] = {
          id: st.id,
          type: "策略金股标的",
          title: `${st.stock_name} (${st.stock_code}) · ${st.status_label}`,
          summary: `${st.role_label} — ${st.logic}`,
          broker: st.lead_broker,
          report_title: st.report_title,
          report_date: st.report_date,
          drive_file_id: st.drive_file_id,
          evidence: st.evidence || [],
          schema: st.schema_preview
        };
      });
    });
  }

  function setPool(pool) {
    state.pool = pool;
    document.getElementById("btn-pool-all").classList.toggle("active", pool === "all");
    document.getElementById("btn-pool-core").classList.toggle("active", pool === "core");
    renderAll();
  }

  function switchTab(tab) {
    state.tab = tab;
    ["macro", "sector", "evidence", "stocks"].forEach((t) => {
      document.getElementById("panel-" + t).classList.toggle("hidden", t !== tab);
      document.getElementById("tab-" + t).classList.toggle("active", t === tab);
    });
    if (tab === "sector") {
      renderSectorQuadrant();
      renderSectorInspector();
    }
  }

  function setDdmFilter(f) {
    state.ddmFilter = f;
    document.querySelectorAll("#ddm-filter-group .seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.ddm === f);
    });
    renderDdmCollider();
  }

  function setNuggetFilter(f) {
    state.nuggetFilter = f;
    document.querySelectorAll("#nugget-filter-group .seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.nug === f);
    });
    renderEvidenceTab();
  }

  function setStockFilter(f) {
    state.stockFilter = f;
    document.querySelectorAll("#stock-filter-group .seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.stk === f);
    });
    renderStocksTab();
  }

  /* ==================== TAB 1 RENDER ==================== */
  function renderMacroTab() {
    const wk = weekData();
    if (!wk) return;

    const syn = wk.synthesis || {};
    document.getElementById("clash-summary-banner").innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
        <span class="pill tone-info">买方首席周度交锋提炼</span>
        <span style="font-size:12px;color:var(--muted);">覆盖当周 ${wk.report_count} 篇策略报告 · 沪深300基准 <strong class="mono">${esc(state.snapshot.market_benchmark?.hs300_latest ?? "—")}</strong></span>
      </div>
      <div>${esc(syn.executive_clash_summary || "")}</div>
    `;

    const th = wk.thermometer[state.pool] || { total_voters: 0, segments: [] };
    document.getElementById("thermo-pool-pill").textContent =
      state.pool === "core" ? `★ 核心池投票 (${th.total_voters}家)` : `全样本投票 (${th.total_voters}家)`;

    document.getElementById("thermo-bar").innerHTML = th.segments
      .filter((s) => s.pct > 0)
      .map(
        (s) =>
          `<div class="seg-${s.tone}" style="width:${s.pct}%" title="${esc(s.label)}: ${s.count}家 (${s.pct}%)"></div>`
      )
      .join("");

    document.getElementById("thermo-legend").innerHTML = th.segments
      .map(
        (s) => `
        <div class="subcard" style="padding:8px 10px;display:flex;justify-content:space-between;align-items:center;font-size:12px;">
          <span style="color:var(--muted);">${esc(s.short)}</span>
          <strong class="mono">${s.count}家 (${Math.round(s.pct)}%)</strong>
        </div>`
      )
      .join("");

    document.getElementById("divergence-note-box").innerHTML = `
      <div style="font-size:12px;font-weight:600;margin-bottom:4px;">核心池 vs 全市场反身性校验</div>
      <div style="font-size:12px;color:var(--muted);line-height:1.55;">${esc(syn.core_vs_all_divergence_note || "")}</div>
    `;

    const shifts = (wk.marginal_shifts || []).filter((s) => state.pool === "all" || s.is_core);
    document.getElementById("shift-count-pill").textContent =
      shifts.length > 0 ? `捕获 ${shifts.length} 家转向信号` : "本周无显著转向";

    if (shifts.length === 0) {
      document.getElementById("shifts-grid").innerHTML = `
        <div class="subcard" style="grid-column:1/-1;color:var(--muted);font-size:12px;text-align:center;padding:24px;">
          当前筛选池内各家首席均维持上期大势定调，未触发跨档位转向信号。
        </div>`;
    } else {
      document.getElementById("shifts-grid").innerHTML = shifts
        .map((s) => {
          const tone = s.direction === "bull" ? "tone-bull" : "tone-bear";
          const inCart = state.cart.includes(s.id);
          const idxStr = s.index_target
            ? `<span class="pill mono">${esc(s.index_target.index_name)} ${s.index_target.point_floor ?? ""}-${s.index_target.point_ceiling ?? ""}</span>`
            : "";
          return `
            <article class="subcard" style="display:flex;flex-direction:column;justify-content:space-between;gap:10px;">
              <div style="display:flex;flex-direction:column;gap:8px;">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
                  <div>
                    <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                      <strong style="font-size:13px;">${esc(s.broker)}</strong>
                      ${s.is_core ? '<span class="pill tone-info">★核心</span>' : ""}
                    </div>
                    <div style="font-size:12px;color:var(--muted);margin-top:2px;">${esc(s.persona)}</div>
                  </div>
                  <span class="pill ${tone}">${esc(s.signal_badge)}</span>
                </div>

                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:5px 8px;border-radius:6px;background:var(--card);border:1px solid var(--card-border);font-size:12px;">
                  <span style="color:var(--muted);text-decoration:line-through;">${esc(s.from_label)}</span>
                  <span>→</span>
                  <strong style="color:var(${s.direction === "bull" ? "--bull" : "--bear"});">${esc(s.to_label)}</strong>
                  ${idxStr}
                </div>

                <div style="font-size:12px;line-height:1.6;">${esc(s.summary)}</div>
              </div>

              <div style="display:flex;justify-content:space-between;align-items:center;padding-top:8px;border-top:1px solid var(--card-border);">
                <button class="link-btn" onclick="App.openSource('${s.id}')">轨迹对照与段号溯源 →</button>
                <button class="btn btn-sm ${inCart ? "tone-info" : ""}" onclick="App.toggleCart('${s.id}')">
                  ${inCart ? "✓ 已入篮" : "+ 入篮"}
                </button>
              </div>
            </article>`;
        })
        .join("");
    }

    renderDdmCollider();
  }

  function renderDdmCollider() {
    const wk = weekData();
    if (!wk) return;
    const claims = (wk.ddm_claims || []).filter((c) => {
      if (state.ddmFilter !== "all" && c.pillar !== state.ddmFilter) return false;
      if (state.pool === "core" && (!c.brokers_core || c.brokers_core.length === 0)) return false;
      return true;
    });

    const bulls = claims.filter((c) => c.side === "bull");
    const bears = claims.filter((c) => c.side === "bear");
    document.getElementById("bull-count-label").textContent = `${bulls.length} 簇`;
    document.getElementById("bear-count-label").textContent = `${bears.length} 簇`;

    const cardHtml = (c) => {
      const brokers = state.pool === "core" ? c.brokers_core : c.brokers_all;
      const inCart = state.cart.includes(c.id);
      const tone = c.side === "bull" ? "tone-bull" : "tone-bear";
      return `
        <div class="subcard" style="display:flex;flex-direction:column;gap:8px;">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
            <span class="pill ${tone}">${esc(c.pillar_label)}</span>
            <span style="font-size:12px;color:var(--muted);">${esc(c.topic_label)}</span>
          </div>
          <div style="font-size:13px;font-weight:550;line-height:1.55;">${esc(c.title)}</div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;padding-top:6px;border-top:1px solid var(--card-border);">
            <div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center;font-size:12px;">
              <span style="color:var(--muted);">共振(${brokers.length})：</span>
              ${brokers.map((b) => `<span class="pill" style="padding:1px 6px;background:var(--card);">${esc(b)}</span>`).join("")}
            </div>
            <div style="display:flex;gap:8px;align-items:center;">
              <button class="link-btn" onclick="App.openSource('${c.id}')">溯源</button>
              <button class="btn btn-sm ${inCart ? "tone-info" : ""}" onclick="App.toggleCart('${c.id}')">
                ${inCart ? "✓ 已入篮" : "+ 入篮"}
              </button>
            </div>
          </div>
        </div>`;
    };

    document.getElementById("bull-claims-col").innerHTML =
      bulls.map(cardHtml).join("") || `<div class="subcard" style="color:var(--muted);font-size:12px;">当前过滤条件下暂无多方论据</div>`;
    document.getElementById("bear-claims-col").innerHTML =
      bears.map(cardHtml).join("") || `<div class="subcard" style="color:var(--muted);font-size:12px;">当前过滤条件下暂无空方顾虑</div>`;
  }

  /* ==================== TAB 2 RENDER ==================== */
  function renderSectorTab() {
    const wk = weekData();
    if (!wk) return;
    const list = wk.sector_matrix || [];
    if (!state.selectedSectorId || !list.some((x) => x.id === state.selectedSectorId)) {
      state.selectedSectorId = list[0]?.id || null;
    }
    const mb = state.snapshot.market_benchmark || {};
    document.getElementById("market-asof-note").textContent =
      `${mb.source_note || ""} · 行情基准日：${mb.as_of || "—"}`;

    renderSectorQuadrant();
    renderSectorInspector();
    renderSectorTable();
  }

  function renderSectorQuadrant() {
    const wk = weekData();
    const svg = document.getElementById("sector-svg");
    if (!wk || !svg) return;
    const list = wk.sector_matrix || [];

    const W = 620, H = 390;
    const padL = 56, padR = 34, padT = 36, padB = 44;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;
    const xScale = (val) => padL + (Math.min(100, Math.max(0, val)) / 100) * plotW;
    const yScale = (val) => padT + ((5 - Math.min(5, Math.max(-5, val))) / 10) * plotH;
    const midX = xScale(45);
    const midY = yScale(0);

    let html = `
      <rect x="${padL}" y="${padT}" width="${midX - padL}" height="${midY - padT}" fill="var(--info-soft)" />
      <rect x="${midX}" y="${padT}" width="${W - padR - midX}" height="${midY - padT}" fill="var(--bull-soft)" />
      <rect x="${midX}" y="${midY}" width="${W - padR - midX}" height="${H - padB - midY}" fill="var(--warn-soft)" />
      <rect x="${padL}" y="${midY}" width="${midX - padL}" height="${H - padB - midY}" fill="var(--bear-soft)" />

      <line x1="${midX}" y1="${padT}" x2="${midX}" y2="${H - padB}" stroke="var(--border)" stroke-dasharray="4 4" stroke-width="1.5" />
      <line x1="${padL}" y1="${midY}" x2="${W - padR}" y2="${midY}" stroke="var(--border)" stroke-dasharray="4 4" stroke-width="1.5" />
      <rect x="${padL}" y="${padT}" width="${plotW}" height="${plotH}" fill="none" stroke="var(--border)" />

      <text x="${padL + 10}" y="${padT + 18}" fill="var(--primary)" font-size="12" font-weight="600">★ 潜伏Alpha区：低共识 · 新升温</text>
      <text x="${W - padR - 10}" y="${padT + 18}" text-anchor="end" fill="var(--bull)" font-size="12" font-weight="600">主线共识区：强共识 · 升温 (盯拥挤度)</text>
      <text x="${W - padR - 10}" y="${H - padB - 10}" text-anchor="end" fill="var(--warn)" font-size="12" font-weight="600">分歧兑现区：强共识 · 边际降温</text>
      <text x="${padL + 10}" y="${H - padB - 10}" fill="var(--bear)" font-size="12" font-weight="600">规避降温区：低共识 · 降温</text>

      <text x="${padL + plotW / 2}" y="${H - 12}" text-anchor="middle" fill="var(--muted)" font-size="12">卖方推荐共识覆盖率 (%) →</text>
      <text x="16" y="${padT + plotH / 2}" text-anchor="middle" fill="var(--muted)" font-size="12" transform="rotate(-90 16 ${padT + plotH / 2})">周边际推荐净变化 (Δ家) →</text>
      <text x="${xScale(20)}" y="${H - padB + 16}" text-anchor="middle" fill="var(--muted)" font-size="12">20%</text>
      <text x="${midX}" y="${H - padB + 16}" text-anchor="middle" fill="var(--muted)" font-size="12">45%</text>
      <text x="${xScale(80)}" y="${H - padB + 16}" text-anchor="middle" fill="var(--muted)" font-size="12">80%</text>
      <text x="${padL - 8}" y="${yScale(3) + 4}" text-anchor="end" fill="var(--muted)" font-size="12">+3</text>
      <text x="${padL - 8}" y="${midY + 4}" text-anchor="end" fill="var(--muted)" font-size="12">0</text>
      <text x="${padL - 8}" y="${yScale(-3) + 4}" text-anchor="end" fill="var(--muted)" font-size="12">-3</text>
    `;

    list.forEach((sec, idx) => {
      const cons = state.pool === "core" ? sec.consensus_core : sec.consensus_all;
      const delt = state.pool === "core" ? sec.delta_core : sec.delta_all;
      // Slight deterministic jitter to prevent overlapping labels at identical coordinates
      const jitterX = ((idx % 3) - 1) * 8;
      const cx = xScale(cons) + jitterX;
      const cy = yScale(delt);
      const r = sec.weight_radius || 12;
      const isSel = sec.id === state.selectedSectorId;

      let strokeColor = "var(--primary)";
      if (cons >= 45 && delt >= 0) strokeColor = "var(--bull)";
      else if (cons >= 45 && delt < 0) strokeColor = "var(--warn)";
      else if (cons < 45 && delt <= 0) strokeColor = "var(--bear)";

      const labelY = delt >= 0 ? cy - r - 6 : cy + r + 14;
      html += `
        <g class="quad-node" onclick="App.selectSector('${sec.id}')">
          ${isSel ? `<circle cx="${cx}" cy="${cy}" r="${r + 5}" fill="none" stroke="var(--text)" stroke-width="1.8" stroke-dasharray="3 2" />` : ""}
          <circle cx="${cx}" cy="${cy}" r="${r}" fill="${strokeColor}" fill-opacity="0.72" stroke="${strokeColor}" stroke-width="2" />
          <text x="${cx}" y="${labelY}" text-anchor="middle" fill="var(--text)" font-size="12" font-weight="${isSel ? "700" : "500"}">${esc(sec.sw_name)}</text>
        </g>`;
    });

    svg.innerHTML = html;
  }

  function selectSector(id) {
    state.selectedSectorId = id;
    renderSectorQuadrant();
    renderSectorInspector();
    renderSectorTable();
  }

  function renderSectorInspector() {
    const wk = weekData();
    const box = document.getElementById("sector-inspector-card");
    if (!wk || !box) return;
    const sec = (wk.sector_matrix || []).find((x) => x.id === state.selectedSectorId) || wk.sector_matrix?.[0];
    if (!sec) {
      box.innerHTML = `<div style="color:var(--muted);font-size:12px;">本周暂无行业配置主线数据</div>`;
      return;
    }

    const cons = state.pool === "core" ? sec.consensus_core : sec.consensus_all;
    const delt = state.pool === "core" ? sec.delta_core : sec.delta_all;
    const inCart = state.cart.includes(sec.id);
    const crowdTone = sec.crowding_pct >= 75 ? "tone-warn" : sec.crowding_pct <= 35 ? "tone-info" : "";

    box.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:12px;">
        <div style="border-bottom:1px solid var(--card-border);padding-bottom:10px;">
          <span class="pill tone-${sec.quadrant_tone}">${esc(sec.quadrant)}</span>
          <h3 style="margin:8px 0 3px;font-size:16px;">申万：${esc(sec.sw_name)} · ${esc(sec.narrative_label)}</h3>
          <div style="font-size:12px;color:var(--muted);">
            卖方推荐覆盖率 <strong class="mono" style="color:var(--text);">${cons}%</strong> · 周边际变化 <strong class="mono" style="color:var(--text);">${delt >= 0 ? "+" + delt : delt} 家</strong>
          </div>
        </div>

        <div>
          <div style="font-size:12px;color:var(--muted);margin-bottom:6px;">自动收拢的卖方原生主题短语：</div>
          <div style="display:flex;flex-wrap:wrap;gap:6px;">
            ${(sec.raw_themes || []).map((t) => `<span class="pill"># ${esc(t)}</span>`).join("")}
          </div>
        </div>

        <div class="pill ${crowdTone}" style="justify-content:space-between;padding:8px 10px;">
          <span>二级市场成交拥挤度校验</span>
          <strong class="mono">${esc(sec.crowding_status)}</strong>
        </div>

        <div class="subcard">
          <div style="font-size:12px;font-weight:600;color:var(--bull);margin-bottom:4px;">↑ 推荐超配核心催化</div>
          <div style="font-size:12px;line-height:1.55;">${esc(sec.bull_logic)}</div>
        </div>

        <div class="subcard">
          <div style="font-size:12px;font-weight:600;color:var(--bear);margin-bottom:4px;">↓ 分歧兑现与规避提示</div>
          <div style="font-size:12px;line-height:1.55;">${esc(sec.bear_logic)}</div>
        </div>
      </div>

      <div style="display:flex;justify-content:space-between;align-items:center;padding-top:12px;margin-top:12px;border-top:1px solid var(--card-border);">
        <button class="link-btn" onclick="App.openSource('${sec.id}')">穿透查看代表研报原文 →</button>
        <button class="btn btn-sm ${inCart ? "tone-info" : ""}" onclick="App.toggleCart('${sec.id}')">
          ${inCart ? "✓ 已在周报篮" : "+ 加入周报篮"}
        </button>
      </div>`;
  }

  function renderSectorTable() {
    const wk = weekData();
    if (!wk) return;
    document.getElementById("sector-tbody").innerHTML = (wk.sector_matrix || [])
      .map((sec) => {
        const cons = state.pool === "core" ? sec.consensus_core : sec.consensus_all;
        const delt = state.pool === "core" ? sec.delta_core : sec.delta_all;
        const isSel = sec.id === state.selectedSectorId;
        const retCls = sec.ret_5d_pct >= 0 ? "color:var(--bull);" : "color:var(--bear);";
        return `
          <tr class="clickable-row ${isSel ? "selected-row" : ""}" onclick="App.selectSector('${sec.id}')">
            <td><strong>${esc(sec.sw_name)}</strong></td>
            <td>${(sec.raw_themes || []).map((t) => `<span class="pill" style="margin:1px 3px 1px 0;">${esc(t)}</span>`).join("")}</td>
            <td class="mono"><strong>${cons}%</strong></td>
            <td class="mono" style="color:var(${delt >= 0 ? "--bull" : "--bear"});font-weight:600;">${delt >= 0 ? "+" + delt : delt}家</td>
            <td class="mono">${sec.turnover_share_pct}% (${sec.crowding_pct}%分位)</td>
            <td class="mono" style="${retCls}">${sec.ret_5d_pct >= 0 ? "+" : ""}${sec.ret_5d_pct}%</td>
            <td><span class="pill tone-${sec.quadrant_tone}">${esc(sec.quadrant)}</span></td>
            <td style="text-align:right;">
              <button class="link-btn" onclick="event.stopPropagation();App.openSource('${sec.id}')">溯源</button>
            </td>
          </tr>`;
      })
      .join("");
  }

  /* ==================== TAB 3 RENDER ==================== */
  function renderEvidenceTab() {
    const wk = weekData();
    if (!wk) return;
    const nuggets = (wk.data_nuggets || []).filter((n) => {
      if (state.pool === "core" && !n.is_core) return false;
      if (state.nuggetFilter !== "all" && n.category !== state.nuggetFilter) return false;
      return true;
    });

    document.getElementById("nuggets-grid").innerHTML =
      nuggets
        .map((n) => {
          const inCart = state.cart.includes(n.id);
          return `
            <article class="subcard" style="display:flex;flex-direction:column;justify-content:space-between;gap:10px;">
              <div style="display:flex;flex-direction:column;gap:6px;">
                <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
                  <span class="pill">${esc(n.category_label)}</span>
                  <span style="font-size:12px;color:var(--muted);">${esc(n.broker)}${n.is_core ? "★" : ""} · P.${n.primary_page}</span>
                </div>
                <div class="mono" style="font-size:14px;font-weight:700;color:var(--primary);margin-top:2px;">${esc(n.metric_phrase)}</div>
                <div style="font-size:13px;line-height:1.55;">${esc(n.implication)}</div>
                ${n.chart_likely_on_page ? `<div style="font-size:12px;color:var(--warn);">📊 原报告第 ${n.primary_page} 页附有对应统计图表</div>` : ""}
              </div>
              <div style="display:flex;justify-content:space-between;align-items:center;padding-top:8px;border-top:1px solid var(--card-border);">
                <button class="link-btn" onclick="App.openSource('${n.id}')">原文段落与原件定位 →</button>
                <button class="btn btn-sm ${inCart ? "tone-info" : ""}" onclick="App.toggleCart('${n.id}')">
                  ${inCart ? "✓ 已入篮" : "+ 入篮"}
                </button>
              </div>
            </article>`;
        })
        .join("") || `<div class="subcard" style="grid-column:1/-1;color:var(--muted);font-size:12px;">当前筛选下暂无增量数据抓手</div>`;

    const cats = (wk.catalysts || []).filter((c) => state.pool === "all" || c.is_core);
    document.getElementById("catalysts-grid").innerHTML =
      cats
        .map(
          (c) => `
          <div class="subcard" style="display:flex;flex-direction:column;gap:6px;">
            <div style="display:flex;justify-content:space-between;font-size:12px;">
              <strong class="mono" style="color:var(--primary);">${esc(c.time_window)}</strong>
              <span style="color:var(--muted);">${esc(c.broker.replace("证券", ""))}提及</span>
            </div>
            <strong style="font-size:13px;">${esc(c.event_title)}</strong>
            <div style="font-size:12px;color:var(--muted);line-height:1.55;">${esc(c.scenario_impact)}</div>
          </div>`
        )
        .join("") || `<div class="subcard" style="grid-column:1/-1;color:var(--muted);font-size:12px;">当前筛选下暂无近期催化节点</div>`;
  }

  /* ==================== TAB 4 RENDER ==================== */
  function renderStocksTab() {
    const wk = weekData();
    if (!wk) return;
    const rows = (wk.golden_stocks || []).filter((s) => {
      if (state.pool === "core" && s.count_core === 0) return false;
      if (state.stockFilter !== "all" && s.status !== state.stockFilter) return false;
      return true;
    });

    document.getElementById("stocks-tbody").innerHTML =
      rows
        .map((st) => {
          const inCart = state.cart.includes(st.id);
          const badgeTone = st.status === "fresh" ? "tone-info" : st.status === "crowded" ? "tone-warn" : "";
          const brokers = state.pool === "core" ? st.brokers_core : st.brokers_all;
          return `
            <tr>
              <td>
                <strong>${esc(st.stock_name)}</strong>
                <div class="mono" style="color:var(--muted);font-size:12px;">${esc(st.stock_code)}</div>
              </td>
              <td>${esc(st.sw_level1)}</td>
              <td>
                <span class="pill ${badgeTone}">${esc(st.status_label)}</span>
                <div style="color:var(--muted);margin-top:4px;">${esc(brokers.join("、"))}</div>
              </td>
              <td><strong>${esc(st.role_label)}</strong></td>
              <td style="max-width:420px;line-height:1.55;color:var(--muted);">${esc(st.logic)}</td>
              <td style="text-align:right;white-space:nowrap;">
                <button class="link-btn" style="margin-right:8px;" onclick="App.openSource('${st.id}')">溯源</button>
                <button class="btn btn-sm ${inCart ? "tone-info" : ""}" onclick="App.toggleCart('${st.id}')">
                  ${inCart ? "✓ 已入篮" : "+ 入篮"}
                </button>
              </td>
            </tr>`;
        })
        .join("") || `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:20px;">当前筛选下暂无策略金股标的记录</td></tr>`;
  }

  /* ==================== SOURCE INSPECTOR DRAWER ==================== */
  function renderTrajectorySvg(profile) {
    const traj = profile?.trajectory_12w || [];
    if (traj.length === 0) {
      return `<div style="font-size:12px;color:var(--muted);">暂无足够历史周序列</div>`;
    }
    const W = 500, H = 135;
    const padL = 24, padR = 24, padT = 16, padB = 26;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;
    const step = plotW / Math.max(traj.length, 1);

    const hsVals = traj.map((t) => t.hs300_close).filter((v) => typeof v === "number");
    const minHs = hsVals.length ? Math.min(...hsVals) * 0.992 : 3500;
    const maxHs = hsVals.length ? Math.max(...hsVals) * 1.008 : 4200;

    let barsHtml = "";
    let linePts = [];

    traj.forEach((pt, idx) => {
      const cx = padL + step * idx + step / 2;
      const bw = Math.min(28, step * 0.62);
      const bh = ((pt.bar_pct || 12) / 100) * plotH;
      const by = padT + plotH - bh;
      let fill = "var(--border)";
      if (pt.score === 2 || pt.score === 1) fill = "var(--bull)";
      else if (pt.score === 0) fill = "var(--warn)";
      else if (pt.score === -1) fill = "var(--bear)";

      barsHtml += `
        <rect x="${cx - bw / 2}" y="${by}" width="${bw}" height="${bh}" rx="3" fill="${fill}" fill-opacity="${idx === traj.length - 1 ? "0.88" : "0.45"}" />
        <text x="${cx}" y="${H - 8}" text-anchor="middle" fill="var(--muted)" font-size="12">${esc(pt.week)}</text>
      `;

      if (typeof pt.hs300_close === "number") {
        const ly = padT + plotH - ((pt.hs300_close - minHs) / Math.max(1, maxHs - minHs)) * plotH;
        linePts.push(`${cx.toFixed(1)},${ly.toFixed(1)}`);
      }
    });

    const polyline = linePts.length >= 2
      ? `<polyline fill="none" stroke="var(--primary)" stroke-width="2.2" points="${linePts.join(" ")}" />`
      : "";

    return `
      <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block;">
        ${barsHtml}
        ${polyline}
      </svg>`;
  }

  function openSource(itemId) {
    const item = state.lookup[itemId];
    if (!item) return;
    const prof = state.snapshot?.broker_profiles?.[item.broker] || {};

    document.getElementById("src-broker").textContent = item.broker;
    document.getElementById("src-persona").textContent = prof.persona || "卖方策略团队";
    document.getElementById("src-title").textContent = `《${item.report_title}》`;
    document.getElementById("src-meta").textContent = `发布日期：${item.report_date} · 信号类型：${item.type}`;

    document.getElementById("src-trajectory-wrap").innerHTML = renderTrajectorySvg(prof);

    const sc = item.schema || {};
    document.getElementById("src-schema-grid").innerHTML = `
      <div class="card" style="padding:8px 10px;"><div style="color:var(--muted);">决策层级</div><strong>${esc(sc.level || "—")}</strong></div>
      <div class="card" style="padding:8px 10px;"><div style="color:var(--muted);">归属维度</div><strong>${esc(sc.ddm || "—")}</strong></div>
      <div class="card" style="padding:8px 10px;"><div style="color:var(--muted);">边际向量</div><strong>${esc(sc.delta || "—")}</strong></div>
      <div class="card" style="padding:8px 10px;"><div style="color:var(--muted);">来源系列</div><strong>${esc(sc.framework || "—")}</strong></div>
    `;

    const driveLink = document.getElementById("src-drive-link");
    if (item.drive_file_id) {
      const pageAnchor = item.evidence?.[0]?.page ? `#page=${item.evidence[0].page}` : "";
      driveLink.href = `https://drive.google.com/file/d/${encodeURIComponent(item.drive_file_id)}/view${pageAnchor}`;
      driveLink.classList.remove("hidden");
    } else {
      driveLink.classList.add("hidden");
    }

    const evs = item.evidence || [];
    document.getElementById("src-quotes-list").innerHTML =
      evs
        .map(
          (ev) => `
          <div class="quote-box">
            <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-bottom:4px;">
              <strong class="mono" style="color:var(--text);">PDF 第 ${ev.page} 页 · 段号 [${esc(ev.pid)}]</strong>
              <span>${esc(ev.heading || "")}</span>
            </div>
            <div>“${esc(ev.text)}${ev.truncated ? "…" : ""}”</div>
          </div>`
        )
        .join("") || `<div style="font-size:12px;color:var(--muted);">暂无关联原文段落</div>`;

    const cartBtn = document.getElementById("src-cart-btn");
    const syncLabel = () => {
      const inCart = state.cart.includes(itemId);
      cartBtn.textContent = inCart ? "✓ 已在投委会周报篮 (点击移除)" : "+ 加入投委会周报篮";
    };
    syncLabel();
    cartBtn.onclick = () => {
      toggleCart(itemId);
      syncLabel();
    };

    document.getElementById("src-backdrop").classList.remove("hidden");
    document.getElementById("src-drawer").classList.add("open");
  }

  function closeSource() {
    document.getElementById("src-backdrop").classList.add("hidden");
    document.getElementById("src-drawer").classList.remove("open");
  }

  /* ==================== BRIEFING CART DRAWER ==================== */
  function toggleCart(itemId) {
    const idx = state.cart.indexOf(itemId);
    if (idx >= 0) state.cart.splice(idx, 1);
    else state.cart.push(itemId);
    saveCart();
    renderAll();
    renderCartDrawer();
  }

  function clearCart() {
    state.cart = [];
    saveCart();
    renderAll();
    renderCartDrawer();
  }

  function openCart(open) {
    if (open) renderCartDrawer();
    document.getElementById("cart-backdrop").classList.toggle("hidden", !open);
    document.getElementById("cart-drawer").classList.toggle("open", open);
  }

  function renderCartDrawer() {
    const validItems = state.cart.map((id) => state.lookup[id]).filter(Boolean);
    document.getElementById("cart-badge").textContent = validItems.length;

    if (validItems.length === 0) {
      document.getElementById("cart-list").innerHTML = `<div class="subcard" style="font-size:12px;color:var(--muted);text-align:center;">暂未收藏卡片，可在任意视图点击「+ 入篮」收集周会汇报素材</div>`;
      document.getElementById("cart-md").textContent = "# 暂无已选策略周报素材";
      return;
    }

    document.getElementById("cart-list").innerHTML = validItems
      .map(
        (it) => `
        <div class="subcard" style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;padding:9px 11px;">
          <div style="font-size:12px;">
            <span class="pill tone-info" style="margin-bottom:4px;">${esc(it.type)}</span>
            <div><strong>${esc(it.title)}</strong></div>
          </div>
          <button class="btn btn-sm" onclick="App.toggleCart('${it.id}')">移除</button>
        </div>`
      )
      .join("");

    const wk = weekData();
    const lines = [
      `# 买方内部策略周会汇报纪要 · ${wk?.week_info?.label || ""}`,
      `> 样本口径：${state.pool === "core" ? "★核心首席白名单池" : "全市场卖方样本池"} | 生成时间：${state.snapshot?.generated_at || ""}`,
      ``,
      `## 一、 本周多空核心交锋眼`,
      wk?.synthesis?.executive_clash_summary || "",
      ``,
      `## 二、 精选重点信号与论据 (${validItems.length}项)`
    ];
    validItems.forEach((it, idx) => {
      const pnum = it.evidence?.[0]?.page ? ` P.${it.evidence[0].page}` : "";
      lines.push(`${idx + 1}. **【${it.type}】${it.title}**`);
      lines.push(`   - 要点：${it.summary}`);
      lines.push(`   - 出处：${it.broker}《${it.report_title}》(${it.report_date}${pnum})`);
    });

    document.getElementById("cart-md").textContent = lines.join("\n");
  }

  function copyBriefing() {
    const text = document.getElementById("cart-md").textContent;
    navigator.clipboard.writeText(text).then(() => {
      const btn = document.getElementById("btn-copy-md");
      const orig = btn.textContent;
      btn.textContent = "✓ 已复制";
      setTimeout(() => { btn.textContent = orig; }, 1600);
    });
  }

  function renderAll() {
    const snap = state.snapshot;
    if (!snap) return;
    document.getElementById("demo-banner").classList.toggle("hidden", !snap.demo_mode);

    const wk = weekData();
    if (wk) {
      document.getElementById("header-subtitle").textContent =
        `更新时间 ${snap.generated_at} · 当周入库 ${wk.report_count} 篇 (${wk.broker_count_all}家机构 / ★核心池 ${wk.broker_count_core}家) · 累计归档 ${snap.total_archived_reports} 篇`;
    }

    const validCount = state.cart.filter((id) => state.lookup[id]).length;
    document.getElementById("cart-badge").textContent = validCount;

    renderMacroTab();
    renderSectorTab();
    renderEvidenceTab();
    renderStocksTab();
  }

  async function init() {
    loadPersisted();
    const url = resolveDataUrl();
    try {
      const resp = await fetch(url, { cache: "no-store" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      state.snapshot = await resp.json();
      state.currentWeek = state.snapshot.latest_week;
      rebuildLookup();

      // Seed 2 default cart items on first visit in demo mode so user can preview Briefing Cart immediately
      if (state.snapshot.demo_mode && state.cart.length === 0) {
        const firstShift = state.snapshot.weeks?.[state.currentWeek]?.marginal_shifts?.[0]?.id;
        const firstNug = state.snapshot.weeks?.[state.currentWeek]?.data_nuggets?.[0]?.id;
        if (firstShift) state.cart.push(firstShift);
        if (firstNug) state.cart.push(firstNug);
      }

      const sel = document.getElementById("week-select");
      sel.innerHTML = (state.snapshot.available_weeks || [])
        .map((w) => `<option value="${esc(w.week_mon)}">${esc(w.label)}</option>`)
        .join("");
      sel.value = state.currentWeek;
      sel.onchange = (e) => {
        state.currentWeek = e.target.value;
        renderAll();
      };

      renderAll();
    } catch (err) {
      document.getElementById("header-subtitle").textContent = `快照加载失败 (${err.message})，请检查 snapshot.json 是否已生成`;
    }
  }

  document.addEventListener("DOMContentLoaded", init);

  return {
    setPool,
    switchTab,
    setDdmFilter,
    setNuggetFilter,
    setStockFilter,
    selectSector,
    openSource,
    closeSource,
    toggleCart,
    clearCart,
    openCart,
    copyBriefing,
    toggleTheme
  };
})();
