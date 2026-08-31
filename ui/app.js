const state = {
  jobs: [],
  summary: null,
  runs: [],
  errors: [],
};

const els = {
  totalJobs: document.querySelector("#totalJobs"),
  latestCandidates: document.querySelector("#latestCandidates"),
  latestSaved: document.querySelector("#latestSaved"),
  latestSkipped: document.querySelector("#latestSkipped"),
  resultCount: document.querySelector("#resultCount"),
  jobsList: document.querySelector("#jobsList"),
  sourceStats: document.querySelector("#sourceStats"),
  runStats: document.querySelector("#runStats"),
  errorStats: document.querySelector("#errorStats"),
  searchInput: document.querySelector("#searchInput"),
  statusFilter: document.querySelector("#statusFilter"),
  sourceFilter: document.querySelector("#sourceFilter"),
  refreshButton: document.querySelector("#refreshButton"),
  jobTemplate: document.querySelector("#jobTemplate"),
};

function esc(value) {
  return value || "미확인";
}

function fmtDate(value) {
  if (!value) return "마감 미확인";
  if (value === "rolling") return "상시";
  return value;
}

function statusLabel(value) {
  return {
    needs_review: "검토 필요",
    approved: "승인",
    rejected: "제외",
  }[value] || value || "검토 필요";
}

function params() {
  const query = new URLSearchParams();
  if (els.searchInput.value.trim()) query.set("q", els.searchInput.value.trim());
  if (els.statusFilter.value) query.set("status", els.statusFilter.value);
  if (els.sourceFilter.value) query.set("source", els.sourceFilter.value);
  query.set("limit", "300");
  return query.toString();
}

async function getJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function loadAll() {
  const [summary, jobs, runs, errors] = await Promise.all([
    getJson("/api/summary"),
    getJson(`/api/jobs?${params()}`),
    getJson("/api/runs"),
    getJson("/api/errors"),
  ]);
  state.summary = summary;
  state.jobs = jobs.jobs;
  state.runs = runs.runs;
  state.errors = errors.errors;
  render();
}

function render() {
  renderSummary();
  renderSourceFilter();
  renderJobs();
  renderSidebars();
}

function renderSummary() {
  const latest = state.summary.latest_run || {};
  els.totalJobs.textContent = state.summary.total || 0;
  els.latestCandidates.textContent = latest.candidates || 0;
  els.latestSaved.textContent = latest.saved || 0;
  els.latestSkipped.textContent = latest.skipped || 0;
}

function renderSourceFilter() {
  const current = els.sourceFilter.value;
  const sources = state.summary.by_source || [];
  els.sourceFilter.innerHTML = '<option value="">전체 출처</option>';
  for (const source of sources) {
    const option = document.createElement("option");
    option.value = source.source_name;
    option.textContent = `${source.source_name} (${source.count})`;
    els.sourceFilter.append(option);
  }
  els.sourceFilter.value = current;
}

function renderJobs() {
  els.resultCount.textContent = `${state.jobs.length}건`;
  els.jobsList.innerHTML = "";

  if (state.jobs.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "표시할 공고가 없습니다.";
    els.jobsList.append(empty);
    return;
  }

  for (const job of state.jobs) {
    const node = els.jobTemplate.content.cloneNode(true);
    const article = node.querySelector(".job");
    article.dataset.status = job.status;
    node.querySelector("h3").textContent = job.title;
    node.querySelector(".meta").textContent = [
      esc(job.institution_name),
      esc(job.location_text),
      job.source_name,
      job.status,
    ].join(" · ");
    node.querySelector(".description").textContent = job.description || "본문 미수집";
    const noteInput = node.querySelector(".note-input");
    noteInput.value = job.review_note || "";
    for (const button of node.querySelectorAll(".review-actions button")) {
      button.addEventListener("click", () => updateReview(job.job_id, button.dataset.status, noteInput.value));
    }
    const status = node.querySelector(".status");
    status.textContent = statusLabel(job.status);
    status.className = `status ${job.status}`;
    node.querySelector(".score").textContent = `신뢰도 ${job.confidence_score}`;
    node.querySelector(".deadline").textContent = fmtDate(job.deadline);
    const link = node.querySelector("a");
    if (job.original_url) {
      link.href = job.original_url;
    } else {
      link.textContent = "링크 없음";
      link.classList.add("disabled");
      link.removeAttribute("href");
    }
    els.jobsList.append(node);
  }
}

async function updateReview(jobId, status, reviewNote) {
  await fetch(`/api/jobs/${jobId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, review_note: reviewNote }),
  });
  await loadAll();
}

function renderSidebars() {
  renderRows(
    els.sourceStats,
    state.summary.by_source || [],
    (row) => row.source_name,
    (row) => row.count
  );

  renderRows(
    els.runStats,
    state.runs,
    (row) => `#${row.run_id} ${row.finished_at || row.started_at}`,
    (row) => `${row.saved}/${row.candidates}`
  );

  renderRows(
    els.errorStats,
    state.errors,
    (row) => row.source_name,
    (row) => row.message
  );
}

function renderRows(container, rows, labelFn, valueFn) {
  container.innerHTML = "";
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "stat-row";
    empty.textContent = "없음";
    container.append(empty);
    return;
  }
  for (const row of rows) {
    const div = document.createElement("div");
    div.className = "stat-row";
    const label = document.createElement("span");
    label.textContent = labelFn(row);
    const value = document.createElement("strong");
    value.textContent = valueFn(row);
    div.append(label, value);
    container.append(div);
  }
}

let searchTimer = null;
function scheduleLoad() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadAll, 180);
}

els.refreshButton.addEventListener("click", loadAll);
els.searchInput.addEventListener("input", scheduleLoad);
els.statusFilter.addEventListener("change", loadAll);
els.sourceFilter.addEventListener("change", loadAll);

loadAll().catch((error) => {
  els.jobsList.innerHTML = "";
  const empty = document.createElement("p");
  empty.className = "empty";
  empty.textContent = `불러오기 실패: ${error.message}`;
  els.jobsList.append(empty);
});
