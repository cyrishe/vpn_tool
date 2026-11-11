"use strict";

const byId = (id) => document.getElementById(id);
const formValues = (form) => Object.fromEntries(new FormData(form));
const pageSize = 50;
const offsets = { node: 0, region: 0 };
let token = "";
let credential = null;
let nodeFilter = "";
let editingRegion = null;
let busy = false;

function notice(message = "", error = false) {
  const target = byId("notice");
  target.textContent = message;
  target.classList.toggle("error", error);
  target.hidden = !message;
}

function selectPanel(panel) {
  for (const button of document.querySelectorAll("[data-panel]")) {
    const selected = button.dataset.panel === panel;
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
    byId(button.dataset.panel).hidden = !selected;
  }
}

function clearCredential() {
  credential = null;
  byId("credential-panel").hidden = true;
}

function resetRegion() {
  editingRegion = null;
  const form = byId("region-form");
  form.reset();
  form.elements.code.disabled = false;
  byId("region-form-title").textContent = "新增地域";
}

function lock() {
  token = "";
  clearCredential();
  resetRegion();
  for (const form of document.forms) form.reset();
  for (const id of ["node-rows", "region-rows", "region-codes", "node-pages", "region-pages", "account-summary"]) {
    byId(id).replaceChildren();
  }
  byId("account-summary").hidden = true;
  byId("login-panel").hidden = false;
  byId("console").hidden = true;
  byId("logout").hidden = true;
  offsets.node = offsets.region = 0;
  nodeFilter = "";
  notice();
}

async function api(path, method = "GET", body) {
  const response = await fetch("/admin/api/" + path, {
    method,
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
  });
  if (response.status === 401) lock();
  const result = await response.json();
  if (!response.ok) {
    const fields = result.error?.details?.map((item) => item.loc.at(-1)).join("、");
    throw new Error(fields ? "请检查字段 " + fields : (result.error?.message ?? "请求失败。"));
  }
  return result;
}

async function run(action, button) {
  if (busy) return;
  busy = true;
  if (button) button.disabled = true;
  byId("logout").disabled = true;
  notice();
  try {
    await action();
  } catch (error) {
    notice(error.message, true);
  } finally {
    busy = false;
    if (button) button.disabled = false;
    byId("logout").disabled = false;
  }
}

function onSubmit(id, action) {
  const form = byId(id);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    run(() => action(form), event.submitter);
  });
}

function actionButton(title, action, style = "subtle") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = style;
  button.textContent = title;
  button.addEventListener("click", () => run(action, button));
  return button;
}

function row(values) {
  const result = document.createElement("tr");
  for (const value of values) {
    const cell = result.insertCell();
    if (value instanceof Node) cell.append(value);
    else cell.textContent = value;
  }
  return result;
}

function renderRows(id, rows, columns, message) {
  const tbody = byId(id);
  tbody.replaceChildren(...rows);
  if (!rows.length) {
    const cell = tbody.insertRow().insertCell();
    cell.colSpan = columns;
    cell.textContent = message;
  }
}

function badge(text, tone) {
  const element = document.createElement("span");
  element.className = "state " + tone;
  element.textContent = text;
  return element;
}

function paginate(kind, count, reload) {
  const previous = actionButton("上一页", async () => reload(Math.max(0, offsets[kind] - pageSize)));
  const next = actionButton("下一页", async () => reload(offsets[kind] + pageSize));
  previous.disabled = offsets[kind] === 0;
  next.disabled = count < pageSize;
  const label = document.createElement("span");
  label.textContent = "第 " + (offsets[kind] / pageSize + 1) + " 页";
  byId(kind + "-pages").replaceChildren(previous, label, next);
}

function nodeStatus(node) {
  const states = {
    provisioning: "等待 Agent",
    verifying: "待核验",
    ready: "可接单",
    draining: "排空中",
    unhealthy: "不健康",
    terminated: "已退役",
  };
  if (node.status === "ready" && !node.accepting_connections) {
    if (node.heartbeat_age_seconds >= 30) return badge("心跳超时", "attention");
    if (node.current_peers >= node.capacity) return badge("容量已满", "attention");
    return badge("暂停调度", "attention");
  }
  return badge(states[node.status] ?? node.status, node.accepting_connections ? "good" : "");
}

function nodeActions(node) {
  const buttons = document.createElement("div");
  async function change(action, message) {
    if (message && !window.confirm(message)) return;
    await api("nodes/" + node.id + "/state", "POST", { action });
    await loadNodes();
    notice("已更新节点 " + node.name + " 的状态。");
  }
  if (["verifying", "draining"].includes(node.status) && node.heartbeat_age_seconds < 30) {
    buttons.append(actionButton("上线", () => change("online", "已核验这个节点的 UDP 和实际出口，可以接收用户连接？")));
  }
  if (node.status === "ready") {
    buttons.append(actionButton("排空", () => change("drain", "停止向此节点分配新连接，保留现有连接？")));
  }
  if (node.status !== "terminated") {
    buttons.append(actionButton("退役", () => change("retire", "退役会撤销节点凭证并释放现有连接。确定退役？"), "danger"));
  }
  return buttons;
}

async function loadNodes(offset = offsets.node) {
  const query = new URLSearchParams({ offset });
  if (nodeFilter) query.set("region", nodeFilter);
  const nodes = await api("nodes?" + query);
  offsets.node = offset;
  renderRows("node-rows", nodes.map((node) => row([
    node.name, node.region, node.endpoint, nodeStatus(node),
    node.heartbeat_age_seconds === null ? "尚未连接" : node.heartbeat_age_seconds + " 秒前",
    node.current_peers + " / " + node.capacity, nodeActions(node),
  ])), 7, "当前没有节点。");
  paginate("node", nodes.length, loadNodes);
}

function editRegion(region) {
  const form = byId("region-form");
  editingRegion = region;
  form.elements.code.value = region.code;
  form.elements.code.disabled = true;
  form.elements.name.value = region.name;
  form.elements.province_code.value = region.province_code;
  form.elements.is_enabled.checked = region.is_enabled;
  byId("region-form-title").textContent = "编辑 " + region.name;
  byId("region-editor").open = true;
  form.elements.name.focus();
}

async function loadRegions(offset = offsets.region) {
  const regions = await api("regions?" + new URLSearchParams({ offset }));
  offsets.region = offset;
  byId("region-codes").replaceChildren(...regions.map((region) => new Option(region.name, region.code)));
  renderRows("region-rows", regions.map((region) => row([
    region.name, region.code, region.province_code,
    badge(region.is_enabled ? "已开放" : "已停用", region.is_enabled ? "good" : ""),
    actionButton("编辑", () => editRegion(region)),
  ])), 5, "当前没有地域。");
  paginate("region", regions.length, loadRegions);
}

function showAccount(account) {
  const summary = byId("account-summary");
  const expiration = account.expires_at ? new Date(account.expires_at).toLocaleString() : "无生效授权";
  summary.textContent = account.email + " · " + (account.status === "active" ? "正常" : "停用") + " · " + expiration;
  summary.hidden = false;
  byId("grant").elements.regions.value = account.regions.join(", ");
}

onSubmit("login", async (form) => {
  token = form.elements.token.value.trim();
  form.reset();
  try {
    await Promise.all([loadNodes(), loadRegions()]);
    selectPanel("nodes");
    byId("login-panel").hidden = true;
    byId("console").hidden = false;
    byId("logout").hidden = false;
  } catch (error) {
    lock();
    throw error;
  }
});
byId("logout").addEventListener("click", lock);
for (const button of document.querySelectorAll("[data-panel]")) {
  button.addEventListener("click", () => selectPanel(button.dataset.panel));
}
byId("refresh-nodes").addEventListener("click", (event) => run(loadNodes, event.currentTarget));
byId("refresh-regions").addEventListener("click", (event) => run(loadRegions, event.currentTarget));
onSubmit("filter-nodes", async (form) => {
  nodeFilter = form.elements.region.value.trim();
  await loadNodes(0);
});

onSubmit("enroll", async (form) => {
  if (credential) throw new Error("请先保存或关闭上一个节点凭证。");
  const payload = formValues(form);
  for (const name of ["name", "region", "endpoint", "public_key"]) payload[name] = payload[name].trim();
  payload.capacity = Number(payload.capacity);
  const result = await api("nodes", "POST", payload);
  credential = result.credential;
  form.reset();
  byId("credential-panel").hidden = false;
  await loadNodes(0);
  notice("节点已登记。请保存凭证并启动 Agent。");
});
byId("close-credential").addEventListener("click", clearCredential);
byId("download-credential").addEventListener("click", () => {
  if (!credential) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(credential, null, 2) + "\n"], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "gateway.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

onSubmit("region-form", async (form) => {
  const payload = formValues(form);
  payload.is_enabled = form.elements.is_enabled.checked;
  if (editingRegion) {
    if (editingRegion.is_enabled && !payload.is_enabled &&
        !window.confirm("停用地域会停止调度并释放当前连接。确定停用？")) return;
    await api("regions/" + editingRegion.code, "PUT", payload);
  } else {
    await api("regions", "POST", payload);
  }
  resetRegion();
  byId("region-editor").open = false;
  await Promise.all([loadRegions(0), loadNodes()]);
  notice("已保存地域。");
});
byId("reset-region").addEventListener("click", resetRegion);
byId("lookup-account").addEventListener("click", (event) => {
  const input = byId("grant").elements.email;
  if (!input.reportValidity()) return;
  byId("account-summary").hidden = true;
  run(async () => showAccount(await api("accounts/lookup", "POST", { email: input.value })), event.currentTarget);
});
byId("grant").elements.email.addEventListener("input", () => { byId("account-summary").hidden = true; });
onSubmit("grant", async (form) => {
  const values = formValues(form);
  const payload = {
    email: values.email,
    regions: values.regions.split(/[\s,，]+/).filter(Boolean),
    days: Number(values.days),
  };
  if (values.password) payload.password = values.password;
  form.elements.password.value = "";
  if (!window.confirm("确定替换 " + payload.email + " 的地域及有效期？")) return;
  showAccount(await api("accounts/grant", "PUT", payload));
  notice("已保存账号授权。");
});
