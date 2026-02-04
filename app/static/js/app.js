function applyView() {
      var saved = localStorage.getItem('s3mgr-view') || 'table';
      document.body.setAttribute('data-view', saved);
      var tableBtn = document.getElementById('viewTable');
      var gridBtn = document.getElementById('viewGrid');
      if (tableBtn && gridBtn) {
        tableBtn.classList.toggle('active', saved === 'table');
        gridBtn.classList.toggle('active', saved === 'grid');
      }
    }
        function toggleView(view) {
      document.body.setAttribute('data-view', view);
      localStorage.setItem('s3mgr-view', view);
      applyView();
    }
    function applyFilters() {
      var box = document.getElementById('searchBox');
      var filter = document.getElementById('typeFilter');
      var q = box ? box.value.toLowerCase() : '';
      var kind = filter ? filter.value : 'all';
      var rows = document.querySelectorAll('#fileTable tbody tr[data-kind]');
      var cards = document.querySelectorAll('.grid-item[data-kind]');
      function match(el) {
        var name = (el.getAttribute('data-name') || '').toLowerCase();
        var kindMatches = kind === 'all' || el.getAttribute('data-kind') === kind;
        var textMatches = !q || name.indexOf(q) !== -1;
        el.classList.toggle('is-hidden', !(kindMatches && textMatches));
      }
      rows.forEach(match);
      cards.forEach(match);
    }
    function initSearch() {
      var box = document.getElementById('searchBox');
      var filter = document.getElementById('typeFilter');
      if (!box) return;
      box.addEventListener('input', applyFilters);
      if (filter) {
        filter.addEventListener('change', applyFilters);
      }
    }
    function initSort() {
      var select = document.getElementById('sortSelect');
      if (!select) return;
      select.addEventListener('change', function() {
        var mode = select.value;
        var tbody = document.querySelector('#fileTable tbody');
        var grid = document.getElementById('gridItems');
        if (!tbody) return;
        var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr[data-kind]'));
        var cards = Array.prototype.slice.call(document.querySelectorAll('.grid-item[data-kind]'));
        rows.sort(function(a, b) {
          if (mode === 'name') {
            return (a.dataset.name || '').localeCompare(b.dataset.name || '');
          }
          if (mode === 'size') {
            return (parseInt(b.dataset.size || '0', 10) - parseInt(a.dataset.size || '0', 10));
          }
          if (mode === 'modified') {
            return (b.dataset.date || '').localeCompare(a.dataset.date || '');
          }
          return 0;
        });
        rows.forEach(function(r) { tbody.appendChild(r); });
        if (grid) {
          cards.sort(function(a, b) {
            if (mode === 'name') {
              return (a.dataset.name || '').localeCompare(b.dataset.name || '');
            }
            if (mode === 'size') {
              return (parseInt(b.dataset.size || '0', 10) - parseInt(a.dataset.size || '0', 10));
            }
            if (mode === 'modified') {
              return (b.dataset.date || '').localeCompare(a.dataset.date || '');
            }
            return 0;
          });
          cards.forEach(function(c) { grid.appendChild(c); });
        }
      });
    }
    function showToast(message) {
      var toast = document.getElementById('toast');
      if (!toast) return;
      toast.textContent = message;
      toast.classList.add('show');
      setTimeout(function() { toast.classList.remove('show'); }, 1400);
    }
    function openModal(opts) {
      var modal = document.getElementById('confirmModal');
      if (!modal) return;
      var titleEl = document.getElementById('confirmTitle');
      var msgEl = document.getElementById('confirmMessage');
      var okBtn = document.getElementById('confirmOk');
      var cancelBtn = document.getElementById('confirmCancel');
      var input = document.getElementById('confirmInput');
      if (titleEl) titleEl.textContent = opts.title || 'Confirm';
      if (msgEl) msgEl.textContent = opts.message || '';
      if (okBtn) okBtn.textContent = opts.okText || 'OK';
      if (cancelBtn) cancelBtn.textContent = opts.cancelText || 'Cancel';
      if (input) {
        input.value = opts.inputValue || '';
        input.placeholder = opts.inputPlaceholder || '';
        input.classList.toggle('is-hidden', !opts.showInput);
        input.readOnly = !!opts.readOnly;
      }
      function close() {
        modal.classList.remove('show');
        okBtn.removeEventListener('click', okHandler);
        cancelBtn.removeEventListener('click', close);
        modal.removeEventListener('click', backdropClose);
      }
      function okHandler() {
        var value = input ? input.value : '';
        close();
        if (opts.onConfirm) opts.onConfirm(value);
      }
      function backdropClose(e) {
        if (e.target === modal) close();
      }
      okBtn.addEventListener('click', okHandler);
      cancelBtn.addEventListener('click', close);
      modal.addEventListener('click', backdropClose);
      modal.classList.add('show');
      if (input && opts.showInput) {
        setTimeout(function() { input.focus(); input.select(); }, 50);
      }
    }
    function showConfirm(title, message, onConfirm) {
      openModal({ title: title, message: message, okText: 'Delete', onConfirm: onConfirm });
    }
    function showAlert(title, message) {
      openModal({ title: title, message: message, okText: 'OK', cancelText: 'Close' });
    }
    function showPrompt(title, message, defaultValue, onConfirm) {
      openModal({ title: title, message: message, okText: 'Save', showInput: true, inputValue: defaultValue || '', onConfirm: onConfirm });
    }
    function showCopyFallback(text) {
      openModal({ title: 'Copy URL', message: 'Copy the link below:', okText: 'Done', cancelText: 'Close', showInput: true, inputValue: text || '', readOnly: true });
    }
    function initCopyButtons() {
      var buttons = document.querySelectorAll('[data-copy]');
      buttons.forEach(function(btn) {
        btn.addEventListener('click', function(e) {
          e.preventDefault();
          var val = btn.getAttribute('data-copy');
          if (!val) return;
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(val);
            showToast('Copied to clipboard');
          } else {
            showCopyFallback(val);
          }
        });
      });
    }
    function initDropzone() {
      var zone = document.getElementById('dropzone');
      var fileInput = document.getElementById('fileInput');
      var fileLabel = document.getElementById('fileCount');
      if (!zone || !fileInput) return;
      ['dragenter','dragover'].forEach(function(evt) {
        zone.addEventListener(evt, function(e) {
          e.preventDefault();
          zone.classList.add('active');
        });
      });
      ['dragleave','drop'].forEach(function(evt) {
        zone.addEventListener(evt, function(e) {
          e.preventDefault();
          zone.classList.remove('active');
        });
      });
      zone.addEventListener('drop', function(e) {
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
          fileInput.files = e.dataTransfer.files;
          if (fileLabel) {
            fileLabel.textContent = e.dataTransfer.files.length + ' files selected';
          }
        }
      });
    }
    function initUpload() {
      var form = document.getElementById('uploadForm');
      if (!form) return;
      var bar = document.getElementById('progressFill');
      var wrap = document.getElementById('progressWrap');
      var txt = document.getElementById('progressText');
      var fileLabel = document.getElementById('fileCount');
      form.addEventListener('submit', function(e) {
        e.preventDefault();
        var fileInput = document.getElementById('fileInput');
        if (!fileInput || !fileInput.files.length) {
          showAlert('Upload', 'Choose a file first');
          return;
        }
        if (wrap) wrap.classList.remove('is-hidden');
        bar.style.width = '0%';
        txt.textContent = '0%';

        var xhr = new XMLHttpRequest();
        xhr.open('POST', form.getAttribute('action') || '/', true);

        xhr.upload.onprogress = function(ev) {
          if (ev.lengthComputable) {
            var p = Math.round((ev.loaded / ev.total) * 100);
            bar.style.width = p + '%';
            txt.textContent = p + '%';
          }
        };
        xhr.onload = function() {
          if (xhr.status === 200) {
            txt.textContent = 'Done';
            setTimeout(function(){ window.location.reload(); }, 500);
          } else {
            txt.textContent = (xhr.responseText && xhr.responseText.trim()) ? xhr.responseText : ('Error ' + xhr.status);
          }
        };
        xhr.onerror = function() { txt.textContent = 'Upload failed'; };

        var fd = new FormData(form);
        xhr.send(fd);
      });
      var fileInput = document.getElementById('fileInput');
      if (fileInput && fileLabel) {
        fileInput.addEventListener('change', function() {
          var count = fileInput.files ? fileInput.files.length : 0;
          fileLabel.textContent = count ? (count + ' files selected') : 'No files selected';
        });
      }
    }
    function getSelectedKeys() {
      var boxes = document.querySelectorAll('.row-select:checked');
      var keys = [];
      boxes.forEach(function(box) {
        var key = box.getAttribute('data-key');
        if (key && keys.indexOf(key) === -1) {
          keys.push(key);
        }
      });
      return keys;
    }
    function syncCheckboxes(key, checked) {
      var boxes = document.querySelectorAll('.row-select');
      boxes.forEach(function(box) {
        if (box.getAttribute('data-key') === key) {
          box.checked = checked;
        }
      });
    }
    function updateSelectionCount() {
      var label = document.getElementById('selectedCount');
      var bar = document.getElementById('bulkBar');
      if (!label) return;
      var keys = getSelectedKeys();
      label.textContent = keys.length + ' selected';
      if (bar) { bar.classList.toggle('hidden', keys.length === 0); }
    }
    function initSelection() {
      var boxes = document.querySelectorAll('.row-select');
      boxes.forEach(function(box) {
        box.addEventListener('change', function() {
          var key = box.getAttribute('data-key');
          syncCheckboxes(key, box.checked);
          updateSelectionCount();
        });
      });
      var selectAll = document.getElementById('selectAll');
      if (selectAll) {
        selectAll.addEventListener('change', function() {
          var rows = document.querySelectorAll('.row-select');
          rows.forEach(function(box) {
            var container = box.closest('.is-hidden');
            if (!container) { box.checked = selectAll.checked; }
          });
          updateSelectionCount();
        });
      }
      updateSelectionCount();
    }
    function submitBulk(action) {
      var keys = getSelectedKeys();
      if (!keys.length) { showAlert('Bulk action', 'Select files or folders first'); return; }
      if (action === 'delete') {
        showConfirm('Delete selected', 'Delete all selected items? This cannot be undone.', function() {
          proceedBulk(action, keys, form, target, targetHidden);
        });
        return;
      }
      var form = document.getElementById('bulkForm');
      var target = document.getElementById('bulkTarget');
      var targetHidden = document.getElementById('bulkTargetHidden');
      if (!form) return;
      proceedBulk(action, keys, form, target, targetHidden);
    }
    function proceedBulk(action, keys, form, target, targetHidden) {
      if (!form) return;
      form.querySelectorAll('input[name="keys"]').forEach(function(el) { el.remove(); });
      keys.forEach(function(k) {
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'keys';
        input.value = k;
        form.appendChild(input);
      });
      var actionInput = document.getElementById('bulkAction');
      if (actionInput) actionInput.value = action;
      if ((action === 'move' || action === 'copy') && (!target || !target.value)) {
        showAlert('Bulk action', 'Enter a target prefix');
        return;
      }
      if (targetHidden) { targetHidden.value = target && target.value ? target.value : ''; }
      form.submit();
    }
    function initBulkActions() {
      var deleteBtn = document.getElementById('bulkDelete');
      var moveBtn = document.getElementById('bulkMove');
      var copyBtn = document.getElementById('bulkCopy');
      if (deleteBtn) {
        deleteBtn.addEventListener('click', function(e) {
          e.preventDefault();
          showConfirm('Delete selected', 'Delete all selected items? This cannot be undone.', function() {
            submitBulk('delete');
          });
        });
      }
      if (moveBtn) moveBtn.addEventListener('click', function(e) { e.preventDefault(); submitBulk('move'); });
      if (copyBtn) copyBtn.addEventListener('click', function(e) { e.preventDefault(); submitBulk('copy'); });
    }
    function initDeleteLinks() {
      var links = document.querySelectorAll('[data-delete-url]');
      links.forEach(function(link) {
        link.addEventListener('click', function(e) {
          e.preventDefault();
          var url = link.getAttribute('data-delete-url');
          if (!url) return;
          showConfirm('Delete item', 'Delete this item? This cannot be undone.', function() {
            window.location.href = url;
          });
        });
      });
    }
    function initRename() {
      var renames = document.querySelectorAll('[data-rename]');
      renames.forEach(function(btn) {
        btn.addEventListener('click', function(e) {
          e.preventDefault();
          var key = btn.getAttribute('data-rename');
          var current = btn.getAttribute('data-name') || key;
          showPrompt('Rename item', 'Enter the new name', current, function(next) {
            if (!next || next === current) return;
            var form = document.getElementById('renameForm');
            if (!form) return;
            form.querySelector('input[name="old"]').value = key;
            form.querySelector('input[name="new"]').value = next;
            form.submit();
          });
        });
      });
    }
    document.addEventListener('DOMContentLoaded', function() {
      applyView();      var tableBtn = document.getElementById('viewTable');
      var gridBtn = document.getElementById('viewGrid');
      if (tableBtn && gridBtn) {
        tableBtn.addEventListener('click', function(e) { e.preventDefault(); toggleView('table'); });
        gridBtn.addEventListener('click', function(e) { e.preventDefault(); toggleView('grid'); });
      }
      var refresh = document.getElementById('lastRefresh');
      if (refresh) { refresh.textContent = new Date().toLocaleTimeString(); }
      initSearch();
      applyFilters();
      initUpload();
      initSort();
      initCopyButtons();
      initDropzone();
      initSelection();
      initBulkActions();
      initRename();
      initDeleteLinks();
    });
