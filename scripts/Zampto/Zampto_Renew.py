#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, platform, requests, re, signal
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from seleniumbase import SB

AUTH_URL = "https://dash.zampto.net/auth/login"
DASHBOARD_URL = "https://dash.zampto.net/"
OVERVIEW_URL = "https://dash.zampto.net/"
SERVER_URL = "https://dash.zampto.net/server?id={}"
OUTPUT_DIR = Path("output/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))

def proxy_requests_config() -> Dict[str, str]:
    proxy = os.environ.get("ZAMPTO_PROXY_NODE", "").strip() or os.environ.get("PROXY_URL", "").strip() or os.environ.get("PROXY_SERVER", "").strip()
    return {"http": proxy, "https": proxy} if proxy else {}

class ClickTimeout(Exception):
    pass

def _timeout_handler(signum, frame):
    raise ClickTimeout()

def run_with_timeout(fn, timeout: int, label: str, default=None):
    if not is_linux():
        try:
            return fn()
        except Exception:
            return default

    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout)
    try:
        return fn()
    except ClickTimeout:
        print(f"  [WARN] {label}超时 ({timeout}s)")
        return default
    except Exception:
        return default
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

def safe_execute_script(sb, script: str, timeout: int = 15, default=None):
    return run_with_timeout(lambda: sb.execute_script(script), timeout, "页面脚本执行", default)

def cn_now() -> datetime:
    return datetime.now(CN_TZ)

def calc_expiry_time(renewal_time_str: str, minutes: int = 2880) -> str:
    if not renewal_time_str:
        return "未知"
    try:
        dt = datetime.strptime(renewal_time_str, "%b %d, %Y %I:%M %p")
        expiry = dt.replace(tzinfo=timezone.utc) + timedelta(minutes=minutes)
        return expiry.astimezone(CN_TZ).strftime("%Y年%m月%d日 %H时%M分")
    except:
        return "未知"

def parse_renewal_datetime(time_str: str) -> Optional[datetime]:
    if not time_str:
        return None
    s = time_str.strip()
    s = s.replace(" UTC", "").replace(",", "")
    for fmt in ["%b %d %Y %I:%M %p", "%b %d %Y"]:
        try:
            return datetime.strptime(s, fmt)
        except:
            continue
    return None

def mask(s: str, show: int = 1) -> str:
    if not s: return "***"
    return s[:show] + "***" if len(s) > show else s[0] + "***"

def mask_id(sid: str) -> str:
    return str(sid)[0] + "***" if sid else "****"

def mask_ip(ip: str) -> str:
    if not ip:
        return "***"
    if ":" in ip:
        parts = ip.split(":")
        return f"{parts[0]}:{parts[1]}:***" if len(parts) > 2 else ip[:4] + "***"
    parts = ip.split(".")
    return f"{parts[0]}.{parts[1]}.***.***" if len(parts) == 4 else ip[:3] + "***"

def safe_sid_for_filename(sid: str) -> str:
    s = str(sid)
    if len(s) <= 3:
        return s
    return f"{s[0]}x{s[-2:]}"

def is_linux():
    return platform.system().lower() == "linux"

def setup_display():
    if is_linux() and not os.environ.get("DISPLAY"):
        try:
            from pyvirtualdisplay import Display
            d = Display(visible=False, size=(1920, 1080))
            d.start()
            os.environ["DISPLAY"] = d.new_display_var
            print("[INFO] 虚拟显示已启动")
            return d
        except Exception as e:
            print(f"[ERROR] 虚拟显示失败: {e}")
            sys.exit(1)
    return None

def shot(idx: int, name: str) -> str:
    return str(OUTPUT_DIR / f"acc{idx}-{cn_now().strftime('%H%M%S')}-{name}.png")

def safe_screenshot(sb, path: str):
    try:
        sb.save_screenshot(path)
        print(f"  [INFO] 截图 → {Path(path).name}")
    except Exception as e:
        print(f"  [WARN] 截图失败: {e}")

def notify(ok: bool, username: str, server_id: str, expiry_info: str, img: str = None):
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat: return
    try:
        status = "✅ 续期成功" if ok else "❌ 续期失败"
        text = f"{status}\n\n账号：{username}\n服务器: {server_id}\n到期: {expiry_info}\n\nZampto Auto Renew"
        if img and Path(img).exists():
            with open(img, "rb") as f:
                requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat, "caption": text}, files={"photo": f}, timeout=60)
        else:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text}, timeout=30)
        print("  [INFO] TG推送成功")
    except Exception as e:
        print(f"  [WARN] TG推送失败: {e}")

def notify_login_fail(username: str, img: str = None):
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat: return
    try:
        text = f"❌ 登录失败\n\n账号：{username}\n\nZampto Auto Renew"
        if img and Path(img).exists():
            with open(img, "rb") as f:
                requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat, "caption": text}, files={"photo": f}, timeout=60)
        else:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text}, timeout=30)
    except: pass

def parse_accounts(s: str) -> List[Tuple[str, str]]:
    return [(p[0].strip(), p[1].strip()) for line in s.strip().split('\n')
            if '-----' in line and len(p := line.strip().split('-----', 1)) == 2 and p[0].strip() and p[1].strip()]

def inject_ad_guard(sb):
    try:
        sb.execute_script('''
        (function() {
            if (window._adGuardActive) return;
            window._adGuardActive = true;

            const adSelectors = [
                'ins.adsbygoogle', 'iframe[id^="aswift"]', '#google_ads_iframe',
                'div[id^="google_ads_lib"]', 'iframe[src*="googleads"]',
                '.ad-container', '.ads-wrapper', 'div[class*="ad-box"]',
                'div[id^="ad-"]', '#bottom-anchor-container',
                'div[class*="fixed-bottom"]', '.fc-ab-root', '.ad-placement'
            ];

            const clean = () => {
                adSelectors.forEach(s => {
                    document.querySelectorAll(s).forEach(el => el.remove());
                });
                document.querySelectorAll(
                    '.modal-backdrop, div[class*="backdrop"]'
                ).forEach(el => {
                    if (el.querySelector('#turnstileContainer') ||
                        el.querySelector('#renewForm') ||
                        el.querySelector('iframe[src*="challenges.cloudflare.com"]') ||
                        (el.innerText && el.innerText.includes('Renew Server'))) {
                        return;
                    }
                    el.remove();
                });
                const modal = document.getElementById('renewModal');
                const modalVisible = modal &&
                    window.getComputedStyle(modal).display !== 'none';
                if (!modalVisible && document.body.style.overflow === 'hidden') {
                    document.body.style.setProperty('overflow', 'auto', 'important');
                }
            };

            clean();
            window._adGuardObserver = new MutationObserver(clean);
            window._adGuardObserver.observe(document.documentElement, {
                childList: true, subtree: true
            });
        })();
        ''')
    except: pass

def dismiss_cookie_only(sb) -> bool:
    try:
        result = sb.execute_script('''
            (function() {
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    var text = buttons[i].textContent.trim();
                    if (text === 'Consent' || text === 'Accept' || text === 'Accept All' ||
                        text === 'Do not consent' || text === 'Reject') {
                        buttons[i].click();
                        return text;
                    }
                }
                return '';
            })()
        ''')
        if result:
            print(f"  [INFO] 已关闭Cookie弹窗 ({result})")
            time.sleep(1)
            return True
    except: pass
    return False

# Cloudflare 整页挑战处理
def is_cloudflare_interstitial(sb) -> bool:
    """
    检测是否处于 Cloudflare 整页挑战页面（非嵌入式 Turnstile）
    """
    try:
        # 排除已经显示登录表单的情况（说明是内嵌 Turnstile，不是整页挑战）
        has_login_form = sb.execute_script('''
            return !!(document.querySelector('input#email')
                   || document.querySelector('input[type="email"]')
                   || document.querySelector('button[type="submit"]'));
        ''')
        if has_login_form:
            return False

        # 排除已经登录成功的情况
        current_url = sb.get_current_url()
        if "dash.zampto.net" in current_url:
            return False

        # 检测 CF 整页挑战的强特征
        page_source = sb.get_page_source()
        title = sb.get_title().lower() if sb.get_title() else ""

        strong_indicators = [
            "Just a moment",
            "Verify you are human",
            "Checking your browser",
            "Checking if the site connection is secure",
        ]
        for indicator in strong_indicators:
            if indicator in page_source:
                return True

        if "just a moment" in title or "attention required" in title:
            return True

        # 页面内容极少且包含 CF 域名
        body_text_len = sb.execute_script('''
            return (document.body && document.body.innerText) ? document.body.innerText.trim().length : 0;
        ''')
        if body_text_len < 100 and "challenges.cloudflare.com" in page_source:
            return True

        return False
    except:
        return False

def bypass_cloudflare_interstitial(sb, idx: int, max_attempts: int = 3) -> bool:
    """绕过 Cloudflare 整页挑战，多次尝试点击并通过"""
    print("  [INFO] 检测到 Cloudflare 整页挑战，尝试绕过...")
    safe_screenshot(sb, shot(idx, "cf_interstitial_start"))

    for attempt in range(max_attempts):
        print(f"  [INFO] CF 绕过尝试 {attempt + 1}/{max_attempts}")
        try:
            sb.uc_gui_click_captcha()
            time.sleep(6)
            if not is_cloudflare_interstitial(sb):
                print("  [INFO] Cloudflare 整页挑战已通过")
                return True
        except Exception as e:
            print(f"  [WARN] 尝试 {attempt + 1} 异常: {e}")
        time.sleep(3)

    # 最后尝试刷新页面
    print("  [INFO] 尝试刷新页面重新加载...")
    try:
        sb.uc_open_with_reconnect(AUTH_URL, reconnect_time=10)
        time.sleep(5)
        if not is_cloudflare_interstitial(sb):
            print("  [INFO] 刷新后 Cloudflare 挑战消失")
            return True
    except:
        pass

    print("  [ERROR] Cloudflare 整页挑战绕过失败")
    return False

def check_renew_modal_open(sb) -> Optional[bool]:
    result = safe_execute_script(sb, '''
            (function() {
                var modal = document.getElementById('renewModal');
                if (modal) {
                    var style = window.getComputedStyle(modal);
                    if (style.display !== 'none' && style.visibility !== 'hidden') return true;
                }
                var cards = document.querySelectorAll('[data-slot="card-title"]');
                for (var i = 0; i < cards.length; i++) {
                    if (cards[i].textContent.trim() === 'Renew') return true;
                }
                var iframes = document.querySelectorAll(
                    'iframe[src*="turnstile"], iframe[src*="challenges.cloudflare"]'
                );
                if (iframes.length > 0) return true;
                var cf = document.querySelector('.cf-turnstile, #turnstileContainer');
                if (cf && cf.offsetWidth > 0) return true;
                return false;
            })()
        ''', default=None)
    return None if result is None else bool(result)

def check_turnstile_done(sb) -> bool:
    return bool(safe_execute_script(sb, '''
            var cf = document.querySelector("input[name='cf-turnstile-response']");
            return cf && cf.value && cf.value.length > 20;
        ''', default=False))

def uc_click_with_timeout(sb, timeout: int = 20) -> bool:
    from selenium.webdriver.common.action_chains import ActionChains
    # Turnstile checkbox 在 closed Shadow DOM 中
    # 用 JS 取容器 bounding rect 算出 checkbox 屏幕坐标再点击
    try:
        rect = sb.execute_script('''
            var el = document.querySelector('#turnstile-container-renew');
            if (!el) return null;
            var r = el.getBoundingClientRect();
            return {left: r.left, top: r.top, w: r.width, h: r.height};
        ''')
        if rect and rect['w'] > 0:
            # Turnstile iframe: 300x65, 水平居中于容器
            # checkbox 距 iframe 左侧约 25px, 垂直居中
            cx = rect['left'] + rect['w'] / 2 - 150 + 25
            cy = rect['top'] + rect['h'] / 2
            # 先移到容器再偏移到精确坐标
            el = sb.find_element('#turnstile-container-renew', timeout=3)
            ActionChains(sb.driver).move_to_element(el).move_by_offset(cx - (rect['left'] + rect['w'] / 2), 0).click().perform()
            print(f"  [INFO] 精确坐标点击成功 ({int(cx)},{int(cy)})")
            return True
    except:
        pass
    try:
        el = sb.find_element('input[name="cf-turnstile-response"]', timeout=3)
        if el:
            ActionChains(sb.driver).move_to_element(el).click().perform()
            print(f"  [INFO] 隐藏 input 附近点击成功")
            return True
    except:
        pass
    try:
        el = sb.find_element('iframe[src*="turnstile"], iframe[src*="challenges"]', timeout=3)
        w, h = el.size["width"], el.size["height"]
        ActionChains(sb.driver).move_to_element_with_offset(el, w // 2, h // 3).click().perform()
        print(f"  [INFO] iframe 内点击成功")
        return True
    except:
        pass
    try:
        sb.uc_gui_click_captcha()
        print(f"  [INFO] 坐标点击成功")
        return True
    except:
        return False

def handle_social_prompt(sb, idx: int) -> bool:
    """处理登录后的社交媒体提示页面，点击 Continue 按钮跳过。"""
    try:
        current_url = sb.get_current_url()
        if "dash.zampto.net" not in current_url:
            return False

        has_continue = sb.execute_script('''
            (function() {
                var forms = document.querySelectorAll('form');
                for (var i = 0; i < forms.length; i++) {
                    var input = forms[i].querySelector(
                        'input[name="action"][value="continue_from_social_prompt"]'
                    );
                    if (input) {
                        var btn = forms[i].querySelector('button[type="submit"]');
                        if (btn) return true;
                    }
                }
                var btn = document.querySelector('button.continue-btn');
                if (btn && btn.textContent.trim() === 'Continue') return true;
                return false;
            })()
        ''')

        if not has_continue:
            return False

        print("  [INFO] 检测到社交媒体提示页面，点击 Continue...")
        safe_screenshot(sb, shot(idx, "social_prompt"))

        clicked = sb.execute_script('''
            (function() {
                var forms = document.querySelectorAll('form');
                for (var i = 0; i < forms.length; i++) {
                    var input = forms[i].querySelector(
                        'input[name="action"][value="continue_from_social_prompt"]'
                    );
                    if (input) {
                        var btn = forms[i].querySelector('button[type="submit"]');
                        if (btn) {
                            btn.click();
                            return "form_submit";
                        }
                        forms[i].submit();
                        return "form_direct";
                    }
                }
                var btn = document.querySelector('button.continue-btn');
                if (btn) {
                    btn.click();
                    return "class_click";
                }
                return "";
            })()
        ''')

        if clicked:
            print(f"  [INFO] 已点击 Continue 按钮 (方式: {clicked})")
            time.sleep(5)

            still_prompt = sb.execute_script('''
                var input = document.querySelector(
                    'input[name="action"][value="continue_from_social_prompt"]'
                );
                return !!input;
            ''')

            if not still_prompt:
                print("  [INFO] 已跳过社交媒体提示页面")
                return True
            else:
                print("  [WARN] 仍在社交媒体提示页面，尝试表单提交...")
                try:
                    sb.execute_script('''
                        var forms = document.querySelectorAll('form');
                        for (var i = 0; i < forms.length; i++) {
                            var input = forms[i].querySelector(
                                'input[name="action"][value="continue_from_social_prompt"]'
                            );
                            if (input) {
                                forms[i].submit();
                                break;
                            }
                        }
                    ''')
                    time.sleep(5)
                    print("  [INFO] 表单已提交")
                    return True
                except Exception as e:
                    print(f"  [WARN] 表单提交失败: {e}")
                    return False
        else:
            print("  [WARN] 未能点击 Continue 按钮")
            return False

    except Exception as e:
        print(f"  [WARN] 处理社交提示页面异常: {e}")
        return False

def _turnstile_container_gone(sb) -> Optional[bool]:
    """检查 Turnstile 弹窗是否已关闭: 容器 #turnstile-container-renew 不再 DOM 中"""
    return safe_execute_script(sb, '''
        return !document.querySelector('#turnstile-container-renew');
    ''', default=None)

def _turnstile_solved(sb) -> bool:
    """Turnstile 是否已通过: 仅检查 token 是否存在"""
    r = safe_execute_script(sb, '''
        var cf = document.querySelector("input[name='cf-turnstile-response']");
        if (cf && cf.value && cf.value.length > 20) return "token";
        return "no";
    ''', default="no")
    return r == "token"

def handle_turnstile(sb, idx: int, sid_f: str) -> bool:
    print("  [INFO] 等待 Turnstile 渲染...")
    # 等待加载动画结束, Turnstile widget 渲染完毕
    for _ in range(20):
        time.sleep(1)
        src = sb.get_page_source()
        if 'challenges.cloudflare.com' in src:
            print("  [INFO] Turnstile 已渲染")
            break
        spinner_gone = safe_execute_script(sb, '''
            var el = document.querySelector('#turnstile-container-renew');
            if (!el) return false;
            return el.innerHTML.indexOf("challenges.cloudflare") !== -1;
        ''', default=False)
        if spinner_gone:
            break
    else:
        print("  [WARN] Turnstile 渲染超时")

    dismiss_cookie_only(sb)

    if _turnstile_solved(sb):
        print("  [INFO] Turnstile 已完成")
        return True

    print("  [INFO] 处理 Turnstile 验证...")
    for attempt in range(3):
        print(f"  [INFO] 点击 Turnstile (第{attempt+1}次)")
        uc_click_with_timeout(sb, timeout=20)

        for _ in range(15):
            time.sleep(1)
            if _turnstile_solved(sb):
                print(f"  [INFO] Turnstile 通过 (第{attempt+1}次)")
                print("  [INFO] 等待弹窗关闭...")
                for _ in range(20):
                    time.sleep(1)
                    if _turnstile_container_gone(sb):
                        print("  [INFO] 弹窗已关闭")
                        return True
                print("  [WARN] 弹窗未自动关闭，继续")
                return True
            if _turnstile_container_gone(sb):
                print("  [INFO] 弹窗已关闭，续期已提交")
                return True

    print("  [WARN] Turnstile 超时")
    return False

def scroll_and_get_renewal_info(sb) -> Tuple[str, str]:
    for _ in range(8):
        try:
            sb.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        except: pass
        time.sleep(1)

        renewal_time, remain_time = "", ""
        try:
            renewal_time = sb.execute_script('''
                var els = document.querySelectorAll('.text-muted-foreground.break-all');
                for (var i = 0; i < els.length; i++) {
                    if (els[i].textContent.indexOf("Server last renewed") !== -1) {
                        var span = els[i].querySelector("span");
                        return span ? span.textContent.trim() : "";
                    }
                }
                return "";
            ''') or ""
            remain_time = sb.execute_script('''
                var els = document.querySelectorAll('.text-muted-foreground.break-all');
                for (var i = 0; i < els.length; i++) {
                    if (els[i].textContent.indexOf("Expiry") !== -1) {
                        var span = els[i].querySelector("span");
                        return span ? span.textContent.trim() : "";
                    }
                }
                return "";
            ''') or ""
        except: pass

        if renewal_time or remain_time:
            return renewal_time, remain_time

        src = sb.get_page_source()
        m = __import__('re').search(r'Server last renewed:[\s\S]*?<span[^>]*>([^<]+)', src)
        if m: renewal_time = m.group(1).strip()
        m = __import__('re').search(r'Expiry\s*\(Next Renewal\):[\s\S]*?<span[^>]*>([^<]+)', src)
        if m: remain_time = m.group(1).strip()
        if renewal_time or remain_time:
            return renewal_time, remain_time

    return "", ""

def login(sb, user: str, pwd: str, idx: int) -> Tuple[bool, Optional[str]]:
    print(f"\n{'─'*40}")
    print(f"  [INFO] 验证出口 IP...")
    try:
        proxies = proxy_requests_config()
        ip_info = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=10).json()
        print(f"  [INFO] 出口IP确认: {mask_ip(ip_info.get('ip', ''))}")
    except: pass

    print(f"\n{'─'*40}")
    print(f"  [INFO] 访问登录页...")
    last_shot = None

    for attempt in range(3):
        try:
            sb.uc_open_with_reconnect(AUTH_URL, reconnect_time=10)
            time.sleep(5)

            # 检测并处理 Cloudflare 整页挑战
            if is_cloudflare_interstitial(sb):
                if not bypass_cloudflare_interstitial(sb, idx):
                    last_shot = shot(idx, "cf_interstitial_failed")
                    safe_screenshot(sb, last_shot)
                    if attempt < 2:
                        continue
                    return False, last_shot
                # 挑战通过后，等待页面跳转到登录表单
                time.sleep(4)

            cur = sb.get_current_url()
            if "dash.zampto.net" in cur and "/auth/" not in cur:
                print("  [INFO] 已登录，跳转到仪表盘")
                handle_social_prompt(sb, idx)
                return True, None

            last_shot = shot(idx, f"login-{attempt}")
            safe_screenshot(sb, last_shot)

            print("  [INFO] 填写账号密码...")
            for _ in range(10):
                if "email" in sb.get_page_source(): break
                time.sleep(2)

            typed_user = False
            for sel in ['input#email', 'input[type="email"]', 'input[type="text"]']:
                try:
                    sb.wait_for_element(sel, timeout=5)
                    sb.type(sel, user)
                    typed_user = True
                    break
                except: continue

            if not typed_user:
                if attempt < 2: time.sleep(5); continue
                return False, last_shot

            typed_pwd = False
            for sel in ['input#password', 'input[type="password"]']:
                try:
                    sb.wait_for_element(sel, timeout=5)
                    sb.type(sel, pwd)
                    typed_pwd = True
                    break
                except: continue

            if not typed_pwd:
                print("  [WARN] 未能填写密码")
                if attempt < 2: time.sleep(5); continue
                return False, last_shot

            time.sleep(1)

            # 检测是否已有 Turnstile
            has_turnstile_before = sb.execute_script('''
                var frames = document.querySelectorAll('iframe');
                for (var i = 0; i < frames.length; i++) {
                    var src = frames[i].src || '';
                    if (src.indexOf('challenges.cloudflare') !== -1 ||
                        src.indexOf('turnstile') !== -1) {
                        return true;
                    }
                }
                return !!(document.querySelector('.cf-turnstile') ||
                          document.querySelector('[data-sitekey]') ||
                          document.querySelector('.jeFng_captchaBox'));
            ''')
            print(f"  [INFO] Turnstile 预检: {'存在' if has_turnstile_before else '未检测到'}")

            # 点击提交
            print("  [INFO] 点击登录...")
            try:
                sb.click('button[type="submit"]')
            except:
                try:
                    sb.execute_script("document.querySelector('button[type=\"submit\"]').click()")
                except:
                    pass

            # 增强的 Turnstile 等待与处理
            print("  [INFO] 等待 Turnstile 加载...")
            turnstile_appeared = False
            max_wait = 40  # 最多等 40 秒
            for i in range(max_wait):
                time.sleep(1)

                cur = sb.get_current_url()
                if "dash.zampto.net" in cur and "/auth/" not in cur:
                    print("  [INFO] 登录成功")
                    handle_social_prompt(sb, idx)
                    return True, None

                has_turnstile = sb.execute_script('''
                    // iframe 包含 challenges.cloudflare 或 turnstile
                    var frames = document.querySelectorAll('iframe');
                    for (var i = 0; i < frames.length; i++) {
                        var src = frames[i].src || '';
                        if (src.indexOf('challenges.cloudflare') !== -1 ||
                            src.indexOf('turnstile') !== -1) return true;
                    }
                    // 常见 Turnstile 选择器
                    if (document.querySelector('.cf-turnstile') ||
                        document.querySelector('[data-sitekey]') ||
                        document.querySelector('input[name="cf-turnstile-response"]')) {
                        return true;
                    }
                    // 页面文本提示（中英文以及 Loading 动画）
                    var bodyText = document.body ? document.body.innerText : '';
                    if (bodyText.indexOf('Please complete the security verification') !== -1 ||
                        bodyText.indexOf('确认您是真人') !== -1 ||
                        bodyText.indexOf('Verify you are human') !== -1 ||
                        bodyText.indexOf('Loading...') !== -1) {
                        return true;
                    }
                    return false;
                ''')
                if has_turnstile:
                    turnstile_appeared = True
                    print("  [INFO] Turnstile 已检测到")
                    break

            if turnstile_appeared:
                print("  [INFO] 处理登录页 Turnstile 验证...")
                time.sleep(3)

                # 检查是否已自动通过
                already_done = sb.execute_script('''
                    var cf = document.querySelector("input[name='cf-turnstile-response']");
                    return cf && cf.value && cf.value.length > 20;
                ''')
                if already_done:
                    print("  [INFO] Turnstile 已自动完成")
                else:
                    for t_attempt in range(4):
                        print(f"  [INFO] 点击 Turnstile (第{t_attempt+1}次)...")
                        uc_click_with_timeout(sb, timeout=25)
                        time.sleep(4)

                        cur = sb.get_current_url()
                        if "dash.zampto.net" in cur and "/auth/" not in cur:
                            print("  [INFO] 登录成功")
                            handle_social_prompt(sb, idx)
                            return True, None

                        done = sb.execute_script('''
                            var cf = document.querySelector("input[name='cf-turnstile-response']");
                            if (cf && cf.value && cf.value.length > 20) return true;
                            return false;
                        ''')
                        if done:
                            print(f"  [INFO] Turnstile 通过 (第{t_attempt+1}次)")
                            break
                        print("  [INFO] 等待 Turnstile 完成...")
                    else:
                        print("  [INFO] 等待 Turnstile 自动完成 (最多30s)...")
                        for _ in range(30):
                            cur = sb.get_current_url()
                            if "dash.zampto.net" in cur and "/auth/" not in cur:
                                print("  [INFO] 登录成功")
                                handle_social_prompt(sb, idx)
                                return True, None
                            done = sb.execute_script('''
                                var cf = document.querySelector("input[name='cf-turnstile-response']");
                                return cf && cf.value && cf.value.length > 20;
                            ''')
                            if done:
                                print("  [INFO] Turnstile 已完成")
                                break
                            time.sleep(1)

                # 关键：Turnstile 通过后重新提交登录表单
                print("  [INFO] Turnstile 已完成，重新点击登录...")
                try:
                    sb.click('button[type="submit"]')
                except:
                    try:
                        sb.execute_script("document.querySelector('button[type=\"submit\"]').click()")
                    except:
                        pass
            else:
                print("  [INFO] 未检测到 Turnstile，直接等待跳转...")

            print("  [INFO] 等待登录跳转...")
            time.sleep(8)

            last_shot = shot(idx, "login_result")
            safe_screenshot(sb, last_shot)

            cur = sb.get_current_url()
            if ("dash.zampto.net" in cur and "/auth/" not in cur) or ("sign-in" not in cur and "/auth/" not in cur):
                print("  [INFO] 登录成功")
                handle_social_prompt(sb, idx)
                return True, last_shot

        except Exception as e:
            print(f"  [WARN] 尝试 {attempt + 1} 异常: {e}")
            if attempt < 2: time.sleep(5)

    return False, last_shot

def logout(sb):
    try:
        sb.delete_all_cookies()
        sb.open("about:blank")
        time.sleep(1)
        print("  [INFO] 已退出登录")
    except: pass

def get_servers(sb, idx: int) -> Tuple[List[Dict[str, str]], str, Optional[str]]:
    servers = []

    sb.open("https://dash.zampto.net/servers")
    time.sleep(5)

    handle_social_prompt(sb, idx)
    time.sleep(2)

    inject_ad_guard(sb)
    dismiss_cookie_only(sb)

    screenshot = shot(idx, "dashboard")
    safe_screenshot(sb, screenshot)

    src = sb.get_page_source()
    if "Access Blocked" in src or "VPN or Proxy" in src:
        return [], "⚠️ 访问被阻止", screenshot

    try:
        data = sb.execute_script('''
            var cards = document.querySelectorAll('[data-slot="card"]');
            var result = [];
            for (var i = 0; i < cards.length; i++) {
                var card = cards[i];
                var badges = card.querySelectorAll('span');
                var isActive = false;
                for (var j = 0; j < badges.length; j++) {
                    if (badges[j].textContent.trim() === 'Active') {
                        isActive = true;
                        break;
                    }
                }
                if (!isActive) continue;
                var links = card.querySelectorAll('a[href*="/server?id="]');
                for (var j = 0; j < links.length; j++) {
                    var m = links[j].getAttribute('href').match(/\\/server\\?id=(\\d+)/);
                    if (m) {
                        var nameEl = card.querySelector('[data-slot="card-title"]');
                        var name = nameEl ? nameEl.textContent.trim() : m[1];
                        result.push({id: m[1], name: name});
                        break;
                    }
                }
            }
            return result;
        ''') or []

        if data:
            for srv in data:
                servers.append({"id": str(srv["id"]), "name": str(srv.get("name", srv["id"]))})
            print(f"  [INFO] 找到 {len(servers)} 个活跃服务器")
        else:
            print("  [WARN] 页面未找到活跃服务器")

    except Exception as e:
        print(f"  [WARN] 解析服务器页面失败: {e}，回退到正则匹配")

    if not servers:
        for sid in re.findall(r"/server\?id=(\d+)", src):
            servers.append({"id": sid})
        print(f"  [INFO] 正则回退找到 {len(servers)} 个服务器")

    if not servers:
        return [], "⚠️ 未找到服务器", screenshot

    return servers, "", screenshot

def renew(sb, sid: str, idx: int, username: str) -> Dict[str, Any]:
    result = {
        "server_id": sid, "success": False, "message": "", "screenshot": None,
        "old_expiry_cn": "", "new_expiry_cn": "", "expiry_info": "",
    }

    sid_m = mask_id(sid)
    sid_f = safe_sid_for_filename(sid)

    print(f"\n{'─'*40}")
    print(f"  [INFO] 续期: 服务器 (id={sid_m})")
    print(f"{'─'*40}")
    print(f"  [INFO] 访问: https://dash.zampto.net/server?id={sid_m}")

    sb.open(SERVER_URL.format(sid))
    time.sleep(4)

    handle_social_prompt(sb, idx)
    time.sleep(2)

    inject_ad_guard(sb)
    dismiss_cookie_only(sb)

    if "Access Blocked" in sb.get_page_source():
        result["message"] = "访问被阻止"
        result["expiry_info"] = "访问被阻止"
        notify(False, username, sid, result["expiry_info"])
        return result

    loaded_shot = shot(idx, f"server_{sid_f}_loaded")
    safe_screenshot(sb, loaded_shot)

    old_renewal, old_remain = scroll_and_get_renewal_info(sb)
    old_expiry_cn = calc_expiry_time(old_renewal)
    old_dt = parse_renewal_datetime(old_renewal)
    result["old_expiry_cn"] = old_expiry_cn
    print(f"  [INFO] 当前剩余时间: {old_remain}")

    print("  [INFO] 查找续期按钮...")
    try:
        clicked = sb.execute_script(f'''
            (function() {{
                var links = document.querySelectorAll('a[onclick*="handleServerRenewal"]');
                for (var i = 0; i < links.length; i++) {{
                    if (links[i].getAttribute('onclick').includes('{sid}')) {{
                        links[i].click();
                        return "handleServerRenewal";
                    }}
                }}
                var btns = document.querySelectorAll('a.action-button, button, a');
                for (var i = 0; i < btns.length; i++) {{
                    var text = btns[i].textContent.trim();
                    if (text.includes('Renew') && !text.includes('Last') && !text.includes('Next')) {{
                        btns[i].click();
                        return "span:" + text;
                    }}
                }}
                return "";
            }})()
        ''')

        if not clicked:
            result["message"] = "未找到续期按钮"
            result["expiry_info"] = f"未找到按钮 | {old_remain}"
            safe_screenshot(sb, shot(idx, f"server_{sid_f}_nobtn"))
            notify(False, username, sid, result["expiry_info"])
            return result

        print(f"  [INFO] 已点击续期按钮 (方式: {clicked})")
    except Exception as e:
        result["message"] = f"点击失败: {e}"
        return result

    time.sleep(2)
    after_click_shot = shot(idx, f"server_{sid_f}_after_click")
    safe_screenshot(sb, after_click_shot)

    has_shield = "none"
    for _ in range(20):
        time.sleep(1)
        container = safe_execute_script(sb, '''
            var el = document.querySelector('#turnstile-container-renew');
            if (!el) return "loading";
            var html = el.innerHTML || "";
            if (html.indexOf("challenges.cloudflare") !== -1 || html.indexOf("cf-turnstile") !== -1) return "present";
            var ts = document.querySelector('input[name="cf-turnstile-response"]');
            if (ts && ts.value && ts.value.length > 20) return "done";
            return "loading";
        ''', default="loading")
        if container != "loading":
            has_shield = container
            break
        src = sb.get_page_source()
        if 'challenges.cloudflare.com' in src or 'cf-turnstile' in src or 'data-sitekey' in src:
            has_shield = "present"
            break

    if has_shield == "present":
        print("  [INFO] 检测到 Turnstile，执行过盾...")
        time.sleep(2)
        if not handle_turnstile(sb, idx, sid_f):
            result["message"] = "Turnstile 处理超时或状态未知"
            result["expiry_info"] = f"{old_remain} (未确认)"
            notify(False, username, sid, result["expiry_info"])
            return result
    elif has_shield == "done":
        print("  [INFO] Turnstile 已完成，续期已提交")
    else:
        print("  [INFO] 未检测到 Turnstile（无盾），等待续期完成...")

    time.sleep(5)

    result_shot = shot(idx, f"server_{sid_f}_result")
    safe_screenshot(sb, result_shot)
    result["screenshot"] = result_shot

    print("  [INFO] 刷新页面确认续期时间...")
    sb.open(SERVER_URL.format(sid))
    time.sleep(4)

    handle_social_prompt(sb, idx)
    time.sleep(2)

    inject_ad_guard(sb)
    dismiss_cookie_only(sb)

    new_renewal, new_remain = scroll_and_get_renewal_info(sb)
    new_expiry_cn = calc_expiry_time(new_renewal)
    new_dt = parse_renewal_datetime(new_renewal)
    result["new_expiry_cn"] = new_expiry_cn
    print(f"  [INFO] 续期后剩余时间: {new_remain}")

    final_shot = shot(idx, f"server_{sid_f}_final")
    safe_screenshot(sb, final_shot)
    result["screenshot"] = final_shot

    renewed = False
    if new_remain and old_remain and new_remain != old_remain:
        renewed = True

    if renewed:
        result["success"] = True
        result["expiry_info"] = f"{old_remain} -> {new_remain}"
        result["message"] = "续期成功"
    else:
        result["success"] = False
        result["expiry_info"] = old_remain
        result["message"] = "续期失败：时间未变化"

    notify(result["success"], username, sid, result["expiry_info"], final_shot)
    print(f"  {'[INFO]' if result['success'] else '[ERROR]'} {result['message']}")
    return result

def process(sb, user: str, pwd: str, idx: int) -> Dict[str, Any]:
    result = {"username": user, "success": False, "message": "", "servers": []}

    login_ok, login_shot = login(sb, user, pwd, idx)
    if not login_ok:
        result["message"] = "登录失败"
        notify_login_fail(user, login_shot)
        return result

    servers, error, dash_shot = get_servers(sb, idx)
    if error:
        result["message"] = error
        notify_login_fail(user, dash_shot)
        logout(sb)
        return result

    print(f"\n  [INFO] 找到 {len(servers)} 个活跃服务器")
    for s in servers:
        print(f"    - ID: {mask_id(s['id'])}")

    for srv in servers:
        r = renew(sb, srv["id"], idx, user)
        result["servers"].append(r)
        time.sleep(3)

    ok = sum(1 for s in result["servers"] if s.get("success"))
    result["success"] = ok > 0
    result["message"] = f"{ok}/{len(result['servers'])} 成功"

    logout(sb)
    return result

def main():
    acc_str = os.environ.get("ZAMPTO_ACCOUNT", "")
    if not acc_str:
        print("[ERROR] 缺少 ZAMPTO_ACCOUNT"); sys.exit(1)

    accounts = parse_accounts(acc_str)
    if not accounts:
        print("[ERROR] 无有效账号"); sys.exit(1)

    print("=" * 40)
    print("  Zampto Auto Renew")
    print("=" * 40)

    proxy = os.environ.get("ZAMPTO_PROXY_NODE", "").strip() or os.environ.get("PROXY_URL", "").strip() or os.environ.get("PROXY_SERVER", "").strip()
    if proxy:
        try:
            ip = requests.get("https://api.ipify.org", proxies=proxy_requests_config(), timeout=10).text.strip()
            print(f"[INFO] 代理连接正常，出口IP: {mask_ip(ip)}")
        except Exception as e:
            print(f"[WARN] 代理测试失败: {e}")

    display = setup_display()
    results = []

    try:
        try:
            import nest_asyncio
            nest_asyncio.apply()
            print("[INFO] nest_asyncio 已应用")
        except ImportError:
            pass

        opts = {"uc": True, "test": True, "locale": "en", "headed": not is_linux()}
        if proxy:
            opts["proxy"] = proxy
            print("[INFO] 使用代理")

        with SB(**opts) as sb:
            for i, (u, p) in enumerate(accounts, 1):
                r = process(sb, u, p, i)
                results.append(r)

    except Exception as e:
        print(f"[ERROR] 脚本异常: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        if display:
            display.stop()

    ok_acc = sum(1 for r in results if r.get("success"))
    total_srv = sum(len(r.get("servers", [])) for r in results)
    ok_srv = sum(sum(1 for s in r.get("servers", []) if s.get("success")) for r in results)

    print(f"\n{'='*40}")
    print(f"[INFO] 账号: {ok_acc}/{len(results)} | 服务器: {ok_srv}/{total_srv}")
    for r in results:
        status = "[INFO]" if r.get("success") else "[ERROR]"
        print(f"{status} {mask(r['username'])}: {r.get('message', '')}")
        for s in r.get("servers", []):
            s_status = "[INFO]" if s.get("success") else "[ERROR]"
            print(f"  {s_status} {mask_id(s['server_id'])}: {s.get('message', '')}")
    print(f"{'='*40}")

    sys.exit(0 if ok_srv > 0 else 1)

if __name__ == "__main__":
    main()
