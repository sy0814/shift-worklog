# 安卓 App（Capacitor 外壳）

App 只是一个外壳：第一次打开填服务器地址，然后显示服务器上的系统网页（和浏览器里是同一套）。
**网页功能更新不用重新装 App**，服务器 `update.ps1 -Online` 以后手机上下次打开就是新的。

## 为什么要 App
服务器用 Caddy 内部证书机构签 HTTPS 证书，浏览器要先装根证书；有人怕不安全不肯装。
App 把**这台服务器的根证书**打包在里面（`res/xml/network_security_config.xml` 信任 `@raw/workrecord_ca`），装了就能用。

## 目录
| 路径 | 内容 |
|---|---|
| `www/index.html` | 填服务器地址（存在 App 本地，三语跟着手机语言）；填过就直接打开 `https://地址/` |
| `www/error.html` | 打不开服务器时显示（Capacitor `errorPath`）：重试 / 改地址 |
| `ca/workrecord-ca.crt` | **服务器的根证书**（`http://服务器/ca.crt` 下载的那个，公开的，不是秘密）。打包时复制到 `res/raw/workrecord_ca.crt` |
| `capacitor.config.json` | `allowNavigation: ["*"]`（地址是用户填的）；`appendUserAgent` 打包时改成 `WorkRecordApp/版本号` |
| `android/` | `npx cap add android` 生成后改过：图标、三语名称（`values-zh` / `values-sr` …）、证书配置、`MainActivity`（下载交给手机浏览器，`/app.apk` 改走 HTTP；返回键：网页能后退就后退，退到头 2 秒内再按一次才退出）、版本号和签名（`app/build.gradle`） |
| 签名钥匙 | **不在仓库里**。GitHub 仓库 → Settings → Secrets and variables → Actions 里的 `ANDROID_KEYSTORE_BASE64`（钥匙文件的 base64）和 `KEYSTORE_PASSWORD`，打包时临时写成 `android/app/release.keystore`。**同一把钥匙签的新版本才能覆盖安装，钥匙文件要另外保存好，不要换**。没设这两个 Secret 时只做编译检查、不发布 |

## 打包和发布
`.github/workflows/android.yml`：PR 里改了 `mobile/` 会打包检查；合并到 master 后打包并发布到 Release **android-latest**（`workrecord.apk` + `version.txt`）。
服务器 `update.ps1 -Online` / `install.ps1` 调 `Update-MobileApk`（`deploy/windows/common.ps1`）下载到 `C:\WorkRecord\data\app\`，
手机浏览器打开 `http://服务器地址/app.apk` 下载（Caddy 80 端口转给程序，`backend/app/main.py` 的 `/app.apk`）。

**要让手机提示更新 App**：改了 `mobile/` 以后把 `package.json` 的 `version` 加一（例如 1.0.0 → 1.0.1）。
网页从 User-Agent 读 App 版本，和 `/api/app-info`（服务器上 `version.txt`）不一样就提示下载（`frontend/src/nativeApp.js`、`views/Layout.vue`）。

什么时候需要新 App：服务器根证书变了（重装服务器又没按备份恢复证书 → 把新的 `ca.crt` 放到 `ca/workrecord-ca.crt`）、
要加推送 / 扫码这类手机原生功能、改图标或名称。

## 已知限制
- 只有安卓（iPhone 要苹果开发者账号签名）。
- 网页里用 JavaScript 生成的下载（导出 Excel、下载出勤月表）在 App 里不会下载，到电脑上做。
- 这个容器连不上 Google 的安卓 SDK 下载源，不能在本地打包，靠 GitHub Actions。
