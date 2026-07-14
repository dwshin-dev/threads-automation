// Threads Auto Pro 프론트엔드 애플리케이션 로직

let appConfig = { accounts: [] };
let activeTab = 'settings';
let eventSource = null;

document.addEventListener("DOMContentLoaded", () => {
    // 최초 데이터 로드
    loadSettings();
    loadAccounts();
    loadQueue();
    connectLogsSSE();
    
    // 1.5초 주기로 자동화 실행 상태 체크 및 대기열 동기화
    setInterval(checkAutomationStatus, 1500);
});

// 탭 전환 로직 (가로형 헤더 탭 적용)
function switchTab(tabName) {
    activeTab = tabName;
    
    // 탭 버튼 스타일 제어
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.classList.remove("active");
    });
    
    const clickedBtn = Array.from(document.querySelectorAll(".tab-btn")).find(btn => btn.innerText.includes(
        tabName === 'settings' ? '설정' : tabName === 'datainput' ? '데이터' : '대시보드'
    ));
    if (clickedBtn) clickedBtn.classList.add("active");
    
    // 콘텐츠 패널 노출 제어
    document.querySelectorAll(".tab-pane").forEach(pane => {
        pane.classList.remove("active");
    });
    document.getElementById(`${tabName}-tab`).classList.add("active");
    
    // 탭 전환 시 신선한 데이터를 반영
    if (tabName === 'datainput') {
        loadAccounts().then(() => {
            loadQueue(); // 계정 목록이 갱신된 후 대기열의 드롭다운을 렌더링
        });
    } else if (tabName === 'dashboard') {
        loadQueueSummary();
    }
}

// 1. 설정 저장 및 불러오기
async function loadSettings() {
    try {
        const response = await fetch("/api/config");
        const data = await response.json();
        appConfig = data;
        
        document.getElementById("headless-mode").checked = data.headless;
        document.getElementById("publish-delay").value = data.publish_delay || 10;
        document.getElementById("openai-key").value = data.openai_api_key || "";
        document.getElementById("gemini-key").value = data.gemini_api_key || "";
        document.getElementById("system-prompt").value = data.system_prompt || "";
    } catch (e) {
        console.error("설정 로드 실패:", e);
    }
}

async function saveSettings(silent = false) {
    const headless = document.getElementById("headless-mode").checked;
    const publish_delay = parseInt(document.getElementById("publish-delay").value) || 10;
    const openai = document.getElementById("openai-key").value.trim();
    const gemini = document.getElementById("gemini-key").value.trim();
    const prompt = document.getElementById("system-prompt").value;
    
    try {
        const response = await fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                headless: headless,
                publish_delay: publish_delay,
                openai_api_key: openai,
                gemini_api_key: gemini,
                system_prompt: prompt
            })
        });
        const result = await response.json();
        if (result.status === "success" && !silent) {
            alert("설정이 저장되었습니다.");
        }
    } catch (e) {
        if (!silent) {
            alert("설정 저장 오류 발생.");
        }
    }
}

// 2. 계정 관리
async function loadAccounts() {
    try {
        const response = await fetch("/api/accounts");
        const accounts = await response.json();
        appConfig.accounts = accounts;
        
        const tbody = document.querySelector("#accounts-table tbody");
        tbody.innerHTML = "";
        
        accounts.forEach(acc => {
            const tr = document.createElement("tr");
            const actualText = acc.actual_username ? `<span class="actual-username" style="font-size: 13px; color: #8e8e8e; margin-left: 6px; font-weight: normal;">(@${acc.actual_username})</span>` : '';
            tr.innerHTML = `
                <td><strong>${acc.username}</strong> ${actualText}</td>
                <td>
                    <span class="badge-tag ${acc.status === '로그인 완료' ? 'green' : 'gray'}">
                        ${acc.status}
                    </span>
                </td>
                <td>
                    <button class="btn btn-blue-outline btn-mini" onclick="loginAccount('${acc.username}')">로그인</button>
                    <button class="btn-icon-only" onclick="renameAccount('${acc.username}')" title="닉네임 변경">✏️</button>
                    <button class="btn-icon-only" onclick="deleteAccount('${acc.username}')" title="삭제">🗑️</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("계정 목록 로드 실패:", e);
    }
}

async function addAccount() {
    const input = document.getElementById("new-account-name");
    const username = input.value.trim();
    if (!username) return;
    
    try {
        const response = await fetch("/api/accounts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: username })
        });
        const result = await response.json();
        if (result.status === "success") {
            input.value = "";
            loadAccounts();
        } else {
            alert(result.message);
        }
    } catch (e) {
        alert("계정 추가 중 오류 발생.");
    }
}

async function deleteAccount(username) {
    if (!confirm(`'${username}' 계정을 정말 삭제하시겠습니까? 관련 세션 데이터도 모두 삭제됩니다.`)) return;
    
    try {
        const response = await fetch(`/api/accounts?username=${encodeURIComponent(username)}`, {
            method: "DELETE"
        });
        const result = await response.json();
        if (result.status === "success") {
            loadAccounts();
        }
    } catch (e) {
        alert("계정 삭제 중 오류 발생.");
    }
}

async function renameAccount(oldUsername) {
    const newUsername = prompt("새로운 닉네임(ID)을 입력하세요:", oldUsername);
    if (!newUsername) return;
    const cleanNew = newUsername.trim();
    if (!cleanNew || cleanNew === oldUsername) return;
    
    try {
        const response = await fetch("/api/accounts/rename", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ old_username: oldUsername, new_username: cleanNew })
        });
        const result = await response.json();
        if (result.status === "success") {
            alert("계정 닉네임이 성공적으로 변경되었습니다.");
            await loadAccounts();
            
            // 데이터 입력 테이블에 매핑된 선택값들도 변경
            const trs = document.querySelectorAll("#data-input-table tbody tr");
            trs.forEach(tr => {
                const select = tr.querySelector(".col-account");
                if (select) {
                    for (let opt of select.options) {
                        if (opt.value === oldUsername) {
                            opt.value = cleanNew;
                            opt.textContent = cleanNew;
                        }
                    }
                    if (select.value === oldUsername) {
                        select.value = cleanNew;
                    }
                }
            });
        } else {
            alert(result.message || "계정 닉네임 변경에 실패했습니다.");
        }
    } catch (e) {
        alert("에러가 발생했습니다: " + e.message);
    }
}

async function loginAccount(username) {
    try {
        const response = await fetch("/api/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: username })
        });
        const result = await response.json();
        if (result.status === "success") {
            alert("스레드 로그인 크롬 창이 실행되었습니다. 로그인을 마치면 창을 닫아주세요.");
        }
    } catch (e) {
        alert("로그인 창 구동 실패.");
    }
}

// 3. 데이터 입력 그리드 테이블
async function loadQueue() {
    try {
        const response = await fetch("/api/queue");
        const queueList = await response.json();
        renderQueueTable(queueList);
    } catch (e) {
        console.error("대기열 로드 실패:", e);
    }
}

function renderQueueTable(queueList) {
    const tbody = document.querySelector("#data-input-table tbody");
    tbody.innerHTML = "";
    
    if (queueList.length === 0) {
        // 기본 빈 행 추가
        addNewRow();
        return;
    }
    
    queueList.forEach((row, index) => {
        tbody.appendChild(createRowElement(row, index));
    });
}

function createRowElement(data = {}, index = 0) {
    const tr = document.createElement("tr");
    tr.dataset.index = index;
    
    // 계정 목록 옵션 생성
    const accountOptions = appConfig.accounts.map(acc => 
        `<option value="${acc.username}">${acc.username}</option>`
    ).join("");
    
    tr.innerHTML = `
        <td class="row-index-cell">${index + 1}</td>
        <td>
            <div style="position: relative; display: flex; align-items: stretch; height: 100%;">
                <textarea class="col-content" placeholder="본문 문구" style="flex: 1; padding-right: 30px; box-sizing: border-box;"></textarea>
                <button class="btn-reroll" onclick="rerollRow(this)" title="AI 변환 (리롤)" style="position: absolute; right: 6px; bottom: 6px; border: 1px solid #D1D5DB; background: #FFFFFF; cursor: pointer; border-radius: 50%; width: 24px; height: 24px; padding: 0; display: flex; align-items: center; justify-content: center; font-size: 12px; z-index: 10; box-shadow: 0 1px 2px rgba(0,0,0,0.1);">🔄</button>
            </div>
        </td>
        <td><textarea class="col-comment" placeholder="댓글 내용(쿠팡 링크 등)"></textarea></td>
        <td><input type="text" class="col-file" placeholder="C:\\\\img1.jpg, C:\\\\img2.mp4"></td>
        <td><input type="text" class="col-tag" placeholder="#tags"></td>
        <td><input type="text" class="col-topic" placeholder="주제명"></td>
        <td><input type="text" class="col-time" placeholder="09:00" style="text-align: center;"></td>
        <td>
            <select class="col-lang">
                <option value="KO">Korean</option>
                <option value="EN">English</option>
                <option value="JA">Japanese</option>
            </select>
        </td>
        <td>
            <select class="col-ai">
                <option value="OFF">OFF</option>
                <option value="GPT">GPT</option>
                <option value="Gemini">Gemini</option>
            </select>
        </td>
        <td>
            <select class="col-account">
                <option value="">--선택--</option>
                ${accountOptions}
            </select>
        </td>
        <td style="text-align: center;">
            <button class="btn-icon-only" onclick="deleteRowElement(this)" title="행 삭제">❌</button>
        </td>
    `;
    
    // HTML 깨짐 방지를 위해 안전하게 값 대입
    tr.querySelector(".col-content").value = data.content || '';
    tr.querySelector(".col-comment").value = data.comment || '';
    tr.querySelector(".col-file").value = data.file || '';
    tr.querySelector(".col-tag").value = data.tag || '';
    tr.querySelector(".col-topic").value = data.topic || '';
    tr.querySelector(".col-time").value = data.time || '';
    
    const langSelect = tr.querySelector(".col-lang");
    if (data.lang === 'KO' || data.lang === 'Korean') langSelect.value = 'KO';
    else if (data.lang === 'EN' || data.lang === 'English') langSelect.value = 'EN';
    else if (data.lang === 'JA' || data.lang === 'Japanese') langSelect.value = 'JA';
    else langSelect.value = data.lang || 'KO';
    
    const aiSelect = tr.querySelector(".col-ai");
    if (data.ai === 'OFF' || data.ai === 'Free') aiSelect.value = 'OFF';
    else if (data.ai === 'GPT') aiSelect.value = 'GPT';
    else if (data.ai === 'Gemini') aiSelect.value = 'Gemini';
    else aiSelect.value = data.ai || 'OFF';
    
    const accSelect = tr.querySelector(".col-account");
    if (data.account) accSelect.value = data.account;
    
    return tr;
}

function addNewRow() {
    const tbody = document.querySelector("#data-input-table tbody");
    const nextIdx = tbody.children.length;
    tbody.appendChild(createRowElement({}, nextIdx));
}

function deleteRowElement(btn) {
    const tr = btn.closest("tr");
    tr.remove();
    // 다시 인덱스 보정
    reindexTable();
}

function reindexTable() {
    document.querySelectorAll("#data-input-table tbody tr").forEach((tr, index) => {
        tr.dataset.index = index;
        const indexCell = tr.querySelector(".row-index-cell");
        if (indexCell) {
            indexCell.innerText = index + 1;
        }
    });
}

function getTableData() {
    const rows = document.querySelectorAll("#data-input-table tbody tr");
    const queueData = [];
    
    rows.forEach(tr => {
        const content = tr.querySelector(".col-content") ? tr.querySelector(".col-content").value : '';
        const comment = tr.querySelector(".col-comment") ? tr.querySelector(".col-comment").value : '';
        const file = tr.querySelector(".col-file") ? tr.querySelector(".col-file").value.trim() : '';
        const tag = tr.querySelector(".col-tag") ? tr.querySelector(".col-tag").value.trim() : '';
        const topic = tr.querySelector(".col-topic") ? tr.querySelector(".col-topic").value.trim() : '';
        const time = tr.querySelector(".col-time") ? tr.querySelector(".col-time").value.trim() : '';
        const lang = tr.querySelector(".col-lang") ? tr.querySelector(".col-lang").value : 'KO';
        const ai = tr.querySelector(".col-ai") ? tr.querySelector(".col-ai").value : 'OFF';
        const account = tr.querySelector(".col-account") ? tr.querySelector(".col-account").value : '';
        
        if (content || comment || file || tag || topic || time || account) {
            queueData.push({
                content,
                comment,
                file,
                tag,
                topic,
                time,
                lang,
                ai,
                account,
                status: 'Pending'
            });
        }
    });
    return queueData;
}

function sortByTime() {
    const data = getTableData();
    if (data.length === 0) return;
    
    data.sort((a, b) => {
        if (!a.time) return 1;
        if (!b.time) return -1;
        return a.time.localeCompare(b.time);
    });
    
    renderQueueTable(data);
}

function groupByAccount() {
    const data = getTableData();
    if (data.length === 0) return;
    
    const groups = {};
    data.forEach(item => {
        const acc = item.account || 'zz_empty';
        if (!groups[acc]) {
            groups[acc] = [];
        }
        groups[acc].push(item);
    });
    
    const sortedAccounts = Object.keys(groups).sort((a, b) => {
        if (a === 'zz_empty') return 1;
        if (b === 'zz_empty') return -1;
        return a.localeCompare(b);
    });
    
    const result = [];
    sortedAccounts.forEach(acc => {
        result.push(...groups[acc]);
    });
    
    renderQueueTable(result);
}

function interleaveAccounts() {
    const data = getTableData();
    if (data.length === 0) return;
    
    const groups = {};
    const accountsList = [];
    
    data.forEach(item => {
        const acc = item.account || 'zz_empty';
        if (!groups[acc]) {
            groups[acc] = [];
            accountsList.push(acc);
        }
        groups[acc].push(item);
    });
    
    accountsList.sort((a, b) => {
        if (a === 'zz_empty') return 1;
        if (b === 'zz_empty') return -1;
        return a.localeCompare(b);
    });
    
    const result = [];
    let hasMore = true;
    let index = 0;
    
    while (hasMore) {
        hasMore = false;
        accountsList.forEach(acc => {
            if (groups[acc][index]) {
                result.push(groups[acc][index]);
                hasMore = true;
            }
        });
        index++;
    }
    
    renderQueueTable(result);
}

async function rerollRow(btn) {
    const tr = btn.closest("tr");
    const textarea = tr.querySelector(".col-content");
    const aiSelect = tr.querySelector(".col-ai");
    const content = textarea.value.trim();
    const ai = aiSelect ? aiSelect.value : "OFF";
    
    if (!content) {
        alert("변환할 본문 내용이 없습니다.");
        return;
    }
    
    if (ai === "OFF" || ai === "Free") {
        alert("이 행의 AI 설정을 GPT 또는 Gemini로 선택한 뒤 리롤을 눌러주세요.");
        return;
    }
    
    btn.classList.add("loading");
    btn.innerText = "⏳";
    
    try {
        const response = await fetch("/api/ai/rewrite", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: content, ai: ai })
        });
        const result = await response.json();
        if (result.status === "success") {
            textarea.value = result.rewritten;
            aiSelect.value = "OFF";
            appendClientLog(`[AI] 본문 리롤 변환 성공 (${ai}) - 중복 변환 방지를 위해 AI 설정을 OFF로 전환했습니다.`);
        } else {
            alert(result.message || "AI 변환에 실패했습니다.");
        }
    } catch (e) {
        alert("오류가 발생했습니다: " + e.message);
    } finally {
        btn.classList.remove("loading");
        btn.innerText = "🔄";
    }
}

async function bulkAiRewrite() {
    const rows = document.querySelectorAll("#data-input-table tbody tr");
    let targetRows = [];
    
    rows.forEach(tr => {
        const textarea = tr.querySelector(".col-content");
        const aiSelect = tr.querySelector(".col-ai");
        const content = textarea ? textarea.value.trim() : "";
        const ai = aiSelect ? aiSelect.value : "OFF";
        
        if (content && (ai === "GPT" || ai === "Gemini")) {
            targetRows.push({
                tr: tr,
                btn: tr.querySelector(".btn-reroll"),
                content: content,
                ai: ai,
                textarea: textarea,
                aiSelect: aiSelect
            });
        }
    });
    
    if (targetRows.length === 0) {
        alert("변환 대상이 없습니다. (본문 내용이 존재하고 AI 옵션이 GPT 또는 Gemini로 선택된 행이 있어야 합니다.)");
        return;
    }
    
    if (!confirm(`총 ${targetRows.length}개의 행에 대해 AI 변환(리롤)을 한 번에 실행하시겠습니까?`)) {
        return;
    }
    
    appendClientLog(`[System] 전체 AI 변환 시작 (총 ${targetRows.length}개 대상)...`);
    
    for (let i = 0; i < targetRows.length; i++) {
        const item = targetRows[i];
        if (item.btn) {
            item.btn.classList.add("loading");
            item.btn.innerText = "⏳";
        }
        
        try {
            const response = await fetch("/api/ai/rewrite", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content: item.content, ai: item.ai })
            });
            const result = await response.json();
            if (result.status === "success") {
                item.textarea.value = result.rewritten;
                item.aiSelect.value = "OFF";
                appendClientLog(`[AI] [${i+1}/${targetRows.length}] 행 변환 완료 - AI 설정을 OFF로 전환했습니다.`);
            } else {
                appendClientLog(`[AI] [${i+1}/${targetRows.length}] 행 변환 실패: ${result.message}`);
            }
        } catch (e) {
            appendClientLog(`[AI] [${i+1}/${targetRows.length}] 에러 발생: ${e.message}`);
        } finally {
            if (item.btn) {
                item.btn.classList.remove("loading");
                item.btn.innerText = "🔄";
            }
        }
        await new Promise(r => setTimeout(r, 400));
    }
    appendClientLog(`[System] 전체 AI 변환 처리가 완료되었습니다.`);
    alert("전체 AI 변환 처리가 완료되었습니다.");
}

function appendClientLog(msg) {
    const consoleBox = document.getElementById("sys-logs-console");
    if (consoleBox) {
        const now = new Date();
        const timeStr = `[${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}]`;
        consoleBox.value += `${timeStr} ${msg}\n`;
        consoleBox.scrollTop = consoleBox.scrollHeight;
    }
}

// 시작 시간과 대기 간격 기준 일괄 예약 시간 적용
function applyTimeInterval() {
    const startTimeVal = document.getElementById("start-time").value; // "09:00"
    const intervalVal = parseInt(document.getElementById("time-interval").value, 10);
    
    if (!startTimeVal || isNaN(intervalVal) || intervalVal <= 0) {
        alert("시작 시간과 올바른 분 간격을 입력해 주세요.");
        return;
    }
    
    const rows = document.querySelectorAll("#data-input-table tbody tr");
    if (rows.length === 0) return;
    
    let [hours, minutes] = startTimeVal.split(":").map(Number);
    let currentDate = new Date();
    currentDate.setHours(hours, minutes, 0, 0);
    
    rows.forEach((tr, index) => {
        if (index > 0) {
            currentDate.setMinutes(currentDate.getMinutes() + intervalVal);
        }
        
        const h = String(currentDate.getHours()).padStart(2, '0');
        const m = String(currentDate.getMinutes()).padStart(2, '0');
        
        const timeInput = tr.querySelector(".col-time");
        if (timeInput) {
            timeInput.value = `${h}:${m}`;
        }
    });
    
    console.log("시간 일괄 적용 완료.");
}

// 4. 새로운 맞춤 제어 액션들 (초기화, 템플릿, 예약 실행)

// 초기화 기능
function clearTable() {
    if (!confirm("정말로 모든 입력 행을 삭제하시겠습니까?")) return;
    const tbody = document.querySelector("#data-input-table tbody");
    tbody.innerHTML = "";
    addNewRow();
}

// 템플릿 파일 다운로드 기능
function downloadTemplate() {
    const csvContent = "\uFEFF내용 (Content) *,댓글 (Comment),파일경로 (File),태그 (Tag),주제 (Topic),시간 (Time),언어,AI (GPT/Gemini/Free),계정 (ID) *\n본문 내용입니다,첫번째 댓글내용,/absolute/path/to/image.jpg,#태그1,인테리어,09:00,KO,OFF,my_account_id\n";
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.setAttribute("href", url);
    link.setAttribute("download", "threads_template.csv");
    link.style.visibility = "hidden";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// 예약 정보 저장 및 즉시 실행 연쇄 기동
async function saveAndStartAutomation() {
    // 자동화 실행 시작 전 현재 설정 폼 자동 무점검 무경고 저장
    await saveSettings(true);
    
    const rows = document.querySelectorAll("#data-input-table tbody tr");
    const queueData = [];
    
    let hasInvalidRow = false;
    
    rows.forEach(tr => {
        const content = tr.querySelector(".col-content").value.trim();
        const comment = tr.querySelector(".col-comment").value.trim();
        const file = tr.querySelector(".col-file").value.trim();
        const tag = tr.querySelector(".col-tag").value.trim();
        const topic = tr.querySelector(".col-topic").value.trim();
        const time = tr.querySelector(".col-time").value.trim();
        const lang = tr.querySelector(".col-lang").value;
        const ai = tr.querySelector(".col-ai").value;
        const account = tr.querySelector(".col-account").value;
        
        // 필수인 내용이 작성된 행만 유효성 체크 및 저장
        if (content) {
            // 시간 양식 확인 (HH:MM)
            const timeRegex = /^([0-9]|0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$/;
            if (!timeRegex.test(time)) {
                alert(`시간 형식이 잘못되었습니다: ${time} (예: 09:00)`);
                hasInvalidRow = true;
                return;
            }
            
            if (!account) {
                alert("내용이 작성된 행에는 로그인 세션이 확보된 스레드 '계정 (ID) *'를 선택해야 합니다.");
                hasInvalidRow = true;
                return;
            }
            
            queueData.push({
                content,
                comment,
                file,
                tag,
                topic,
                time,
                lang,
                ai,
                account,
                status: 'Pending'
            });
        }
    });
    
    if (hasInvalidRow) return;
    
    if (queueData.length === 0) {
        alert("예약 실행할 데이터를 최소 1행 이상 입력해 주세요 (내용 필수 입력).");
        return;
    }
    
    try {
        // 1단계: 대기열 저장
        const saveRes = await fetch("/api/queue", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(queueData)
        });
        const saveResult = await saveRes.json();
        
        if (saveResult.status === "success") {
            // 2단계: 자동화 기동
            const startRes = await fetch("/api/start", { method: "POST" });
            const startResult = await startRes.json();
            
            if (startResult.status === "success" || startResult.message.includes("이미")) {
                alert("예약 대기열이 업데이트되었으며 스케줄러 자동화가 시작되었습니다!");
                // 대시보드로 전환하여 실시간 모니터링 수동 제공
                switchTab('dashboard');
            } else {
                alert("대기열은 저장되었으나 자동화 스케줄러를 시작하지 못했습니다: " + startResult.message);
            }
        } else {
            alert("예약 대기열 반영에 실패했습니다.");
        }
    } catch (e) {
        alert("예약 반영 중 네트워크 에러 발생: " + e.message);
    }
}

// 기존 예비 저장용 API (버튼 연동 없지만 내부 호환성 제공)
async function saveQueueData() {
    const rows = document.querySelectorAll("#data-input-table tbody tr");
    const queueData = [];
    
    rows.forEach(tr => {
        const content = tr.querySelector(".col-content").value.trim();
        const comment = tr.querySelector(".col-comment").value.trim();
        const file = tr.querySelector(".col-file").value.trim();
        const tag = tr.querySelector(".col-tag").value.trim();
        const topic = tr.querySelector(".col-topic").value.trim();
        const time = tr.querySelector(".col-time").value.trim();
        const lang = tr.querySelector(".col-lang").value;
        const ai = tr.querySelector(".col-ai").value;
        const account = tr.querySelector(".col-account").value;
        
        if (content) {
            queueData.push({
                content,
                comment,
                file,
                tag,
                topic,
                time,
                lang,
                ai,
                account,
                status: 'Pending'
            });
        }
    });
    
    try {
        const response = await fetch("/api/queue", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(queueData)
        });
        const result = await response.json();
        if (result.status === "success") {
            alert("예약 정보가 백엔드에 반영되었습니다.");
        }
    } catch (e) {
        alert("예약 저장 도중 에러가 발생했습니다.");
    }
}

// 구글 시트 또는 엑셀 CSV 불러오기 및 파싱
function loadCsvFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const formData = new FormData();
    formData.append("file", file);
    
    appendClientLog(`[System] 파일 업로드 및 파싱 시작: ${file.name}...`);
    
    fetch("/api/upload_file", {
        method: "POST",
        body: formData
    })
    .then(res => res.json())
    .then(result => {
        if (result.status === "success") {
            renderQueueTable(result.rows);
            appendClientLog(`[System] 파일 파싱 완료 (${result.rows.length}행 로드됨)`);
        } else {
            alert(result.message || "파일 파싱 실패");
            appendClientLog(`[System Error] 파일 파싱 실패: ${result.message}`);
        }
    })
    .catch(e => {
        alert("파일 전송 오류: " + e.message);
        appendClientLog(`[System Error] 파일 전송 오류: ${e.message}`);
    });
}

// 5. 대시보드 및 실시간 로그 스트리밍 (SSE)
function connectLogsSSE() {
    if (eventSource) {
        eventSource.close();
    }
    
    eventSource = new EventSource("/api/logs");
    const consoleBox = document.getElementById("sys-logs-console");
    
    eventSource.onmessage = function(event) {
        const msg = event.data;
        const logLine = document.createElement("div");
        logLine.className = "log-line";
        
        // 특정 상태별 로그 글자 컬러 처리
        if (msg.includes("[Success]")) {
            logLine.style.color = "#10B981"; // 초록
        } else if (msg.includes("[Fail]") || msg.includes("[Error]") || msg.includes("오류:")) {
            logLine.style.color = "#EF4444"; // 빨강
        } else if (msg.includes("[System]")) {
            logLine.style.color = "#2563EB"; // 파랑
        }
        
        logLine.innerText = msg;
        consoleBox.appendChild(logLine);
        consoleBox.scrollTop = consoleBox.scrollHeight;
    };
    
    eventSource.onerror = function() {
        console.warn("SSE 연결 해제됨. 5초 뒤 재연동합니다.");
        eventSource.close();
        setTimeout(connectLogsSSE, 5000);
    };
}

async function startAutomation() {
    try {
        const response = await fetch("/api/start", { method: "POST" });
        const result = await response.json();
        if (result.status === "success") {
            document.getElementById("main-start-btn").disabled = true;
            document.getElementById("main-stop-btn").disabled = false;
            updateStatusIndicator(true, "자동화 작동 중");
        }
    } catch (e) {
        alert("자동화 시작 실패.");
    }
}

async function stopAutomation() {
    try {
        const response = await fetch("/api/stop", { method: "POST" });
        const result = await response.json();
        if (result.status === "success") {
            document.getElementById("main-start-btn").disabled = false;
            document.getElementById("main-stop-btn").disabled = true;
            updateStatusIndicator(false, "정지됨");
        }
    } catch (e) {
        alert("자동화 중지 실패.");
    }
}

async function checkAutomationStatus() {
    try {
        const response = await fetch("/api/status");
        const status = await response.json();
        
        const startBtn = document.getElementById("main-start-btn");
        const stopBtn = document.getElementById("main-stop-btn");
        
        if (status.is_running) {
            startBtn.disabled = true;
            stopBtn.disabled = false;
            updateStatusIndicator(true, "작동 중");
        } else {
            startBtn.disabled = false;
            stopBtn.disabled = true;
            updateStatusIndicator(false, "Idle");
        }
        
        // 주기적으로 대시보드 탭에 있을 때만 대기열 현황 업데이트
        if (activeTab === 'dashboard') {
            loadQueueSummary();
        }
    } catch (e) {
        console.error("상태 모니터링 연동 오류:", e);
    }
}

function updateStatusIndicator(active, text) {
    const dot = document.getElementById("status-dot");
    const textLabel = document.getElementById("status-text");
    
    if (active) {
        dot.classList.add("active");
        dot.style.background = "#10B981";
        dot.style.boxShadow = "0 0 6px #10B981";
    } else {
        dot.classList.remove("active");
        dot.style.background = "#94A3B8";
        dot.style.boxShadow = "none";
    }
    textLabel.innerText = text;
}

// 대시보드 작업 대기열 요약 렌더링
async function loadQueueSummary() {
    try {
        const response = await fetch("/api/queue");
        const queueList = await response.json();
        
        const tbody = document.querySelector("#queue-status-table tbody");
        tbody.innerHTML = "";
        
        if (queueList.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-secondary);">예약된 작업이 없습니다.</td></tr>`;
            return;
        }
        
        queueList.forEach(row => {
            const tr = document.createElement("tr");
            
            let statusBadge = "";
            if (row.status === 'Pending') statusBadge = `<span class="badge badge-pending">대기</span>`;
            else if (row.status === 'Running') statusBadge = `<span class="badge badge-running">진행중</span>`;
            else if (row.status === 'Success') statusBadge = `<span class="badge badge-success">성공</span>`;
            else if (row.status === 'Fail') statusBadge = `<span class="badge badge-fail">실패</span>`;
            
            const contentSummary = row.content.length > 25 ? row.content.substring(0, 25) + "..." : row.content;
            
            tr.innerHTML = `
                <td><strong>${row.account || '미지정'}</strong></td>
                <td><span style="font-family: monospace;">${row.time}</span></td>
                <td>${contentSummary}</td>
                <td>${statusBadge}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("대시보드 대기열 로드 실패:", e);
    }
}
