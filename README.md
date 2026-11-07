# PWM Fan Driver + Web Monitor

> 原作者arounyf的PWM-fan项目，专为 **OEC-Turbo (RK3566)** 适配的 GPIO PWM 风扇驱动，本fork项目对DSM7进行了部分适配，可通过web来读取监控CPU、硬盘的温度，并读取风扇转速（内核gpio原因无法进行调速）。


## 硬件接线

| 风扇线 | 颜色 | 接法 |
|--------|------|------|
| GND | 黑 | 外部 12V 电源 GND |
| 12V | 黄/红 | 外部 12V 电源正极 |
| TACH | 绿/黄 | RX (转速读取) |

## 部署步骤

```bash
# 1. 安装依赖
①在套件中心安装python3.9
②SSH连接到DSM的shell，然后执行以下命令：
  sudo -i（然后输入登录用户的密码）
  cd /tmp
  curl -sS https://bootstrap.pypa.io/pip/3.9/get-pip.py -o get-pip.py
  python3.9 get-pip.py
  python3.9 -m pip install gpiod

# 2. 复制文件
mkdir -p /opt/pwm-fan
cp fan_driver.py web_server.py /opt/pwm-fan/
chmod +x /opt/pwm-fan/*.py

# 3. 安装服务
cp pwm-fan.service pwm-fan-web.service /usr/lib/systemd/system/
systemctl daemon-reload
systemctl enable pwm-fan.service
systemctl start pwm-fan.service
systemctl enable pwm-fan-web.service
systemctl start pwm-fan-web.service

# 4. 验证
cat /tmp/pwm-fan-status.json
curl http://127.0.0.1:8081
```

## Web 访问

`http://<机器IP>:8081`

--------------------------------------------以下是原作者的内容----------------------------------------------
- **Auto 模式**：≤35°C 风扇停转，35~65°C 线性调速，≥65°C 全速
- **Manual 模式**：滑块 0%~100%，支持 OFF/25/50/75/100% 快捷按钮

## 配置

编辑 `fan_driver.py` 顶部常量：

| 参数 | 说明 |
|------|------|
| PWM_CHIP | PWM 控制 gpiochip |
| PWM_PIN | PWM 控制引脚 |
| TACH_CHIP | 转速反馈 gpiochip |
| TACH_PIN | 转速反馈引脚 |
| PWM_FREQ | PWM 频率 (Hz) |
| TEMP_MIN | 风扇起转温度 (毫度) |
| TEMP_MAX | 风扇全速温度 (毫度) |
| DUTY_MIN | 最低占空比 (%) |

## 文件说明

| 文件 | 作用 |
|------|------|
| fan_driver.py | 主驱动，PWM 输出 + 温度读取 + 转速反馈 |
| web_server.py | Web 监控控制页面 |
| pwm-fan.service | 驱动 systemd 服务 |
| pwm-fan-web.service | Web systemd 服务 |
| install.sh | 一键安装脚本 (需 root) |
| LICENSE | GPL v3 开源协议 |
