/**
 * Shared Ledger Verification Console - User Friendly & Live Polling Application
 */

// Global State
let currentTab = "dashboard";
let currentCaseDetail = null;
let currentArtifactKey = "judge"; // Default to core Judge tab
let activeEventSource = null;
let currentBatchId = null;

let lastSeenCompletedCaseId = null;
let livePollingTimer = null;

// User-friendly scenario metadata
const FOCUS_DICT = {
  expense_aa: {
    title: "多人 AA 聚餐记账",
    desc: "大家平摊饭钱，由一人先付款，系统自动计算并记录谁欠谁多少钱",
  },
  targeted_repayment: {
    title: "还指定的一笔钱",
    desc: "明确指定清偿某一次消费产生的具体借款凭据",
  },
  prepayment_refund: {
    title: "预付款与原路退款",
    desc: "先存押金/预付款，后续用预付款核销消费，以及发生退款时原路返还",
  },
};

const ARTIFACT_GUIDES = {
  judge: "业务法官（DeepSeek）阅读了完整业务逻辑手册，仔细比对了数据库执行后的真实账目，给出了最终权威审计意见与差异结论。",
  raw_case: "由本地 AI (Qwen) 模拟人类日常生活构思的记账故事，定义了参与者、消费意图与平摊方式。",
  scenario: "由 DeepSeek 将生活故事转译为系统标准 Scenario v1 指令，包含了精确到角分的操作参数。",
  operations: "本地 Supabase 数据库按顺序真实执行的每一条动作（创建活动、加入成员、记账、清账）调用日志。",
  state_final: "记账完成后，数据库中保存的最终真实投影账面快照（包括每个人该还谁多少钱、是否结清等）。",
  compiler_result: "DeepSeek 编译场景时的思考耗时、尝试次数与格式自我修复记录。",
};

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  initNavigation();
  initArtifactTabs();
  initFilterControls();
  initRunForm();
  checkEnvironment();
  loadFocusCatalog();
  restoreBatchStream();

  // Handle URL hash routing
  handleHashRouting();
  window.addEventListener("hashchange", handleHashRouting);

  // Start Global Live Monitor Heartbeat (polls every 1.8 seconds)
  startLiveHeartbeat();
});

// Toast helper
function showToast(message, duration = 3000) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => {
    toast.classList.remove("show");
  }, duration);
}

// -------------------------------------------------------------
// Global Live Monitor Heartbeat (Catches Claude Code & UI runs)
// -------------------------------------------------------------
function startLiveHeartbeat() {
  if (livePollingTimer) clearInterval(livePollingTimer);
  pollLiveExecution();
  livePollingTimer = setInterval(pollLiveExecution, 1800);
}

async function pollLiveExecution() {
  try {
    const res = await fetch("/api/workflow/live");
    if (!res.ok) return;
    const data = await res.json();

    const banner = document.getElementById("live-banner");
    const liveTitle = document.getElementById("live-title");
    const liveDesc = document.getElementById("live-desc");
    const actionBtn = document.getElementById("live-action-btn");
    const miniStepper = document.getElementById("mini-stepper");

    if (data.has_active_run && data.active_case) {
      const c = data.active_case;
      banner.className = "live-banner active";
      actionBtn.style.display = "inline-flex";

      const sourceLabel = c.source === "web_ui" ? "网页控制台" : "Claude Code / 后台";
      liveTitle.innerHTML = `🔥 检测到【${sourceLabel}】正在执行测试：<span style="color:#60a5fa">${c.focus_title || c.focus}</span>`;
      liveDesc.textContent = `${c.stage_name} (已耗时约 ${c.age_seconds} 秒) | ${c.stage_desc || ''}`;

      // Update mini stepper
      updateMiniStepper(c.stages, c.stage);

      // If user is currently on view-run, sync the large pipeline stepper too
      syncLargePipelineStepper(c);
    } else {
      // Idle or recently completed
      if (data.latest_completed) {
        const latest = data.latest_completed;

        // Detect if this is a newly finished case
        if (lastSeenCompletedCaseId && lastSeenCompletedCaseId !== latest.id) {
          const v = latest.judge_verdict || latest.overall_result || "已完成";
          showToast(`🎉 测试完成！案例 ${latest.focus || ''} 判决: [${v}]`);

          // Auto refresh current view without resetting scroll
          if (currentTab === "dashboard") loadDashboardData(false);
          else if (currentTab === "cases") loadCasesList(false);
          else if (currentTab === "issues") loadIssueQueue(false);
        }
        lastSeenCompletedCaseId = latest.id;

        banner.className = "live-banner completed";
        actionBtn.style.display = "inline-flex";
        actionBtn.textContent = "查看该案例";
        actionBtn.onclick = () => { window.location.hash = `#detail/${encodeURIComponent(latest.id)}`; };

        const fTitle = (FOCUS_DICT[latest.focus] && FOCUS_DICT[latest.focus].title) || latest.focus;
        const vHtml = latest.judge_verdict === "PASS"
          ? `<strong style="color:var(--color-pass-text)">通过 (PASS)</strong>`
          : (latest.judge_verdict === "FAIL" ? `<strong style="color:var(--color-fail-text)">发现缺陷 (FAIL)</strong>` : `<strong>${latest.judge_verdict || latest.status}</strong>`);

        liveTitle.innerHTML = `✅ 最近测试完毕：【${fTitle}】 判定结果：${vHtml}`;
        liveDesc.textContent = `编号: ${latest.id} | 完成于: ${latest.time_display || '刚刚'} | 耗时: ${latest.latencies ? latest.latencies.total : '-'}s`;

        // Reset mini stepper to all green/neutral
        resetMiniStepperAllDone();
      } else {
        banner.className = "live-banner idle";
        actionBtn.style.display = "none";
        liveTitle.textContent = "后台监控待命中";
        liveDesc.textContent = "只要 Claude Code 或后台脚本一开始跑测试，这里就会立刻显示实时步骤与已耗时";
        resetMiniStepperIdle();
      }
    }
  } catch (err) {
    // Ignore transient network errors
  }
}

function updateMiniStepper(stages, currentStage) {
  document.querySelectorAll(".mini-step").forEach(el => {
    const s = el.dataset.step;
    const st = stages ? stages[s] : null;
    el.className = `mini-step ${st || 'waiting'}`;
  });
}

function resetMiniStepperAllDone() {
  document.querySelectorAll(".mini-step").forEach(el => {
    el.className = "mini-step completed";
  });
}

function resetMiniStepperIdle() {
  document.querySelectorAll(".mini-step").forEach(el => {
    el.className = "mini-step";
  });
}

function syncLargePipelineStepper(activeCase) {
  const pipelineCard = document.getElementById("pipeline-card");
  if (pipelineCard.style.display === "none") {
    pipelineCard.style.display = "block";
  }
  document.getElementById("pipeline-batch-info").textContent =
    `正在执行: ${activeCase.focus_title || activeCase.focus} (已用时 ${activeCase.age_seconds}s)`;
  document.getElementById("pipeline-status-text").textContent = activeCase.stage_name;

  const stageKeys = ["generator", "compiler", "loader", "runner", "judge"];
  const stages = activeCase.stages || {};

  stageKeys.forEach(s => {
    const stepEl = document.getElementById(`step-${s}`);
    const statusEl = document.getElementById(`status-${s}`);
    const st = stages[s] || "waiting";
    stepEl.className = `pipe-step ${st}`;

    if (st === "running") statusEl.textContent = "正在处理...";
    else if (st === "completed") statusEl.textContent = "已就绪";
    else statusEl.textContent = "等待中";
  });
}

// -------------------------------------------------------------
// Navigation & Hash Routing
// -------------------------------------------------------------
function initNavigation() {
  document.querySelectorAll(".nav-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tab;
      window.location.hash = `#${target}`;
    });
  });
}

function handleHashRouting() {
  const hash = window.location.hash.slice(1) || "dashboard";
  if (hash.startsWith("detail/")) {
    const caseId = decodeURIComponent(hash.slice(7));
    openCaseDetail(caseId);
  } else {
    switchTab(hash);
  }
}

function switchTab(tabName) {
  currentTab = tabName;
  document.querySelectorAll(".nav-tab").forEach(tab => {
    tab.classList.toggle("active", tab.dataset.tab === tabName);
  });

  document.querySelectorAll(".view-section").forEach(sec => {
    sec.classList.remove("active");
  });

  const activeSec = document.getElementById(`view-${tabName}`);
  if (activeSec) {
    activeSec.classList.add("active");
  }

  // Load section-specific data
  if (tabName === "dashboard") {
    loadDashboardData();
  } else if (tabName === "cases") {
    loadCasesList();
  } else if (tabName === "issues") {
    loadIssueQueue();
  }
}

function goBackFromDetail() {
  window.location.hash = "#cases";
}

function toggleExplainer() {
  const body = document.getElementById("explainer-body");
  const btn = document.getElementById("btn-toggle-explainer");
  if (body.style.display === "none") {
    body.style.display = "block";
    btn.textContent = "收起说明 ▲";
  } else {
    body.style.display = "none";
    btn.textContent = "展开说明 ▼";
  }
}

// -------------------------------------------------------------
// Check Environment Status
// -------------------------------------------------------------
async function checkEnvironment() {
  const badge = document.getElementById("env-status-badge");
  try {
    const res = await fetch("/api/config/info");
    if (!res.ok) throw new Error("Failed to check environment");
    const data = await res.json();
    const env = data.env_status || {};

    const hasSupabase = env.has_supabase_url && env.has_supabase_anon_key;
    const hasDeepSeek = env.has_deepseek_api_key;

    if (hasSupabase && hasDeepSeek) {
      badge.innerHTML = `
        <span class="status-dot"></span>
        <span class="status-text">本地环境已就绪</span>
      `;
      badge.title = `Supabase 本地实例: 正常\nDeepSeek: 正常\nQwen: ${env.local_generator_model}`;
    } else {
      badge.innerHTML = `
        <span class="status-dot warning"></span>
        <span class="status-text">环境缺少部分密钥</span>
      `;
      badge.title = `Supabase: ${hasSupabase ? '正常' : '缺少配置'}\nDeepSeek: ${hasDeepSeek ? '正常' : '未检测到 API Key'}`;
    }
  } catch (err) {
    badge.innerHTML = `
      <span class="status-dot danger"></span>
      <span class="status-text">连接异常</span>
    `;
  }
}

// -------------------------------------------------------------
// 1. Dashboard View
// -------------------------------------------------------------
async function loadDashboardData(showToastNotice = false) {
  try {
    const res = await fetch("/api/dashboard");
    if (!res.ok) throw new Error("加载仪表盘失败");
    const data = await res.json();

    // 1. Total & Verdict stats
    document.getElementById("stat-total-cases").textContent = data.total_cases;
    const v = data.verdicts || {};
    document.getElementById("stat-pass").textContent = `通过 PASS ${v.PASS || 0}`;
    document.getElementById("stat-fail").textContent = `发现缺陷 FAIL ${v.FAIL || 0}`;
    document.getElementById("stat-uncertain").textContent = `存疑 UNCERTAIN ${v.UNCERTAIN || 0}`;
    document.getElementById("stat-error").textContent = `异常 ERROR ${v.ERROR || 0}`;

    // Update issues badge in top nav
    const issueBadge = document.getElementById("issues-count-badge");
    const issuesCount = (v.FAIL || 0) + (v.UNCERTAIN || 0) + (v.ERROR || 0);
    issueBadge.textContent = issuesCount;
    issueBadge.style.display = issuesCount > 0 ? "inline-block" : "none";

    // 2. Loader stats
    const loader = data.loader_stats || {};
    document.getElementById("stat-loader-rate").textContent = `${loader.valid_rate}%`;
    document.getElementById("stat-loader-bar").style.width = `${loader.valid_rate}%`;
    document.getElementById("stat-loader-detail").textContent =
      `合规用例: ${loader.valid || 0} / 校验总数: ${loader.tested || 0}`;

    // 3. Runner stats
    const runner = data.runner_stats || {};
    document.getElementById("stat-runner-rate").textContent = `${runner.execution_rate}%`;
    document.getElementById("stat-runner-bar").style.width = `${runner.execution_rate}%`;
    document.getElementById("stat-runner-detail").textContent =
      `记账成功: ${runner.executed || 0} / 进入数据库总数: ${runner.tested || 0}`;

    // 3b. Coverage framework counters (unique valid coverage, not raw attempts)
    renderCoverageStats(data.coverage);

    // 4. Average Latencies
    const lats = data.average_latencies || {};
    document.getElementById("lat-gen").textContent = lats.generator !== null ? `${lats.generator}s` : "-";
    document.getElementById("lat-comp").textContent = lats.compiler !== null ? `${lats.compiler}s` : "-";
    document.getElementById("lat-run").textContent = lats.runner !== null ? `${lats.runner}s` : "-";
    document.getElementById("lat-judge").textContent = lats.judge !== null ? `${lats.judge}s` : "-";
    document.getElementById("lat-total").textContent = lats.total !== null ? `${lats.total}s` : "-";

    // 5. Focus Breakdown Table
    const tbody = document.querySelector("#focus-stats-table tbody");
    tbody.innerHTML = "";
    if (data.focus_stats && data.focus_stats.length > 0) {
      data.focus_stats.forEach(f => {
        const tr = document.createElement("tr");
        const fMeta = FOCUS_DICT[f.focus] || { title: f.focus, desc: "" };

        tr.innerHTML = `
          <td>
            <strong>${fMeta.title}</strong>
            <div class="text-muted" style="font-size: 11px;">${f.focus}</div>
          </td>
          <td>${f.total}</td>
          <td><span class="badge badge-pass">${f.pass}</span></td>
          <td><span class="badge badge-fail">${f.fail}</span></td>
          <td><span class="badge badge-error">${f.error}</span></td>
          <td><strong>${f.pass_rate}%</strong></td>
        `;
        tbody.appendChild(tr);
      });
    } else {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">暂无场景统计数据</td></tr>`;
    }

    // 6. Recent Cases List
    const recentContainer = document.getElementById("recent-cases-list");
    recentContainer.innerHTML = "";
    if (data.recent_cases && data.recent_cases.length > 0) {
      data.recent_cases.forEach(c => {
        const row = document.createElement("div");
        row.className = "recent-case-row";
        row.onclick = () => { window.location.hash = `#detail/${encodeURIComponent(c.id)}`; };

        const verdictBadge = getVerdictBadgeHtml(c.judge_verdict, c.overall_result);
        const fMeta = FOCUS_DICT[c.focus] || { title: c.focus };

        row.innerHTML = `
          <div>
            <strong>${fMeta.title}</strong>
            <span class="text-muted" style="font-size: 11px; margin-left: 8px;">${c.id}</span>
          </div>
          <div style="display: flex; align-items: center; gap: 12px;">
            <span class="text-muted" style="font-size: 12px;">${c.time_display}</span>
            <span class="tag">${c.latencies && c.latencies.total ? c.latencies.total + 's' : '-'}</span>
            ${verdictBadge}
          </div>
        `;
        recentContainer.appendChild(row);
      });
    } else {
      recentContainer.innerHTML = `<div class="text-muted text-center">暂无近期案例</div>`;
    }

    if (showToastNotice) {
      showToast("大盘数据已更新！");
    }
  } catch (err) {
    console.error("Dashboard error:", err);
  }
}

// -------------------------------------------------------------
// 2. Run Workflow View
// -------------------------------------------------------------
function initRunForm() {
  const form = document.getElementById("workflow-run-form");
  const focusSelect = document.getElementById("select-focus");
  const hintText = document.getElementById("focus-hint-text");

  focusSelect.addEventListener("change", (e) => {
    const val = e.target.value;
    if (FOCUS_DICT[val]) {
      hintText.textContent = FOCUS_DICT[val].desc;
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const focus = focusSelect.value;
    const count = parseInt(document.getElementById("input-count").value, 10) || 1;

    const btn = document.getElementById("btn-start-run");
    btn.disabled = true;
    btn.innerHTML = `<span class="status-dot"></span> 正在启动测试...`;

    try {
      const res = await fetch("/api/workflow/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ focus, count }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "启动失败");
      }
      const data = await res.json();
      currentBatchId = data.batch_id;
      rememberBatchId(currentBatchId);
      showToast(`测试已发起 (批次编号: ${currentBatchId})`);

      // Show pipeline progress card
      const pipelineCard = document.getElementById("pipeline-card");
      pipelineCard.style.display = "block";
      pipelineCard.scrollIntoView({ behavior: "smooth" });

      resetPipelineDisplay();
      startPipelineEventStream(currentBatchId);
    } catch (err) {
      alert("启动工作流失败: " + err.message);
      btn.disabled = false;
      btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> 立即启动测试`;
    }
  });
}

/** Log a finished batch's coverage counters next to its raw case count. */
function renderBatchCoverage(coverage) {
  if (!coverage) return;
  appendPipelineLog(
    `[覆盖统计] 生成 ${coverage.generated_count} · 命中 ${coverage.focus_valid_count} · ` +
    `未命中 ${coverage.focus_mismatch_count} · 重复 ${coverage.duplicate_count} · ` +
    `唯一有效覆盖 ${coverage.unique_valid_count}` +
    (coverage.pass_rate === null || coverage.pass_rate === undefined
      ? "" : ` · PASS 率 ${coverage.pass_rate}%`),
    "info"
  );
}

/**
 * The batch id survives a page reload, so the console can re-attach to a run
 * that is still going. The SSE endpoint replays the events the reload missed.
 */
function rememberBatchId(batchId) {
  try {
    if (batchId) sessionStorage.setItem("sl_batch_id", batchId);
    else sessionStorage.removeItem("sl_batch_id");
  } catch (err) {
    // Storage can be unavailable in private windows; losing it is not fatal.
  }
}

function restoreBatchStream() {
  let batchId = null;
  try {
    batchId = sessionStorage.getItem("sl_batch_id");
  } catch (err) {
    batchId = null;
  }
  if (!batchId) return;
  currentBatchId = batchId;
  const pipelineCard = document.getElementById("pipeline-card");
  if (pipelineCard) pipelineCard.style.display = "block";
  resetPipelineDisplay();
  startPipelineEventStream(batchId);
}

function resetPipelineDisplay() {  ["generator", "compiler", "loader", "runner", "judge"].forEach(stage => {
    const el = document.getElementById(`step-${stage}`);
    el.className = "pipe-step";
    document.getElementById(`status-${stage}`).textContent = "等待中";
  });
  document.getElementById("pipeline-result-box").style.display = "none";
  document.getElementById("pipeline-result-content").innerHTML = "";
  document.getElementById("pipeline-status-text").textContent = "正在连接流水线...";
}

function startPipelineEventStream(batchId) {
  if (activeEventSource) {
    activeEventSource.close();
  }

  activeEventSource = new EventSource(`/api/workflow/events/${batchId}`);

  activeEventSource.addEventListener("batch_started", (e) => {
    const data = JSON.parse(e.data);
    const fTitle = (FOCUS_DICT[data.focus] && FOCUS_DICT[data.focus].title) || data.focus;
    document.getElementById("pipeline-batch-info").textContent =
      `场景: ${fTitle} | 计划执行: ${data.total_count} 个案例`;
    appendPipelineLog(`[批次启动] 业务场景: ${fTitle}, 计划生成: ${data.total_count} 个案例`, "info");
  });

  activeEventSource.addEventListener("case_started", (e) => {
    const data = JSON.parse(e.data);
    document.getElementById("pipeline-status-text").textContent =
      `正在执行第 ${data.case_index} / ${data.total_count} 个案例...`;
    appendPipelineLog(`[案例 ${data.case_index}/${data.total_count}] 开始流转端到端验证`, "running");
    resetPipelineDisplay();
  });

  activeEventSource.addEventListener("stage_progress", (e) => {
    const data = JSON.parse(e.data);
    const stage = data.stage;
    const status = data.status;
    const details = data.details || {};

    const stepEl = document.getElementById(`step-${stage}`);
    const statusEl = document.getElementById(`status-${stage}`);

    if (stepEl && statusEl) {
      stepEl.className = `pipe-step ${status}`;
      if (status === "running") {
        statusEl.textContent = "执行中...";
        appendPipelineLog(` ➔ [步骤 ${stage.toUpperCase()}] 开始处理`, "running");
      } else if (status === "completed") {
        let text = "已完成";
        if (details.latency) text = `${details.latency}s`;
        if (details.verdict) text = `${details.verdict} (${details.latency}s)`;
        statusEl.textContent = text;
        appendPipelineLog(` ✔ [步骤 ${stage.toUpperCase()}] 成功完成 (${text})`, "success");
      } else if (status === "failed") {
        statusEl.textContent = details.error || "失败";
        appendPipelineLog(` ✖ [步骤 ${stage.toUpperCase()}] 执行失败: ${details.error || ''}`, "error");
      } else if (status === "skipped") {
        statusEl.textContent = "跳过";
        appendPipelineLog(` ⊘ [步骤 ${stage.toUpperCase()}] 已跳过`, "info");
      }
    }
  });

  activeEventSource.addEventListener("case_completed", (e) => {
    const data = JSON.parse(e.data);
    const r = data.result || {};
    appendPipelineLog(`[案例 ${data.case_index}/${data.total_count}] 判定完成: 法官=${r.judge_verdict || '-'}, 数据库记账=${r.runner_result || '-'}`, "success");

    const resultBox = document.getElementById("pipeline-result-box");
    resultBox.style.display = "block";

    const item = document.createElement("div");
    item.className = "recent-case-row";
    item.style.marginTop = "8px";
    item.innerHTML = `
      <div>
        <strong>案例 ID: ${data.case_id || '完成'}</strong>
        <span style="margin-left: 8px; font-size:12px;" class="text-muted">Run: ${r.run_id || '-'}</span>
      </div>
      <div style="display: flex; gap: 8px; align-items: center;">
        ${getVerdictBadgeHtml(r.judge_verdict, r.status)}
        <button class="btn btn-sm btn-outline" onclick="window.location.hash='#detail/${encodeURIComponent(data.case_id)}'">查看详情</button>
      </div>
    `;
    document.getElementById("pipeline-result-content").appendChild(item);
  });

  activeEventSource.addEventListener("case_failed", (e) => {
    const data = JSON.parse(e.data);
    appendPipelineLog(`[案例 ${data.case_index}/${data.total_count}] 异常终止: ${data.error}`, "error");
  });

  activeEventSource.addEventListener("batch_completed", (e) => {
    const data = JSON.parse(e.data);
    appendPipelineLog(`[全部完成] 计划 ${data.total_count} 个案例全部执行完毕！`, "success");
    document.getElementById("pipeline-status-text").textContent = "本批次已全部完成";
    renderBatchCoverage(data.coverage);
    rememberBatchId(null);

    const btn = document.getElementById("btn-start-run");
    btn.disabled = false;
    btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> 立即启动测试`;

    if (activeEventSource) {
      activeEventSource.close();
      activeEventSource = null;
    }
    showToast("测试已全部执行完毕！");
  });

  activeEventSource.onerror = () => {
    if (activeEventSource) {
      activeEventSource.close();
      activeEventSource = null;
    }
    const btn = document.getElementById("btn-start-run");
    btn.disabled = false;
    btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> 立即启动测试`;
  };
}

function appendPipelineLog(message, type = "info") {
  const container = document.getElementById("pipeline-logs");
  const now = new Date().toTimeString().split(" ")[0];
  const line = document.createElement("div");
  line.className = `log-line ${type}`;
  line.innerHTML = `<span class="timestamp">[${now}]</span> ${escapeHtml(message)}`;
  container.appendChild(line);
  container.scrollTop = container.scrollHeight;
}

function clearPipelineLogs() {
  document.getElementById("pipeline-logs").innerHTML = "";
}

// -------------------------------------------------------------
// 3. Cases List View
// -------------------------------------------------------------
let filterVerdict = "ALL";
let filterFocus = "ALL";
let filterCoverage = "ALL";
let filterSearch = "";
let searchDebounceTimer = null;

function initFilterControls() {
  document.querySelectorAll("#filter-verdict-group .btn-filter").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#filter-verdict-group .btn-filter").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      filterVerdict = btn.dataset.verdict;
      loadCasesList();
    });
  });

  document.getElementById("filter-focus-select").addEventListener("change", (e) => {
    filterFocus = e.target.value;
    loadCasesList();
  });

  const coverageSelect = document.getElementById("filter-coverage-select");
  if (coverageSelect) {
    coverageSelect.addEventListener("change", (e) => {
      filterCoverage = e.target.value;
      loadCasesList();
    });
  }

  document.getElementById("filter-search-input").addEventListener("input", (e) => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
      filterSearch = e.target.value.trim();
      loadCasesList();
    }, 250);
  });
}

async function loadCasesList(showLoadingNotice = true) {
  const tbody = document.querySelector("#cases-data-table tbody");
  if (showLoadingNotice) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">加载案例列表中...</td></tr>`;
  }

  try {
    const params = new URLSearchParams({
      verdict: filterVerdict,
      focus: filterFocus,
      coverage: filterCoverage,
      search: filterSearch,
    });
    const res = await fetch(`/api/cases?${params.toString()}`);
    if (!res.ok) throw new Error("获取案例列表失败");
    const cases = await res.json();

    if (!cases || cases.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">未找到符合条件的案例</td></tr>`;
      return;
    }

    tbody.innerHTML = "";
    cases.forEach(c => {
      const tr = document.createElement("tr");

      const verdictBadge = getVerdictBadgeHtml(c.judge_verdict, c.overall_result);
      const runnerBadge = c.runner_result === "EXECUTED"
        ? `<span class="badge badge-pass">记账成功</span>`
        : (c.runner_result === "FAILED" ? `<span class="badge badge-fail">记账抛错</span>` : `<span class="badge badge-subtle">-</span>`);

      const latencyText = c.latencies && c.latencies.total !== null ? `${c.latencies.total}s` : "-";
      const fMeta = FOCUS_DICT[c.focus] || { title: c.focus };

      // Artifacts dot indicators
      const arts = c.has_artifacts || {};
      const artDotsHtml = `
        <div class="art-dots">
          <span class="art-dot ${arts.raw_case ? 'active' : ''}" title="原始故事 Raw Case"></span>
          <span class="art-dot ${arts.compiler_result ? 'active' : ''}" title="编译尝试 Compiler"></span>
          <span class="art-dot ${arts.scenario ? 'active' : ''}" title="测试场景 Scenario v1"></span>
          <span class="art-dot ${arts.operations ? 'active' : ''}" title="数据库轨迹 Operations"></span>
          <span class="art-dot ${arts.state_final ? 'active' : ''}" title="账本终态 Final State"></span>
          <span class="art-dot ${arts.judge ? 'active' : ''}" title="法官裁决 Judge"></span>
        </div>
      `;

      tr.innerHTML = `
        <td>
          <strong>${c.id}</strong>
          ${c.run_id && c.id !== c.run_id ? `<div class="text-muted" style="font-size: 11px;">${c.run_id}</div>` : ''}
        </td>
        <td>
          <strong>${fMeta.title}</strong>
          <div class="text-muted" style="font-size: 11px;">${c.focus}${
            c.plan_seed !== null && c.plan_seed !== undefined ? ` · seed ${c.plan_seed}` : ''
          }</div>
          ${getCoverageBadgeHtml(c)}
        </td>
        <td style="font-size: 12px; color: var(--text-muted);">${c.time_display}</td>
        <td>${runnerBadge}</td>
        <td>${verdictBadge}</td>
        <td style="font-family: var(--font-mono); font-size: 12px;">${latencyText}</td>
        <td>${artDotsHtml}</td>
        <td>
          <button class="btn btn-sm btn-outline" onclick="window.location.hash='#detail/${encodeURIComponent(c.id)}'">
            查看详情
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Load cases error:", err);
    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">加载案例发生异常</td></tr>`;
  }
}

// -------------------------------------------------------------
// 4. Case Detail View
// -------------------------------------------------------------
async function openCaseDetail(caseId) {
  switchTab("detail");
  document.getElementById("detail-title").textContent = `案例详情: ${caseId}`;
  document.getElementById("art-code-display").textContent = "正在读取产物文件...";

  try {
    const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}`);
    if (!res.ok) throw new Error("案例不存在或无法读取");
    currentCaseDetail = await res.json();

    const arts = currentCaseDetail.artifacts || {};
    const resMeta = arts.result || {};
    const judgeData = arts.judge || {};

    // 1. Fill metadata card
    const fKey = resMeta.focus || "unknown";
    const fMeta = FOCUS_DICT[fKey] || { title: fKey };
    document.getElementById("meta-focus").textContent = `${fMeta.title} (${fKey})`;
    document.getElementById("meta-run-id").textContent = resMeta.run_id || caseId;
    document.getElementById("meta-time").textContent = currentCaseDetail.time_display || "-";

    const totalLat = [
      resMeta.generator_latency_seconds || resMeta.generation_latency_seconds,
      resMeta.compiler_latency_seconds,
      resMeta.runner_latency_seconds,
      resMeta.judge_latency_seconds
    ].filter(x => typeof x === 'number').reduce((a, b) => a + b, 0);

    document.getElementById("meta-latency").textContent = totalLat > 0 ? `${totalLat.toFixed(2)} 秒` : "-";

    const modelNames = [
      resMeta.local_generator_model || resMeta.local_model,
      resMeta.compiler_model,
      resMeta.judge_model
    ].filter(Boolean).join(" / ") || "系统默认模型配置";
    document.getElementById("meta-models").textContent = modelNames;

    // Badges in header
    const judgeVerdict = resMeta.judge_verdict || judgeData.verdict;
    document.getElementById("detail-badges").innerHTML = getVerdictBadgeHtml(judgeVerdict, resMeta.status);

    // 2. If judge found defects (FAIL or UNCERTAIN), highlight contradictions prominently
    const diffAlert = document.getElementById("detail-diff-alert");
    const diffContent = document.getElementById("detail-diff-content");

    if (judgeVerdict === "FAIL" || judgeVerdict === "UNCERTAIN") {
      diffAlert.style.display = "block";
      let diffHtml = `<div><strong>法官核心总结:</strong> ${escapeHtml(judgeData.summary || '业务逻辑比对不一致')}</div>`;

      if (judgeData.differences && judgeData.differences.length > 0) {
        diffHtml += `<ul style="margin-top: 6px;">${judgeData.differences.map(d => `<li><strong>矛盾点:</strong> ${escapeHtml(d)}</li>`).join("")}</ul>`;
      }
      diffContent.innerHTML = diffHtml;
    } else {
      diffAlert.style.display = "none";
    }

    // Show currently selected artifact tab
    renderArtifactContent(currentArtifactKey);
  } catch (err) {
    alert("加载 Case 详情失败: " + err.message);
    goBackFromDetail();
  }
}

function initArtifactTabs() {
  document.querySelectorAll(".art-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".art-tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      currentArtifactKey = tab.dataset.art;
      renderArtifactContent(currentArtifactKey);
    });
  });

  document.getElementById("btn-copy-artifact").addEventListener("click", () => {
    if (!currentCaseDetail) return;
    const content = getArtifactData(currentArtifactKey);
    if (!content) {
      showToast("当前产物为空");
      return;
    }
    const text = typeof content === "string" ? content : JSON.stringify(content, null, 2);
    navigator.clipboard.writeText(text).then(() => {
      showToast("已成功复制到剪贴板！");
    }).catch(() => {
      showToast("复制失败，请手动选择复制");
    });
  });
}

function getArtifactData(key) {
  if (!currentCaseDetail || !currentCaseDetail.artifacts) return null;
  return currentCaseDetail.artifacts[key];
}

function renderArtifactContent(key) {
  const codeEl = document.getElementById("art-code-display");
  const filenameEl = document.getElementById("art-current-filename");
  const guideText = document.getElementById("art-guide-text");

  const filenames = {
    raw_case: "raw_case.json (原始生活故事)",
    compiler_result: "compiler_result.json (指令转译记录)",
    scenario: "scenario.json (标准 Scenario v1 指令)",
    operations: "operations.jsonl (本地数据库调用日志)",
    state_final: "state_final.json (账本最终对账状态)",
    judge: "judge.json (业务法官裁决报告)",
  };
  filenameEl.textContent = filenames[key] || `${key}.json`;
  guideText.textContent = ARTIFACT_GUIDES[key] || "查看当前产物详情数据。";

  const data = getArtifactData(key);
  if (data === null || data === undefined) {
    codeEl.innerHTML = `<span class="text-muted">（该阶段未生成产物或未运行该步骤）</span>`;
    return;
  }

  codeEl.textContent = JSON.stringify(data, null, 2);
}

// -------------------------------------------------------------
// 5. Issue Queue View
// -------------------------------------------------------------
async function loadIssueQueue(showLoadingNotice = true) {
  const container = document.getElementById("issues-list-container");
  if (showLoadingNotice) {
    container.innerHTML = `<div class="text-center text-muted card" style="padding: 40px;">加载缺陷与异常列表中...</div>`;
  }

  try {
    const res = await fetch("/api/issues");
    if (!res.ok) throw new Error("获取问题队列失败");
    const issues = await res.json();

    // Counts
    let cFail = 0, cUncertain = 0, cComp = 0, cRun = 0, cJudge = 0;
    issues.forEach(i => {
      if (i.issue_type === "FAIL") cFail++;
      else if (i.issue_type === "UNCERTAIN") cUncertain++;
      else if (i.issue_type === "COMPILER_INVALID") cComp++;
      else if (i.issue_type === "RUNNER_FAILED") cRun++;
      else if (i.issue_type === "JUDGE_ERROR") cJudge++;
    });

    document.getElementById("issue-count-fail").textContent = cFail;
    document.getElementById("issue-count-uncertain").textContent = cUncertain;
    document.getElementById("issue-count-compiler").textContent = cComp;
    document.getElementById("issue-count-runner").textContent = cRun;
    document.getElementById("issue-count-judge").textContent = cJudge;

    // Update issue badge in nav
    const totalIssues = issues.length;
    const badge = document.getElementById("issues-count-badge");
    badge.textContent = totalIssues;
    badge.style.display = totalIssues > 0 ? "inline-block" : "none";

    if (totalIssues === 0) {
      container.innerHTML = `
        <div class="card text-center" style="padding: 50px;">
          <h3 style="color: var(--color-pass-text); margin-bottom: 8px;">太棒了！当前系统没有任何缺陷与异常案例</h3>
          <p class="text-muted">所有已执行的测试案例均通过了业务法官的查账审计。</p>
        </div>
      `;
      return;
    }

    container.innerHTML = "";
    issues.forEach(item => {
      const card = document.createElement("div");
      card.className = "issue-item";

      const badgeType = item.issue_type === "FAIL" ? "badge-fail" :
        (item.issue_type === "UNCERTAIN" ? "badge-uncertain" : "badge-error");

      const fMeta = FOCUS_DICT[item.focus] || { title: item.focus || '未知场景' };

      let diffHtml = "";
      if (item.differences && item.differences.length > 0) {
        diffHtml = `<ul class="issue-diff-list">${item.differences.map(d => `<li><strong>矛盾点:</strong> ${escapeHtml(d)}</li>`).join("")}</ul>`;
      }

      card.innerHTML = `
        <div class="issue-item-header">
          <div class="issue-item-title">
            <span class="badge ${badgeType}">${item.issue_type === 'FAIL' ? '业务规则冲突 FAIL' : item.issue_type}</span>
            <h4>${fMeta.title}</h4>
            <span class="tag" style="font-size: 11px;">${escapeHtml(item.id)}</span>
          </div>
          <button class="btn btn-sm btn-outline" onclick="window.location.hash='#detail/${encodeURIComponent(item.id)}'">
            排查审计证据
          </button>
        </div>

        <div class="issue-item-desc">
          <strong>法官指出:</strong> ${escapeHtml(item.summary || item.loader_error || '未记录明确错误信息')}
          ${diffHtml}
        </div>

        <div class="issue-item-footer">
          <span>发生时间: ${item.time_display}</span>
          <span>Run 标识: ${item.run_id || '-'}</span>
        </div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    console.error("Load issue queue error:", err);
    container.innerHTML = `<div class="card text-center text-muted" style="padding: 30px;">加载问题队列发生错误</div>`;
  }
}

// -------------------------------------------------------------
// Helper Utilities
// -------------------------------------------------------------
function getVerdictBadgeHtml(verdict, overallStatus) {
  if (verdict === "PASS") {
    return `<span class="badge badge-pass">✅ 通过 PASS</span>`;
  } else if (verdict === "FAIL") {
    return `<span class="badge badge-fail">❌ 发现缺陷 FAIL</span>`;
  } else if (verdict === "UNCERTAIN") {
    return `<span class="badge badge-uncertain">⚠️ 存疑 UNCERTAIN</span>`;
  } else if (verdict === "JUDGE_ERROR" || overallStatus === "JUDGE_ERROR") {
    return `<span class="badge badge-error">🚫 裁判异常 JUDGE_ERR</span>`;
  } else if (overallStatus === "COMPILER_INVALID") {
    return `<span class="badge badge-error">🚫 格式不合规 COMPILER_INVALID</span>`;
  } else if (overallStatus === "RUNNER_FAILED") {
    return `<span class="badge badge-fail">🚫 记账失败 RUNNER_FAILED</span>`;
  } else if (overallStatus === "GENERATION_ERROR") {
    return `<span class="badge badge-error">🚫 故事生成异常 GEN_ERROR</span>`;
  } else if (overallStatus === "EXECUTED") {
    return `<span class="badge badge-info">已记账 EXECUTED</span>`;
  } else if (overallStatus === "LOADER_VALID") {
    return `<span class="badge badge-info">格式通过 VALID</span>`;
  }
  return `<span class="badge badge-subtle">${overallStatus || '未知 UNKNOWN'}</span>`;
}

/**
 * Coverage badge: whether this generated case counts towards verified coverage.
 * A case can be a business PASS and still not be coverage.
 */
function getCoverageBadgeHtml(c) {
  if (c.source_type !== "generated") {
    return "";
  }
  if (c.duplicate) {
    const canonical = c.duplicate_of ? c.duplicate_of.slice(-6) : "";
    return `<div class="cov-badge cov-duplicate" title="与更早案例 ${c.duplicate_of || ''} 的业务结构相同，不计入唯一覆盖">
      ♻️ DUPLICATE_CASE${canonical ? ` → …${canonical}` : ''}</div>`;
  }
  if (c.focus_status === "FOCUS_MISMATCH") {
    return `<div class="cov-badge cov-mismatch" title="${escapeHtml(c.focus_error || '')}">
      🎯 FOCUS_MISMATCH</div>`;
  }
  if (c.coverage_status === "UNIQUE_VALID") {
    return `<div class="cov-badge cov-unique">✔ 唯一有效覆盖</div>`;
  }
  if (c.focus_status === "UNKNOWN") {
    return `<div class="cov-badge cov-unknown" title="该案例生成于 Focus Contract 启用之前">覆盖状态未知</div>`;
  }
  return `<div class="cov-badge cov-invalid">未计入覆盖</div>`;
}

/** Fill the focus filter and the run-picker from the backend focus registry. */
async function loadFocusCatalog() {
  try {
    const res = await fetch("/api/config/info");
    if (!res.ok) return null;
    const data = await res.json();
    const focuses = data.supported_focuses || [];
    focuses.forEach(f => {
      FOCUS_DICT[f.id] = { title: f.name.replace(/\s*\([^)]*\)$/, ""), desc: f.desc };
    });
    const select = document.getElementById("filter-focus-select");
    if (select && select.options.length <= 1) {
      focuses.forEach(f => {
        const option = document.createElement("option");
        option.value = f.id;
        option.textContent = `${f.name}${f.tier === "smoke" ? " · Smoke" : ""}`;
        select.appendChild(option);
      });
    }
    return data;
  } catch (err) {
    console.error("Load focus catalog error:", err);
    return null;
  }
}

/** Render the coverage KPI strip from the dashboard payload. */
function renderCoverageStats(coverage) {
  if (!coverage) return;
  const pct = (part, whole) => (whole ? Math.round((part / whole) * 100) : 0);
  const generated = coverage.generated_count || 0;
  const focusValid = coverage.focus_valid_count || 0;
  const unique = coverage.unique_valid_count || 0;

  const set = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };
  set("cov-generated", generated);
  set("cov-focus-valid", `${focusValid} (${pct(focusValid, generated)}%)`);
  set("cov-focus-mismatch", coverage.focus_mismatch_count || 0);
  set("cov-duplicate", coverage.duplicate_count || 0);
  set("cov-unique-valid", unique);

  const duplicateSub = document.getElementById("cov-duplicate-sub");
  if (duplicateSub && focusValid) {
    duplicateSub.textContent =
      `占命中案例 ${Math.round(((coverage.duplicate_count || 0) / focusValid) * 100)}%；与更早案例业务结构相同`;
  }
  const uniqueSub = document.getElementById("cov-unique-valid-sub");
  if (uniqueSub) {
    uniqueSub.textContent = coverage.pass_rate === null || coverage.pass_rate === undefined
      ? `PASS 率以此为分母；当前无法计算`
      : `PASS 率 ${coverage.pass_rate}%（分母为唯一有效覆盖 ${unique}）`;
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
