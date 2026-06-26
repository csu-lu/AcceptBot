import requests

def send_wechat(send_key, title, content, log_callback=None):
    """
    通过Server酱发送微信通知
    :param send_key: Server酱的SendKey
    :param title: 消息标题
    :param content: 消息内容
    :param log_callback: 用于GUI显示日志的回调函数 (接受字符串参数)
    """
    if not send_key:
        if log_callback:
            log_callback("发送失败：未配置 SendKey")
        return False

    url = f"https://sctapi.ftqq.com/{send_key}.send"
    data = {
        "title": title,
        "desp": content
    }
    
    try:
        # 添加 proxies={"http": None, "https": None} 强制绕过系统 VPN 代理
        # 因为 Server酱 是国内服务，走国外 VPN 节点常常会超时被拦截
        response = requests.post(url, data=data, timeout=10, proxies={"http": None, "https": None})
        response.raise_for_status()
        result = response.json()
        
        # Server酱 API v2 返回码 0 表示成功
        if result.get('code') == 0:
            if log_callback:
                log_callback(f"微信通知已发送: {title}")
            return True
        else:
            if log_callback:
                log_callback(f"微信通知发送失败: {result.get('message', '未知错误')}")
            return False
            
    except Exception as e:
        if log_callback:
            log_callback(f"微信通知发送异常: {str(e)}")
        return False
