// test_calendar_ui_logic.js — Unit test cho logic hiển thị và lọc lịch trên Frontend (Chuẩn https://github.com/chinhuy2310/new_argosworks)
const assert = require('assert');

// 1. Kiểm tra chuẩn hóa loại sự kiện (Type Normalization)
function normalizeCompanyType(rawType){
  var t = (rawType || "기타").trim();
  if(t === "오전반차" || t === "오후반차") return "반차";
  if(t === "휴가" || t === "경조사") return "연차";
  return t;
}

assert.strictEqual(normalizeCompanyType("오전반차"), "반차");
assert.strictEqual(normalizeCompanyType("오후반차"), "반차");
assert.strictEqual(normalizeCompanyType("휴가"), "연차");
assert.strictEqual(normalizeCompanyType("경조사"), "연차");
assert.strictEqual(normalizeCompanyType("회의"), "회의");

// 2. Kiểm tra bộ lọc tên thành viên chính xác (Exact Base Name Match — không dính substring)
function isEventVisible(ev, selectedMemberKeys, loggedInUser){
  var myUserKey = loggedInUser.name + "|" + loggedInUser.org;
  var isManagerOrAdmin = loggedInUser.role === "admin" || loggedInUser.role === "manager";

  // Lịch bị từ chối chỉ hiển thị cho người tạo và Manager/Admin
  if(ev.approval_status === "rejected"){
    var isOwner = (ev.ownerKey === myUserKey || ev.ownerName === loggedInUser.name);
    if(!isOwner && !isManagerOrAdmin){
      return false;
    }
  }

  // Khớp chính xác tên thành viên
  var oName = (ev.ownerName || "").trim().toLowerCase();
  var matchMember = false;
  selectedMemberKeys.forEach(function(k){
    var baseName = k.split("|")[0].trim().toLowerCase();
    if(baseName === oName) matchMember = true;
  });
  return matchMember;
}

const userA = { name: "동진위", org: "dev", role: "member" };
const userB = { name: "최성우", org: "dev", role: "member" };
const mgr = { name: "개발팀장", org: "dev", role: "manager" };

const evRejected = { ownerName: "동진위", ownerKey: "동진위|dev", approval_status: "rejected" };

// Đồng nghiệp B không được thấy lịch rejected của A
assert.strictEqual(isEventVisible(evRejected, new Set(["동진위|dev"]), userB), false);

// Chủ sở hữu A và Manager được thấy lịch rejected
assert.strictEqual(isEventVisible(evRejected, new Set(["동진위|dev"]), userA), true);
assert.strictEqual(isEventVisible(evRejected, new Set(["동진위|dev"]), mgr), true);

// Không bị dính substring ("동" không được khớp "동진위")
assert.strictEqual(isEventVisible({ ownerName: "동진위", ownerKey: "동진위|dev" }, new Set(["동|dev"]), userA), false);
assert.strictEqual(isEventVisible({ ownerName: "동진위", ownerKey: "동진위|dev" }, new Set(["동진위|dev"]), userA), true);

// 3. Phân bổ Banner dài ngày LIỀN MẠCH (Continuous Spanning Banner — chuẩn new_argosworks)
function allocateMultiDaySpan(firstCol, lastCol, ev, maxVisibleSlots = 4){
  var spanCols = lastCol - firstCol + 1;
  var slotItems = {};

  // Cột đầu tiên nhận toàn bộ dải thanh kéo dài liền mạch
  slotItems[firstCol] = {
    type: 'event',
    event: ev,
    spanCols: spanCols,
    spanType: spanCols > 1 ? 'range' : 'single',
    widthStyle: spanCols > 1 ? `width: calc(${spanCols * 100}% + ${(spanCols - 1) * 13}px); z-index: 5;` : ''
  };

  // Các cột tiếp theo trong tuần chỉ đặt spacer vô hình để giữ chỗ hàng dọc, không chia nhỏ box
  for(var k = firstCol + 1; k <= lastCol; k++){
    slotItems[k] = {
      type: 'spacer',
      placeholder: true
    };
  }
  return slotItems;
}

const sampleEv = { id: 101, title: "경영전략회의", startDate: "2026-10-12", endDate: "2026-10-16" };
const weekSlots = allocateMultiDaySpan(0, 4, sampleEv);

// Cột 0 (thứ Hai) chứa 1 banner duy nhất vắt qua 5 cột
assert.strictEqual(weekSlots[0].type, 'event');
assert.strictEqual(weekSlots[0].spanCols, 5);
assert.strictEqual(weekSlots[0].spanType, 'range');
assert.strictEqual(weekSlots[0].widthStyle, 'width: calc(500% + 52px); z-index: 5;');

// Các cột 1, 2, 3, 4 (thứ Ba đến thứ Sáu) là spacer giữ chỗ, không tạo thêm ô đứt quãng
for(let dayCol = 1; dayCol <= 4; dayCol++){
  assert.strictEqual(weekSlots[dayCol].type, 'spacer');
  assert.strictEqual(weekSlots[dayCol].placeholder, true);
}

console.log("All Calendar UI Logic tests passed successfully!");
