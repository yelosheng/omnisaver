// ==UserScript==
// @name         Twitter/X, YouTube & XiaoHongShu Saver
// @namespace    https://github.com/yelosheng/twitter-saver
// @version      3.15
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

    const ICON_DATA_URL = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA0MDAgNDUwIiB3aWR0aD0iNDAwIiBoZWlnaHQ9IjQ1MCI+CiAgPGRlZnM+CiAgICA8ZmlsdGVyIGlkPSJkcm9wLXNoYWRvdyIgeD0iLTIwJSIgeT0iLTIwJSIgd2lkdGg9IjE1MCUiIGhlaWdodD0iMTUwJSI+CiAgICAgIDxmZURyb3BTaGFkb3cgZHg9IjgiIGR5PSIxMiIgc3RkRGV2aWF0aW9uPSIxMCIgZmxvb2QtY29sb3I9IiMwMDAwMDAiIGZsb29kLW9wYWNpdHk9IjAuNiIvPgogICAgPC9maWx0ZXI+CgogICAgPGxpbmVhckdyYWRpZW50IGlkPSJwbGFzdGljLWJvZHkiIHgxPSIwJSIgeTE9IjAlIiB4Mj0iMTAwJSIgeTI9IjEwMCUiPgogICAgICA8c3RvcCBvZmZzZXQ9IjAlIiBzdG9wLWNvbG9yPSIjNGE0YTRhIiAvPgogICAgICA8c3RvcCBvZmZzZXQ9IjUwJSIgc3RvcC1jb2xvcj0iIzMzMzMzMyIgLz4KICAgICAgPHN0b3Agb2Zmc2V0PSIxMDAlIiBzdG9wLWNvbG9yPSIjMWExYTFhIiAvPgogICAgPC9saW5lYXJHcmFkaWVudD4KCiAgICA8bGluZWFyR3JhZGllbnQgaWQ9ImJydXNoZWQtbWV0YWwiIHgxPSIwJSIgeTE9IjAlIiB4Mj0iMTAwJSIgeTI9IjAlIj4KICAgICAgPHN0b3Agb2Zmc2V0PSIwJSIgc3RvcC1jb2xvcj0iI2IwYjBiMCIgLz4KICAgICAgPHN0b3Agb2Zmc2V0PSIxNSUiIHN0b3AtY29sb3I9IiNmZmZmZmYiIC8+CiAgICAgIDxzdG9wIG9mZnNldD0iMzAlIiBzdG9wLWNvbG9yPSIjYTBhMGEwIiAvPgogICAgICA8c3RvcCBvZmZzZXQ9IjUwJSIgc3RvcC1jb2xvcj0iI2UwZTBlMCIgLz4KICAgICAgPHN0b3Agb2Zmc2V0PSI4MCUiIHN0b3AtY29sb3I9IiM4ODg4ODgiIC8+CiAgICAgIDxzdG9wIG9mZnNldD0iMTAwJSIgc3RvcC1jb2xvcj0iI2NjY2NjYyIgLz4KICAgIDwvbGluZWFyR3JhZGllbnQ+CgogICAgPGxpbmVhckdyYWRpZW50IGlkPSJsYWJlbC1iZyIgeDE9IjAlIiB5MT0iMCUiIHgyPSIwJSIgeTI9IjEwMCUiPgogICAgICA8c3RvcCBvZmZzZXQ9IjAlIiBzdG9wLWNvbG9yPSIjZmRmZGZkIiAvPgogICAgICA8c3RvcCBvZmZzZXQ9IjEwMCUiIHN0b3AtY29sb3I9IiNlNmU2ZTYiIC8+CiAgICA8L2xpbmVhckdyYWRpZW50PgogICAgCiAgICA8bGluZWFyR3JhZGllbnQgaWQ9ImxhYmVsLWhlYWRlciIgeDE9IjAlIiB5MT0iMCUiIHgyPSIxMDAlIiB5Mj0iMCUiPgogICAgICA8c3RvcCBvZmZzZXQ9IjAlIiBzdG9wLWNvbG9yPSIjMWUzYzcyIiAvPgogICAgICA8c3RvcCBvZmZzZXQ9IjEwMCUiIHN0b3AtY29sb3I9IiMyYTUyOTgiIC8+CiAgICA8L2xpbmVhckdyYWRpZW50PgogIDwvZGVmcz4KCiAgPGcgdHJhbnNmb3JtPSJ0cmFuc2xhdGUoNTAsIDQwKSIgZmlsdGVyPSJ1cmwoI2Ryb3Atc2hhZG93KSI+CiAgICAKICAgIDxyZWN0IHg9IjAiIHk9IjAiIHdpZHRoPSIzMDAiIGhlaWdodD0iMzIwIiByeD0iMTIiIGZpbGw9InVybCgjcGxhc3RpYy1ib2R5KSIgLz4KICAgIAogICAgPHBhdGggZD0iTSAxMiAxIEwgMjg4IDEgQSAxMSAxMSAwIDAgMSAyOTkgMTIiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzY2NjY2NiIgc3Ryb2tlLXdpZHRoPSIyIiAvPgogICAgPHBhdGggZD0iTSAxIDI4OCBMIDEgMTIgQSAxMSAxMSAwIDAgMSAxMiAxIiBmaWxsPSJub25lIiBzdHJva2U9IiM1NTU1NTUiIHN0cm9rZS13aWR0aD0iMiIgLz4KICAgIDxwYXRoIGQ9Ik0gMjk5IDI4OCBMIDI5OSAxMiIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjMTExMTExIiBzdHJva2Utd2lkdGg9IjIiIC8+CiAgICA8cGF0aCBkPSJNIDEyIDMxOSBMIDI4OCAzMTkiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzBhMGEwYSIgc3Ryb2tlLXdpZHRoPSIyIiAvPgoKICAgIDxyZWN0IHg9IjMwIiB5PSIwIiB3aWR0aD0iMTYwIiBoZWlnaHQ9IjkwIiBmaWxsPSIjMjIyMjIyIiAvPgogICAgPHJlY3QgeD0iMzAiIHk9IjAiIHdpZHRoPSIxNjAiIGhlaWdodD0iMyIgZmlsbD0iIzExMTExMSIgLz4gPHJlY3QgeD0iNTAiIHk9IjAiIHdpZHRoPSIxNTAiIGhlaWdodD0iOTAiIHJ4PSIyIiBmaWxsPSJ1cmwoI2JydXNoZWQtbWV0YWwpIiAvPgogICAgPHJlY3QgeD0iNTAiIHk9Ijg4IiB3aWR0aD0iMTUwIiBoZWlnaHQ9IjIiIGZpbGw9IiM1NTU1NTUiIC8+CiAgICA8cmVjdCB4PSI1MCIgeT0iMCIgd2lkdGg9IjEuNSIgaGVpZ2h0PSI5MCIgZmlsbD0iI2ZmZmZmZiIgLz4KICAgIDxyZWN0IHg9IjE1NSIgeT0iMjAiIHdpZHRoPSIyMCIgaGVpZ2h0PSI1MCIgcng9IjMiIGZpbGw9IiM2NjY2NjYiIC8+CiAgICA8cmVjdCB4PSIxNTYiIHk9IjIxIiB3aWR0aD0iMTgiIGhlaWdodD0iNDgiIHJ4PSIyIiBmaWxsPSIjMzMzMzMzIiAvPgogICAgPHJlY3QgeD0iNzUiIHk9IjEwIiB3aWR0aD0iMjUiIGhlaWdodD0iNDAiIHJ4PSIyIiBmaWxsPSIjMWExYTFhIiAvPgoKCiAgICA8cG9seWdvbiBwb2ludHM9IjE4LDE1IDI2LDI3IDEwLDI3IiBmaWxsPSIjMjIyMjIyIiAvPgogICAgPHBvbHlnb24gcG9pbnRzPSIxOCwxNiAyNSwyNiAxMSwyNiIgZmlsbD0iIzFhMWExYSIgLz4KCiAgICA8ZyB0cmFuc2Zvcm09InRyYW5zbGF0ZSgyNjAsIDMwKSI+CiAgICAgIDx0ZXh0IHg9IjAiIHk9IjAiIGZvbnQtZmFtaWx5PSJBcmlhbCwgSGVsdmV0aWNhLCBzYW5zLXNlcmlmIiBmb250LXdlaWdodD0iOTAwIiBmb250LXNpemU9IjIwIiBmaWxsPSIjMWYxZjFmIj5IRDwvdGV4dD4KICAgICAgPHRleHQgeD0iMC41IiB5PSIxLjUiIGZvbnQtZmFtaWx5PSJBcmlhbCwgSGVsdmV0aWNhLCBzYW5zLXNlcmlmIiBmb250LXdlaWdodD0iOTAwIiBmb250LXNpemU9IjIwIiBmaWxsPSJub25lIiBzdHJva2U9IiM1YTVhNWEiIHN0cm9rZS13aWR0aD0iMC41Ij5IRDwvdGV4dD4KICAgIDwvZz4KCiAgICA8cmVjdCB4PSIyNjAiIHk9IjI4NSIgd2lkdGg9IjIwIiBoZWlnaHQ9IjIwIiByeD0iMyIgZmlsbD0iIzAwMDAwMCIgLz4KICAgIDxyZWN0IHg9IjI2MCIgeT0iMjg1IiB3aWR0aD0iMjAiIGhlaWdodD0iMiIgZmlsbD0iIzExMTExMSIgLz4KCiAgICA8cmVjdCB4PSIyMCIgeT0iMjg1IiB3aWR0aD0iMjAiIGhlaWdodD0iMjAiIHJ4PSIzIiBmaWxsPSIjMDAwMDAwIiAvPgogICAgPHJlY3QgeD0iMjIiIHk9IjI4NyIgd2lkdGg9IjE2IiBoZWlnaHQ9IjgiIHJ4PSIxLjUiIGZpbGw9IiNjMDJhMmEiIC8+CiAgICA8cmVjdCB4PSIyMiIgeT0iMjg3IiB3aWR0aD0iMTYiIGhlaWdodD0iMiIgZmlsbD0iI2ZmNTU1NSIgLz4gPHJlY3QgeD0iMjUiIHk9IjE0NSIgd2lkdGg9IjI1MCIgaGVpZ2h0PSIxNzUiIHJ4PSI4IiBmaWxsPSIjMTExMTExIiAvPgogICAgCiAgICA8cmVjdCB4PSIyOCIgeT0iMTQ4IiB3aWR0aD0iMjQ0IiBoZWlnaHQ9IjE2OSIgcng9IjYiIGZpbGw9InVybCgjbGFiZWwtYmcpIiAvPgogICAgCiAgICA8cGF0aCBkPSJNIDI4IDE1NCBBIDYgNiAwIDAgMSAzNCAxNDggTCAyNjYgMTQ4IEEgNiA2IDAgMCAxIDI3MiAxNTQgTCAyNzIgMTg1IEwgMjggMTg1IFoiIGZpbGw9InVybCgjbGFiZWwtaGVhZGVyKSIgLz4KCiAgICA8dGV4dCB4PSIzOCIgeT0iMTczIiBmb250LWZhbWlseT0iJ1RyZWJ1Y2hldCBNUycsIEFyaWFsLCBzYW5zLXNlcmlmIiBmb250LXdlaWdodD0iYm9sZCIgZm9udC1zaXplPSIyMiIgZmlsbD0iI2ZmZmZmZiIgbGV0dGVyLXNwYWNpbmc9IjEiPjJIRDwvdGV4dD4KICAgIAogICAgPHRleHQgeD0iMTgwIiB5PSIxNzMiIGZvbnQtZmFtaWx5PSJJbXBhY3QsIHNhbnMtc2VyaWYiIGZvbnQtd2VpZ2h0PSJub3JtYWwiIGZvbnQtc2l6ZT0iMjQiIGZpbGw9IiNmZmZmZmYiIGZvbnQtc3R5bGU9Iml0YWxpYyI+VmVydGV4PC90ZXh0PgogICAgPHRleHQgeD0iMjUyIiB5PSIxNjAiIGZvbnQtZmFtaWx5PSJBcmlhbCwgc2Fucy1zZXJpZiIgZm9udC1zaXplPSI4IiBmaWxsPSIjZmZmZmZmIj7CrjwvdGV4dD4KCiAgICA8bGluZSB4MT0iNDUiIHkxPSIyMTAiIHgyPSIyNTUiIHkyPSIyMTAiIHN0cm9rZT0iI2IwYzRkZSIgc3Ryb2tlLXdpZHRoPSIyIiAvPgogICAgPGxpbmUgeDE9IjQ1IiB5MT0iMjQwIiB4Mj0iMjU1IiB5Mj0iMjQwIiBzdHJva2U9IiNiMGM0ZGUiIHN0cm9rZS13aWR0aD0iMiIgLz4KICAgIDxsaW5lIHgxPSI0NSIgeTE9IjI3MCIgeDI9IjI1NSIgeTI9IjI3MCIgc3Ryb2tlPSIjYjBjNGRlIiBzdHJva2Utd2lkdGg9IjIiIC8+CgogICAgPHRleHQgeD0iNDUiIHk9IjMwMCIgZm9udC1mYW1pbHk9Im1vbm9zcGFjZSIgZm9udC13ZWlnaHQ9ImJvbGQiIGZvbnQtc2l6ZT0iMTEiIGZpbGw9IiM2NjY2NjYiPklCTSBGT1JNQVRURUQ8L3RleHQ+CiAgICA8dGV4dCB4PSIxOTAiIHk9IjMwMCIgZm9udC1mYW1pbHk9Im1vbm9zcGFjZSIgZm9udC13ZWlnaHQ9ImJvbGQiIGZvbnQtc2l6ZT0iMTEiIGZpbGw9IiM2NjY2NjYiPjEuNDQgTUI8L3RleHQ+CgogICAgPHJlY3QgeD0iMjgiIHk9IjMxMiIgd2lkdGg9IjI0NCIgaGVpZ2h0PSI1IiBmaWxsPSIjYzAyYTJhIiAvPgogICAgPHJlY3QgeD0iMjgiIHk9IjMxMiIgd2lkdGg9IjUwIiBoZWlnaHQ9IjUiIGZpbGw9IiNmZmFhMDAiIC8+CiAgPC9nPgo8L3N2Zz4K';


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
                /* Video page overlay button — top-left corner of #movie_player */
                .yt-saver-overlay-btn {
                    position: absolute;
                    top: 10px;
                    left: 10px;
                    z-index: 1000;
                    width: 36px;
                    height: 36px;
                    border-radius: 50%;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    opacity: 0;
                    transition: opacity 0.15s;
                    background: rgba(255,255,255,0.15);
                    border: 1.5px solid rgba(255,255,255,0.6);
                    box-sizing: border-box;
                    backdrop-filter: blur(2px);
                }
                #movie_player:hover .yt-saver-overlay-btn {
                    opacity: 1;
                }
                .yt-saver-overlay-btn:hover {
                    background: rgba(255,255,255,0.3) !important;
                    border-color: rgba(255,255,255,0.95) !important;
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

    function isYouTubeHomePage() {
        return window.location.hostname === 'www.youtube.com' &&
            (window.location.pathname === '/' || window.location.pathname === '');
    }

    function createYtThumbnailBtn(videoUrl) {
        const btn = document.createElement('div');
        btn.className = 'yt-saver-thumb-btn';
        btn.title = '保存视频';
        btn.style.cssText = `
            position: absolute; top: 6px; left: 6px; z-index: 10;
            width: 32px; height: 32px; border-radius: 50%;
            cursor: pointer; padding: 0;
            display: flex; align-items: center; justify-content: center;
            opacity: 0; transition: opacity 0.15s;
            pointer-events: auto;
            background: rgba(255,255,255,0.15);
            border: 1.5px solid rgba(255,255,255,0.6);
            box-sizing: border-box;
            backdrop-filter: blur(2px);
        `;
        const img = document.createElement('img');
        img.src = ICON_DATA_URL;
        img.style.cssText = 'width:17px;height:17px;display:block;pointer-events:none;opacity:0.9;transition:transform 0.4s ease-out;';
        btn.appendChild(img);

        btn.addEventListener('mouseenter', () => {
            btn.style.background = 'rgba(255,255,255,0.3)';
            btn.style.borderColor = 'rgba(255,255,255,0.9)';
        });
        btn.addEventListener('mouseleave', () => {
            btn.style.background = 'rgba(255,255,255,0.15)';
            btn.style.borderColor = 'rgba(255,255,255,0.6)';
        });

        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            img.style.transition = 'none';
            img.style.transform = 'rotate(0deg)';
            requestAnimationFrame(() => {
                img.style.transition = 'transform 0.4s ease-out';
                img.style.transform = 'rotate(360deg)';
                setTimeout(() => {
                    img.style.transition = 'none';
                    img.style.transform = 'rotate(0deg)';
                }, 420);
            });
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

            const thumbLink = card.querySelector('a#thumbnail') ||
                              card.querySelector('a[href*="/watch?v="]') ||
                              card.querySelector('a[href*="/shorts/"]');
            if (!thumbLink) return;

            if (getComputedStyle(thumbLink).position === 'static') {
                thumbLink.style.position = 'relative';
            }

            const btn = createYtThumbnailBtn(videoUrl);
            thumbLink.appendChild(btn);

            injected++;
        });
        if (injected > 0) console.log(`[YT-SAVER] injected ${injected} thumbnail buttons`);
    }

    // ── Video page overlay button (top-left corner of player) ────────────────

    function createYtOverlayBtn(videoUrl) {
        const btn = document.createElement('div');
        btn.id = 'yt-saver-overlay-btn';
        btn.className = 'yt-saver-overlay-btn';
        btn.title = '保存视频';

        const img = document.createElement('img');
        img.src = ICON_DATA_URL;
        img.style.cssText = 'width:20px;height:20px;display:block;pointer-events:none;opacity:0.9;transition:transform 0.4s ease-out;';
        btn.appendChild(img);

        ['mousedown','mouseup','keydown','keyup'].forEach(evt =>
            btn.addEventListener(evt, e => e.stopPropagation())
        );
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            img.style.transition = 'none';
            img.style.transform = 'rotate(0deg)';
            requestAnimationFrame(() => {
                img.style.transition = 'transform 0.4s ease-out';
                img.style.transform = 'rotate(360deg)';
                setTimeout(() => { img.style.transition = 'none'; img.style.transform = 'rotate(0deg)'; }, 420);
            });
            submitYouTubeToAPI(videoUrl);
        });
        return btn;
    }

    function injectYtOverlayBtn() {
        if (!isYouTubeVideoPage()) return;
        if (document.getElementById('yt-saver-overlay-btn')) return;

        const player = document.getElementById('movie_player');
        if (!player) return;

        const url = getYouTubeVideoUrl();
        if (!url) return;

        if (getComputedStyle(player).position === 'static') {
            player.style.position = 'relative';
        }

        player.appendChild(createYtOverlayBtn(url));
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

        // Bounding-rect hover tracker — immune to shadow DOM, overlays, and CSS cascade issues.
        // Checks mouse coordinates directly against each thumbnail link's bounding box.
        document.addEventListener('mousemove', (e) => {
            document.querySelectorAll('.yt-saver-thumb-btn').forEach(btn => {
                const link = btn.parentElement;
                if (!link || !link.isConnected) return;
                const r = link.getBoundingClientRect();
                btn.style.opacity = (
                    e.clientX >= r.left && e.clientX <= r.right &&
                    e.clientY >= r.top  && e.clientY <= r.bottom
                ) ? '1' : '0';
            });
        }, {passive: true});

        hookYtCardMenus();

        // Poll as primary driver
        setInterval(injectYtOverlayBtn, 1000);
        setInterval(injectYtThumbnailButtons, 1500);

        // MutationObserver on ytd-app for faster reaction
        const initObs = setInterval(() => {
            const app = document.querySelector('ytd-app');
            if (!app) return;
            clearInterval(initObs);
            const obs = new MutationObserver(() => {
                if (!document.getElementById('yt-saver-overlay-btn')) injectYtOverlayBtn();
                injectYtThumbnailButtons();
            });
            obs.observe(app, { childList: true, subtree: true });
            injectYtOverlayBtn();
            injectYtThumbnailButtons();
        }, 500);

        // SPA navigation
        window.addEventListener('yt-navigate-finish', () => {
            document.getElementById('yt-saver-overlay-btn')?.remove();
            setTimeout(injectYtOverlayBtn, 500);
            setTimeout(injectYtOverlayBtn, 1500);
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
