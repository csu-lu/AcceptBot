import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

def fetch_current_status(url, username, password, log_callback=None):
    """
    使用 Playwright 抓取稿件状态
    针对 Editorial Manager (EM) 和 ScholarOne 进行了专门定制
    """
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(f"[Spider] {msg}")

    if not url or not username or not password:
        log("错误：URL、账号或密码未配置！")
        return None

    with sync_playwright() as p:
        try:
            # 尝试使用 Chrome 浏览器打开，并禁用系统自带的翻译弹窗（防止遮挡操作）
            browser = p.chromium.launch(
                channel="chrome", 
                headless=False,
                args=["--disable-translate", "--disable-features=TranslateUI"]
            )
            log("已启动系统自带的 Chrome 浏览器核心 (可见模式)")
        except Exception:
            log("未找到系统 Chrome，正在使用默认 Chromium 核心 (可见模式)...")
            browser = p.chromium.launch(
                headless=False,
                args=["--disable-translate", "--disable-features=TranslateUI"]
            )
            
        context = browser.new_context()
        page = context.new_page()
        
        # --- 定义一个清理 Cookie 的核弹级函数，随时调用 ---
        def nuke_cookie_banner():
            try:
                # 首先尝试常规点击
                cookie_btn = page.locator("#onetrust-accept-btn-handler, button:has-text('Accept Cookies'), button:has-text('Accept All'), button:has-text('接受Cookies'), a:has-text('接受Cookies')")
                if cookie_btn.count() > 0:
                    cookie_btn.first.click(force=True)
                    page.wait_for_timeout(500)
                
                # 在浏览器内部注入一个永不停歇的清洁工：每 500 毫秒巡逻一次，谁敢弹窗就杀谁
                page.evaluate("""
                    function clearBanners() {
                        const ot = document.getElementById('onetrust-consent-sdk');
                        if (ot) ot.remove();
                        const translate = document.getElementById('skiptranslate');
                        if (translate) translate.remove();
                        document.querySelectorAll('iframe').forEach(f => {
                            try {
                                const ot_inner = f.contentDocument.getElementById('onetrust-consent-sdk');
                                if (ot_inner) ot_inner.remove();
                            } catch(e) {}
                        });
                    }
                    clearBanners();
                    if (!window.bannerNukerInterval) {
                        window.bannerNukerInterval = setInterval(clearBanners, 500);
                    }
                """)
            except Exception:
                pass

        try:
            log(f"正在访问页面: {url}")
            page.goto(url, timeout=60000)
            
            nuke_cookie_banner()
            log("已执行初始网页的 Cookie 遮罩层与翻译弹窗清理。")
            
            # --- 1. 自动登录逻辑 ---
            # 找到输入框并填充 (针对 EM 和 S1 进行差异化定位)
            try:
                log("正在等待账号密码输入框加载...")
                # 优先寻找 ScholarOne 的输入框
                page.locator("input[name*='USERID'], input[name*='USERNAME'], #username").first.wait_for(timeout=5000)
                page.locator("input[name*='USERID'], input[name*='USERNAME'], #username").first.fill(username)
                page.locator("input[name*='PASSWORD'], #password").first.fill(password)
                
                if page.locator("button#logInButton").count() > 0:
                    page.locator("button#logInButton").click(force=True)
                else:
                    page.locator("input[type='submit'], button[type='submit']").first.click(force=True)
            except PlaywrightTimeoutError:
                try:
                    # 兼容 Editorial Manager (经过深度 DOM 分析)
                    frame_content = page.frame_locator("iframe[name='content'], iframe#content")
                    frame_login = page.frame_locator("iframe[name='login'], iframe#login, iframe[src*='login.asp']")
                    
                    target_frame = None
                    
                    def find_and_fill_em():
                        nonlocal target_frame
                        try:
                            frame_login.locator("#username").first.wait_for(timeout=3000)
                            target_frame = frame_login
                        except:
                            try:
                                frame_content.locator("#username").first.wait_for(timeout=3000)
                                target_frame = frame_content
                            except:
                                pass
                        
                        if not target_frame:
                            if page.locator("a#Login, #Login").count() > 0:
                                log("检测到 EM 登录入口，正在点击 Login...")
                                page.locator("a#Login, #Login").first.click(force=True)
                                page.wait_for_timeout(3000)
                            
                            try:
                                frame_content.locator("#username").first.wait_for(timeout=5000)
                                target_frame = frame_content
                            except:
                                try:
                                    frame_login.locator("#username").first.wait_for(timeout=5000)
                                    target_frame = frame_login
                                except:
                                    pass
                                
                        if target_frame:
                            log("成功在 iframe 中找到 EM 登录框！")
                            target_frame.locator("#username").first.fill(username)
                            target_frame.locator("#passwordTextbox").first.fill(password)
                            
                            if target_frame.locator("input[value='Author Login']").count() > 0:
                                target_frame.locator("input[value='Author Login']").first.click(force=True)
                            else:
                                target_frame.locator("button[type='submit'], input[type='submit']").first.click(force=True)
                            return True
                        return False

                    # 第一次尝试
                    success = False
                    try:
                        success = find_and_fill_em()
                    except Exception:
                        pass
                        
                    # 发现被挡住/失败后，执行强制清理重试机制
                    if not success:
                        log("常规登录定位失败或超时，疑似被延迟加载的遮罩挡住。激活强制清理并重试...")
                        nuke_cookie_banner()
                        page.wait_for_timeout(2000)
                        
                        # 强行再点一次主页的 Login（如果之前因为遮挡没点上的话）
                        if page.locator("a#Login, #Login").count() > 0:
                            page.locator("a#Login, #Login").first.click(force=True)
                            page.wait_for_timeout(3000)
                            
                        success = find_and_fill_em()
                        
                    if not success:
                        raise PlaywrightTimeoutError("EM login boxes not found even after retry.")
                except PlaywrightTimeoutError:
                    log("常规登录框统统未找到，可能页面加载极慢或者结构发生巨变，尝试最后暴力填充...")
                    if page.locator("input[type='text'], input[type='email']").count() > 0:
                        page.locator("input[type='text'], input[type='email']").first.fill(username)
                        page.locator("input[type='password']").first.fill(password)
                        page.keyboard.press("Enter")
                    else:
                        log("无法找到任何账号密码输入框！")
                        return None
                
            log("登录已提交，等待页面加载...")
            try:
                # 尽量等 networkidle，但最多等 10 秒。EM 经常有后台长连接，不能死等
                page.wait_for_load_state('networkidle', timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(3000) # 额外等待页面 JS 渲染
            
            # --- 登录成功后，再次爆发核弹清理 Cookie 弹窗 ---
            nuke_cookie_banner()
            log("已执行登录后的二次 Cookie 遮罩层清理。")

            # --- 2. 根据网址自动选择抓取策略 ---
            if "editorialmanager.com" in url.lower():
                log("识别为 Editorial Manager 系统，进入专属抓取逻辑...")
                
                # 再次强调，登录后的内容同样在 iframe 里
                frame = page.frame_locator("iframe[name='content'], iframe#content")

                # 点击 Submissions Being Processed (使用 JS 原生点击，最强穿透)
                try:
                    target_link = frame.locator("a:has-text('Submissions Being Processed')").first
                    target_link.wait_for(timeout=10000)
                    target_link.evaluate("node => node.click()")
                    try:
                        page.wait_for_load_state('networkidle', timeout=10000)
                    except Exception:
                        pass
                    page.wait_for_timeout(3000)
                except Exception as e:
                    log("首次点击 Submissions Being Processed 失败或被拦截，执行强制清理后重试...")
                    nuke_cookie_banner()
                    page.wait_for_timeout(2000)
                    try:
                        target_link = frame.locator("a:has-text('Submissions Being Processed')").first
                        target_link.wait_for(timeout=5000)
                        target_link.evaluate("node => node.click()")
                        try:
                            page.wait_for_load_state('networkidle', timeout=10000)
                        except Exception:
                            pass
                        page.wait_for_timeout(3000)
                    except Exception as e2:
                        log(f"重试点击 Submissions Being Processed 依然失败...({e2})")
                    
                # 寻找表头含有 'Current Status' 的表格
                table = frame.locator("table:has(th:has-text('Current Status'))").first
                
                # 因为没法直接用 if table.count() 判断（frame locator 没有直接计算数目的好办法，这里用 text 内容）
                try:
                    # 找到包含 Action Links 的那一行稿件数据
                    row = table.locator("tr:has-text('Action Links')").first
                    row.wait_for(timeout=10000) # 确认行存在
                    status_text = row.inner_text()
                    # 清理多余换行符，将整行数据拼成一句话（包含日期和状态）
                    status_text = " | ".join([s.strip() for s in status_text.split('\n') if s.strip()])
                    log(f"成功获取 EM 稿件状态。")
                    return status_text
                except Exception:
                    log("未能准确定位 EM 状态表格，尝试返回网页摘要。")
                    try:
                        return frame.locator("body").inner_text()[:200]
                    except:
                        return page.locator("body").inner_text()[:200]
                
            elif "manuscriptcentral.com" in url.lower():
                log("识别为 ScholarOne 系统，进入专属抓取逻辑...")
                
                # 必须点击 Author 标签
                if page.locator("a:has-text('Author'), span:has-text('Author')").count() > 0:
                    page.locator("a:has-text('Author'), span:has-text('Author')").first.click()
                    page.wait_for_load_state('networkidle', timeout=30000)
                    page.wait_for_timeout(2000)
                    
                # 点击 Submitted Manuscripts (有时候在左侧栏)
                if page.locator("a:has-text('Submitted Manuscripts')").count() > 0:
                    page.locator("a:has-text('Submitted Manuscripts')").first.click()
                    page.wait_for_load_state('networkidle', timeout=30000)
                    page.wait_for_timeout(2000)
                    
                # 寻找包含 STATUS 列的表格
                table = page.locator("table:has(th:has-text('STATUS'))").first
                if table.count() > 0:
                    # 获取表体的第一行数据 (跳过表头)
                    row = table.locator("tbody tr").first
                    if row.count() > 0:
                        status_text = row.inner_text()
                        status_text = " | ".join([s.strip() for s in status_text.split('\n') if s.strip()])
                        log(f"成功获取 ScholarOne 稿件状态。")
                        return status_text
                
                log("未能准确定位 ScholarOne 状态表格，尝试返回网页摘要。")
                return page.locator("body").inner_text()[:200]

            else:
                log("未识别的系统域名，尝试直接返回正文摘要...")
                return page.locator("body").inner_text()[:200]
            
        except PlaywrightTimeoutError:
            log("页面加载或元素查找超时！请检查网络或配置的链接是否正确。")
            return None
        except Exception as e:
            log(f"抓取过程发生异常: {str(e)}")
            return None
        finally:
            browser.close()

if __name__ == "__main__":
    from data_manager import load_config
    config = load_config()
    print("===== 开始独立测试网页抓取模块 =====")
    
    test_url = input(f"请输入测试期刊的URL (按回车使用默认: {config.get('url')}): ") or config.get("url")
    test_user = input(f"请输入测试账号 (按回车使用默认: {config.get('username')}): ") or config.get("username")
    test_pwd = input(f"请输入测试密码 (按回车使用默认: {config.get('password')}): ") or config.get("password")
    
    status = fetch_current_status(test_url, test_user, test_pwd)
    print(f"\n>>>>> 最终获取的测试状态结果:\n{status}")
