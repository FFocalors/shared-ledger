/**
 * Shared Ledger Verification Console - Vanilla JavaScript Application
 */

// Global State
let currentTab = "dashboard";
let currentCaseDetail = null;
let currentArtifactKey = "raw_case";
let activeEventSource = null;
let currentBatchId = null;

// Initialize when DOM ready
document.addEventListener("DOMContentLoaded", () => {
  initNavigation();
  initArtifactTabs();
  initFilterControls();
  initRunForm();
  checkEnvironment();

  // Handle URL hash routing
  handleHashRouting();
  window.addEventListener("hashchange", handleHashRouting);
});

// Toast notification helper
function showToast(message, duration = 2500) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => {
    toast.classList.remove("show");
  }, duration);
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
        <span class="status-text">本地就绪 (Supabase + DeepSeek)</span>
      `;
      badge.title = `Generator: ${env.local_generator_model}\nCompiler/Judge: ${env.compiler_model}`;
    } else {
      badge.innerHTML = `
        <span class="status-dot warning"></span>
        <span class="status-text">环境部分就绪</span>
      `;
      badge.title = `Supabase: ${hasSupabase ? 'OK' : '缺少配置'}\nDeepSeek: ${hasDeepSeek ? 'OK' : '缺少配置'}`;
    }
  } catch (err) {
    badge.innerHTML = `
      <span class="status-dot danger"></span>
      <span class="status-text">服务连接异常</span>
    `;
  }
}

// -------------------------------------------------------------
// 1. Dashboard View
// -------------------------------------------------------------
async function loadDashboardData() {
  try {
    const res = await fetch("/api/dashboard");
    if (!res.ok) throw new Error("加载仪表盘失败");
    const data = await res.json();

    // 1. Total & Verdict stats
    document.getElementById("stat-total-cases").textContent = data.total_cases;
    const v = data.verdicts || {};
    document.getElementById("stat-pass").textContent = `PASS ${v.PASS || 0}`;
    document.getElementById("stat-fail").textContent = `FAIL ${v.FAIL || 0}`;
    document.getElementById("stat-uncertain").textContent = `UNCERTAIN ${v.UNCERTAIN || 0}`;
    document.getElementById("stat-error").textContent = `ERROR ${v.ERROR || 0}`;

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
      `VALID: ${loader.valid || 0} / 校验总数: ${loader.tested || 0}`;

    // 3. Runner stats
    const runner = data.runner_stats || {};
    document.getElementById("stat-runner-rate").textContent = `${runner.execution_rate}%`;
    document.getElementById("stat-runner-bar").style.width = `${runner.execution_rate}%`;
    document.getElementById("stat-runner-detail").textContent =
      `EXECUTED: ${runner.executed || 0} / 执行总数: ${runner.tested || 0}`;

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
        tr.innerHTML = `
          <td><strong>${f.focus}</strong></td>
          <td>${f.total}</td>
          <td><span class="badge badge-pass">${f.pass}</span></td>
          <td><span class="badge badge-fail">${f.fail}</span></td>
          <td><span class="badge badge-error">${f.error}</span></td>
          <td><strong>${f.pass_rate}%</strong></td>
        `;
        tbody.appendChild(tr);
      });
    } else {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">暂无 Focus 统计数据</td></tr>`;
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
        const runnerBadge = c.runner_result === "EXECUTED"
          ? `<span class="badge badge-pass">EXECUTED</span>`
          : (c.runner_result === "FAILED" ? `<span class="badge badge-fail">FAILED</span>` : `<span class="badge badge-subtle">-</span>`);

        row.innerHTML = `
          <div>
            <strong>${c.id}</strong>
            <span class="tag" style="margin-left: 8px;">${c.focus}</span>
          </div>
          <div style="display: flex; align-items: center; gap: 12px;">
            <span class="text-muted" style="font-size: 12px;">${c.time_display}</span>
            ${runnerBadge}
            ${verdictBadge}
          </div>
        `;
        recentContainer.appendChild(row);
      });
    } else {
      recentContainer.innerHTML = `<div class="text-muted text-center">暂无近期案例</div>`;
    }
  } catch (err) {
    console.error("Dashboard error:", err);
    showToast("加载仪表盘数据出错");
  }
}

// -------------------------------------------------------------
// 2. Run Workflow View
// -------------------------------------------------------------
function initRunForm() {
  const form = document.getElementById("workflow-run-form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const focus = document.getElementById("select-focus").value;
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
      showToast(`测试已启动 (批次: ${currentBatchId})`);

      // Show pipeline progress card
      const pipelineCard = document.getElementById("pipeline-card");
      pipelineCard.style.display = "block";
      pipelineCard.scrollIntoView({ behavior: "smooth" });

      resetPipelineDisplay();
      startPipelineEventStream(currentBatchId);
    } catch (err) {
      alert("启动工作流失败: " + err.message);
      btn.disabled = false;
      btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> 启动测试工作流`;
    }
  });
}

function resetPipelineDisplay() {
  ["generator", "compiler", "loader", "runner", "judge"].forEach(stage => {
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
    document.getElementById("pipeline-batch-info").textContent =
      `场景: ${data.focus} | 批次数量: ${data.total_count} 个案例`;
    appendPipelineLog(`[批次启动] 场景: ${data.focus}, 计划执行: ${data.total_count} 个`, "info");
  });

  activeEventSource.addEventListener("case_started", (e) => {
    const data = JSON.parse(e.data);
    document.getElementById("pipeline-status-text").textContent =
      `正在执行第 ${data.case_index} / ${data.total_count} 个案例...`;
    appendPipelineLog(`[Case ${data.case_index}/${data.total_count}] 开始执行端到端验证流水线`, "running");
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
        appendPipelineLog(` ➔ [${stage.toUpperCase()}] 阶段开始执行`, "running");
      } else if (status === "completed") {
        let text = "已完成";
        if (details.latency) text = `${details.latency}s`;
        if (details.verdict) text = `${details.verdict} (${details.latency}s)`;
        statusEl.textContent = text;
        appendPipelineLog(` ✔ [${stage.toUpperCase()}] 成功完成 (${text})`, "success");
      } else if (status === "failed") {
        statusEl.textContent = details.error || "失败";
        appendPipelineLog(` ✖ [${stage.toUpperCase()}] 执行失败: ${details.error || ''}`, "error");
      } else if (status === "skipped") {
        statusEl.textContent = "跳过";
        appendPipelineLog(` ⊘ [${stage.toUpperCase()}] 已跳过`, "info");
      }
    }
  });

  activeEventSource.addEventListener("case_completed", (e) => {
    const data = JSON.parse(e.data);
    const r = data.result || {};
    appendPipelineLog(`[Case ${data.case_index}/${data.total_count}] 结束: Judge=${r.judge_verdict || '-'}, Runner=${r.runner_result || '-'}`, "success");

    // Show result item in pipeline-result-box
    const resultBox = document.getElementById("pipeline-result-box");
    resultBox.style.display = "block";

    const item = document.createElement("div");
    item.className = "recent-case-row";
    item.style.marginTop = "8px";
    item.innerHTML = `
      <div>
        <strong>Case ID: ${data.case_id || '完成'}</strong>
        <span style="margin-left: 8px;">Run ID: ${r.run_id || '-'}</span>
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
    appendPipelineLog(`[Case ${data.case_index}/${data.total_count}] 异常失败: ${data.error}`, "error");
  });

  activeEventSource.addEventListener("batch_completed", (e) => {
    const data = JSON.parse(e.data);
    appendPipelineLog(`[批次结束] 全部 ${data.total_count} 个案例执行完毕！`, "success");
    document.getElementById("pipeline-status-text").textContent = "批次执行完成";

    const btn = document.getElementById("btn-start-run");
    btn.disabled = false;
    btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> 启动测试工作流`;

    if (activeEventSource) {
      activeEventSource.close();
      activeEventSource = null;
    }
    showToast("流水线测试执行完毕！");
  });

  activeEventSource.onerror = () => {
    // If disconnected, close
    if (activeEventSource) {
      activeEventSource.close();
      activeEventSource = null;
    }
    const btn = document.getElementById("btn-start-run");
    btn.disabled = false;
    btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> 启动测试工作流`;
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
let filterSearch = "";
let searchDebounceTimer = null;

function initFilterControls() {
  // Verdict filter buttons
  document.querySelectorAll("#filter-verdict-group .btn-filter").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#filter-verdict-group .btn-filter").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      filterVerdict = btn.dataset.verdict;
      loadCasesList();
    });
  });

  // Focus filter select
  document.getElementById("filter-focus-select").addEventListener("change", (e) => {
    filterFocus = e.target.value;
    loadCasesList();
  });

  // Search input with debounce
  document.getElementById("filter-search-input").addEventListener("input", (e) => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
      filterSearch = e.target.value.trim();
      loadCasesList();
    }, 250);
  });
}

async function loadCasesList() {
  const tbody = document.querySelector("#cases-data-table tbody");
  tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">加载案例列表中...</td></tr>`;

  try {
    const params = new URLSearchParams({
      verdict: filterVerdict,
      focus: filterFocus,
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
        ? `<span class="badge badge-pass">EXECUTED</span>`
        : (c.runner_result === "FAILED" ? `<span class="badge badge-fail">FAILED</span>` : `<span class="badge badge-subtle">-</span>`);

      const latencyText = c.latencies && c.latencies.total !== null ? `${c.latencies.total}s` : "-";

      // Artifacts dot indicators
      const arts = c.has_artifacts || {};
      const artDotsHtml = `
        <div class="art-dots">
          <span class="art-dot ${arts.raw_case ? 'active' : ''}" title="Raw Case"></span>
          <span class="art-dot ${arts.compiler_result ? 'active' : ''}" title="Compiler"></span>
          <span class="art-dot ${arts.scenario ? 'active' : ''}" title="Scenario v1"></span>
          <span class="art-dot ${arts.operations ? 'active' : ''}" title="Operations"></span>
          <span class="art-dot ${arts.state_final ? 'active' : ''}" title="Final State"></span>
          <span class="art-dot ${arts.judge ? 'active' : ''}" title="Judge"></span>
        </div>
      `;

      tr.innerHTML = `
        <td>
          <strong>${c.run_id || c.id}</strong>
          ${c.run_id && c.id !== c.run_id ? `<div class="text-muted" style="font-size: 11px;">${c.id}</div>` : ''}
        </td>
        <td><span class="tag">${c.focus}</span></td>
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
  document.getElementById("detail-title").textContent = `Case: ${caseId}`;
  document.getElementById("art-code-display").textContent = "正在读取产物文件...";

  try {
    const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}`);
    if (!res.ok) throw new Error("案例不存在或无法读取");
    currentCaseDetail = await res.json();

    const arts = currentCaseDetail.artifacts || {};
    const resMeta = arts.result || {};

    // Fill metadata cards
    document.getElementById("meta-focus").textContent = resMeta.focus || "-";
    document.getElementById("meta-run-id").textContent = resMeta.run_id || caseId;
    document.getElementById("meta-time").textContent = currentCaseDetail.time_display || "-";

    const totalLat = [
      resMeta.generator_latency_seconds || resMeta.generation_latency_seconds,
      resMeta.compiler_latency_seconds,
      resMeta.runner_latency_seconds,
      resMeta.judge_latency_seconds
    ].filter(x => typeof x === 'number').reduce((a, b) => a + b, 0);

    document.getElementById("meta-latency").textContent = totalLat > 0 ? `${totalLat.toFixed(2)}s` : "-";

    const modelNames = [
      resMeta.local_generator_model || resMeta.local_model,
      resMeta.compiler_model,
      resMeta.judge_model
    ].filter(Boolean).join(" / ") || "默认模型配置";
    document.getElementById("meta-models").textContent = modelNames;

    // Badges in header
    const judgeVerdict = resMeta.judge_verdict || (arts.judge ? arts.judge.verdict : null);
    document.getElementById("detail-badges").innerHTML = getVerdictBadgeHtml(judgeVerdict, resMeta.status);

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
      showToast("已复制到剪贴板！");
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

  const filenames = {
    raw_case: "raw_case.json",
    compiler_result: "compiler_result.json",
    scenario: "scenario.json",
    operations: "operations.jsonl",
    state_final: "state_final.json",
    judge: "judge.json",
  };
  filenameEl.textContent = filenames[key] || `${key}.json`;

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
async function loadIssueQueue() {
  const container = document.getElementById("issues-list-container");
  container.innerHTML = `<div class="text-center text-muted card" style="padding: 40px;">加载问题队列中...</div>`;

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
          <h3 style="color: var(--color-pass-text); margin-bottom: 8px;">太棒了！当前没有任何异常案例</h3>
          <p class="text-muted">所有已执行的案例均已通过 (PASS) 或正常完成。</p>
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

      let diffHtml = "";
      if (item.differences && item.differences.length > 0) {
        diffHtml = `<ul class="issue-diff-list">${item.differences.map(d => `<li>${escapeHtml(d)}</li>`).join("")}</ul>`;
      }

      card.innerHTML = `
        <div class="issue-item-header">
          <div class="issue-item-title">
            <span class="badge ${badgeType}">${item.issue_type}</span>
            <h4>${escapeHtml(item.id)}</h4>
            <span class="tag">${item.focus || 'unknown'}</span>
          </div>
          <button class="btn btn-sm btn-outline" onclick="window.location.hash='#detail/${encodeURIComponent(item.id)}'">
            排查 Case 产物
          </button>
        </div>

        <div class="issue-item-desc">
          <strong>问题摘要:</strong> ${escapeHtml(item.summary || item.loader_error || '未记录明确错误信息')}
          ${diffHtml}
        </div>

        <div class="issue-item-footer">
          <span>发生时间: ${item.time_display}</span>
          <span>Run ID: ${item.run_id || '-'}</span>
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
    return `<span class="badge badge-pass">PASS</span>`;
  } else if (verdict === "FAIL") {
    return `<span class="badge badge-fail">FAIL</span>`;
  } else if (verdict === "UNCERTAIN") {
    return `<span class="badge badge-uncertain">UNCERTAIN</span>`;
  } else if (verdict === "JUDGE_ERROR" || overallStatus === "JUDGE_ERROR") {
    return `<span class="badge badge-error">JUDGE_ERROR</span>`;
  } else if (overallStatus === "COMPILER_INVALID") {
    return `<span class="badge badge-error">COMPILER_INVALID</span>`;
  } else if (overallStatus === "RUNNER_FAILED") {
    return `<span class="badge badge-fail">RUNNER_FAILED</span>`;
  } else if (overallStatus === "GENERATION_ERROR") {
    return `<span class="badge badge-error">GEN_ERROR</span>`;
  } else if (overallStatus === "EXECUTED") {
    return `<span class="badge badge-info">EXECUTED</span>`;
  } else if (overallStatus === "LOADER_VALID") {
    return `<span class="badge badge-info">VALID</span>`;
  }
  return `<span class="badge badge-subtle">${overallStatus || 'UNKNOWN'}</span>`;
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
