/* =====================================================================
   Student Management System - interactions & motion
   Plain JavaScript, no dependencies. Safe to load on every page.
   ===================================================================== */

(function () {
    "use strict";

    var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /* ---------- tiny helpers ---------- */
    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }
    function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
    function debounce(fn, ms) {
        var t;
        return function () {
            var args = arguments, ctx = this;
            clearTimeout(t);
            t = setTimeout(function () { fn.apply(ctx, args); }, ms);
        };
    }

    /* ---------- top progress bar ---------- */
    var bar = el("div", "page-progress");
    var barTimer;
    function progressStart() {
        bar.classList.remove("done");
        bar.style.width = "0";
        void bar.offsetWidth;
        bar.classList.add("active");
        bar.style.width = "85%";
        clearTimeout(barTimer);
        barTimer = setTimeout(progressDone, 12000); // safety net
    }
    function progressDone() {
        clearTimeout(barTimer);
        bar.classList.remove("active");
        bar.classList.add("done");
    }

    /* ---------- toasts ---------- */
    function getStack() {
        var stack = document.querySelector(".flash-stack");
        if (!stack) {
            stack = el("div", "flash-stack");
            stack.setAttribute("role", "status");
            stack.setAttribute("aria-live", "polite");
            document.body.appendChild(stack);
        }
        return stack;
    }

    function dismissToast(alert) {
        if (!alert || alert.classList.contains("leaving")) return;
        clearTimeout(alert._timer);
        alert.classList.add("leaving");
        setTimeout(function () { alert.remove(); }, 340);
    }

    function armToast(alert) {
        var life = alert.classList.contains("danger") ? 7000 : 5000;
        var remaining = life, startedAt;
        alert.style.setProperty("--life", life + "ms");

        function run() {
            startedAt = Date.now();
            alert._timer = setTimeout(function () { dismissToast(alert); }, remaining);
        }
        alert.addEventListener("mouseenter", function () {
            clearTimeout(alert._timer);
            remaining -= Date.now() - startedAt;
        });
        alert.addEventListener("mouseleave", run);
        var close = alert.querySelector(".alert-close");
        if (close) close.addEventListener("click", function () { dismissToast(alert); });
        run();
    }

    window.toast = function (message, type) {
        var stack = getStack();
        var duplicate = qsa(".alert", stack).some(function (a) {
            return a.firstElementChild && a.firstElementChild.textContent === message;
        });
        if (duplicate) return;
        var alert = el("div", "alert " + (type || "success"));
        alert.appendChild(el("span", "", message));
        var btn = el("button", "alert-close", "×");
        btn.type = "button";
        btn.setAttribute("aria-label", "Dismiss message");
        alert.appendChild(btn);
        stack.appendChild(alert);
        armToast(alert);
    };

    /* ---------- confirm dialog (replaces window.confirm) ---------- */
    function confirmModal(opts) {
        return new Promise(function (resolve) {
            var previous = document.activeElement;
            var backdrop = el("div", "modal-backdrop");
            var modal = el("div", "modal");
            modal.setAttribute("role", "alertdialog");
            modal.setAttribute("aria-modal", "true");
            modal.setAttribute("aria-labelledby", "modal-title");
            modal.setAttribute("aria-describedby", "modal-text");

            var icon = el("div", "modal-icon", "!");
            var title = el("h3", "", opts.title || "Are you sure?");
            title.id = "modal-title";
            var text = el("p", "", opts.message || "");
            text.id = "modal-text";
            var actions = el("div", "modal-actions");
            var cancel = el("button", "button", "Cancel");
            cancel.type = "button";
            var ok = el("button", "button danger-solid", opts.okText || "Confirm");
            ok.type = "button";
            actions.appendChild(cancel);
            actions.appendChild(ok);
            [icon, title, text, actions].forEach(function (n) { modal.appendChild(n); });
            backdrop.appendChild(modal);
            document.body.appendChild(backdrop);
            document.body.style.overflow = "hidden";

            requestAnimationFrame(function () {
                backdrop.classList.add("open");
                cancel.focus();
            });

            function close(result) {
                document.removeEventListener("keydown", onKey, true);
                backdrop.classList.remove("open");
                document.body.style.overflow = "";
                setTimeout(function () {
                    backdrop.remove();
                    if (previous && previous.focus) previous.focus();
                }, 260);
                resolve(result);
            }
            function onKey(e) {
                if (e.key === "Escape") { e.preventDefault(); close(false); }
                if (e.key === "Tab") {
                    e.preventDefault();
                    (document.activeElement === cancel ? ok : cancel).focus();
                }
            }
            document.addEventListener("keydown", onKey, true);
            cancel.addEventListener("click", function () { close(false); });
            ok.addEventListener("click", function () { close(true); });
            backdrop.addEventListener("mousedown", function (e) { if (e.target === backdrop) close(false); });
        });
    }

    /* ---------- count-up numbers ---------- */
    function countUp(node) {
        if (node.dataset.counted) return;
        node.dataset.counted = "1";
        if (reduceMotion) return;
        var original = node.textContent.trim();
        var m = original.match(/^([^\d\-]*)(-?[\d,]*\.?\d+)(.*)$/);
        if (!m) return;
        var prefix = m[1], numText = m[2], suffix = m[3];
        var target = parseFloat(numText.replace(/,/g, ""));
        if (!isFinite(target) || target === 0) return;
        var decimals = (numText.split(".")[1] || "").length;
        var grouping = numText.indexOf(",") !== -1;
        var duration = 1100, start = performance.now();

        function frame(now) {
            var t = Math.min(1, (now - start) / duration);
            var eased = 1 - Math.pow(1 - t, 4);
            var value = (target * eased).toLocaleString("en-US", {
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals,
                useGrouping: grouping
            });
            node.textContent = t < 1 ? prefix + value + suffix : original;
            if (t < 1) requestAnimationFrame(frame);
        }
        requestAnimationFrame(frame);
    }

    /* ---------- scroll reveal + count-up trigger ---------- */
    function initReveal() {
        var selector = ".page-heading, .hero-heading, .panel, .stat-card, .demo-banner > div, .mini-stats > div, .concept-list > div";
        var targets = qsa(selector).filter(function (n) { return !n.closest(".login-card"); });
        var perParent = new Map();

        targets.forEach(function (node) {
            var parent = node.parentElement;
            var index = perParent.get(parent) || 0;
            perParent.set(parent, index + 1);
            node.style.setProperty("--d", Math.min(index, 8) * 70 + "ms");
            node.classList.add("reveal");
        });

        var counters = ".stat-card strong, .mini-stats b, .demo-banner b, .counter-number";

        function show(node) {
            node.classList.add("in");
            qsa(counters, node).forEach(countUp);
            if (node.matches(counters)) countUp(node);
            // hand control back to the element's own hover transitions
            var delay = parseFloat(node.style.getPropertyValue("--d")) || 0;
            setTimeout(function () {
                node.classList.remove("reveal", "in");
                node.style.removeProperty("--d");
            }, 700 + delay);
        }

        if (!("IntersectionObserver" in window) || reduceMotion) {
            targets.forEach(show);
            return;
        }
        var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    io.unobserve(entry.target);
                    show(entry.target);
                }
            });
        }, { threshold: 0, rootMargin: "0px 0px -30px 0px" });
        targets.forEach(function (node) { io.observe(node); });
    }

    /* ---------- tables: row animation, row links, sorting, live filter ---------- */
    function animateRows(rows) {
        if (reduceMotion) return;
        rows.forEach(function (row, i) {
            row.classList.remove("row-anim");
            void row.offsetWidth;
            row.style.setProperty("--i", Math.min(i, 14));
            row.classList.add("row-anim");
        });
        setTimeout(function () {
            rows.forEach(function (row) { row.classList.remove("row-anim"); });
        }, 1400);
    }

    function cellSortKey(td) {
        var text = (td ? td.textContent : "").trim();
        var date = /^([A-Z][a-z]{2} \d{1,2}, \d{4})(?:\s*·\s*(\d{1,2}:\d{2} [AP]M))?/.exec(text);
        if (date) {
            var parsed = Date.parse(date[1] + (date[2] ? " " + date[2] : ""));
            if (!isNaN(parsed)) return { n: parsed, t: text };
        }
        if (/^[₱$]?\s*-?[\d,]*\.?\d+\s*%?$/.test(text)) {
            return { n: parseFloat(text.replace(/[₱$,%\s]/g, "")), t: text };
        }
        return { n: null, t: text };
    }

    function clearMarks(root) {
        qsa("mark.hit", root).forEach(function (mark) {
            var parent = mark.parentNode;
            parent.replaceChild(document.createTextNode(mark.textContent), mark);
            parent.normalize();
        });
    }
    function highlight(root, query) {
        var lower = query.toLowerCase();
        var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode: function (n) {
                if (!n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
                if (n.parentNode.closest("button, form, a.button, script, style")) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            }
        });
        var nodes = [], n;
        while ((n = walker.nextNode())) nodes.push(n);
        nodes.forEach(function (node) {
            var idx = node.nodeValue.toLowerCase().indexOf(lower);
            if (idx === -1) return;
            var mid = node.splitText(idx);
            mid.splitText(query.length);
            var mark = el("mark", "hit");
            mid.parentNode.replaceChild(mark, mid);
            mark.appendChild(mid);
        });
    }

    function enhanceTable(table) {
        var tbody = table.tBodies[0];
        if (!tbody) return;
        var allRows = qsa("tr", tbody);
        var rows = allRows.filter(function (r) { return !r.querySelector("td[colspan]"); });
        if (!rows.length) return;

        // rows that contain a record link become clickable
        rows.forEach(function (row) {
            var link = row.querySelector("a.table-link");
            if (!link) return;
            row.classList.add("row-link");
            row.title = "Open " + link.textContent.trim().split("\n")[0];
        });

        // animate first rows once the table scrolls into view
        if ("IntersectionObserver" in window) {
            var rio = new IntersectionObserver(function (entries) {
                if (entries[0].isIntersecting) {
                    rio.disconnect();
                    animateRows(rows.filter(function (r) { return !r.classList.contains("tt-hidden"); }).slice(0, 15));
                }
            }, { threshold: 0 });
            rio.observe(table);
        }

        var holder = table.closest(".table-wrap, .history-scroll, .activity-scroll");
        var emptyRow = null, count = null, input = null, sortState = { index: -1, dir: "asc" };

        // ----- sorting -----
        var headers = qsa("thead th", table);
        headers.forEach(function (th, idx) {
            var label = th.textContent.trim();
            var buttonCells = rows.filter(function (r) {
                return r.cells[idx] && r.cells[idx].querySelector(".button, button");
            }).length;
            // skip empty headers and columns that only hold action buttons
            if (rows.length < 2 || !label || buttonCells >= Math.ceil(rows.length / 2)) return;
            th.classList.add("sortable");
            th.tabIndex = 0;
            th.setAttribute("role", "button");
            th.title = "Click to sort";
            function sort() {
                sortState.dir = sortState.index === idx && sortState.dir === "asc" ? "desc" : "asc";
                sortState.index = idx;
                headers.forEach(function (h) { h.classList.remove("asc", "desc"); });
                th.classList.add(sortState.dir);
                var factor = sortState.dir === "asc" ? 1 : -1;
                rows.sort(function (a, b) {
                    var ka = cellSortKey(a.cells[idx]), kb = cellSortKey(b.cells[idx]);
                    if (ka.n !== null && kb.n !== null && ka.n !== kb.n) return (ka.n - kb.n) * factor;
                    return ka.t.localeCompare(kb.t, undefined, { numeric: true, sensitivity: "base" }) * factor;
                });
                rows.forEach(function (r) { tbody.appendChild(r); });
                if (emptyRow) tbody.appendChild(emptyRow);
                animateRows(rows.filter(function (r) { return !r.classList.contains("tt-hidden"); }).slice(0, 15));
            }
            th.addEventListener("click", sort);
            th.addEventListener("keydown", function (e) {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sort(); }
            });
        });

        // ----- live filter (only for longer tables) -----
        if (rows.length >= 6 && holder && !table.hasAttribute("data-no-filter")) {
            var tools = el("div", "table-tools");
            var wrap = el("div", "tt-input");
            wrap.appendChild(el("span", "", "⌕"));
            input = el("input");
            input.type = "search";
            input.placeholder = "Filter this table…";
            input.setAttribute("aria-label", "Filter table rows");
            wrap.appendChild(input);
            count = el("span", "tt-count", rows.length + " rows");
            tools.appendChild(wrap);
            tools.appendChild(count);
            holder.parentNode.insertBefore(tools, holder);

            emptyRow = el("tr", "tt-empty");
            emptyRow.hidden = true;
            var td = el("td", "empty");
            td.colSpan = headers.length || 1;
            emptyRow.appendChild(td);
            tbody.appendChild(emptyRow);

            input.addEventListener("input", debounce(function () {
                var q = input.value.trim();
                var lower = q.toLowerCase();
                var shown = 0;
                rows.forEach(function (row) {
                    clearMarks(row);
                    var hit = !lower || row.textContent.toLowerCase().indexOf(lower) !== -1;
                    row.classList.toggle("tt-hidden", !hit);
                    if (hit) {
                        shown++;
                        if (lower) highlight(row, q);
                    }
                });
                count.textContent = lower ? "Showing " + shown + " of " + rows.length : rows.length + " rows";
                count.classList.remove("flash");
                void count.offsetWidth;
                count.classList.add("flash");
                emptyRow.hidden = shown !== 0;
                emptyRow.firstChild.textContent = "No rows match “" + q + "”.";
            }, 110));
        }
    }

    /* ---------- forms ---------- */
    function startLoading(form, submitter) {
        if (form.dataset.submitting === "1") return false;
        form.dataset.submitting = "1";
        var btn = submitter || form.querySelector("button[type=submit], button:not([type])");
        if (btn) {
            btn.classList.add("is-loading");
            form._loadingBtn = btn;
        }
        progressStart();
        setTimeout(function () { resetLoading(form); }, 15000);
        return true;
    }
    function resetLoading(form) {
        form.dataset.submitting = "";
        if (form._loadingBtn) form._loadingBtn.classList.remove("is-loading");
    }

    function initPasswordToggles() {
        var eyeOpen = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
        var eyeShut = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.9 17.9A10.9 10.9 0 0 1 12 20C5 20 1 12 1 12a18.5 18.5 0 0 1 5.1-5.9M9.9 4.2A9.1 9.1 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.2 3.2M1 1l22 22"/></svg>';
        qsa("input[type=password]").forEach(function (input) {
            if (input.closest(".password-toggle")) return; // account page already has its own toggle
            var wrap = el("div", "pw-field");
            input.parentNode.insertBefore(wrap, input);
            wrap.appendChild(input);
            var btn = el("button", "pw-eye");
            btn.type = "button";
            btn.innerHTML = eyeOpen;
            btn.setAttribute("aria-label", "Show password");
            btn.addEventListener("click", function () {
                var show = input.type === "password";
                input.type = show ? "text" : "password";
                btn.innerHTML = show ? eyeShut : eyeOpen;
                btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
                input.focus();
            });
            wrap.appendChild(btn);
        });
    }

    function initFilePreview() {
        qsa("input[type=file]").forEach(function (input) {
            var maxMb = parseFloat(input.dataset.maxMb) || 3;
            var preview = null, url = null;
            input.addEventListener("change", function () {
                if (preview) { preview.remove(); preview = null; }
                if (url) { URL.revokeObjectURL(url); url = null; }
                var file = input.files && input.files[0];
                if (!file) return;
                if (file.size > maxMb * 1024 * 1024) {
                    window.toast("That image is larger than " + maxMb + " MB. Please choose a smaller file.", "danger");
                    input.value = "";
                    return;
                }
                if (!/^image\//.test(file.type)) return;
                url = URL.createObjectURL(file);
                preview = el("div");
                preview.appendChild(el("span", "upload-preview-label", "New photo preview"));
                var img = el("img", "upload-preview");
                img.src = url;
                img.alt = "Selected photo preview";
                preview.appendChild(img);
                input.insertAdjacentElement("afterend", preview);
            });
        });
    }

    function initAmountField() {
        var amount = document.querySelector('input[name="amount"]');
        if (!amount) return;
        amount.addEventListener("blur", function () {
            var numeric = Number(String(this.value).replace(/,/g, ""));
            if (this.value.trim() && Number.isFinite(numeric)) {
                this.value = numeric.toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            }
        });
        amount.addEventListener("focus", function () {
            this.value = String(this.value).replace(/,/g, "");
        });
    }

    /* ---------- global event wiring ---------- */
    function initGlobalEvents() {
        // ripple on buttons
        document.addEventListener("pointerdown", function (e) {
            if (reduceMotion) return;
            var btn = e.target.closest(".button");
            if (!btn || btn.disabled || btn.classList.contains("is-loading")) return;
            var rect = btn.getBoundingClientRect();
            var size = Math.max(rect.width, rect.height) * 2;
            var dot = el("span", "ripple");
            dot.style.width = dot.style.height = size + "px";
            dot.style.left = e.clientX - rect.left - size / 2 + "px";
            dot.style.top = e.clientY - rect.top - size / 2 + "px";
            btn.appendChild(dot);
            dot.addEventListener("animationend", function () { dot.remove(); });
        });

        // spotlight that follows the cursor on cards
        document.addEventListener("pointermove", function (e) {
            var card = e.target.closest && e.target.closest(".stat-card, .workflow-step, .demo-banner > div");
            if (!card) return;
            var rect = card.getBoundingClientRect();
            card.style.setProperty("--mx", e.clientX - rect.left + "px");
            card.style.setProperty("--my", e.clientY - rect.top + "px");
        }, { passive: true });

        // clickable table rows
        document.addEventListener("click", function (e) {
            var row = e.target.closest("tr.row-link");
            if (!row || e.target.closest("a, button, form, input, select, label")) return;
            var link = row.querySelector("a.table-link");
            if (link) link.click();
        });

        // dashboard cards the current role cannot open
        qsa('a.stat-link[href="#"]').forEach(function (a) { a.classList.add("locked"); });
        document.addEventListener("click", function (e) {
            var a = e.target.closest('a.stat-link[href="#"]');
            if (!a) return;
            e.preventDefault();
            a.classList.remove("shake");
            void a.offsetWidth;
            a.classList.add("shake");
            a.addEventListener("animationend", function () { a.classList.remove("shake"); }, { once: true });
            window.toast("Your role doesn't have access to that module.", "danger");
        });

        // smooth page-to-page transition
        document.addEventListener("click", function (e) {
            if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
            var a = e.target.closest("a[href]");
            if (!a || (a.target && a.target !== "_self") || a.hasAttribute("download")) return;
            var raw = a.getAttribute("href");
            if (!raw || raw.charAt(0) === "#" || /^(javascript|mailto|tel):/i.test(raw)) return;
            var dest;
            try { dest = new URL(a.href, location.href); } catch (err) { return; }
            if (dest.origin !== location.origin) return;
            if (dest.pathname === location.pathname && dest.search === location.search) return;
            if (reduceMotion) return;
            e.preventDefault();
            document.body.classList.add("leaving");
            progressStart();
            setTimeout(function () { location.href = dest.href; }, 170);
        });

        // forms: animated confirm dialog + loading state
        document.addEventListener("submit", function (e) {
            var form = e.target;
            if (!(form instanceof HTMLFormElement) || e.defaultPrevented) return;

            if (form.dataset.confirmed === "1") {
                form.dataset.confirmed = "";
                startLoading(form, e.submitter);
                return;
            }
            if (form.dataset.confirm) {
                e.preventDefault();
                var submitter = e.submitter;
                confirmModal({
                    title: form.dataset.confirmTitle,
                    message: form.dataset.confirm,
                    okText: form.dataset.confirmOk
                }).then(function (yes) {
                    if (!yes) return;
                    form.dataset.confirmed = "1";
                    if (form.requestSubmit) form.requestSubmit(submitter || undefined);
                    else form.submit();
                });
                return;
            }
            if (!startLoading(form, e.submitter)) e.preventDefault();
        });

        // shake fields that fail validation
        document.addEventListener("invalid", function (e) {
            var field = e.target;
            field.classList.remove("shake");
            void field.offsetWidth;
            field.classList.add("shake");
            field.addEventListener("animationend", function () { field.classList.remove("shake"); }, { once: true });
        }, true);

        // "/" jumps to the first search box
        document.addEventListener("keydown", function (e) {
            if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
            var active = document.activeElement;
            if (active && (/^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName) || active.isContentEditable)) return;
            var search = document.querySelector("input[type=search]");
            if (search) { e.preventDefault(); search.focus(); search.select(); }
        });

        window.addEventListener("beforeunload", progressStart);
        window.addEventListener("pageshow", function (e) {
            document.body.classList.remove("leaving");
            progressDone();
            if (e.persisted) qsa("form").forEach(resetLoading);
        });
    }

    /* ---------- sticky nav shadow + back-to-top ---------- */
    function initScrollUi() {
        var nav = document.querySelector(".navbar");
        var top = el("button", "to-top", "↑");
        top.type = "button";
        top.setAttribute("aria-label", "Back to top");
        top.title = "Back to top";
        top.addEventListener("click", function () {
            window.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
        });
        document.body.appendChild(top);

        var ticking = false;
        function update() {
            var y = window.scrollY;
            if (nav) nav.classList.toggle("scrolled", y > 90);
            top.classList.toggle("show", y > 420);
            ticking = false;
        }
        window.addEventListener("scroll", function () {
            if (!ticking) { ticking = true; requestAnimationFrame(update); }
        }, { passive: true });
        update();
    }

    /* ---------- dark / light theme ----------
       The initial theme is set by a tiny script in <head> (no flash).
       Here: toggle, remember the choice, follow the OS until the user picks,
       and sync across tabs. The switch uses a circular reveal that grows from
       the button (View Transitions API) with a plain fade as the fallback. */
    var THEME_KEY = "sms-theme";
    var rootEl = document.documentElement;

    function currentTheme() { return rootEl.getAttribute("data-theme") === "dark" ? "dark" : "light"; }
    function readSaved() {
        try { var v = localStorage.getItem(THEME_KEY); return v === "dark" || v === "light" ? v : null; }
        catch (e) { return null; }
    }
    function applyTheme(theme) {
        rootEl.setAttribute("data-theme", theme);
        var dark = theme === "dark";
        qsa("[data-theme-toggle]").forEach(function (btn) {
            btn.setAttribute("aria-checked", dark ? "true" : "false");
            btn.title = dark ? "Switch to light mode" : "Switch to dark mode";
        });
    }
    function setTheme(theme, originBtn) {
        if (theme === currentTheme()) return;
        try { localStorage.setItem(THEME_KEY, theme); } catch (e) {}

        if (reduceMotion) { applyTheme(theme); return; }

        if (document.startViewTransition && originBtn) {
            var box = originBtn.getBoundingClientRect();
            var x = box.left + box.width / 2, y = box.top + box.height / 2;
            var radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
            var vt = document.startViewTransition(function () { applyTheme(theme); });
            vt.ready.then(function () {
                rootEl.animate(
                    { clipPath: ["circle(0px at " + x + "px " + y + "px)", "circle(" + radius + "px at " + x + "px " + y + "px)"] },
                    { duration: 700, easing: "cubic-bezier(.22,.8,.3,1)", pseudoElement: "::view-transition-new(root)" }
                );
            }).catch(function () {});
        } else {
            rootEl.classList.add("theme-fade");
            applyTheme(theme);
            setTimeout(function () { rootEl.classList.remove("theme-fade"); }, 520);
        }
    }
    function initTheme() {
        applyTheme(currentTheme());
        qsa("[data-theme-toggle]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                btn.classList.remove("ts-pop");
                void btn.offsetWidth;
                btn.classList.add("ts-pop");
                setTheme(currentTheme() === "dark" ? "light" : "dark", btn);
            });
        });
        // follow the operating system until the user makes their own choice
        if (window.matchMedia) {
            var mq = matchMedia("(prefers-color-scheme: dark)");
            var onSystem = function (e) { if (!readSaved()) applyTheme(e.matches ? "dark" : "light"); };
            if (mq.addEventListener) mq.addEventListener("change", onSystem);
            else if (mq.addListener) mq.addListener(onSystem);
        }
        // keep other open tabs in step
        window.addEventListener("storage", function (e) {
            if (e.key === THEME_KEY && (e.newValue === "dark" || e.newValue === "light")) applyTheme(e.newValue);
        });
    }

    /* ---------- boot ---------- */
    document.addEventListener("DOMContentLoaded", function () {
        document.body.appendChild(bar);

        qsa(".flash-stack .alert").forEach(armToast);

        initTheme();
        initGlobalEvents();
        initScrollUi();
        initPasswordToggles();
        initFilePreview();
        initAmountField();
        qsa(".search-input input, input[type=search]").forEach(function (i) {
            if (!i.title) i.title = "Press / to jump here";
        });
        qsa(".table-wrap table, .history-scroll table, .activity-scroll table").forEach(enhanceTable);
        initReveal();
    });
})();


// Keep student selectors scoped to a chosen section without hiding the full roster.
function filterStudentOptions(sectionSelect, studentSelectId) {
  const students = document.getElementById(studentSelectId);
  if (!students) return;
  const sectionId = sectionSelect.value;
  let selectedStillVisible = false;
  Array.from(students.options).forEach((option, index) => {
    if (index === 0) { option.hidden = false; return; }
    const visible = !sectionId || option.dataset.section === sectionId;
    option.hidden = !visible;
    if (visible && option.selected) selectedStillVisible = true;
  });
  if (!selectedStillVisible && students.value !== '') {
    students.value = '';
    students.dispatchEvent(new Event('change')); // lets the curriculum course filter reset too
  }
}
document.addEventListener('DOMContentLoaded', () => {
  [['student_section', 'student_id'], ['calc_student_section', 'calc_student_id'], ['rec_section', 'rec_student']].forEach(([sectionId, studentId]) => {
    const sectionSelect = document.getElementById(sectionId);
    if (sectionSelect) filterStudentOptions(sectionSelect, studentId);
  });
});


// Account dropdown and explicit logout confirmation.
document.addEventListener("DOMContentLoaded", function () {
  var wrap = document.querySelector("[data-profile-menu]");
  if (wrap) {
    var trigger = wrap.querySelector("[data-profile-menu-trigger]");
    var panel = wrap.querySelector("[data-profile-menu-panel]");
    function setOpen(open) {
      panel.hidden = !open;
      trigger.setAttribute("aria-expanded", open ? "true" : "false");
    }
    trigger.addEventListener("click", function (event) {
      event.stopPropagation();
      setOpen(panel.hidden);
    });
    document.addEventListener("click", function (event) {
      if (!wrap.contains(event.target)) setOpen(false);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !panel.hidden) {
        setOpen(false);
        trigger.focus();
      }
    });
  }
  document.querySelectorAll("[data-logout-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var confirmed = window.confirm("Are you sure you want to sign out of NEPTUNE?");
      if (!confirmed) event.preventDefault();
    });
  });
});


/* =====================================================================
   Keep the scroll position after entering / saving / filtering
   Remembers where the page (and any scrollable list) was when a form is
   submitted and puts it back when the same page loads again.
   Add data-no-scroll-keep to a form to opt out.
   ===================================================================== */
(function () {
    "use strict";
    var KEY = "sms-scroll-keep";
    function lists() { return Array.prototype.slice.call(document.querySelectorAll(".history-scroll, .scroll-list")); }

    document.addEventListener("submit", function (e) {
        var form = e.target;
        if (!(form instanceof HTMLFormElement) || e.defaultPrevented || form.hasAttribute("data-no-scroll-keep")) return;
        try {
            sessionStorage.setItem(KEY, JSON.stringify({
                path: location.pathname, y: window.pageYOffset, t: Date.now(),
                lists: lists().map(function (l) { return l.scrollTop; })
            }));
        } catch (err) { /* storage unavailable: just behave normally */ }
    });

    var saved = null;
    try {
        var raw = sessionStorage.getItem(KEY);
        sessionStorage.removeItem(KEY);
        saved = raw ? JSON.parse(raw) : null;
    } catch (err) { saved = null; }
    if (!saved || saved.path !== location.pathname || Date.now() - saved.t > 15000) return;

    // The page can still be growing (tables, fonts) when the script first runs, so keep trying
    // for a moment until it is tall enough, and stop at once if the person scrolls themselves.
    var finished = false, tries = 0;
    ["wheel", "touchstart", "keydown", "mousedown"].forEach(function (name) {
        window.addEventListener(name, function () { finished = true; }, { passive: true, once: true });
    });
    function restore() {
        if (finished) return;
        var boxes = lists();
        (saved.lists || []).forEach(function (top, i) { if (boxes[i]) boxes[i].scrollTop = top; });
        var maxY = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
        window.scrollTo({ top: Math.min(saved.y, maxY), left: 0, behavior: "instant" });
        if (maxY >= saved.y - 1 || ++tries > 40) { finished = true; return; }
        setTimeout(restore, 50);
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", restore);
    else restore();
})();
