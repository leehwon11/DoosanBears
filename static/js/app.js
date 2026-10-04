/* 공통 유틸 */

// AI 응답 등 외부 텍스트를 innerHTML에 넣을 때 반드시 사용
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function fmtDate(d) {
  return d && d.length >= 8 ? d.slice(0, 4) + '.' + d.slice(4, 6) + '.' + d.slice(6, 8) : '';
}

function resultClass(r) {
  return r === '승' ? 'win' : r === '패' ? 'lose' : 'draw';
}

/* 세그먼트 탭: <div class="seg" data-tabs="group"> <button data-tab="name"> ↔ #group-name.tab-panel */
function initTabs(root = document) {
  root.querySelectorAll('.seg[data-tabs]').forEach(seg => {
    const group = seg.dataset.tabs;
    seg.querySelectorAll('button[data-tab]').forEach(btn => {
      btn.setAttribute('role', 'tab');
      btn.addEventListener('click', () => {
        seg.querySelectorAll('button[data-tab]').forEach(b => {
          b.classList.toggle('active', b === btn);
          b.setAttribute('aria-selected', b === btn);
        });
        document.querySelectorAll('[data-tab-group="' + group + '"]').forEach(p => {
          p.classList.toggle('active', p.id === group + '-' + btn.dataset.tab);
        });
        seg.dispatchEvent(new CustomEvent('tabchange', { detail: btn.dataset.tab }));
      });
    });
  });
}

/* 모달 */
const Modal = {
  el: null,
  open(html) {
    this.el = this.el || document.getElementById('modal');
    document.getElementById('modal-body').innerHTML = html;
    this.el.classList.add('open');
    document.body.style.overflow = 'hidden';
  },
  set(html) { document.getElementById('modal-body').innerHTML = html; },
  close() {
    if (!this.el) return;
    this.el.classList.remove('open');
    document.body.style.overflow = '';
  },
  loading(msg) {
    this.open('<div class="loading"><div class="spinner"></div><p>' + esc(msg) + '</p></div>');
  },
};

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  const modal = document.getElementById('modal');
  if (modal) {
    modal.addEventListener('click', e => { if (e.target === modal || e.target.closest('[data-close]')) Modal.close(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') Modal.close(); });
  }
  const tbtn = document.getElementById('theme-toggle');
  if (tbtn) tbtn.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('theme', next); } catch (e) {}
  });
});

async function postJSON(url, body) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  let data;
  try { data = await resp.json(); } catch (e) { data = { error: '응답을 해석할 수 없어요 (' + resp.status + ')' }; }
  if (!resp.ok && !data.error) data.error = '요청 실패 (' + resp.status + ')';
  return data;
}

function aiReportHTML(kicker, title, meta, content) {
  return '<div class="modal-kicker">' + esc(kicker) + '</div>' +
    (title ? '<div class="modal-title">' + esc(title) + '</div>' : '') +
    (meta ? '<div class="modal-meta">' + esc(meta) + '</div>' : '<div style="height:12px"></div>') +
    '<div class="ai-content">' + esc(content) + '</div>';
}
