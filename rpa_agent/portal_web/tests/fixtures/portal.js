// Local stand-in for the supplier site, for the driver tests only. State lives in localStorage
// key "fx" (seeded by the test through an init script) so it survives page changes like the real
// server-side cart does. Every state-changing action is appended to fx.log.
(function () {
  function load() { return JSON.parse(localStorage.getItem('fx') || '{}'); }
  function save(fx) { localStorage.setItem('fx', JSON.stringify(fx)); }
  function canon(s) { return String(s || '').trim().replace(/^0+/, ''); }
  function pad(s) { s = canon(s); return ('000000000000000000' + s).slice(-18); }
  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function banner(text) {
    var box = document.getElementById('messages');
    box.innerHTML = '';
    if (text) box.appendChild(el('div', { role: 'alert' }, text));   // a new element each time
  }
  function nameOf(fx, sku) { return (fx.names || {})[canon(sku)] || ('ITEM ' + canon(sku)); }

  function header(fx) {
    var acc = document.getElementById('account');
    if (acc) acc.textContent = fx.account || '';
    var c = fx.credit || {};
    ['consumption', 'credit', 'limit'].forEach(function (k) {
      var e = document.getElementById('credit-' + k);
      if (e) e.textContent = c[k] || '';
    });
  }

  function renderCart(fx, editable) {
    var body = document.getElementById('cart-body');
    if (!body) return;
    body.innerHTML = '';
    (fx.cart || []).forEach(function (row) {
      var tr = el('tr');
      tr.appendChild(el('td', {}, pad(row.sku)));
      tr.appendChild(el('td', {}, nameOf(fx, row.sku)));
      var q = el('td');
      if (editable) {
        var inp = el('input', { type: 'number', 'aria-label': 'Quantity' });
        inp.value = row.qty;
        q.appendChild(inp);
      } else { q.textContent = row.qty; }
      tr.appendChild(q);
      tr.appendChild(el('td', {}, '12.50'));
      tr.appendChild(el('td', {}, '10'));
      tr.appendChild(el('td', {}, '1+0'));
      tr.appendChild(el('td', {}, fx.expiry || '30/06/2027'));
      if (editable) {
        var act = el('td');
        var upd = el('button', { type: 'button' }, 'Update');
        upd.onclick = function () { updateQty(row.sku, Number(inp.value)); };
        var rm = el('button', { type: 'button' }, 'Remove');
        rm.onclick = function () { removeRow(row.sku); };
        act.appendChild(upd); act.appendChild(rm);
        tr.appendChild(act);
      }
      body.appendChild(tr);
    });
  }

  function addLine() {
    var fx = load();
    var sku = canon(document.getElementById('qo-sku').value);
    var qty = Number(document.getElementById('qo-qty').value);
    fx.log = (fx.log || []).concat([{ a: 'add', sku: sku, qty: qty }]);
    var stock = (fx.stock || {})[sku];
    var unknown = (fx.unknown || {})[sku];
    var msg;
    if (unknown) { msg = unknown; }
    else if (stock === 0) { msg = nameOf(fx, sku) + ': No material Stock'; }
    else if (stock !== undefined && qty > stock) { msg = nameOf(fx, sku) + ': No Enough material Stock'; }
    else {
      var hit = (fx.cart || []).filter(function (r) { return canon(r.sku) === sku; })[0];
      if (hit) { hit.qty += qty; msg = 'This item was already in your cart. The quantity was updated.'; }
      else { fx.cart = (fx.cart || []).concat([{ sku: sku, qty: qty }]); msg = 'Quick order list has been added to the cart'; }
    }
    save(fx); banner(msg); renderCart(fx, true);
  }

  function updateQty(sku, qty) {
    var fx = load();
    fx.log = (fx.log || []).concat([{ a: 'update', sku: canon(sku), qty: qty }]);
    var stock = (fx.stock || {})[canon(sku)];
    var msg;
    if (stock !== undefined && qty > stock) { msg = nameOf(fx, sku) + ': No Enough material Stock'; }
    else {
      fx.cart.forEach(function (r) { if (canon(r.sku) === canon(sku)) r.qty = qty; });
      msg = 'This item was already in your cart. The quantity was updated.';
    }
    save(fx); banner(msg); renderCart(fx, true);
  }

  function removeRow(sku) {
    var fx = load();
    fx.log = (fx.log || []).concat([{ a: 'remove', sku: canon(sku) }]);
    fx.cart = (fx.cart || []).filter(function (r) { return canon(r.sku) !== canon(sku); });
    save(fx); banner('Product has been removed from your cart.'); renderCart(fx, true);
  }

  function search() {
    var fx = load();
    var term = document.getElementById('search-term').value.toLowerCase();
    var list = document.getElementById('search-results');
    list.innerHTML = '';
    Object.keys(fx.names || {}).forEach(function (sku) {
      var name = fx.names[sku];
      if (name.toLowerCase().indexOf(term) === -1) return;
      var li = el('li');
      li.appendChild(el('span', {}, name));
      li.appendChild(el('span', {}, ' ID ' + pad(sku) + ' '));
      li.appendChild(el('span', {}, 'PH. Price 12.50'));
      if ((fx.stock || {})[sku] === 0) li.appendChild(el('span', {}, ' Out Of Stock'));
      list.appendChild(li);
    });
  }

  function submitOrder() {
    var fx = load();
    var ref = fx.next_order || '2104322530';
    fx.log = (fx.log || []).concat([{ a: 'submit' }]);
    fx.orders = (fx.orders || []).concat([{ ref: ref, date: fx.today || '18/11/2026',
      lines: (fx.cart || []).map(function (r) { return { sku: r.sku, qty: r.qty }; }) }]);
    fx.cart = [];
    save(fx);
    location.href = 'thank_you.html';
  }

  // a pager the robot must notice (never press): fx.history_page_size / fx.details_page_size
  function pager(box, id) {
    var old = document.getElementById(id);
    if (old) old.remove();
    var nav = el('nav', { id: id, 'aria-label': 'Pagination' });
    nav.appendChild(el('a', { href: '#next' }, 'Next'));
    box.appendChild(nav);
  }

  function history() {
    var fx = load();
    var body = document.getElementById('history-body');
    var all = (fx.orders || []).slice().reverse();
    var size = fx.history_page_size || all.length;
    if (all.length > size) pager(document.getElementById('history-box'), 'history-pager');
    all.slice(0, size).forEach(function (o) {
      var tr = el('tr');
      var td = el('td');
      var a = el('a', { href: '#order-' + o.ref }, o.ref);
      a.onclick = function () { details(o); };
      td.appendChild(a);
      tr.appendChild(td);
      tr.appendChild(el('td', {}, o.date));
      tr.appendChild(el('td', {}, 'Created'));
      tr.appendChild(el('td', {}, '100.00'));
      body.appendChild(tr);
    });
  }

  function details(o) {
    var fx = load();
    var body = document.getElementById('details-body');
    body.innerHTML = '';
    var section = document.getElementById('details');
    var old = document.getElementById('details-pager');
    if (old) old.remove();
    var count = document.getElementById('details-count');
    if (count) count.remove();
    var size = fx.details_page_size || (o.lines || []).length;
    if ((o.lines || []).length > size) pager(section, 'details-pager');
    if (fx.details_count) section.appendChild(el('span', { id: 'details-count', 'aria-label': 'Number of items' },
                                                 String((o.lines || []).length + (fx.details_count_extra || 0)) + ' items'));
    (o.lines || []).slice(0, size).forEach(function (r) {
      var tr = el('tr');
      tr.appendChild(el('td', {}, pad(r.sku)));
      tr.appendChild(el('td', {}, 'ITEM ' + canon(r.sku)));
      tr.appendChild(el('td', {}, String(r.qty)));
      body.appendChild(tr);
    });
    document.getElementById('details').hidden = false;
  }

  window.addEventListener('DOMContentLoaded', function () {
    var fx = load();
    var page = document.body.getAttribute('data-page');
    header(fx);
    if (page === 'quick-order') {
      renderCart(fx, true);
      document.getElementById('qo-add').onclick = addLine;
      document.getElementById('search-go').onclick = search;
    } else if (page === 'review') {
      renderCart(fx, false);
      document.getElementById('submit-order').onclick = submitOrder;
    } else if (page === 'history') {
      history();
    }
  });
})();
