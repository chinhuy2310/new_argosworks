// test_calendar_render_regression.js
// Hồi quy: render lưới lịch tháng KHÔNG được văng lỗi khi có ô ngày tràn sự kiện (> maxVisibleSlots).
// Trước đây renderCellHtml() dùng biến `isEn` ngoài phạm vi → ReferenceError → schedGrid.innerHTML
// không bao giờ được gán → toàn bộ lịch tháng trống trơn dù API vẫn trả dữ liệu.
// Chạy: node tests/test_calendar_render_regression.js
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.join(__dirname, "..");

// ── 1. DOM stub tối thiểu (đủ để utils.js + calendar.js nạp và render) ──
function makeEl(id) {
  return {
    id: id || "", innerHTML: "", textContent: "", value: "", checked: false,
    hidden: false, disabled: false, style: {}, dataset: {}, children: [],
    classList: {
      _s: new Set(),
      add() { for (const a of arguments) this._s.add(a); },
      remove() { for (const a of arguments) this._s.delete(a); },
      toggle(c, f) { const want = f === undefined ? !this._s.has(c) : !!f; want ? this._s.add(c) : this._s.delete(c); return want; },
      contains(c) { return this._s.has(c); }
    },
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
    hasAttribute() { return false; }, appendChild(c) { this.children.push(c); return c; },
    removeChild() {}, insertBefore(c) { return c; }, addEventListener() {},
    removeEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
    closest() { return null; }, focus() {}, blur() {}, click() {}, scrollIntoView() {},
    contains() { return false; },
    getBoundingClientRect() { return { top: 0, left: 0, width: 100, height: 100, right: 100, bottom: 100 }; },
    offsetWidth: 100, offsetHeight: 24, offsetLeft: 0, offsetTop: 0
  };
}

const elCache = new Map();
const getEl = (id) => {
  if (!elCache.has(id)) elCache.set(id, makeEl(id));
  return elCache.get(id);
};

const doc = {
  getElementById: getEl, querySelector: () => null, querySelectorAll: () => [],
  createElement: (tag) => makeEl(tag), addEventListener: () => {},
  removeEventListener: () => {}, body: makeEl("body"), documentElement: makeEl("html"),
  activeElement: null, cookie: "", readyState: "complete"
};

const mkStorage = () => ({
  _d: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null; },
  setItem(k, v) { this._d[k] = String(v); },
  removeItem(k) { delete this._d[k]; },
  clear() { this._d = {}; }
});

const ctx = {
  console, document: doc, localStorage: mkStorage(), sessionStorage: mkStorage(),
  location: { href: "http://localhost/", origin: "http://localhost", search: "", pathname: "/" },
  navigator: { userAgent: "node-regression", language: "ko" },
  fetch: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) }),
  setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
  requestAnimationFrame: () => 0, alert: () => {}, confirm: () => true, prompt: () => "",
  BroadcastChannel: undefined,
  CustomEvent: class { constructor(t, o) { this.type = t; this.detail = o && o.detail; } },
  Event: class { constructor(t) { this.type = t; } }
};
ctx.window = ctx;
ctx.globalThis = ctx;
ctx.self = ctx;
ctx.addEventListener = () => {};
ctx.removeEventListener = () => {};
ctx.dispatchEvent = () => true;
ctx.matchMedia = () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {} });
ctx.i18n = { getLang: () => "ko", t: (k) => k, setLang: () => {} };
vm.createContext(ctx);

["web/js/utils.js", "web/js/calendar.js"].forEach((rel) => {
  vm.runInContext(fs.readFileSync(path.join(ROOT, rel), "utf8"), ctx, { filename: rel });
});

// ── 2. Fixture: tháng 10/2026, ngày 07/10 có 5 sự kiện (vượt maxVisibleSlots = 3) ──
const owner = { ownerName: "김민수", ownerOrg: "mgmt", ownerKey: "김민수|mgmt" };
const makeEvent = (id, type, title, startDate, endDate) => Object.assign(
  { id, type, title, startDate, endDate, approval_status: "approved" }, owner
);

const EVENTS = [
  makeEvent(1, "반차", "오후 반차", "2026-10-07", "2026-10-07"),
  makeEvent(2, "업무", "업무 카드 A", "2026-10-07", "2026-10-07"),
  makeEvent(3, "업무", "업무 카드 B", "2026-10-07", "2026-10-07"),
  makeEvent(4, "회의", "주간 회의", "2026-10-07", "2026-10-07"),
  makeEvent(5, "재택", "재택 근무", "2026-10-07", "2026-10-07"),
  makeEvent(6, "출장", "출장 vắt nhiều ngày", "2026-10-05", "2026-10-16"),
  makeEvent(7, "연차", "연차 휴가", "2026-10-22", "2026-10-23")
];

const MEMBERS = [
  { key: "김민수|mgmt", name: "김민수", org: "mgmt", email: "" }
];

ctx.EVENTS = EVENTS;
ctx.MEMBERS = MEMBERS;

vm.runInContext(`
  loggedInUser = { name: "김민수", org: "mgmt", role: "admin", isAdmin: 1, token: "test" };
  schedEvents = EVENTS;
  allSchedMembers = MEMBERS;
  myUserKey = "김민수|mgmt";
  selectedMemberKeys = new Set(MEMBERS.map(function(m){ return m.key; }));
  schedViewYear = 2026;
  schedViewMonth = 10;
  schedSelectedDate = "2026-10-07";
  isWeekendVisible = true;
`, ctx);

const run = (expr) => vm.runInContext(expr, ctx);

// ── 3. Assertions ──
// 3.1 Ô ngày có 5 sự kiện phải tạo overflowCount và KHÔNG được ném lỗi.
assert.doesNotThrow(() => run("renderSchedule()"),
  "renderSchedule() phải render được cả khi có ô ngày tràn sự kiện");

const monthHtml = run("schedGrid.innerHTML");
assert.ok(monthHtml.length > 1000, "Lưới tháng phải có nội dung (hiện tại: " + monthHtml.length + " ký tự)");
assert.ok(monthHtml.indexOf('data-date="2026-10-07"') !== -1, "Lưới tháng phải chứa ô ngày 2026-10-07");
assert.ok(monthHtml.indexOf("더보기") !== -1, "Ô ngày tràn sự kiện phải có link '+N개 더보기'");
assert.ok(monthHtml.indexOf("cal-chip") !== -1, "Lưới tháng phải chứa chip sự kiện");

// 3.2 Sự kiện nhiều ngày hiển thị liền mạch qua các cột (span) trong tuần 05~11/10.
assert.strictEqual(run('eventsOnDate("2026-10-10").length'), 1,
  "Sự kiện 05/10~16/10 phải xuất hiện ở ngày 2026-10-10");
assert.strictEqual(run('eventsOnDate("2026-10-12").length'), 1,
  "Sự kiện 05/10~16/10 phải xuất hiện cả ở tuần sau (2026-10-12)");
assert.strictEqual(run('eventsOnDate("2026-10-02").length'), 0,
  "Không có sự kiện nào vào ngày 2026-10-02");

// 3.3 Week view & Agenda view vẫn render bình thường (không hồi quy).
assert.doesNotThrow(() => run("renderWeekView()"), "renderWeekView() không được ném lỗi");
assert.ok(run("schedWeekGrid.innerHTML").indexOf("cal-week-event-card") !== -1,
  "Week view phải chứa card sự kiện");

assert.doesNotThrow(() => run("renderAgendaView()"), "renderAgendaView() không được ném lỗi");
assert.ok(run("schedAgendaList.innerHTML").indexOf("2026-10-07") !== -1,
  "Agenda view phải liệt kê sự kiện ngày 2026-10-07");

// 3.4 Chế độ 5 ngày (ẩn cuối tuần) cũng phải render được.
vm.runInContext("isWeekendVisible = false;", ctx);
assert.doesNotThrow(() => run("renderSchedule()"), "Chế độ 5 ngày (주말 숨김) không được ném lỗi");
assert.ok(run("schedGrid.innerHTML").indexOf('data-date="2026-10-07"') !== -1,
  "Chế độ 5 ngày vẫn phải hiển thị ô ngày 2026-10-07");

// 3.5 Các nhánh render "đặc biệt" (nhiều người tham gia, chờ duyệt, bị từ chối, Jira card)
//     cũng phải render được — đây là code mới thêm nên dễ phát sinh lỗi phạm vi biến.
const EXTRA_EVENTS = EVENTS.concat([
  Object.assign(makeEvent(21, "업무", "Họp nhiều người", "2026-10-28", "2026-10-30"), {
    approval_status: "pending",
    participants: [
      { name: "김민수", org: "mgmt", key: "김민수|mgmt", isOwner: true },
      { name: "박서준", org: "dev", key: "박서준|dev" },
      { name: "최유진", org: "dev", key: "최유진|dev" }
    ]
  }),
  Object.assign(makeEvent(22, "연차", "연차 bị từ chối", "2026-10-29", "2026-10-29"), {
    approval_status: "rejected",
    reject_reason: "인원 부족"
  }),
  Object.assign(makeEvent(23, "업무", "SCRUM-42", "2026-10-30", "2026-10-30"), {
    source: "jira",
    cardCode: "SCRUM-42",
    jira: { key: "SCRUM-42" }
  })
]);

ctx.EXTRA_EVENTS = EXTRA_EVENTS;
vm.runInContext("schedEvents = EXTRA_EVENTS; isWeekendVisible = true;", ctx);

assert.doesNotThrow(() => run("renderSchedule()"),
  "Lưới tháng phải render được với sự kiện nhiều người tham gia / pending / rejected / Jira");

const richHtml = run("schedGrid.innerHTML");
assert.ok(richHtml.indexOf('data-date="2026-10-28"') !== -1,
  "Lưới tháng phải hiển thị ô ngày 2026-10-28 (sự kiện nhiều người tham gia)");
assert.ok(richHtml.indexOf("cal-multiparts-wrap") !== -1,
  "Sự kiện nhiều người tham gia phải render nhãn người tham gia");
assert.ok(richHtml.indexOf("반려") !== -1,
  "Sự kiện bị từ chối phải có badge '반려'");
assert.ok(richHtml.indexOf("대기") !== -1,
  "Sự kiện chờ duyệt phải có badge '대기'");
assert.ok(richHtml.indexOf("SCRUM-42") !== -1,
  "Sự kiện Jira phải hiển thị mã issue");

assert.doesNotThrow(() => run("renderWeekView()"),
  "Week view phải render được với sự kiện nhiều người tham gia / Jira");
assert.doesNotThrow(() => run("renderAgendaView()"),
  "Agenda view phải render được với sự kiện nhiều người tham gia / pending / rejected");

// 3.6 Bộ lọc thanh bên (Sidebar Filters & Member List) không được văng lỗi
vm.runInContext(`
  allSchedMembers = [
    { name: "김민수", org: "mgmt", key: "김민수|mgmt" },
    { name: "박서준", org: "dev", key: "박서준|dev" }
  ];
  selectedMemberKeys = new Set(["김민수|mgmt", "박서준|dev"]);
  myUserKey = "김민수|mgmt";
`, ctx);

assert.doesNotThrow(() => run("updateAllCalendarFilters()"),
  "updateAllCalendarFilters() không được ném lỗi (renderMembersList / updateQuickFilterUi phải tồn tại)");

const membersHtml = run("schedMembersList.innerHTML");
assert.ok(membersHtml.indexOf("김민수") !== -1, "Danh sách thành viên phải chứa 김민수");
assert.ok(membersHtml.indexOf("박서준") !== -1, "Danh sách thành viên phải chứa 박서준");

console.log("All Calendar render regression tests passed successfully!");

