(() => {
  const CATEGORIES = {
    Food:          { icon: '🍔', color: '--cat-food' },
    Transport:     { icon: '🚌', color: '--cat-transport' },
    Shopping:      { icon: '🛍️', color: '--cat-shopping' },
    Entertainment: { icon: '🎬', color: '--cat-entertainment' },
    Health:        { icon: '💊', color: '--cat-health' },
    Housing:       { icon: '🏠', color: '--cat-housing' },
    Utilities:     { icon: '💡', color: '--cat-utilities' },
    Other:         { icon: '📦', color: '--cat-other' },
  };
  const CUSTOM_CATEGORY_META = { icon: '🏷️', color: '--cat-custom' };
  const ADD_CATEGORY_VALUE = '__add__';

  let customCategories = [];
  let lastCategoryValue = 'Food';

  const MONTH_NAMES = ['January','February','March','April','May','June',
    'July','August','September','October','November','December'];

  const els = {
    loginView: document.getElementById('loginView'),
    loginForm: document.getElementById('loginForm'),
    loginUsername: document.getElementById('loginUsername'),
    loginPassword: document.getElementById('loginPassword'),
    loginError: document.getElementById('loginError'),
    appView: document.getElementById('appView'),
    pageTitle: document.getElementById('pageTitle'),
    currentUser: document.getElementById('currentUser'),
    logoutBtn: document.getElementById('logoutBtn'),

    accountUsername: document.getElementById('accountUsername'),
    changePasswordForm: document.getElementById('changePasswordForm'),
    currentPassword: document.getElementById('currentPassword'),
    newPassword: document.getElementById('newPassword'),
    changePasswordMsg: document.getElementById('changePasswordMsg'),

    prevMonth: document.getElementById('prevMonth'),
    nextMonth: document.getElementById('nextMonth'),
    monthLabel: document.getElementById('monthLabel'),
    totalValue: document.getElementById('totalValue'),
    chartCard: document.getElementById('chartCard'),
    chart: document.getElementById('chart'),
    form: document.getElementById('expenseForm'),
    amount: document.getElementById('amount'),
    description: document.getElementById('description'),
    location: document.getElementById('location'),
    category: document.getElementById('category'),
    date: document.getElementById('date'),
    emptyState: document.getElementById('emptyState'),
    expenseList: document.getElementById('expenseList'),

    trendChart: document.getElementById('trendChart'),
    dowChart: document.getElementById('dowChart'),
    weekdayTotal: document.getElementById('weekdayTotal'),
    weekendTotal: document.getElementById('weekendTotal'),

    budgetList: document.getElementById('budgetList'),

    feedbackForm: document.getElementById('feedbackForm'),
    feedbackKindToggle: document.getElementById('feedbackKindToggle'),
    feedbackText: document.getElementById('feedbackText'),
    feedbackEmptyState: document.getElementById('feedbackEmptyState'),
    feedbackList: document.getElementById('feedbackList'),

    tooltip: document.getElementById('tooltip'),
  };

  let viewDate = new Date();
  viewDate.setDate(1);

  els.date.valueAsDate = new Date();

  // ------------------------------------------------------------- API ----

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    if (res.status === 401 && path !== '/api/login') {
      showLogin();
      throw new Error('Session expired');
    }
    if (!res.ok) {
      let detail = `Request failed (${res.status})`;
      try {
        const body = await res.json();
        if (body.detail) detail = body.detail;
      } catch { /* no body */ }
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  function currency(n) {
    return n.toLocaleString('he-IL', { style: 'currency', currency: 'ILS' });
  }

  function monthKey(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ------------------------------------------------------------ auth ----

  function setCurrentUser(username) {
    els.currentUser.textContent = username;
    els.accountUsername.textContent = username;
  }

  function showLogin() {
    els.loginView.hidden = false;
    els.appView.hidden = true;
    els.loginUsername.focus();
  }

  async function showApp() {
    els.loginView.hidden = true;
    els.appView.hidden = false;
    setActiveTab('home');
    await Promise.all([loadCategories(), loadHome()]);
  }

  els.loginForm.addEventListener('submit', async (evt) => {
    evt.preventDefault();
    els.loginError.hidden = true;
    try {
      const res = await api('/api/login', {
        method: 'POST',
        body: JSON.stringify({ username: els.loginUsername.value, password: els.loginPassword.value }),
      });
      setCurrentUser(res.username);
      els.loginPassword.value = '';
      await showApp();
    } catch (err) {
      els.loginError.textContent = err.message || 'Login failed';
      els.loginError.hidden = false;
    }
  });

  els.logoutBtn.addEventListener('click', async () => {
    try { await api('/api/logout', { method: 'POST' }); } catch { /* ignore */ }
    showLogin();
  });

  els.changePasswordForm.addEventListener('submit', async (evt) => {
    evt.preventDefault();
    els.changePasswordMsg.hidden = true;
    try {
      await api('/api/change-password', {
        method: 'POST',
        body: JSON.stringify({
          current_password: els.currentPassword.value,
          new_password: els.newPassword.value,
        }),
      });
      els.changePasswordForm.reset();
      els.changePasswordMsg.textContent = 'Password changed.';
      els.changePasswordMsg.className = 'change-password-msg success';
      els.changePasswordMsg.hidden = false;
    } catch (err) {
      els.changePasswordMsg.textContent = err.message || 'Could not change password';
      els.changePasswordMsg.className = 'change-password-msg error';
      els.changePasswordMsg.hidden = false;
    }
  });

  // -------------------------------------------------------------- tabs ----

  const TAB_TITLES = { home: 'Home', insights: 'Insights', budgets: 'Budgets', feedback: 'Feedback' };

  function setActiveTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    document.getElementById('homeTab').hidden = tab !== 'home';
    document.getElementById('insightsTab').hidden = tab !== 'insights';
    document.getElementById('budgetsTab').hidden = tab !== 'budgets';
    document.getElementById('feedbackTab').hidden = tab !== 'feedback';
    els.pageTitle.textContent = TAB_TITLES[tab];
  }

  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tab = btn.dataset.tab;
      setActiveTab(tab);
      try {
        if (tab === 'insights') await loadInsights();
        if (tab === 'budgets') await loadBudgets();
        if (tab === 'feedback') await loadFeedback();
      } catch (err) {
        console.error(err);
      }
    });
  });

  // -------------------------------------------------------- tooltip ----

  function showTooltip(evt, text) {
    els.tooltip.textContent = text;
    els.tooltip.hidden = false;
    moveTooltip(evt);
  }

  function moveTooltip(evt) {
    els.tooltip.style.left = `${evt.clientX}px`;
    els.tooltip.style.top = `${evt.clientY}px`;
  }

  function hideTooltip() {
    els.tooltip.hidden = true;
  }

  // -------------------------------------------------------- Home tab ----

  async function loadHome() {
    els.monthLabel.textContent = `${MONTH_NAMES[viewDate.getMonth()]} ${viewDate.getFullYear()}`;
    const monthExpenses = await api(`/api/expenses?month=${monthKey(viewDate)}`);
    const total = monthExpenses.reduce((sum, e) => sum + e.amount, 0);
    els.totalValue.textContent = currency(total);
    renderChart(monthExpenses);
    renderList(monthExpenses);
  }

  function renderChart(monthExpenses) {
    if (monthExpenses.length === 0) {
      els.chartCard.hidden = true;
      els.chart.innerHTML = '';
      return;
    }
    els.chartCard.hidden = false;

    const byCategory = {};
    for (const e of monthExpenses) {
      byCategory[e.category] = (byCategory[e.category] || 0) + e.amount;
    }

    const rows = Object.entries(byCategory).sort((a, b) => b[1] - a[1]);
    const max = rows[0][1];

    els.chart.innerHTML = rows.map(([cat, amt]) => {
      const meta = CATEGORIES[cat] || CUSTOM_CATEGORY_META;
      const pct = Math.round((amt / max) * 100);
      return `
        <div class="chart-row">
          <span class="cat-label">${meta.icon} ${cat}</span>
          <span class="bar-track"><span class="bar-fill" style="width:${pct}%; background:var(${meta.color})"></span></span>
          <span class="cat-amount">${currency(amt)}</span>
        </div>`;
    }).join('');
  }

  function renderList(monthExpenses) {
    if (monthExpenses.length === 0) {
      els.emptyState.hidden = false;
      els.expenseList.innerHTML = '';
      return;
    }
    els.emptyState.hidden = true;

    const byDay = {};
    for (const e of monthExpenses) {
      (byDay[e.date] ||= []).push(e);
    }
    const days = Object.keys(byDay).sort((a, b) => b.localeCompare(a));

    els.expenseList.innerHTML = days.map(day => {
      const items = byDay[day].sort((a, b) => b.id - a.id);
      const dayTotal = items.reduce((sum, e) => sum + e.amount, 0);
      const label = formatDay(day);

      const rows = items.map(e => {
        const meta = CATEGORIES[e.category] || CUSTOM_CATEGORY_META;
        return `
          <div class="expense-row" data-id="${e.id}">
            <span class="cat-dot" style="background:var(${meta.color})"></span>
            <div class="expense-main">
              <div class="expense-desc">${escapeHtml(e.description)}</div>
              <div class="expense-cat">${meta.icon} ${e.category}${e.location ? ` · ${escapeHtml(e.location)}` : ''}</div>
            </div>
            <span class="expense-amount">${currency(e.amount)}</span>
            <button class="delete-btn" data-id="${e.id}" aria-label="Delete expense" type="button">×</button>
          </div>`;
      }).join('');

      return `
        <div class="day-group">
          <div class="day-header"><span>${label}</span><span>${currency(dayTotal)}</span></div>
          ${rows}
        </div>`;
    }).join('');
  }

  function formatDay(isoDate) {
    const [y, m, d] = isoDate.split('-').map(Number);
    const date = new Date(y, m - 1, d);
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    const sameDay = (a, b) => a.toDateString() === b.toDateString();
    if (sameDay(date, today)) return 'Today';
    if (sameDay(date, yesterday)) return 'Yesterday';
    return date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  }

  els.form.addEventListener('submit', async (evt) => {
    evt.preventDefault();
    const amount = parseFloat(els.amount.value);
    if (!amount || amount <= 0) return;

    const payload = {
      amount,
      description: els.description.value.trim() || 'Expense',
      location: els.location.value.trim() || null,
      category: els.category.value,
      date: els.date.value,
    };

    try {
      await api('/api/expenses', { method: 'POST', body: JSON.stringify(payload) });
    } catch (err) {
      alert(err.message);
      return;
    }

    const enteredDate = els.date.value;
    els.form.reset();
    els.date.value = enteredDate;
    lastCategoryValue = els.category.value;

    const [y, m] = enteredDate.split('-').map(Number);
    viewDate = new Date(y, m - 1, 1);

    await loadHome();
    els.amount.focus();
  });

  els.expenseList.addEventListener('click', async (evt) => {
    const btn = evt.target.closest('.delete-btn');
    if (!btn) return;
    const id = Number(btn.dataset.id);
    try {
      await api(`/api/expenses/${id}`, { method: 'DELETE' });
    } catch (err) {
      alert(err.message);
      return;
    }
    await loadHome();
  });

  // ---------------------------------------------------------- categories ----

  async function loadCategories() {
    const res = await api('/api/categories');
    customCategories = res.custom;
    populateCategorySelect(lastCategoryValue);
  }

  function populateCategorySelect(selectValue) {
    const options = [
      ...Object.keys(CATEGORIES).map(cat => `<option value="${cat}">${CATEGORIES[cat].icon} ${cat}</option>`),
      ...customCategories.map(cat => `<option value="${escapeHtml(cat)}">${CUSTOM_CATEGORY_META.icon} ${escapeHtml(cat)}</option>`),
      `<option value="${ADD_CATEGORY_VALUE}">+ Add new category…</option>`,
    ];
    els.category.innerHTML = options.join('');
    const hasValue = [...els.category.options].some(o => o.value === selectValue);
    els.category.value = hasValue ? selectValue : els.category.options[0].value;
    lastCategoryValue = els.category.value;
  }

  els.category.addEventListener('change', async () => {
    if (els.category.value !== ADD_CATEGORY_VALUE) {
      lastCategoryValue = els.category.value;
      return;
    }

    const name = (window.prompt('New category name:') || '').trim();
    if (!name) {
      populateCategorySelect(lastCategoryValue);
      return;
    }

    let created;
    try {
      created = await api('/api/categories', { method: 'POST', body: JSON.stringify({ name }) });
    } catch (err) {
      alert(err.message);
      populateCategorySelect(lastCategoryValue);
      return;
    }

    if (!CATEGORIES[created.name] && !customCategories.includes(created.name)) {
      customCategories.push(created.name);
      customCategories.sort((a, b) => a.localeCompare(b));
    }
    populateCategorySelect(created.name);
  });

  els.prevMonth.addEventListener('click', async () => {
    viewDate.setMonth(viewDate.getMonth() - 1);
    await loadHome();
  });

  els.nextMonth.addEventListener('click', async () => {
    viewDate.setMonth(viewDate.getMonth() + 1);
    await loadHome();
  });

  // ---------------------------------------------------- Insights tab ----

  async function loadInsights() {
    const [trends, patterns] = await Promise.all([
      api('/api/analytics/trends?months=6'),
      api('/api/analytics/patterns?months=3'),
    ]);
    renderTrendChart(trends);
    renderDowChart(patterns.by_day);
    els.weekdayTotal.textContent = currency(patterns.weekday_total);
    els.weekendTotal.textContent = currency(patterns.weekend_total);
  }

  function renderTrendChart(trends) {
    const { months, totals } = trends;
    const W = 320, H = 150, padL = 6, padR = 6, padT = 12, padB = 24;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;
    const max = Math.max(...totals, 1);
    const n = totals.length;

    const x = i => (n === 1 ? padL + plotW / 2 : padL + (i / (n - 1)) * plotW);
    const y = v => padT + plotH - (v / max) * plotH;

    const points = totals.map((v, i) => [x(i), y(v)]);
    const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
    const baseline = padT + plotH;
    const areaPath = `M${points[0][0].toFixed(1)},${baseline.toFixed(1)} ` +
      points.map(p => `L${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ') +
      ` L${points[n - 1][0].toFixed(1)},${baseline.toFixed(1)} Z`;

    const dots = points.map(p => `<circle class="trend-dot" cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3.5"></circle>`).join('');

    const labels = months.map((m, i) => {
      const mo = Number(m.split('-')[1]);
      const label = MONTH_NAMES[mo - 1].slice(0, 3);
      return `<text class="trend-axis-label" x="${x(i).toFixed(1)}" y="${H - 6}" text-anchor="middle">${label}</text>`;
    }).join('');

    const colW = n > 1 ? plotW / n : plotW;
    const hits = points.map((p, i) => {
      const hx = padL + i * colW;
      return `<rect class="trend-hit" data-i="${i}" x="${hx.toFixed(1)}" y="${padT}" width="${colW.toFixed(1)}" height="${plotH}" fill="transparent"></rect>`;
    }).join('');

    els.trendChart.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
        <line class="trend-gridline" x1="${padL}" y1="${baseline}" x2="${W - padR}" y2="${baseline}"></line>
        <path class="trend-area" d="${areaPath}"></path>
        <path class="trend-line" d="${linePath}"></path>
        ${dots}
        ${labels}
        ${hits}
      </svg>`;

    els.trendChart.querySelectorAll('.trend-hit').forEach(hit => {
      const i = Number(hit.dataset.i);
      const mo = Number(months[i].split('-')[1]);
      const yr = months[i].split('-')[0];
      const label = `${MONTH_NAMES[mo - 1]} ${yr} — ${currency(totals[i])}`;
      hit.addEventListener('pointerenter', (e) => showTooltip(e, label));
      hit.addEventListener('pointermove', moveTooltip);
      hit.addEventListener('pointerleave', hideTooltip);
    });
  }

  function renderDowChart(byDay) {
    const W = 320, H = 150, padL = 6, padR = 6, padT = 12, padB = 24;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;
    const max = Math.max(...byDay.map(d => d.total), 1);
    const n = byDay.length;
    const colW = plotW / n;
    const barW = colW * 0.55;
    const baseline = padT + plotH;

    const bars = byDay.map((d, i) => {
      const h = Math.max((d.total / max) * plotH, d.total > 0 ? 2 : 0);
      const bx = padL + i * colW + (colW - barW) / 2;
      const by = baseline - h;
      return `<rect class="dow-bar" data-i="${i}" x="${bx.toFixed(1)}" y="${by.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" rx="3"></rect>`;
    }).join('');

    const labels = byDay.map((d, i) => {
      const lx = padL + i * colW + colW / 2;
      return `<text class="dow-axis-label" x="${lx.toFixed(1)}" y="${H - 6}" text-anchor="middle">${d.day}</text>`;
    }).join('');

    const hits = byDay.map((d, i) => {
      const hx = padL + i * colW;
      return `<rect class="dow-hit" data-i="${i}" x="${hx.toFixed(1)}" y="${padT}" width="${colW.toFixed(1)}" height="${plotH}"></rect>`;
    }).join('');

    els.dowChart.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
        <line class="dow-baseline" x1="${padL}" y1="${baseline}" x2="${W - padR}" y2="${baseline}"></line>
        ${bars}
        ${labels}
        ${hits}
      </svg>`;

    els.dowChart.querySelectorAll('.dow-hit').forEach(hit => {
      const i = Number(hit.dataset.i);
      const label = `${byDay[i].day} — ${currency(byDay[i].total)}`;
      hit.addEventListener('pointerenter', (e) => showTooltip(e, label));
      hit.addEventListener('pointermove', moveTooltip);
      hit.addEventListener('pointerleave', hideTooltip);
    });
  }

  // ----------------------------------------------------- Budgets tab ----

  function currentMonthKey() {
    return monthKey(new Date());
  }

  async function loadBudgets() {
    const month = currentMonthKey();
    const [budgets, status] = await Promise.all([
      api('/api/budgets'),
      api(`/api/analytics/budget-status?month=${month}`),
    ]);
    renderBudgets(budgets, status);
  }

  function renderBudgets(budgets, statusRows) {
    const statusByCategory = Object.fromEntries(statusRows.map(r => [r.category, r]));

    els.budgetList.innerHTML = [...Object.keys(CATEGORIES), ...customCategories].map(cat => {
      const meta = CATEGORIES[cat] || CUSTOM_CATEGORY_META;
      const limit = budgets[cat];
      const hasLimit = limit !== undefined;
      const row = statusByCategory[cat];
      const spent = row ? row.spent : 0;
      const pct = row ? Math.min(row.pct, 100) : 0;
      const status = row ? row.status : 'good';
      const statusText = status === 'critical' ? 'Over budget' : status === 'warning' ? 'Near limit' : 'On track';

      return `
        <div class="budget-row ${hasLimit ? '' : 'no-budget'}">
          <div class="budget-head">
            <span class="budget-cat">${meta.icon} ${cat}</span>
            ${hasLimit
              ? `<span class="budget-amounts">${currency(spent)} <span class="muted">/ ${currency(limit)}</span></span>`
              : `<span class="muted">No limit set</span>`}
          </div>
          ${hasLimit ? `
            <div class="budget-track"><div class="budget-fill ${status}" style="width:${pct}%"></div></div>
            <span class="budget-status-label ${status}">${statusText}</span>
          ` : ''}
          <div class="budget-edit">
            <span class="currency">₪</span>
            <input type="number" min="0" step="1" inputmode="decimal"
                   placeholder="${hasLimit ? limit : 'Set limit'}"
                   data-cat="${cat}" class="budget-input" />
            <button type="button" class="budget-save" data-cat="${cat}">Save</button>
          </div>
        </div>`;
    }).join('');

    els.budgetList.querySelectorAll('.budget-save').forEach(btn => {
      btn.addEventListener('click', async () => {
        const cat = btn.dataset.cat;
        const input = els.budgetList.querySelector(`.budget-input[data-cat="${CSS.escape(cat)}"]`);
        const value = parseFloat(input.value);
        if (!value || value <= 0) return;
        try {
          await api(`/api/budgets/${encodeURIComponent(cat)}`, {
            method: 'PUT',
            body: JSON.stringify({ monthly_limit: value }),
          });
        } catch (err) {
          alert(err.message);
          return;
        }
        await loadBudgets();
      });
    });
  }

  // ---------------------------------------------------- Feedback tab ----

  const FEEDBACK_ICON = { bug: '🐛', feature: '✨' };
  let feedbackKind = 'bug';

  els.feedbackKindToggle.querySelectorAll('.kind-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      feedbackKind = btn.dataset.kind;
      els.feedbackKindToggle.querySelectorAll('.kind-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.kind === feedbackKind);
      });
    });
  });

  async function loadFeedback() {
    const items = await api('/api/feedback');
    renderFeedback(items);
  }

  function renderFeedback(items) {
    if (items.length === 0) {
      els.feedbackEmptyState.hidden = false;
      els.feedbackList.innerHTML = '';
      return;
    }
    els.feedbackEmptyState.hidden = true;

    const open = items.filter(i => i.status === 'open');
    const done = items.filter(i => i.status === 'done');

    const row = (item) => `
      <div class="feedback-row ${item.status === 'done' ? 'done' : ''}" data-id="${item.id}">
        <button class="feedback-check-btn" data-id="${item.id}" aria-label="Toggle resolved" type="button">✓</button>
        <div class="feedback-main">
          <div class="feedback-text">${FEEDBACK_ICON[item.kind]} ${escapeHtml(item.text)}</div>
          <div class="feedback-meta">${item.username ? `${escapeHtml(item.username)} · ` : ''}${formatRelativeTime(item.created_at)}</div>
        </div>
        <button class="feedback-delete-btn" data-id="${item.id}" aria-label="Delete" type="button">×</button>
      </div>`;

    let html = open.map(row).join('');
    if (done.length > 0) {
      html += `<div class="feedback-divider">Resolved</div>` + done.map(row).join('');
    }
    els.feedbackList.innerHTML = html;
  }

  function formatRelativeTime(isoString) {
    const then = new Date(isoString + 'Z');
    const diffMs = Date.now() - then.getTime();
    const minutes = Math.floor(diffMs / 60000);
    if (minutes < 1) return 'Just now';
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 30) return `${days}d ago`;
    return then.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  els.feedbackForm.addEventListener('submit', async (evt) => {
    evt.preventDefault();
    const text = els.feedbackText.value.trim();
    if (!text) return;
    try {
      await api('/api/feedback', { method: 'POST', body: JSON.stringify({ kind: feedbackKind, text }) });
    } catch (err) {
      alert(err.message);
      return;
    }
    els.feedbackForm.reset();
    feedbackKind = 'bug';
    els.feedbackKindToggle.querySelectorAll('.kind-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.kind === 'bug');
    });
    await loadFeedback();
  });

  els.feedbackList.addEventListener('click', async (evt) => {
    const checkBtn = evt.target.closest('.feedback-check-btn');
    const deleteBtn = evt.target.closest('.feedback-delete-btn');

    if (checkBtn) {
      const id = Number(checkBtn.dataset.id);
      const row = checkBtn.closest('.feedback-row');
      const newStatus = row.classList.contains('done') ? 'open' : 'done';
      try {
        await api(`/api/feedback/${id}`, { method: 'PATCH', body: JSON.stringify({ status: newStatus }) });
      } catch (err) {
        alert(err.message);
        return;
      }
      await loadFeedback();
      return;
    }

    if (deleteBtn) {
      const id = Number(deleteBtn.dataset.id);
      try {
        await api(`/api/feedback/${id}`, { method: 'DELETE' });
      } catch (err) {
        alert(err.message);
        return;
      }
      await loadFeedback();
    }
  });

  // -------------------------------------------------------------- init ----

  (async function init() {
    try {
      const res = await api('/api/me');
      setCurrentUser(res.username);
      await showApp();
    } catch {
      showLogin();
    }
  })();
})();
