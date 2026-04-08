// ==UserScript==
// @name         Twitter/X, YouTube & XiaoHongShu Saver
// @namespace    https://github.com/yelosheng/twitter-saver
// @version      3.9
// @description  在 Twitter/X 推文、YouTube 视频和小红书笔记页面添加保存按钮，一键归档到本地服务
// @author       yelosheng
// @match        https://twitter.com/*
// @match        https://x.com/*
// @match        https://www.youtube.com/*
// @match        https://www.xiaohongshu.com/*
// @match        https://mp.weixin.qq.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @connect      *
// ==/UserScript==

(function() {
    'use strict';

    const DEFAULT_BACKEND = 'http://localhost:6201';

    function getBackendUrl() {
        return GM_getValue('backendUrl', DEFAULT_BACKEND).replace(/\/$/, '');
    }

    function getApiKey() {
        return GM_getValue('apiKey', '');
    }

    function buildAuthHeaders() {
        const key = getApiKey();
        const headers = { 'Content-Type': 'application/json' };
        if (key) headers['Authorization'] = `Bearer ${key}`;
        return headers;
    }

    GM_registerMenuCommand('🔑 设置 API Key', function() {
        const current = getApiKey();
        const newKey = prompt('请输入后端 API Key（在 Settings 页面生成）', current);
        if (newKey !== null) {
            GM_setValue('apiKey', newKey.trim());
            alert(newKey.trim() ? 'API Key 已保存' : 'API Key 已清除');
        }
    });

    GM_registerMenuCommand('⚙️ 设置后端地址', function() {
        const current = getBackendUrl();
        const newUrl = prompt('请输入后端服务地址（例：http://localhost:6201）', current);
        if (newUrl !== null && newUrl.trim()) {
            GM_setValue('backendUrl', newUrl.trim().replace(/\/$/, ''));
            alert('设置已保存，刷新页面生效');
        }
    });

    const ICON_DATA_URL = 'data:image/png;base64,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';

    function getSaveIconHtml() {
        return `
        <div class="save-icon-circle" style="
            display: flex;
            align-items: center;
            justify-content: center;
            width: 25px;
            height: 25px;
            min-width: 25px;
            min-height: 25px;
            flex-shrink: 0;
            border-radius: 50%;
            border: 1px solid rgba(29, 155, 240, 0.4);
            box-sizing: border-box;
            transition: border-color 0.2s ease-out;
        ">
            <img src="${ICON_DATA_URL}"
                 alt="Save"
                 class="save-icon-img"
                 style="
                    width: 17px;
                    height: 17px;
                    display: block;
                    pointer-events: none;
                    opacity: 0.7;
                 ">
        </div>
    `;
    }

    function injectRotateCss() {
        if (!document.querySelector('#save-button-rotate-style')) {
            const style = document.createElement('style');
            style.id = 'save-button-rotate-style';
            style.textContent = `
                .save-icon-img.rotate-effect {
                    transform: rotate(360deg);
                    transition: transform 0.4s ease-out;
                }
            `;
            document.head.appendChild(style);
        }
    }

    function createSaveButton(tweetElement) {
        const saveButton = document.createElement('div');
        saveButton.style.cssText = 'display: flex; align-items: center; align-self: center;';

        saveButton.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: center; cursor: pointer; padding: 8px; border-radius: 50%; transition: all 0.2s; width: 35px; height: 35px; margin: 0 4px;"
                 class="save-button" title="保存推文">
                ${getSaveIconHtml()}
            </div>
        `;

        const buttonElement = saveButton.querySelector('.save-button');
        const iconImage = saveButton.querySelector('.save-icon-img');
        const iconCircle = saveButton.querySelector('.save-icon-circle');

        buttonElement.addEventListener('mouseenter', function() {
            this.style.backgroundColor = 'rgba(29, 155, 240, 0.1)';
            if (iconImage) iconImage.style.opacity = '1';
            if (iconCircle) iconCircle.style.borderColor = 'rgba(29, 155, 240, 0.8)';
        });

        buttonElement.addEventListener('mouseleave', function() {
            this.style.backgroundColor = 'transparent';
            if (iconImage) iconImage.style.opacity = '0.7';
            if (iconCircle) iconCircle.style.borderColor = 'rgba(29, 155, 240, 0.4)';
        });

        buttonElement.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();

            if (iconImage) {
                iconImage.classList.remove('rotate-effect');
                void iconImage.offsetWidth;
                iconImage.classList.add('rotate-effect');
                setTimeout(() => {
                    iconImage.classList.remove('rotate-effect');
                }, 400);
            }

            this.style.transform = 'scale(0.8)';
            setTimeout(() => {
                this.style.transform = 'scale(1)';
            }, 150);

            const tweetUrl = getTweetUrl(tweetElement);

            if (tweetUrl) {
                submitTweetToAPI(tweetUrl);
            } else {
                showToast('无法获取推文URL', 'error');
            }
        });

        return saveButton;
    }

    function getTweetUrl(tweetElement) {
        try {
            const timeElement = tweetElement.querySelector('time');
            if (timeElement && timeElement.parentElement && timeElement.parentElement.href) {
                return timeElement.parentElement.href;
            }
            const statusLinks = tweetElement.querySelectorAll('a[href*="/status/"]');
            if (statusLinks.length > 0) {
                return statusLinks[0].href;
            }
            const article = tweetElement.closest('article');
            if (article) {
                const links = article.querySelectorAll('a[href*="/status/"]');
                if (links.length > 0) {
                    return links[0].href;
                }
            }
            const currentUrl = window.location.href;
            if (currentUrl.includes('/status/')) {
                return currentUrl.split('?')[0];
            }
            return null;
        } catch (error) {
            console.error('获取推文URL时出错:', error);
            return null;
        }
    }

    function showToast(message, type = 'info') {
        const existingToast = document.querySelector('.save-toast');
        if (existingToast) existingToast.remove();

        const toast = document.createElement('div');
        toast.className = 'save-toast';
        const bgColor = type === 'success' ? '#4CAF50' : type === 'error' ? '#f44336' : type === 'warning' ? '#ff9800' : '#2196F3';

        toast.style.cssText = `
            position: fixed; top: 20px; right: 20px; background: ${bgColor}; color: white;
            padding: 12px 20px; border-radius: 8px; font-size: 14px; font-weight: 500;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3); z-index: 10000; max-width: 300px;
            animation: slideIn 0.3s ease-out; display: flex; align-items: center;
        `;

        if (!document.querySelector('#toast-style')) {
            const style = document.createElement('style');
            style.id = 'toast-style';
            style.textContent = `@keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } } @keyframes slideOut { from { transform: translateX(0); opacity: 1; } to { transform: translateX(100%); opacity: 0; } }`;
            document.head.appendChild(style);
        }

        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease-in';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    // ── YouTube ───────────────────────────────────────────────────────────────

    function isYouTubeVideoPage() {
        return window.location.hostname === 'www.youtube.com' &&
            (window.location.pathname === '/watch' ||
             window.location.pathname.startsWith('/shorts/'));
    }

    function getYouTubeVideoUrl() {
        if (window.location.pathname === '/watch') {
            const v = new URLSearchParams(window.location.search).get('v');
            return v ? `https://www.youtube.com/watch?v=${v}` : null;
        }
        if (window.location.pathname.startsWith('/shorts/')) {
            const id = window.location.pathname.split('/shorts/')[1].split(/[/?]/)[0];
            return id ? `https://www.youtube.com/watch?v=${id}` : null;
        }
        return null;
    }

    function submitYouTubeToAPI(url) {
        const apiUrl = `${getBackendUrl()}/api/submit`;
        showToast('正在保存视频...', 'info');
        GM_xmlhttpRequest({
            method: 'POST',
            url: apiUrl,
            headers: buildAuthHeaders(),
            data: JSON.stringify({ url }),
            onload: function(response) {
                try {
                    const result = JSON.parse(response.responseText);
                    if (result.success) {
                        result.duplicate
                            ? showToast(`视频已存在 (状态: ${result.status})`, 'warning')
                            : showToast(`保存任务已提交 (ID: ${result.task_id})`, 'success');
                    } else {
                        showToast(`保存失败: ${result.message || result.error}`, 'error');
                    }
                } catch (e) {
                    showToast('响应解析失败', 'error');
                }
            },
            onerror: () => showToast('网络请求失败，请检查后端地址设置', 'error'),
            ontimeout: () => showToast('请求超时', 'error'),
            timeout: 10000
        });
    }

    function createYtSaveControl() {
        const btn = document.createElement('button');
        btn.id = 'yt-saver-btn';
        btn.className = 'yt-saver-btn';
        btn.title = '保存视频';
        btn.style.cssText = `
            background-color: var(--yt-spec-badge-chip-background, rgba(0,0,0,0.05));
            color: var(--yt-spec-text-primary, #0f0f0f);
            border: none; border-radius: 18px; cursor: pointer;
            height: 36px; padding: 0 16px;
            display: inline-flex; align-items: center; gap: 6px;
            font-size: 14px; font-family: "Roboto","Arial",sans-serif; font-weight: 500;
            margin-left: 8px; vertical-align: middle;
            transition: background-color 0.1s;
        `;
        const img = document.createElement('img');
        img.src = ICON_DATA_URL;
        img.style.cssText = 'width:16px;height:16px;vertical-align:middle;opacity:0.85;';
        btn.appendChild(img);
        btn.appendChild(document.createTextNode(' 保存'));

        ['click','mousedown','mouseup','keydown','keyup'].forEach(evt =>
            btn.addEventListener(evt, e => e.stopPropagation())
        );
        btn.onmouseover = () => btn.style.backgroundColor = 'var(--yt-spec-badge-chip-background-hover, rgba(0,0,0,0.1))';
        btn.onmouseout  = () => btn.style.backgroundColor = 'var(--yt-spec-badge-chip-background, rgba(0,0,0,0.05))';
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const url = getYouTubeVideoUrl();
            if (url) submitYouTubeToAPI(url);
            else showToast('无法获取视频URL', 'error');
        });
        return btn;
    }

    function isYouTubeHomePage() {
        return window.location.hostname === 'www.youtube.com' &&
            (window.location.pathname === '/' || window.location.pathname === '');
    }

    function createYtThumbnailBtn(videoUrl) {
        const btn = document.createElement('button');
        btn.className = 'yt-saver-thumb-btn';
        btn.title = '保存视频';
        btn.style.cssText = `
            position: absolute; top: 6px; left: 6px; z-index: 10;
            width: 32px; height: 32px; border-radius: 50%;
            border: none; cursor: pointer; padding: 0;
            background: rgba(0,0,0,0.6);
            display: flex; align-items: center; justify-content: center;
            opacity: 1; transition: opacity 0.15s;
            pointer-events: auto;
        `;
        const img = document.createElement('img');
        img.src = ICON_DATA_URL;
        img.style.cssText = 'width:18px;height:18px;display:block;';
        btn.appendChild(img);
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            submitYouTubeToAPI(videoUrl);
        });
        ['mousedown','mouseup','keydown','keyup'].forEach(evt =>
            btn.addEventListener(evt, e => e.stopPropagation())
        );
        return btn;
    }

    function extractVideoUrlFromCard(card) {
        // Old format: a#thumbnail with /watch?v= URL
        let link = card.querySelector('a#thumbnail[href*="/watch?v="]');
        if (link) {
            const m = link.getAttribute('href').match(/[?&]v=([^&]+)/);
            if (m) return `https://www.youtube.com/watch?v=${m[1]}`;
        }
        // Any <a> with /watch?v=
        link = card.querySelector('a[href*="/watch?v="]');
        if (link) {
            const m = link.getAttribute('href').match(/[?&]v=([^&]+)/);
            if (m) return `https://www.youtube.com/watch?v=${m[1]}`;
        }
        // Shorts link
        link = card.querySelector('a[href*="/shorts/"]');
        if (link) {
            const m = link.getAttribute('href').match(/\/shorts\/([^?&/]+)/);
            if (m) return `https://www.youtube.com/watch?v=${m[1]}`;
        }
        return null;
    }

    function injectYtThumbnailButtons() {
        let injected = 0;
        document.querySelectorAll('ytd-rich-item-renderer, ytd-video-renderer').forEach((card) => {
            if (card.querySelector('.yt-saver-thumb-btn')) return;

            const videoUrl = extractVideoUrlFromCard(card);
            if (!videoUrl) return;

            // Find the thumbnail container specifically (not the whole card)
            const container = card.querySelector('ytd-thumbnail') ||                    // old format
                              card.querySelector('yt-thumbnail-view-model') ||           // new lockup format
                              card.querySelector('[class*="thumbnail"]') ||              // any thumbnail wrapper
                              card.querySelector('#dismissible') ||
                              card;
            if (getComputedStyle(container).position === 'static') container.style.position = 'relative';

            const btn = createYtThumbnailBtn(videoUrl);
            btn.style.opacity = '0';
            container.appendChild(btn);
            container.addEventListener('mouseenter', () => btn.style.opacity = '1');
            container.addEventListener('mouseleave', () => btn.style.opacity = '0');
            injected++;
        });
        if (injected > 0) console.log(`[YT-SAVER] injected ${injected} thumbnail buttons`);
    }

    function injectYtButton() {
        if (!isYouTubeVideoPage()) return;
        if (document.getElementById('yt-saver-btn')) return;

        const targets = [
            document.querySelector('ytd-watch-metadata #top-level-buttons-computed'),
            document.querySelector('ytd-watch-metadata #flexible-item-buttons'),
            document.querySelector('#top-level-buttons-computed'),
            document.querySelector('ytd-watch-metadata #actions'),
        ];
        const target = targets.find(t => t && t.offsetParent !== null);
        if (!target) return;

        target.appendChild(createYtSaveControl());
    }

    // ── 3-dot menu injection ──────────────────────────────────────────────────
    let _menuVideoUrl = null;

    function hookYtCardMenus() {
        // Capture video URL when any 3-dot menu button is clicked on a card
        document.addEventListener('click', (e) => {
            // Match any button/icon that could be a 3-dot menu trigger
            const menuBtn = e.target.closest('button, yt-icon-button, yt-button-shape, [class*="menu"]');
            if (!menuBtn) return;
            const card = menuBtn.closest('ytd-rich-item-renderer, ytd-video-renderer, ytd-compact-video-renderer');
            if (!card) return;
            const videoUrl = extractVideoUrlFromCard(card);
            if (videoUrl) _menuVideoUrl = videoUrl;
        }, true);

        // Watch for the popup listbox to appear and inject our item
        const menuObs = new MutationObserver(() => {
            const listbox = document.querySelector('ytd-popup-container tp-yt-paper-listbox');
            if (!listbox || listbox.querySelector('.yt-saver-menu-item') || !_menuVideoUrl) return;

            const videoUrl = _menuVideoUrl;

            const item = document.createElement('tp-yt-paper-item');
            item.className = 'yt-saver-menu-item style-scope ytd-menu-service-item-renderer';
            item.setAttribute('role', 'option');
            item.style.cssText = 'display:flex;align-items:center;padding:0 16px;min-height:36px;cursor:pointer;';

            const iconWrap = document.createElement('yt-icon');
            iconWrap.style.cssText = 'width:24px;height:24px;margin-right:16px;flex-shrink:0;';
            const iconImg = document.createElement('img');
            iconImg.src = ICON_DATA_URL;
            iconImg.style.cssText = 'width:18px;height:18px;opacity:0.7;';
            iconWrap.appendChild(iconImg);

            const label = document.createElement('span');
            label.textContent = '保存视频';
            label.style.cssText = 'font-size:1.4rem;line-height:2rem;font-family:inherit;';

            item.appendChild(iconWrap);
            item.appendChild(label);
            item.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                submitYouTubeToAPI(videoUrl);
                // Close the menu
                document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
            });

            listbox.insertBefore(item, listbox.firstChild);
        });
        menuObs.observe(document.body, { childList: true, subtree: true });
    }

    function initYouTube() {
        if (window.location.hostname !== 'www.youtube.com') return;

        hookYtCardMenus();

        // Poll every second as the primary driver (mirrors working reference script)
        setInterval(injectYtButton, 1000);
        setInterval(injectYtThumbnailButtons, 1500);

        // MutationObserver on ytd-app for faster reaction
        const initObs = setInterval(() => {
            const app = document.querySelector('ytd-app');
            if (!app) return;
            clearInterval(initObs);
            const obs = new MutationObserver(() => {
                if (!document.getElementById('yt-saver-btn')) injectYtButton();
                injectYtThumbnailButtons();
            });
            obs.observe(app, { childList: true, subtree: true });
            injectYtButton();
            injectYtThumbnailButtons();
        }, 500);

        // SPA navigation
        window.addEventListener('yt-navigate-finish', () => {
            document.getElementById('yt-saver-btn')?.remove();
            setTimeout(injectYtButton, 500);
            setTimeout(injectYtButton, 1500);
            setTimeout(injectYtThumbnailButtons, 800);
            setTimeout(injectYtThumbnailButtons, 2000);
        });
    }

    // ── XiaoHongShu (小红书) ─────────────────────────────────────────────────

    function isXhsNotePage() {
        return window.location.hostname === 'www.xiaohongshu.com' &&
            /\/(explore|discovery\/item)\/[a-f0-9]+/.test(window.location.pathname);
    }

    function getXhsNoteUrl() {
        // Return full URL including xsec_token query param
        return window.location.href;
    }

    function submitXhsToAPI(url) {
        const apiUrl = `${getBackendUrl()}/api/submit`;
        showToast('正在保存小红书笔记...', 'info');
        GM_xmlhttpRequest({
            method: 'POST',
            url: apiUrl,
            headers: buildAuthHeaders(),
            data: JSON.stringify({ url }),
            onload: function(response) {
                try {
                    const result = JSON.parse(response.responseText);
                    if (result.success) {
                        result.duplicate
                            ? showToast(`笔记已存在 (状态: ${result.status})`, 'warning')
                            : showToast(`保存成功: ${result.title || ''}`, 'success');
                    } else {
                        showToast(`保存失败: ${result.message || result.error}`, 'error');
                    }
                } catch (e) {
                    showToast('响应解析失败', 'error');
                }
            },
            onerror: () => showToast('网络请求失败，请检查后端地址设置', 'error'),
            ontimeout: () => showToast('请求超时', 'error'),
            timeout: 30000
        });
    }

    // Extract note URL from a feed card element
    function extractXhsNoteUrl(card) {
        // Feed cards have <a> links to /explore/<id> or /discovery/item/<id>
        const link = card.querySelector('a[href*="/explore/"], a[href*="/discovery/item/"]');
        if (link) {
            const href = link.getAttribute('href');
            if (/\/(explore|discovery\/item)\/[a-f0-9]+/.test(href)) {
                // Build full URL
                return href.startsWith('http') ? href : 'https://www.xiaohongshu.com' + href;
            }
        }
        return null;
    }

    function createXhsFeedCardBtn(noteUrl) {
        const btn = document.createElement('div');
        btn.className = 'xhs-saver-card-btn';
        btn.title = '保存笔记';
        btn.style.cssText = `
            position: absolute; top: 6px; right: 6px; z-index: 10;
            width: 32px; height: 32px; border-radius: 50%;
            background: rgba(0,0,0,0.5); cursor: pointer;
            display: flex; align-items: center; justify-content: center;
            opacity: 0; transition: opacity 0.15s;
            pointer-events: auto;
        `;
        const img = document.createElement('img');
        img.src = ICON_DATA_URL;
        img.style.cssText = 'width:18px;height:18px;display:block;';
        btn.appendChild(img);
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            submitXhsToAPI(noteUrl);
        });
        ['mousedown','mouseup'].forEach(evt =>
            btn.addEventListener(evt, e => e.stopPropagation())
        );
        return btn;
    }

    function injectXhsFeedCardButtons() {
        // XHS feed uses section.note-item or similar card wrappers
        // Try multiple selectors for feed cards
        const cardSelectors = [
            'section.note-item',
            'div.note-item',
            '[class*="note-item"]',
            'section[class*="feed"]',
            '.feeds-container section',
            // Waterfall feed cards
            'a[href*="/explore/"]',
        ];

        let cards = [];
        for (const sel of cardSelectors) {
            cards = document.querySelectorAll(sel);
            if (cards.length > 0) break;
        }

        let injected = 0;
        cards.forEach((card) => {
            if (card.querySelector('.xhs-saver-card-btn')) return;

            let noteUrl;
            // If the card itself is an <a> link
            if (card.tagName === 'A') {
                const href = card.getAttribute('href');
                if (/\/(explore|discovery\/item)\/[a-f0-9]+/.test(href)) {
                    noteUrl = href.startsWith('http') ? href : 'https://www.xiaohongshu.com' + href;
                    // Find the cover/image container inside
                    const container = card.querySelector('[class*="cover"], img, [class*="image"]')?.parentElement || card;
                    if (getComputedStyle(container).position === 'static') container.style.position = 'relative';
                    const btn = createXhsFeedCardBtn(noteUrl);
                    container.appendChild(btn);
                    container.addEventListener('mouseenter', () => btn.style.opacity = '1');
                    container.addEventListener('mouseleave', () => btn.style.opacity = '0');
                    injected++;
                }
                return;
            }

            noteUrl = extractXhsNoteUrl(card);
            if (!noteUrl) return;

            // Find cover/thumbnail area
            const cover = card.querySelector('[class*="cover"], [class*="image"], img')?.parentElement || card;
            if (getComputedStyle(cover).position === 'static') cover.style.position = 'relative';
            const btn = createXhsFeedCardBtn(noteUrl);
            cover.appendChild(btn);
            cover.addEventListener('mouseenter', () => btn.style.opacity = '1');
            cover.addEventListener('mouseleave', () => btn.style.opacity = '0');
            injected++;
        });
        if (injected > 0) console.log(`[XHS-SAVER] injected ${injected} card buttons`);
    }

    function injectXhsNoteDetailBtn() {
        // Only on note detail pages
        if (!isXhsNotePage()) {
            // Remove any existing detail button when not on note page
            document.querySelectorAll('.xhs-saver-detail-btn').forEach(b => b.remove());
            return;
        }

        // Already injected for this note
        if (document.querySelector('.xhs-saver-detail-btn')) return;

        // Find the note detail modal/container — try multiple selectors
        const detailSelectors = [
            '.note-detail-mask',
            '#noteContainer',
            '.note-container',
            '[class*="note-detail"]',
            '[class*="noteDetail"]',
            // The modal overlay that contains the note
            '.note-scroller',
            '[class*="detail-container"]',
        ];

        let detailContainer = null;
        for (const sel of detailSelectors) {
            detailContainer = document.querySelector(sel);
            if (detailContainer) break;
        }

        // Fallback: find any overlay/modal with high z-index that appeared
        if (!detailContainer) {
            detailContainer = document.querySelector('[class*="mask"]') ||
                              document.querySelector('[class*="modal"]') ||
                              document.querySelector('[class*="overlay"]');
        }

        const btn = document.createElement('div');
        btn.className = 'xhs-saver-detail-btn';
        btn.title = '保存笔记';
        btn.style.cssText = `
            position: fixed; bottom: 120px; right: 18px; z-index: 999999;
            width: 36px; height: 36px; border-radius: 50%;
            background: white; cursor: pointer;
            display: flex; align-items: center; justify-content: center;
            border: 1px solid rgba(0,0,0,0.08);
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        `;

        // Try to align with the XHS right-side toolbar buttons
        // Find a circular button near the right edge (the "只看图文" or reload button)
        setTimeout(() => {
            const allBtns = document.querySelectorAll('div[class], button[class], span[class]');
            for (const el of allBtns) {
                const r = el.getBoundingClientRect();
                if (r.width >= 30 && r.width <= 44 && r.height >= 30 && r.height <= 44 &&
                    r.right > window.innerWidth - 50 && r.bottom > window.innerHeight - 200) {
                    // Found a toolbar button — align our button with it
                    btn.style.right = (window.innerWidth - r.right + (r.width - 36) / 2) + 'px';
                    btn.style.bottom = (window.innerHeight - r.top + 12) + 'px';
                    console.log('[XHS-SAVER] aligned with toolbar button at', r.right, r.top);
                    break;
                }
            }
        }, 500);

        const img = document.createElement('img');
        img.src = ICON_DATA_URL;
        img.style.cssText = 'width:20px;height:20px;display:block;opacity:0.7;transition:opacity 0.2s;';
        btn.appendChild(img);

        btn.addEventListener('mouseenter', () => {
            btn.style.transform = 'scale(1.08)';
            btn.style.boxShadow = '0 2px 12px rgba(0,0,0,0.15)';
            img.style.opacity = '1';
        });
        btn.addEventListener('mouseleave', () => {
            btn.style.transform = 'scale(1)';
            btn.style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)';
            img.style.opacity = '0.7';
        });
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            submitXhsToAPI(getXhsNoteUrl());
        });

        document.body.appendChild(btn);
        console.log('[XHS-SAVER] note detail save button injected');
    }

    function initXHS() {
        if (window.location.hostname !== 'www.xiaohongshu.com') return;
        console.log('[XHS-SAVER] initializing...');

        // Try feed card buttons
        injectXhsFeedCardButtons();
        // Note detail button
        injectXhsNoteDetailBtn();

        // Watch for SPA navigation and DOM changes
        let lastUrl = location.href;
        const observer = new MutationObserver(() => {
            if (location.href !== lastUrl) {
                lastUrl = location.href;
                console.log('[XHS-SAVER] URL changed:', lastUrl);
                // URL changed
                // Remove old detail button so it re-injects for the new note
                document.querySelectorAll('.xhs-saver-detail-btn').forEach(b => b.remove());
                setTimeout(injectXhsNoteDetailBtn, 300);
                setTimeout(injectXhsNoteDetailBtn, 1000);
            }
            injectXhsFeedCardButtons();
        });
        observer.observe(document.body, { childList: true, subtree: true });

        // Poll for URL changes
        setInterval(() => {
            if (location.href !== lastUrl) {
                lastUrl = location.href;
                // URL changed
                document.querySelectorAll('.xhs-saver-detail-btn').forEach(b => b.remove());
                setTimeout(injectXhsNoteDetailBtn, 300);
            }
            injectXhsNoteDetailBtn();
        }, 1000);

        // Periodic feed card injection
        setInterval(injectXhsFeedCardButtons, 2000);
    }

    // ── WeChat (微信公众号) ───────────────────────────────────────────────────

    function isWechatArticlePage() {
        return window.location.hostname === 'mp.weixin.qq.com' &&
            (window.location.pathname.startsWith('/s') || window.location.search.includes('__biz'));
    }

    function submitWechatToAPI(url) {
        const apiUrl = `${getBackendUrl()}/api/submit`;
        showToast('正在保存微信文章...', 'info');
        GM_xmlhttpRequest({
            method: 'POST',
            url: apiUrl,
            headers: buildAuthHeaders(),
            data: JSON.stringify({ url }),
            onload: function(response) {
                try {
                    const result = JSON.parse(response.responseText);
                    if (result.success) {
                        result.duplicate
                            ? showToast(`文章已存在 (状态: ${result.status})`, 'warning')
                            : showToast(`保存成功`, 'success');
                    } else {
                        showToast(`保存失败: ${result.message || result.error}`, 'error');
                    }
                } catch (e) {
                    showToast('响应解析失败', 'error');
                }
            },
            onerror: () => showToast('网络请求失败，请检查后端地址设置', 'error'),
            ontimeout: () => showToast('请求超时', 'error'),
            timeout: 30000
        });
    }

    function injectWechatBtn() {
        if (!isWechatArticlePage()) return;
        if (document.getElementById('wechat-saver-btn')) return;

        // Wait for meta_content to be available
        const metaContent = document.getElementById('meta_content');
        if (!metaContent) return;

        const btn = document.createElement('span');
        btn.id = 'wechat-saver-btn';
        btn.title = '保存文章';
        btn.style.cssText = `
            display: inline-flex; align-items: center; justify-content: center;
            cursor: pointer; margin-right: 6px;
            vertical-align: middle; line-height: 1;
            width: 22px; height: 22px;
            border-radius: 50%;
            border: 1px solid rgba(29,155,240,0.35);
            transition: border-color 0.2s, background 0.2s;
            position: relative; top: -3px;
        `;

        const img = document.createElement('img');
        img.src = ICON_DATA_URL;
        img.style.cssText = 'width:13px;height:13px;display:block;opacity:0.7;transition:opacity 0.2s,transform 0.4s ease-out;';
        btn.appendChild(img);

        btn.addEventListener('mouseenter', () => {
            btn.style.borderColor = 'rgba(29,155,240,0.8)';
            btn.style.background = 'rgba(29,155,240,0.08)';
            img.style.opacity = '1';
        });
        btn.addEventListener('mouseleave', () => {
            btn.style.borderColor = 'rgba(29,155,240,0.35)';
            btn.style.background = 'transparent';
            img.style.opacity = '0.7';
        });
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            // Spin animation
            img.style.transition = 'transform 0.4s ease-out';
            img.style.transform = 'rotate(360deg)';
            setTimeout(() => {
                img.style.transition = 'none';
                img.style.transform = 'rotate(0deg)';
                setTimeout(() => { img.style.transition = 'opacity 0.2s,transform 0.4s ease-out'; }, 20);
            }, 420);
            submitWechatToAPI(window.location.href);
        });

        // Insert after #copyright_logo if present, otherwise prepend
        const copyrightLogo = document.getElementById('copyright_logo');
        if (copyrightLogo && copyrightLogo.nextSibling) {
            metaContent.insertBefore(btn, copyrightLogo.nextSibling);
        } else {
            metaContent.insertBefore(btn, metaContent.firstChild);
        }

        console.log('[WECHAT-SAVER] save button injected');
    }

    function initWeChat() {
        if (window.location.hostname !== 'mp.weixin.qq.com') return;
        console.log('[WECHAT-SAVER] initializing...');

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => setTimeout(injectWechatBtn, 500));
        } else {
            setTimeout(injectWechatBtn, 500);
        }
        // Retry in case DOM loads slowly
        setTimeout(injectWechatBtn, 1500);
        setTimeout(injectWechatBtn, 3000);
    }

    // ── Twitter/X ─────────────────────────────────────────────────────────────

    function submitTweetToAPI(url) {
        const apiUrl = `${getBackendUrl()}/api/submit`;
        showToast('正在保存推文...', 'info');
        GM_xmlhttpRequest({
            method: 'POST',
            url: apiUrl,
            headers: buildAuthHeaders(),
            data: JSON.stringify({ url }),
            onload: function(response) {
                try {
                    const result = JSON.parse(response.responseText);
                    if (result.success) {
                        result.duplicate
                            ? showToast(`推文已存在 (状态: ${result.status})`, 'warning')
                            : showToast(`保存任务已提交 (ID: ${result.task_id})`, 'success');
                    } else {
                        showToast(`保存失败: ${result.message || result.error}`, 'error');
                    }
                } catch (e) {
                    showToast('响应解析失败', 'error');
                }
            },
            onerror: () => showToast('网络请求失败，请检查后端地址设置', 'error'),
            ontimeout: () => showToast('请求超时', 'error'),
            timeout: 10000
        });
    }

    function addSaveButtonToTweet(tweetElement) {
        if (tweetElement.querySelector('.save-button')) return;

        // Prefer the group that contains the Like button — avoids grabbing the
        // wrong div[role="group"] on the detail page (e.g. the stats/metrics row).
        let actionBar =
            tweetElement.querySelector('div[role="group"]:has(button[data-testid="like"])') ||
            tweetElement.querySelector('div[role="group"]:has(button[aria-label*="Like"])') ||
            tweetElement.querySelector('div[role="group"]');

        if (actionBar) {
            const saveButton = createSaveButton(tweetElement);
            actionBar.appendChild(saveButton);
        }
    }

    function observeTweets() {
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                mutation.addedNodes.forEach(function(node) {
                    if (node.nodeType === 1) {
                        const tweets = node.querySelectorAll('article[data-testid="tweet"]');
                        tweets.forEach(addSaveButtonToTweet);
                        if (node.matches && node.matches('article[data-testid="tweet"]')) {
                            addSaveButtonToTweet(node);
                        }
                    }
                });
            });
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    function init() {
        injectRotateCss();

        if (window.location.hostname === 'www.youtube.com') {
            initYouTube();
            return;
        }

        if (window.location.hostname === 'www.xiaohongshu.com') {
            initXHS();
            return;
        }

        if (window.location.hostname === 'mp.weixin.qq.com') {
            initWeChat();
            return;
        }

        const start = () => {
            const existingTweets = document.querySelectorAll('article[data-testid="tweet"]');
            existingTweets.forEach(addSaveButtonToTweet);
            observeTweets();
        };
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => setTimeout(start, 1000));
        } else {
            setTimeout(start, 1000);
        }
    }

    init();

})();
