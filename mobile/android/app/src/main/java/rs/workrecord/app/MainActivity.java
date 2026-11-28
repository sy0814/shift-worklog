package rs.workrecord.app;

import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.WebView;
import android.widget.Toast;

import androidx.activity.OnBackPressedCallback;

import com.getcapacitor.BridgeActivity;

/**
 * App 外壳：本地页面填服务器地址后打开服务器上的系统网页（证书已打包，见 res/xml/network_security_config.xml）。
 * 网页里的下载（例如新版本安装包 http://服务器/app.apk、导出的 Excel）交给手机浏览器 / 系统去下载，WebView 自己不会下载。
 * 返回键 / 返回手势：网页能后退就后退（网页里打开弹窗时压了一条历史，后退 = 关弹窗，见 frontend/src/backClose.js）；
 * 退到头了要 2 秒内再按一次才回桌面。没有装 @capacitor/app 时 Capacitor 不管返回键，Android 默认直接关掉 App。
 */
public class MainActivity extends BridgeActivity {
    private long lastBack = 0;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                WebView web = getBridge() != null ? getBridge().getWebView() : null;
                if (web != null && web.canGoBack()) {
                    web.goBack();
                    return;
                }
                long now = System.currentTimeMillis();
                if (now - lastBack < 2000) {
                    finish();
                } else {
                    lastBack = now;
                    Toast.makeText(MainActivity.this, R.string.press_back_again, Toast.LENGTH_SHORT).show();
                }
            }
        });
        getBridge().getWebView().setDownloadListener((url, userAgent, contentDisposition, mimetype, contentLength) -> {
            try {
                // 新版本安装包：手机浏览器不认这个证书，改走 HTTP（服务器 80 端口提供 /app.apk）
                if (url.startsWith("https://") && Uri.parse(url).getPath() != null && Uri.parse(url).getPath().endsWith("/app.apk")) {
                    url = "http://" + url.substring("https://".length());
                }
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
            } catch (Exception ignored) {
                // 没有能打开链接的应用：什么都不做
            }
        });
    }
}
